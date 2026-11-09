"""Фильтры, сортировка и таблица записей реестра (без интерфейса)."""
from datetime import datetime

from src.moodle import registry_table as T
from src.moodle.registry import (
    F_COURSE_LINK, F_COURSE_NAME, F_DEPARTMENT, F_EXCEPTION, F_GROUP, F_KIND, F_SOURCE, F_STATUS, STATUS_BANK, STATUS_NEW,
    STATUS_QUIZ, STATUS_REWORK, RegistryEntry, RegistryFile,
)


def entry(i, name, status, modified=0, file=True, cid=None, group="", exception="", kind="", department=""):
    return RegistryEntry(
        i,
        {F_COURSE_NAME: name, F_STATUS: status, F_GROUP: group, F_EXCEPTION: exception, F_KIND: kind,
         F_DEPARTMENT: department, F_COURSE_LINK: f"https://m/course/view.php?id={cid}" if cid else ""},
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


# --- исключения и фильтры по виду контроля и кафедре ---------------------------------------

REAL = [
    entry(1, "Анатомия", STATUS_NEW, 1, cid=16, kind="Экзамен", department="ГиЕНД"),
    entry(2, "Философия", STATUS_NEW, 2, cid=17, kind="Зачёт", department="Философии", exception="Тест не нужен"),
    entry(3, "Математика", STATUS_NEW, 3, cid=18, kind="Экзамен", department="Математики", exception="Несколько тестов"),
    entry(4, "Право", STATUS_NEW, 4, cid=19, kind="", department=""),
]


def test_exception_options_start_with_no_exception_and_list_found_values():
    assert T.exception_options(REAL) == [T.NO_EXCEPTION, "Несколько тестов", "Тест не нужен"]
    assert T.exception_options([]) == [T.NO_EXCEPTION]


def test_filter_by_exceptions_default_hides_manual_records():
    assert ids(T.filter_entries(REAL, None, exceptions=T.DEFAULT_EXCEPTIONS)) == [1, 4]
    assert ids(T.filter_entries(REAL, None, exceptions=["Тест не нужен"])) == [2]
    assert ids(T.filter_entries(REAL, None, exceptions=["Тест не нужен", "Несколько тестов"])) == [2, 3]


def test_empty_exceptions_filter_means_no_restriction():
    assert ids(T.filter_entries(REAL, None, exceptions=[])) == [1, 2, 3, 4]
    assert ids(T.filter_entries(REAL, None)) == [1, 2, 3, 4]


def test_value_options_sorted_with_not_set_last():
    assert T.value_options(REAL, F_KIND) == ["Зачёт", "Экзамен", T.NOT_SET]
    assert T.value_options(REAL, F_DEPARTMENT) == ["ГиЕНД", "Математики", "Философии", T.NOT_SET]


def test_filter_by_kind_and_department():
    assert ids(T.filter_entries(REAL, None, kinds=["Экзамен"])) == [1, 3]
    assert ids(T.filter_entries(REAL, None, kinds=[T.NOT_SET])) == [4]
    assert ids(T.filter_entries(REAL, None, departments=["Философии", T.NOT_SET])) == [2, 4]
    assert ids(T.filter_entries(REAL, None, kinds=["Экзамен"], departments=["Математики"])) == [3]


def test_frame_shows_exception_and_result_files():
    done = entry(5, "Химия", STATUS_QUIZ, 5, exception="Тест не нужен")
    done.files["Проверенный файл"] = [RegistryFile("b.txt", "https://m/b")]
    row = T.entries_frame([done]).iloc[0]
    assert row[F_EXCEPTION] == "Тест не нужен"
    assert row["Проверенный файл"] == "есть" and row["Файл (Gift) для заливки"] == "нет"
