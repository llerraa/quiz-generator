from src.exporters.aiken_exporter import questions_to_aiken
from src.models import (
    MultipleChoiceQuestion,
    TrueFalseQuestion,
)
from src.parsing.aiken_parser import looks_like_aiken, parse_aiken

SAMPLE = """Какой язык называют интерпретируемым?
A. Assembler
B. Python
C. Машинный код
ANSWER: B

Столица России?
A) Москва
B) Казань
ANSWER: A
"""


def test_parses_basic_file():
    result = parse_aiken(SAMPLE)
    assert result.errors == []
    assert len(result.questions) == 2
    q1, q2 = result.questions
    assert isinstance(q1, MultipleChoiceQuestion)
    assert q1.question == "Какой язык называют интерпретируемым?"
    assert q1.options == ["Assembler", "Python", "Машинный код"]
    assert q1.correct_index == 1
    assert q2.options == ["Москва", "Казань"]  # скобка `A)` тоже принимается
    assert q2.correct_index == 0


def test_answer_is_case_insensitive_and_allows_no_space():
    text = "Вопрос?\nA. один\nB. два\nanswer:b\n"
    result = parse_aiken(text)
    assert result.errors == []
    assert result.questions[0].correct_index == 1


def test_windows_line_endings_and_bom():
    text = "﻿" + SAMPLE.replace("\n", "\r\n")
    result = parse_aiken(text)
    assert result.errors == []
    assert len(result.questions) == 2


def test_extra_blank_lines_are_fine():
    text = "\n\n" + SAMPLE.replace("\n\n", "\n\n\n\n") + "\n\n"
    result = parse_aiken(text)
    assert result.errors == []
    assert len(result.questions) == 2


def test_multiline_question_and_option():
    text = (
        "Длинный вопрос,\n"
        "который перенесён на вторую строку?\n"
        "A. Короткий\n"
        "B. Длинный вариант,\n"
        "продолжение на следующей строке\n"
        "ANSWER: B\n"
    )
    result = parse_aiken(text)
    assert result.errors == []
    q = result.questions[0]
    assert q.question == "Длинный вопрос, который перенесён на вторую строку?"
    assert q.options[1] == "Длинный вариант, продолжение на следующей строке"


def test_true_false_recognized_in_any_order():
    text = (
        "Земля круглая.\nA. Верно\nB. Неверно\nANSWER: A\n\n"
        "Земля плоская.\nA. Неверно\nB. Верно\nANSWER: A\n\n"
        "Python is typed.\nA. True\nB. False\nANSWER: A\n"
    )
    result = parse_aiken(text)
    assert result.errors == []
    q1, q2, q3 = result.questions
    assert all(isinstance(q, TrueFalseQuestion) for q in result.questions)
    assert q1.is_true is True
    assert q2.is_true is False  # выбран вариант «Неверно»
    assert q3.is_true is True


def test_answer_points_to_missing_option():
    result = parse_aiken("Вопрос?\nA. один\nB. два\nANSWER: D\n")
    assert result.questions == []
    assert len(result.errors) == 1
    assert "несуществующий вариант" in result.errors[0]


def test_multiple_answers_are_reported():
    result = parse_aiken("Вопрос?\nA. один\nB. два\nC. три\nANSWER: A, C\n")
    assert result.questions == []
    assert "одна буква" in result.errors[0]


def test_missing_answer_line_does_not_break_next_question():
    text = (
        "Первый без ответа?\nA. один\nB. два\n\n"
        "Второй нормальный?\nA. да\nB. нет\nANSWER: A\n"
    )
    result = parse_aiken(text)
    assert len(result.questions) == 1
    assert result.questions[0].question == "Второй нормальный?"
    assert len(result.errors) == 1
    assert "нет строки" in result.errors[0]
    assert "Первый без ответа" in result.errors[0]


def test_missing_answer_at_end_of_file():
    result = parse_aiken("Вопрос?\nA. один\nB. два\n")
    assert result.questions == []
    assert "нет строки" in result.errors[0]


def test_single_option_and_no_question_text_are_errors():
    r1 = parse_aiken("Вопрос?\nA. один\nANSWER: A\n")
    assert r1.questions == [] and "меньше двух" in r1.errors[0]
    r2 = parse_aiken("A. один\nB. два\nANSWER: A\n")
    assert r2.questions == [] and "нет текста вопроса" in r2.errors[0]


def test_one_bad_question_does_not_lose_the_good_ones():
    text = (
        "Хороший 1?\nA. а\nB. б\nANSWER: A\n\n"
        "Плохой?\nA. а\nB. б\nANSWER: Z\n\n"
        "Хороший 2?\nA. а\nB. б\nANSWER: B\n"
    )
    result = parse_aiken(text)
    assert [q.question for q in result.questions] == ["Хороший 1?", "Хороший 2?"]
    assert len(result.errors) == 1
    assert "Вопрос 2" in result.errors[0]


def test_empty_text():
    result = parse_aiken("")
    assert result.questions == [] and result.errors == []


def test_question_text_starting_with_letter_and_dot_in_middle_is_not_an_option():
    # «B. ...» без предшествующего «A.» — не вариант, а часть текста вопроса
    text = "Вопрос с продолжением\nB. это не вариант\nA. первый\nB. второй\nANSWER: B\n"
    result = parse_aiken(text)
    assert result.errors == []
    assert "B. это не вариант" in result.questions[0].question
    assert result.questions[0].options == ["первый", "второй"]


# --- looks_like_aiken ---

def test_looks_like_aiken_true():
    assert looks_like_aiken(SAMPLE)


def test_looks_like_aiken_false_for_plain_text():
    assert not looks_like_aiken("Просто текст лекции.\nНикаких вопросов здесь нет.")
    assert not looks_like_aiken("1. Вопрос\nа) вариант\nб) вариант\nОтвет: а")
    assert not looks_like_aiken("")


def test_looks_like_aiken_needs_both_options_and_answer():
    assert not looks_like_aiken("Вопрос?\nANSWER: A")
    assert not looks_like_aiken("Вопрос?\nA. один\nB. два")


# --- Круговая проверка: наш экспорт читается нашим же парсером ---

def test_round_trip_export_then_parse():
    original = [
        MultipleChoiceQuestion(
            question="Что такое переменная?",
            options=["Имя для данных", "Тип цикла", "Файл", "Библиотека"],
            correct_index=0,
        ),
        MultipleChoiceQuestion(
            question="Вопрос: с двоеточием, цифрами 1.5 и скобками (так)?",
            options=["один", "два"],
            correct_index=1,
        ),
        TrueFalseQuestion(statement="Python — язык программирования.", is_true=True),
        TrueFalseQuestion(statement="Python — это змея, и только.", is_true=False),
    ]
    text = questions_to_aiken(original)
    assert looks_like_aiken(text)

    result = parse_aiken(text)
    assert result.errors == []
    assert result.questions == original
