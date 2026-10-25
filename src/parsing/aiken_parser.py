"""
Чтение вопросов из файла в формате Aiken — без обращения к LLM.

Для режима «привести готовые вопросы к формату». Aiken — строгий формат,
поэтому разбирается обычным кодом: это бесплатно (ни одного токена), мгновенно
и без риска, что модель «додумает» ответ, которого в файле нет.

Формат одного вопроса:

    Текст вопроса
    A. вариант
    B. вариант
    ANSWER: B

Вопросы отделяются пустой строкой. Парсер терпимее самой Moodle:
  - принимает `A.` и `A)` у вариантов;
  - принимает `ANSWER:` в любом регистре;
  - допускает вопрос и вариант, перенесённые на несколько строк.

Если вопрос не удалось прочитать, парсер НЕ роняет весь файл, а пропускает
этот вопрос и записывает причину в `errors` — интерфейс покажет её
преподавателю.

Ограничение: буквы вариантов — только латинские (как в самой спецификации
Aiken). Файл с вариантами «А. Б. В.» кириллицей этот парсер не узнает.
"""
import re
from dataclasses import dataclass, field

from src.exporters.aiken_exporter import FALSE_LABEL, TRUE_LABEL
from src.models import MultipleChoiceQuestion, TrueFalseQuestion

_OPTION_RE = re.compile(r"^\s*([A-Za-z])[.)]\s+(\S.*)$")
_ANSWER_LINE_RE = re.compile(r"^\s*ANSWER\s*:(.*)$", re.IGNORECASE)
_ANSWER_VALUE_RE = re.compile(r"^\s*([A-Za-z])\s*[.)]?\s*$")

# Пары вариантов, по которым вопрос узнаётся как «верно/неверно».
# Сравниваем без регистра и без точки в конце.
_TF_PAIRS: list[tuple[str, str]] = [
    (TRUE_LABEL.lower(), FALSE_LABEL.lower()),
    ("true", "false"),
    ("правда", "ложь"),
]


@dataclass
class AikenParseResult:
    """Результат разбора: что удалось прочитать и что нет."""

    questions: list[MultipleChoiceQuestion | TrueFalseQuestion] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def looks_like_aiken(text: str) -> bool:
    """
    Похож ли текст на файл Aiken: есть хотя бы один вариант `A.` и строка `ANSWER:`.

    Проверка намеренно простая — нужна, чтобы решить, читать файл кодом
    или отдавать модели. Если файл признан Aiken, но кое-что в нём
    не разобралось, пользователь увидит конкретные ошибки по вопросам.
    """
    has_answer = False
    has_option_a = False
    for line in text.splitlines():
        if _ANSWER_LINE_RE.match(line):
            has_answer = True
        else:
            m = _OPTION_RE.match(line)
            if m and m.group(1).upper() == "A":
                has_option_a = True
        if has_answer and has_option_a:
            return True
    return False


def _expected_letter(options_read: int) -> str:
    """Какая буква ожидается у следующего варианта, если уже прочитано `options_read` вариантов."""
    return chr(ord("A") + options_read)


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _normalize_option(text: str) -> str:
    return text.strip().rstrip(".").strip().lower()


def _build_question(
    question_lines: list[str],
    options: list[str],
    answer_value: str,
    number: int,
) -> tuple[MultipleChoiceQuestion | TrueFalseQuestion | None, str | None]:
    """Собирает вопрос из прочитанных строк или возвращает текст ошибки."""
    question_text = " ".join(" ".join(question_lines).split())
    label = f"Вопрос {number}" + (f" («{_short(question_text)}»)" if question_text else "")

    if not question_text:
        return None, f"{label}: нет текста вопроса перед вариантами."
    if len(options) < 2:
        return None, f"{label}: найдено меньше двух вариантов ответа."
    if len(options) > 6:
        return None, f"{label}: больше 6 вариантов ({len(options)}) — приложение их не поддерживает."

    m = _ANSWER_VALUE_RE.match(answer_value)
    if not m:
        return None, (
            f"{label}: после ANSWER: ожидается одна буква (например, «ANSWER: B»), "
            f"а в файле «{answer_value.strip()}». Aiken не умеет несколько верных ответов."
        )
    index = ord(m.group(1).upper()) - ord("A")
    if index >= len(options):
        return None, (
            f"{label}: ответ «{m.group(1).upper()}» указывает на несуществующий вариант "
            f"(в вопросе вариантов: {len(options)})."
        )

    # Вопрос с вариантами «Верно/Неверно» превращаем обратно в тип «верно/неверно».
    if len(options) == 2:
        normalized = [_normalize_option(o) for o in options]
        for true_label, false_label in _TF_PAIRS:
            if sorted(normalized) == sorted([true_label, false_label]):
                chosen = normalized[index]
                return TrueFalseQuestion(statement=question_text, is_true=(chosen == true_label)), None

    return MultipleChoiceQuestion(
        question=question_text, options=options, correct_index=index
    ), None


def parse_aiken(text: str) -> AikenParseResult:
    """
    Разбирает текст в формате Aiken.

    Args:
        text: содержимое .txt-файла.

    Returns:
        AikenParseResult: прочитанные вопросы и список ошибок по тем,
        которые прочитать не удалось.
    """
    result = AikenParseResult()
    text = text.lstrip("﻿")  # BOM, который добавляют некоторые редакторы Windows

    question_lines: list[str] = []
    options: list[str] = []
    seen_blank_after_options = False
    number = 0  # порядковый номер вопроса в файле — для понятных сообщений

    def has_content() -> bool:
        return bool(question_lines or options)

    def reset() -> None:
        question_lines.clear()
        options.clear()

    def flush_unfinished() -> None:
        """Блок начался, но строки ANSWER так и не было — записываем ошибку."""
        nonlocal number
        if has_content():
            number += 1
            head = _short(" ".join(question_lines)) or "без текста"
            result.errors.append(
                f"Вопрос {number} («{head}»): нет строки «ANSWER: <буква>» — вопрос пропущен."
            )
            reset()

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            if options:
                seen_blank_after_options = True
            continue

        answer_match = _ANSWER_LINE_RE.match(line)
        if answer_match:
            number += 1
            question, error = _build_question(question_lines, options, answer_match.group(1), number)
            if question is not None:
                result.questions.append(question)
            else:
                result.errors.append(error)
            reset()
            seen_blank_after_options = False
            continue

        option_match = _OPTION_RE.match(line)
        if option_match:
            expected_letter = _expected_letter(len(options))
            if option_match.group(1).upper() == expected_letter:
                options.append(option_match.group(2).strip())
                seen_blank_after_options = False
                continue

        # Обычная строка текста.
        if not options:
            question_lines.append(line)
        elif seen_blank_after_options:
            # Пустая строка после вариантов и новый текст — это уже следующий вопрос,
            # а у предыдущего не было ANSWER.
            flush_unfinished()
            question_lines.append(line)
            seen_blank_after_options = False
        else:
            # Продолжение длинного варианта на следующей строке.
            options[-1] = f"{options[-1]} {line}"

    flush_unfinished()
    return result
