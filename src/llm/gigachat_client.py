"""
Клиент GigaChat API для генерации тестовых вопросов из текста лекции.

Использует встроенную в GigaChat SDK поддержку structured output
(giga.chat_parse с response_format=Pydantic-модель) — SDK сам строит
JSON Schema из модели и сам разбирает ответ обратно в объект, поэтому
не приходится вручную парсить сырой JSON и ловить опечатки модели.
"""
import logging

from gigachat import GigaChat
from gigachat.models import ChatCompletionRequest, ChatMessage
from pydantic import BaseModel, Field

from src.config import Config
from src.models import (
    MatchingPair,
    MatchingQuestion,
    MultipleChoiceQuestion,
    Question,
    QuestionType,
    TrueFalseQuestion,
)

logger = logging.getLogger(__name__)


# --- "Сырые" схемы для structured output ---
# Не переиспользуем модели из src/models.py напрямую: там есть поля
# (type, source_pages), которые заполняет наш код, а не GigaChat —
# просить их у модели незачем, это лишний повод для неё что-то придумать.

class _GeneratedMCQ(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int


class _GeneratedMCQList(BaseModel):
    questions: list[_GeneratedMCQ]


class _GeneratedTrueFalse(BaseModel):
    statement: str
    is_true: bool


class _GeneratedTrueFalseList(BaseModel):
    questions: list[_GeneratedTrueFalse]


class _GeneratedMatchingPair(BaseModel):
    left: str
    right: str


class _GeneratedMatching(BaseModel):
    instruction: str
    pairs: list[_GeneratedMatchingPair] = Field(min_length=2)


class _GeneratedMatchingList(BaseModel):
    questions: list[_GeneratedMatching]


_SCHEMA_BY_TYPE = {
    QuestionType.MULTIPLE_CHOICE: _GeneratedMCQList,
    QuestionType.TRUE_FALSE: _GeneratedTrueFalseList,
    QuestionType.MATCHING: _GeneratedMatchingList,
}

_TYPE_DESCRIPTION_RU = {
    QuestionType.MULTIPLE_CHOICE: "с несколькими вариантами ответа (ровно один верный)",
    QuestionType.TRUE_FALSE: "верно/неверно",
    QuestionType.MATCHING: "на соответствие (сопоставление пар «термин — определение»)",
}


class GigaChatClient:
    """Обёртка над GigaChat SDK — единственное место в проекте, которое знает про GigaChat."""

    def __init__(self):
        Config.validate()
        self._giga = GigaChat(
            credentials=Config.GIGACHAT_CREDENTIALS,
            scope=Config.GIGACHAT_SCOPE,
            model=Config.GIGACHAT_MODEL,
            # Сертификат Минцифры на этапе прототипа не устанавливаем —
            # см. README про TLS-верификацию при переходе в продакшен.
            verify_ssl_certs=False,
        )

    def generate_questions(
        self,
        text: str,
        question_type: QuestionType,
        count: int = 3,
        source_pages: list[int] | None = None,
    ) -> list[Question]:
        """
        Генерирует список вопросов одного типа по тексту (обычно — одного чанка).

        Args:
            text: текст лекции, из которого нужно составить вопросы.
            question_type: какой тип вопросов генерировать.
            count: сколько вопросов сгенерировать (не больше Config.MAX_QUESTIONS_PER_REQUEST).
            source_pages: номера страниц-источников — прокидываются в результат как есть.

        Returns:
            Список объектов нужного типа (см. src/models.py).
        """
        count = min(count, Config.MAX_QUESTIONS_PER_REQUEST)
        schema_cls = _SCHEMA_BY_TYPE[question_type]
        type_description = _TYPE_DESCRIPTION_RU[question_type]

        chat_request = ChatCompletionRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "Ты помогаешь преподавателю составлять тестовые вопросы по "
                        "материалам лекции. Вопросы должны проверять понимание "
                        "материала, а не дословное запоминание фраз из текста."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"Составь ровно {count} вопрос(ов) типа «{type_description}» "
                        f"по следующему тексту лекции:\n\n{text}"
                    ),
                ),
            ],
        )

        # Используем giga.chat.parse (основной эндпоинт), а не giga.chat_parse —
        # последний помечен в SDK как Beta и обращается к отдельному "резервному"
        # адресу API, которого пока нет на боевом сервере GigaChat (ловили 404).
        completion, parsed = self._giga.chat.parse(chat_request, response_format=schema_cls, strict=True)

        usage = completion.usage
        logger.info(
            "GigaChat: потрачено токенов — запрос=%s, ответ=%s, всего=%s",
            usage.input_tokens, usage.output_tokens, usage.total_tokens,
        )

        return [
            self._to_app_model(item, question_type, source_pages or [])
            for item in parsed.questions
        ]

    @staticmethod
    def _to_app_model(item, question_type: QuestionType, source_pages: list[int]) -> Question:
        if question_type == QuestionType.MULTIPLE_CHOICE:
            return MultipleChoiceQuestion(
                question=item.question,
                options=item.options,
                correct_index=item.correct_index,
                source_pages=source_pages,
            )
        if question_type == QuestionType.TRUE_FALSE:
            return TrueFalseQuestion(
                statement=item.statement,
                is_true=item.is_true,
                source_pages=source_pages,
            )
        if question_type == QuestionType.MATCHING:
            pairs = [MatchingPair(left=p.left, right=p.right) for p in item.pairs]
            return MatchingQuestion(
                instruction=item.instruction,
                pairs=pairs,
                source_pages=source_pages,
            )
        raise ValueError(f"Неизвестный тип вопроса: {question_type}")
