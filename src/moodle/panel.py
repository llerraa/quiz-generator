"""Блоки интерфейса «Moodle»: выбор записи из реестра и отправка результата (реестр + курс)."""
from __future__ import annotations

import html
import os

import streamlit as st

from src.config import Config
from src.exporters.aiken_exporter import questions_to_aiken
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.exporters.gift_exporter import questions_to_gift
from src.moodle import registry_table as T
from src.moodle.client import (
    GRADE_CATEGORY_PREFIX, QUIZ_SECTION_NAME, MoodleClient, MoodleError, QuizSettings, pick_grade_category, quiz_title,
)
from src.moodle.publish import (
    UploadLog, can_publish, fingerprint, make_report, make_rework_report, quiz_blocked_reason,
)
from src.moodle.registry import (
    F_COURSE_NAME, F_GROUP, F_SOURCE, F_TEACHER, STATUS_BANK, STATUS_QUIZ, STATUS_REWORK,
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

    # Фильтры над таблицей
    c_status, c_file, c_sort = st.columns([3, 2, 2])
    with c_status:
        statuses = st.multiselect("Статус", options=T.status_options(entries), default=T.DEFAULT_STATUSES,
                                  key="registry_statuses")
    with c_file:
        file_filter = st.selectbox("Файл от зав кафедрой", T.FILE_CHOICES, key="registry_file_filter")
    with c_sort:
        sort_mode = st.selectbox("Порядок", T.SORT_CHOICES, key="registry_sort")
    query = st.text_input("Поиск по названию курса, группе, преподавателю, кафедре или номеру курса", key="registry_query")

    shown = T.sort_entries(T.filter_entries(entries, statuses, file_filter, query), sort_mode)
    st.caption(f"Показано записей: {len(shown)} из {len(entries)}.")
    if not shown:
        st.info("Под выбранные фильтры записей нет. Добавьте статусы в фильтр «Статус», чтобы увидеть остальные.")
        return None

    # Таблица: клик по строке выбирает запись (ссылка на курс открывается отдельным кликом по ячейке)
    frame = T.entries_frame(shown)
    event = st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"registry_table_{len(shown)}_{abs(hash(tuple(e.entry_id for e in shown)))}",
        column_config={
            "Ссылка на курс": st.column_config.LinkColumn("Ссылка на курс", display_text="Открыть курс"),
            "Изменено": st.column_config.DatetimeColumn("Изменено", format="DD.MM.YYYY HH:mm"),
        },
    )
    clicked = event.selection.rows if event is not None and getattr(event, "selection", None) else []

    by_id = {e.entry_id: e for e in shown}
    order = list(by_id)
    col_entry, col_file = st.columns([3, 2])
    with col_entry:
        chosen = st.selectbox(
            "Запись реестра (кликните строку в таблице или выберите здесь)",
            options=order,
            index=clicked[0] if clicked and clicked[0] < len(order) else 0,
            format_func=lambda i: _entry_label(by_id[i]),
        )
    entry = by_id[chosen]

    files = entry.files.get(F_SOURCE, [])
    with col_file:
        st.markdown("<div class='imes-field-label'>Файл от зав кафедрой</div>", unsafe_allow_html=True)
        if not files:
            st.warning("В этой записи нет файла от зав кафедрой.")
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

def _course_info(client: MoodleClient, course_id: int) -> dict:
    """Название курса и название дисциплины из полей курса (с запоминанием на сессию)."""
    cache = st.session_state.setdefault("_course_info", {})
    if course_id not in cache:
        cache[course_id] = client.course_info(course_id)
    return cache[course_id]


def _grade_categories(client: MoodleClient, course_id: int) -> list[str] | None:
    """Категории журнала оценок курса (с запоминанием на сессию); None — узнать не удалось."""
    cache = st.session_state.setdefault("_grade_categories", {})
    if course_id not in cache:
        try:
            names = client.grade_categories(course_id)
        except MoodleError as exc:
            st.warning(str(exc))
            return None
        if names is None:
            return None  # неудачу не запоминаем: после исправления (плагин, права) список подтянется сам
        cache[course_id] = names
    return cache[course_id]


def _course_title(client: MoodleClient, course_id: int, fallback: str = "") -> str:
    """Название курса из Moodle (с запоминанием на сессию); если не получилось, запасной вариант."""
    return _course_info(client, course_id)["name"] or fallback


def _quiz_settings_form(discipline: str | None, course_id: int | None = None,
                        custom_fields: list[str] | None = None,
                        grade_categories: list[str] | None = None,
                        grade_categories_error: str | None = None) -> QuizSettings:
    """
    Свёрнутый блок настроек теста: значения по умолчанию можно поменять перед созданием.

    discipline: «Название дисциплины» из полей курса (из 1С); из него собирается название теста.
    """
    default = QuizSettings(name="")
    with st.expander("Настройки теста в курсе"):
        name = st.text_input(
            "Название теста",
            value=quiz_title(discipline),
            key=f"quiz_name_{course_id}_{abs(hash(discipline or ''))}",  # другой курс → название подставится заново
            help="«Тест. Промежуточная аттестация по дисциплине …»; название дисциплины берётся из настроек курса, "
                 "раздел «Поля из 1С».",
        )
        if not discipline:
            if custom_fields:
                st.caption("В полях курса «Поля из 1С» не нашлось заполненного названия дисциплины (поле «Название "
                           "дисциплины» или discipline_name). Moodle вернул поля: " + ", ".join(custom_fields)
                           + ". Впишите название в название теста вручную.")
            else:
                st.caption("В полях курса «Поля из 1С» не нашлось названия дисциплины: Moodle не вернул дополнительных "
                           "полей курса (проверьте, что поле заполнено и видно пользователю токена). "
                           "Впишите название в название теста вручную.")
        grade_category = _grade_category_picker(course_id, grade_categories, grade_categories_error)
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
        idnumber = st.text_input("Идентификационный номер теста", value=default.idnumber or "",
                                 key="quiz_idnumber",
                                 help="Номер элемента оценивания в журнале; на него ссылаются формулы категорий "
                                      "([[ПА-тест]]). Должен быть уникальным в курсе. Пусто: номер не задаётся. "
                                      "Формулу категории приложение не меняет: её правят вручную.")
        shuffle_q = st.checkbox("Перемешивать вопросы", value=default.shuffle_questions, key="quiz_shuffle_q")
        shuffle_a = st.checkbox("Перемешивать варианты ответов", value=default.shuffle_answers, key="quiz_shuffle_a")
        visible = st.checkbox("Сразу показать тест студентам", value=default.visible, key="quiz_visible",
                              help="По умолчанию тест создаётся скрытым: его сначала проверяют и сами открывают.")
        st.caption("Проходного балла нет. После попытки студент видит оценку, но не правильные ответы.")
    return QuizSettings(
        name=name.strip() or quiz_title(discipline),
        visible=visible, attempts=int(attempts), time_limit_minutes=int(minutes),
        points_per_question=float(points), shuffle_questions=shuffle_q, shuffle_answers=shuffle_a,
        grade_category=grade_category, idnumber=idnumber.strip() or None,
    )


def _grade_category_picker(course_id: int | None, categories: list[str] | None, reason: str | None = None) -> str | None:
    """Выбор категории журнала оценок: по умолчанию «ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ …», если она есть в курсе."""
    help_text = ("Категория журнала оценок курса, в которую попадёт тест. Название должно совпадать с журналом "
                 "(регистр важен). Если категория не выбрана, Moodle положит тест вне категорий.")
    if categories is None:
        st.caption("Не удалось получить список категорий журнала оценок: без названия категории Moodle положит тест "
                   "в корень журнала. Название можно вписать вручную.")
        if reason:
            st.caption(f"Ответ Moodle: {reason[:400]}")
        return st.text_input("Категория журнала оценок", value="", key=f"quiz_gradecat_text_{course_id}",
                             help=help_text).strip() or None
    picked = pick_grade_category(categories)
    if picked is None:
        st.caption(f"В журнале оценок курса нет категории «{GRADE_CATEGORY_PREFIX}…»: по умолчанию тест "
                   "попадёт в корень журнала. Выберите другую категорию, если нужно.")
    return st.selectbox("Категория журнала оценок", categories,
                        index=categories.index(picked) if picked in categories else 0,
                        key=f"quiz_gradecat_{course_id}", help=help_text)


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
        if "cmidnumber_taken" in str(exc):
            st.info("Идентификационный номер уже занят в курсе. Так бывает, если в курсе уже есть элемент журнала "
                    "с таким номером или тест с ним только что удалили: Moodle завершает удаление при следующем "
                    "запуске cron. Посмотрите «Значения ID» в «Редактировать формулу» категории журнала, освободите "
                    "номер и повторите. Номер можно сменить в «Настройках теста в курсе», но тогда формула "
                    "категории должна ссылаться на него.")
        return

    log.add(fp, course_id, category, len(questions), kind="quiz")
    state = "скрыт от студентов" if not settings.visible else "виден студентам"
    st.success(f"Тест создан в курсе № {course_id}: вопросов {created['questions']}, "
               f"максимум {created['questions'] * settings.points_per_question:g} баллов, тест {state}.")
    st.markdown(f"[Открыть тест в Moodle]({created['url']})")
    for warning in created.get("warnings", []):
        st.warning(warning)
    if entry is not None and registry is not None:
        try:
            registry.set_status(entry.entry_id, STATUS_QUIZ,
                                report=make_report(result, usage, len(questions), quiz_url=created["url"]))
        except MoodleError as exc:
            st.warning(f"Тест создан, но статус в базе данных не обновился: {exc}")


def _rework_button(entry, registry, result) -> None:
    """Кнопка «Отправить на доработку»: статус записи меняется, в отчёт попадают причины пропуска вопросов."""
    if entry is None or registry is None:
        return
    st.markdown("<div class='imes-panel-sub'>Если файл не подходит (мало вопросов, нет пометок ответов), "
                "отправьте его преподавателю на доработку: в записи появится статус и причины.</div>",
                unsafe_allow_html=True)
    if st.button("Отправить на доработку", key="moodle_rework",
                 help="Статус записи: «Отправлен на доработку (тест не сформирован)», в отчёт попадут причины."):
        try:
            registry.set_status(entry.entry_id, STATUS_REWORK, report=make_rework_report(result))
            st.success("Запись помечена: отправлен на доработку (тест не сформирован).")
        except MoodleError as exc:
            st.error(f"Не удалось обновить запись в базе данных: {exc}")


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
        _rework_button(entry, registry, result)
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
    blocked = quiz_blocked_reason(result)  # вопросов меньше нормы: ни в банк, ни в тест не отправляем
    if blocked:
        st.warning(blocked.replace("Тест в курсе не создаётся", "В курс ничего не отправляется"))
    c_reg, c_course = st.columns(2)
    with c_reg:
        if entry is not None and registry is not None:
            if st.button("Добавить обработанный файл в базу данных", disabled=not confirmed,
                         key="moodle_save_registry",
                         help="В запись реестра попадут «Проверенный файл» (Aiken), «Файл (Gift) для заливки» и отчёт. "
                              "Если вопросов меньше нормы, статус станет «Отправлен на доработку (тест не сформирован)», "
                              "иначе не меняется: он меняется после загрузки в банк вопросов или создания теста."):
                try:
                    short = result is not None and getattr(result, "shortfall", 0) > 0
                    registry.save_result(
                        entry.entry_id,
                        xml_name=f"{file_stem}_moodle.xml", xml_text=xml_text,
                        aiken_name=f"{file_stem}_aiken.txt", aiken_text=questions_to_aiken(questions),
                        gift_name=f"{file_stem}_gift.txt", gift_text=questions_to_gift(questions),
                        # Не хватает вопросов до нормы: запись уходит на доработку, тест не формируется
                        status=STATUS_REWORK if short else None,
                        report=make_rework_report(result) if short else report,
                    )
                    st.success("Обработанные файлы добавлены в базу данных."
                               + (" Вопросов меньше нормы: статус записи «Отправлен на доработку (тест не сформирован)»."
                                  if short else ""))
                except MoodleError as exc:
                    st.error(f"Не удалось добавить файл в базу данных: {exc}")
    with c_course:
        if st.button("Загрузить вопросы в банк вопросов курса", type="primary", disabled=not confirmed or bool(blocked),
                     key="moodle_upload", help="Вопросы попадут в банк вопросов курса, в указанную папку."):
            try:
                message = client.import_xml(course_id, xml_text, filename=f"{file_stem}_moodle.xml")
                log.add(fp, course_id, category, len(questions))
                st.success(f"Вопросы загружены в курс № {course_id}. {message}")
                if entry is not None and registry is not None:
                    try:
                        registry.set_status(entry.entry_id, STATUS_BANK)
                    except MoodleError as exc:
                        st.warning(f"Вопросы в курсе, но статус в базе данных не обновился: {exc}")
            except MoodleError as exc:
                st.error(f"Не удалось загрузить в курс: {exc}")

    st.markdown("<div class='imes-panel-sub'>Или создайте готовый тест: вопросы попадут и в банк, и в новый тест "
                f"в разделе «{html.escape(QUIZ_SECTION_NAME)}».</div>", unsafe_allow_html=True)
    info = _course_info(client, course_id)
    settings = _quiz_settings_form(info["discipline"], course_id, info.get("custom_fields"),
                                   _grade_categories(client, course_id),
                                   getattr(client, "grade_categories_error", None))
    if st.button("Создать тест в курсе", disabled=not confirmed or bool(blocked), key="moodle_create_quiz",
                 help="Тест создаётся скрытым. Не нажимайте вместе с загрузкой в банк: вопросы задвоятся."):
        _create_quiz(client, course_id, category, questions, settings, log, fp, entry, registry,
                     result, usage, file_stem)

    _rework_button(entry, registry, result)
