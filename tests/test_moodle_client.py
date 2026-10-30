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
    assert result == {"cmid": 42, "questions": 25, "url": "https://moodle.test/mod/quiz/view.php?id=42"}
    data = post.call_args_list[1].kwargs["data"]
    assert data["wsfunction"] == "local_qbankremotemanager_upload_quiz"
    assert data["itemid"] == 77
    assert data["shuffle"] == 1
    assert data["config[quizname]"] == "Экзамен"
    assert data["config[courseid]"] == 16
    assert data["config[visible]"] == 0


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
