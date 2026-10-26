from src.moodle.client import MoodleClient
from src.moodle.registry import (
    F_RESULT_XML, F_STATUS, F_REPORT, F_SOURCE, F_COURSE_LINK, MoodleRegistry, course_id_from_link,
)


class FakeClient(MoodleClient):
    def __init__(self):
        super().__init__(base_url="https://m.example", token="SECRET")
        self.calls = []

    def call(self, function, **params):
        self.calls.append((function, params))
        if function == "mod_data_get_databases_by_courses":
            return {"databases": [{"id": 5, "name": "Реестр"}]}
        if function == "mod_data_get_fields":
            names = [F_COURSE_LINK, F_SOURCE, F_RESULT_XML, "Обработанный файл (Aiken, для чтения)", F_STATUS, F_REPORT]
            return {"fields": [{"id": 10 + i, "name": n} for i, n in enumerate(names)]}
        if function == "mod_data_get_entries":
            return {"entries": [{"id": 7, "contents": [
                {"fieldid": 10, "content": "https://m/course/view.php?id=16"},
                {"fieldid": 11, "content": "a.docx", "files": [{"filename": "a.docx", "fileurl": "https://m/webservice/pluginfile.php/1/a.docx"}]},
                {"fieldid": 14, "content": "<p>Не обработан</p>"},
            ]}]}
        return {}

    def upload_draft(self, filename, content):
        return 99


def test_course_id_from_link():
    assert course_id_from_link("https://m45.umu.vstu.ru/course/view.php?id=16") == 16
    assert course_id_from_link("нет ссылки") is None


def test_entries_parsed_by_field_name():
    reg = MoodleRegistry(FakeClient(), 17)
    entry = reg.find_by_course(16)[0]
    assert entry.entry_id == 7
    assert entry.status == "Не обработан"
    assert entry.files[F_SOURCE][0].name == "a.docx"
    assert reg.find_by_course(99) == []


def test_check_fields_reports_missing():
    assert MoodleRegistry(FakeClient(), 17).check_fields() == []


def test_save_result_sends_files_status_report():
    client = FakeClient()
    MoodleRegistry(client, 17).save_result(7, xml_text="<x/>", aiken_text="Q", status="Обработан", report="ок")
    function, params = client.calls[-1]
    assert function == "mod_data_update_entry"
    assert params["entryid"] == 7
    assert params["data[2][subfield]"] == "file" and params["data[2][value]"] == "99"
    assert params["data[0][value]"] == '"Обработан"'


# --- публикация -------------------------------------------------------------
from types import SimpleNamespace

from src.moodle.publish import UploadLog, can_publish, fingerprint, make_report


def test_fingerprint_depends_on_course_folder_and_content():
    a = fingerprint(16, "Папка", "<x/>")
    assert a == fingerprint(16, "Папка", "<x/>")
    assert a != fingerprint(17, "Папка", "<x/>")
    assert a != fingerprint(16, "Другая", "<x/>")
    assert a != fingerprint(16, "Папка", "<y/>")


def test_upload_log_remembers(tmp_path):
    log = UploadLog(tmp_path / "sub" / "log.json")
    fp = fingerprint(16, "П", "<x/>")
    assert log.find(fp) is None
    log.add(fp, 16, "П", 25)
    assert log.find(fp)["questions"] == 25
    assert UploadLog(tmp_path / "sub" / "log.json").find(fp)["course_id"] == 16


def test_can_publish_blocks_partial_or_empty():
    assert can_publish(None)[0]
    assert not can_publish(SimpleNamespace(budget_error="лимит", questions=[1]))[0]
    assert not can_publish(SimpleNamespace(budget_error="", questions=[]))[0]
    assert can_publish(SimpleNamespace(budget_error="", questions=[1]))[0]


def test_make_report_mentions_counts():
    res = SimpleNamespace(questions=[1, 2], target=25, skipped=[1], errors=[], source="aiken")
    text = make_report(res, None, 2)
    assert "2 из 25" in text and "Пропущено: 1" in text and "без ИИ" in text


# --- название курса ---------------------------------------------------------
from src.moodle.client import MoodleError


def test_course_name_found_missing_and_error():
    class C(MoodleClient):
        def __init__(self, reply):
            super().__init__(base_url="https://m.example", token="SECRET")
            self.reply = reply

        def call(self, function, **params):
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    assert C({"courses": [{"fullname": "Основы Python"}]}).course_name(16) == "Основы Python"
    assert C({"courses": []}).course_name(99) is None
    assert C(MoodleError("нет прав")).course_name(16) is None
