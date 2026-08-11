"""
Экспорт сгенерированных вопросов в JSON.

Для Streamlit-интерфейса удобнее строка в памяти, а не файл на диске —
st.download_button принимает готовые данные напрямую, без временных файлов.
"""
import json

from src.models import Question


def questions_to_json(questions: list[Question]) -> str:
    """
    Сериализует список вопросов в JSON-строку.

    ensure_ascii=False — иначе кириллица превратится в escape-последовательности
    вида \\u0412\\u043e\\u043f... и итоговый файл будет нечитаем глазами.

    Args:
        questions: список вопросов любого из трёх типов (см. src/models.py).

    Returns:
        Готовая JSON-строка с отступами, пригодная для сохранения в файл.
    """
    data = [q.model_dump(mode="json") for q in questions]
    return json.dumps(data, ensure_ascii=False, indent=2)