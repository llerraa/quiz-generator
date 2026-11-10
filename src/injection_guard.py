"""
Вторая линия защиты от промпт-инъекций: проверка того, что модель вернула.

Первая линия — промпт (src/llm/bothub_client.py): текст файла помечен как данные.
Она снижает риск, но не гарантирует защиту. Схемы Pydantic проверяют только
структуру ответа, а не смысл: фраза-приказ из файла может пройти как «вопрос»
или «вариант ответа» и дойти до студентов.

Поэтому каждый вопрос просматривается по узким шаблонам (обращения к ИИ,
«игнорируй предыдущие указания», попытки раскрыть промпт, указания «считай
верным …») и по длине. Подозрительные вопросы НЕ удаляются: приложение
показывает их человеку и не отправляет тест в Moodle, пока человек их не
прочитает и не подтвердит (см. src/moodle/panel.py).

Шаблоны намеренно узкие: слово «выполни» само по себе встречается в учебных
заданиях («выполните расчёт»), и по нему вопросы бы помечались постоянно.
"""
from __future__ import annotations

import re

# Предел длины: больше — похоже на вставленный посторонний текст, а не на вопрос.
MAX_QUESTION_CHARS = 1500
MAX_OPTION_CHARS = 600

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (reason, re.compile(pattern, re.IGNORECASE | re.UNICODE))
    for reason, pattern in (
        ("«игнорируй предыдущие указания»",
         r"игнорир\w*\s+(?:все\s+|всё\s+|любые\s+)?(?:предыдущ|прошл|прежн|вышеуказан|выше|свои|эти|данн)\w*"),
        ("«забудь предыдущие указания»",
         r"забуд\w*\s+(?:все\s+|всё\s+|что\s+)?(?:предыдущ|прошл|прежн|свои|эти|инструкц|указани|правил)\w*"),
        ("«не слушай»", r"не\s+слуша\w*\s+(?:инструкц|указани|правил|систем|предыдущ|выше)"),
        ("упоминание системного промпта",
         r"(?:system|системн\w*)\s*[-_ ]?\s*(?:prompt|промпт|инструкци|сообщени)\w*"),
        ("просьба раскрыть инструкции",
         r"(?:раскрой|покажи|выведи|повтори|пришли|напиши|распечатай)\s+(?:мне\s+|нам\s+)?"
         r"(?:свои\s+|свою\s+|твои\s+|твою\s+|эти\s+|все\s+|весь\s+|полный\s+)?"
         r"(?:системн\w+\s+)?(?:промпт|инструкци|правил)\w*"),
        ("указание «считай верным / отмечай верным»",
         r"(?:считай\w*|отмечай\w*|помечай\w*|выбирай\w*|всегда\s+выбирай\w*)\s+(?:всегда\s+)?"
         r"(?:верн|правильн|вариант)\w*"),
        ("обращение к ИИ с новой ролью",
         r"(?:ты\s+(?:теперь|больше\s+не)\s|с\s+этого\s+момента\s+ты\s|притворись\s|"
         r"действуй\s+как\s+(?:будто|если)\b|new\s+instructions?|you\s+are\s+now\b|jailbreak|\bDAN\s+mode)"),
        ("«ignore previous instructions»",
         r"(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
         r"(?:previous|prior|above|earlier|system)\s+(?:instructions?|prompts?|rules?)"),
        ("служебный маркер приложения",
         r"\[\s*ДАННЫЕ[_\s-]*(?:НАЧАЛО|КОНЕЦ)\s*\]|===\s*БЕЗОПАСНОСТЬ"),
    )
)


def injection_reasons(text: str) -> list[str]:
    """Почему текст подозрителен (пустой список — шаблонов инъекции не найдено)."""
    if not text:
        return []
    return [reason for reason, pattern in _PATTERNS if pattern.search(text)]


def has_injection_markers(text: str) -> bool:
    """True, если в тексте есть узкие шаблоны манипуляции промптом."""
    return bool(injection_reasons(text))


def _strings(value, key: str = ""):
    """Все строки внутри вопроса (текст, варианты, пары, пояснение) вместе с именем поля."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, key)


def question_problems(question) -> list[str]:
    """Что подозрительного в одном вопросе (любого типа). Пусто — ничего."""
    data = question.model_dump() if hasattr(question, "model_dump") else {"question": str(question)}
    problems: list[str] = []
    for key, text in _strings(data):
        for reason in injection_reasons(text):
            if reason not in problems:
                problems.append(reason)
        limit = MAX_OPTION_CHARS if key in ("options", "left", "right") else MAX_QUESTION_CHARS
        if key in ("question", "statement", "instruction", "options", "left", "right") and len(text) > limit:
            note = f"аномально длинный текст ({len(text)} символов)"
            if note not in problems:
                problems.append(note)
    return problems


def flag_injected_questions(questions) -> dict[int, list[str]]:
    """
    Подозрительные вопросы: {номер с нуля: [причины]}.

    Только пометка для ручной проверки, вопросы не удаляются и не меняются.
    """
    flagged: dict[int, list[str]] = {}
    for index, question in enumerate(questions):
        problems = question_problems(question)
        if problems:
            flagged[index] = problems
    return flagged
