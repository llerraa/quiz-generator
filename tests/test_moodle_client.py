"""Тесты для src/moodle/client.py: Moodle подменяем, реальных запросов нет."""
from unittest.mock import MagicMock, patch

import pytest

from src.moodle.client import MoodleClient, MoodleError


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def _client():
    return MoodleClient(base_url="https://moodle.test/", token="SECRET")


def test_requires_url_and_token(monkeypatch):
    monkeypatch.setattr("src.moodle.client.Config.MOODLE_URL", None)
    monkeypatch.setattr("src.moodle.client.Config.MOODLE_TOKEN", None)
    with pytest.raises(MoodleError):
        MoodleClient()


def test_site_info_sends_token_and_function():
    with patch("src.moodle.client.requests.post", return_value=_resp({"release": "4.5.6"})) as post:
        info = _client().site_info()
    assert info["release"] == "4.5.6"
    url = post.call_args.args[0]
    assert url == "https://moodle.test/webservice/rest/server.php"
    data = post.call_args.kwargs["data"]
    assert data["wsfunction"] == "core_webservice_get_site_info"
    assert data["wstoken"] == "SECRET"


def test_moodle_error_becomes_readable_and_has_no_token():
    err = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Неверный токен"}
    with patch("src.moodle.client.requests.post", return_value=_resp(err)):
        with pytest.raises(MoodleError) as exc:
            _client().site_info()
    assert "Неверный токен" in str(exc.value)
    assert "SECRET" not in str(exc.value)


def test_network_error_does_not_leak_token():
    import requests

    with patch("src.moodle.client.requests.post", side_effect=requests.ConnectionError("https://x?wstoken=SECRET")):
        with pytest.raises(MoodleError) as exc:
            _client().site_info()
    assert "SECRET" not in str(exc.value)


def test_upload_returns_itemid():
    with patch("src.moodle.client.requests.post", return_value=_resp([{"itemid": 987, "filename": "a.xml"}])) as post:
        assert _client().upload_draft("a.xml", b"<quiz/>") == 987
    assert post.call_args.args[0].endswith("/webservice/upload.php")
    assert post.call_args.kwargs["data"]["token"] == "SECRET"


def test_upload_error_when_no_itemid():
    with patch("src.moodle.client.requests.post", return_value=_resp([])):
        with pytest.raises(MoodleError):
            _client().upload_draft("a.xml", b"x")


def test_import_xml_uploads_then_calls_function():
    responses = [_resp([{"itemid": 55}]), _resp({"status": True, "message": "Successfully imported 3 questions from XML."})]
    with patch("src.moodle.client.requests.post", side_effect=responses) as post:
        message = _client().import_xml(16, "<quiz/>")
    assert "3 questions" in message
    second = post.call_args_list[1].kwargs["data"]
    assert second["wsfunction"] == "local_questions_importer_ws_import_xml"
    assert second["courseid"] == 16 and second["draftitemid"] == 55


def test_import_xml_fails_when_plugin_says_no():
    responses = [_resp([{"itemid": 55}]), _resp({"status": False, "message": "нет"})]
    with patch("src.moodle.client.requests.post", side_effect=responses):
        with pytest.raises(MoodleError):
            _client().import_xml(16, "<quiz/>")


# --- создание теста в курсе (плагин local_qbankremotemanager) ---------------

from src.moodle.client import QuizSettings


def test_quiz_settings_to_config_converts_units():
    config = QuizSettings(name="Тест", time_limit_minutes=30, attempts=2, extra={"navmethod": "free"}).to_config(16)
    assert config["quizname"] == "Тест"
    assert config["courseid"] == 16
    assert config["visible"] == 0  # по умолчанию тест скрыт
    assert config["timelimit"] == 1800  # минуты → секунды
    assert config["attempts"] == 2
    assert config["navmethod"] == "free"
    # плагин не принимает свой же вариант по умолчанию, поэтому способ оценивания передаём всегда
    assert config["grademethod"] == "Высшая оценка"


def test_create_quiz_uploads_then_sends_flat_config():
    responses = [_resp([{"itemid": 77}]), _resp({"quizid": 42, "status": "OK", "num_of_questions": 25})]
    with patch("src.moodle.client.requests.post", side_effect=responses) as post:
        result = _client().create_quiz(16, "<quiz/>", QuizSettings(name="Экзамен", shuffle_questions=True))
    assert result == {"cmid": 42, "questions": 25, "url": "https://moodle.test/mod/quiz/view.php?id=42",
                      "warnings": []}
    data = post.call_args_list[1].kwargs["data"]
    assert data["wsfunction"] == "local_qbankremotemanager_upload_quiz"
    assert data["itemid"] == 77
    assert data["shuffle"] == 1
    assert data["config[quizname]"] == "Экзамен"
    assert data["config[courseid]"] == 16
    assert data["config[visible]"] == 0
    # идентификационный номер теста (плагин imes2); формулу категории приложение не трогает
    assert data["config[cmidnumber]"] == "ПА-тест" and "config[appendtogradecalc]" not in data


def test_create_quiz_plugin_error_becomes_readable():
    responses = [_resp([{"itemid": 1}]), _resp({"status": "ERROR", "error_message": "No questions in file"})]
    with patch("src.moodle.client.requests.post", side_effect=responses):
        with pytest.raises(MoodleError) as exc:
            _client().create_quiz(16, "<quiz/>", QuizSettings(name="X"))
    assert "No questions in file" in str(exc.value)
    assert "SECRET" not in str(exc.value)


def test_plugin_available_false_when_function_missing():
    err = {"exception": "webservice_access_exception", "errorcode": "accessexception", "message": "Нет доступа"}
    with patch("src.moodle.client.requests.post", return_value=_resp(err)):
        assert _client().plugin_available() is False
    with patch("src.moodle.client.requests.post", return_value=_resp("OK")):
        assert _client().plugin_available() is True


def test_section_number_found_by_name_ignoring_case_and_spaces():
    sections = [{"name": "Общее", "section": 0}, {"name": " промежуточная аттестация ", "section": 3}]
    with patch("src.moodle.client.requests.post", return_value=_resp(sections)) as post:
        assert _client().section_number(16) == 3
    data = post.call_args.kwargs["data"]
    assert data["wsfunction"] == "core_course_get_contents"
    assert data["courseid"] == 16


def test_section_number_none_when_missing():
    with patch("src.moodle.client.requests.post", return_value=_resp([{"name": "Общее", "section": 0}])):
        assert _client().section_number(16) is None


def test_section_number_error_when_function_returns_garbage():
    with patch("src.moodle.client.requests.post", return_value=_resp({"x": 1})):
        with pytest.raises(MoodleError):
            _client().section_number(16)


def test_moodle_debuginfo_is_shown_without_token():
    err = {"exception": "dml_write_exception", "errorcode": "dmlwriteexception",
           "message": "Ошибка записи в базу данных", "debuginfo": "Column 'x' cannot be null (token SECRET)"}
    with patch("src.moodle.client.requests.post", return_value=_resp(err)):
        with pytest.raises(MoodleError) as exc:
            _client().site_info()
    assert "cannot be null" in str(exc.value)
    assert "SECRET" not in str(exc.value)


def test_quiz_settings_defaults_are_exam_friendly():
    config = QuizSettings(name="Т").to_config(16)
    assert config["timelimit"] == 40 * 60
    assert config["attempts"] == 1
    assert config["questionsperpage"] == 1
    assert config["navmethod"] == "free"
    assert config["preferredbehaviour"] == "deferredfeedback"
    # студент видит оценку, но не правильные ответы
    assert config["marksimmediately"] == config["marksopen"] == config["marksclosed"] == 1
    assert "rightanswerimmediately" not in config
    assert "gradepass" not in config  # проходного балла нет


def test_quiz_settings_can_hide_marks():
    config = QuizSettings(name="Т", show_marks=False).to_config(16)
    assert "marksimmediately" not in config


# --- название дисциплины из «Полей из 1С» ------------------------------------------------

def _course_client(courses):
    class C(MoodleClient):
        def call(self, function, **params):
            assert function == "core_course_get_courses_by_field"
            return {"courses": courses}
    return C(base_url="https://m.example", token="T")


def test_course_info_reads_discipline_from_custom_fields():
    course = {"fullname": "Анатомия (ЛД, 2026)", "customfields": [
        {"name": "Код дисциплины", "shortname": "code", "valueraw": "000000353"},
        {"name": "Название дисциплины", "shortname": "disc", "valueraw": "<p>Анатомия и физиология ЦНС </p>"},
    ]}
    info = _course_client([course]).course_info(16)
    assert info["name"] == "Анатомия (ЛД, 2026)"
    assert info["discipline"] == "Анатомия и физиология ЦНС"
    assert info["custom_fields"] == ["Код дисциплины", "Название дисциплины"]


def test_course_info_finds_discipline_by_short_name_on_test_site():
    # на m45 поле называется discipline_name, а discipline_code пустое
    course = {"fullname": "Курс 16", "customfields": [
        {"name": "discipline_code", "shortname": "discipline_code", "valueraw": ""},
        {"name": "discipline_name", "shortname": "discipline_name", "valueraw": "d_name_test"},
    ]}
    assert _course_client([course]).course_info(16)["discipline"] == "d_name_test"


def test_course_info_empty_discipline_field_is_none():
    course = {"fullname": "К", "customfields": [{"name": "discipline_name", "shortname": "discipline_name", "valueraw": "  "}]}
    info = _course_client([course]).course_info(16)
    assert info["discipline"] is None and info["custom_fields"] == ["discipline_name"]


def test_course_info_without_custom_field_or_course():
    assert _course_client([{"fullname": "К"}]).course_info(1) == {"name": "К", "discipline": None, "custom_fields": []}
    assert _course_client([]).course_info(1) == {"name": None, "discipline": None, "custom_fields": []}


def test_quiz_title():
    from src.moodle.client import quiz_title
    assert quiz_title("Анатомия") == "Тест. Промежуточная аттестация по дисциплине Анатомия"
    assert quiz_title("  ") == quiz_title(None) == "Тест. Промежуточная аттестация"


# --- категория журнала оценок -------------------------------------------------------------

EXPECTED_ERROR = ("Moodle вернул ошибку: Wrong value for gradecat entered. Expected one of: [ Не определено, "
                  "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ (максимум можно набрать 50 баллов), "
                  "ТЕКУЩИЙ КОНТРОЛЬ (максимум можно набрать 50 баллов),] but was __список_категорий__. "
                  "(badargument_with_expected_values)")


def test_quiz_settings_pass_grade_category_name_to_plugin():
    assert "gradecat" not in QuizSettings(name="Т").to_config(16)
    assert QuizSettings(name="Т", grade_category="Кат").to_config(16)["gradecat"] == "Кат"


def test_parse_expected_values_reads_plugin_error():
    from src.moodle.client import parse_expected_values
    assert parse_expected_values(EXPECTED_ERROR) == [
        "Не определено",
        "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ (максимум можно набрать 50 баллов)",
        "ТЕКУЩИЙ КОНТРОЛЬ (максимум можно набрать 50 баллов)",
    ]
    assert parse_expected_values("что-то другое") is None


def test_pick_grade_category_matches_prefix_ignoring_case_and_spaces():
    from src.moodle.client import pick_grade_category
    names = ["Не определено", "Промежуточная  аттестация (50)", "Текущий контроль"]
    assert pick_grade_category(names) == "Промежуточная  аттестация (50)"
    assert pick_grade_category(["Не определено"]) is None
    assert pick_grade_category(None) is None


def test_grade_categories_asks_plugin_with_invalid_name_and_parses_error():
    seen = {}

    class C(MoodleClient):
        def call(self, function, **params):
            seen.update(params, function=function)
            raise MoodleError(EXPECTED_ERROR)

    names = C(base_url="https://m.example", token="T").grade_categories(16)
    assert names[1].startswith("ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ")
    assert seen["function"] == "local_qbankremotemanager_upload_quiz"
    assert seen["config[gradecat]"] == "__список_категорий__" and seen["itemid"] == 0


def test_grade_categories_unknown_when_plugin_gives_other_error():
    class C(MoodleClient):
        def call(self, function, **params):
            raise MoodleError("Moodle вернул ошибку: нет прав")

    assert C(base_url="https://m.example", token="T").grade_categories(16) is None


def test_grade_categories_refuses_silently_created_quiz():
    class C(MoodleClient):
        def call(self, function, **params):
            return {"status": "OK", "quizid": 77}

    import pytest
    with pytest.raises(MoodleError, match="77"):
        C(base_url="https://m.example", token="T").grade_categories(16)


# --- идентификационный номер теста (плагин imes2) --------------------------------------------

def test_quiz_settings_idnumber():
    config = QuizSettings(name="Т").to_config(16)
    assert config["cmidnumber"] == "ПА-тест" and "appendtogradecalc" not in config
    config = QuizSettings(name="Т", idnumber=None).to_config(16)
    assert "cmidnumber" not in config
    assert QuizSettings(name="Т", idnumber="ПА-другой").to_config(16)["cmidnumber"] == "ПА-другой"


def test_create_quiz_on_old_plugin_retries_without_idnumber_and_warns():
    unexpected = {"exception": "invalid_parameter_exception", "errorcode": "invalidparameter",
                  "message": "Invalid parameter value detected",
                  "debuginfo": "config => Unexpected keys (cmidnumber) detected in parameter array."}
    responses = [_resp([{"itemid": 5}]), _resp(unexpected), _resp({"quizid": 9, "status": "OK", "num_of_questions": 2})]
    with patch("src.moodle.client.requests.post", side_effect=responses) as post:
        result = _client().create_quiz(16, "<quiz/>", QuizSettings(name="Т"))
    assert result["cmid"] == 9
    assert any("не поддерживает идентификационный номер" in w for w in result["warnings"])
    first, retry = post.call_args_list[1].kwargs["data"], post.call_args_list[2].kwargs["data"]
    assert "config[cmidnumber]" in first and "config[cmidnumber]" not in retry
    assert retry["itemid"] == 5


def test_create_quiz_does_not_retry_on_other_errors():
    err = {"exception": "moodle_exception", "errorcode": "cmidnumber_taken",
           "message": 'The ID number "ПА" is already used in this course.'}
    with patch("src.moodle.client.requests.post", side_effect=[_resp([{"itemid": 5}]), _resp(err)]) as post:
        with pytest.raises(MoodleError, match="already used"):
            _client().create_quiz(16, "<quiz/>", QuizSettings(name="Т"))
    assert post.call_count == 2


def test_create_quiz_shows_plugin_remark_as_warning():
    ok = {"quizid": 9, "status": "OK", "num_of_questions": 2, "error_message": "Какое-то замечание плагина"}
    with patch("src.moodle.client.requests.post", side_effect=[_resp([{"itemid": 5}]), _resp(ok)]):
        result = _client().create_quiz(16, "<quiz/>", QuizSettings(name="Т"))
    assert result["warnings"] == ["Какое-то замечание плагина"]


def test_grade_categories_probe_does_not_send_imes2_fields():
    # старый плагин отклонил бы cmidnumber раньше, чем проверил категорию, и список не получился бы
    seen = {}

    class C(MoodleClient):
        def call(self, function, **params):
            seen.update(params)
            raise MoodleError(EXPECTED_ERROR)

    assert C(base_url="https://m.example", token="T").grade_categories(16)
    assert "config[cmidnumber]" not in seen


def test_grade_categories_remembers_reason_when_list_is_unavailable():
    class C(MoodleClient):
        def call(self, function, **params):
            raise MoodleError("Moodle вернул ошибку: Invalid parameter value detected (invalidparameter)")

    client = C(base_url="https://m.example", token="T")
    assert client.grade_categories(16) is None
    assert "invalidparameter" in client.grade_categories_error
