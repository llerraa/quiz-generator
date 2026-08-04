"""
Конфигурация проекта.

Единая точка чтения настроек и секретов из .env — весь остальной код
получает ключи и параметры только отсюда, а не читает os.environ напрямую.
Это тот самый "изолированный слой", который позволит позже подменить
персональный GigaChat-ключ на организационный (ИМЭС), не трогая остальной код.
"""
import os

from dotenv import load_dotenv

# Подгружаем переменные из .env в окружение процесса.
# Если .env отсутствует (например, на сервере секреты заданы иначе,
# как в Streamlit Cloud secrets) — load_dotenv просто ничего не сделает.
load_dotenv()


class Config:
    """Настройки приложения, собранные в одном месте."""

    # --- GigaChat API ---
    GIGACHAT_CREDENTIALS: str | None = os.getenv("GIGACHAT_CREDENTIALS")
    GIGACHAT_SCOPE: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    GIGACHAT_MODEL: str = os.getenv("GIGACHAT_MODEL", "GigaChat")

    # --- Ограничения генерации ---
    MAX_QUESTIONS_PER_REQUEST: int = int(
        os.getenv("MAX_QUESTIONS_PER_REQUEST", "30")
    )

    @classmethod
    def validate(cls) -> None:
        """
        Проверяет, что критичные для работы приложения настройки заданы.
        Вызывается при старте приложения (app.py), а не при каждом импорте —
        чтобы модуль парсинга можно было тестировать без ключа GigaChat.
        """
        if not cls.GIGACHAT_CREDENTIALS:
            raise RuntimeError(
                "GIGACHAT_CREDENTIALS не задан. Скопируйте .env.example в .env "
                "и укажите реальный ключ авторизации GigaChat API."
            )
