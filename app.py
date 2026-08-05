"""
Streamlit-интерфейс для преподавателя: загрузка лекции, выбор количества
и типов вопросов, генерация теста и просмотр результата.

Запуск: `streamlit run app.py`

TODO (следующие этапы): экспорт в JSON/Excel/QTI (src/exporters — пока заглушки).
"""
import os
import sys
import tempfile

import streamlit as st

# Страховка от ошибок вроде "'ascii' codec can't encode characters":
# в контексте выполнения скрипта Streamlit кодировка вывода иногда
# определяется не как UTF-8, из-за чего падает любой русский текст в логах.
for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding and _stream.encoding.lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

from src.config import Config
from src.llm.gigachat_client import GigaChatClient
from src.models import QuestionType
from src.parsing.chunking import chunk_document
from src.parsing.pdf_parser import parse_pdf

st.set_page_config(page_title="Генератор тестов из лекций", page_icon="📝")
st.title("Генератор тестовых вопросов из PDF-лекций")

_TYPE_LABELS_RU = {
    QuestionType.MULTIPLE_CHOICE: "Множественный выбор",
    QuestionType.TRUE_FALSE: "Верно/неверно",
    QuestionType.MATCHING: "На соответствие",
}


def _distribute_count(total: int, n_chunks: int) -> list[int]:
    """Равномерно распределяет total вопросов между n_chunks смысловыми блоками текста."""
    if n_chunks == 0:
        return []
    base, remainder = divmod(total, n_chunks)
    return [base + 1 if i < remainder else base for i in range(n_chunks)]


def _question_preview(question) -> str:
    """Короткий текст вопроса для заголовка в списке результатов."""
    if question.type == QuestionType.MULTIPLE_CHOICE:
        return question.question
    if question.type == QuestionType.TRUE_FALSE:
        return question.statement
    if question.type == QuestionType.MATCHING:
        return question.instruction
    return "Вопрос"


# --- Проверка ключа GigaChat заранее, а не в момент нажатия кнопки ---
if not Config.GIGACHAT_CREDENTIALS:
    st.error(
        "Не найден ключ GigaChat. Скопируйте .env.example в .env и укажите "
        "реальный GIGACHAT_CREDENTIALS, затем перезапустите приложение."
    )
    st.stop()


# --- Загрузка PDF ---
uploaded_file = st.file_uploader("Загрузите PDF лекции", type="pdf")

if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        document = parse_pdf(tmp_path)
    finally:
        os.unlink(tmp_path)  # временный файл больше не нужен — весь текст уже в document

    chunks = chunk_document(document)

    st.success(
        f"Загружено: {len(document.pages)} стр., "
        f"{len(chunks)} смысловых блок(ов) текста для генерации"
    )
    if document.has_scanned_pages:
        st.warning(
            "Часть страниц похожа на сканы без текстового слоя — "
            "вопросы по ним не будут сгенерированы (см. README)."
        )

    if not chunks:
        st.error("Не удалось извлечь текст из PDF — проверьте файл.")
        st.stop()

    # --- Настройка количества вопросов по типам ---
    st.subheader("Сколько вопросов сгенерировать")
    col1, col2, col3 = st.columns(3)
    with col1:
        n_mcq = st.number_input(_TYPE_LABELS_RU[QuestionType.MULTIPLE_CHOICE], min_value=0, max_value=20, value=3)
    with col2:
        n_tf = st.number_input(_TYPE_LABELS_RU[QuestionType.TRUE_FALSE], min_value=0, max_value=20, value=3)
    with col3:
        n_matching = st.number_input(_TYPE_LABELS_RU[QuestionType.MATCHING], min_value=0, max_value=20, value=2)

    if st.button("Сгенерировать вопросы", type="primary"):
        counts = {
            QuestionType.MULTIPLE_CHOICE: n_mcq,
            QuestionType.TRUE_FALSE: n_tf,
            QuestionType.MATCHING: n_matching,
        }
        active_types = {qt: c for qt, c in counts.items() if c > 0}

        if not active_types:
            st.warning("Выберите хотя бы один тип вопросов с количеством больше 0.")
        else:
            client = GigaChatClient()
            all_questions = []
            total_steps = len(active_types) * len(chunks)
            step = 0
            progress = st.progress(0.0, text="Генерируем вопросы...")

            for question_type, total_count in active_types.items():
                per_chunk = _distribute_count(total_count, len(chunks))
                for chunk, chunk_count in zip(chunks, per_chunk):
                    step += 1
                    progress.progress(
                        step / total_steps,
                        text=f"{_TYPE_LABELS_RU[question_type]}: страницы {chunk.page_numbers}...",
                    )
                    if chunk_count == 0:
                        continue
                    try:
                        questions = client.generate_questions(
                            text=chunk.text,
                            question_type=question_type,
                            count=chunk_count,
                            source_pages=chunk.page_numbers,
                        )
                        all_questions.extend(questions)
                    except Exception as exc:
                        st.error(
                            f"Ошибка генерации ({_TYPE_LABELS_RU[question_type]}, "
                            f"страницы {chunk.page_numbers})"
                        )

            progress.empty()
            st.session_state["questions"] = all_questions
            st.success(f"Готово! Сгенерировано вопросов: {len(all_questions)}")


# --- Просмотр результата ---
if st.session_state.get("questions"):
    st.subheader(f"Сгенерированные вопросы ({len(st.session_state['questions'])})")
    for i, q in enumerate(st.session_state["questions"], start=1):
        with st.expander(f"{i}. [{_TYPE_LABELS_RU[q.type]}] {_question_preview(q)}"):
            st.json(q.model_dump())
