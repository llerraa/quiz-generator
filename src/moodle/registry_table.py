"""
Таблица записей реестра: фильтры, сортировка и превращение в таблицу для показа.

Здесь только обычные функции без Streamlit, чтобы их можно было проверить тестами.
Интерфейс (фильтры над таблицей, выбор строки) собирает src/moodle/panel.py.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.moodle.registry import (
    F_COURSE_LINK, F_COURSE_NAME, F_DEPARTMENT, F_EXCEPTION, F_GROUP, F_KIND, F_RESULT_AIKEN, F_RESULT_GIFT, F_SOURCE,
    F_STATUS, F_TEACHER, STATUS_NEW, STATUSES, RegistryEntry,
)

NO_STATUS = "(без статуса)"

FILE_ANY = "Все записи"
FILE_YES = "С файлом от зав кафедрой"
FILE_NO = "Без файла"
FILE_CHOICES = [FILE_ANY, FILE_YES, FILE_NO]

SORT_NEW = "Новые сверху (по дате изменения)"
SORT_OLD = "Старые сверху (по дате изменения)"
SORT_DB = "Как в базе данных"
SORT_CHOICES = [SORT_NEW, SORT_OLD, SORT_DB]

NO_EXCEPTION = "(без исключения)"  # запись без текста в колонке «Исключения»: её обрабатывает приложение
NOT_SET = "(не указано)"  # пустое значение в колонках «Вид контроля» и «Кафедра»

DEFAULT_EXCEPTIONS = [NO_EXCEPTION]  # по умолчанию исключения скрыты: их обрабатывают вручную
DEFAULT_STATUSES = [STATUS_NEW, NO_STATUS]  # как раньше: по умолчанию видны только необработанные


def status_label(entry: RegistryEntry) -> str:
    return entry.status or NO_STATUS


def status_options(entries: list[RegistryEntry]) -> list[str]:
    """Все статусы для фильтра: четыре стандартных, «без статуса» и любые другие, что встретились в базе."""
    extra = sorted({status_label(e) for e in entries} - set(STATUSES) - {NO_STATUS})
    return [*STATUSES, NO_STATUS, *extra]


def exception_label(entry: RegistryEntry) -> str:
    return entry.exception or NO_EXCEPTION


def exception_options(entries: list[RegistryEntry]) -> list[str]:
    """Значения для фильтра «Исключения»: «без исключения» и все тексты, что встретились в базе."""
    return [NO_EXCEPTION, *sorted({e.exception for e in entries if e.exception})]


def value_label(entry: RegistryEntry, column: str) -> str:
    return entry.values.get(column, "") or NOT_SET


def value_options(entries: list[RegistryEntry], column: str) -> list[str]:
    """Значения колонки для фильтра (виды контроля, кафедры): по алфавиту, «не указано» в конце, если такие есть."""
    labels = {value_label(e, column) for e in entries}
    return [*sorted(labels - {NOT_SET}), *([NOT_SET] if NOT_SET in labels else [])]


def has_source_file(entry: RegistryEntry) -> bool:
    return bool(entry.files.get(F_SOURCE))


def filter_entries(
    entries: list[RegistryEntry],
    statuses: list[str] | None = None,
    file_filter: str = FILE_ANY,
    query: str = "",
    *,
    exceptions: list[str] | None = None,
    kinds: list[str] | None = None,
    departments: list[str] | None = None,
) -> list[RegistryEntry]:
    """
    Оставляет записи с нужным статусом, с/без файла и со словом из поиска (название, группа, преподаватель, курс).

    statuses: пустой список — ничего не показывать; None — без ограничения.
    exceptions, kinds, departments: None или пустой список — без ограничения; иначе только выбранные значения.
    """
    result = []
    needle = query.strip().casefold()
    for e in entries:
        if statuses is not None and status_label(e) not in statuses:
            continue
        if exceptions and exception_label(e) not in exceptions:
            continue
        if kinds and value_label(e, F_KIND) not in kinds:
            continue
        if departments and value_label(e, F_DEPARTMENT) not in departments:
            continue
        if file_filter == FILE_YES and not has_source_file(e):
            continue
        if file_filter == FILE_NO and has_source_file(e):
            continue
        if needle:
            haystack = " ".join(
                [e.values.get(k, "") for k in (F_COURSE_NAME, F_GROUP, F_TEACHER, F_KIND, F_DEPARTMENT)] + [str(e.course_id or "")]
            ).casefold()
            if needle not in haystack:
                continue
        result.append(e)
    return result


def sort_entries(entries: list[RegistryEntry], mode: str = SORT_NEW) -> list[RegistryEntry]:
    """Новые сверху / старые сверху по дате изменения; «как в базе» оставляет порядок Moodle. Записи без даты — в конце."""
    if mode == SORT_DB:
        return list(entries)
    dated = [e for e in entries if e.modified]
    undated = [e for e in entries if not e.modified]
    dated.sort(key=lambda e: e.modified, reverse=(mode == SORT_NEW))
    return dated + undated


def entries_frame(entries: list[RegistryEntry]) -> pd.DataFrame:
    """Таблица для показа: одна строка на запись, ссылка на курс в отдельной колонке."""
    rows = []
    for e in entries:
        v = e.values
        rows.append({
            "Курс": v.get(F_COURSE_NAME) or f"запись {e.entry_id}",
            "Ссылка на курс": v.get(F_COURSE_LINK) or None,
            "Вид контроля": v.get(F_KIND, ""),
            "Группа": v.get(F_GROUP, ""),
            "Преподаватель": v.get(F_TEACHER, ""),
            "Кафедра": v.get(F_DEPARTMENT, ""),
            "Статус": status_label(e),
            F_EXCEPTION: e.exception,
            F_SOURCE: "есть" if has_source_file(e) else "нет",
            F_RESULT_AIKEN: "есть" if e.files.get(F_RESULT_AIKEN) else "нет",
            F_RESULT_GIFT: "есть" if e.files.get(F_RESULT_GIFT) else "нет",
            "Изменено": datetime.fromtimestamp(e.modified) if e.modified else pd.NaT,
        })
    # Самое нужное слева: на узком экране остальное прокручивается
    columns = ["Курс", "Статус", F_EXCEPTION, "Изменено", F_SOURCE, F_RESULT_AIKEN, F_RESULT_GIFT, "Ссылка на курс",
               "Вид контроля", "Группа", "Преподаватель", "Кафедра"]
    return pd.DataFrame(rows, columns=columns)
