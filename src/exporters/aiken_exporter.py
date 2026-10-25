"""
Экспорт вопросов в формат Aiken.

Aiken — самый простой текстовый формат импорта вопросов в Moodle
(Банк вопросов → Импорт → Формат Aiken). Один вопрос выглядит так:

    Какой язык программирования называют интерпретируемым?
    A. Python
    B. Assembler
    C. Машинный код
    ANSWER: A

Между вопросами — пустая строка.

Что формат НЕ умеет — и поэтому сюда не попадает:
  - соответствие (matching), эссе и короткий ответ: в Aiken есть только
    вопросы «выбери один вариант из списка»;
  - пояснение к ответу (explanation): отдельного поля для него нет.
Верно/неверно записывается как вопрос с двумя вариантами «Верно» и «Неверно».

Приложение не молчит о пропущенных вопросах: функция
count_skipped_for_aiken() возвращает их число, и интерфейс показывает его
преподавателю рядом с кнопкой скачивания.
"""
from src.models import MultipleChoiceQuestion, Question, TrueFalseQuestion

# Названия двух вариантов для вопроса «верно/неверно». Парсер
# (src/parsing/aiken_parser.py) узнаёт именно их и собирает обратно
# вопрос типа «верно/неверно», поэтому менять их нужно синхронно.
TRUE_LABEL = "Верно"
FALSE_LABEL = "Неверно"

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _one_line(text: str) -> str:
    """Aiken читает вопрос и каждый вариант построчно — переносы строк схлопываем в пробелы."""
    return " ".join(text.split())


def _mcq_block(q: MultipleChoiceQuestion) -> str:
    lines = [_one_line(q.question)]
    for letter, option in zip(_LETTERS, q.options):
        lines.append(f"{letter}. {_one_line(option)}")
    lines.append(f"ANSWER: {_LETTERS[q.correct_index]}")
    return "\n".join(lines)


def _tf_block(q: TrueFalseQuestion) -> str:
    lines = [
        _one_line(q.statement),
        f"A. {TRUE_LABEL}",
        f"B. {FALSE_LABEL}",
        f"ANSWER: {'A' if q.is_true else 'B'}",
    ]
    return "\n".join(lines)


def count_skipped_for_aiken(questions: list[Question]) -> int:
    """Сколько вопросов Aiken выразить не может (соответствие, эссе, короткий ответ)."""
    return sum(
        1 for q in questions
        if not isinstance(q, (MultipleChoiceQuestion, TrueFalseQuestion))
    )


def questions_to_aiken(questions: list[Question]) -> str:
    """
    Преобразует список вопросов в текст формата Aiken.

    Берёт только вопросы с множественным выбором и «верно/неверно»;
    остальные типы пропускает (их число даёт count_skipped_for_aiken).
    Если подходящих вопросов нет — возвращает пустую строку.

    Returns:
        Текст в UTF-8, блоки вопросов разделены пустой строкой.
    """
    blocks: list[str] = []
    for q in questions:
        if isinstance(q, MultipleChoiceQuestion):
            blocks.append(_mcq_block(q))
        elif isinstance(q, TrueFalseQuestion):
            blocks.append(_tf_block(q))

    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"
