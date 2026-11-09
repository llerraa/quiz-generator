from src.moodle.client import MoodleClient
from src.moodle.registry import (
    F_RESULT_AIKEN, F_RESULT_GIFT, F_RESULT_XML, F_STATUS, F_REPORT, F_SOURCE, F_COURSE_LINK, MoodleRegistry,
    course_id_from_link,
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
            names = [F_COURSE_LINK, F_SOURCE, F_RESULT_XML, F_RESULT_AIKEN, F_STATUS, F_REPORT]
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
    assert course_id_from_link("https://m.example/course/view.php?id=16") == 16
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


def test_save_result_without_status_keeps_status_untouched():
    client = FakeClient()
    MoodleRegistry(client, 17).save_result(7, xml_text="<x/>", report="ок")
    _, params = client.calls[-1]
    assert params["data[0][value]"] == '"ок"'
    assert all('"Обработан"' not in str(v) for v in params.values())


def test_gift_file_written_only_when_column_exists():
    client = FakeClient()
    reg = MoodleRegistry(client, 17)
    reg.save_result(7, gift_text="::q:: q {=A. a}", report="ок")  # колонки GIFT в базе нет
    assert "data[1][subfield]" not in client.calls[-1][1]
    reg._fields[F_RESULT_GIFT] = {"id": 9}
    reg.save_result(7, gift_text="::q:: q {=A. a}", report="ок")
    params = client.calls[-1][1]
    assert params["data[1][subfield]"] == "file" and params["data[1][fieldid]"] == 9


def test_entry_modified_time_is_read():
    class C(FakeClient):
        def call(self, function, **params):
            data = super().call(function, **params)
            if function == "mod_data_get_entries":
                data["entries"][0]["timemodified"] = 1760000000
            return data
    assert MoodleRegistry(C(), 17).entries()[0].modified == 1760000000


# --- публикация -------------------------------------------------------------
from types import SimpleNamespace

from src.moodle.publish import UploadLog, can_publish, fingerprint, make_rework_report, make_report


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
    assert "2 из 25" in text and "Пропущено: 1" in text
    assert "Требуется" not in text and "CAPS" not in text and text.splitlines()[0] == "Вошло вопросов: 2 из 25."


def test_make_report_never_mentions_tokens_and_shows_quiz_link():
    res = SimpleNamespace(questions=list(range(25)), target=25, skipped=[], errors=[], source="llm")
    usage = SimpleNamespace(calls=3, estimated_caps=5000.0)
    text = make_report(res, usage, 25, quiz_url="https://m/mod/quiz/view.php?id=5")
    assert text.splitlines() == ["Вошло вопросов: 25 из 25.", "Тест создан в курсе: https://m/mod/quiz/view.php?id=5"]


def test_review_note_is_added_only_when_set(monkeypatch):
    import src.moodle.publish as publish
    res = SimpleNamespace(questions=[1], target=25, skipped=[], errors=[], source="aiken")
    monkeypatch.setattr(publish, "REVIEW_NOTE", "Требуется выборочная проверка вопросов.")
    assert publish.make_report(res).splitlines()[-1] == "Требуется выборочная проверка вопросов."
    assert "Требуется" not in publish.make_report(res, quiz_url="https://m/q")


def test_rework_report_lists_reasons():
    skipped = [SimpleNamespace(title="Вопрос 1", reason="не найдена пометка правильного ответа")]
    res = SimpleNamespace(questions=[], target=25, skipped=skipped)
    text = make_rework_report(res)
    assert "0 из 25" in text and "не найдена пометка" in text and "отправлен преподавателю на доработку" in text


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


# --- новая база: другие названия колонок, без колонки XML ---------------------------------

class NewBaseClient(FakeClient):
    """Колонки как в текущей базе ИМЭС (регистр и пробелы в названиях могут отличаться)."""
    def call(self, function, **params):
        if function == "mod_data_get_fields":
            self.calls.append((function, params))
            names = ["Наименование курса", "Ссылка на курс", "Вид контроля", "Учебная группа", "Преподаватель",
                     "Кафедра", "Файл от зав кафедрой", "Статус", "проверенный  файл", "Файл (GIFT) для заливки", "Отчёт"]
            return {"fields": [{"id": 10 + i, "name": n} for i, n in enumerate(names)]}
        return super().call(function, **params)


def test_new_base_columns_are_recognised_case_insensitively():
    reg = MoodleRegistry(NewBaseClient(), 17)
    assert reg.check_fields() == []
    assert F_RESULT_AIKEN in reg.fields() and F_RESULT_GIFT in reg.fields() and F_RESULT_XML not in reg.fields()


def test_save_result_skips_missing_xml_column_and_writes_checked_and_gift_files():
    client = NewBaseClient()
    MoodleRegistry(client, 17).save_result(7, xml_text="<x/>", aiken_text="Q", gift_text="G", report="ок")
    _, params = client.calls[-1]
    file_fields = [v for k, v in params.items() if k.endswith("[subfield]") and v == "file"]
    assert len(file_fields) == 2  # Aiken и GIFT; XML в базе нет, поэтому не пишется
    assert params["data[1][fieldid]"] == 18 and params["data[2][fieldid]"] == 19


def test_exception_column_is_read_and_empty_by_default():
    reg = MoodleRegistry(FakeClient(), 17)
    entry = reg.find_by_course(16)[0]
    assert entry.exception == ""  # в тестовой базе колонки «Исключения» нет
    entry.values["Исключения"] = "Тест не нужен"
    assert entry.exception == "Тест не нужен"
