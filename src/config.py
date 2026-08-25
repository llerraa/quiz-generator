"""
Конфигурация проекта.

Единая точка чтения настроек и секретов из .env — весь остальной код
получает ключи и параметры только отсюда, а не читает os.environ напрямую.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Настройки приложения, собранные в одном месте."""

    BOTHUB_API_KEY: str | None = os.getenv("BOTHUB_API_KEY")
    BOTHUB_BASE_URL: str = os.getenv("BOTHUB_BASE_URL", "https://bothub.chat/api/v2/openai/v1")
    BOTHUB_MODEL: str = os.getenv("BOTHUB_MODEL", "claude-sonnet-5")

    MAX_QUESTIONS_PER_REQUEST: int = int(
        os.getenv("MAX_QUESTIONS_PER_REQUEST", "30")
    )

    @classmethod
    def validate(cls) -> None:
        if not cls.BOTHUB_API_KEY:
            raise RuntimeError(
                "BOTHUB_API_KEY не задан. Скопируйте .env.example в .env "
                "и укажите реальный ключ, полученный в личном кабинете BotHub "
                "(bothub.chat → Для разработчиков)."
            )