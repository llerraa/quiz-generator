"""Ограничение расхода на один файл: исключение, которое останавливает обработку."""


class BudgetExceeded(Exception):
    """Файл уже «съел» отведённый лимит CAPS — новые запросы к ИИ не отправляются."""

    def __init__(self, spent_caps: float, limit_caps: float):
        self.spent_caps = spent_caps
        self.limit_caps = limit_caps
        super().__init__(
            f"Превышен лимит токенов на один файл: потрачено примерно {spent_caps:,.0f} CAPS "
            f"при лимите {limit_caps:,.0f}".replace(",", " ")
        )
