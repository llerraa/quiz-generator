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

from dataclasses import dataclass, field

import requests

from src.config import Config

IMPORT_FUNCTION = "local_questions_importer_ws_import_xml"
# Плагин local_qbankremotemanager: создаёт тест в курсе и кладёт в него вопросы из Moodle XML
PING_FUNCTION = "local_qbankremotemanager_am_i_here"
QUIZ_FUNCTION = "local_qbankremotemanager_upload_quiz"
CATEGORIES_FUNCTION = "local_qbankremotemanager_get_question_categories"
# Название раздела курса, куда кладётся новый тест (в шаблоне курсов ЭИОС оно одинаковое)
QUIZ_SECTION_NAME = "Промежуточная аттестация"
REQUEST_TIMEOUT = 60  # секунд


class MoodleError(Exception):
    """Moodle ответил ошибкой или недоступен. Текст понятен без знания Moodle."""


@dataclass
class QuizSettings:
    """
    Настройки теста, который создаётся в курсе. Значения по умолчанию — предварительные,
    до согласования с ИМЭС; в интерфейсе их можно менять перед созданием.
    Тест создаётся СКРЫТЫМ: сотрудник сам проверяет его и открывает студентам.
    Всё, что здесь не указано, Moodle берёт из общих настроек теста на сайте.
    """

    name: str
    section: int = 0              # номер раздела курса (0 — самый верхний, общий)
    visible: bool = False         # скрытый тест не виден студентам
    attempts: int = 1             # число попыток (0 — без ограничения)
    time_limit_minutes: int = 40  # время на попытку; 0 — без ограничения
    points_per_question: float = 2  # баллы за вопрос; кладутся в XML (defaultgrade), максимум теста = сумма
    shuffle_answers: bool = True  # перемешивать варианты ответов внутри вопроса
    shuffle_questions: bool = True   # перемешивать порядок вопросов
    questions_per_page: int = 1   # вопросов на странице (0 — все на одной)
    navigation: str = "free"      # "free" — можно возвращаться к прошлым вопросам, "sequential" — нельзя
    behaviour: str = "deferredfeedback"  # оценка и отзыв только после завершения попытки
    show_marks: bool = True       # студент видит оценку после попытки (правильные ответы не показываем)
    # Способ оценивания при нескольких попытках. Плагин принимает НАЗВАНИЕ на языке сайта
    # («Высшая оценка», «Средняя оценка», «Первая попытка», «Последняя попытка»), а его же
    # значение по умолчанию не проходит собственную проверку, поэтому передаём явно.
    # При одной попытке разницы нет. Если язык сайта не русский, укажите название на нём.
    grade_method: str = "Высшая оценка"
    extra: dict = field(default_factory=dict)  # любые другие поля config плагина

    def to_config(self, course_id: int) -> dict:
        config: dict = {
            "quizname": self.name,
            "courseid": int(course_id),
            "section": int(self.section),
            "visible": int(self.visible),
            "attempts": int(self.attempts),
            "timelimit": int(self.time_limit_minutes) * 60,  # плагин ждёт секунды
            "shuffleanswers": int(self.shuffle_answers),
            "questionsperpage": int(self.questions_per_page),
            "navmethod": self.navigation,
            "preferredbehaviour": self.behaviour,
            "grademethod": self.grade_method,
        }
        if self.show_marks:
            # Флаги «Параметры просмотра»: оценка видна сразу после попытки, пока тест открыт и после закрытия.
            for when in ("immediately", "open", "closed"):
                config[f"marks{when}"] = 1
        config.update(self.extra)
        return config


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
            text = f"Moodle вернул ошибку: {message}" + (f" ({code})" if code else "")
            # Подробности (например, текст ошибки базы данных) Moodle присылает только в режиме отладки
            debug = str(data.get("debuginfo") or "").strip()
            if debug:
                text += f"\nПодробности от Moodle: {debug[:800]}".replace(self.token, "ТОКЕН")
            raise MoodleError(text)
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

    # --- создание теста в курсе (плагин local_qbankremotemanager) -------------

    def plugin_available(self) -> bool:
        """Есть ли на сайте плагин создания тестов и включена ли его функция в службе."""
        try:
            self.call(PING_FUNCTION)
        except MoodleError:
            return False
        return True

    def question_categories(self, course_id: int) -> list[dict]:
        """Папки банка вопросов курса: список {'id': ..., 'name': ...} (поля как вернёт плагин)."""
        data = self.call(CATEGORIES_FUNCTION, courseid=course_id)
        if isinstance(data, dict):
            data = data.get("categories", [])
        return data if isinstance(data, list) else []

    def section_number(self, course_id: int, name: str = QUIZ_SECTION_NAME) -> int | None:
        """
        Номер раздела курса по его названию (0 — верхний общий раздел) или None, если такого нет.
        Нужна функция core_course_get_contents в службе «Генератор тестов».
        """
        data = self.call("core_course_get_contents", courseid=course_id,
                         **{"options[0][name]": "excludecontents", "options[0][value]": 1})
        if not isinstance(data, list):
            raise MoodleError("Moodle не вернул список разделов курса. Проверьте, что функция "
                              "core_course_get_contents добавлена в службу.")
        wanted = name.strip().casefold()
        for section in data:
            if str(section.get("name", "")).strip().casefold() == wanted:
                return int(section["section"])
        return None

    def create_quiz(self, course_id: int, xml_text: str, settings: QuizSettings,
                    filename: str = "quiz.xml") -> dict:
        """
        Создаёт тест в курсе: плагин сам загружает вопросы из Moodle XML в банк вопросов
        и добавляет их в новый тест. Возвращает {'cmid': ..., 'questions': ..., 'url': ...}.

        Внимание: защиты от дублей нет — повторный вызов создаст ещё один тест.
        """
        itemid = self.upload_draft(filename, xml_text.encode("utf-8"))
        params: dict = {f"config[{key}]": value for key, value in settings.to_config(course_id).items()}
        params["itemid"] = itemid
        params["shuffle"] = int(settings.shuffle_questions)
        result = self.call(QUIZ_FUNCTION, **params)
        if not isinstance(result, dict):
            raise MoodleError(f"Плагин ответил в неожиданном формате: {result}")
        if result.get("status") != "OK":
            raise MoodleError(f"Тест не создан: {result.get('error_message') or result}")
        cmid = int(result["quizid"])  # плагин называет quizid номер модуля курса (cmid)
        return {
            "cmid": cmid,
            "questions": int(result.get("num_of_questions", 0)),
            "url": f"{self.base_url}/mod/quiz/view.php?id={cmid}",
        }
