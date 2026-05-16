#!/usr/bin/env python3
"""Создаёт PNG-иконки 192 и 512 для manifest (нужен Pillow). Запуск: python scripts/generate_pwa_icons.py"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Установите Pillow: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"
BG = (15, 17, 23)
ACCENT = (79, 127, 255)
ACCENT2 = (167, 139, 250)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG + (255,))
    d = ImageDraw.Draw(img)
    m = size // 16
    r_outer = size // 6
    x0, y0 = m * 3, m * 4
    x1, y1 = size - m * 3, size - m * 3
    d.rounded_rectangle([x0, y0, x1, y1], radius=r_outer, outline=ACCENT, width=max(2, size // 32))
    d.line([x0, y0 + (y1 - y0) // 4, x1, y0 + (y1 - y0) // 4], fill=ACCENT, width=max(2, size // 40))
    cy = y0 + (y1 - y0) * 3 // 5
    for cx, col in ((x0 + (x1 - x0) // 4, ACCENT), (size // 2, ACCENT2), (x1 - (x1 - x0) // 4, ACCENT)):
        r = size // 28
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for sz in (192, 512):
        path = OUT / f"icon-{sz}.png"
        draw_icon(sz).save(path, "PNG")
        print(f"OK {path}")
    print("Готово. Перезапустите сервер и обновите страницу (Ctrl+F5).")


if __name__ == "__main__":
    main()
