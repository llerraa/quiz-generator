"""Тесты для src/parsing/chunking.py."""
import pytest

from src.parsing.chunking import chunk_document
from src.parsing.pdf_parser import parse_pdf
from tests.make_sample_pdf import make_sample_pdf


@pytest.fixture
def parsed_sample(tmp_path):
    """Парсит тестовый PDF (2 текстовые страницы + 1 почти пустая)."""
    pdf_path = make_sample_pdf(tmp_path / "test_lecture.pdf")
    return parse_pdf(pdf_path)


def test_chunk_document_skips_likely_scanned_pages(parsed_sample):
    chunks = chunk_document(parsed_sample)
    all_pages_used = [p for chunk in chunks for p in chunk.page_numbers]
    assert 3 not in all_pages_used  # страница 3 почти пустая — должна быть пропущена


def test_chunk_document_combines_pages_within_target_size(parsed_sample):
    # Обе текстовые страницы small — с большим целевым размером попадут в один чанк
    chunks = chunk_document(parsed_sample, target_chunk_size=5000)
    assert len(chunks) == 1
    assert chunks[0].page_numbers == [1, 2]


def test_chunk_document_splits_when_exceeding_target_size(parsed_sample):
    # Очень маленький целевой размер — страницы не должны склеиваться в один чанк
    chunks = chunk_document(parsed_sample, target_chunk_size=10)
    assert len(chunks) == 2
    assert chunks[0].page_numbers == [1]
    assert chunks[1].page_numbers == [2]


def test_chunk_text_contains_expected_content(parsed_sample):
    chunks = chunk_document(parsed_sample, target_chunk_size=5000)
    normalized = " ".join(chunks[0].text.split())
    assert "нейронных" in normalized
    assert "активации" in normalized


def test_chunk_document_empty_input_returns_empty_list():
    from src.parsing.pdf_parser import ParsedDocument

    empty_doc = ParsedDocument(source_path="none", pages=[])
    assert chunk_document(empty_doc) == []