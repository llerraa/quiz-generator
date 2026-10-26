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
