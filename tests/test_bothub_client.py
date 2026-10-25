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
    _GeneratedEssay,
    _GeneratedEssayList,
    _GeneratedMatching,
    _GeneratedMatchingList,
    _GeneratedMatchingPair,
    _GeneratedMCQ,
    _GeneratedMCQList,
    _GeneratedShortAnswer,
    _GeneratedShortAnswerList,
    _GeneratedTrueFalse,
    _GeneratedTrueFalseList,
)
from src.models import (
    EssayQuestion,
    MatchingQuestion,
    MultipleChoiceQuestion,
    QuestionType,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)


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


# --- Тесты на новые типы: эссе и короткий ответ ---

def test_to_app_model_converts_essay():
    item = _GeneratedEssay(question="Опишите принцип работы нейросети", grading_criteria="Слои, веса, функция активации")
    result = BotHubClient._to_app_model(item, QuestionType.ESSAY, source_pages=[7])

    assert isinstance(result, EssayQuestion)
    assert result.grading_criteria == "Слои, веса, функция активации"
    assert result.source_pages == [7]


def test_to_app_model_converts_short_answer():
    item = _GeneratedShortAnswer(question="Функция f(x)=max(0,x)?", sample_answer="ReLU")
    result = BotHubClient._to_app_model(item, QuestionType.SHORT_ANSWER, source_pages=[8])

    assert isinstance(result, ShortAnswerQuestion)
    assert result.sample_answer == "ReLU"


@patch("src.llm.bothub_client.OpenAI")
def test_generate_questions_handles_essay_type(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")

    mock_client_instance = MagicMock()
    mock_openai_cls.return_value = mock_client_instance

    fake_json = '{"questions": [{"question": "Опишите принцип работы нейросети", "grading_criteria": "Слои, веса"}]}'
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock(message=MagicMock(content=fake_json))]
    fake_completion.usage.prompt_tokens = 50
    fake_completion.usage.completion_tokens = 20
    fake_completion.usage.total_tokens = 70
    mock_client_instance.chat.completions.create.return_value = fake_completion

    client = BotHubClient()
    result = client.generate_questions(text="текст лекции", question_type=QuestionType.ESSAY, count=1)

    assert len(result) == 1
    assert isinstance(result[0], EssayQuestion)


@patch("src.llm.bothub_client.OpenAI")
def test_generate_questions_handles_short_answer_type(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")

    mock_client_instance = MagicMock()
    mock_openai_cls.return_value = mock_client_instance

    fake_json = '{"questions": [{"question": "Функция f(x)=max(0,x)?", "sample_answer": "ReLU"}]}'
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock(message=MagicMock(content=fake_json))]
    fake_completion.usage.prompt_tokens = 40
    fake_completion.usage.completion_tokens = 10
    fake_completion.usage.total_tokens = 50
    mock_client_instance.chat.completions.create.return_value = fake_completion

    client = BotHubClient()
    result = client.generate_questions(text="текст лекции", question_type=QuestionType.SHORT_ANSWER, count=1)

    assert len(result) == 1
    assert isinstance(result[0], ShortAnswerQuestion)
    assert result[0].sample_answer == "ReLU"


# --- Учёт расхода токенов и защита от скрытых повторов ---

def _fake_completion(prompt_tokens, completion_tokens, content='{"questions": []}'):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=content))]
    completion.usage.prompt_tokens = prompt_tokens
    completion.usage.completion_tokens = completion_tokens
    completion.usage.total_tokens = prompt_tokens + completion_tokens
    return completion


@patch("src.llm.bothub_client.OpenAI")
def test_usage_accumulates_over_several_calls(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    instance = MagicMock()
    mock_openai_cls.return_value = instance
    instance.chat.completions.create.side_effect = [
        _fake_completion(1000, 200),
        _fake_completion(500, 100),
    ]

    client = BotHubClient()
    assert client.usage.calls == 0
    client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)
    client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)

    assert client.usage.calls == 2
    assert client.usage.prompt_tokens == 1500
    assert client.usage.completion_tokens == 300
    assert client.usage.total_tokens == 1800


@patch("src.llm.bothub_client.OpenAI")
def test_usage_estimate_uses_configured_tariff(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    monkeypatch.setattr("src.llm.bothub_client.Config.CAPS_PER_INPUT_TOKEN", 1.0)
    monkeypatch.setattr("src.llm.bothub_client.Config.CAPS_PER_OUTPUT_TOKEN", 10.0)
    monkeypatch.setattr("src.llm.bothub_client.Config.RUB_PER_CAP", 0.5)
    instance = MagicMock()
    mock_openai_cls.return_value = instance
    instance.chat.completions.create.return_value = _fake_completion(100, 20)

    client = BotHubClient()
    client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)

    assert client.usage.estimated_caps == 100 * 1.0 + 20 * 10.0
    assert client.usage.estimated_rub == pytest.approx(300 * 0.5)


@patch("src.llm.bothub_client.OpenAI")
def test_missing_usage_in_response_does_not_crash(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    instance = MagicMock()
    mock_openai_cls.return_value = instance
    completion = _fake_completion(1, 1)
    completion.usage = None  # провайдер иногда не присылает usage
    instance.chat.completions.create.return_value = completion

    client = BotHubClient()
    client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)

    assert client.usage.calls == 1
    assert client.usage.total_tokens == 0


@patch("src.llm.bothub_client.OpenAI")
def test_sdk_hidden_retries_are_disabled(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    BotHubClient()
    assert mock_openai_cls.call_args.kwargs["max_retries"] == 0


@patch("src.llm.bothub_client.OpenAI")
def test_budget_limit_blocks_next_request_but_not_the_one_in_flight(mock_openai_cls, monkeypatch):
    from src.budget import BudgetExceeded

    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    monkeypatch.setattr("src.llm.bothub_client.Config.CAPS_PER_INPUT_TOKEN", 1.0)
    monkeypatch.setattr("src.llm.bothub_client.Config.CAPS_PER_OUTPUT_TOKEN", 1.0)
    instance = MagicMock()
    mock_openai_cls.return_value = instance
    instance.chat.completions.create.return_value = _fake_completion(600, 500)  # 1100 CAPS за вызов

    client = BotHubClient(max_caps=1000)
    client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)  # первый проходит
    assert client.usage.estimated_caps == 1100

    with pytest.raises(BudgetExceeded) as err:
        client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)
    assert "Превышен лимит токенов на один файл" in str(err.value)
    assert instance.chat.completions.create.call_count == 1  # второй запрос в сеть не ушёл


@patch("src.llm.bothub_client.OpenAI")
def test_no_limit_by_default_and_zero_means_unlimited(mock_openai_cls, monkeypatch):
    monkeypatch.setattr("src.llm.bothub_client.Config.BOTHUB_API_KEY", "fake-key")
    instance = MagicMock()
    mock_openai_cls.return_value = instance
    instance.chat.completions.create.return_value = _fake_completion(100000, 100000)

    for limit in (None, 0):
        client = BotHubClient(max_caps=limit)
        for _ in range(3):
            client.extract_questions(text="текст", question_type=QuestionType.MULTIPLE_CHOICE)
        assert client.usage.calls == 3
