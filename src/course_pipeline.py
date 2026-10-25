"""
Подготовка теста для курса из файла преподавателя (режим «Тест для курса»).

Задача: преподаватель положил файл с готовыми вопросами в любом оформлении,
а на выходе нужен тест из до 25 вопросов в формате Aiken (один верный ответ).

Правила:
  - файл уже в формате Aiken → читаем обычным кодом, без модели;
  - иначе модель находит вопросы и ПОМЕТКИ правильных ответов (сама ответы
    не выбирает), а годится вопрос под Aiken или нет — решает этот модуль;
  - берём первые 25 подходящих вопросов подряд, неподходящие пропускаем
    и честно перечисляем с причинами, чтобы ничего не терялось молча;
  - файл режется на фрагменты: так ответ модели короче, и можно остановиться,
    как только набрано нужное число вопросов (экономит запросы).

Причины пропуска вопроса:
  - не найдена пометка правильного ответа;
  - отмечено несколько верных ответов (в Aiken он только один);
  - число вариантов не от 2 до 6;
  - вопрос без вариантов ответа (открытый, на соответствие и т.п.);
  - ошибка формата в самом файле Aiken.
"""
from dataclasses import dataclass, field
from typing import Callable

from src.models import MultipleChoiceQuestion, TrueFalseQuestion
from src.parsing.aiken_parser import looks_like_aiken, parse_aiken

TARGET_QUESTIONS = 25
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 600

CourseQuestion = MultipleChoiceQuestion | TrueFalseQuestion


@dataclass
class SkippedQuestion:
    title: str  # начало вопроса (может быть пустым, если вопрос не удалось даже прочитать)
    reason: str


@dataclass
class CourseTestResult:
    questions: list[CourseQuestion] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # по какой пометке определён ответ; параллельно questions
    skipped: list[SkippedQuestion] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # фрагменты, которые не удалось обработать
    source: str = "llm"  # "aiken" — прочитано кодом, "llm" — через модель
    stopped_early: bool = False  # набрали цель, остаток файла не разбирали
    extra_valid: int = 0  # подходящих вопросов сверх цели (отброшены)
    target: int = TARGET_QUESTIONS

    @property
    def shortfall(self) -> int:
        """Сколько вопросов не хватает до цели."""
        return max(0, self.target - len(self.questions))


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Режет текст на фрагменты по границам строк, с небольшим перекрытием.

    Перекрытие нужно, чтобы вопрос, оказавшийся на стыке, целиком попал хотя бы
    в один фрагмент (обрубки на краях модель пропускает по инструкции).
    """
    lines = text.splitlines()
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > size:
            chunks.append("\n".join(current))
            # хвост предыдущего фрагмента становится началом следующего
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(current):
                if tail_len + len(prev) + 1 > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            current, current_len = tail, tail_len
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _short(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def _classify(item) -> tuple[MultipleChoiceQuestion | None, str | None]:
    """Годится ли вопрос под Aiken: возвращает (вопрос, None) или (None, причина)."""
    question_text = " ".join(item.question.split())
    options = [" ".join(o.split()) for o in item.options if o.strip()]

    if not question_text:
        return None, "нет текста вопроса"
    if len(options) < 2:
        return None, "меньше двух вариантов ответа"
    if len(options) > 6:
        return None, f"больше 6 вариантов ({len(options)})"

    answers = sorted(set(item.marked_answers))
    if not answers:
        return None, "не найдена пометка правильного ответа"
    if len(answers) > 1:
        return None, "отмечено несколько верных ответов (в Aiken он только один)"
    if not 0 <= answers[0] < len(options):
        return None, "пометка указывает на несуществующий вариант"
    if not item.answer_evidence.strip():
        # Ответ назван, а пометки-основания нет: похоже на догадку модели
        return None, "не удалось подтвердить пометку ответа в тексте файла"

    return MultipleChoiceQuestion(
        question=question_text, options=options, correct_index=answers[0]
    ), None


def _from_aiken(text: str, target: int) -> CourseTestResult:
    parsed = parse_aiken(text)
    result = CourseTestResult(source="aiken", target=target)
    result.questions = list(parsed.questions[:target])
    result.evidence = ["формат Aiken: строка ANSWER"] * len(result.questions)
    result.extra_valid = max(0, len(parsed.questions) - target)
    result.skipped = [SkippedQuestion(title="", reason=err) for err in parsed.errors]
    return result


def prepare_course_test(
    text: str,
    extract_fn: Callable[[str], object] | None,
    target: int = TARGET_QUESTIONS,
    on_progress: Callable[[int, int], None] | None = None,
) -> CourseTestResult:
    """
    Превращает текст файла преподавателя в тест для курса.

    Args:
        text: текст файла (с метками оформления, см. docx_parser.EMPHASIS_LEGEND).
        extract_fn: функция «фрагмент текста → результат извлечения», обычно
            BotHubClient().extract_course_questions. Не нужна для файла Aiken.
        target: сколько вопросов нужно в тесте.
        on_progress: необязательный отчёт о ходе работы (готово_фрагментов, всего).
    """
    text = text.strip()
    if not text:
        raise ValueError("В файле нет текста.")

    if looks_like_aiken(text):
        return _from_aiken(text, target)

    if extract_fn is None:
        raise ValueError("Для файла не в формате Aiken нужна функция извлечения.")

    result = CourseTestResult(source="llm", target=target)
    seen: set[str] = set()
    chunks = split_text(text)

    for index, chunk in enumerate(chunks, start=1):
        if len(result.questions) >= target:
            result.stopped_early = True
            break
        try:
            extraction = extract_fn(chunk)
        except Exception as exc:  # один сбойный фрагмент не должен терять остальные
            result.errors.append(f"Фрагмент {index} из {len(chunks)} не обработан: {exc}")
            if on_progress:
                on_progress(index, len(chunks))
            continue

        for item in extraction.questions:
            key = _key(item.question)
            if key:  # вопрос без текста дубликатом не считаем — он попадёт в «пропущенные»
                if key in seen:
                    continue
                seen.add(key)
            question, reason = _classify(item)
            if question is None:
                result.skipped.append(SkippedQuestion(title=_short(item.question), reason=reason))
            elif len(result.questions) < target:
                result.questions.append(question)
                result.evidence.append(item.answer_evidence.strip())
            else:
                result.extra_valid += 1

        for item in extraction.unsupported:
            key = _key(item.text)
            if key:
                if key in seen:
                    continue
                seen.add(key)
            result.skipped.append(
                SkippedQuestion(title=_short(item.text), reason=f"нет вариантов ответа: {item.reason}")
            )

        if on_progress:
            on_progress(index, len(chunks))

    return result
