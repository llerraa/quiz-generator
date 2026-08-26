"""Тесты для src/exporters/moodle_xml_exporter.py."""
import xml.etree.ElementTree as ET

from src.exporters.moodle_xml_exporter import questions_to_moodle_xml
from src.models import (
    EssayQuestion,
    MatchingPair,
    MatchingQuestion,
    MultipleChoiceQuestion,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)


def test_moodle_xml_is_well_formed():
    questions = [MultipleChoiceQuestion(question="Q1?", options=["A", "B"], correct_index=0)]
    xml_str = questions_to_moodle_xml(questions)
    root = ET.fromstring(xml_str)  # ParseError сам провалит тест, если что-то не так
    assert root.tag == "quiz"


def test_moodle_xml_keeps_cyrillic_readable():
    questions = [MultipleChoiceQuestion(question="Что такое ReLU?", options=["Ответ А", "Ответ Б"], correct_index=0)]
    xml_str = questions_to_moodle_xml(questions)
    assert "Что такое ReLU?" in xml_str
    assert "Ответ А" in xml_str


def test_moodle_xml_contains_one_question_element_per_question():
    questions = [
        MultipleChoiceQuestion(question="Q1?", options=["A", "B"], correct_index=0),
        TrueFalseQuestion(statement="Q2", is_true=True),
        MatchingQuestion(instruction="Q3", pairs=[MatchingPair(left="X", right="Y"), MatchingPair(left="Z", right="W")]),
        EssayQuestion(question="Q4", grading_criteria="Критерий"),
        ShortAnswerQuestion(question="Q5", sample_answer="Ответ"),
    ]
    xml_str = questions_to_moodle_xml(questions)
    root = ET.fromstring(xml_str)
    assert len(root.findall("question")) == 5


def test_moodle_xml_mc_marks_correct_answer_with_fraction_100():
    questions = [MultipleChoiceQuestion(question="Q?", options=["Неверный", "Верный"], correct_index=1)]
    root = ET.fromstring(questions_to_moodle_xml(questions))
    answers = root.find("question").findall("answer")
    assert answers[0].get("fraction") == "0"
    assert answers[1].get("fraction") == "100"


def test_moodle_xml_true_false_uses_true_false_text_values():
    questions = [TrueFalseQuestion(statement="Утверждение", is_true=False)]
    root = ET.fromstring(questions_to_moodle_xml(questions))
    answers = root.find("question").findall("answer")
    values = {a.find("text").text: a.get("fraction") for a in answers}
    assert values["true"] == "0"
    assert values["false"] == "100"


def test_moodle_xml_matching_uses_subquestion_tags():
    questions = [
        MatchingQuestion(
            instruction="Сопоставьте",
            pairs=[MatchingPair(left="A", right="1"), MatchingPair(left="B", right="2")],
        )
    ]
    root = ET.fromstring(questions_to_moodle_xml(questions))
    subquestions = root.find("question").findall("subquestion")
    assert len(subquestions) == 2
    assert subquestions[0].find("text").text == "A"
    assert subquestions[0].find("answer/text").text == "1"


def test_moodle_xml_essay_has_no_scored_answer():
    questions = [EssayQuestion(question="Опишите принцип работы нейросети", grading_criteria="Критерий А")]
    root = ET.fromstring(questions_to_moodle_xml(questions))
    question = root.find("question")
    answer = question.find("answer")
    assert answer.get("fraction") == "0"  # "нет ответа и нет оценки" — по документации Moodle
    feedback_text = question.find("generalfeedback/text").text
    assert "Критерий А" in feedback_text


def test_moodle_xml_short_answer_marks_sample_answer_correct():
    questions = [ShortAnswerQuestion(question="Функция f(x)=max(0,x)?", sample_answer="ReLU")]
    root = ET.fromstring(questions_to_moodle_xml(questions))
    answer = root.find("question/answer")
    assert answer.get("fraction") == "100"
    assert answer.find("text").text == "ReLU"


def test_moodle_xml_empty_list_still_produces_valid_xml():
    root = ET.fromstring(questions_to_moodle_xml([]))
    assert root.findall("question") == []