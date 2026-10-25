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

    # Тариф для оценки расхода в интерфейсе (CAPS — внутренняя валюта BotHub).
    # Цифры — для claude-sonnet-5, подогнаны по двум настоящим списаниям из кабинета
    # (25.10.2026: 2084+670 токенов → 4 959 CAPS; 1961+811 → 5 491 CAPS); при смене модели или тарифа
    # поправьте в .env, иначе оценка будет неточной. Настоящее списание всегда
    # смотрите в личном кабинете BotHub: это только прикидка.
    CAPS_PER_INPUT_TOKEN: float = float(os.getenv("BOTHUB_CAPS_PER_INPUT_TOKEN", "0.9127"))
    CAPS_PER_OUTPUT_TOKEN: float = float(os.getenv("BOTHUB_CAPS_PER_OUTPUT_TOKEN", "4.5633"))
    RUB_PER_CAP: float = float(os.getenv("BOTHUB_RUB_PER_CAP", "0.0001"))

    # Защита от случайного большого расхода: файл длиннее этого числа символов
    # в режиме «Тест для курса» не обрабатывается ИИ (файлы Aiken не ограничены).
    COURSE_MAX_CHARS: int = int(os.getenv("COURSE_MAX_CHARS", "60000"))

    # 20 000 CAPS (≈ 2 ₽) выбрано по замерам 25.10.2026: файл на 10 вопросов стоит 5–7,3 тыс.,
    # на 25 вопросов ожидается 12–16 тыс. CAPS — с запасом, но без риска большого счёта.
    # Лимит расхода на ОДИН файл в режиме «Тест для курса», в CAPS. Как только файл
    # «съел» столько — новые запросы к ИИ не отправляются, обработка останавливается.
    # Проверка идёт между запросами: уже отправленный запрос остановить нельзя, поэтому
    # итог может превысить лимит на стоимость одного запроса. 0 — без лимита.
    COURSE_MAX_CAPS: float = float(os.getenv("COURSE_MAX_CAPS", "20000"))

    @classmethod
    def validate(cls) -> None:
        if not cls.BOTHUB_API_KEY:
            raise RuntimeError(
                "BOTHUB_API_KEY не задан. Скопируйте .env.example в .env "
                "и укажите реальный ключ, полученный в личном кабинете BotHub "
                "(bothub.chat → Для разработчиков)."
            )