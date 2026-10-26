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

    def add(self, fp: str, course_id: int, category: str, questions: int) -> None:
        data = self._read()
        data[fp] = {
            "course_id": course_id,
            "category": category,
            "questions": questions,
            "when": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_report(result=None, usage=None, questions_count: int = 0) -> str:
    """Короткий текст для колонки «Отчёт» в реестре."""
    lines: list[str] = []
    if result is not None:
        lines.append(f"Вошло вопросов: {len(result.questions)} из {result.target}.")
        if result.skipped:
            lines.append(f"Пропущено: {len(result.skipped)} (не подходят под формат: один верный ответ из списка).")
        if result.errors:
            lines.append(f"Ошибок при разборе фрагментов: {len(result.errors)}.")
        lines.append("Ответы прочитаны кодом из Aiken, без ИИ." if result.source == "aiken"
                     else "Пометки ответов найдены ИИ в файле преподавателя.")
    else:
        lines.append(f"Вопросов: {questions_count}.")
    if usage is not None and getattr(usage, "calls", 0):
        lines.append(f"Расход ИИ ≈ {usage.estimated_caps:.0f} CAPS.")
    lines.append("Требуется выборочная проверка вопросов преподавателем.")
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
