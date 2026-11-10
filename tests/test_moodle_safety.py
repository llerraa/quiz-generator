"""Предохранители: приложение не меняет формулы журнала и не вызывает лишних функций Moodle."""
import itertools
import re
from pathlib import Path

import pytest

from src.moodle.client import (
    ALLOWED_FUNCTIONS, ALLOWED_QUIZ_CONFIG_KEYS, FORBIDDEN_QUIZ_CONFIG_KEYS, MoodleClient, MoodleError, QuizSettings,
    check_quiz_config,
)

SRC = Path(__file__).resolve().parent.parent / "src"


def test_every_combination_of_settings_sends_only_allowed_keys_and_no_formula():
    """Перебираем все комбинации переключателей: формульных и лишних ключей не бывает."""
    count = 0
    for (visible, shuffle_a, shuffle_q, show_marks, category, idnumber, attempts, nav, behaviour,
         method) in itertools.product(
            (True, False), (True, False), (True, False), (True, False),
            (None, "", "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ"), (None, "", "ПА-тест"),
            (0, 1, 3), ("free", "sequential"), ("deferredfeedback", "immediatefeedback"),
            ("Высшая оценка", "Первая попытка")):
        settings = QuizSettings(
            name="Тест", visible=visible, shuffle_answers=shuffle_a, shuffle_questions=shuffle_q,
            show_marks=show_marks, grade_category=category, idnumber=idnumber, attempts=attempts,
            navigation=nav, behaviour=behaviour, grade_method=method,
        )
        config = settings.to_config(16)
        assert set(config) <= ALLOWED_QUIZ_CONFIG_KEYS
        assert not set(config) & FORBIDDEN_QUIZ_CONFIG_KEYS
        count += 1
    assert count == 2 ** 4 * 3 * 3 * 3 * 2 * 2 * 2


@pytest.mark.parametrize("key", ["appendtogradecalc", "gradecalc", "deletequiz", "anything_else"])
def test_extra_cannot_smuggle_unknown_or_formula_keys(key):
    with pytest.raises(MoodleError) as exc:
        QuizSettings(name="Тест", extra={key: 1}).to_config(16)
    assert key in str(exc.value)


def test_formula_key_gets_explicit_explanation():
    with pytest.raises(MoodleError) as exc:
        check_quiz_config({"quizname": "x", "appendtogradecalc": "[[ПА]]"})
    assert "формул" in str(exc.value)


def test_known_extra_key_still_works():
    assert QuizSettings(name="Тест", extra={"attempts": 2}).to_config(16)["attempts"] == 2


def test_client_refuses_functions_outside_allowlist_without_sending(monkeypatch):
    client = MoodleClient("https://m.example", "T")
    sent = []
    monkeypatch.setattr(client, "_post", lambda *a, **k: sent.append((a, k)))
    for function in ("core_grades_update_grades", "core_course_delete_courses", "core_user_update_users",
                     "core_grades_save_grade_item", "mod_quiz_delete_attempts"):
        with pytest.raises(MoodleError):
            client.call(function)
    assert not sent


def test_allowlist_has_exactly_three_writing_functions():
    writing = {f for f in ALLOWED_FUNCTIONS if re.search(r"(update|upload|import|create|delete|save|set)", f)}
    assert writing == {
        "mod_data_update_entry", "local_questions_importer_ws_import_xml", "local_qbankremotemanager_upload_quiz",
    }


def test_source_code_calls_only_allowed_functions():
    """Любая строка вида core_/mod_/local_…, встречающаяся в коде приложения, должна быть в списке разрешённых."""
    pattern = re.compile(r'"((?:core|mod|local)_[a-z0-9_]+)"')
    found = set()
    for path in SRC.rglob("*.py"):
        found |= set(pattern.findall(path.read_text(encoding="utf-8")))
    assert found, "не нашли ни одного названия функции: проверка не работает"
    assert found <= ALLOWED_FUNCTIONS, sorted(found - ALLOWED_FUNCTIONS)


def test_app_never_mentions_grade_formula_keys_in_requests():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "client.py":
            continue  # здесь ключ назван в списке запрещённых
        assert "appendtogradecalc" not in text, path


@pytest.mark.parametrize("code", ["accessexception", "servicenotavailable", "invalidtoken"])
def test_switched_off_moodle_gives_clear_message(monkeypatch, code):
    """Если админ выключил функцию, службу или токен («рубильник»), приложение объясняет это и не падает."""
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"exception": "x", "errorcode": code, "message": "Access control exception"}

    monkeypatch.setattr("src.moodle.client.requests.post", lambda *a, **k: Resp())
    with pytest.raises(MoodleError) as exc:
        MoodleClient("https://m.example", "T").call("mod_data_update_entry")
    assert code in str(exc.value) and "отключил" in str(exc.value)
