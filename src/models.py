"""
Схема данных для тестовых вопросов.

Единый формат, в который должен укладываться результат генерации —
неважно, какой провайдер это делает (сейчас BotHub/Claude). Экспортёры
(JSON/Excel/QTI) тоже работают именно с этими моделями, а не с сырым
текстом ответа LLM — это и есть та самая "граница" между слоем llm/
и слоем export/, о которой мы говорили в архитектуре.
"""
from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"
    ESSAY = "essay"
    SHORT_ANSWER = "short_answer"


class MultipleChoiceQuestion(BaseModel):
    """Вопрос с несколькими вариантами ответа, один из которых верный."""

    type: Literal[QuestionType.MULTIPLE_CHOICE] = QuestionType.MULTIPLE_CHOICE
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int  # индекс правильного варианта в списке options (с 0)
    explanation: str | None = None  # объяснение от модели — для быстрой проверки человеком
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


class EssayQuestion(BaseModel):
    """
    Открытый вопрос, требующий развёрнутого письменного ответа.

    Нет единственного «правильного» варианта — вместо этого критерии
    оценки, по которым преподаватель проверяет ответ студента вручную.
    """

    type: Literal[QuestionType.ESSAY] = QuestionType.ESSAY
    question: str
    grading_criteria: str  # на что обращать внимание при проверке ответа
    source_pages: list[int] = Field(default_factory=list)


class ShortAnswerQuestion(BaseModel):
    """
    Вопрос, предполагающий короткий текстовый ответ (слово, число, фраза).

    В отличие от эссе — здесь есть конкретный эталонный ответ, с которым
    можно сверять ответ студента (в том числе автоматически, если LMS
    поддерживает такую проверку).
    """

    type: Literal[QuestionType.SHORT_ANSWER] = QuestionType.SHORT_ANSWER
    question: str
    sample_answer: str  # эталонный/ожидаемый ответ
    source_pages: list[int] = Field(default_factory=list)


# Любой вопрос в проекте — это один из пяти типов выше.
# Pydantic сам разберёт, какой именно, по полю "type".
Question = Union[
    MultipleChoiceQuestion,
    TrueFalseQuestion,
    MatchingQuestion,
    EssayQuestion,
    ShortAnswerQuestion,
]