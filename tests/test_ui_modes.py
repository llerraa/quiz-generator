import pytest

from src.ui_modes import (
    COURSE_MODES,
    MODE_FILE,
    MODE_LECTURE,
    MODE_POINTS,
    MODE_REGISTRY,
    MODES,
    SWITCH_OFF_LABEL,
    SWITCH_ON_LABEL,
    render_mode_description_html,
)


def test_three_distinct_sections_in_order():
    assert MODES == [MODE_REGISTRY, MODE_FILE, MODE_LECTURE]
    assert len(set(MODES)) == 3


def test_every_section_has_three_short_points():
    assert set(MODE_POINTS) == set(MODES)
    for points in MODE_POINTS.values():
        assert len(points) == 3
        assert all(text.strip() for text, _ in points)


def test_key_point_is_bold_for_course_sections():
    for mode in COURSE_MODES:
        html = render_mode_description_html(mode)
        assert html.count("<strong>") == 1
    assert "<strong>" not in render_mode_description_html(MODE_LECTURE)


def test_course_sections_are_registry_and_file():
    assert COURSE_MODES == (MODE_REGISTRY, MODE_FILE)


@pytest.mark.parametrize("mode", MODES)
def test_description_html_is_a_list_with_all_points(mode):
    html = render_mode_description_html(mode)
    assert html.startswith("<ul") and html.count("<li>") == 3


def test_switch_labels_are_distinct():
    assert SWITCH_OFF_LABEL != SWITCH_ON_LABEL


def test_text_is_escaped(monkeypatch):
    import src.ui_modes as ui

    monkeypatch.setitem(ui.MODE_POINTS, MODE_FILE, [("<script>x</script> a & b", True)])
    html = ui.render_mode_description_html(MODE_FILE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "a &amp; b" in html


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        render_mode_description_html("что-то другое")
