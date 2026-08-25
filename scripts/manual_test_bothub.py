"""
Ручная проверка реального вызова BotHub API.

Не часть автотестов (pytest) — требует настоящий BOTHUB_API_KEY в .env
и реально тратит токены. Запускать вручную:

    python3 scripts/manual_test_bothub.py

Главная цель именно этой проверки — убедиться, что структурированный вывод
(response_format с Pydantic-схемой) реально работает через BotHub на выбранной
модели. Это единственное, что нельзя проверить без реального ключа.
"""
import logging
import sys
from pathlib import Path

# Позволяет запускать файл напрямую (python3 scripts/manual_test_bothub.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.bothub_client import BotHubClient
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

    client = BotHubClient()

    for question_type in QuestionType:
        print(f"=== {question_type.value} ===")
        try:
            questions = client.generate_questions(
                text=first_chunk.text,
                question_type=question_type,
                count=2,
                source_pages=first_chunk.page_numbers,
            )
            for q in questions:
                print(q.model_dump_json(indent=2, exclude_none=True))
        except Exception as exc:
            print(f"ОШИБКА при генерации {question_type.value}: {type(exc).__name__}: {exc}")
        print()


if __name__ == "__main__":
    main()