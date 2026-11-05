"""Фильтры, сортировка и таблица записей реестра (без интерфейса)."""
from datetime import datetime

from src.moodle import registry_table as T
from src.moodle.registry import (
    F_COURSE_LINK, F_COURSE_NAME, F_DEPARTMENT, F_GROUP, F_SOURCE, F_STATUS, STATUS_BANK, STATUS_NEW, STATUS_QUIZ, STATUS_REWORK,
    RegistryEntry, RegistryFile,
)


def entry(i, name, status, modified=0, file=True, cid=None, group=""):
    return RegistryEntry(
        i,
        {F_COURSE_NAME: name, F_STATUS: status, F_GROUP: group,
         F_COURSE_LINK: f"https://m/course/view.php?id={cid}" if cid else ""},
        {F_SOURCE: [RegistryFile("a.txt", "https://m/f")]} if file else {},
        modified,
    )


ENTRIES = [
    entry(1, "Анатомия", STATUS_NEW, 100, cid=16, group="ЛД-1"),
    entry(2, "Биохимия", STATUS_QUIZ, 300, cid=17),
    entry(3, "Физика", "", 200, file=False, cid=18),
    entry(4, "Химия", STATUS_REWORK, 0, cid=19),
    entry(5, "Гистология", STATUS_BANK, 250, cid=20),
]


def ids(entries):
    return [e.entry_id for e in entries]


def test_sort_newest_first_with_undated_last():
    assert ids(T.sort_entries(ENTRIES, T.SORT_NEW)) == [2, 5, 3, 1, 4]


def test_sort_oldest_first_with_undated_last():
    assert ids(T.sort_entries(ENTRIES, T.SORT_OLD)) == [1, 3, 5, 2, 4]


def test_sort_as_in_database_keeps_order():
    assert ids(T.sort_entries(ENTRIES, T.SORT_DB)) == [1, 2, 3, 4, 5]


def test_filter_by_status_including_no_status():
    assert ids(T.filter_entries(ENTRIES, [STATUS_NEW, T.NO_STATUS])) == [1, 3]
    assert ids(T.filter_entries(ENTRIES, [STATUS_QUIZ])) == [2]
    assert ids(T.filter_entries(ENTRIES, None)) == [1, 2, 3, 4, 5]


def test_filter_by_file():
    assert ids(T.filter_entries(ENTRIES, None, T.FILE_NO)) == [3]
    assert ids(T.filter_entries(ENTRIES, None, T.FILE_YES)) == [1, 2, 4, 5]


def test_search_by_name_group_and_course_number():
    assert ids(T.filter_entries(ENTRIES, None, query="анатом")) == [1]
    assert ids(T.filter_entries(ENTRIES, None, query="лд-1")) == [1]
    assert ids(T.filter_entries(ENTRIES, None, query="17")) == [2]


def test_status_options_contain_standard_unknown_and_empty():
    odd = entry(6, "Старая", "Обработан", 1)
    options = T.status_options(ENTRIES + [odd])
    assert options[:4] == [STATUS_NEW, STATUS_BANK, STATUS_QUIZ, STATUS_REWORK]
    assert T.NO_STATUS in options and "Обработан" in options


def test_frame_has_course_link_status_file_and_date():
    frame = T.entries_frame([ENTRIES[0], ENTRIES[2]])
    row = frame.iloc[0]
    assert row["Курс"] == "Анатомия" and row["Ссылка на курс"] == "https://m/course/view.php?id=16"
    assert row["Статус"] == STATUS_NEW and row[F_SOURCE] == "есть"
    assert row["Изменено"] == datetime.fromtimestamp(100)
    assert frame.iloc[1]["Статус"] == T.NO_STATUS and frame.iloc[1][F_SOURCE] == "нет"


def test_empty_frame_keeps_columns():
    assert "Ссылка на курс" in T.entries_frame([]).columns
