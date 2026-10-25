"""
Единая загрузка файла с вопросами: PDF, DOCX или TXT → текст.

Для режима «Тест для курса». Оформление (жирный, цвет и т.п.) сохраняется
метками, чтобы ответ, отмеченный не словами, а видом текста, не терялся.
"""
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.parsing.docx_parser import parse_docx
from src.parsing.pdf_parser import parse_pdf

SUPPORTED_SUFFIXES = (".pdf", ".docx", ".txt")


@dataclass
class LoadedFile:
    text: str
    warnings: list[str] = field(default_factory=list)


def decode_text_file(raw: bytes) -> str:
    """
    Декодирует .txt: сначала UTF-8 (в том числе с BOM), затем Windows-1251.

    Файлы, сохранённые в «Блокноте» на русской Windows, нередко в cp1251 —
    с `errors="replace"` по UTF-8 из них получились бы сплошные «�».
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def load_question_file(raw: bytes, suffix: str) -> LoadedFile:
    """
    Args:
        raw: содержимое файла.
        suffix: расширение с точкой, в любом регистре (".docx").

    Raises:
        ValueError: неподдерживаемый формат или файл не читается.
    """
    suffix = suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Формат {suffix or '(без расширения)'} не поддерживается. Нужен PDF, DOCX или TXT.")

    if suffix == ".txt":
        return LoadedFile(text=decode_text_file(raw))

    # pdfplumber и python-docx читают с диска — пишем во временный файл
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        if suffix == ".docx":
            return LoadedFile(text=parse_docx(tmp_path, mark_emphasis=True))

        document = parse_pdf(tmp_path, mark_emphasis=True)
        warnings = []
        scanned = [p.page_number for p in document.pages if p.likely_scanned]
        if scanned:
            pages = ", ".join(str(n) for n in scanned[:10]) + ("…" if len(scanned) > 10 else "")
            warnings.append(
                f"На страницах {pages} нет текстового слоя (похоже на скан) — "
                "вопросы с этих страниц не прочитаны."
            )
        return LoadedFile(text=document.full_text, warnings=warnings)
    finally:
        os.unlink(tmp_path)
