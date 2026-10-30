"""
Streamlit-интерфейс: три раздела (тест из реестра Moodle, тест из файла, тест из лекции),
просмотр результата и отправка теста в Moodle.

Запуск: `streamlit run app.py`
"""

import html as html_lib
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

# Страховка от ошибок вроде "'ascii' codec can't encode characters":
# в контексте выполнения скрипта Streamlit кодировка вывода иногда
# определяется не как UTF-8, из-за чего падает любой русский текст в логах.
for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding and _stream.encoding.lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

from src.config import Config
from src.course_pipeline import prepare_course_test
from src.exporters.aiken_exporter import count_skipped_for_aiken, questions_to_aiken
from src.exporters.excel_exporter import questions_to_excel_bytes
from src.exporters.json_exporter import questions_to_json
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.exporters.qti_exporter import questions_to_qti_xml
from src.llm.bothub_client import BotHubClient
from src.moodle.panel import pick_registry_entry, render_moodle_panel
from src.models import QuestionType
from src.ui_modes import (
    MODE_FILE as _SECTION_FILE,
    MODE_LECTURE as _SECTION_LECTURE,
    MODE_REGISTRY as _SECTION_REGISTRY,
    MODES as _SECTIONS,
    SWITCH_OFF_LABEL,
    SWITCH_ON_HINT,
    SWITCH_ON_LABEL,
    render_mode_description_html,
)

# Внутренние режимы работы (раздел «Тест из файла» с галочкой «все типы» уходит в _MODE_EXTRACT).
_MODE_REGISTRY = "registry"
_MODE_FILE = "file"
_MODE_EXTRACT = "extract"
_MODE_GENERATE = "generate"
_COURSE_MODES = (_MODE_REGISTRY, _MODE_FILE)  # файл преподавателя → до 25 вопросов → Moodle
from src.parsing.chunking import chunk_document
from src.parsing.aiken_parser import looks_like_aiken, parse_aiken
from src.parsing.docx_parser import parse_docx
from src.parsing.file_loader import load_question_file
from src.parsing.pdf_parser import parse_pdf

st.set_page_config(page_title="Генератор тестов для Moodle", page_icon="📝", layout="wide")

_TYPE_LABELS_RU = {
    QuestionType.MULTIPLE_CHOICE: "Множественный выбор",
    QuestionType.TRUE_FALSE: "Верно/неверно",
    QuestionType.MATCHING: "На соответствие",
    QuestionType.ESSAY: "Эссе",
    QuestionType.SHORT_ANSWER: "Короткий ответ",
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
.imes-disclaimer-lg {
    font-size: 0.98rem; line-height: 1.65; padding: 1rem 1.2rem;
    border-left-width: 4px;
}
.imes-warning-white {
    background: #FFFFFF; border: 1px solid var(--imes-orange-border);
    border-left: 4px solid var(--imes-orange); border-radius: 10px;
    padding: 1rem 1.2rem; margin: 0.8rem 0;
    color: #1A1A1A; font-size: 0.98rem; line-height: 1.65;
}
.imes-warning-white strong { color: #000000; }
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
.imes-mode-label {
    font-size: 1.35rem; font-weight: 800; color: var(--text);
    margin: 1.6rem 0 0.7rem 0; letter-spacing: -0.01em;
}
[data-testid="stRadio"] label p {
    font-size: 1.08rem !important; font-weight: 600 !important;
}
[data-testid="stRadio"] > div { gap: 1.8rem !important; }
.stButton button {
    background: var(--imes-orange) !important; color: white !important;
    border: none !important; border-radius: 999px !important;
    padding: 0.55rem 1.9rem !important; font-weight: 700 !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
    box-shadow: 0 4px 16px rgba(252, 77, 15, 0.28);
}
.stButton button:hover {
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

/* --- Переключатель разделов: оранжевая полоса на всю ширину --- */
.st-key-mode_switch {
    background: var(--imes-orange); border-radius: 18px; padding: 6px;
    box-shadow: 0 8px 28px rgba(252, 77, 15, 0.30);
}
.st-key-mode_switch [data-testid="stElementContainer"], .st-key-mode_switch [data-testid="stRadio"],
.st-key-mode_switch [data-testid="stRadio"] > div { width: 100% !important; }
.st-key-mode_switch [role="radiogroup"] { display: flex !important; width: 100%; gap: 6px !important; flex-wrap: nowrap !important; }
.st-key-mode_switch [role="radiogroup"] > * { flex: 1 1 0 !important; min-width: 0; }
.st-key-mode_switch label[data-testid="stRadioOption"] {
    display: flex; width: 100%; justify-content: center; margin: 0 !important;
    padding: 0.95rem 0.8rem !important; border-radius: 13px; cursor: pointer;
    background: transparent; transition: background 0.15s ease; box-sizing: border-box;
}
.st-key-mode_switch label[data-testid="stRadioOption"]:hover { background: rgba(255,255,255,0.16); }
.st-key-mode_switch label[data-testid="stRadioOption"] div:has(> [data-testid="stMarkdownContainer"]) > div:first-child { display: none !important; }
.st-key-mode_switch label[data-testid="stRadioOption"] div:has(> [data-testid="stMarkdownContainer"]) { justify-content: center; width: 100%; }
.st-key-mode_switch label[data-testid="stRadioOption"] p {
    color: #FFFFFF !important; font-size: 1.2rem !important; font-weight: 800 !important;
    text-align: center; letter-spacing: -0.01em; white-space: nowrap;
}
.st-key-mode_switch label[data-testid="stRadioOption"]:has(input:checked) { background: #FFFFFF; }
.st-key-mode_switch label[data-testid="stRadioOption"]:has(input:checked) p { color: var(--imes-orange) !important; }

/* --- Описание выбранного раздела --- */
.imes-mode-list { list-style: none; padding: 0; margin: 1.3rem 0 0.8rem; }
.imes-mode-list li {
    position: relative; padding-left: 1.7rem; margin: 0.5rem 0;
    font-size: 1.22rem; line-height: 1.5; color: #B9B9BF;
}
.imes-mode-list li::before {
    content: ""; position: absolute; left: 0.25rem; top: 0.62em;
    width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--imes-orange);
}
.imes-mode-list li strong { color: #FFFFFF; font-weight: 800; }
.st-key-mode_options {
    background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
    padding: 0.55rem 1.2rem; margin: 0.4rem 0 0.4rem;
}
.st-key-mode_options [data-testid="stHorizontalBlock"] { align-items: center; }
.imes-switch-label { font-size: 1.02rem; font-weight: 600; color: var(--text-muted); }
.imes-switch-label.right { text-align: right; }
.imes-switch-label.is-active { color: #FFFFFF; font-weight: 800; }
.imes-switch-hint { color: var(--text-muted); font-size: 0.95rem; margin: 0.2rem 0 0.4rem; }
.imes-caption { color: var(--text-muted); font-size: 0.85rem; margin: 1rem 0 0.3rem; }

/* --- Этапы работы: белые карточки на тёмном фоне --- */
[class*="st-key-step_"] {
    --surface: #F5F5F7; --border: rgba(0,0,0,0.10);
    --text: #1A1A1A; --text-muted: #5E5E66;
    background: #FFFFFF; border-radius: 18px; padding: 1.3rem 1.6rem 1.5rem;
    margin: 1.1rem 0 0.4rem; color: #1A1A1A;
}
[class*="st-key-step_"] .imes-step { margin: 0 0 0.9rem 0; }
[class*="st-key-step_"] .imes-step-title { font-size: 1.2rem; }
[class*="st-key-step_"] p, [class*="st-key-step_"] li, [class*="st-key-step_"] label,
[class*="st-key-step_"] span, [class*="st-key-step_"] summary, [class*="st-key-step_"] strong,
[class*="st-key-step_"] [data-testid="stMarkdownContainer"],
[class*="st-key-step_"] [data-testid="stCaptionContainer"],
[class*="st-key-step_"] [data-testid="stWidgetLabel"] { color: #1A1A1A !important; }
[class*="st-key-step_"] .imes-step-badge, [class*="st-key-step_"] .imes-qcard-tag,
[class*="st-key-step_"] .imes-option-mark, [class*="st-key-step_"] .imes-matching-arrow { color: var(--imes-orange) !important; }
[class*="st-key-step_"] .imes-pages, [class*="st-key-step_"] .imes-explanation,
[class*="st-key-step_"] .imes-option, [class*="st-key-step_"] .imes-caption { color: #5E5E66 !important; }
[class*="st-key-step_"] .imes-option-correct, [class*="st-key-step_"] .imes-option-correct span { color: #1A1A1A !important; }
[class*="st-key-step_"] .imes-option-mark { color: var(--imes-orange) !important; }
/* поля ввода и списки */
[class*="st-key-step_"] [data-baseweb="input"], [class*="st-key-step_"] [data-baseweb="base-input"],
[class*="st-key-step_"] [data-baseweb="select"] > div, [class*="st-key-step_"] textarea,
[class*="st-key-step_"] [data-testid="stSelectbox"] [role="group"],
[class*="st-key-step_"] [data-testid="stTextInput"] [role="group"],
[class*="st-key-step_"] [data-testid="stNumberInput"] [role="group"],
[class*="st-key-step_"] [data-testid="stTextInputRootElement"],
[class*="st-key-step_"] [data-testid="stNumberInputContainer"] {
    background: #F2F2F4 !important; border-color: rgba(0,0,0,0.14) !important;
}
[class*="st-key-step_"] input, [class*="st-key-step_"] [data-baseweb="select"] * {
    color: #1A1A1A !important; -webkit-text-fill-color: #1A1A1A !important;
}
[class*="st-key-step_"] [data-baseweb="select"] svg, [class*="st-key-step_"] [data-testid="stSelectbox"] svg { fill: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stNumberInput"] button { background: #E6E6EA !important; }
[class*="st-key-step_"] [data-testid="stNumberInput"] button * { color: #1A1A1A !important; fill: #1A1A1A !important; }
[class*="st-key-step_"] [data-baseweb="checkbox"] > span:first-child { border-color: #8A8A90 !important; }
[class*="st-key-step_"] label:has(input[type="checkbox"]:not(:checked)) > div:first-of-type {
    background: #FFFFFF !important; border: 2px solid #8A8A90 !important;
}
/* загрузка файла и раскрывающиеся блоки */
[class*="st-key-step_"] [data-testid="stFileUploaderDropzone"] {
    background: #F5F5F7 !important; border: 1.5px dashed rgba(0,0,0,0.22) !important;
}
[class*="st-key-step_"] [data-testid="stFileUploader"] button {
    background: #FFFFFF !important; border: 1px solid rgba(0,0,0,0.25) !important; box-shadow: none !important;
}
[class*="st-key-step_"] [data-testid="stFileUploader"] button * { color: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stFileUploaderFile"] * { color: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stFileChip"] {
    background: #FFFFFF !important; border: 1px solid rgba(0,0,0,0.18) !important; border-radius: 8px !important;
}
[class*="st-key-step_"] [data-testid="stFileChip"], [class*="st-key-step_"] [data-testid="stFileChip"] * { color: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stFileChip"] svg { fill: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stFileChipDeleteBtn"] button { background: transparent !important; box-shadow: none !important; }
[class*="st-key-step_"] [data-testid="stFileUploader"] [data-testid="stBaseButton-borderlessIcon"] { background: #FFFFFF !important; }
[class*="st-key-step_"] [data-testid="stFileUploader"] [data-testid="stBaseButton-borderlessIcon"] * { color: #1A1A1A !important; }
[class*="st-key-step_"] [data-testid="stExpander"] { border-color: rgba(0,0,0,0.14) !important; }
[class*="st-key-step_"] [data-testid="stExpander"] details, [class*="st-key-step_"] [data-testid="stExpander"] summary { background: transparent !important; }
[class*="st-key-step_"] [data-testid="stExpander"] svg { fill: #1A1A1A !important; color: #1A1A1A !important; }
/* кнопки */
[class*="st-key-step_"] .stButton button, [class*="st-key-step_"] .stButton button * { color: #FFFFFF !important; }
[class*="st-key-step_"] .stButton button:disabled { opacity: 0.4; box-shadow: none; }
[class*="st-key-step_"] [data-testid="stDownloadButton"] button, [class*="st-key-step_"] [data-testid="stDownloadButton"] button * { color: var(--imes-orange) !important; }
/* заметки внутри карточек */
[class*="st-key-step_"] .imes-warning-white {
    background: #FFF4EF; border-color: var(--imes-orange-border); margin: 1rem 0 0;
}
[class*="st-key-step_"] .imes-disclaimer { margin-top: 0.5rem; }
.imes-field-label { font-size: 0.875rem; margin-bottom: 0.4rem; color: #1A1A1A; }
.imes-file-chip {
    display: block; background: #F2F2F4; border: 1px solid rgba(0,0,0,0.14); border-radius: 8px;
    padding: 0.55rem 0.8rem; font-size: 0.95rem; font-weight: 600; color: #1A1A1A; word-break: break-all;
}
.imes-panel-note {
    background: #F5F5F7; border-left: 3px solid var(--imes-orange); border-radius: 8px;
    padding: 0.7rem 1rem; margin: 0.7rem 0; color: #1A1A1A; font-size: 1.02rem;
}
.imes-panel-note strong { color: #000000; }
.imes-panel-sub { color: #5E5E66; font-size: 0.88rem; margin-top: 0.2rem; }
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

    if q.type == QuestionType.ESSAY:
        return (
            f"<div class='imes-qcard'><span class='imes-qcard-tag'>Эссе</span>"
            f"<div class='imes-qcard-question'>{index}. {_esc(q.question)}</div>"
            f"<div class='imes-explanation'><strong>Критерии оценки:</strong> "
            f"{_esc(q.grading_criteria)}</div>"
            f"<div class='imes-pages'>Страницы: {pages}</div></div>"
        )

    if q.type == QuestionType.SHORT_ANSWER:
        return (
            f"<div class='imes-qcard'><span class='imes-qcard-tag'>Короткий ответ</span>"
            f"<div class='imes-qcard-question'>{index}. {_esc(q.question)}</div>"
            f"<div class='imes-option imes-option-correct'>"
            f"<span class='imes-option-mark'>✓</span><span>{_esc(q.sample_answer)}</span></div>"
            f"<div class='imes-pages'>Страницы: {pages}</div></div>"
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
        "<div class='imes-hero-title'>Генератор <span class='accent'>тестов</span> "
        "для Moodle</div>"
        "<div class='imes-hero-subtitle'>Готовим тест из файла преподавателя или из лекции "
        "и отправляем его в курс.</div>",
        unsafe_allow_html=True,
    )
with col_visual:
    st.image("assets/imes_laptop_mockup.png", width="stretch")

# --- Проверка ключа BotHub заранее, а не в момент нажатия кнопки ---
if not Config.BOTHUB_API_KEY:
    st.error(
        "Не найден ключ BotHub. Скопируйте .env.example в .env и укажите "
        "реальный BOTHUB_API_KEY, затем перезапустите приложение."
    )
    st.stop()

def _format_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _render_course_report(result, usage=None) -> None:
    """Итог подготовки теста: сколько вошло, что пропущено и почему — ничего не теряется молча."""
    n = len(result.questions)
    if usage is not None and usage.calls:
        st.info(
            f"Расход этого запуска: запросов к ИИ — {usage.calls}, токенов — вход "
            f"{_format_number(usage.prompt_tokens)}, выход {_format_number(usage.completion_tokens)}; "
            f"примерно {_format_number(usage.estimated_caps)} CAPS (≈ {usage.estimated_rub:.2f} ₽). "
            "Это прикидка по тарифу из настроек, точное списание смотрите в личном кабинете BotHub."
        )
    elif result.source == "aiken":
        st.info("Файл в формате Aiken прочитан без ИИ. Расход этого запуска: 0.")

    if result.budget_error:
        st.error(
            f"{result.budget_error}. Обработка остановлена, чтобы не тратить деньги дальше: "
            f"разобрано фрагментов {result.chunks_done} из {result.chunks_total}, "
            f"в тест попало {n} из {result.target} вопросов. Это неполный результат — "
            "не загружайте его в курс как готовый тест. Лимит меняется через COURSE_MAX_CAPS в .env."
        )
    elif n == 0:
        st.error("Ни один вопрос не подошёл для теста.")
    elif result.shortfall == 0:
        st.success(f"В тест вошло {n} вопросов из {result.target}.")
    else:
        st.warning(
            f"В тест вошло {n} из {result.target}: подходящих вопросов в файле "
            f"не хватило, не хватает {result.shortfall}."
        )

    if result.extra_valid:
        st.info(
            f"Подходящих вопросов больше, чем нужно: взяты первые {result.target}, "
            f"ещё {result.extra_valid} не вошли."
        )
    if result.stopped_early:
        st.info("Нужное число вопросов набрано — остальную часть файла не разбирали.")

    for message in result.errors:
        st.error(message)

    if result.skipped:
        st.warning(
            f"Пропущено вопросов: {len(result.skipped)}. Они не подходят под формат Aiken "
            "(один вариант из списка, один верный ответ) — их нужно поправить в исходном файле "
            "или добавить вручную."
        )
        with st.expander("Какие вопросы пропущены и почему", expanded=n == 0 or len(result.skipped) <= 8):
            for item in result.skipped:
                if item.title:
                    st.markdown(f"- «{item.title}» — {item.reason}")
                else:
                    st.markdown(f"- {item.reason}")

    if n and result.source == "llm":
        with st.expander("Как определены правильные ответы (для проверки)"):
            for number, (q, evidence) in enumerate(zip(result.questions, result.evidence), start=1):
                shown = evidence.replace("`", "'")
                st.markdown(f"{number}. по пометке в файле: `{shown}`")


def _reset_course_if_changed(sig) -> None:
    """Новый файл (или запись, или файл убрали) — отчёт и вопросы от прошлого больше не актуальны."""
    if st.session_state.get("_course_file_sig") != sig:
        st.session_state["questions"] = []
        st.session_state["course_result"] = None
        st.session_state["course_usage"] = None
        st.session_state["_course_file_sig"] = sig


@contextmanager
def _step(number: int, title: str, key: str):
    """Этап работы на белой карточке: номер, название и содержимое."""
    with st.container(key=f"step_{key}"):
        st.markdown(
            f"<div class='imes-step'><span class='imes-step-badge'>{number}</span>"
            f"<span class='imes-step-title'>{_esc(title)}</span></div>",
            unsafe_allow_html=True,
        )
        yield


def _analyze_file(file_name: str, data: bytes):
    """
    Читает файл преподавателя и коротко пишет, что это за файл (прямо под его именем).
    Возвращает (загруженный текст, это Aiken?) или None, если файл не прочитался.
    """
    try:
        loaded = load_question_file(data, Path(file_name).suffix)
    except ValueError as exc:
        st.error(str(exc))
        return None
    for warning_text in loaded.warnings:
        st.warning(warning_text)
    if not loaded.text.strip():
        st.error("Не удалось извлечь текст из файла — проверьте, что в нём есть текстовый слой.")
        return None
    is_aiken = looks_like_aiken(loaded.text)
    st.markdown(
        "<div class='imes-disclaimer'>"
        + (
            "Файл в формате <strong>Aiken</strong>: вопросы читаются без ИИ."
            if is_aiken
            else "Файл не в формате Aiken: вопросы найдёт ИИ."
        )
        + f" Символов: {_format_number(len(loaded.text))}.</div>",
        unsafe_allow_html=True,
    )
    return loaded, is_aiken


def _prepare_test(file_name: str, loaded, course_is_aiken: bool) -> None:
    """Кнопка «Подготовить тест»: отбор до 25 вопросов из файла преподавателя."""
    too_long = (not course_is_aiken) and len(loaded.text) > Config.COURSE_MAX_CHARS
    if too_long:
        st.error(
            f"Файл слишком большой для обработки ИИ: {_format_number(len(loaded.text))} символов, "
            f"предел — {_format_number(Config.COURSE_MAX_CHARS)}. Это защита от случайного большого "
            "расхода. Если файл настоящий, разрежьте его на части или поднимите COURSE_MAX_CHARS в .env."
        )
    if st.button("Подготовить тест", type="primary", disabled=too_long, key="course_prepare"):
        course_usage = None
        client = None
        try:
            if course_is_aiken:
                course_result = prepare_course_test(loaded.text, None)
            else:
                client = BotHubClient(max_caps=Config.COURSE_MAX_CAPS)
                progress = st.progress(0.0, text="Ищем вопросы...")

                def _on_progress(done: int, total: int) -> None:
                    progress.progress(done / total, text=f"Обработано фрагментов: {done} из {total}")

                course_result = prepare_course_test(
                    loaded.text, client.extract_course_questions, on_progress=_on_progress
                )
                progress.empty()
                course_usage = client.usage
        except Exception as exc:
            st.error(f"Не удалось подготовить тест: {exc}")
            # Даже при сбое часть запросов могла уже пройти и стоить денег — не прячем это.
            if client is not None and client.usage.calls:
                st.warning(
                    f"До сбоя успело пройти запросов: {client.usage.calls}, "
                    f"примерно {_format_number(client.usage.estimated_caps)} CAPS. "
                    "Сверьтесь с личным кабинетом BotHub."
                )
        else:
            st.session_state["course_usage"] = course_usage
            st.session_state["questions"] = [
                {"question": q, "source_text": "", "mode": "extract"}
                for q in course_result.questions
            ]
            st.session_state["course_result"] = course_result
            stem = re.sub(r"[^\w\-]+", "_", Path(file_name).stem).strip("_")
            st.session_state["course_source_stem"] = stem or "quiz"


def _download_buttons(questions_only: list, file_stem: str | None, simple: bool) -> None:
    """Кнопки скачивания. simple=True: только Aiken и Moodle XML (разделы с отправкой в Moodle)."""
    aiken_text = questions_to_aiken(questions_only)
    if simple:
        col_a, col_b, _ = st.columns([1, 1, 2])
        with col_a:
            st.download_button(
                label="Скачать в Aiken", data=aiken_text, file_name=f"{file_stem}_aiken.txt",
                mime="text/plain", disabled=not aiken_text,
                help="Для импорта в Moodle: Банк вопросов → Импорт → Aiken.",
            )
        with col_b:
            st.download_button(
                label="Скачать для Moodle (XML)", data=questions_to_moodle_xml(questions_only),
                file_name=f"{file_stem}_moodle.xml", mime="application/xml",
                help="Банк вопросов → Импорт → Moodle XML.",
            )
        return
    col_dl1, col_dl2, col_dl3, col_dl4, col_dl5 = st.columns(5)
    with col_dl1:
        st.download_button("Скачать в JSON", data=questions_to_json(questions_only),
                           file_name="quiz_questions.json", mime="application/json")
    with col_dl2:
        st.download_button("Скачать в Excel", data=questions_to_excel_bytes(questions_only),
                           file_name="quiz_questions.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col_dl3:
        st.download_button("Скачать в QTI", data=questions_to_qti_xml(questions_only),
                           file_name="quiz_questions_qti.xml", mime="application/xml")
    with col_dl4:
        st.download_button("Скачать для Moodle", data=questions_to_moodle_xml(questions_only),
                           file_name="quiz_questions_moodle.xml", mime="application/xml")
    with col_dl5:
        st.download_button(
            "Скачать в Aiken", data=aiken_text, file_name="quiz_questions_aiken.txt",
            mime="text/plain", disabled=not aiken_text,
            help="Простой текстовый формат для импорта в Moodle (Банк вопросов → Импорт → Aiken).",
        )
    aiken_skipped = count_skipped_for_aiken(questions_only)
    if aiken_skipped:
        st.markdown(
            f"<div class='imes-disclaimer'>В файл Aiken не вошло вопросов: <strong>{aiken_skipped}</strong>. "
            "Этот формат хранит только вопросы с выбором ответа и «верно/неверно»; "
            "соответствие, эссе и короткий ответ в нём выразить нельзя — "
            "для них используйте «Скачать для Moodle».</div>",
            unsafe_allow_html=True,
        )


# --- Переключатель разделов (оранжевая полоса на всю ширину) и описание выбранного раздела ---
with st.container(key="mode_switch"):
    section = st.radio("Раздел", _SECTIONS, horizontal=True, label_visibility="collapsed")
st.markdown(render_mode_description_html(section), unsafe_allow_html=True)

if section == _SECTION_REGISTRY:
    flow = _MODE_REGISTRY
elif section == _SECTION_FILE:
    all_types = bool(st.session_state.get("all_types_toggle", False))
    with st.container(key="mode_options"):
        col_off, col_switch, col_on = st.columns([5, 1.2, 5], vertical_alignment="center")
        with col_off:
            st.markdown(
                f"<div class='imes-switch-label right{'' if all_types else ' is-active'}'>{_esc(SWITCH_OFF_LABEL)}</div>",
                unsafe_allow_html=True,
            )
        with col_switch:
            st.toggle("Режим вопросов", key="all_types_toggle", label_visibility="collapsed")
        with col_on:
            st.markdown(
                f"<div class='imes-switch-label{' is-active' if all_types else ''}'>{_esc(SWITCH_ON_LABEL)}</div>",
                unsafe_allow_html=True,
            )
    if all_types:
        st.markdown(f"<div class='imes-switch-hint'>{_esc(SWITCH_ON_HINT)}</div>", unsafe_allow_html=True)
    flow = _MODE_EXTRACT if all_types else _MODE_FILE
else:
    flow = _MODE_GENERATE

# При смене раздела старые результаты больше не относятся к делу — сбрасываем,
# иначе они молча остаются висеть на экране под новым разделом.
if st.session_state.get("_active_mode") != flow:
    st.session_state["questions"] = []
    st.session_state["course_result"] = None
    st.session_state["course_usage"] = None
    st.session_state["_active_mode"] = flow


if flow == _MODE_GENERATE:
    # --- Тест из лекции: PDF → вопросы, придуманные ИИ ---
    chunks = []
    with _step(1, "Загрузите лекцию", "lecture_upload"):
        uploaded_file = st.file_uploader("PDF лекции", type="pdf", label_visibility="collapsed")
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
                f"{len(chunks)} смысловых блок(ов) текста для генерации.</div>",
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

    if chunks:
        with _step(2, "Выберите количество вопросов", "lecture_counts"):
            col1, col2, col3 = st.columns(3)
            with col1:
                n_mcq = st.number_input(_TYPE_LABELS_RU[QuestionType.MULTIPLE_CHOICE], min_value=0, max_value=20, value=3)
            with col2:
                n_tf = st.number_input(_TYPE_LABELS_RU[QuestionType.TRUE_FALSE], min_value=0, max_value=20, value=3)
            with col3:
                n_matching = st.number_input(_TYPE_LABELS_RU[QuestionType.MATCHING], min_value=0, max_value=20, value=2)
            col4, col5, _ = st.columns(3)
            with col4:
                n_essay = st.number_input(_TYPE_LABELS_RU[QuestionType.ESSAY], min_value=0, max_value=20, value=0)
            with col5:
                n_short_answer = st.number_input(_TYPE_LABELS_RU[QuestionType.SHORT_ANSWER], min_value=0, max_value=20, value=0)

        with _step(3, "Сгенерируйте вопросы", "lecture_generate"):
            if st.button("Сгенерировать вопросы", type="primary"):
                counts = {
                    QuestionType.MULTIPLE_CHOICE: n_mcq,
                    QuestionType.TRUE_FALSE: n_tf,
                    QuestionType.MATCHING: n_matching,
                    QuestionType.ESSAY: n_essay,
                    QuestionType.SHORT_ANSWER: n_short_answer,
                }
                active_types = {qt: c for qt, c in counts.items() if c > 0}

                if not active_types:
                    st.warning("Выберите хотя бы один тип вопросов с количеством больше 0.")
                else:
                    client = BotHubClient()
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
                                for q in questions:
                                    all_questions.append(
                                        {"question": q, "source_text": chunk.text, "mode": "generate"}
                                    )
                            except Exception as exc:
                                st.error(
                                    f"Ошибка генерации ({_TYPE_LABELS_RU[question_type]}, "
                                    f"страницы {chunk.page_numbers}): {exc}"
                                )

                    progress.empty()
                    st.session_state["questions"] = all_questions
                    st.success(f"Готово! Сгенерировано вопросов: {len(all_questions)}")

elif flow == _MODE_EXTRACT:
    # --- «Тест из файла» в режиме всех типов вопросов: найти в файле все вопросы, без лимита 25 ---
    existing_text = ""
    with _step(1, "Загрузите файл с вопросами", "extract_upload"):
        uploaded_existing = st.file_uploader(
            "Файл с вопросами", type=["pdf", "docx", "txt"], label_visibility="collapsed",
        )
        st.markdown(
            "<div class='imes-disclaimer'>Подойдут PDF, Word (.docx) и текст (.txt). Ответ должен быть "
            "отмечен словами («Ответ: Б») или знаком (*): жирный шрифт и подчёркивание в этом режиме "
            "не учитываются. Файл в формате Aiken читается без ИИ.</div>",
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
                    existing_text = parse_docx(tmp_path, mark_emphasis=False)  # у этого режима свой промпт, он меток не знает
                finally:
                    os.unlink(tmp_path)
            else:  # .txt
                existing_text = raw_bytes.decode("utf-8", errors="replace")

            if not existing_text.strip():
                st.error("Не удалось извлечь текст из файла — проверьте, что в нём есть текстовый слой.")
            else:
                st.markdown(
                    f"<div class='imes-disclaimer'>Извлечено символов: {_format_number(len(existing_text))}.</div>",
                    unsafe_allow_html=True,
                )

    if existing_text.strip():
        is_aiken = looks_like_aiken(existing_text)

        if is_aiken:
            # --- Файл в формате Aiken: читаем обычным кодом, без ИИ ---
            with _step(2, "Прочитайте вопросы", "extract_aiken"):
                st.markdown(
                    "<div class='imes-disclaimer'>Файл распознан как <strong>Aiken</strong>. Он строгий, "
                    "поэтому вопросы читаются обычной программой, без ИИ: бесплатно и без домыслов. "
                    "Aiken хранит только вопросы с выбором ответа и «верно/неверно».</div>",
                    unsafe_allow_html=True,
                )
                if st.button("Прочитать вопросы", type="primary"):
                    parsed = parse_aiken(existing_text)
                    st.session_state["questions"] = [
                        {"question": q, "source_text": existing_text, "mode": "extract"}
                        for q in parsed.questions
                    ]
                    if parsed.questions:
                        st.success(f"Готово! Прочитано вопросов: {len(parsed.questions)}")
                    else:
                        st.warning("Ни один вопрос прочитать не удалось.")
                    if parsed.errors:
                        st.warning(
                            f"Не удалось прочитать вопросов: {len(parsed.errors)}. "
                            "Эти вопросы пропущены:\n\n"
                            + "\n".join(f"- {err}" for err in parsed.errors)
                        )
        else:
            with _step(2, "Выберите типы вопросов", "extract_types"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    find_mcq = st.checkbox(_TYPE_LABELS_RU[QuestionType.MULTIPLE_CHOICE], value=True)
                with col2:
                    find_tf = st.checkbox(_TYPE_LABELS_RU[QuestionType.TRUE_FALSE], value=True)
                with col3:
                    find_matching = st.checkbox(_TYPE_LABELS_RU[QuestionType.MATCHING], value=True)
                col4, col5, _ = st.columns(3)
                with col4:
                    find_essay = st.checkbox(_TYPE_LABELS_RU[QuestionType.ESSAY], value=True)
                with col5:
                    find_short_answer = st.checkbox(_TYPE_LABELS_RU[QuestionType.SHORT_ANSWER], value=True)

            with _step(3, "Извлеките вопросы", "extract_run"):
                if st.button("Извлечь вопросы", type="primary"):
                    types_to_find = [
                        qt for qt, enabled in [
                            (QuestionType.MULTIPLE_CHOICE, find_mcq),
                            (QuestionType.TRUE_FALSE, find_tf),
                            (QuestionType.MATCHING, find_matching),
                            (QuestionType.ESSAY, find_essay),
                            (QuestionType.SHORT_ANSWER, find_short_answer),
                        ] if enabled
                    ]

                    if not types_to_find:
                        st.warning("Выберите хотя бы один тип вопросов для поиска.")
                    else:
                        client = BotHubClient()
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
                                for q in questions:
                                    all_questions.append(
                                        {"question": q, "source_text": existing_text, "mode": "extract"}
                                    )
                            except Exception as exc:
                                st.error(f"Ошибка извлечения ({_TYPE_LABELS_RU[question_type]}): {exc}")

                        progress.empty()
                        st.session_state["questions"] = all_questions
                        if all_questions:
                            st.success(f"Готово! Найдено вопросов: {len(all_questions)}")
                        else:
                            st.warning("Вопросов выбранных типов в файле не нашлось.")

else:
    # --- «Тест из реестра» и «Тест из файла»: файл преподавателя → до 25 вопросов → Moodle ---
    registry_ctx = None  # (реестр, запись) — только в разделе «из реестра»
    analysis_box: dict = {}  # "v" = (текст файла, это Aiken?) — результат чтения файла преподавателя
    source_name = None
    sig = None
    if flow == _MODE_REGISTRY:
        with _step(1, "Выберите запись реестра", "source"):
            def _note(name: str, data: bytes) -> None:
                analysis_box["v"] = _analyze_file(name, data)

            picked = pick_registry_entry(on_file=_note)
        if picked is not None:
            registry, entry, source_name, source_bytes = picked
            registry_ctx = (registry, entry)
            sig = ("registry", entry.entry_id, len(source_bytes))
    else:
        with _step(1, "Загрузите файл преподавателя", "source"):
            uploaded_course = st.file_uploader(
                "Файл преподавателя", type=["pdf", "docx", "txt"], label_visibility="collapsed",
                key="course_uploader",
            )
            if uploaded_course is not None:
                course_bytes = uploaded_course.read()
                source_name = uploaded_course.name
                sig = ("file", source_name, len(course_bytes))
                analysis_box["v"] = _analyze_file(source_name, course_bytes)
            with st.expander("Как приложение определяет правильный ответ"):
                st.markdown(
                    "Подойдёт Aiken, Word, PDF или текст в любом оформлении. Ответ может быть отмечен "
                    "словами («Ответ: Б»), знаком (*, +), ключом в конце файла, жирным шрифтом, "
                    "подчёркиванием, маркером или цветом. **ИИ ответы сам не выбирает**: он только "
                    "переносит пометки из файла. Нет пометки — вопрос пропускается, и это видно в отчёте. "
                    "В тест входят первые 25 подходящих вопросов с одним верным ответом."
                )
    _reset_course_if_changed(sig)
    analysis = analysis_box.get("v")

    if analysis is not None:
        with _step(2, "Подготовьте тест", "prepare"):
            _prepare_test(source_name, analysis[0], analysis[1])
            if st.session_state.get("course_result") is not None:
                _render_course_report(st.session_state["course_result"], st.session_state.get("course_usage"))


# --- Результат, отправка в Moodle или скачивание ---
if st.session_state.get("questions"):
    items = st.session_state["questions"]
    is_course = flow in _COURSE_MODES
    with _step(3 if is_course else 4, f"Проверьте результат ({len(items)})", "result"):
        for i, item in enumerate(items):
            st.markdown(_render_question_card(item["question"], i + 1), unsafe_allow_html=True)
            if item["mode"] == "generate":
                col_regen, _ = st.columns([1, 4])
                with col_regen:
                    if st.button("🔄 Перегенерировать", key=f"regen_{i}"):
                        try:
                            client = BotHubClient()
                            new_questions = client.generate_questions(
                                text=item["source_text"],
                                question_type=item["question"].type,
                                count=1,
                                source_pages=item["question"].source_pages,
                            )
                            if new_questions:
                                st.session_state["questions"][i] = {
                                    "question": new_questions[0],
                                    "source_text": item["source_text"],
                                    "mode": "generate",
                                }
                                st.rerun()
                            else:
                                st.warning("Не удалось получить новый вопрос — попробуйте ещё раз.")
                        except Exception as exc:
                            st.error(f"Ошибка перегенерации: {exc}")

        if is_course:
            st.markdown(
                "<div class='imes-warning-white'>"
                "<strong>Перед отправкой в курс сверьте ответы с исходным файлом.</strong> "
                "В отчёте выше список «Как определены правильные ответы» показывает пометку, "
                "по которой выбран каждый ответ.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='imes-warning-white'>"
                "<strong>Перед использованием проверьте вопросы.</strong> ИИ может ошибаться, "
                "особенно в выборе правильного варианта. Если в поле «Объяснение» нет связного текста, "
                "сверьте ответ с лекцией. Неверный вопрос можно заменить кнопкой «Перегенерировать».</div>",
                unsafe_allow_html=True,
            )

    questions_only = [item["question"] for item in items]
    if is_course:
        file_stem = st.session_state.get("course_source_stem") or "quiz"
        with _step(4, "Отправьте в Moodle", "send"):
            panel_kwargs = {}
            if registry_ctx is not None:
                registry, entry = registry_ctx
                panel_kwargs = {"course_id": entry.course_id, "entry": entry, "registry": registry}
            render_moodle_panel(
                questions_only, file_stem,
                st.session_state.get("course_result"), st.session_state.get("course_usage"),
                **panel_kwargs,
            )
            st.markdown("<div class='imes-caption'>Или скачайте файлы и импортируйте в Moodle вручную</div>",
                        unsafe_allow_html=True)
            _download_buttons(questions_only, file_stem, simple=True)
    else:
        with _step(5, "Скачайте тест", "download"):
            _download_buttons(questions_only, None, simple=False)
