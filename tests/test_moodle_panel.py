"""Интерфейс реестра и отправки в Moodle на подменённом Moodle (сеть не нужна)."""
from streamlit.testing.v1 import AppTest

ROOT = str(__import__("pathlib").Path(__file__).resolve().parent.parent)


def _registry_script():
    import os, sys
    sys.path.insert(0, ROOT_PLACEHOLDER)
    import streamlit as st
    from src.config import Config
    from src.moodle import registry as R
    from src.moodle import panel as P
    from src.moodle.client import MoodleClient

    Config.MOODLE_URL, Config.MOODLE_TOKEN = "https://m.example", "T"
    os.environ["MOODLE_REGISTRY_COURSE"] = "17"
    AIKEN = "Что такое переменная?\nA. Имя для значения\nB. Цикл\nANSWER: A\n".encode()

    def mk(i, name, cid, status):
        return R.RegistryEntry(
            i,
            {R.F_COURSE_NAME: name, R.F_COURSE_LINK: f"https://m/course/view.php?id={cid}", R.F_STATUS: status},
            {R.F_SOURCE: [R.RegistryFile("a.txt", "https://m/f")]},
        )

    R.MoodleRegistry.entries = lambda self: [mk(1, "Курс А", 16, "Не обработан"), mk(2, "Курс Б", 18, "Обработан")]
    R.MoodleRegistry.download = lambda self, f: AIKEN
    P.MoodleClient = lambda: MoodleClient("https://m.example", "T")

    picked = P.pick_registry_entry()
    st.session_state["picked_ok"] = picked is not None
    if picked:
        st.write(f"course={picked[1].course_id} name={picked[2]} size={len(picked[3])}")


def _run(show_all: bool = False, file_filter: str | None = None) -> AppTest:
    """Скрипт подменяет классы Moodle глобально, поэтому после запуска всё возвращаем как было."""
    import inspect, os, textwrap

    from src.config import Config
    from src.moodle import panel as P
    from src.moodle import registry as R

    saved = (R.MoodleRegistry.entries, R.MoodleRegistry.download, P.MoodleClient,
             Config.MOODLE_URL, Config.MOODLE_TOKEN, os.environ.get("MOODLE_REGISTRY_COURSE"))
    src = textwrap.dedent(inspect.getsource(_registry_script)).replace("ROOT_PLACEHOLDER", repr(ROOT))
    try:
        at = AppTest.from_string(src + "\n_registry_script()\n", default_timeout=30)
        at.run()
        if show_all:
            at.multiselect(key="registry_statuses").set_value(["Не обработан", "(без статуса)", "Обработан"]).run()
        if file_filter:
            at.selectbox(key="registry_file_filter").select(file_filter).run()
        return at
    finally:
        (R.MoodleRegistry.entries, R.MoodleRegistry.download, P.MoodleClient,
         Config.MOODLE_URL, Config.MOODLE_TOKEN, env) = saved
        if env is None:
            os.environ.pop("MOODLE_REGISTRY_COURSE", None)
        else:
            os.environ["MOODLE_REGISTRY_COURSE"] = env


def test_registry_lists_only_unprocessed_by_default():
    at = _run()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert list(table["Курс"]) == ["Курс А"] and list(table["Статус"]) == ["Не обработан"]
    assert table["Ссылка на курс"].iloc[0] == "https://m/course/view.php?id=16"
    options = [s for s in at.selectbox if "Запись реестра" in s.label][0].options
    assert len(options) == 1 and "Курс А" in options[0] and "курс № 16" in options[0]
    assert at.session_state["picked_ok"] is True
    assert any("course=16" in m.value for m in at.markdown)
    assert any("Показано записей: 1 из 2" in c.value for c in at.caption)


def test_registry_can_show_processed_too():
    at = _run(show_all=True)
    assert not at.exception, at.exception
    assert len(at.dataframe[0].value) == 2
    entry_select = [s for s in at.selectbox if "Запись реестра" in s.label][0]
    assert len(entry_select.options) == 2


def test_registry_filter_by_file_hides_entries_without_file():
    at = _run(show_all=True, file_filter="Без файла")
    assert not at.exception, at.exception
    assert any("записей нет" in i.value for i in at.info)


# --- кнопка «Создать тест в курсе» ---------------------------------------------------------

def _quiz_script():
    import os, sys, tempfile
    sys.path.insert(0, ROOT_PLACEHOLDER)
    import streamlit as st
    from src.config import Config
    from src.models import MultipleChoiceQuestion
    from src.moodle import panel as P
    from src.moodle.publish import UploadLog

    Config.MOODLE_URL, Config.MOODLE_TOKEN = "https://m.example", "T"
    calls = st.session_state.setdefault("calls", [])

    class FakeClient:
        def course_name(self, cid):
            return "Анатомия"

        def course_info(self, cid):
            return {"name": "Анатомия", "discipline": st.session_state.get("discipline", "Анатомия и физиология ЦНС")}

        def grade_categories(self, cid):
            return st.session_state.get(
                "gradecats",
                ["Не определено", "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ (максимум можно набрать 50 баллов)",
                 "ТЕКУЩИЙ КОНТРОЛЬ (максимум можно набрать 50 баллов)"])

        def plugin_available(self):
            return st.session_state.get("plugin", True)

        def section_number(self, cid):
            return st.session_state.get("section", 3)

        def create_quiz(self, cid, xml, settings, filename="quiz.xml"):
            if st.session_state.get("taken"):
                from src.moodle.client import MoodleError
                raise MoodleError('Moodle вернул ошибку: The ID number "ПА" is already used in this course. '
                                  '(cmidnumber_taken)')
            calls.append((cid, settings, xml))
            return {"cmid": 42, "questions": 2, "url": "https://m.example/mod/quiz/view.php?id=42"}

    P.MoodleClient = lambda: FakeClient()
    log_path = os.path.join(tempfile.mkdtemp(), "log.json")
    P.UploadLog = lambda: UploadLog(log_path)
    qs = [MultipleChoiceQuestion(question=f"Вопрос {i}?", options=["а", "б"], correct_index=0) for i in range(2)]
    result = None
    if st.session_state.get("target"):
        from src.course_pipeline import CourseTestResult
        result = CourseTestResult(questions=qs, target=st.session_state["target"])
    P.render_moodle_panel(qs, "f", result, None, course_id=st.session_state.get("reg_course", 16))


def _run_quiz(course_override=None, **state):
    import inspect, textwrap

    from src.config import Config
    from src.moodle import panel as P

    saved = (P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN)
    src = textwrap.dedent(inspect.getsource(_quiz_script)).replace("ROOT_PLACEHOLDER", repr(ROOT))
    try:
        at = AppTest.from_string(src + "\n_quiz_script()\n", default_timeout=30)
        for key, value in state.items():
            at.session_state[key] = value
        at.run()
        if course_override is not None:
            at.text_input(key="moodle_course_id").set_value(course_override).run()
        at.checkbox(key="moodle_confirm").check().run()
        at.button(key="moodle_create_quiz").click().run()
        return at
    finally:
        P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN = saved


def test_create_quiz_button_creates_hidden_quiz_in_found_section():
    at = _run_quiz()
    assert not at.exception, at.exception
    cid, settings, xml = at.session_state["calls"][0]
    assert cid == 16 and settings.section == 3 and settings.visible is False
    assert settings.name == "Тест. Промежуточная аттестация по дисциплине Анатомия и физиология ЦНС"
    assert "<defaultgrade>2</defaultgrade>" in xml
    assert any("Тест создан" in s.value and "4 балл" in s.value for s in at.success)


def test_create_quiz_reports_missing_section_and_creates_nothing():
    at = _run_quiz(section=None)
    assert not at.exception, at.exception
    assert not at.session_state["calls"]
    assert any("нет раздела" in e.value for e in at.error)


def test_create_quiz_reports_missing_plugin():
    at = _run_quiz(plugin=False)
    assert not at.session_state["calls"]
    assert any("плагин" in e.value for e in at.error)


def test_course_number_from_registry_can_be_overridden():
    # в записи реестра курс № 421, которого на тестовой ЭИОС нет: отправляем в курс № 16
    at = _run_quiz(course_override="16", reg_course=421)
    assert not at.exception, at.exception
    assert at.session_state["calls"][0][0] == 16
    assert any("421" in c.value and "16" in c.value for c in at.caption)


def test_course_number_from_registry_is_used_by_default():
    at = _run_quiz(reg_course=421)
    assert at.session_state["calls"][0][0] == 421
    assert at.text_input(key="moodle_course_id").value == "421"


def test_quiz_name_without_discipline_field_has_no_tail_and_warns():
    at = _run_quiz(discipline=None)
    assert at.session_state["calls"][0][1].name == "Тест. Промежуточная аттестация"
    assert any("Поля из 1С" in c.value for c in at.caption)


# --- статус «Отправлен на доработку» при нехватке вопросов -----------------------------------

def _save_script(questions_count, target):
    import sys
    sys.path.insert(0, ROOT_PLACEHOLDER)
    import streamlit as st
    from src.config import Config
    from src.course_pipeline import CourseTestResult
    from src.models import MultipleChoiceQuestion
    from src.moodle import panel as P
    from src.moodle import registry as R
    from src.moodle.publish import UploadLog
    import os, tempfile

    Config.MOODLE_URL, Config.MOODLE_TOKEN = "https://m.example", "T"
    saved = st.session_state.setdefault("saved", [])

    class FakeClient:
        def course_name(self, cid):
            return "Анатомия"

        def course_info(self, cid):
            return {"name": "Анатомия", "discipline": "Анатомия", "custom_fields": []}

        def grade_categories(self, cid):
            return []

    class FakeRegistry:
        def save_result(self, entry_id, **kwargs):
            saved.append((entry_id, kwargs))

    P.MoodleClient = lambda: FakeClient()
    P.UploadLog = lambda: UploadLog(os.path.join(tempfile.mkdtemp(), "log.json"))
    qs = [MultipleChoiceQuestion(question=f"Вопрос {i}?", options=["а", "б"], correct_index=0)
          for i in range(questions_count)]
    result = CourseTestResult(questions=qs, target=target)
    entry = R.RegistryEntry(5, {R.F_COURSE_NAME: "Курс"}, {})
    P.render_moodle_panel(qs, "f", result, None, course_id=16, entry=entry, registry=FakeRegistry())


def _run_save(questions_count, target=25):
    import inspect, textwrap

    from src.config import Config
    from src.moodle import panel as P

    saved = (P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN)
    src = textwrap.dedent(inspect.getsource(_save_script)).replace("ROOT_PLACEHOLDER", repr(ROOT))
    try:
        at = AppTest.from_string(src + f"\n_save_script({questions_count}, {target})\n", default_timeout=30)
        at.run()
        at.checkbox(key="moodle_confirm").check().run()
        at.button(key="moodle_save_registry").click().run()
        return at
    finally:
        P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN = saved


def test_saving_short_test_to_registry_sets_rework_status():
    from src.moodle.registry import STATUS_REWORK

    at = _run_save(20)
    assert not at.exception, at.exception
    _, kwargs = at.session_state["saved"][0]
    assert kwargs["status"] == STATUS_REWORK
    assert "Не хватает вопросов: 5." in kwargs["report"]
    assert "Тест не сформирован" in kwargs["report"]
    assert any("доработку" in s.value for s in at.success)


def test_saving_full_test_to_registry_keeps_status():
    at = _run_save(25)
    assert not at.exception, at.exception
    _, kwargs = at.session_state["saved"][0]
    assert kwargs["status"] is None
    assert "Вошло вопросов: 25 из 25." in kwargs["report"]


# --- категория журнала оценок ----------------------------------------------------------------

def test_quiz_goes_to_final_attestation_grade_category_by_default():
    at = _run_quiz()
    assert not at.exception, at.exception
    settings = at.session_state["calls"][0][1]
    assert settings.grade_category == "ПРОМЕЖУТОЧНАЯ АТТЕСТАЦИЯ (максимум можно набрать 50 баллов)"
    assert settings.to_config(16)["gradecat"] == settings.grade_category


def test_quiz_without_attestation_category_warns_and_uses_first_category():
    at = _run_quiz(gradecats=["Не определено", "ТЕКУЩИЙ КОНТРОЛЬ (максимум можно набрать 50 баллов)"])
    assert at.session_state["calls"][0][1].grade_category == "Не определено"
    assert any("нет категории" in c.value for c in at.caption)


def test_quiz_grade_category_can_be_typed_when_list_is_unavailable():
    at = _run_quiz(gradecats=None)
    assert any("Не удалось получить список категорий" in c.value for c in at.caption)
    assert at.session_state["calls"][0][1].grade_category is None  # поле пустое: тест создаётся без категории


def test_quiz_gets_idnumber_from_defaults_and_formula_is_not_touched():
    at = _run_quiz()
    settings = at.session_state["calls"][0][1]
    assert settings.idnumber == "ПА-тест"
    config = settings.to_config(16)
    assert config["cmidnumber"] == "ПА-тест" and "appendtogradecalc" not in config


def test_create_quiz_button_is_blocked_when_questions_are_fewer_than_target():
    import inspect, textwrap

    from src.config import Config
    from src.moodle import panel as P

    saved = (P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN)
    src = textwrap.dedent(inspect.getsource(_quiz_script)).replace("ROOT_PLACEHOLDER", repr(ROOT))
    try:
        at = AppTest.from_string(src + "\n_quiz_script()\n", default_timeout=30)
        at.session_state["target"] = 25  # в тестовом файле только 2 вопроса
        at.run()
        at.checkbox(key="moodle_confirm").check().run()
        assert not at.exception, at.exception
        assert at.button(key="moodle_create_quiz").disabled
        assert at.button(key="moodle_upload").disabled  # и загрузка в банк вопросов тоже
        assert any("не хватает 23" in w.value and "ничего не отправляется" in w.value for w in at.warning)
        assert not at.session_state["calls"]
    finally:
        P.MoodleClient, P.UploadLog, Config.MOODLE_URL, Config.MOODLE_TOKEN = saved


def test_create_quiz_button_is_enabled_when_target_is_reached():
    at = _run_quiz(target=2)  # 2 вопроса из 2
    assert not at.exception, at.exception
    assert at.session_state["calls"]
    assert not at.button(key="moodle_upload").disabled


def test_taken_idnumber_error_gets_explanation_and_creates_nothing():
    at = _run_quiz(taken=True)
    assert not at.exception, at.exception
    assert not at.session_state["calls"]
    assert any("cmidnumber_taken" in e.value for e in at.error)
    assert any("cron" in i.value and "Значения ID" in i.value for i in at.info)
