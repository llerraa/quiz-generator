"""
Веса вариантов для вопроса с двумя верными ответами (общие для Moodle XML и GIFT).

Правило из инструкции ИМЭС: сумма весов всех вариантов равна нулю, чтобы нельзя было
набрать баллы, отметив все варианты подряд.
  - каждый верный вариант: 100 / (число верных), округлённое вниз до целого (при двух верных — 50);
  - каждый неверный вариант: минус столько, чтобы сумма всех весов вышла 0
    (при двух верных и двух неверных — минус 50).
Вопрос с одним верным ответом весов не использует: верный 100, остальные 0.
"""
from __future__ import annotations


def choice_weights(option_count: int, correct: list[int]) -> list[float]:
    """Вес каждого варианта в процентах (в порядке вариантов)."""
    right = sorted(set(correct))
    if len(right) <= 1:
        return [100.0 if i in right else 0.0 for i in range(option_count)]
    wrong = option_count - len(right)
    right_weight = float(100 // len(right))
    wrong_weight = -(right_weight * len(right)) / wrong if wrong else 0.0
    return [right_weight if i in right else wrong_weight for i in range(option_count)]


def format_weight(value: float) -> str:
    """50.0 → «50», -33.333333 → «-33.33333» (формат, понятный Moodle)."""
    rounded = round(value, 5)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.5f}".rstrip("0")
