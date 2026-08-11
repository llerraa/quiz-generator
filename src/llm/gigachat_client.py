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
from pydantic import BaseModel, Field, model_validator

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
    # Явно просим объяснение ДО номера ответа — важен именно такой порядок полей:
    # модель заполняет JSON последовательно, и вынужденное рассуждение перед
    # фиксацией номера снижает количество случаев, когда correct_index указывает
    # не на тот вариант, который модель сама только что описала как верный.
    explanation: str = Field(description="Краткое объяснение, какой вариант верный и почему")
    correct_index: int

    @model_validator(mode="after")
    def _check_correct_index_in_range(self) -> "_GeneratedMCQ":
        # Раньше это никак не проверялось — GigaChat один раз вернул correct_index=3
        # при всего трёх вариантах (валидные индексы 0-2), и такой "битый" вопрос
        # спокойно прошёл бы дальше. Теперь такой ответ отклоняется на этом же этапе.
        if not 0 <= self.correct_index < len(self.options):
            raise ValueError(
                f"correct_index={self.correct_index} вне диапазона options "
                f"(допустимо 0..{len(self.options) - 1})"
            )
        return self


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

    @model_validator(mode="after")
    def _check_pairs_are_differentiated(self) -> "_GeneratedMatching":
        # Реальный кейс из практики: GigaChat сгенерировал 4 пары, у каждой
        # справа один и тот же ответ ("Технологии нейронных сетей") — формально
        # валидные данные, но бессмысленное задание: сопоставлять нечего.
        rights = [p.right.strip().lower() for p in self.pairs]
        if len(set(rights)) == 1:
            raise ValueError(
                "Все пары указывают на один и тот же вариант справа — "
                "такое соответствие не проверяет реальные знания."
            )
        return self


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
                        "материала, а не дословное запоминание фраз из текста.\n\n"
                        "Для вопросов с вариантами ответа (multiple_choice) строго "
                        "соблюдай разделение полей:\n"
                        "- Поле 'options' — ТОЛЬКО сами варианты ответа, коротко и по "
                        "существу. Никаких пояснений, слов «это верно»/«это неверно», "
                        "комментариев в скобках или спецсимволов разметки внутри "
                        "options — это готовые варианты для теста, которые увидит "
                        "студент как есть.\n"
                        "- Поле 'explanation' — сюда, и только сюда, пиши краткое "
                        "объяснение: сначала процитируй короткий фрагмент текста "
                        "лекции, который подтверждает правильный ответ, затем "
                        "объясни на его основе, какой вариант верный.\n"
                        "- Поле 'correct_index' заполняй в конце, на основе своего "
                        "explanation.\n\n"
                        "Для вопросов на соответствие (matching): каждая пара должна "
                        "связывать РАЗНЫЕ понятия с РАЗНЫМИ, не повторяющимися ответами "
                        "справа. Если несколько элементов слева описываются одним и тем "
                        "же общим ответом справа — это не задание на соответствие, "
                        "переформулируй так, чтобы у каждой пары был свой, отличающийся "
                        "от остальных правый вариант."
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
            "GigaChat usage: input=%s, output=%s, total=%s",
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
                explanation=item.explanation,
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
