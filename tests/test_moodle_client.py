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
