"""Визуальная приёмка 0.51: соус, кляксы и узлы из исполняемых сценариев.

Запуск из forma/: PYTHONPATH=. python docs/make_organic_051.py
Нужны numpy, manifold3d и Pillow. Результат: docs/organic_051.png.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
OUT = Path("/tmp/forma051_organic")
FONTS = Path("/usr/share/fonts/truetype/dejavu")
TILE, PAD, HEAD = 420, 58, 112
COLS, ROWS = 3, 2
DARK_BG = (0.055, 0.062, 0.075)

F_TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 29)
F_SUBTITLE = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 16)
F_NAME = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 18)
F_TEXT = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 14)

CASES = [
    ("Соус на носителе", "ray-cast · круглое сечение · носитель сохранён", "iso",
     "сосиска = capsule radius=15 height=150 color=#b96755\n"
     "сосиска = rotate [сосиска] angle=90 axis=y\n"
     "горчица = sauce [сосиска] length=105 amplitude=12 waves=5 radius=2.2 "
     "drips=2 seed=4 color=#e7b700"),
    ("Волна и боковые ветви", "pattern=волна · drips=3 · seed=4", "iso",
     "соус = sauce length=120 amplitude=18 waves=4 radius=2.5 "
     "pattern=волна drips=3 seed=4 color=#e7b700"),
    ("Клякса · seed 12", "выпуклый объём · 7 отдельных брызг", "iso",
     "клякса = blot radius=45 thickness=4 dome=1.4 droplets=7 seed=12 color=#d51f72"),
    ("Клякса · seed 31", "тот же сценарий, другая воспроизводимая форма", "iso",
     "клякса = blot radius=45 thickness=4 dome=1.4 droplets=7 seed=31 color=#d51f72"),
    ("Простой узел и восьмёрка", "3D-переплетения · проверенный просвет", "iso",
     "простой = knot kind=простой size=70 radius=2.5 tail=10 at=[-65,0,0] color=#d5c59c\n"
     "восьмёрка = knot kind=восьмерка size=70 radius=2.5 tail=10 at=[65,0,0] color=#d5c59c"),
    ("Бант и галстук", "свободные концы · замкнутые объёмные сетки", "iso",
     "бант = knot kind=бант size=70 radius=2.5 tail=10 at=[-75,0,0] color=#d5c59c\n"
     "галстук = knot kind=галстук size=70 radius=2.5 tail=10 at=[75,0,0] color=#d5c59c"),
]


def shot(script: str, view: str, index: int) -> Image.Image:
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error))
    solids = result.visible_solids()
    for solid in solids:
        if solid.manifold.is_empty() or solid.manifold.volume() <= 0:
            raise SystemExit(f"Пустое тело в сцене {index}: {solid.name}")
    meshes = _prepare(solids, result.scene.groups)
    vertices = np.concatenate([m["verts"] for m in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08
    image, _ = _render_view(meshes, center, radius, view, TILE, 2,
                            [*lo, *hi], grid=False, shadow=True,
                            bg=DARK_BG, style=None)
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / f"{index:02d}_{view}.png",
              (np.clip(image, 0, 1) * 255).astype(np.uint8))
    return Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8), "RGB")


def main() -> None:
    width = COLS * TILE + (COLS + 1) * PAD
    height = HEAD + ROWS * (TILE + 66) + (ROWS + 1) * PAD
    canvas = Image.new("RGB", (width, height), (17, 22, 29))
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, 27), "ФОРМА 3D 0.51 — соус, клякса и узлы",
              font=F_TITLE, fill=(237, 242, 249))
    draw.text((PAD, 70), "Собственная параметрическая геометрия; никаких импортированных сеток или декалей.",
              font=F_SUBTITLE, fill=(158, 174, 192))
    for index, (title, subtitle, view, script) in enumerate(CASES):
        row, col = divmod(index, COLS)
        x = PAD + col * (TILE + PAD)
        y = HEAD + PAD + row * (TILE + 66 + PAD)
        canvas.paste(shot(script, view, index + 1), (x, y))
        draw.text((x + 3, y + TILE + 12), title, font=F_NAME, fill=(230, 236, 244))
        draw.text((x + 3, y + TILE + 39), subtitle, font=F_TEXT, fill=(147, 163, 181))
    canvas.save(ROOT / "organic_051.png", optimize=True)
    print(ROOT / "organic_051.png")


if __name__ == "__main__":
    main()
