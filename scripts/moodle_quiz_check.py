"""
Проба создания теста в курсе через плагин local_qbankremotemanager.

Запуск из корня проекта (с активированным .venv):
    python3 -m scripts.moodle_quiz_check --course 16
        только проверка: есть ли плагин и какие папки банка вопросов видны в курсе
    python3 -m scripts.moodle_quiz_check --course 16 --file data/sample/teacher_files/09_aiken_30.txt
        создаёт СКРЫТЫЙ тест «Проба: …» из первых 3 вопросов файла Aiken в разделе «Промежуточная аттестация»

Тест создаётся скрытым, поэтому студенты его не увидят. После пробы удалите его в курсе вручную.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.moodle.client import QUIZ_SECTION_NAME, MoodleClient, MoodleError, QuizSettings
from src.parsing.aiken_parser import parse_aiken
from src.parsing.file_loader import decode_text_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", type=int, required=True, help="номер курса (число после id= в адресе)")
    parser.add_argument("--file", help="файл Aiken: из него берутся первые 3 вопроса для пробного теста")
    parser.add_argument("--count", type=int, default=3, help="сколько вопросов взять для пробы (по умолчанию 3)")
    parser.add_argument("--section", type=int, default=None,
                        help=f"номер раздела курса; если не указан, ищется раздел «{QUIZ_SECTION_NAME}»")
    args = parser.parse_args()

    try:
        client = MoodleClient()
        info = client.site_info()
        print(f"Связь есть. Сайт: {info.get('sitename')}; версия: {info.get('release')}; пользователь: {info.get('username')}")

        if not client.plugin_available():
            print("Плагин local_qbankremotemanager не отвечает. Проверьте, что он установлен, а его функции "
                  "добавлены в службу «Генератор тестов» (Администрирование → Сервер → Веб-службы).")
            return 1
        print("Плагин на месте.")

        for cat in client.question_categories(args.course):
            print(f"  папка банка вопросов: {cat}")

        if args.file:
            text = decode_text_file(Path(args.file).read_bytes())
            questions = parse_aiken(text).questions[: args.count]
            if not questions:
                print("В файле не нашлось вопросов Aiken.")
                return 2
            category = f"{Config.MOODLE_CATEGORY} (проба)"
            xml_text = questions_to_moodle_xml(questions, category=category)
            section = args.section
            if section is None:
                section = client.section_number(args.course)
                if section is None:
                    print(f"В курсе {args.course} нет раздела «{QUIZ_SECTION_NAME}». Создайте его или укажите --section.")
                    return 1
                print(f"Раздел «{QUIZ_SECTION_NAME}» найден, его номер {section}.")
            settings = QuizSettings(name=f"Проба: тест из {len(questions)} вопросов", section=section)
            print(f"Создаю скрытый тест в курсе {args.course} из {len(questions)} вопросов…")
            result = client.create_quiz(args.course, xml_text, settings, "probe.xml")
            print(f"Готово: вопросов в тесте {result['questions']}. Открыть: {result['url']}")
            print("Проверьте тест в курсе (он скрыт) и удалите его вручную.")
    except MoodleError as exc:
        print(f"Ошибка: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())