"""
Извлечение текста из DOCX-файлов с уже готовыми вопросами преподавателя.

Проще, чем pdf_parser.py: не нужна постраничная структура и флаг
"похоже на скан" — docx всегда содержит настоящий текстовый слой.
"""
from pathlib import Path

from docx import Document


def parse_docx(file_path: str | Path) -> str:
    """
    Извлекает весь текст из docx-файла одной строкой.

    Args:
        file_path: путь к .docx-файлу.

    Returns:
        Текст документа, абзацы разделены переносом строки.

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

    # Забираем текст не только из обычных абзацев, но и из таблиц —
    # преподаватели нередко оформляют вопросы/варианты таблицей.
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())

    return "\n".join(parts)