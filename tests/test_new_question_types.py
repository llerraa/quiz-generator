"""Тесты для новых типов вопросов (эссе, короткий ответ) в src/models.py."""
from src.models import EssayQuestion, QuestionType, ShortAnswerQuestion


def test_essay_question_defaults():
    q = EssayQuestion(question="Опишите принцип работы нейросети", grading_criteria="Слои, веса, функция активации")
    assert q.type == QuestionType.ESSAY
    assert q.source_pages == []


def test_short_answer_question_defaults():
    q = ShortAnswerQuestion(question="Функция f(x)=max(0,x)?", sample_answer="ReLU")
    assert q.type == QuestionType.SHORT_ANSWER
    assert q.sample_answer == "ReLU"


def test_essay_and_short_answer_serialize_with_type_field():
    essay = EssayQuestion(question="Q?", grading_criteria="C")
    sa = ShortAnswerQuestion(question="Q2?", sample_answer="A")

    assert essay.model_dump()["type"] == "essay"
    assert sa.model_dump()["type"] == "short_answer"