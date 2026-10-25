"""
Модуль извлечения текста из PDF-лекций.

Реализует этап "парсинг документов" из архитектуры проекта.
Использует pdfplumber — покрывает "цифровые" PDF с текстовым слоем
(презентации и лекции, экспортированные из PowerPoint/Word/LaTeX).

Извлечение — обычным extract_text(), БЕЗ layout=True. Изначально
закладывался layout=True для сохранения порядка текста в многоколоночных
макетах, но на реальном тестировании на лекциях ИМЭС (PDF из PowerPoint)
выяснилось, что он забивает результат пробелами: текст разбросан по
отдельным блокам в разных местах слайда, и layout=True пытается сохранить
их визуальные позиции пробелами, а не текстом (на одном реальном слайде —
495 символов текста без layout против 4793 с ним, почти сплошные пробелы).
Это ломало и подсчёт likely_scanned, и группировку в чанки.

Триггеры для смены подхода (задокументировано осознанно, чтобы не
переусложнять код заранее — см. README проекта):
  - Если на реальных материалах преподавателей ИМЭС появятся сканы
    без текстового слоя (см. флаг likely_scanned) — подключить OCR
    (pytesseract + pdf2image) как отдельный fallback-модуль.
  - Если появятся настоящие многоколоночные макеты (не PowerPoint,
    а, например, PDF научных статей), где порядок текста без layout
    "плывёт" — рассмотреть layout=True именно для таких файлов отдельно,
    не как общий дефолт (см. находку выше, почему не по умолчанию).
"""
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# Ниже какого количества символов "чистого" текста считаем страницу
# подозрительной на скан/отсутствие текстового слоя.
MIN_CHARS_PER_PAGE = 20


# Допуск по вертикали (в пунктах PDF), в пределах которого слова считаются
# одной строкой при сборке текста с метками оформления.
_LINE_TOLERANCE = 3.0


def _is_bold_font(fontname: str | None) -> bool:
    return bool(fontname) and "bold" in fontname.lower()


def _is_coloured(color) -> bool:
    """Заметно «цветной» (не чёрный/серый/белый) шрифт — только для RGB-цвета."""
    if isinstance(color, (tuple, list)) and len(color) == 3:
        return (max(color) - min(color)) > 0.25
    return False


def _page_text_with_emphasis(page) -> tuple[str, bool]:
    """
    Текст страницы, где жирные и цветные слова обёрнуты метками **…** и {~…~}.

    Возвращает (текст, были_ли_метки). Если выделений на странице нет, вызывающий
    код использует обычный extract_text(): он лучше держит порядок текста, и
    нет смысла рисковать им ради страницы без выделений.

    Подчёркивание и выделение маркером в PDF — отдельные нарисованные линии
    и прямоугольники, а не свойства букв, поэтому здесь не распознаются.
    """
    words = page.extract_words(extra_attrs=["fontname", "non_stroking_color"])
    if not words:
        return "", False

    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[list[dict]] = []
    for word in words:
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= _LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])

    found = False
    out_lines: list[str] = []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        pieces: list[tuple[tuple[bool, bool], list[str]]] = []
        for w in line:
            flags = (_is_bold_font(w.get("fontname")), _is_coloured(w.get("non_stroking_color")))
            if pieces and pieces[-1][0] == flags:
                pieces[-1][1].append(w["text"])
            else:
                pieces.append((flags, [w["text"]]))
        rendered: list[str] = []
        for (bold, coloured), texts in pieces:
            chunk = " ".join(texts)
            if bold:
                chunk = f"**{chunk}**"
                found = True
            if coloured:
                chunk = f"{{~{chunk}~}}"
                found = True
            rendered.append(chunk)
        out_lines.append(" ".join(rendered))
    return "\n".join(out_lines), found


@dataclass
class PageContent:
    """Извлечённый текст одной страницы PDF."""

    page_number: int  # нумерация с 1, как в самом PDF
    text: str  # извлечённый текст, без постобработки
    char_count: int  # длина text.strip()
    likely_scanned: bool  # True — вероятно скан, нужен OCR (пока не реализован)


@dataclass
class ParsedDocument:
    """Результат парсинга всего PDF-файла."""

    source_path: str
    pages: list[PageContent] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Весь текст документа одной строкой, страницы разделены пустой строкой."""
        return "\n\n".join(p.text.strip() for p in self.pages if p.text.strip())

    @property
    def has_scanned_pages(self) -> bool:
        """True, если хотя бы одна страница похожа на скан без текстового слоя."""
        return any(p.likely_scanned for p in self.pages)


def parse_pdf(file_path: str | Path, mark_emphasis: bool = False) -> ParsedDocument:
    """
    Извлекает текст из PDF постранично.

    Args:
        file_path: путь к PDF-файлу лекции.
        mark_emphasis: помечать жирные и цветные слова метками **…** и {~…~}
            (нужно для файлов с вопросами, где верный ответ выделен
            оформлением). Для лекций выключено.

    Returns:
        ParsedDocument со списком страниц и их текстом.

    Raises:
        FileNotFoundError: если файл не найден.
        ValueError: если файл не удалось открыть или прочитать как PDF.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    pages: list[PageContent] = []

    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                # ВАЖНО: без layout=True. Изначально казалось разумным включить
                # layout=True для сохранения порядка текста в многоколоночных
                # документах — но на реальных лекциях ИМЭС (PDF из PowerPoint,
                # где текст разбросан по отдельным блокам в разных местах слайда)
                # это давало огромное количество пробелов вместо текста: на одном
                # реальном слайде — 495 символов текста без layout против 4793
                # символов (почти сплошные пробелы) с layout=True. Ломало и подсчёт
                # длины для likely_scanned, и группировку в чанки.
                raw_text = page.extract_text() or ""
                if mark_emphasis:
                    marked_text, has_marks = _page_text_with_emphasis(page)
                    if has_marks:
                        raw_text = marked_text
                cleaned = raw_text.strip()

                pages.append(
                    PageContent(
                        page_number=i,
                        text=raw_text,
                        char_count=len(cleaned),
                        likely_scanned=len(cleaned) < MIN_CHARS_PER_PAGE,
                    )
                )
    except Exception as exc:  # pdfplumber может кидать разные внутренние ошибки
        raise ValueError(f"Не удалось прочитать PDF {file_path}: {exc}") from exc

    return ParsedDocument(source_path=str(file_path), pages=pages)
