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

import re
from dataclasses import dataclass, field

import requests

from src.config import Config

IMPORT_FUNCTION = "local_questions_importer_ws_import_xml"
# Плагин local_qbankremotemanager: создаёт тест в курсе и кладёт в него вопросы из Moodle XML
PING_FUNCTION = "local_qbankremotemanager_am_i_here"
QUIZ_FUNCTION = "local_qbankremotemanager_upload_quiz"
CATEGORIES_FUNCTION = "local_qbankremotemanager_get_question_categories"
# --- Предохранители: приложение ничего не меняет в журнале оценок и в настройках курса ---
# Функции Moodle, которые вообще разрешено вызывать. Всё остальное (в том числе любая функция
# изменения журнала, курса или пользователей) client.call() отклонит до отправки запроса.
# Записывающих здесь три: загрузка вопросов, создание теста и обновление записи реестра.
ALLOWED_FUNCTIONS = frozenset({
    "core_webservice_get_site_info",
    "core_course_get_courses_by_field",
    "core_course_get_contents",
    "mod_data_get_databases_by_courses",
    "mod_data_get_fields",
    "mod_data_get_entries",
    "mod_data_update_entry",
    IMPORT_FUNCTION,
    PING_FUNCTION,
    QUIZ_FUNCTION,
    CATEGORIES_FUNCTION,
})
# Параметры config для upload_quiz, которые приложение вообще может отправить.
# Формула категории журнала (appendtogradecalc) сюда НЕ входит: формулы менеджеры правят вручную.
# Любой другой ключ (в том числе из QuizSettings.extra) приведёт к ошибке до отправки запроса.
ALLOWED_QUIZ_CONFIG_KEYS = frozenset({
    "quizname", "courseid", "section", "visible", "attempts", "timelimit", "shuffleanswers",
    "questionsperpage", "navmethod", "preferredbehaviour", "grademethod", "gradecat", "cmidnumber",
    "marksimmediately", "marksopen", "marksclosed",
})
FORBIDDEN_QUIZ_CONFIG_KEYS = frozenset({"appendtogradecalc"})
# Название раздела курса, куда кладётся новый тест (в шаблоне курсов ЭИОС оно одинаковое)
QUIZ_SECTION_NAME = "Промежуточная аттестация"
# Поле курса «Название дисциплины» (раздел настроек курса «Поля из 1С»): на боевой ЭИОС оно
# называется по-русски, на тестовом сайте по краткому имени. Совпадение ищется без учёта регистра.
DISCIPLINE_FIELD_NAMES = ("Название дисциплины", "discipline_name")
DISCIPLINE_FIELD = DISCIPLINE_FIELD_NAMES[0]
QUIZ_TITLE_PREFIX = "Тест. Промежуточная аттестация"
REQUEST_TIMEOUT = 60  # секунд


def quiz_title(discipline: str | None) -> str:
    """«Тест. Промежуточная аттестация по дисциплине {название}»; без названия дисциплины — без хвоста."""
    discipline = " ".join((discipline or "").split())
    return f"{QUIZ_TITLE_PREFIX} по дисциплине {discipline}"[:250] if discipline else QUIZ_TITLE_PREFIX


# Коды отказа Moodle, когда функция, служба или токен выключены или нет прав. Так выглядят и «рубильники»
# администратора (см. docs/DETAILS.md, раздел «Рубильники в Moodle»), поэтому к тексту добавляем пояснение.
ACCESS_DENIED_CODES = frozenset({
    "accessexception", "servicenotavailable", "invalidtoken", "webservicesnotenabled", "nopermissions",
})
ACCESS_DENIED_HINT = (
    "\nВозможно, администратор Moodle отключил эту возможность или токен. Повторять попытки не нужно: "
    "сообщите ответственному за Moodle (код ошибки указан выше)."
)


class MoodleError(Exception):
    """Moodle ответил ошибкой или недоступен. Текст понятен без знания Moodle."""


def check_quiz_config(config: dict) -> None:
    """Не даёт отправить в плагин параметры вне белого списка (в первую очередь формулы журнала)."""
    bad = sorted(set(config) - ALLOWED_QUIZ_CONFIG_KEYS)
    if bad:
        forbidden = sorted(set(bad) & FORBIDDEN_QUIZ_CONFIG_KEYS)
        raise MoodleError(
            "Приложение не отправляет в Moodle параметры " + ", ".join(bad)
            + (": изменение формул журнала запрещено, формулы правят менеджеры вручную." if forbidden
               else ": их нет в списке разрешённых.")
        )


def _custom_field(record: dict, titles) -> str | None:
    """Значение дополнительного поля курса по названию или краткому имени; None, если поля нет или оно пустое."""
    wanted = {t.casefold() for t in ([titles] if isinstance(titles, str) else titles)}
    for item in record.get("customfields") or []:
        names = {str(item.get("name", "")).strip().casefold(), str(item.get("shortname", "")).strip().casefold()}
        if wanted & names:
            value = re.sub(r"<[^>]+>", "", str(item.get("valueraw") or item.get("value") or ""))
            return " ".join(value.split()) or None
    return None


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
    # Категория журнала оценок: плагин принимает её НАЗВАНИЕ (с учётом регистра, как в журнале).
    # None — не передавать: Moodle положит тест в корень журнала, вне категорий.
    grade_category: str | None = None
    # Идентификационный номер теста в журнале оценок: на него ссылаются формулы категорий ([[ПА]]).
    # Формулу категории приложение НЕ меняет: её правят менеджеры вручную.
    # Нужна версия плагина imes2; на старой тест создаётся без номера (см. create_quiz). Пусто — не задавать.
    idnumber: str | None = "ПА-тест"
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
        if self.grade_category:
            config["gradecat"] = self.grade_category
        if self.idnumber:
            config["cmidnumber"] = self.idnumber
        if self.show_marks:
            # Флаги «Параметры просмотра»: оценка видна сразу после попытки, пока тест открыт и после закрытия.
            for when in ("immediately", "open", "closed"):
                config[f"marks{when}"] = 1
        config.update(self.extra)
        check_quiz_config(config)
        return config


# Категория журнала оценок, куда кладём тест (раздел курса «Промежуточная аттестация»)
GRADE_CATEGORY_PREFIX = "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ"
# Заведомо несуществующее название: плагин проверяет его до создания чего-либо и в ошибке перечисляет все категории
_GRADE_PROBE = "__список_категорий__"
_EXPECTED_RE = re.compile(r"Expected one of:\s*\[(.*)\]\s*but was", re.S)


# Поля config, которые понимает только плагин версии imes2
_NEW_PLUGIN_KEYS = {"cmidnumber"}


def _is_unknown_keys_error(message: str) -> bool:
    """Moodle отклонил поля, которых нет в описании функции (плагин старой версии)."""
    lowered = message.lower()
    return "unexpected keys" in lowered or "invalidparameter" in lowered or "invalid parameter" in lowered


def parse_expected_values(message: str) -> list[str] | None:
    """Список допустимых значений из ошибки плагина «Expected one of: [ a, b, c,] but was …»; None — не нашли."""
    match = _EXPECTED_RE.search(message)
    if not match:
        return None
    values = [part.strip() for part in match.group(1).split(",")]
    return [v for v in values if v] or None


def pick_grade_category(names: list[str] | None, prefix: str = GRADE_CATEGORY_PREFIX) -> str | None:
    """Категория, название которой начинается с prefix (без учёта регистра и лишних пробелов); иначе None."""
    wanted = " ".join(prefix.split()).casefold()
    for name in names or []:
        if " ".join(name.split()).casefold().startswith(wanted):
            return name
    return None


class MoodleClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or Config.MOODLE_URL or "").rstrip("/")
        self.token = token or Config.MOODLE_TOKEN
        self.grade_categories_error: str | None = None  # почему не удалось получить категории журнала
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
            if code in ACCESS_DENIED_CODES:
                text += ACCESS_DENIED_HINT
            # Подробности (например, текст ошибки базы данных) Moodle присылает только в режиме отладки
            debug = str(data.get("debuginfo") or "").strip()
            if debug:
                text += f"\nПодробности от Moodle: {debug[:800]}".replace(self.token, "ТОКЕН")
            raise MoodleError(text)
        return data

    def call(self, function: str, **params) -> object:
        """Вызов функции веб-сервиса через REST (только из списка ALLOWED_FUNCTIONS)."""
        if function not in ALLOWED_FUNCTIONS:
            raise MoodleError(f"Приложению не разрешено вызывать функцию Moodle {function}.")
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

    def course_record(self, course_id: int) -> dict | None:
        """Описание курса из Moodle (в том числе дополнительные поля) или None. Ошибки не выбрасываем."""
        try:
            data = self.call("core_course_get_courses_by_field", field="id", value=course_id)
        except MoodleError:
            return None
        courses = data.get("courses", []) if isinstance(data, dict) else []
        return courses[0] if courses else None

    def course_name(self, course_id: int) -> str | None:
        """
        Полное название курса или None (курса нет, нет прав или функции нет в службе).
        Нужно только для показа пользователю, поэтому ошибки не выбрасываем.
        """
        record = self.course_record(course_id)
        return (record.get("fullname") or None) if record else None

    def course_info(self, course_id: int) -> dict:
        """Название курса и «Название дисциплины» из полей курса (из 1С): {'name', 'discipline', 'custom_fields'}; нет данных — None."""
        record = self.course_record(course_id)
        if not record:
            return {"name": None, "discipline": None, "custom_fields": []}
        found = [str(i.get("name") or i.get("shortname") or "?") for i in record.get("customfields") or []]
        return {
            "name": record.get("fullname") or None,
            "discipline": _custom_field(record, DISCIPLINE_FIELD_NAMES),
            "custom_fields": found,  # что Moodle вернул: помогает понять, почему дисциплина не нашлась
        }

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

    def grade_categories(self, course_id: int, section: int = 0) -> list[str] | None:
        """
        Названия категорий журнала оценок курса или None, если узнать не удалось.

        У плагина нет отдельной функции для списка категорий, зато он проверяет `gradecat` ДО импорта
        вопросов и создания теста и перечисляет допустимые значения в тексте ошибки. Поэтому спрашиваем его
        заведомо неверным названием: ничего не создаётся. Список разбирается по запятым, поэтому название
        категории с запятой внутри здесь разделится на части (в журнале ИМЭС таких нет).
        """
        # Без идентификационного номера: поля imes2 старый плагин отклонил бы раньше, чем дошёл бы до категорий
        config = QuizSettings(name="probe", section=section, grade_category=_GRADE_PROBE,
                              idnumber=None).to_config(course_id)
        params = {f"config[{key}]": value for key, value in config.items()}
        params["itemid"] = 0
        self.grade_categories_error = None
        try:
            result = self.call(QUIZ_FUNCTION, **params)
        except MoodleError as exc:
            names = parse_expected_values(str(exc))
            if names is None:
                self.grade_categories_error = str(exc)  # покажем в интерфейсе, чтобы было видно причину
            return names
        # Плагин не отклонил выдуманное название (другая версия): список получить нельзя.
        # Если вдруг тест всё же создан, выбрасываем исключение, чтобы это не прошло молча.
        if isinstance(result, dict) and result.get("status") == "OK":
            raise MoodleError("Проверка категорий журнала неожиданно создала тест "
                              f"(модуль {result.get('quizid')}). Удалите его в курсе.")
        self.grade_categories_error = f"Плагин не отклонил выдуманное название категории: {result}"
        return None

    def create_quiz(self, course_id: int, xml_text: str, settings: QuizSettings,
                    filename: str = "quiz.xml") -> dict:
        """
        Создаёт тест в курсе: плагин сам загружает вопросы из Moodle XML в банк вопросов
        и добавляет их в новый тест. Возвращает {'cmid': ..., 'questions': ..., 'url': ...}.

        Внимание: защиты от дублей нет — повторный вызов создаст ещё один тест.
        """
        itemid = self.upload_draft(filename, xml_text.encode("utf-8"))
        warnings: list[str] = []
        config = settings.to_config(course_id)
        try:
            result = self._upload_quiz(config, itemid, settings)
        except MoodleError as exc:
            if not _NEW_PLUGIN_KEYS & config.keys() or not _is_unknown_keys_error(str(exc)):
                raise
            # Плагин старой версии (imes1) не знает идентификационный номер: создаём тест без него
            for key in _NEW_PLUGIN_KEYS:
                config.pop(key, None)
            warnings.append(f"Плагин на сайте ещё не поддерживает идентификационный номер теста: тест создан без "
                            f"«{settings.idnumber}». Поставьте номер вручную в настройках теста или обновите плагин "
                            "до версии imes2.")
            result = self._upload_quiz(config, itemid, settings)
        if not isinstance(result, dict):
            raise MoodleError(f"Плагин ответил в неожиданном формате: {result}")
        if result.get("status") != "OK":
            raise MoodleError(f"Тест не создан: {result.get('error_message') or result}")
        cmid = int(result["quizid"])  # плагин называет quizid номер модуля курса (cmid)
        if result.get("error_message"):  # статус OK, но плагин передал замечание
            warnings.append(str(result["error_message"]))
        return {
            "cmid": cmid,
            "questions": int(result.get("num_of_questions", 0)),
            "url": f"{self.base_url}/mod/quiz/view.php?id={cmid}",
            "warnings": warnings,
        }

    def _upload_quiz(self, config: dict, itemid: int, settings: QuizSettings) -> object:
        check_quiz_config(config)  # последняя проверка прямо перед отправкой
        params: dict = {f"config[{key}]": value for key, value in config.items()}
        params["itemid"] = itemid
        params["shuffle"] = int(settings.shuffle_questions)
        return self.call(QUIZ_FUNCTION, **params)
