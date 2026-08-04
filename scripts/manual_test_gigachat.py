"""
Ручная проверка реального вызова GigaChat API.

Не часть автотестов (pytest) — требует настоящий GIGACHAT_CREDENTIALS в .env
и реально тратит токены из вашего лимита. Запускать вручную:

    python3 scripts/manual_test_gigachat.py

Берёт маленький тестовый PDF, генерирует по 2 вопроса каждого типа —
этого достаточно, чтобы своими глазами увидеть, что GigaChat реально
работает, и посмотреть в логах, сколько токенов ушло на эту проверку.
"""

import logging
import sys
from pathlib import Path

# Позволяет запускать файл напрямую (python3 scripts/manual_test_gigachat.py):
# без этой строки Python ищет модули только внутри папки scripts/ и не видит
# src/ уровнем выше, в корне проекта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.gigachat_client import GigaChatClient
from src.models import QuestionType
from src.parsing.chunking import chunk_document
from src.parsing.pdf_parser import parse_pdf

logging.basicConfig(level=logging.INFO, format="%(message)s")

SAMPLE_PDF = "data/sample/test_lecture.pdf"


def main():
    print(f"Парсим {SAMPLE_PDF}...")
    document = parse_pdf(SAMPLE_PDF)

    chunks = chunk_document(document)
    if not chunks:
        print("Не нашлось текста для генерации вопросов — проверьте сам PDF.")
        return

    first_chunk = chunks[0]
    print(f"Берём первый чанк (страницы {first_chunk.page_numbers}, {first_chunk.char_count} символов)")
    print()

    client = GigaChatClient()

    for question_type in QuestionType:
        print(f"=== {question_type.value} ===")
        questions = client.generate_questions(
            text=first_chunk.text,
            question_type=question_type,
            count=2,
            source_pages=first_chunk.page_numbers,
        )
        for q in questions:
            print(q.model_dump_json(indent=2, exclude_none=True))
        print()


if __name__ == "__main__":
    main()