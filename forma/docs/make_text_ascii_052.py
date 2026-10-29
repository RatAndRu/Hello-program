"""Визуальная приёмка шрифта 0.52: атласы и объёмный ASCII-рендер.

Запуск из forma/: PYTHONPATH=. python docs/make_text_ascii_052.py
Нужны numpy, manifold3d и Pillow.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.fonts import glyph_strokes
from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")
TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 30)
SUBTITLE = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 17)
LABEL = ImageFont.truetype(str(FONTS / "DejaVuSansMono.ttf"), 14)
SMALL = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 14)
ASCII = "".join(chr(code) for code in range(32, 127))
CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ" + "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def atlas(chars: str, title: str, subtitle: str, output: str) -> None:
    cols, cell_w, cell_h, pad, head = 10, 142, 160, 24, 116
    rows = (len(chars) + cols - 1) // cols
    image = Image.new("RGB", (cols * cell_w + (cols + 1) * pad,
                              head + rows * cell_h + (rows + 1) * pad), (16, 21, 28))
    draw = ImageDraw.Draw(image)
    draw.text((pad, 22), title, font=TITLE, fill=(239, 244, 250))
    draw.text((pad, 69), subtitle, font=SUBTITLE, fill=(157, 174, 193))
    for index, char in enumerate(chars):
        row, col = divmod(index, cols)
        x0 = pad + col * (cell_w + pad)
        y0 = head + pad + row * (cell_h + pad)
        draw.rounded_rectangle((x0, y0, x0 + cell_w, y0 + cell_h), radius=8,
                               fill=(29 + (index % 2) * 3, 36 + (index % 2) * 3, 46))
        if char == " ":
            draw.text((x0 + 31, y0 + 45), "SPACE", font=SUBTITLE, fill=(224, 190, 112))
        else:
            scale = 13.5
            origin_x = x0 + (cell_w - 4 * scale) / 2
            baseline = y0 + 105
            for line in glyph_strokes(char):
                points = [(origin_x + x * scale, baseline - y * scale) for x, y in line]
                draw.line(points, fill=(232, 238, 246), width=5, joint="curve")
                radius = 2.5
                for x, y in (points[0], points[-1]):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                                 fill=(232, 238, 246))
        code = f"{ord(char):03d}  U+{ord(char):04X}"
        draw.text((x0 + 12, y0 + 138), code, font=LABEL, fill=(133, 151, 171))
    image.save(ROOT / output, optimize=True)
    print(ROOT / output)


def solid_render() -> None:
    rows = [ASCII[1:16], ASCII[16:33], ASCII[33:49], ASCII[49:64],
            ASCII[64:81], ASCII[81:95]]
    scripts = []
    for index, text in enumerate(rows):
        scripts.append(f"ряд_{index} = text {json.dumps(text)} size=8 depth=0.8 "
                       f"weight=0.55 plane=xy at=[0,{-index * 14},0]")
    result = build("\n".join(scripts), analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error))
    solids = result.visible_solids()
    meshes = _prepare(solids, result.scene.groups)
    vertices = np.concatenate([mesh["verts"] for mesh in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2 * 1.04
    image, _ = _render_view(meshes, center, radius, "top", 1500, 2,
                            [*lo, *hi], grid=False, shadow=False,
                            bg=(0.055, 0.062, 0.075), style=None)
    pixels = (np.clip(image, 0, 1) * 255).astype(np.uint8)
    output = ROOT / "text_geometry_052.png"
    write_png(output, pixels)
    print(f"{output} — {len(solids)} строк, {sum(s.stats()['tris'] for s in solids)} треугольников")


def main() -> None:
    atlas(ASCII, "ФОРМА 3D 0.52 — 95 печатных символов ASCII",
          "Фактические штрихи встроенного шрифта; коды десятичные и Unicode.", "text_ascii_052.png")
    atlas(CYRILLIC, "ФОРМА 3D 0.52 — кириллица двух регистров",
          "Отдельные строчные формы; исправленные Ц, Ы, Э и Я.", "text_cyrillic_052.png")
    solid_render()


if __name__ == "__main__":
    main()
