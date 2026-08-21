"""
Streamlit-интерфейс для преподавателя: загрузка лекции, выбор количества
и типов вопросов, генерация теста и просмотр результата.

Запуск: `streamlit run app.py`

TODO: экспорт в QTI (src/exporters/qti_exporter.py — пока заглушка).
"""
import html as html_lib
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Страховка от ошибок вроде "'ascii' codec can't encode characters":
# в контексте выполнения скрипта Streamlit кодировка вывода иногда
# определяется не как UTF-8, из-за чего падает любой русский текст в логах.
for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding and _stream.encoding.lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

from src.config import Config
from src.exporters.excel_exporter import questions_to_excel_bytes
from src.exporters.json_exporter import questions_to_json
from src.llm.gigachat_client import GigaChatClient
from src.models import QuestionType
from src.parsing.chunking import chunk_document
from src.parsing.docx_parser import parse_docx
from src.parsing.pdf_parser import parse_pdf

st.set_page_config(page_title="Генератор тестов из лекций", page_icon="📝", layout="wide")

_TYPE_LABELS_RU = {
    QuestionType.MULTIPLE_CHOICE: "Множественный выбор",
    QuestionType.TRUE_FALSE: "Верно/неверно",
    QuestionType.MATCHING: "На соответствие",
}

# --- Фирменные стили ИМЭС (оранжевый/чёрный/белый) ---
_CSS = """
<style>
:root {
    --imes-orange: #FC4D0F;
    --imes-orange-soft: rgba(252, 77, 15, 0.12);
    --imes-orange-border: rgba(252, 77, 15, 0.35);
    --surface: #17171A;
    --border: rgba(255,255,255,0.09);
    --text: #F5F5F5;
    --text-muted: #8F8F94;
}
.stApp {
    background:
        radial-gradient(1100px circle at 8% -15%, rgba(252,77,15,0.30) 0%, rgba(252,77,15,0) 48%),
        radial-gradient(900px circle at 105% -5%, rgba(252,77,15,0.16) 0%, rgba(252,77,15,0) 42%) !important;
}
@keyframes imesFadeUp {
    from { opacity: 0; transform: translateY(14px); }
    to { opacity: 1; transform: translateY(0); }
}
.imes-eyebrow { animation: imesFadeUp 0.55s ease-out both; }
.imes-hero-title { animation: imesFadeUp 0.55s ease-out 0.08s both; }
.imes-hero-subtitle { animation: imesFadeUp 0.55s ease-out 0.16s both; }
.stApp, .stApp p, .stApp label, .stApp div {
    font-family: -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
}
.stApp h1, .stApp h2, .stApp h3 {
    font-weight: 800 !important;
    letter-spacing: -0.02em;
}
.imes-eyebrow {
    color: var(--text-muted); font-size: 0.72rem; font-weight: 600;
    letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 0.35rem;
}
.imes-hero-title {
    font-size: 2.3rem; font-weight: 800; line-height: 1.15;
    letter-spacing: -0.02em; color: var(--text); margin: 0 0 0.6rem 0;
}
.imes-hero-title .accent { color: var(--imes-orange); }
.imes-hero-subtitle {
    color: var(--text-muted); font-size: 1rem; line-height: 1.55;
    max-width: 560px; margin-bottom: 0.4rem;
}
.imes-disclaimer {
    background: var(--surface); border: 1px solid var(--border);
    border-left: 3px solid var(--imes-orange);
    border-radius: 10px; padding: 0.7rem 0.9rem; margin-top: 0.7rem;
    color: var(--text-muted); font-size: 0.82rem; line-height: 1.5;
}
.imes-disclaimer strong { color: var(--text); }
.imes-step {
    display: flex; align-items: center; gap: 0.6rem; margin: 1.8rem 0 0.7rem 0;
}
.imes-step-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; border-radius: 999px;
    background: var(--imes-orange-soft); color: var(--imes-orange);
    font-weight: 700; font-size: 0.8rem; border: 1px solid var(--imes-orange-border);
    flex-shrink: 0;
}
.imes-step-title { font-weight: 700; font-size: 1.08rem; color: var(--text); }
.stButton > button {
    background: var(--imes-orange) !important; color: white !important;
    border: none !important; border-radius: 999px !important;
    padding: 0.55rem 1.9rem !important; font-weight: 700 !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
    box-shadow: 0 4px 16px rgba(252, 77, 15, 0.28);
}
.stButton > button:hover {
    background: #FF6B3D !important; transform: translateY(-1px);
    box-shadow: 0 8px 22px rgba(252, 77, 15, 0.4);
}
[data-testid="stFileUploader"] button {
    border-radius: 8px !important;
    padding: 0.4rem 1rem !important;
    box-shadow: none !important;
    white-space: nowrap !important;
}
[data-testid="stFileUploaderDropzone"] {
    background: var(--surface) !important;
    border: 1.5px dashed var(--border) !important; border-radius: 14px !important;
}
[data-testid="stDownloadButton"] button {
    background: transparent !important; color: var(--imes-orange) !important;
    border: 1.5px solid var(--imes-orange-border) !important;
    border-radius: 999px !important; padding: 0.5rem 1.6rem !important;
    font-weight: 700 !important; box-shadow: none !important;
    transition: all 0.15s ease;
}
[data-testid="stDownloadButton"] button:hover {
    background: var(--imes-orange-soft) !important; border-color: var(--imes-orange) !important;
}
.imes-qcard {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 1.1rem 1.3rem; margin-bottom: 0.9rem;
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.imes-qcard:hover {
    transform: translateY(-2px);
    border-color: var(--imes-orange-border);
}
.imes-qcard-tag {
    display: inline-block; background: var(--imes-orange-soft); color: var(--imes-orange);
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
    padding: 0.15rem 0.55rem; border-radius: 999px; margin-bottom: 0.6rem;
}
.imes-qcard-question {
    font-weight: 700; font-size: 1rem; color: var(--text);
    margin-bottom: 0.75rem; line-height: 1.4;
}
.imes-option {
    display: flex; align-items: flex-start; gap: 0.5rem; padding: 0.45rem 0.6rem;
    border-radius: 8px; margin-bottom: 0.35rem; color: var(--text-muted); font-size: 0.92rem;
}
.imes-option-correct {
    background: var(--imes-orange-soft); color: var(--text);
    border: 1px solid var(--imes-orange-border);
}
.imes-option-mark { flex-shrink: 0; font-weight: 700; color: var(--imes-orange); }
.imes-explanation {
    margin-top: 0.6rem; padding-top: 0.6rem; border-top: 1px solid var(--border);
    color: var(--text-muted); font-size: 0.85rem; line-height: 1.5; font-style: italic;
}
.imes-pages { margin-top: 0.6rem; color: var(--text-muted); font-size: 0.75rem; }
.imes-matching-row {
    display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0;
    color: var(--text); font-size: 0.92rem;
}
.imes-matching-arrow { color: var(--imes-orange); }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


def _esc(text: str) -> str:
    return html_lib.escape(text)


def _distribute_count(total: int, n_chunks: int) -> list[int]:
    """Равномерно распределяет total вопросов между n_chunks смысловыми блоками текста."""
    if n_chunks == 0:
        return []
    base, remainder = divmod(total, n_chunks)
    return [base + 1 if i < remainder else base for i in range(n_chunks)]


def _render_question_card(q, index: int) -> str:
    """Собирает HTML-карточку вопроса вместо сырого JSON — под фирменный стиль."""
    pages = ", ".join(str(p) for p in q.source_pages) if q.source_pages else "—"

    if q.type == QuestionType.MULTIPLE_CHOICE:
        options_html = "".join(
            f"<div class='imes-option{' imes-option-correct' if i == q.correct_index else ''}'>"
            f"<span class='imes-option-mark'>{'✓' if i == q.correct_index else '○'}</span>"
            f"<span>{_esc(opt)}</span></div>"
            for i, opt in enumerate(q.options)
        )
        explanation_html = (
            f"<div class='imes-explanation'>{_esc(q.explanation)}</div>" if q.explanation else ""
        )
        return (
            f"<div class='imes-qcard'><span class='imes-qcard-tag'>Множественный выбор</span>"
            f"<div class='imes-qcard-question'>{index}. {_esc(q.question)}</div>"
            f"{options_html}{explanation_html}"
            f"<div class='imes-pages'>Страницы: {pages}</div></div>"
        )

    if q.type == QuestionType.TRUE_FALSE:
        badge = "ВЕРНО" if q.is_true else "НЕВЕРНО"
        return (
            f"<div class='imes-qcard'><span class='imes-qcard-tag'>Верно / неверно</span>"
            f"<div class='imes-qcard-question'>{index}. {_esc(q.statement)}</div>"
            f"<div class='imes-option imes-option-correct'>"
            f"<span class='imes-option-mark'>✓</span><span>{badge}</span></div>"
            f"<div class='imes-pages'>Страницы: {pages}</div></div>"
        )

    if q.type == QuestionType.MATCHING:
        rows_html = "".join(
            f"<div class='imes-matching-row'>{_esc(p.left)}"
            f"<span class='imes-matching-arrow'>→</span>{_esc(p.right)}</div>"
            for p in q.pairs
        )
        return (
            f"<div class='imes-qcard'><span class='imes-qcard-tag'>На соответствие</span>"
            f"<div class='imes-qcard-question'>{index}. {_esc(q.instruction)}</div>"
            f"{rows_html}<div class='imes-pages'>Страницы: {pages}</div></div>"
        )

    return "<div class='imes-qcard'>Неизвестный тип вопроса</div>"


# --- Hero ---
col_logo, col_hero, col_visual = st.columns([1, 4, 3], vertical_alignment="center")
with col_logo:
    st.image("assets/imes_logo_icon.png", width=120)
with col_hero:
    st.markdown(
        "<div class='imes-eyebrow'>Институт международных экономических связей · "
        "ИИ-инструменты для преподавателей</div>"
        "<div class='imes-hero-title'>Генератор <span class='accent'>тестовых вопросов</span> "
        "из лекций</div>"
        "<div class='imes-hero-subtitle'>Загрузите PDF лекции — получите готовый набор вопросов "
        "(множественный выбор, верно/неверно, на соответствие), сгенерированных ИИ на основе "
        "материала.</div>",
        unsafe_allow_html=True,
    )
with col_visual:
    st.image("assets/imes_laptop_mockup.png", width="stretch")
    st.markdown(
        "<div class='imes-disclaimer'><strong>Экспорт в ЭИОС.</strong> Готовые вопросы можно "
        "выгрузить в нужном формате и загрузить в ЭИОС для студентов. Пожалуйста, "
        "перепроверяйте вопросы перед использованием — ИИ может допускать ошибки.</div>",
        unsafe_allow_html=True,
    )

# --- Проверка ключа GigaChat заранее, а не в момент нажатия кнопки ---
if not Config.GIGACHAT_CREDENTIALS:
    st.error(
        "Не найден ключ GigaChat. Скопируйте .env.example в .env и укажите "
        "реальный GIGACHAT_CREDENTIALS, затем перезапустите приложение."
    )
    st.stop()

_MODE_GENERATE = "Сгенерировать вопросы из лекции"
_MODE_EXTRACT = "Привести готовые вопросы к формату"

mode = st.radio(
    "Что делаем?",
    [_MODE_GENERATE, _MODE_EXTRACT],
    horizontal=True,
)
st.markdown("<div style='margin-bottom: 0.5rem;'></div>", unsafe_allow_html=True)


if mode == _MODE_GENERATE:
    # --- Шаг 1. Загрузка PDF ---
    st.markdown(
        "<div class='imes-step'><span class='imes-step-badge'>1</span>"
        "<span class='imes-step-title'>Загрузите лекцию</span></div>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        uploaded_file = st.file_uploader(
            "PDF лекции", type="pdf", label_visibility="collapsed"
        )
        with st.expander("Лекция в PowerPoint, а не в PDF? Покажу, как быстро перевести"):
            st.markdown(
                "**В PowerPoint (Windows и Mac):**\n"
                "1. Откройте презентацию\n"
                "2. **Файл → Экспорт** (или **Сохранить как**)\n"
                "3. В качестве формата выберите **PDF**\n"
                "4. Сохраните — готово, займёт несколько секунд\n\n"
                "**В Keynote (Mac):**\n"
                "1. **Файл → Экспорт в → PDF**\n\n"
                "Затем просто загрузите получившийся PDF-файл сюда."
            )

    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        try:
            document = parse_pdf(tmp_path)
        finally:
            os.unlink(tmp_path)  # временный файл больше не нужен — весь текст уже в document

        chunks = chunk_document(document)

        st.markdown(
            f"<div class='imes-disclaimer'>Загружено: {len(document.pages)} стр., "
            f"{len(chunks)} смысловых блок(ов) текста для генерации</div>",
            unsafe_allow_html=True,
        )
        if document.has_scanned_pages:
            st.markdown(
                "<div class='imes-disclaimer'>Часть страниц похожа на сканы без текстового "
                "слоя — вопросы по ним не будут сгенерированы (см. README).</div>",
                unsafe_allow_html=True,
            )

        if not chunks:
            st.error("Не удалось извлечь текст из PDF — проверьте файл.")
            st.stop()

        # --- Шаг 2. Настройка количества вопросов по типам ---
        st.markdown(
            "<div class='imes-step'><span class='imes-step-badge'>2</span>"
            "<span class='imes-step-title'>Сколько вопросов сгенерировать</span></div>",
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                n_mcq = st.number_input(_TYPE_LABELS_RU[QuestionType.MULTIPLE_CHOICE], min_value=0, max_value=20, value=3)
            with col2:
                n_tf = st.number_input(_TYPE_LABELS_RU[QuestionType.TRUE_FALSE], min_value=0, max_value=20, value=3)
            with col3:
                n_matching = st.number_input(_TYPE_LABELS_RU[QuestionType.MATCHING], min_value=0, max_value=20, value=2)

        # --- Шаг 3. Генерация ---
        st.markdown(
            "<div class='imes-step'><span class='imes-step-badge'>3</span>"
            "<span class='imes-step-title'>Генерация</span></div>",
            unsafe_allow_html=True,
        )

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
                                f"страницы {chunk.page_numbers}): {exc}"
                            )

                progress.empty()
                st.session_state["questions"] = all_questions
                st.success(f"Готово! Сгенерировано вопросов: {len(all_questions)}")

else:
    # --- Шаг 1. Загрузка файла с готовыми вопросами ---
    st.markdown(
        "<div class='imes-step'><span class='imes-step-badge'>1</span>"
        "<span class='imes-step-title'>Загрузите файл с готовыми вопросами</span></div>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        uploaded_existing = st.file_uploader(
            "Файл с вопросами", type=["pdf", "docx", "txt"], label_visibility="collapsed",
        )
        st.markdown(
            "<div class='imes-disclaimer'>Поддерживаются PDF, Word (.docx) и обычный "
            "текст (.txt). Если в исходном docx/pdf преподавателя правильный ответ "
            "помечен жирным шрифтом или подчёркиванием, а не текстом (например, "
            "явным «Правильный ответ: Б» или звёздочкой) — наш парсер это не "
            "увидит, потому что извлекает обычный текст без форматирования.</div>",
            unsafe_allow_html=True,
        )

    if uploaded_existing is not None:
        suffix = Path(uploaded_existing.name).suffix.lower()
        raw_bytes = uploaded_existing.read()

        if suffix == ".pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            try:
                existing_text = parse_pdf(tmp_path).full_text
            finally:
                os.unlink(tmp_path)
        elif suffix == ".docx":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            try:
                existing_text = parse_docx(tmp_path)
            finally:
                os.unlink(tmp_path)
        else:  # .txt
            existing_text = raw_bytes.decode("utf-8", errors="replace")

        if not existing_text.strip():
            st.error("Не удалось извлечь текст из файла — проверьте, что в нём есть текстовый слой.")
            st.stop()

        st.markdown(
            f"<div class='imes-disclaimer'>Извлечено {len(existing_text)} символов текста.</div>",
            unsafe_allow_html=True,
        )

        # --- Шаг 2. Какие типы вопросов искать ---
        st.markdown(
            "<div class='imes-step'><span class='imes-step-badge'>2</span>"
            "<span class='imes-step-title'>Какие типы вопросов искать</span></div>",
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                find_mcq = st.checkbox(_TYPE_LABELS_RU[QuestionType.MULTIPLE_CHOICE], value=True)
            with col2:
                find_tf = st.checkbox(_TYPE_LABELS_RU[QuestionType.TRUE_FALSE], value=True)
            with col3:
                find_matching = st.checkbox(_TYPE_LABELS_RU[QuestionType.MATCHING], value=True)

        # --- Шаг 3. Извлечение ---
        st.markdown(
            "<div class='imes-step'><span class='imes-step-badge'>3</span>"
            "<span class='imes-step-title'>Извлечение</span></div>",
            unsafe_allow_html=True,
        )

        if st.button("Извлечь вопросы", type="primary"):
            types_to_find = [
                qt for qt, enabled in [
                    (QuestionType.MULTIPLE_CHOICE, find_mcq),
                    (QuestionType.TRUE_FALSE, find_tf),
                    (QuestionType.MATCHING, find_matching),
                ] if enabled
            ]

            if not types_to_find:
                st.warning("Выберите хотя бы один тип вопросов для поиска.")
            else:
                client = GigaChatClient()
                all_questions = []
                progress = st.progress(0.0, text="Ищем вопросы...")

                for i, question_type in enumerate(types_to_find, start=1):
                    progress.progress(
                        i / len(types_to_find),
                        text=f"Ищем: {_TYPE_LABELS_RU[question_type]}...",
                    )
                    try:
                        questions = client.extract_questions(
                            text=existing_text, question_type=question_type
                        )
                        all_questions.extend(questions)
                    except Exception as exc:
                        st.error(f"Ошибка извлечения ({_TYPE_LABELS_RU[question_type]}): {exc}")

                progress.empty()
                st.session_state["questions"] = all_questions
                if all_questions:
                    st.success(f"Готово! Найдено вопросов: {len(all_questions)}")
                else:
                    st.warning("Вопросов выбранных типов в файле не нашлось.")


# --- Просмотр результата ---
if st.session_state.get("questions"):
    st.markdown(
        f"<div class='imes-step'><span class='imes-step-badge'>4</span>"
        f"<span class='imes-step-title'>Результат "
        f"({len(st.session_state['questions'])})</span></div>",
        unsafe_allow_html=True,
    )
    cards_html = "".join(
        _render_question_card(q, i) for i, q in enumerate(st.session_state["questions"], start=1)
    )
    st.markdown(cards_html, unsafe_allow_html=True)

    col_dl1, col_dl2, _ = st.columns([1, 1, 3])
    with col_dl1:
        st.download_button(
            label="Скачать в JSON",
            data=questions_to_json(st.session_state["questions"]),
            file_name="quiz_questions.json",
            mime="application/json",
        )
    with col_dl2:
        st.download_button(
            label="Скачать в Excel",
            data=questions_to_excel_bytes(st.session_state["questions"]),
            file_name="quiz_questions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )