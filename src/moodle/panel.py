"""Блоки интерфейса «Moodle»: выбор записи из реестра и отправка результата (реестр + курс)."""
from __future__ import annotations

import html
import os

import streamlit as st

from src.config import Config
from src.exporters.aiken_exporter import questions_to_aiken
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.moodle.client import QUIZ_SECTION_NAME, MoodleClient, MoodleError, QuizSettings
from src.moodle.publish import UploadLog, can_publish, fingerprint, make_report
from src.moodle.registry import (
    F_COURSE_NAME, F_GROUP, F_SOURCE, F_TEACHER, STATUS_DONE, STATUS_NEW, STATUS_UPLOADED,
    MoodleRegistry, RegistryEntry,
)


def moodle_configured() -> bool:
    return bool(Config.MOODLE_URL and Config.MOODLE_TOKEN)


def _registry(client: MoodleClient) -> MoodleRegistry | None:
    raw = os.getenv("MOODLE_REGISTRY_COURSE", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return None
    return MoodleRegistry(client, int(raw), os.getenv("MOODLE_REGISTRY_NAME") or None)


# --- Раздел «Тест из реестра»: выбор записи и файла преподавателя ----------------------

def _entry_label(entry: RegistryEntry) -> str:
    v = entry.values
    parts = [v.get(F_COURSE_NAME) or f"запись {entry.entry_id}"]
    if entry.course_id:
        parts.append(f"курс № {entry.course_id}")
    for key in (F_GROUP, F_TEACHER):
        if v.get(key):
            parts.append(v[key])
    if entry.status:
        parts.append(f"[{entry.status}]")
    return " · ".join(parts)


def pick_registry_entry(on_file=None):
    """
    Показывает список записей реестра: слева запись, справа её файл преподавателя.
    Скачивает файл выбранной записи в память.

    on_file(имя, байты) вызывается в правой колонке сразу под именем файла:
    туда приложение выводит заметку про сам файл.

    Возвращает (registry, entry, имя_файла, байты) или None, если выбор ещё не сделан
    или что-то не так (причина показана на экране).
    """
    if not moodle_configured():
        st.info("Связь с Moodle не настроена: добавьте MOODLE_URL и MOODLE_TOKEN в .env (см. .env.example).")
        return None
    try:
        client = MoodleClient()
    except MoodleError as exc:
        st.error(str(exc))
        return None
    registry = _registry(client)
    if registry is None:
        st.info("Реестр не настроен: добавьте в .env строку MOODLE_REGISTRY_COURSE=17 (номер курса с базой данных).")
        return None

    col_all, col_refresh, _ = st.columns([3, 2, 3], vertical_alignment="center")
    with col_all:
        show_all = st.checkbox("Отображать обработанные записи", key="registry_show_all")
    with col_refresh:
        if st.button("Обновить список", key="registry_refresh"):
            st.session_state.pop("_registry_entries", None)
            st.session_state.pop("_registry_files", None)

    if "_registry_entries" not in st.session_state:
        try:
            with st.spinner("Читаю реестр..."):
                st.session_state["_registry_entries"] = registry.entries()
        except MoodleError as exc:
            st.error(f"Не удалось прочитать реестр: {exc}")
            return None
    entries: list[RegistryEntry] = st.session_state["_registry_entries"]

    shown = [e for e in entries if show_all or e.status in ("", STATUS_NEW)]
    if not shown:
        st.info("Необработанных записей в реестре нет. Включите «Отображать обработанные записи», чтобы увидеть все.")
        return None

    by_id = {e.entry_id: e for e in shown}
    col_entry, col_file = st.columns([3, 2])
    with col_entry:
        chosen = st.selectbox(
            "Запись реестра",
            options=list(by_id),
            format_func=lambda i: _entry_label(by_id[i]),
            key="registry_entry_id",
        )
    entry = by_id[chosen]

    files = entry.files.get(F_SOURCE, [])
    with col_file:
        st.markdown("<div class='imes-field-label'>Файл преподавателя</div>", unsafe_allow_html=True)
        if not files:
            st.warning("В этой записи нет файла преподавателя.")
            return None
        if entry.course_id is None:
            st.error("В записи нет корректной ссылки на курс (ожидается …/course/view.php?id=число).")
            return None

        source = files[0]
        cache = st.session_state.setdefault("_registry_files", {})
        key = (entry.entry_id, source.url)
        if key not in cache:
            try:
                with st.spinner(f"Скачиваю файл «{source.name}»..."):
                    cache[key] = registry.download(source)
            except MoodleError as exc:
                st.error(str(exc))
                return None
        st.markdown(f"<div class='imes-file-chip'>📄 {html.escape(source.name)}</div>", unsafe_allow_html=True)
        if on_file is not None:
            on_file(source.name, cache[key])
    return registry, entry, source.name, cache[key]


# --- Шаг «Отправить в Moodle» ------------------------------------------------------------

def _course_title(client: MoodleClient, course_id: int, fallback: str = "") -> str:
    """Название курса из Moodle (с запоминанием на сессию); если не получилось, запасной вариант."""
    cache = st.session_state.setdefault("_course_names", {})
    if course_id not in cache:
        cache[course_id] = client.course_name(course_id)
    return cache[course_id] or fallback


def _quiz_settings_form(title: str) -> QuizSettings:
    """Свёрнутый блок настроек теста: значения по умолчанию можно поменять перед созданием."""
    default = QuizSettings(name="")
    with st.expander("Настройки теста в курсе"):
        name = st.text_input(
            "Название теста",
            value=f"Промежуточная аттестация: {title}" if title else "Промежуточная аттестация",
            key="quiz_name",
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            minutes = st.number_input("Время, минут (0 — без ограничения)", min_value=0, max_value=600,
                                      value=default.time_limit_minutes, step=5, key="quiz_minutes")
        with c2:
            attempts = st.number_input("Попыток (0 — без ограничения)", min_value=0, max_value=20,
                                       value=default.attempts, key="quiz_attempts")
        with c3:
            points = st.number_input("Баллов за вопрос", min_value=0.5, max_value=100.0,
                                     value=float(default.points_per_question), step=0.5, key="quiz_points")
        shuffle_q = st.checkbox("Перемешивать вопросы", value=default.shuffle_questions, key="quiz_shuffle_q")
        shuffle_a = st.checkbox("Перемешивать варианты ответов", value=default.shuffle_answers, key="quiz_shuffle_a")
        visible = st.checkbox("Сразу показать тест студентам", value=default.visible, key="quiz_visible",
                              help="По умолчанию тест создаётся скрытым: его сначала проверяют и сами открывают.")
        st.caption("Проходного балла нет. После попытки студент видит оценку, но не правильные ответы.")
    return QuizSettings(
        name=name.strip() or "Промежуточная аттестация",
        visible=visible, attempts=int(attempts), time_limit_minutes=int(minutes),
        points_per_question=float(points), shuffle_questions=shuffle_q, shuffle_answers=shuffle_a,
    )


def _create_quiz(client: MoodleClient, course_id: int, category: str, questions, settings: QuizSettings,
                 log: UploadLog, fp: str, entry, registry, result, usage, file_stem: str) -> None:
    """Создаёт тест в курсе: вопросы попадают в банк (в указанную папку) и в новый тест."""
    try:
        if not client.plugin_available():
            st.error("На сайте не найден плагин создания тестов (local_qbankremotemanager) или его функции "
                     "не добавлены в службу Moodle. Вопросы можно загрузить в банк вопросов отдельной кнопкой.")
            return
        section = client.section_number(course_id)
        if section is None:
            st.error(f"В курсе № {course_id} нет раздела «{QUIZ_SECTION_NAME}». Создайте его в курсе "
                     "и повторите: тест кладётся в этот раздел.")
            return
        settings.section = section
        xml_text = questions_to_moodle_xml(questions, category=category, default_grade=settings.points_per_question)
        created = client.create_quiz(course_id, xml_text, settings, filename=f"{file_stem}_moodle.xml")
    except MoodleError as exc:
        st.error(f"Не удалось создать тест: {exc}")
        return

    log.add(fp, course_id, category, len(questions), kind="quiz")
    state = "скрыт от студентов" if not settings.visible else "виден студентам"
    st.success(f"Тест создан в курсе № {course_id}: вопросов {created['questions']}, "
               f"максимум {created['questions'] * settings.points_per_question:g} баллов, тест {state}.")
    st.markdown(f"[Открыть тест в Moodle]({created['url']})")
    if entry is not None and registry is not None:
        try:
            registry.set_status(entry.entry_id, STATUS_UPLOADED,
                                report=make_report(result, usage, len(questions)) + f"\nТест создан в курсе: {created['url']}")
        except MoodleError as exc:
            st.warning(f"Тест создан, но статус в базе данных не обновился: {exc}")


def render_moodle_panel(
    questions,
    file_stem: str,
    result=None,
    usage=None,
    *,
    course_id: int | None = None,
    entry: RegistryEntry | None = None,
    registry: MoodleRegistry | None = None,
) -> None:
    """
    Содержимое шага «Отправьте в Moodle» (заголовок рисует app.py).

    course_id и entry/registry передаёт раздел «из реестра» (курс известен, запись обновляем).
    В разделе «из файла» их нет: номер курса вводится вручную, в реестр ничего не пишем.
    """
    if not moodle_configured():
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

    registry_course_id = course_id  # курс из ссылки в записи реестра (в разделе «из файла» его нет)
    col1, col2 = st.columns([1, 2])
    with col1:
        course_raw = st.text_input(
            "Номер курса",
            value=str(registry_course_id) if registry_course_id else "",
            key=f"moodle_course_id_{entry.entry_id}" if entry is not None else "moodle_course_id",
            help="Число из адреса курса: …/course/view.php?id=16 → 16. "
                 "В разделе «из реестра» подставляется из записи; измените, если тест нужно отправить в другой курс.",
        )
    with col2:
        category = st.text_input("Папка в банке вопросов", value=Config.MOODLE_CATEGORY, key="moodle_category")
    if not course_raw.strip().isdigit():
        st.caption("Введите номер курса, и появятся кнопки отправки.")
        return
    course_id = int(course_raw.strip())
    title = _course_title(
        client, course_id,
        fallback=(entry.values.get(F_COURSE_NAME, "") if entry is not None and course_id == registry_course_id else ""),
    )
    if registry_course_id and course_id != registry_course_id:
        st.caption(f"В записи реестра указан курс № {registry_course_id}, отправка пойдёт в курс № {course_id}.")
    category = category.strip() or Config.MOODLE_CATEGORY

    xml_text = questions_to_moodle_xml(questions, category=category)
    fp = fingerprint(course_id, category, xml_text)
    log = UploadLog()
    already = log.find(fp)

    title_html = f"«{html.escape(title)}»" if title else "<em>название не получено</em>"
    st.markdown(
        f"<div class='imes-panel-note'><div>Курс № <strong>{course_id}</strong> · {title_html}</div>"
        f"<div class='imes-panel-sub'>Вопросов: {len(questions)} · папка в банке вопросов: «{html.escape(category)}»</div></div>",
        unsafe_allow_html=True,
    )
    if not title:
        st.caption(
            "Название курса не удалось получить: проверьте номер курса или добавьте функцию "
            "core_course_get_courses_by_field в службу Moodle."
        )
    if already:
        st.warning(f"Этот тест уже загружали в этот курс ({already['when']}). Повторная загрузка создаст вопросы второй раз.")
    confirmed = st.checkbox(
        "Я проверил(а) вопросы и курс" + (" и всё равно загружаю ещё раз" if already else ""),
        key="moodle_confirm",
    )

    report = make_report(result, usage, len(questions))
    c_reg, c_course = st.columns(2)
    with c_reg:
        if entry is not None and registry is not None:
            if st.button("Добавить обработанный файл в базу данных", disabled=not confirmed,
                         key="moodle_save_registry",
                         help="В запись реестра попадут файлы Moodle XML и Aiken, статус «Обработан» и отчёт."):
                try:
                    registry.save_result(
                        entry.entry_id,
                        xml_name=f"{file_stem}_moodle.xml", xml_text=xml_text,
                        aiken_name=f"{file_stem}_aiken.txt", aiken_text=questions_to_aiken(questions),
                        status=STATUS_DONE, report=report,
                    )
                    st.success("Обработанный файл добавлен в базу данных.")
                except MoodleError as exc:
                    st.error(f"Не удалось добавить файл в базу данных: {exc}")
    with c_course:
        if st.button("Загрузить вопросы в банк вопросов курса", type="primary", disabled=not confirmed,
                     key="moodle_upload", help="Вопросы попадут в банк вопросов курса, в указанную папку."):
            try:
                message = client.import_xml(course_id, xml_text, filename=f"{file_stem}_moodle.xml")
                log.add(fp, course_id, category, len(questions))
                st.success(f"Вопросы загружены в курс № {course_id}. {message}")
                if entry is not None and registry is not None:
                    try:
                        registry.set_status(entry.entry_id, STATUS_UPLOADED)
                    except MoodleError as exc:
                        st.warning(f"Вопросы в курсе, но статус в базе данных не обновился: {exc}")
            except MoodleError as exc:
                st.error(f"Не удалось загрузить в курс: {exc}")

    st.markdown("<div class='imes-panel-sub'>Или создайте готовый тест: вопросы попадут и в банк, и в новый тест "
                f"в разделе «{html.escape(QUIZ_SECTION_NAME)}».</div>", unsafe_allow_html=True)
    settings = _quiz_settings_form(title)
    if st.button("Создать тест в курсе", disabled=not confirmed, key="moodle_create_quiz",
                 help="Тест создаётся скрытым. Не нажимайте вместе с загрузкой в банк: вопросы задвоятся."):
        _create_quiz(client, course_id, category, questions, settings, log, fp, entry, registry,
                     result, usage, file_stem)
