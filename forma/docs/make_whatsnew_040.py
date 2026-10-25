"""Плакат 0.40: лестница, рычаг, кнопка, призма с любыми углами, сектор тора.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_040.py

Результат — docs/whatsnew_040.png: сетка 3 × 2, подписи по-русски. Каждая
плитка — настоящая сцена, построенная текстовым сценарием, а не рисунок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = _font("DejaVuSans-Bold.ttf", 27)
F_NAME = _font("DejaVuSans-Bold.ttf", 17)
F_TEXT = _font("DejaVuSans.ttf", 14)

TILE = 380
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2
DARK_BG = (0.055, 0.062, 0.075)

# (подпись, мелкая подпись, сценарий, вид, приближение, сдвиг камеры)
CASES = [
    ("Лестница: рейка и перекладина", "капсула/брусок/овал · цилиндр/брусок",
     "а = ladder length=1700 width=420 rungs=9 tilt=76\n"
     "б = ladder length=1500 width=380 rail=брусок rail_d=44 rung=брусок "
     "rung_d=34 rungs=7 tilt=90 at=[700,0,0]\n"
     "color а color=#cfd6e2 metal=0.2\n"
     "color б color=#b98a5a metal=0.0 rough=0.6",
     "iso", 1.0, (0, 0, 0.02)),
    ("Рычаг: палка и ручка", "палка цилиндр/брусок · ручка шар/цилиндр/нет",
     "а = lever length=200 diameter=14 knob=шар knob_d=40\n"
     "б = lever length=200 shaft=брусок size=20 knob=цилиндр knob_d=30 knob_h=70 "
     "at=[300,0,0]\n"
     "в = lever length=200 diameter=16 knob=шар knob_d=44 angle=35 at=[600,0,0]\n"
     "color а color=#cfd6e2 metal=0.55 rough=0.3\n"
     "color б color=#8fb3d9 metal=0.35\n"
     "color в color=#d98f6a metal=0.1",
     "iso", 1.0, (0, 0, 0.05)),
    ("Кнопка: шляпка + гнездо", "два объекта: верх плоский/вогнутый/выпуклый",
     "а = button diameter=34 height=12 top=вогнутая\n"
     "б = button diameter=34 height=12 top=выпуклая base=квадрат base_d=80 "
     "at=[120,0,0]\n"
     "в = button diameter=30 height=10 fit=зазор gap=3 base_d=74 at=[240,0,0]\n"
     "color а color=#e2c86a metal=0.4\n"
     "color а_гнездо color=#5a6070 metal=0.1\n"
     "color б color=#e2c86a metal=0.4\n"
     "color б_гнездо color=#5a6070 metal=0.1\n"
     "color в color=#e2c86a metal=0.4\n"
     "color в_гнездо color=#5a6070 metal=0.1",
     "iso", 1.0, (0, 0, 0.0)),
    ("Треугольная призма: любые углы", "стороны 120/90/60 · 100/100/40 · по углам",
     "а = tri_prism a=120 b=90 c=60 height=40 at=[-150,0,0]\n"
     "б = tri_prism a=100 b=100 c=40 height=34 at=[0,0,60]\n"
     "в = tri_prism base=100 angle_a=30 angle_b=120 height=36 at=[200,0,0]\n"
     "color а color=#9fb8cf metal=0.25\n"
     "color б color=#cfd6e2 metal=0.25\n"
     "color в color=#b9a6d9 metal=0.25",
     "iso", 1.0, (0, 0, 0.02)),
    ("Сектор тора: дуга и отверстие", "угол · поворот · hole — дырка под подвес",
     "а = torus_sector major=60 minor=10 angle=180 at=[-160,0,220]\n"
     "б = torus_sector major=50 minor=12 angle=200 hole=8 at=[60,0,220]\n"
     "в = torus_sector major=34 minor=9 angle=300 hole=6 at=[230,0,220]\n"
     "color а color=#cfd6e2 metal=0.7 rough=0.25\n"
     "color б color=#e2b26a metal=0.7 rough=0.25\n"
     "color в color=#8fd9b3 metal=0.7 rough=0.25\n"
     "пол = box size=[700,300,4] at=[0,0,-10]\n"
     "color пол color=#2a303c",
     "iso", 1.15, (0, 0, 0.08)),
    ("Кнопка нажата и отпущена", "шляпку двигают отдельно от гнезда",
     "к = button diameter=46 height=14 top=выпуклая base_d=110 base_h=10\n"
     "п = button diameter=46 height=14 top=выпуклая base_d=110 base_h=10 "
     "at=[170,0,0]\n"
     "translate п offset=[0,0,30]\n"
     "color к color=#e2c86a metal=0.45\n"
     "color к_гнездо color=#5a6070\n"
     "color п color=#e2c86a metal=0.45\n"
     "color п_гнездо color=#5a6070",
     "iso", 1.0, (0, 0, 0.06)),
]


def shot(script: str, view: str, zoom: float, focus):
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible and o.name != "сетка"]
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    if focus:
        c = c + (hi - lo) * np.array(focus, dtype=float)
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08 / zoom
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=True, bg=DARK_BG, style=None)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.40 — механика и произвольные формы",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "лестница · рычаг · кнопка из двух деталей · призма с любыми "
                      "углами · сектор тора с отверстием",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, note, script, view, zoom, focus) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view, zoom, focus)
        sheet.paste(im, (x, y))
        dr.text((x + 12, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 12, y + TILE + 26), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 12, y + TILE + 2), (x + TILE - 12, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_040.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
