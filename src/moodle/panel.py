"""Блок интерфейса «Moodle»: сохранить результат в реестр и загрузить вопросы в курс."""
from __future__ import annotations

import os

import streamlit as st

from src.config import Config
from src.exporters.aiken_exporter import questions_to_aiken
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.moodle.client import MoodleClient, MoodleError
from src.moodle.publish import UploadLog, can_publish, fingerprint, make_report
from src.moodle.registry import (
    STATUS_DONE, STATUS_UPLOADED, MoodleRegistry, RegistryEntry,
)


def _registry(client: MoodleClient) -> MoodleRegistry | None:
    raw = os.getenv("MOODLE_REGISTRY_COURSE", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return None
    return MoodleRegistry(client, int(raw), os.getenv("MOODLE_REGISTRY_NAME") or None)


def render_moodle_panel(questions, file_stem: str, result=None, usage=None) -> None:
    st.markdown(
        "<div class='imes-step'><span class='imes-step-badge'>4</span>"
        "<span class='imes-step-title'>Отправить в Moodle</span></div>",
        unsafe_allow_html=True,
    )
    if not (Config.MOODLE_URL and Config.MOODLE_TOKEN):
        st.info("Связь с Moodle не настроена: добавьте MOODLE_URL и MOODLE_TOKEN в .env (см. .env.example).")
        return

    ok, why_not = can_publish(result)
    if not ok:
        st.error(why_not)
        return

    try:
        client = MoodleClient()
    except MoodleError as exc:
        st.error(str(exc))
        return
    registry = _registry(client)

    col1, col2 = st.columns([1, 2])
    with col1:
        course_raw = st.text_input("Номер курса", key="moodle_course_id", help="Число из адреса курса: …/course/view.php?id=16 → 16")
    with col2:
        category = st.text_input("Папка в банке вопросов", value=Config.MOODLE_CATEGORY, key="moodle_category")

    if not course_raw.strip().isdigit():
        st.caption("Введите номер курса — тогда появятся кнопки отправки.")
        return
    course_id = int(course_raw.strip())
    category = category.strip() or Config.MOODLE_CATEGORY

    entry: RegistryEntry | None = None
    if registry is not None:
        try:
            matches = registry.find_by_course(course_id)
        except MoodleError as exc:
            st.warning(f"Реестр недоступен: {exc}")
            matches = []
        if len(matches) == 1:
            entry = matches[0]
            st.success(f"Запись в реестре найдена: «{entry.values.get('Наименование курса', '')}», статус «{entry.status}».")
        elif len(matches) > 1:
            st.warning(f"В реестре несколько записей с курсом № {course_id} — запись выберите вручную, автоматически не обновляю.")
        else:
            st.caption("Записи этого курса в реестре нет — результат можно загрузить в курс, но не в реестр.")

    xml_text = questions_to_moodle_xml(questions, category=category)
    fp = fingerprint(course_id, category, xml_text)
    log = UploadLog()
    already = log.find(fp)
    st.markdown(
        f"<div class='imes-disclaimer'>В курс № <strong>{course_id}</strong> на {Config.MOODLE_URL} "
        f"будет загружено вопросов: <strong>{len(questions)}</strong>, в папку «{category}».</div>",
        unsafe_allow_html=True,
    )
    if already:
        st.warning(
            f"Этот тест уже загружали в этот курс ({already['when']}). Повторная загрузка создаст вопросы второй раз."
        )
    confirmed = st.checkbox(
        "Я проверил(а) вопросы и готов(а) отправить" + (" ещё раз" if already else ""), key="moodle_confirm"
    )

    c_reg, c_course, _ = st.columns([1, 1, 1])
    report = make_report(result, usage, len(questions))
    with c_reg:
        if st.button("Сохранить в реестр", disabled=not (confirmed and entry), help="Файлы XML и Aiken, статус «Обработан» и отчёт."):
            try:
                registry.save_result(
                    entry.entry_id,
                    xml_name=f"{file_stem}_moodle.xml", xml_text=xml_text,
                    aiken_name=f"{file_stem}_aiken.txt", aiken_text=questions_to_aiken(questions),
                    status=STATUS_DONE, report=report,
                )
                st.success("Результат сохранён в реестре.")
            except MoodleError as exc:
                st.error(f"Не удалось сохранить в реестр: {exc}")
    with c_course:
        if st.button("Загрузить в курс", type="primary", disabled=not confirmed, help="Вопросы попадут в банк вопросов курса, в указанную папку."):
            try:
                message = client.import_xml(course_id, xml_text, filename=f"{file_stem}_moodle.xml")
                log.add(fp, course_id, category, len(questions))
                st.success(f"Вопросы загружены в курс № {course_id}. {message}")
                if entry is not None:
                    try:
                        registry.set_status(entry.entry_id, STATUS_UPLOADED)
                    except MoodleError as exc:
                        st.warning(f"Вопросы в курсе, но статус в реестре не обновился: {exc}")
            except MoodleError as exc:
                st.error(f"Не удалось загрузить в курс: {exc}")
