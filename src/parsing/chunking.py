"""
Разбиение извлечённого текста на смысловые чанки перед отправкой в LLM.

Зачем это отдельный шаг, а не просто "кинуть в GigaChat всё как есть":
  - Если отправлять каждую страницу лекции по отдельности — вопросы
    получаются мелкими и оторванными от контекста соседних слайдов.
  - Если отправлять всю лекцию одним куском — дорого по токенам и модель
    хуже удерживает фокус на длинном тексте.
Компромисс: группируем соседние страницы в чанки заданного целевого размера.
"""
from dataclasses import dataclass

from src.parsing.pdf_parser import ParsedDocument, PageContent

# Целевой размер чанка в символах. Это не жёсткий лимит, а ориентир —
# страницы добавляются в чанк, пока не превысим это значение.
DEFAULT_CHUNK_SIZE = 3000

# Служебные слайды (прощание, финальная благодарность) — не пустые (поэтому
# likely_scanned их не ловит), но и не несут учебного содержания. Реальный
# случай из практики: GigaChat сгенерировал по такому слайду вопрос
# "Как завершить лекцию?" с ответом "Сказать «Спасибо за внимание»" —
# формально валидный вопрос, но не проверяющий никаких знаний по теме.
_CLOSING_SLIDE_MARKERS = [
    "спасибо за внимание",
    "успехов в обучении",
    "спасибо за просмотр",
    "конец лекции",
]


def _is_closing_slide(text: str) -> bool:
    """Эвристика: слайд похож на служебную концовку презентации."""
    normalized = text.lower()
    return any(marker in normalized for marker in _CLOSING_SLIDE_MARKERS)


@dataclass
class TextChunk:
    """Один смысловой кусок текста, готовый для отправки в LLM."""

    chunk_id: int
    text: str
    page_numbers: list[int]  # какие страницы вошли в чанк (для ссылок в вопросах)
    char_count: int


def chunk_document(
    document: ParsedDocument,
    target_chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[TextChunk]:
    """
    Группирует страницы документа в чанки заданного целевого размера.

    Страницы, помеченные как вероятный скан (likely_scanned), полностью
    пустые, или похожие на служебные "прощальные" слайды, пропускаются —
    из них нельзя сгенерировать осмысленные вопросы.

    Args:
        document: результат parse_pdf().
        target_chunk_size: ориентировочный размер чанка в символах.

    Returns:
        Список TextChunk — каждый содержит одну или несколько соседних страниц.
    """
    usable_pages = [
        p for p in document.pages
        if not p.likely_scanned and p.text.strip() and not _is_closing_slide(p.text)
    ]

    chunks: list[TextChunk] = []
    current_pages: list[PageContent] = []
    current_size = 0

    for page in usable_pages:
        page_text = page.text.strip()

        # Если добавление этой страницы превысит целевой размер и в чанке
        # уже что-то накоплено — закрываем текущий чанк и начинаем новый.
        if current_pages and current_size + len(page_text) > target_chunk_size:
            chunks.append(_build_chunk(len(chunks) + 1, current_pages))
            current_pages = []
            current_size = 0

        current_pages.append(page)
        current_size += len(page_text)

    if current_pages:
        chunks.append(_build_chunk(len(chunks) + 1, current_pages))

    return chunks


def _build_chunk(chunk_id: int, pages: list[PageContent]) -> TextChunk:
    text = "\n\n".join(p.text.strip() for p in pages)
    return TextChunk(
        chunk_id=chunk_id,
        text=text,
        page_numbers=[p.page_number for p in pages],
        char_count=len(text),
    )