"""
Конвертирует уже готовый JSON с вопросами (например, скачанный ранее из
интерфейса) напрямую в Moodle XML — без повторного обращения к BotHub.

Использование:
    python3 scripts/json_to_moodle_xml.py путь/к/quiz_questions.json

Результат сохранится рядом, с тем же именем и расширением .xml
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.models import (
    EssayQuestion,
    MatchingQuestion,
    MultipleChoiceQuestion,
    QuestionType,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)

_MODEL_BY_TYPE = {
    QuestionType.MULTIPLE_CHOICE: MultipleChoiceQuestion,
    QuestionType.TRUE_FALSE: TrueFalseQuestion,
    QuestionType.MATCHING: MatchingQuestion,
    QuestionType.ESSAY: EssayQuestion,
    QuestionType.SHORT_ANSWER: ShortAnswerQuestion,
}


def main():
    if len(sys.argv) != 2:
        print("Использование: python3 scripts/json_to_moodle_xml.py путь/к/файлу.json")
        return

    json_path = Path(sys.argv[1])
    raw_items = json.loads(json_path.read_text(encoding="utf-8"))

    questions = [_MODEL_BY_TYPE[QuestionType(item["type"])].model_validate(item) for item in raw_items]
    print(f"Загружено вопросов: {len(questions)}")

    xml_str = questions_to_moodle_xml(questions)

    out_path = json_path.with_suffix(".xml")
    out_path.write_text(xml_str, encoding="utf-8")
    print(f"Сохранено: {out_path}")


if __name__ == "__main__":
    main()