"""
Реестр тестов в Moodle: чтение записей из элемента «База данных» и запись результата обратно.

Что такое «запись»: одна строка реестра = один курс (наименование, ссылка на курс, группы,
преподаватели, файл преподавателя и колонки для готовых файлов).

Поля ищутся по НАЗВАНИЮ колонки, поэтому названия в базе нельзя переименовывать.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

from src.moodle.client import MoodleClient, MoodleError, REQUEST_TIMEOUT

# Названия колонок в базе (должны совпадать со словами в таблице Moodle)
F_COURSE_NAME = "Наименование курса"
F_COURSE_LINK = "Ссылка на курс"
F_KIND = "Вид контроля"
F_GROUP = "Учебная группа"
F_TEACHER = "Преподаватель"
F_DEPARTMENT = "Кафедра"
F_SOURCE = "Файл от преподавателя"
F_RESULT_XML = "Обработанный файл"
F_RESULT_AIKEN = "Обработанный файл (Aiken, для чтения)"
F_STATUS = "Статус"
F_REPORT = "Отчёт"

STATUS_NEW = "Не обработан"
STATUS_DONE = "Обработан"
STATUS_UPLOADED = "Загружен в курс"
STATUS_ERROR = "Ошибка"

FUNCTIONS_NEEDED = [
    "mod_data_get_databases_by_courses",
    "mod_data_get_fields",
    "mod_data_get_entries",
    "mod_data_update_entry",
]


def course_id_from_link(link: str) -> int | None:
    """https://…/course/view.php?id=16 -> 16"""
    match = re.search(r"[?&]id=(\d+)", link or "")
    return int(match.group(1)) if match else None


@dataclass
class RegistryFile:
    name: str
    url: str


@dataclass
class RegistryEntry:
    entry_id: int
    values: dict[str, str] = field(default_factory=dict)       # название колонки -> текст
    files: dict[str, list[RegistryFile]] = field(default_factory=dict)  # колонка -> файлы

    @property
    def course_id(self) -> int | None:
        return course_id_from_link(self.values.get(F_COURSE_LINK, ""))

    @property
    def status(self) -> str:
        return self.values.get(F_STATUS, "")


def _text(content: str | None) -> str:
    """Moodle отдаёт HTML: убираем теги и пробелы по краям."""
    return re.sub(r"<[^>]+>", "", content or "").strip()


class MoodleRegistry:
    def __init__(self, client: MoodleClient, registry_course_id: int, registry_name: str | None = None):
        self.client = client
        self.registry_course_id = registry_course_id
        self.registry_name = registry_name
        self._database_id: int | None = None
        self._fields: dict[str, dict] | None = None

    # --- структура базы -----------------------------------------------------

    def database_id(self) -> int:
        if self._database_id is None:
            data = self.client.call("mod_data_get_databases_by_courses", **{"courseids[0]": self.registry_course_id})
            databases = data.get("databases", []) if isinstance(data, dict) else []
            if self.registry_name:
                databases = [d for d in databases if d.get("name") == self.registry_name] or databases
            if not databases:
                raise MoodleError(f"В курсе {self.registry_course_id} не найден элемент «База данных».")
            self._database_id = int(databases[0]["id"])
        return self._database_id

    def fields(self) -> dict[str, dict]:
        """Поля базы: название -> описание (id, type, …)."""
        if self._fields is None:
            data = self.client.call("mod_data_get_fields", databaseid=self.database_id())
            self._fields = {f["name"]: f for f in data.get("fields", [])} if isinstance(data, dict) else {}
        return self._fields

    def check_fields(self) -> list[str]:
        """Каких обязательных колонок не хватает (пустой список = всё в порядке)."""
        need = [F_COURSE_LINK, F_SOURCE, F_RESULT_XML, F_RESULT_AIKEN, F_STATUS, F_REPORT]
        have = self.fields()
        return [name for name in need if name not in have]

    # --- чтение -------------------------------------------------------------

    def entries(self) -> list[RegistryEntry]:
        data = self.client.call(
            "mod_data_get_entries", databaseid=self.database_id(), returncontents=1, perpage=1000
        )
        id_to_name = {int(f["id"]): name for name, f in self.fields().items()}
        result: list[RegistryEntry] = []
        for raw in (data.get("entries", []) if isinstance(data, dict) else []):
            entry = RegistryEntry(entry_id=int(raw["id"]))
            for content in raw.get("contents", []):
                name = id_to_name.get(int(content["fieldid"]))
                if not name:
                    continue
                files = [
                    RegistryFile(name=f.get("filename", ""), url=f.get("fileurl", ""))
                    for f in (content.get("files") or [])
                    if f.get("fileurl")
                ]
                if files:
                    entry.files[name] = files
                entry.values[name] = _text(content.get("content"))
            result.append(entry)
        return result

    def find_by_course(self, course_id: int) -> list[RegistryEntry]:
        return [e for e in self.entries() if e.course_id == course_id]

    def download(self, file: RegistryFile) -> bytes:
        """Скачивает файл из базы. Токен добавляется к адресу и в ошибки не попадает."""
        try:
            response = requests.get(file.url, params={"token": self.client.token}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MoodleError(f"Не удалось скачать файл «{file.name}»: {type(exc).__name__}.") from None
        return response.content

    # --- запись -------------------------------------------------------------

    def _item(self, field_name: str, value, subfield: str = "") -> dict:
        return {"fieldid": int(self.fields()[field_name]["id"]), "subfield": subfield, "value": json.dumps(value, ensure_ascii=False)}

    def save_result(
        self,
        entry_id: int,
        *,
        xml_name: str | None = None,
        xml_text: str | None = None,
        aiken_name: str | None = None,
        aiken_text: str | None = None,
        status: str,
        report: str = "",
    ) -> None:
        """Кладёт готовые файлы, статус и отчёт в запись реестра."""
        items = [self._item(F_STATUS, status), self._item(F_REPORT, report)]
        if xml_text is not None:
            itemid = self.client.upload_draft(xml_name or "test.xml", xml_text.encode("utf-8"))
            items.append(self._item(F_RESULT_XML, itemid, "file"))
        if aiken_text is not None:
            itemid = self.client.upload_draft(aiken_name or "test.txt", aiken_text.encode("utf-8"))
            items.append(self._item(F_RESULT_AIKEN, itemid, "file"))
        payload: dict[str, object] = {"entryid": entry_id}
        for i, item in enumerate(items):
            for key, value in item.items():
                payload[f"data[{i}][{key}]"] = value
        self.client.call("mod_data_update_entry", **payload)

    def set_status(self, entry_id: int, status: str, report: str | None = None) -> None:
        items = [self._item(F_STATUS, status)]
        if report is not None:
            items.append(self._item(F_REPORT, report))
        payload: dict[str, object] = {"entryid": entry_id}
        for i, item in enumerate(items):
            for key, value in item.items():
                payload[f"data[{i}][{key}]"] = value
        self.client.call("mod_data_update_entry", **payload)
