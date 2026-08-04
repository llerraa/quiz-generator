"""
Модуль извлечения текста из PDF-лекций.

Реализует этап "парсинг документов" из архитектуры проекта.
Использует pdfplumber — покрывает "цифровые" PDF с текстовым слоем
(презентации и лекции, экспортированные из PowerPoint/Word/LaTeX).

Триггеры для смены подхода (задокументировано осознанно, чтобы не
переусложнять код заранее — см. README проекта):
  - Если на реальных материалах преподавателей ИМЭС появятся сканы
    без текстового слоя (см. флаг likely_scanned) — подключить OCR
    (pytesseract + pdf2image) как отдельный fallback-модуль.
  - Если появятся многоколоночные макеты, на которых layout=True не
    справляется с порядком текста — попробовать PyMuPDF (pymupdf4llm)
    для этих конкретных файлов.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# Ниже какого количества символов "чистого" текста считаем страницу
# подозрительной на скан/отсутствие текстового слоя.
MIN_CHARS_PER_PAGE = 20


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


def parse_pdf(file_path: str | Path) -> ParsedDocument:
    """
    Извлекает текст из PDF постранично.

    Args:
        file_path: путь к PDF-файлу лекции.

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
                # layout=True старается сохранить визуальный порядок текста —
                # важно для слайдов с несколькими колонками или блоками текста.
                raw_text = page.extract_text(layout=True) or ""
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
