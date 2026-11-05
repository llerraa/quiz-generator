"""
Логика «публикации» теста в Moodle без интерфейса: защита от повторной загрузки и текст отчёта.

Журнал загрузок хранится в data/moodle_uploads.json (в git не попадает): так приложение помнит,
что именно этот тест уже загружали в этот курс. Плагин импорта сам дубли не отсеивает.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path("data") / "moodle_uploads.json"

# Строка в конце отчёта, пока тест в курсе ещё не создан. Преподаватели вопросы не проверяют,
# поэтому по умолчанию строки нет; если понадобится напоминание, впишите сюда текст,
# например "Требуется выборочная проверка вопросов."
REVIEW_NOTE = ""


def fingerprint(course_id: int, category: str, xml_text: str) -> str:
    """Отпечаток «курс + папка + содержимое теста»: если всё то же — это повторная загрузка."""
    raw = f"{course_id}\n{category}\n{xml_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class UploadLog:
    def __init__(self, path: Path | str = DEFAULT_LOG):
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def find(self, fp: str) -> dict | None:
        return self._read().get(fp)

    def add(self, fp: str, course_id: int, category: str, questions: int, kind: str = "bank") -> None:
        data = self._read()
        data[fp] = {
            "course_id": course_id,
            "category": category,
            "questions": questions,
            "kind": kind,  # "bank" — вопросы в банк, "quiz" — создан тест в курсе
            "when": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_report(result=None, usage=None, questions_count: int = 0, *, quiz_url: str | None = None) -> str:
    """
    Текст для колонки «Отчёт» в реестре.

    Расход ИИ в отчёт не пишем (он нужен только тому, кто запускает приложение, и виден на экране).
    Последняя строка: ссылка на созданный тест (если он создан) или REVIEW_NOTE (по умолчанию пусто).
    """
    lines: list[str] = []
    if result is not None:
        lines.append(f"Вошло вопросов: {len(result.questions)} из {result.target}.")
        if result.skipped:
            lines.append(f"Пропущено: {len(result.skipped)} (не подходят под формат: выбор из списка, 1 или 2 верных ответа).")
        if result.errors:
            lines.append(f"Ошибок при разборе фрагментов: {len(result.errors)}.")
    else:
        lines.append(f"Вопросов: {questions_count}.")
    if quiz_url:
        lines.append(f"Тест создан в курсе: {quiz_url}")
    elif REVIEW_NOTE:
        lines.append(REVIEW_NOTE)
    return "\n".join(lines)


def make_rework_report(result=None, limit: int = 8) -> str:
    """Отчёт для статуса «Отправлен на доработку»: что не так с файлом преподавателя."""
    lines: list[str] = []
    if result is not None:
        lines.append(f"Вошло вопросов: {len(result.questions)} из {result.target}.")
        if getattr(result, "shortfall", 0) > 0:
            lines.append(f"Не хватает вопросов: {result.shortfall}.")
        for item in result.skipped[:limit]:
            title = f"«{item.title}»: " if getattr(item, "title", "") else ""
            lines.append(f"- {title}{item.reason}")
        rest = len(result.skipped) - limit
        if rest > 0:
            lines.append(f"- … и ещё пропущено: {rest}")
    lines.append("Тест не сформирован: файл отправлен преподавателю на доработку.")
    return "\n".join(lines)


def can_publish(result=None) -> tuple[bool, str]:
    """Можно ли отправлять результат в курс. Неполный из-за лимита или пустой — нельзя."""
    if result is None:
        return True, ""
    if result.budget_error:
        return False, "Обработка была остановлена по лимиту расхода — результат неполный, в курс его отправлять нельзя."
    if not result.questions:
        return False, "В тесте нет ни одного вопроса."
    return True, ""
