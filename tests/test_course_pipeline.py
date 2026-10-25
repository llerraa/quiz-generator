"""Тесты конвейера «Тест для курса». Настоящая модель не вызывается — вместо неё подставная функция."""
import pytest

from src.course_pipeline import (
    CHUNK_CHARS,
    TARGET_QUESTIONS,
    prepare_course_test,
    split_text,
)
from src.llm.bothub_client import (
    _CourseExtraction,
    _ExtractedCourseMCQ,
    _ExtractedUnsupported,
)
from src.models import MultipleChoiceQuestion, TrueFalseQuestion


def mcq(question="Вопрос?", options=("а", "б", "в"), answers=(1,), evidence="Ответ: Б"):
    return _ExtractedCourseMCQ(
        question=question,
        options=list(options),
        marked_answers=list(answers),
        answer_evidence=evidence,
    )


def fake(*items, unsupported=()):
    """Подставная функция извлечения: всегда возвращает одни и те же элементы."""
    def _extract(chunk):
        return _CourseExtraction(questions=list(items), unsupported=list(unsupported))
    return _extract


# ---------- файл Aiken: читаем кодом, модель не нужна ----------

AIKEN = """Что такое переменная?
A. Имя для данных
B. Тип цикла
ANSWER: A

Столица России?
A. Москва
B. Казань
ANSWER: A
"""


def test_aiken_file_is_read_without_model():
    result = prepare_course_test(AIKEN, extract_fn=None)
    assert result.source == "aiken"
    assert len(result.questions) == 2
    assert result.questions[0].correct_index == 0
    assert result.skipped == [] and result.errors == []
    assert result.shortfall == 23


def test_aiken_over_limit_is_cut_and_counted():
    blocks = "\n\n".join(f"Вопрос {i}?\nA. да\nB. нет\nANSWER: A" for i in range(30))
    result = prepare_course_test(blocks, extract_fn=None)
    assert len(result.questions) == TARGET_QUESTIONS
    assert result.extra_valid == 5
    assert result.shortfall == 0
    # берутся ПЕРВЫЕ 25 по порядку
    assert result.questions[0].question == "Вопрос 0?"
    assert result.questions[-1].question == "Вопрос 24?"


def test_aiken_broken_question_is_reported_not_lost():
    text = AIKEN + "\nСломанный?\nA. раз\nB. два\nANSWER: Z\n"
    result = prepare_course_test(text, extract_fn=None)
    assert len(result.questions) == 2
    assert len(result.skipped) == 1
    assert "несуществующий вариант" in result.skipped[0].reason


def test_aiken_true_false_stays_valid():
    text = "Земля круглая.\nA. Верно\nB. Неверно\nANSWER: A\n"
    result = prepare_course_test(text, extract_fn=None)
    assert isinstance(result.questions[0], TrueFalseQuestion)


# ---------- через модель: отбор по правилам Aiken ----------

def test_valid_question_is_accepted_with_evidence():
    result = prepare_course_test("любой текст", fake(mcq(answers=(2,), evidence="**в)**")))
    assert result.source == "llm"
    q = result.questions[0]
    assert isinstance(q, MultipleChoiceQuestion)
    assert q.correct_index == 2
    assert result.evidence == ["**в)**"]


@pytest.mark.parametrize(
    "item, expected_reason",
    [
        (mcq(answers=(), evidence=""), "не найдена пометка"),
        (mcq(answers=(0, 2)), "несколько верных"),
        (mcq(answers=(5,)), "несуществующий вариант"),
        (mcq(answers=(1,), evidence="  "), "не удалось подтвердить"),
        (mcq(options=("только один",), answers=(0,)), "меньше двух"),
        (mcq(options=tuple("абвгдеж"), answers=(0,)), "больше 6"),
        (mcq(question="   ", answers=(0,)), "нет текста вопроса"),
    ],
)
def test_question_not_fitting_aiken_is_skipped_with_reason(item, expected_reason):
    result = prepare_course_test("текст", fake(item))
    assert result.questions == []
    assert len(result.skipped) == 1
    assert expected_reason in result.skipped[0].reason


def test_same_marked_answer_listed_twice_counts_as_one():
    result = prepare_course_test("текст", fake(mcq(answers=(1, 1))))
    assert len(result.questions) == 1


def test_good_and_bad_questions_mixed_nothing_lost_silently():
    items = [
        mcq("Хороший 1?"),
        mcq("Без ответа?", answers=(), evidence=""),
        mcq("Хороший 2?"),
        mcq("Два ответа?", answers=(0, 1)),
    ]
    result = prepare_course_test("текст", fake(*items))
    assert [q.question for q in result.questions] == ["Хороший 1?", "Хороший 2?"]
    assert len(result.skipped) == 2


def test_unsupported_questions_are_reported():
    result = prepare_course_test(
        "текст",
        fake(mcq(), unsupported=[_ExtractedUnsupported(text="Объясните, что такое ИИ", reason="открытый вопрос")]),
    )
    assert len(result.questions) == 1
    assert len(result.skipped) == 1
    assert "открытый вопрос" in result.skipped[0].reason
    assert "Объясните" in result.skipped[0].title


def test_duplicates_are_ignored():
    result = prepare_course_test("текст", fake(mcq("Один и тот же?"), mcq("один   и ТОТ же?")))
    assert len(result.questions) == 1


def test_fewer_than_target_reports_shortfall():
    result = prepare_course_test("текст", fake(*[mcq(f"В{i}?") for i in range(7)]))
    assert len(result.questions) == 7
    assert result.shortfall == 18


# ---------- длинные файлы: фрагменты, остановка, сбои ----------

def _long_text(lines=600):
    return "\n".join(f"строка номер {i} с некоторым содержимым для объёма" for i in range(lines))


def test_stops_after_target_and_does_not_process_rest():
    text = _long_text()
    assert len(split_text(text)) >= 3
    calls = []

    def extract(chunk):
        n = len(calls)
        calls.append(chunk)
        return _CourseExtraction(questions=[mcq(f"Фрагмент {n} вопрос {i}?") for i in range(20)])

    result = prepare_course_test(text, extract)
    assert len(result.questions) == 25
    assert result.extra_valid == 15
    assert result.stopped_early is True
    assert len(calls) == 2  # третий фрагмент уже не нужен


def test_failed_chunk_is_reported_and_others_survive():
    text = _long_text()
    state = {"n": 0}

    def extract(chunk):
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("Модель вернула невалидный JSON")
        return _CourseExtraction(questions=[mcq(f"Вопрос {state['n']}?")])

    result = prepare_course_test(text, extract)
    assert len(result.errors) == 1
    assert "Фрагмент 1" in result.errors[0]
    assert len(result.questions) >= 1


def test_progress_callback_is_called():
    text = _long_text()
    seen = []
    prepare_course_test(text, fake(mcq("Один?")), on_progress=lambda done, total: seen.append((done, total)))
    total = len(split_text(text))
    assert total >= 2
    assert seen == [(i, total) for i in range(1, total + 1)]


def test_empty_text_and_missing_extractor():
    with pytest.raises(ValueError):
        prepare_course_test("   \n ", extract_fn=fake())
    with pytest.raises(ValueError):
        prepare_course_test("обычный текст без Aiken", extract_fn=None)


# ---------- split_text ----------

def test_short_text_is_one_chunk():
    assert split_text("коротко") == ["коротко"]


def test_chunks_cover_all_lines_and_overlap():
    text = _long_text(400)
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS + 200 for c in chunks)
    joined = "\n".join(chunks)
    for i in range(400):
        assert f"строка номер {i} " in joined
    # перекрытие: последняя строка первого фрагмента есть и во втором
    assert chunks[0].splitlines()[-1] in chunks[1].splitlines()


def test_very_long_single_line_does_not_hang():
    chunks = split_text("а" * (CHUNK_CHARS * 3))
    assert "".join(chunks) == "а" * (CHUNK_CHARS * 3)
