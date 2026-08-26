"""Тесты для src/exporters/qti_exporter.py."""
import xml.etree.ElementTree as ET

from src.exporters.qti_exporter import questions_to_qti_xml
from src.models import EssayQuestion, MatchingPair, MatchingQuestion, MultipleChoiceQuestion, ShortAnswerQuestion, TrueFalseQuestion


def test_qti_xml_is_well_formed():
    questions = [
        MultipleChoiceQuestion(question="Q1?", options=["A", "B"], correct_index=0),
    ]
    xml_str = questions_to_qti_xml(questions)
    # Если XML некорректен, fromstring выбросит ParseError — тест сам себя проверит
    root = ET.fromstring(xml_str)
    assert root.tag == "questestinterop"


def test_qti_xml_keeps_cyrillic_readable():
    questions = [MultipleChoiceQuestion(question="Что такое ReLU?", options=["Ответ А", "Ответ Б"], correct_index=0)]
    xml_str = questions_to_qti_xml(questions)
    assert "Что такое ReLU?" in xml_str
    assert "Ответ А" in xml_str


def test_qti_xml_contains_one_item_per_question():
    questions = [
        MultipleChoiceQuestion(question="Q1?", options=["A", "B"], correct_index=0),
        TrueFalseQuestion(statement="Q2", is_true=True),
        MatchingQuestion(instruction="Q3", pairs=[MatchingPair(left="X", right="Y"), MatchingPair(left="Z", right="W")]),
    ]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    items = root.findall(".//item")
    assert len(items) == 3


def test_qti_mc_marks_correct_option():
    questions = [MultipleChoiceQuestion(question="Q?", options=["Неверный", "Верный"], correct_index=1)]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    varequal = root.find(".//varequal")
    assert varequal.text == "opt_1"  # индекс 1 — второй (верный) вариант


def test_qti_true_false_maps_to_two_option_mc():
    questions = [TrueFalseQuestion(statement="Утверждение", is_true=False)]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    labels = [m.text for m in root.findall(".//response_label/material/mattext")]
    assert labels == ["Верно", "Неверно"]
    varequal = root.find(".//varequal")
    assert varequal.text == "opt_1"  # is_true=False -> "Неверно" второй вариант


def test_qti_matching_creates_one_response_per_pair():
    questions = [
        MatchingQuestion(
            instruction="Сопоставьте",
            pairs=[MatchingPair(left="A", right="1"), MatchingPair(left="B", right="2"), MatchingPair(left="C", right="3")],
        )
    ]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    response_lids = root.findall(".//response_lid")
    assert len(response_lids) == 3


def test_qti_empty_list_still_produces_valid_xml():
    xml_str = questions_to_qti_xml([])
    root = ET.fromstring(xml_str)
    assert root.findall(".//item") == []


def test_qti_essay_has_no_auto_scoring():
    # У эссе нет единственного правильного ответа — resprocessing (авто-баллы)
    # быть не должно, оценивает преподаватель вручную.
    questions = [EssayQuestion(question="Опишите принцип работы нейросети", grading_criteria="Слои, веса")]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    item = root.find(".//item")
    assert item.find(".//resprocessing") is None


def test_qti_essay_includes_grading_criteria_as_solution():
    questions = [EssayQuestion(question="Q?", grading_criteria="Критерий А, критерий Б")]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    solution_text = root.find(".//solutionmaterial/material/mattext")
    assert solution_text.text == "Критерий А, критерий Б"


def test_qti_short_answer_checks_against_sample_answer():
    questions = [ShortAnswerQuestion(question="Функция f(x)=max(0,x)?", sample_answer="ReLU")]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    varequal = root.find(".//varequal")
    assert varequal.text == "ReLU"
    assert varequal.get("case") == "No"  # без учёта регистра


def test_qti_short_answer_uses_free_text_response_not_choices():
    questions = [ShortAnswerQuestion(question="Q?", sample_answer="A")]
    xml_str = questions_to_qti_xml(questions)
    root = ET.fromstring(xml_str)
    item = root.find(".//item")
    assert item.find(".//response_str") is not None
    assert item.find(".//response_lid") is None  # это не вопрос с вариантами