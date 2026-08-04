"""
Генерирует тестовый PDF, имитирующий лекцию, для проверки pdf_parser.py.

Не часть основного приложения — вспомогательный скрипт для тестов
и ручной проверки, так как реальные лекционные материалы ИМЭС
в репозиторий не кладём (см. README, раздел про приватность данных).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Стандартные шрифты reportlab (Helvetica) не поддерживают кириллицу —
# ищем любой шрифт с поддержкой кириллицы среди типичных путей разных ОС.
_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),  # macOS
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),        # Linux
    Path("C:/Windows/Fonts/arial.ttf"),                             # Windows
]
_FONT_PATH = next((p for p in _FONT_CANDIDATES if p.exists()), None)

if _FONT_PATH is None:
    raise FileNotFoundError(
        "Не найден шрифт с поддержкой кириллицы ни по одному известному пути. "
        "Найдите в Finder любой .ttf-файл (например, в /System/Library/Fonts) "
        "и добавьте его путь в список _FONT_CANDIDATES выше."
    )

pdfmetrics.registerFont(TTFont("DejaVuSans", _FONT_PATH))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _FONT_PATH))

def make_sample_pdf(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    c = canvas.Canvas(str(output_path), pagesize=A4)

    # Страница 1 — обычный текстовый слайд с "лекционным" содержанием
    c.setFont("DejaVuSans-Bold", 16)
    c.drawString(50, 800, "Лекция 1. Основы нейронных сетей")
    c.setFont("DejaVuSans", 12)
    text_lines = [
        "Нейронная сеть — это математическая модель, вдохновлённая",
        "структурой биологических нейронных сетей мозга.",
        "",
        "Основные компоненты:",
        "1. Входной слой — принимает признаки объекта.",
        "2. Скрытые слои — выполняют преобразования данных.",
        "3. Выходной слой — формирует итоговый прогноз.",
        "",
        "Функция активации вводит нелинейность в модель, без неё",
        "сеть из любого числа слоёв эквивалентна одному линейному слою.",
    ]
    y = 760
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 20
    c.showPage()

    # Страница 2 — тоже текстовая, для проверки постраничного извлечения
    c.setFont("DejaVuSans-Bold", 16)
    c.drawString(50, 800, "Функции активации")
    c.setFont("DejaVuSans", 12)
    text_lines_2 = [
        "ReLU (Rectified Linear Unit) — наиболее популярная функция",
        "активации в современных архитектурах: f(x) = max(0, x).",
        "",
        "Sigmoid сжимает значения в диапазон (0, 1), но страдает",
        "от проблемы затухающего градиента на глубоких сетях.",
    ]
    y = 760
    for line in text_lines_2:
        c.drawString(50, y, line)
        y -= 20
    c.showPage()

    # Страница 3 — почти пустая, имитирует "скан без текстового слоя"
    # (например, слайд-схема, где весь смысл в картинке, а не в тексте)
    c.setFont("DejaVuSans", 10)
    c.drawString(50, 800, "Рис. 1")
    c.showPage()

    c.save()
    return output_path


if __name__ == "__main__":
    path = make_sample_pdf(Path(__file__).parent.parent / "data" / "sample" / "test_lecture.pdf")
    print(f"Тестовый PDF создан: {path}")
