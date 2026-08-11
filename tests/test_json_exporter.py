"""Тесты для src/exporters/json_exporter.py."""
import json

from src.exporters.json_exporter import questions_to_json
from src.models import MatchingPair, MatchingQuestion, MultipleChoiceQuestion, TrueFalseQuestion


def test_questions_to_json_produces_valid_json():
    questions = [
        MultipleChoiceQuestion(
            question="Что такое ReLU?",
            options=["Функция активации", "Тип слоя"],
            correct_index=0,
            source_pages=[1],
        ),
    ]
    result = questions_to_json(questions)
    parsed = json.loads(result)  # не должно упасть — значит, валидный JSON
    assert len(parsed) == 1
    assert parsed[0]["question"] == "Что такое ReLU?"


def test_questions_to_json_keeps_cyrillic_readable():
    # ensure_ascii=False — кириллица должна остаться как есть, а не \u-escape
    questions = [TrueFalseQuestion(statement="Тест на русском", is_true=True)]
    result = questions_to_json(questions)
    assert "Тест на русском" in result
    assert "\\u" not in result


def test_questions_to_json_handles_all_three_types():
    questions = [
        MultipleChoiceQuestion(question="Q1?", options=["A", "B"], correct_index=0),
        TrueFalseQuestion(statement="Утверждение", is_true=False),
        MatchingQuestion(
            instruction="Сопоставьте",
            pairs=[MatchingPair(left="X", right="Y"), MatchingPair(left="Z", right="W")],
        ),
    ]
    result = questions_to_json(questions)
    parsed = json.loads(result)
    assert len(parsed) == 3
    assert parsed[0]["type"] == "multiple_choice"
    assert parsed[1]["type"] == "true_false"
    assert parsed[2]["type"] == "matching"


def test_questions_to_json_empty_list():
    assert json.loads(questions_to_json([])) == []