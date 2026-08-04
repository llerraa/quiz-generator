"""Тесты для src/parsing/pdf_parser.py."""
import pytest

from src.parsing.pdf_parser import parse_pdf
from tests.make_sample_pdf import make_sample_pdf


@pytest.fixture
def sample_pdf(tmp_path):
    """Генерирует тестовый PDF (3 страницы: 2 текстовые + 1 почти пустая)."""
    return make_sample_pdf(tmp_path / "test_lecture.pdf")


def test_parse_pdf_returns_all_pages(sample_pdf):
    doc = parse_pdf(sample_pdf)
    assert len(doc.pages) == 3


def test_parse_pdf_extracts_readable_cyrillic_text(sample_pdf):
    doc = parse_pdf(sample_pdf)
    # Пробелы от layout=True нормализуем, чтобы не зависеть от точной вёрстки
    normalized = " ".join(doc.pages[0].text.split())
    assert "Лекция 1. Основы нейронных сетей" in normalized


def test_parse_pdf_flags_near_empty_page_as_likely_scanned(sample_pdf):
    doc = parse_pdf(sample_pdf)
    assert doc.pages[2].likely_scanned is True
    assert doc.pages[0].likely_scanned is False
    assert doc.has_scanned_pages is True


def test_parse_pdf_full_text_joins_pages(sample_pdf):
    doc = parse_pdf(sample_pdf)
    assert "нейронных" in doc.full_text
    assert "активации" in doc.full_text


def test_parse_pdf_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_pdf("data/sample/does_not_exist.pdf")
