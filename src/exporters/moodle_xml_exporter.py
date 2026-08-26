"""
Экспорт сгенерированных вопросов в формат Moodle XML.

Это "родной" формат самой Moodle (Банк вопросов → Импорт → Moodle XML),
придуманный разработчиками Moodle специально для импорта вопросов в неё же —
в отличие от QTI, здесь нет риска несовместимости между разными
интерпретациями стандарта.

Понадобился этот отдельный экспортёр после того, как реальный Moodle не
опознал вопросы в QTI 1.2 файле ("В импортируемом файле нет вопросов") —
у Moodle QTI-импорт исторически не полностью совместим с общим стандартом,
требует специфичных внутренних служебных полей. QTI-экспортёр (qti_exporter.py)
не удалён — он покрывает требование задания РУДН про формат "QTI" по имени
и может пригодиться для других LMS.

Источник структуры формата: официальная документация Moodle
(docs.moodle.org/en/Moodle_XML_format).
"""
import xml.etree.ElementTree as ET
from xml.dom import minidom

from src.models import (
    EssayQuestion,
    MatchingQuestion,
    MultipleChoiceQuestion,
    Question,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)


def _short_name(text: str, limit: int = 60) -> str:
    """Название вопроса для Банка вопросов Moodle — короткая версия текста вопроса."""
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _add_common_tags(question: ET.Element, name: str, question_text: str) -> None:
    name_el = ET.SubElement(question, "name")
    ET.SubElement(name_el, "text").text = name

    qtext = ET.SubElement(question, "questiontext")
    qtext.set("format", "html")
    ET.SubElement(qtext, "text").text = question_text


def _add_mc_question(quiz: ET.Element, index: int, q: MultipleChoiceQuestion) -> None:
    question = ET.SubElement(quiz, "question")
    question.set("type", "multichoice")
    _add_common_tags(question, _short_name(q.question), q.question)

    for i, opt in enumerate(q.options):
        answer = ET.SubElement(question, "answer")
        answer.set("fraction", "100" if i == q.correct_index else "0")
        ET.SubElement(answer, "text").text = opt

    ET.SubElement(question, "single").text = "true"
    ET.SubElement(question, "shuffleanswers").text = "1"
    ET.SubElement(question, "answernumbering").text = "abc"

    if q.explanation:
        # generalfeedback — документированное поле, общее для всех типов
        # вопросов в Moodle XML — используем для объяснения модели.
        feedback = ET.SubElement(question, "generalfeedback")
        feedback.set("format", "html")
        ET.SubElement(feedback, "text").text = q.explanation


def _add_tf_question(quiz: ET.Element, index: int, q: TrueFalseQuestion) -> None:
    question = ET.SubElement(quiz, "question")
    question.set("type", "truefalse")
    _add_common_tags(question, _short_name(q.statement), q.statement)

    true_answer = ET.SubElement(question, "answer")
    true_answer.set("fraction", "100" if q.is_true else "0")
    ET.SubElement(true_answer, "text").text = "true"

    false_answer = ET.SubElement(question, "answer")
    false_answer.set("fraction", "0" if q.is_true else "100")
    ET.SubElement(false_answer, "text").text = "false"


def _add_short_answer_question(quiz: ET.Element, index: int, q: ShortAnswerQuestion) -> None:
    question = ET.SubElement(quiz, "question")
    question.set("type", "shortanswer")
    _add_common_tags(question, _short_name(q.question), q.question)

    ET.SubElement(question, "usecase").text = "0"  # без учёта регистра

    answer = ET.SubElement(question, "answer")
    answer.set("fraction", "100")
    ET.SubElement(answer, "text").text = q.sample_answer


def _add_matching_question(quiz: ET.Element, index: int, q: MatchingQuestion) -> None:
    question = ET.SubElement(quiz, "question")
    question.set("type", "matching")
    _add_common_tags(question, _short_name(q.instruction), q.instruction)

    for pair in q.pairs:
        subquestion = ET.SubElement(question, "subquestion")
        ET.SubElement(subquestion, "text").text = pair.left
        answer = ET.SubElement(subquestion, "answer")
        ET.SubElement(answer, "text").text = pair.right

    ET.SubElement(question, "shuffleanswers").text = "true"


def _add_essay_question(quiz: ET.Element, index: int, q: EssayQuestion) -> None:
    question = ET.SubElement(quiz, "question")
    question.set("type", "essay")
    _add_common_tags(question, _short_name(q.question), q.question)

    # У эссе нет автопроверки — критерии оценки кладём в generalfeedback
    # (документированное общее поле), чтобы преподаватель видел их при проверке.
    feedback = ET.SubElement(question, "generalfeedback")
    feedback.set("format", "html")
    ET.SubElement(feedback, "text").text = f"Критерии оценки: {q.grading_criteria}"

    # По формату Moodle XML у эссе всё равно должен быть один answer-тег,
    # даже пустой ("нет ответа и нет оценки" — согласно документации).
    answer = ET.SubElement(question, "answer")
    answer.set("fraction", "0")
    ET.SubElement(answer, "text").text = ""


def questions_to_moodle_xml(questions: list[Question]) -> str:
    """
    Собирает Moodle XML из списка вопросов.

    Args:
        questions: список вопросов любого из пяти типов (см. src/models.py).

    Returns:
        Готовая XML-строка для импорта через
        "Банк вопросов → Импорт → формат Moodle XML".
    """
    quiz = ET.Element("quiz")

    for i, q in enumerate(questions, start=1):
        if isinstance(q, MultipleChoiceQuestion):
            _add_mc_question(quiz, i, q)
        elif isinstance(q, TrueFalseQuestion):
            _add_tf_question(quiz, i, q)
        elif isinstance(q, MatchingQuestion):
            _add_matching_question(quiz, i, q)
        elif isinstance(q, EssayQuestion):
            _add_essay_question(quiz, i, q)
        elif isinstance(q, ShortAnswerQuestion):
            _add_short_answer_question(quiz, i, q)

    rough_string = ET.tostring(quiz, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")