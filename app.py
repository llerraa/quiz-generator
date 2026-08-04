"""
Streamlit-интерфейс для преподавателя: загрузка лекции, выбор количества
и типов вопросов, генерация теста и экспорт в JSON/Excel/QTI.

TODO (следующие этапы разработки):
  - Загрузка PDF через st.file_uploader
  - Настройки генерации: типы вопросов, количество (Config.MAX_QUESTIONS_PER_REQUEST)
  - Вызов src.parsing.pdf_parser.parse_pdf → src.llm.gigachat_client → экспорт
  - Кнопки скачивания результата в трёх форматах

Запускать (когда будет реализовано): `streamlit run app.py`
"""
import streamlit as st

st.set_page_config(page_title="Генератор тестов из лекций", page_icon="📝")
st.title("Генератор тестовых вопросов из PDF-лекций")
st.info("Интерфейс в разработке — сейчас реализован только парсинг PDF (src/parsing).")
