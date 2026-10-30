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


def _run(show_all: bool = False) -> AppTest:
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
        if show_all:
            at.session_state["registry_show_all"] = True
        return at.run()
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
    options = at.selectbox[0].options
    assert len(options) == 1 and "Курс А" in options[0] and "курс № 16" in options[0]
    assert at.session_state["picked_ok"] is True
    assert any("course=16" in m.value for m in at.markdown)


def test_registry_can_show_processed_too():
    at = _run(show_all=True)
    assert not at.exception, at.exception
    assert len(at.selectbox[0].options) == 2


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

        def plugin_available(self):
            return st.session_state.get("plugin", True)

        def section_number(self, cid):
            return st.session_state.get("section", 3)

        def create_quiz(self, cid, xml, settings, filename="quiz.xml"):
            calls.append((cid, settings, xml))
            return {"cmid": 42, "questions": 2, "url": "https://m.example/mod/quiz/view.php?id=42"}

    P.MoodleClient = lambda: FakeClient()
    log_path = os.path.join(tempfile.mkdtemp(), "log.json")
    P.UploadLog = lambda: UploadLog(log_path)
    qs = [MultipleChoiceQuestion(question=f"Вопрос {i}?", options=["а", "б"], correct_index=0) for i in range(2)]
    P.render_moodle_panel(qs, "f", None, None, course_id=st.session_state.get("reg_course", 16))


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
    assert settings.name == "Промежуточная аттестация: Анатомия"
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
