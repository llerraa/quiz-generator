from src.exporters.aiken_exporter import count_skipped_for_aiken, questions_to_aiken
from src.models import (
    EssayQuestion,
    MatchingPair,
    MatchingQuestion,
    MultipleChoiceQuestion,
    ShortAnswerQuestion,
    TrueFalseQuestion,
)


def _mcq(correct_index=1):
    return MultipleChoiceQuestion(
        question="Какой язык называют интерпретируемым?",
        options=["Assembler", "Python", "Машинный код"],
        correct_index=correct_index,
        explanation="Python выполняется интерпретатором.",
    )


def _others():
    return [
        MatchingQuestion(
            instruction="Сопоставьте",
            pairs=[MatchingPair(left="a", right="1"), MatchingPair(left="b", right="2")],
        ),
        EssayQuestion(question="Опишите...", grading_criteria="Полнота"),
        ShortAnswerQuestion(question="Столица?", sample_answer="Москва"),
    ]


def test_mcq_block_format():
    text = questions_to_aiken([_mcq()])
    assert text == (
        "Какой язык называют интерпретируемым?\n"
        "A. Assembler\n"
        "B. Python\n"
        "C. Машинный код\n"
        "ANSWER: B\n"
    )


def test_answer_letter_follows_correct_index():
    for idx, letter in enumerate("ABC"):
        assert f"ANSWER: {letter}" in questions_to_aiken([_mcq(correct_index=idx)])


def test_true_false_true_and_false():
    t = questions_to_aiken([TrueFalseQuestion(statement="Земля круглая.", is_true=True)])
    f = questions_to_aiken([TrueFalseQuestion(statement="Земля плоская.", is_true=False)])
    assert t == "Земля круглая.\nA. Верно\nB. Неверно\nANSWER: A\n"
    assert f == "Земля плоская.\nA. Верно\nB. Неверно\nANSWER: B\n"


def test_blocks_separated_by_blank_line():
    text = questions_to_aiken([_mcq(), TrueFalseQuestion(statement="Утверждение.", is_true=True)])
    blocks = text.strip().split("\n\n")
    assert len(blocks) == 2
    assert blocks[1].startswith("Утверждение.")


def test_unsupported_types_are_skipped_and_counted():
    questions = [_mcq(), *_others()]
    assert count_skipped_for_aiken(questions) == 3
    text = questions_to_aiken(questions)
    assert "Сопоставьте" not in text
    assert "Опишите" not in text
    assert "Столица" not in text
    assert text.count("ANSWER:") == 1


def test_only_unsupported_types_gives_empty_string():
    assert questions_to_aiken(_others()) == ""
    assert count_skipped_for_aiken(_others()) == 3


def test_empty_list():
    assert questions_to_aiken([]) == ""
    assert count_skipped_for_aiken([]) == 0


def test_line_breaks_inside_question_and_options_are_collapsed():
    q = MultipleChoiceQuestion(
        question="Первая строка\nвторая строка",
        options=["вариант\nс переносом", "обычный"],
        correct_index=0,
    )
    text = questions_to_aiken([q])
    assert text.splitlines()[0] == "Первая строка вторая строка"
    assert "A. вариант с переносом" in text
    # одна строка вопроса + 2 варианта + ANSWER
    assert len(text.strip().splitlines()) == 4


def test_explanation_is_not_written():
    assert "Python выполняется" not in questions_to_aiken([_mcq()])
