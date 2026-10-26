"""
Клиент веб-сервисов Moodle: проверка связи и загрузка теста в банк вопросов курса.

Как это работает (по шагам):
1. Файл с тестом (Moodle XML) отправляется на адрес /webservice/upload.php —
   Moodle кладёт его во «временную» папку пользователя и отвечает номером (itemid).
2. Вызывается функция плагина local_questions_importer_ws_import_xml
   с номером курса и этим itemid — плагин читает файл и создаёт вопросы в курсе.

Токен — это пропуск в Moodle, как пароль: хранится только в .env, в логи и сообщения
об ошибках не попадает.
"""
from __future__ import annotations

import requests

from src.config import Config

IMPORT_FUNCTION = "local_questions_importer_ws_import_xml"
REQUEST_TIMEOUT = 60  # секунд


class MoodleError(Exception):
    """Moodle ответил ошибкой или недоступен. Текст понятен без знания Moodle."""


class MoodleClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or Config.MOODLE_URL or "").rstrip("/")
        self.token = token or Config.MOODLE_TOKEN
        if not self.base_url or not self.token:
            raise MoodleError(
                "Не заданы MOODLE_URL и MOODLE_TOKEN. Добавьте их в .env "
                "(адрес сайта без слова /webservice и токен из «Управление токенами»)."
            )

    # --- служебное ---------------------------------------------------------

    def _post(self, url: str, **kwargs) -> object:
        try:
            response = requests.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            # str(exc) может содержать адрес вместе с токеном — не показываем его целиком
            raise MoodleError(f"Не удалось связаться с Moodle: {type(exc).__name__}. Проверьте MOODLE_URL и сеть.") from None
        except ValueError:
            raise MoodleError("Moodle ответил не в том формате (не JSON). Проверьте MOODLE_URL.") from None
        if isinstance(data, dict) and ("exception" in data or "error" in data):
            message = data.get("message") or data.get("error") or "неизвестная ошибка"
            code = data.get("errorcode", "")
            raise MoodleError(f"Moodle вернул ошибку: {message}" + (f" ({code})" if code else ""))
        return data

    def call(self, function: str, **params) -> object:
        """Вызов функции веб-сервиса через REST."""
        payload = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        return self._post(f"{self.base_url}/webservice/rest/server.php", data=payload)

    # --- что умеем ---------------------------------------------------------

    def site_info(self) -> dict:
        """Название сайта, версия Moodle, имя пользователя токена."""
        data = self.call("core_webservice_get_site_info")
        return data  # type: ignore[return-value]

    def course_name(self, course_id: int) -> str | None:
        """
        Полное название курса или None (курса нет, нет прав или функции нет в службе).
        Нужно только для показа пользователю, поэтому ошибки не выбрасываем.
        """
        try:
            data = self.call("core_course_get_courses_by_field", field="id", value=course_id)
        except MoodleError:
            return None
        courses = data.get("courses", []) if isinstance(data, dict) else []
        return (courses[0].get("fullname") or None) if courses else None

    def upload_draft(self, filename: str, content: bytes) -> int:
        """Загружает файл во временную папку пользователя, возвращает itemid."""
        data = self._post(
            f"{self.base_url}/webservice/upload.php",
            data={"token": self.token, "filearea": "draft", "itemid": 0},
            files={"file_1": (filename, content)},
        )
        if not isinstance(data, list) or not data or "itemid" not in data[0]:
            raise MoodleError("Moodle принял файл, но не вернул его номер. Проверьте, что у службы включена загрузка файлов.")
        return int(data[0]["itemid"])

    def import_xml(self, course_id: int, xml_text: str, filename: str = "quiz.xml") -> str:
        """
        Загружает Moodle XML в банк вопросов курса.

        Внимание: защиты от дублей нет — повторная загрузка того же теста
        создаст вопросы второй раз.
        """
        itemid = self.upload_draft(filename, xml_text.encode("utf-8"))
        result = self.call(IMPORT_FUNCTION, courseid=course_id, draftitemid=itemid)
        if not isinstance(result, dict) or not result.get("status"):
            raise MoodleError(f"Плагин не подтвердил импорт: {result}")
        return str(result.get("message", "Импорт выполнен."))
