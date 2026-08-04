"""Тесты для src/models.py."""
import pytest
from pydantic import ValidationError

from src.models import MatchingPair, MatchingQuestion, MultipleChoiceQuestion, TrueFalseQuestion


def test_multiple_choice_question_valid():
    q = MultipleChoiceQuestion(
        question="Что такое ReLU?",
        options=["Функция активации", "Тип нейросети", "Метод оптимизации", "Функция потерь"],
        correct_index=0,
        source_pages=[2],
    )
    assert q.type == "multiple_choice"
    assert q.options[q.correct_index] == "Функция активации"


def test_multiple_choice_question_rejects_single_option():
    # min_length=2 в схеме — вопрос из одного варианта ответа не имеет смысла
    with pytest.raises(ValidationError):
        MultipleChoiceQuestion(question="Тест?", options=["Единственный вариант"], correct_index=0)


def test_true_false_question_valid():
    q = TrueFalseQuestion(statement="ReLU — функция активации.", is_true=True, source_pages=[2])
    assert q.type == "true_false"
    assert q.is_true is True


def test_matching_question_valid():
    q = MatchingQuestion(
        instruction="Сопоставьте термин и определение",
        pairs=[
            MatchingPair(left="ReLU", right="max(0, x)"),
            MatchingPair(left="Sigmoid", right="Сжимает значения в (0, 1)"),
        ],
    )
    assert q.type == "matching"
    assert len(q.pairs) == 2


def test_matching_question_rejects_single_pair():
    # min_length=2 — "соответствие" из одной пары не имеет смысла
    with pytest.raises(ValidationError):
        MatchingQuestion(instruction="Тест", pairs=[MatchingPair(left="A", right="B")])


def test_source_pages_defaults_to_empty_list():
    q = TrueFalseQuestion(statement="Тест", is_true=False)
    assert q.source_pages == []