"""
Извлечение текста из DOCX-файлов с уже готовыми вопросами преподавателя.

Преподаватели отмечают правильный ответ по-разному: словами («Ответ: Б»),
звёздочкой, а часто — только оформлением: жирным шрифтом, подчёркиванием,
выделением маркером или цветом. Обычное извлечение текста (`paragraph.text`)
оформление теряет, и ответ становится не найти.

Поэтому по умолчанию оформление сохраняется в виде лёгких текстовых меток,
которые затем читает модель (см. EMPHASIS_LEGEND — описание меток для промпта):

    **жирный**    __подчёркнутый__    ==выделенный маркером==    {~цветной~}

Второе, что исправлено: порядок. Таблицы читаются на своём месте в документе
(а не добавляются в конец), строка таблицы превращается в одну строку текста
с ячейками через « | » — так связь «вопрос — вариант — отметка» не рвётся.

Не поддерживается: текстовые поля и фигуры, нумерация Word (номера «а) б) в)»,
которые Word подставляет сам, в тексте отсутствуют — порядок вариантов
при этом сохраняется), рисунки.
"""
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

# Описание меток для промпта модели — держим рядом с кодом, который их ставит.
EMPHASIS_LEGEND = (
    "В тексте оформление исходного документа передано метками: "
    "**текст** — жирный шрифт, __текст__ — подчёркнутый, "
    "==текст== — выделенный маркером, {~текст~} — цветной шрифт. "
    "Строки таблицы записаны через « | »."
)

_BLACKISH = {"000000", "010101", "1A1A1A", "222222", "262626", "333333"}


def _is_set(value) -> bool:
    """Свойство python-docx включено: True, но не None/False/«нет подчёркивания»."""
    if value is None or value is False:
        return False
    if getattr(value, "name", None) == "NONE":
        return False
    return True


def _inherited(run, paragraph, attr: str):
    """Значение bold/italic с учётом стиля символа и стиля абзаца."""
    direct = getattr(run, attr)
    if direct is not None:
        return direct
    for style in (run.style, paragraph.style):
        if style is not None and getattr(style.font, attr) is not None:
            return getattr(style.font, attr)
    return None


def _run_flags(run, paragraph) -> tuple[bool, bool, bool, bool]:
    bold = bool(_inherited(run, paragraph, "bold"))
    underline = _is_set(run.underline)
    highlight = run.font.highlight_color is not None
    color = False
    rgb = run.font.color.rgb if run.font.color is not None else None
    if rgb is not None and str(rgb).upper() not in _BLACKISH:
        color = True
    return bold, underline, highlight, color


def _wrap(text: str, flags: tuple[bool, bool, bool, bool]) -> str:
    """Оборачивает текст метками; пробелы по краям остаются снаружи меток."""
    core = text.strip()
    if not core or not any(flags):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    bold, underline, highlight, color = flags
    if bold:
        core = f"**{core}**"
    if underline:
        core = f"__{core}__"
    if highlight:
        core = f"=={core}=="
    if color:
        core = f"{{~{core}~}}"
    return f"{lead}{core}{trail}"


def _paragraph_text(paragraph: Paragraph, mark_emphasis: bool) -> str:
    if not mark_emphasis:
        return paragraph.text

    # Склеиваем соседние фрагменты с одинаковым оформлением, чтобы не получить
    # «**а****б**» из-за того, что Word разбил слово на несколько кусков.
    groups: list[list] = []  # [flags, text]
    for run in paragraph.runs:
        if not run.text:
            continue
        flags = _run_flags(run, paragraph)
        if groups and groups[-1][0] == flags:
            groups[-1][1] += run.text
        else:
            groups.append([flags, run.text])

    plain = "".join(text for _, text in groups)
    if plain != paragraph.text:
        # В абзаце есть то, чего нет среди обычных фрагментов (например, гиперссылка):
        # надёжнее отдать простой текст без меток, чем потерять часть слов.
        return paragraph.text
    return "".join(_wrap(text, flags) for flags, text in groups)


def _iter_blocks(doc):
    """Абзацы и таблицы документа в том порядке, в котором они стоят в файле."""
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_lines(table: Table, mark_emphasis: bool) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        seen = set()
        cells: list[str] = []
        for cell in row.cells:
            # Объединённая ячейка приходит из python-docx несколько раз — берём один раз.
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            text = " ".join(
                t for t in (_paragraph_text(p, mark_emphasis).strip() for p in cell.paragraphs) if t
            )
            if text:
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def parse_docx(file_path: str | Path, mark_emphasis: bool = True) -> str:
    """
    Извлекает весь текст из docx-файла одной строкой.

    Args:
        file_path: путь к .docx-файлу.
        mark_emphasis: сохранять оформление (жирный, подчёркивание, маркер,
            цвет) метками — см. EMPHASIS_LEGEND.

    Returns:
        Текст документа в порядке следования; абзацы и строки таблиц
        разделены переносом строки.

    Raises:
        FileNotFoundError: если файл не найден.
        ValueError: если файл не удалось прочитать как docx.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать DOCX {file_path}: {exc}") from exc

    parts: list[str] = []
    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = _paragraph_text(block, mark_emphasis)
            if text.strip():
                parts.append(text)
        else:
            parts.extend(_table_lines(block, mark_emphasis))

    return "\n".join(parts)
