"""
Проверка связи с Moodle и пробная загрузка теста в курс.

Запуск из корня проекта (с активированным .venv):
    python3 scripts/moodle_check.py                    # только проверка связи
    python3 scripts/moodle_check.py --course 16 --import data/sample/teacher_files/09_aiken_30.txt

Для пробы берутся первые 3 вопроса файла Aiken и кладутся в папку
«<MOODLE_CATEGORY> (проба)», чтобы не смешивать их с настоящими тестами.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.moodle.client import MoodleClient, MoodleError
from src.parsing.aiken_parser import parse_aiken
from src.parsing.file_loader import decode_text_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", type=int, help="номер курса (число после id= в адресе)")
    parser.add_argument("--import", dest="import_file", help="файл Aiken для пробной загрузки")
    args = parser.parse_args()

    try:
        client = MoodleClient()
        info = client.site_info()
        print(f"Связь есть. Сайт: {info.get('sitename')}; версия: {info.get('release')}; пользователь: {info.get('username')}")

        if args.import_file:
            if not args.course:
                print("Для загрузки укажите номер курса: --course 16")
                return 2
            text = decode_text_file(Path(args.import_file).read_bytes())
            questions = parse_aiken(text).questions[:3]
            if not questions:
                print("В файле не нашлось вопросов Aiken.")
                return 2
            category = f"{Config.MOODLE_CATEGORY} (проба)"
            xml_text = questions_to_moodle_xml(questions, category=category)
            print(f"Загружаю {len(questions)} вопроса(ов) в курс {args.course}, папка «{category}»…")
            print(client.import_xml(args.course, xml_text, "probe.xml"))
            print("Готово. Откройте в курсе «Банк вопросов» и проверьте папку.")
    except MoodleError as exc:
        print(f"Ошибка: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
