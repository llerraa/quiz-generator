"""
Экспорт сгенерированных вопросов в формат QTI 1.2 (IMS QTI) для импорта в LMS
(Moodle и другие системы, поддерживающие импорт вопросов в формате QTI).

Собираем XML вручную через стандартный xml.etree — не через сторонние
библиотеки. Пробовали две:
  - text2qti — не поддерживает вопросы на соответствие вообще;
  - qti_package_maker — падает на кириллице (внутренняя проверка требует
    только ASCII для расчёта контрольных сумм, без возможности отключить).
Обе оказались непригодны для русскоязычного контента.

ВАЖНО: файл проверен на валидность XML и корректную кодировку UTF-8, но
поведение конкретно в Moodle не проверялось на реальном сервере (нет доступа
для теста). Перед реальным использованием стоит один раз попробовать импорт
и свериться с результатом — если Moodle потребует полный IMS-пакет (zip с
imsmanifest.xml) вместо одного XML-файла, это отдельная небольшая доработка.

Про эссе отдельно: у него нет автоматической проверки (resprocessing) — это
осознанное решение, у открытого вопроса нет единственного правильного
ответа, проверять должен человек. Критерии оценки приложены как "решение"
(itemfeedback/solution) — стандартный элемент QTI для подсказки
проверяющему, но не все LMS одинаково его отображают при импорте.
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


def _material(parent: ET.Element, text: str) -> None:
    """Добавляет стандартный QTI-блок <material><mattext>...</mattext></material>."""
    material = ET.SubElement(parent, "material")
    mattext = ET.SubElement(material, "mattext")
    mattext.set("texttype", "text/plain")
    mattext.text = text


def _add_mc_item(section: ET.Element, item_id: str, question_text: str, options: list[str], correct_index: int) -> None:
    """Добавляет вопрос с одним верным вариантом (используется и для MCQ, и для верно/неверно)."""
    item = ET.SubElement(section, "item")
    item.set("ident", item_id)
    item.set("title", item_id)

    presentation = ET.SubElement(item, "presentation")
    _material(presentation, question_text)

    response_lid = ET.SubElement(presentation, "response_lid")
    response_lid.set("ident", "response1")
    response_lid.set("rcardinality", "Single")
    render_choice = ET.SubElement(response_lid, "render_choice")

    option_ids = [f"opt_{i}" for i in range(len(options))]
    for opt_id, opt_text in zip(option_ids, options):
        response_label = ET.SubElement(render_choice, "response_label")
        response_label.set("ident", opt_id)
        _material(response_label, opt_text)

    resprocessing = ET.SubElement(item, "resprocessing")
    outcomes = ET.SubElement(resprocessing, "outcomes")
    decvar = ET.SubElement(outcomes, "decvar")
    decvar.set("maxvalue", "100")
    decvar.set("minvalue", "0")
    decvar.set("varname", "SCORE")
    decvar.set("vartype", "Decimal")

    respcondition = ET.SubElement(resprocessing, "respcondition")
    respcondition.set("continue", "No")
    conditionvar = ET.SubElement(respcondition, "conditionvar")
    varequal = ET.SubElement(conditionvar, "varequal")
    varequal.set("respident", "response1")
    varequal.text = option_ids[correct_index]
    setvar = ET.SubElement(respcondition, "setvar")
    setvar.set("action", "Set")
    setvar.set("varname", "SCORE")
    setvar.text = "100"


def _add_matching_item(section: ET.Element, item_id: str, instruction: str, pairs: list) -> None:
    """
    Добавляет вопрос на соответствие.

    QTI 1.2 не имеет отдельного "типа" для соответствия — стандартный подход:
    один response_lid на каждую левую часть пары, каждый предлагает выбрать
    из ВСЕХ правых вариантов (это и создаёт эффект "сопоставления").
    """
    item = ET.SubElement(section, "item")
    item.set("ident", item_id)
    item.set("title", item_id)

    presentation = ET.SubElement(item, "presentation")
    _material(presentation, instruction)

    right_ids = [f"right_{i}" for i in range(len(pairs))]

    for i, pair in enumerate(pairs):
        response_lid = ET.SubElement(presentation, "response_lid")
        response_lid.set("ident", f"response_{i}")
        response_lid.set("rcardinality", "Single")
        material = ET.SubElement(response_lid, "material")
        mattext = ET.SubElement(material, "mattext")
        mattext.set("texttype", "text/plain")
        mattext.text = pair.left
        render_choice = ET.SubElement(response_lid, "render_choice")
        for right_id, other_pair in zip(right_ids, pairs):
            response_label = ET.SubElement(render_choice, "response_label")
            response_label.set("ident", right_id)
            _material(response_label, other_pair.right)

    resprocessing = ET.SubElement(item, "resprocessing")
    outcomes = ET.SubElement(resprocessing, "outcomes")
    decvar = ET.SubElement(outcomes, "decvar")
    decvar.set("maxvalue", "100")
    decvar.set("minvalue", "0")
    decvar.set("varname", "SCORE")
    decvar.set("vartype", "Decimal")

    # Каждая пара оценивается независимо — за каждый верный ответ начисляется
    # равная доля от 100 (100 / количество пар).
    points_per_pair = round(100 / len(pairs), 2)
    for i, right_id in enumerate(right_ids):
        respcondition = ET.SubElement(resprocessing, "respcondition")
        respcondition.set("continue", "Yes")
        conditionvar = ET.SubElement(respcondition, "conditionvar")
        varequal = ET.SubElement(conditionvar, "varequal")
        varequal.set("respident", f"response_{i}")
        varequal.text = right_id
        setvar = ET.SubElement(respcondition, "setvar")
        setvar.set("action", "Add")
        setvar.set("varname", "SCORE")
        setvar.text = str(points_per_pair)


def _add_short_answer_item(section: ET.Element, item_id: str, question_text: str, sample_answer: str) -> None:
    """
    Добавляет вопрос с коротким текстовым ответом.

    QTI 1.2: response_str + render_fib (поле свободного ввода) вместо
    response_lid (список вариантов). Ответ студента сверяется с эталонным
    без учёта регистра — это стандартная, но приблизительная проверка:
    опечатки или синонимы автоматически не засчитаются.
    """
    item = ET.SubElement(section, "item")
    item.set("ident", item_id)
    item.set("title", item_id)

    presentation = ET.SubElement(item, "presentation")
    _material(presentation, question_text)

    response_str = ET.SubElement(presentation, "response_str")
    response_str.set("ident", "response1")
    response_str.set("rcardinality", "Single")
    render_fib = ET.SubElement(response_str, "render_fib")
    response_label = ET.SubElement(render_fib, "response_label")
    response_label.set("ident", "answer1")

    resprocessing = ET.SubElement(item, "resprocessing")
    outcomes = ET.SubElement(resprocessing, "outcomes")
    decvar = ET.SubElement(outcomes, "decvar")
    decvar.set("maxvalue", "100")
    decvar.set("minvalue", "0")
    decvar.set("varname", "SCORE")
    decvar.set("vartype", "Decimal")

    respcondition = ET.SubElement(resprocessing, "respcondition")
    respcondition.set("continue", "No")
    conditionvar = ET.SubElement(respcondition, "conditionvar")
    varequal = ET.SubElement(conditionvar, "varequal")
    varequal.set("respident", "response1")
    varequal.set("case", "No")  # сверка без учёта регистра
    varequal.text = sample_answer
    setvar = ET.SubElement(respcondition, "setvar")
    setvar.set("action", "Set")
    setvar.set("varname", "SCORE")
    setvar.text = "100"


def _add_essay_item(section: ET.Element, item_id: str, question_text: str, grading_criteria: str) -> None:
    """
    Добавляет открытый вопрос (эссе) — без автоматической проверки.

    У эссе нет единственного правильного ответа, поэтому resprocessing
    (автоматическое начисление баллов) не добавляем — оценивает
    преподаватель вручную. Критерии оценки прикладываем как "решение"
    (itemfeedback/solution) — стандартный элемент QTI 1.2 для подсказки
    проверяющему, что должно быть в хорошем ответе.
    """
    item = ET.SubElement(section, "item")
    item.set("ident", item_id)
    item.set("title", item_id)

    presentation = ET.SubElement(item, "presentation")
    _material(presentation, question_text)

    response_str = ET.SubElement(presentation, "response_str")
    response_str.set("ident", "response1")
    response_str.set("rcardinality", "Single")
    render_fib = ET.SubElement(response_str, "render_fib")
    render_fib.set("rows", "10")
    render_fib.set("columns", "60")
    response_label = ET.SubElement(render_fib, "response_label")
    response_label.set("ident", "answer1")

    itemfeedback = ET.SubElement(item, "itemfeedback")
    itemfeedback.set("ident", "solution")
    solution = ET.SubElement(itemfeedback, "solution")
    solutionmaterial = ET.SubElement(solution, "solutionmaterial")
    _material(solutionmaterial, grading_criteria)


def questions_to_qti_xml(questions: list[Question], quiz_title: str = "Тест") -> str:
    """
    Собирает QTI 1.2 XML-файл из списка вопросов.

    Args:
        questions: список вопросов любого из пяти типов (см. src/models.py).
        quiz_title: название теста, отобразится в LMS при импорте.

    Returns:
        Готовая XML-строка (с объявлением кодировки UTF-8), пригодная для
        сохранения в .xml-файл и импорта в LMS.
    """
    root = ET.Element("questestinterop")
    assessment = ET.SubElement(root, "assessment")
    assessment.set("ident", "quiz_1")
    assessment.set("title", quiz_title)
    section = ET.SubElement(assessment, "section")
    section.set("ident", "section_1")

    for i, q in enumerate(questions, start=1):
        item_id = f"item_{i}"
        if isinstance(q, MultipleChoiceQuestion):
            _add_mc_item(section, item_id, q.question, q.options, q.correct_index)
        elif isinstance(q, TrueFalseQuestion):
            options = ["Верно", "Неверно"]
            correct_index = 0 if q.is_true else 1
            _add_mc_item(section, item_id, q.statement, options, correct_index)
        elif isinstance(q, MatchingQuestion):
            _add_matching_item(section, item_id, q.instruction, q.pairs)
        elif isinstance(q, ShortAnswerQuestion):
            _add_short_answer_item(section, item_id, q.question, q.sample_answer)
        elif isinstance(q, EssayQuestion):
            _add_essay_item(section, item_id, q.question, q.grading_criteria)

    # minidom для человекочитаемого форматирования (переносы строк, отступы) —
    # сам ET такого не умеет, а сырой XML в одну строку неудобно проверять глазами.
    rough_string = ET.tostring(root, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")