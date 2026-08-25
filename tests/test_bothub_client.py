"""
Тесты для src/llm/bothub_client.py.

Реальных вызовов к BotHub API здесь нет и не должно быть — тесты должны
проходить у любого, кто клонирует репозиторий, даже без ключа BotHub.
Настоящий вызов API проверяется отдельным ручным скриптом
(scripts/manual_test_bothub.py), не через pytest.
"""
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.llm.bothub_client import (
    BotHubClient,
    _GeneratedMatching,
    _GeneratedMatchingList,
    _GeneratedMatchingPair,
    _GeneratedMCQ,
    _GeneratedMCQList,
    _GeneratedTrueFalse,
    _GeneratedTrueFalseList,
)
from src.models import MatchingQuestion, MultipleChoiceQuestion, QuestionType, TrueFalseQuestion


def test_generated_matching_rejects_identical_right_values():
    with pytest.raises(ValidationError):
        _GeneratedMatching(
            instruction="Тест",
            pairs=[
                _GeneratedMatchingPair(left="A", right="Одно и то же"),
                _GeneratedMatchingPair(left="B", right="Одно и то же"),
                _GeneratedMatchingPair(left="C", right="одно и то же"),
            ],
        )


def test_generated_mcq_rejects_out_of_range_correct_index():
    with pytest.raises(ValidationError):
        _GeneratedMCQ(
            question="Тест?",
            options=["A", "B", "C"],
            explanation="Тестовое объяснение",
            correct_index=3,
        )


def test_client_init_raises_without_credentials(monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", None)
    with pytest.raises(RuntimeError):
        BotHubClient()


def test_to_app_model_converts_multiple_choice():
    item = _GeneratedMCQ(question="Что такое ReLU?", options=["Функция активации", "Тип слоя"], explanation="e", correct_index=0)
    result = BotHubClient._to_app_model(item, QuestionType.MULTIPLE_CHOICE, source_pages=[2])

    assert isinstance(result, MultipleChoiceQuestion)
    assert result.question == "Что такое ReLU?"
    assert result.source_pages == [2]


def test_to_app_model_converts_true_false():
    item = _GeneratedTrueFalse(statement="ReLU — функция активации.", is_true=True)
    result = BotHubClient._to_app_model(item, QuestionType.TRUE_FALSE, source_pages=[3])

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
    result = BotHubClient._to_app_model(item, QuestionType.MATCHING, source_pages=[])

    assert isinstance(result, MatchingQuestion)
    assert len(result.pairs) == 2
    assert result.pairs[0].left == "ReLU"


# --- Тесты на разбор JSON из ответа модели (_parse_json_response) ---
# Именно тут была реальная проблема на практике: модель отвечала обычным
# текстом вместо JSON, потому что response_format не сработал через BotHub.

def test_parse_json_response_handles_clean_json():
    raw = '{"questions": [{"question": "Q?", "options": ["A", "B"], "explanation": "e", "correct_index": 0}]}'
    result = BotHubClient._parse_json_response(raw, _GeneratedMCQList)
    assert len(result.questions) == 1


def test_parse_json_response_strips_markdown_fence():
    raw = '```json\n{"questions": []}\n```'
    result = BotHubClient._parse_json_response(raw, _GeneratedMCQList)
    assert result.questions == []


def test_parse_json_response_extracts_json_surrounded_by_prose():
    raw = 'Вот структурированный ответ:\n\n{"questions": []}\n\nНадеюсь, это поможет!'
    result = BotHubClient._parse_json_response(raw, _GeneratedMCQList)
    assert result.questions == []


def test_parse_json_response_raises_clear_error_on_pure_prose():
    # Реальный кейс из практики: модель ответила "Вот 2 вопроса... Правильный
    # ответ: C" вместо JSON — response_format был проигнорирован через прокси.
    with pytest.raises(ValueError, match="невалидный JSON"):
        BotHubClient._parse_json_response("Вот 2 вопроса по теме... Правильный ответ: C", _GeneratedMCQList)


# --- Тесты полного пути через мок SDK openai ---

@patch("src.llm.bothub_client.OpenAI")
def test_generate_questions_uses_create_and_converts_results(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")

    mock_client_instance = MagicMock()
    mock_openai_cls.return_value = mock_client_instance

    fake_json = (
        '{"questions": ['
        '{"question": "Вопрос 1?", "options": ["A", "B"], "explanation": "e1", "correct_index": 0},'
        '{"question": "Вопрос 2?", "options": ["C", "D"], "explanation": "e2", "correct_index": 1}'
        ']}'
    )
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock(message=MagicMock(content=fake_json))]
    fake_completion.usage.prompt_tokens = 100
    fake_completion.usage.completion_tokens = 50
    fake_completion.usage.total_tokens = 150
    mock_client_instance.chat.completions.create.return_value = fake_completion

    client = BotHubClient()
    result = client.generate_questions(
        text="Текст лекции про ReLU и Sigmoid.",
        question_type=QuestionType.MULTIPLE_CHOICE,
        count=2,
        source_pages=[1, 2],
    )

    assert len(result) == 2
    assert all(isinstance(q, MultipleChoiceQuestion) for q in result)
    assert result[0].source_pages == [1, 2]
    mock_client_instance.chat.completions.create.assert_called_once()


@patch("src.llm.bothub_client.OpenAI")
def test_extract_questions_finds_existing_questions(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")

    mock_client_instance = MagicMock()
    mock_openai_cls.return_value = mock_client_instance

    fake_json = '{"questions": [{"question": "Уже готовый вопрос?", "options": ["A", "B"], "explanation": "из документа", "correct_index": 0}]}'
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock(message=MagicMock(content=fake_json))]
    fake_completion.usage.prompt_tokens = 50
    fake_completion.usage.completion_tokens = 20
    fake_completion.usage.total_tokens = 70
    mock_client_instance.chat.completions.create.return_value = fake_completion

    client = BotHubClient()
    result = client.extract_questions(
        text="1. Уже готовый вопрос? а) A (верно) б) B",
        question_type=QuestionType.MULTIPLE_CHOICE,
    )

    assert len(result) == 1
    assert isinstance(result[0], MultipleChoiceQuestion)
    mock_client_instance.chat.completions.create.assert_called_once()