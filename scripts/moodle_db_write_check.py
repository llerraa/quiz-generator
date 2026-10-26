"""
Проверка ЗАПИСИ в реестр (меняет одну запись!). Используйте на тестовой ЭИОС.

Что делает: в указанную запись кладёт маленький пробный файл в колонку
«Обработанный файл (Aiken, для чтения)», ставит статус «Обработан» и текст в «Отчёт».
Чтобы вернуть как было: --reset (очистит статус на «Не обработан» и отчёт; файл удалите вручную через ✏️).

Запуск:
    python -m scripts.moodle_db_check --registry-course 17      # посмотреть номера записей
    python -m scripts.moodle_db_write_check --registry-course 17 --entry 1
    python -m scripts.moodle_db_write_check --registry-course 17 --entry 1 --reset
"""
from __future__ import annotations

import argparse
import sys

from src.moodle.client import MoodleClient, MoodleError
from src.moodle.registry import MoodleRegistry, STATUS_DONE, STATUS_NEW


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-course", type=int, required=True)
    parser.add_argument("--entry", type=int, required=True, help="номер записи (печатает moodle_db_check)")
    parser.add_argument("--name", default="Реестр тестов промежуточной аттестации")
    parser.add_argument("--reset", action="store_true", help="вернуть статус «Не обработан» и очистить отчёт")
    args = parser.parse_args()
    try:
        registry = MoodleRegistry(MoodleClient(), args.registry_course, args.name)
        if args.reset:
            registry.set_status(args.entry, STATUS_NEW, "")
            print("Статус возвращён, отчёт очищен. Пробный файл удалите вручную (✏️ у записи).")
        else:
            registry.save_result(
                args.entry,
                aiken_name="proba_aiken.txt",
                aiken_text="Проверка записи из приложения.\n",
                status=STATUS_DONE,
                report="Проба записи из quiz-generator: статус, отчёт и файл.",
            )
            print("Готово. Откройте базу данных в браузере: у записи должны появиться статус «Обработан», отчёт и файл proba_aiken.txt.")
    except MoodleError as exc:
        print(f"Ошибка: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
