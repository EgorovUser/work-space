"""Генерирует PWA-иконки в frontend/public/icons/ через PyMuPDF.

Иконки уже лежат в репозитории — скрипт нужен только при смене дизайна
(цвет, глиф, скругление) или добавлении размера. Запуск из корня репо:

    .venv/bin/python scripts/make_pwa_icons.py

Дизайн: скруглённый квадрат цвета --accent (#0e6b54) с белой «W».
Маскируемая и яблочная — полный квадрат без прозрачности (требование
платформ: safe zone 80% для maskable, непрозрачность для iOS).
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "icons"

ACCENT = (0.055, 0.42, 0.33)  # #0e6b54 — --accent светлой темы
WHITE = (1.0, 1.0, 1.0)

# (файл, размер, скругление, доля глифа, прозрачность)
SPECS = (
    ("icon-192.png", 192, True, 0.5, True),
    ("icon-512.png", 512, True, 0.5, True),
    ("icon-512-maskable.png", 512, False, 0.38, False),
    ("apple-touch-icon.png", 180, False, 0.5, False),
)


def make_icon(size: int, out: Path, rounded: bool, glyph: float, alpha: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=size, height=size)
    shape = page.new_shape()
    if rounded:
        shape.draw_rect(fitz.Rect(0, 0, size, size), radius=0.22)
    else:
        shape.draw_rect(fitz.Rect(0, 0, size, size))
    shape.finish(fill=ACCENT, color=None)
    shape.commit()
    fontsize = size * glyph
    width = fitz.get_text_length("W", fontname="hebo", fontsize=fontsize)
    page.insert_text(
        fitz.Point((size - width) / 2, size / 2 + 0.36 * fontsize),
        "W",
        fontsize=fontsize,
        fontname="hebo",
        color=WHITE,
    )
    pix = page.get_pixmap(alpha=alpha)
    pix.save(str(out))
    doc.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, rounded, glyph, alpha in SPECS:
        out = OUT / name
        make_icon(size, out, rounded, glyph, alpha)
        print(f"{name}: {size}x{size}, rounded={rounded}")
    print(f"готово: {OUT}")


if __name__ == "__main__":
    main()
