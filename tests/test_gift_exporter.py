"""GIFT-файл должен совпадать с правилами промпта ИМЭС «Aiken → GIFT»."""
from src.exporters.gift_exporter import questions_to_gift
from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.exporters.multichoice_weights import choice_weights, format_weight
from src.models import MultipleChoiceQuestion, TrueFalseQuestion
from src.parsing.aiken_parser import parse_aiken

AIKEN = """Какой вариант является правильным в вопросе 2?
A. Правильный вариант
B. Неверный вариант 1
C. Неверный вариант 2
D. Неверный вариант 3
ANSWER: A

Какие варианты являются правильным в вопросе 1?
A. Неверный вариант 1
B. Правильный вариант 1
C. Неверный вариант 2
D. Правильный вариант 2
ANSWER: B,D
"""

EXPECTED = """::Какой вариант является правильным в вопросе 2?:: Какой вариант является правильным в вопросе 2?
{
=A. Правильный вариант
~B. Неверный вариант 1
~C. Неверный вариант 2
~D. Неверный вариант 3
}

::Какие варианты являются правильным в вопросе 1?:: Какие варианты являются правильным в вопросе 1?
{
~%-50%A. Неверный вариант 1
~%50%B. Правильный вариант 1
~%-50%C. Неверный вариант 2
~%50%D. Правильный вариант 2
}
"""


def test_gift_matches_institute_prompt_example():
    assert questions_to_gift(parse_aiken(AIKEN).questions) == EXPECTED


def test_multi_question_has_no_equals_sign_and_weights_sum_to_zero():
    q = MultipleChoiceQuestion(question="Q?", options=list("абвг"), correct_index=0, also_correct=[2])
    weights = choice_weights(4, q.correct_indices)
    assert weights == [50, -50, 50, -50] and sum(weights) == 0
    gift = questions_to_gift([q])
    assert "=" not in gift.replace("::Q?:: Q?", "")


def test_special_characters_are_escaped():
    q = MultipleChoiceQuestion(question="a=b {x} #1: ~", options=["да~", "нет"], correct_index=0)
    gift = questions_to_gift([q])
    assert r"a\=b \{x\} \#1\: \~" in gift
    assert r"=A. да\~" in gift


def test_long_text_goes_on_one_line_and_name_is_short():
    q = MultipleChoiceQuestion(question="слово " * 40, options=["один", "два"], correct_index=1)
    first = questions_to_gift([q]).splitlines()[0]
    assert first.startswith("::") and first.count("::") == 2
    assert len(first.split("::")[1]) <= 61


def test_true_false_is_written_as_two_options():
    gift = questions_to_gift([TrueFalseQuestion(statement="Земля круглая", is_true=True)])
    assert "=A. Верно" in gift and "~B. Неверно" in gift


def test_no_bom_and_blank_line_between_questions():
    gift = questions_to_gift(parse_aiken(AIKEN).questions)
    assert not gift.startswith("﻿") and "}\n\n::" in gift


def test_empty_list_gives_empty_text():
    assert questions_to_gift([]) == ""


def test_odd_option_counts_still_sum_to_zero():
    weights = choice_weights(5, [0, 1])
    assert abs(sum(weights)) < 1e-9 and weights[0] == 50
    assert format_weight(-33.333333) == "-33.33333" and format_weight(50.0) == "50"


def test_moodle_xml_uses_checkboxes_for_two_correct():
    q = MultipleChoiceQuestion(question="Q?", options=list("абвг"), correct_index=1, also_correct=[3])
    xml = questions_to_moodle_xml([q])
    assert "<single>false</single>" in xml
    assert xml.count('fraction="50"') == 2 and xml.count('fraction="-50"') == 2


def test_moodle_xml_single_answer_unchanged():
    q = MultipleChoiceQuestion(question="Q?", options=list("абв"), correct_index=1)
    xml = questions_to_moodle_xml([q])
    assert "<single>true</single>" in xml
    assert xml.count('fraction="100"') == 1 and xml.count('fraction="0"') == 2
