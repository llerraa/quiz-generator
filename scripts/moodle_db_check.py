"""
Проверка связи с реестром тестов (элемент «База данных» в Moodle). Только ЧТЕНИЕ, ничего не меняет.

Запуск (из папки проекта, с активным .venv):
    python -m scripts.moodle_db_check --registry-course 17
    python -m scripts.moodle_db_check --registry-course 17 --download   # скачать файлы преподавателей
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.moodle.client import MoodleClient, MoodleError
from src.moodle.registry import FUNCTIONS_NEEDED, MoodleRegistry, F_SOURCE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-course", type=int, required=True, help="номер курса с базой данных (у нас 17)")
    parser.add_argument("--name", default="Реестр тестов промежуточной аттестации")
    parser.add_argument("--download", action="store_true", help="скачать файлы преподавателей в папку tmp_moodle_files/")
    args = parser.parse_args()

    try:
        client = MoodleClient()
        info = client.site_info()
        print(f"Связь есть: {info.get('sitename')} (Moodle {info.get('release')}), пользователь {info.get('username')}")
        available = {f["name"] for f in info.get("functions", [])}
        for fn in FUNCTIONS_NEEDED:
            print(f"  функция {fn}: {'есть' if fn in available else 'НЕТ — добавьте в службу'}")

        registry = MoodleRegistry(client, args.registry_course, args.name)
        print(f"База данных найдена, её номер: {registry.database_id()}")
        missing = registry.check_fields()
        print("Колонки: все на месте" if not missing else f"Не хватает колонок: {', '.join(missing)}")
        for entry in registry.entries():
            print(f"\nЗапись {entry.entry_id}: {entry.values.get('Наименование курса')}")
            print(f"  курс № {entry.course_id}, статус «{entry.status}»")
            for fname, files in entry.files.items():
                for f in files:
                    print(f"  файл [{fname}]: {f.name}")
            if args.download:
                out = Path("tmp_moodle_files")
                out.mkdir(exist_ok=True)
                for f in entry.files.get(F_SOURCE, []):
                    (out / f"{entry.entry_id}_{f.name}").write_bytes(registry.download(f))
                    print(f"  скачан: {out / (str(entry.entry_id) + '_' + f.name)}")
    except MoodleError as exc:
        print(f"Ошибка: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
