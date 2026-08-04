"""
Схема данных для тестовых вопросов.

Единый формат, в который должен укладываться результат генерации —
неважно, GigaChat это делает сейчас или другой провайдер в будущем.
Экспортёры (JSON/Excel/QTI) тоже работают именно с этими моделями,
а не с сырым текстом ответа LLM — это и есть та самая "граница" между
слоем llm/ и слоем export/, о которой мы говорили в архитектуре.
"""
from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"


class MultipleChoiceQuestion(BaseModel):
    """Вопрос с несколькими вариантами ответа, один из которых верный."""

    type: Literal[QuestionType.MULTIPLE_CHOICE] = QuestionType.MULTIPLE_CHOICE
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int  # индекс правильного варианта в списке options (с 0)
    source_pages: list[int] = Field(default_factory=list)


class TrueFalseQuestion(BaseModel):
    """Утверждение, которое нужно оценить как верное или неверное."""

    type: Literal[QuestionType.TRUE_FALSE] = QuestionType.TRUE_FALSE
    statement: str
    is_true: bool
    source_pages: list[int] = Field(default_factory=list)


class MatchingPair(BaseModel):
    """Одна пара «понятие — определение» для вопроса на соответствие."""

    left: str
    right: str


class MatchingQuestion(BaseModel):
    """Вопрос на соответствие: сопоставить элементы левого и правого списка."""

    type: Literal[QuestionType.MATCHING] = QuestionType.MATCHING
    instruction: str
    pairs: list[MatchingPair] = Field(min_length=2)
    source_pages: list[int] = Field(default_factory=list)


# Любой вопрос в проекте — это один из трёх типов выше.
# Pydantic сам разберёт, какой именно, по полю "type".
Question = Union[MultipleChoiceQuestion, TrueFalseQuestion, MatchingQuestion]