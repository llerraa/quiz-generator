import pytest

from src.ui_modes import (
    COMPARISON_ROWS,
    MODE_COURSE,
    MODE_EXTRACT,
    MODE_GENERATE,
    MODES,
    render_mode_comparison_html,
)


def test_three_distinct_modes_in_order():
    assert MODES == [MODE_COURSE, MODE_GENERATE, MODE_EXTRACT]
    assert len(set(MODES)) == 3
    assert [m[0] for m in MODES] == ["1", "2", "3"]


def test_every_row_describes_all_three_modes_and_nothing_is_empty():
    for row in COMPARISON_ROWS:
        assert len(row) == 4, row
        assert all(cell.strip() for cell in row), row


def test_row_titles_are_unique():
    titles = [row[0] for row in COMPARISON_ROWS]
    assert len(titles) == len(set(titles))


@pytest.mark.parametrize("current", MODES)
def test_exactly_the_current_column_is_highlighted(current):
    html = render_mode_comparison_html(current)
    # подсвечены заголовок и по одной ячейке в каждой строке
    assert html.count("class='is-current'") == 1 + len(COMPARISON_ROWS)
    index = MODES.index(current)
    first_row_cell = COMPARISON_ROWS[0][1 + index]
    assert f"<td class='is-current'>{first_row_cell}</td>" in html


def test_all_mode_names_are_in_header():
    html = render_mode_comparison_html(MODE_COURSE)
    for mode in MODES:
        assert mode in html


def test_text_is_escaped(monkeypatch):
    import src.ui_modes as ui

    monkeypatch.setattr(ui, "COMPARISON_ROWS", [("Строка <b>", "<script>x</script>", "a & b", "c")])
    html = ui.render_mode_comparison_html(MODE_COURSE)
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html and "a &amp; b" in html


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        render_mode_comparison_html("что-то другое")
