"""
Диагностика: какие шрифты и цвета видит приложение в PDF.

Зачем: режим «Тест для курса» узнаёт правильный ответ по жирному шрифту и цвету.
Если ответ в PDF выделен, а приложение его не видит, этот скрипт покажет почему.

Запуск из корня проекта:
    python scripts/diagnose_pdf_fonts.py                 # соберёт тестовый PDF и проверит его
    python scripts/diagnose_pdf_fonts.py путь/к/файлу.pdf  # проверит ваш PDF

Можно запускать и на настоящих файлах преподавателей: скрипт ничего не меняет.
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdfminer  # noqa: E402
import pdfplumber  # noqa: E402

from src.parsing.pdf_parser import _is_bold_font, _is_coloured  # noqa: E402


def _find_fonts():
    for folder in (ROOT / "assets", ROOT / "tests" / "assets", ROOT / "assets" / "fonts"):
        regular, bold = folder / "DejaVuSans.ttf", folder / "DejaVuSans-Bold.ttf"
        if regular.exists() and bold.exists():
            return regular, bold
    return None


def _make_test_pdf(path: Path) -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    fonts = _find_fonts()
    if fonts is None:
        raise SystemExit("Не нашла DejaVuSans.ttf и DejaVuSans-Bold.ttf в assets/ — положите их туда.")
    regular, bold = fonts
    print(f"Шрифт обычный: {regular}  ({regular.stat().st_size} байт)")
    print(f"Шрифт жирный:  {bold}  ({bold.stat().st_size} байт)")
    if regular.stat().st_size == bold.stat().st_size:
        print("  !!! Размеры одинаковые: возможно, жирный файл — копия обычного.")
    pdfmetrics.registerFont(TTFont("DejaVuSans", regular))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold))
    c = canvas.Canvas(str(path))
    for y, (text, font) in zip((780, 760, 740), [("обычная строка", "DejaVuSans"),
                                                   ("жирная строка", "DejaVuSans-Bold"),
                                                   ("ещё обычная", "DejaVuSans")]):
        c.setFont(font, 12)
        c.drawString(50, y, text)
    c.save()


def main() -> None:
    import reportlab

    print(f"pdfplumber {pdfplumber.__version__}, pdfminer.six {pdfminer.__version__}, reportlab {reportlab.Version}")

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = ROOT / "data" / "diagnose_test.pdf"
        _make_test_pdf(pdf_path)
        print(f"Тестовый PDF: {pdf_path}")

    fonts_counter: Counter = Counter()
    samples: dict = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:5]:
            for w in page.extract_words(extra_attrs=["fontname", "non_stroking_color"]):
                key = (w["fontname"], str(w["non_stroking_color"]))
                fonts_counter[key] += 1
                samples.setdefault(key, w["text"])

    print("\nШрифты и цвета в файле (первые 5 страниц):")
    for (fontname, color), count in fonts_counter.most_common():
        bold = _is_bold_font(fontname)
        print(f"  {fontname!r:45} цвет={color:24} слов={count:4}  жирный={'ДА' if bold else 'нет'}  пример: {samples[(fontname, color)]!r}")
    if not any(_is_bold_font(f) for f, _ in fonts_counter):
        print("\nЖирных слов приложение не нашло. Пришлите этот вывод целиком.")


if __name__ == "__main__":
    main()
