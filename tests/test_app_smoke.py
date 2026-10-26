"""Дымовые проверки интерфейса: каждый раздел открывается без ошибок."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import Config
from src.ui_modes import (
    MODE_FILE, MODE_LECTURE, MODE_REGISTRY, MODES, SWITCH_OFF_LABEL, SWITCH_ON_HINT, SWITCH_ON_LABEL,
)

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(autouse=True)
def _fake_keys(monkeypatch):
    monkeypatch.setattr(Config, "BOTHUB_API_KEY", "test-key")
    monkeypatch.setattr(Config, "MOODLE_URL", None)
    monkeypatch.setattr(Config, "MOODLE_TOKEN", None)


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_app_opens_on_registry_section():
    at = _app()
    assert not at.exception
    assert at.radio[0].value == MODE_REGISTRY
    assert any("Связь с Moodle не настроена" in i.value for i in at.info)


@pytest.mark.parametrize("section", MODES)
def test_every_section_renders_without_errors(section):
    at = _app()
    at.radio[0].set_value(section).run()
    assert not at.exception, at.exception


def test_file_section_has_toggle_for_all_types():
    at = _app()
    at.radio[0].set_value(MODE_FILE).run()
    assert at.toggle[0].value is False
    at.toggle[0].set_value(True).run()
    assert not at.exception, at.exception


def test_lecture_section_asks_for_pdf():
    at = _app()
    at.radio[0].set_value(MODE_LECTURE).run()
    assert not at.exception
    assert any("Загрузите лекцию" in m.value for m in at.markdown)


def test_switch_shows_both_labels_and_hint_only_when_on():
    at = _app()
    at.radio[0].set_value(MODE_FILE).run()
    shown = " ".join(m.value for m in at.markdown)
    assert SWITCH_OFF_LABEL in shown and SWITCH_ON_LABEL in shown
    assert SWITCH_ON_HINT not in shown
    at.toggle[0].set_value(True).run()
    assert SWITCH_ON_HINT in " ".join(m.value for m in at.markdown)


def test_sections_show_their_description_list():
    at = _app()
    for section in MODES:
        at.radio[0].set_value(section).run()
        assert any("imes-mode-list" in m.value for m in at.markdown), section
