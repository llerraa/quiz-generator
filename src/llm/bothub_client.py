"""
Клиент BotHub API (OpenAI-совместимый) для генерации тестовых вопросов
из текста лекции.

BotHub — российский агрегатор доступа к LLM (Claude, GPT и др.) с оплатой
рублями, работает по стандарту OpenAI API.

ВАЖНО про structured output: изначально использовался client.chat.completions
.parse() с response_format=Pydantic-модель (аналог giga.chat.parse()) — но на
практике модель (claude-sonnet-5 через BotHub) полностью игнорировала этот
параметр и отвечала обычным текстом в чате, а не JSON. Вероятная причина: у
Claude в его собственном API нет параметра response_format вообще (там другой
механизм — tool use), и BotHub, судя по всему, не транслирует это требование
при проксировании запроса к Claude.

Поэтому формат ответа теперь запрашивается ЯВНО ТЕКСТОМ в самом промпте (а не
через отдельный технический параметр), а разбор JSON из ответа модели делаем
вручную, с защитой от markdown-обёртки (```json ... ```) и лишнего текста
до/после — это надёжнее, чем полагаться на response_format через прокси.

Раньше в проекте использовался GigaChat — перешли на BotHub, чтобы иметь
доступ к более широкому набору моделей (Claude, GPT) через один API.
"""
import json
import logging

from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from src.config import Config
from src.models import (
    EssayQuestion,
    MatchingPair,
    MatchingQuestion,
    MultipleChoiceQuestion,
    Question,
    QuestionType,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)

logger = logging.getLogger(__name__)


# --- "Сырые" схемы для structured output ---
# Не переиспользуем модели из src/models.py напрямую: там есть поля
# (type, source_pages), которые заполняет наш код, а не модель —
# просить их у LLM незачем, это лишний повод для неё что-то придумать.

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
        rights = [p.right.strip().lower() for p in self.pairs]
        if len(set(rights)) == 1:
            raise ValueError(
                "Все пары указывают на один и тот же вариант справа — "
                "такое соответствие не проверяет реальные знания."
            )
        return self


class _GeneratedMatchingList(BaseModel):
    questions: list[_GeneratedMatching]


class _GeneratedEssay(BaseModel):
    question: str
    grading_criteria: str = Field(
        description="Критерии оценки — на что преподавателю обращать внимание при проверке ответа"
    )


class _GeneratedEssayList(BaseModel):
    questions: list[_GeneratedEssay]


class _GeneratedShortAnswer(BaseModel):
    question: str
    sample_answer: str = Field(description="Краткий эталонный ответ (слово, число или фраза)")


class _GeneratedShortAnswerList(BaseModel):
    questions: list[_GeneratedShortAnswer]


_SCHEMA_BY_TYPE = {
    QuestionType.MULTIPLE_CHOICE: _GeneratedMCQList,
    QuestionType.TRUE_FALSE: _GeneratedTrueFalseList,
    QuestionType.MATCHING: _GeneratedMatchingList,
    QuestionType.ESSAY: _GeneratedEssayList,
    QuestionType.SHORT_ANSWER: _GeneratedShortAnswerList,
}

_TYPE_DESCRIPTION_RU = {
    QuestionType.MULTIPLE_CHOICE: "с несколькими вариантами ответа (ровно один верный)",
    QuestionType.TRUE_FALSE: "верно/неверно",
    QuestionType.MATCHING: "на соответствие (сопоставление пар «термин — определение»)",
    QuestionType.ESSAY: "эссе (открытый вопрос, требующий развёрнутого письменного ответа)",
    QuestionType.SHORT_ANSWER: "короткий ответ (открытый вопрос с кратким эталонным ответом)",
}

_SYSTEM_PROMPT_GENERATE = (
    "Ты помогаешь преподавателю составлять тестовые вопросы по "
    "материалам лекции. Вопросы должны проверять понимание "
    "материала, а не дословное запоминание фраз из текста.\n\n"
    "Для вопросов с вариантами ответа (multiple_choice) строго "
    "соблюдай разделение полей:\n"
    "- Поле 'options' — ТОЛЬКО сами варианты ответа, коротко и по "
    "существу. Никаких пояснений, слов «это верно»/«это неверно», "
    "комментариев в скобках или спецсимволов разметки внутри "
    "options — это готовые варианты для теста, которые увидит "
    "студент как есть. Варианты должны быть ВЗАИМОИСКЛЮЧАЮЩИМИ — "
    "верным должен быть ровно один из них, а остальные — явно "
    "неверными или менее точными, а не другими равнозначными "
    "правильными примерами из той же категории.\n"
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
    "от остальных правый вариант.\n\n"
    "Для вопросов типа «эссе» (essay): вопрос должен требовать "
    "развёрнутого рассуждения, а не одного факта — единственно "
    "верного ответа здесь нет. В поле 'grading_criteria' перечисли "
    "конкретные пункты, которые обязательно должны быть в хорошем "
    "ответе (это не эталонный текст, а именно критерии для проверки).\n\n"
    "Для вопросов типа «короткий ответ» (short_answer): вопрос должен "
    "предполагать один конкретный, краткий ответ — слово, число или "
    "короткую фразу (не разворачивай в вопрос с вариантами и не "
    "проси развёрнутое рассуждение). В поле 'sample_answer' укажи "
    "именно такой краткий ожидаемый ответ, без пояснений."
)

_SYSTEM_PROMPT_EXTRACT_TEMPLATE = (
    "Ты помогаешь преподавателю привести уже готовые тестовые "
    "вопросы к структурированному формату. В тексте ниже могут "
    "быть вопросы разных типов — найди среди них ТОЛЬКО вопросы "
    "типа «{type_description}» и извлеки их как есть. НЕ придумывай "
    "новых вопросов и не меняй формулировку по существу — только "
    "переноси в структуру.\n\n"
    "Правильный ответ определяй по явным текстовым указаниям рядом "
    "с вариантом или сразу после вопроса. Указания могут выглядеть "
    "по-разному, учитывай ВСЕ эти варианты: слово «верно»/«да» в "
    "скобках; фраза «Правильный ответ: ...» или короткая «Ответ: ...» "
    "(в том числе отдельной строкой после списка вариантов); "
    "символ «*» рядом с вариантом; символ «(+)» рядом с вариантом; "
    "жирный шрифт или другое визуальное выделение НЕ считаются "
    "указанием — в извлечённом тексте оформление не сохраняется, "
    "поэтому такой вариант нельзя определить как правильный только "
    "по расположению или виду.\n\n"
    "Если по вопросу есть явный текстовый маркер, но неясно, к "
    "какому именно варианту он относится — НЕ угадывай. В этом "
    "случае и в любом другом случае неуверенности лучше вообще "
    "пропустить этот вопрос (не включать его в questions), чем "
    "указать неверный ответ.\n\n"
    "Если в тексте нет вопросов такого типа — верни пустой список "
    "questions."
)


class BotHubClient:
    """Обёртка над BotHub API (через SDK openai) — единственное место в проекте, знающее про BotHub."""

    def __init__(self):
        Config.validate()
        self._client = OpenAI(
            api_key=Config.BOTHUB_API_KEY,
            base_url=Config.BOTHUB_BASE_URL,
            # Без явного таймаута SDK готов молча ждать ответа до 10 минут —
            # при проблемах с сетью/сервером это выглядит как зависание.
            # 60 секунд — с запасом даже для сложных структурированных ответов.
            timeout=60.0,
        )

    def _call_structured(self, system_prompt: str, user_prompt: str, schema_cls: type[BaseModel]) -> BaseModel:
        """
        Запрашивает у модели ответ, разобранный по schema_cls.

        Не полагаемся на параметр response_format — на практике (проверено
        на реальном вызове claude-sonnet-5 через BotHub) он просто
        игнорируется, и модель отвечает обычным текстом вместо JSON.
        Вместо этого явно требуем формат текстом в промпте и сами парсим
        и валидируем результат — надёжнее, чем полагаться на прокси.
        """
        schema_json = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
        format_instruction = (
            "\n\nОтветь СТРОГО в формате JSON и только JSON — без вступительных "
            "фраз, пояснений, markdown-обрамления в ```json``` или любого "
            "текста до или после объекта. JSON должен точно соответствовать "
            f"следующей JSON Schema:\n{schema_json}"
        )

        completion = self._client.chat.completions.create(
            model=Config.BOTHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt + format_instruction},
                {"role": "user", "content": user_prompt},
            ],
        )

        usage = completion.usage
        logger.info(
            "BotHub usage: prompt=%s, completion=%s, total=%s",
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
        )

        raw_content = completion.choices[0].message.content
        return self._parse_json_response(raw_content, schema_cls)

    @staticmethod
    def _parse_json_response(raw_content: str, schema_cls: type[BaseModel]) -> BaseModel:
        """Разбирает JSON из ответа модели с защитой от markdown-обёртки и лишнего текста."""
        cleaned = raw_content.strip()

        # Модель иногда оборачивает JSON в ```json ... ``` — убираем разметку.
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        # Если модель всё же добавила текст до/после JSON — вырезаем сам объект
        # по первой "{" и последней "}".
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Модель вернула невалидный JSON: {exc}\n"
                f"Ответ модели (начало): {raw_content[:300]}"
            ) from exc

        return schema_cls.model_validate(data)

    def generate_questions(
        self,
        text: str,
        question_type: QuestionType,
        count: int = 3,
        source_pages: list[int] | None = None,
    ) -> list[Question]:
        """Генерирует список вопросов одного типа по тексту (обычно — одного чанка)."""
        count = min(count, Config.MAX_QUESTIONS_PER_REQUEST)
        schema_cls = _SCHEMA_BY_TYPE[question_type]
        type_description = _TYPE_DESCRIPTION_RU[question_type]

        parsed = self._call_structured(
            system_prompt=_SYSTEM_PROMPT_GENERATE,
            user_prompt=(
                f"Составь ровно {count} вопрос(ов) типа «{type_description}» "
                f"по следующему тексту лекции:\n\n{text}"
            ),
            schema_cls=schema_cls,
        )

        return [
            self._to_app_model(item, question_type, source_pages or [])
            for item in parsed.questions
        ]

    def extract_questions(
        self,
        text: str,
        question_type: QuestionType,
        source_pages: list[int] | None = None,
    ) -> list[Question]:
        """Извлекает уже существующие в тексте вопросы одного типа — НЕ генерирует новые."""
        schema_cls = _SCHEMA_BY_TYPE[question_type]
        type_description = _TYPE_DESCRIPTION_RU[question_type]
        system_prompt = _SYSTEM_PROMPT_EXTRACT_TEMPLATE.format(type_description=type_description)

        parsed = self._call_structured(
            system_prompt=system_prompt,
            user_prompt=f"Текст с вопросами:\n\n{text}",
            schema_cls=schema_cls,
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
        if question_type == QuestionType.ESSAY:
            return EssayQuestion(
                question=item.question,
                grading_criteria=item.grading_criteria,
                source_pages=source_pages,
            )
        if question_type == QuestionType.SHORT_ANSWER:
            return ShortAnswerQuestion(
                question=item.question,
                sample_answer=item.sample_answer,
                source_pages=source_pages,
            )
        raise ValueError(f"Неизвестный тип вопроса: {question_type}")