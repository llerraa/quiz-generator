"""
Тесты для src/llm/gigachat_client.py.

Реальных вызовов к GigaChat API здесь нет и не должно быть — тесты должны
проходить у любого, кто клонирует репозиторий, даже без ключа GigaChat.
Настоящий вызов API проверяется отдельным ручным скриптом
(scripts/manual_test_gigachat.py), не через pytest.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.llm.gigachat_client import (
    GigaChatClient,
    _GeneratedMatching,
    _GeneratedMatchingList,
    _GeneratedMatchingPair,
    _GeneratedMCQ,
    _GeneratedMCQList,
    _GeneratedTrueFalse,
    _GeneratedTrueFalseList,
)
from src.models import MatchingQuestion, MultipleChoiceQuestion, QuestionType, TrueFalseQuestion


def test_client_init_raises_without_credentials(monkeypatch):
    monkeypatch.setattr("src.llm.gigachat_client.Config.GIGACHAT_CREDENTIALS", None)
    with pytest.raises(RuntimeError):
        GigaChatClient()


def test_to_app_model_converts_multiple_choice():
    item = _GeneratedMCQ(question="Что такое ReLU?", options=["Функция активации", "Тип слоя"], correct_index=0)
    result = GigaChatClient._to_app_model(item, QuestionType.MULTIPLE_CHOICE, source_pages=[2])

    assert isinstance(result, MultipleChoiceQuestion)
    assert result.question == "Что такое ReLU?"
    assert result.source_pages == [2]


def test_to_app_model_converts_true_false():
    item = _GeneratedTrueFalse(statement="ReLU — функция активации.", is_true=True)
    result = GigaChatClient._to_app_model(item, QuestionType.TRUE_FALSE, source_pages=[3])

    assert isinstance(result, TrueFalseQuestion)
    assert result.is_true is True


def test_to_app_model_converts_matching():
    item = _GeneratedMatching(
        instruction="Сопоставьте термин и определение",
        pairs=[
            _GeneratedMatchingPair(left="ReLU", right="max(0, x)"),
            _GeneratedMatchingPair(left="Sigmoid", right="Сжимает в (0, 1)"),
        ],
    )
    result = GigaChatClient._to_app_model(item, QuestionType.MATCHING, source_pages=[])

    assert isinstance(result, MatchingQuestion)
    assert len(result.pairs) == 2
    assert result.pairs[0].left == "ReLU"


@patch("src.llm.gigachat_client.GigaChat")
def test_generate_questions_uses_chat_parse_and_converts_results(mock_gigachat_cls, monkeypatch):
    # Подкладываем фиктивные креды, чтобы Config.validate() не упал
    monkeypatch.setattr("src.llm.gigachat_client.Config.GIGACHAT_CREDENTIALS", "fake-creds")

    mock_giga_instance = MagicMock()
    mock_gigachat_cls.return_value = mock_giga_instance

    fake_completion = MagicMock()
    fake_completion.usage.input_tokens = 100
    fake_completion.usage.output_tokens = 50
    fake_completion.usage.total_tokens = 150

    fake_parsed = _GeneratedMCQList(
        questions=[
            _GeneratedMCQ(question="Вопрос 1?", options=["A", "B"], correct_index=0),
            _GeneratedMCQ(question="Вопрос 2?", options=["C", "D"], correct_index=1),
        ]
    )

    mock_giga_instance.chat.parse.return_value = (fake_completion, fake_parsed)

    client = GigaChatClient()
    result = client.generate_questions(
        text="Текст лекции про ReLU и Sigmoid.",
        question_type=QuestionType.MULTIPLE_CHOICE,
        count=2,
        source_pages=[1, 2],
    )

    assert len(result) == 2
    assert all(isinstance(q, MultipleChoiceQuestion) for q in result)
    assert result[0].source_pages == [1, 2]
    mock_giga_instance.chat.parse.assert_called_once()