"""
Экспорт вопросов в формат GIFT (Moodle) по правилам, которые ИМЭС задаёт в промпте конвертации Aiken → GIFT.

Раньше сотрудник отдавал файл Aiken нейросети с этим промптом; здесь то же самое делает код:
бесплатно, мгновенно и без риска, что модель что-то изменит.

Правила (как в промпте):
  - вопрос: ::краткое имя:: текст { варианты };
  - порядок вариантов сохраняется, буквы «A.», «B.» остаются в тексте варианта;
  - один верный ответ: «=» у верного, «~» у остальных;
  - два верных: «=» не используется, у верных «~%50%», у неверных «~%-50%» (сумма весов 0);
  - спецсимволы ~ = # { } : экранируются обратной косой чертой;
  - между вопросами одна пустая строка; без категорий и комментариев; UTF-8 без BOM.

Вопрос «верно/неверно» выводится как вопрос с двумя вариантами «Верно» / «Неверно» (как и в Aiken).
Типы без вариантов ответа (эссе, соответствие, короткий ответ) в GIFT-файл не попадают.
"""
from __future__ import annotations

import re

from src.exporters.aiken_exporter import FALSE_LABEL, TRUE_LABEL
from src.exporters.multichoice_weights import choice_weights, format_weight
from src.models import MultipleChoiceQuestion, Question, TrueFalseQuestion

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SPECIAL = re.compile(r"([~=#{}:])")
NAME_LIMIT = 60


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", _one_line(text))


def _short_name(text: str) -> str:
    text = _one_line(text)
    return text if len(text) <= NAME_LIMIT else text[:NAME_LIMIT].rstrip() + "…"


def _block(question_text: str, options: list[str], correct: list[int]) -> str:
    weights = choice_weights(len(options), correct)
    multi = len(set(correct)) > 1
    lines = [f"::{_escape(_short_name(question_text))}:: {_escape(question_text)}", "{"]
    for i, (option, weight) in enumerate(zip(options, weights)):
        text = f"{_LETTERS[i]}. {_escape(option)}"
        if multi:
            lines.append(f"~%{format_weight(weight)}%{text}")
        else:
            lines.append(f"{'=' if i in correct else '~'}{text}")
    lines.append("}")
    return "\n".join(lines)


def questions_to_gift(questions: list[Question]) -> str:
    """Текст GIFT-файла для вопросов с выбором ответа; остальные типы пропускаются."""
    blocks: list[str] = []
    for q in questions:
        if isinstance(q, MultipleChoiceQuestion):
            blocks.append(_block(q.question, q.options, q.correct_indices))
        elif isinstance(q, TrueFalseQuestion):
            blocks.append(_block(q.statement, [TRUE_LABEL, FALSE_LABEL], [0 if q.is_true else 1]))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
