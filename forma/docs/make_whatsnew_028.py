"""Плакат 0.28: живые превью, четыре новые формы и карандашный стиль.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_028.py

Результат — docs/whatsnew_028.png (сетка 3 × 2, подписи по-русски).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.anime import normalize_style
from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = _font("DejaVuSans-Bold.ttf", 27)
F_NAME = _font("DejaVuSans-Bold.ttf", 18)
F_TEXT = _font("DejaVuSans.ttf", 15)

CROWN = ("к = crown diameter=150 height=48 wall=4 teeth=12 tooth=30 tip=0.35 rim=3")

YIN = ("и = yin_yang diameter=110 thick=14 round=2\n"
       "я = yin_yang diameter=110 thick=14 round=2 side=правый at=[0,0,14] "
       "color=#2b6cb0")

LENS = ("в = lens diameter=64 sag=14 edge=6 mode=выпуклая at=[-38,0,0] "
        "color=#8fd3ff\n"
        "г = lens diameter=64 sag=14 mode=вогнутая at=[38,0,0] color=#ffd08f")

CARTRIDGE = ("в = cartridge diameter=7.62 length=56 kind=винтовочный "
             "at=[-14,0,0] color=#e0b45a\n"
             "п = cartridge diameter=9 length=29 kind=пистолетный "
             "at=[20,0,0] color=#9aa4b2")

# карандашный скетч: штриховка по тени и зерно бумаги
SKETCH = ("корпус = lathe points=[[0,0],[38,0],[38,86],[0,86]] segments=96 "
          "thickness=3 open=top\n"
          "кружка = sphere radius=26 at=[22,0,104]\n"
          "подставка = box size=[110,70,10] at=[0,0,-5]")

# линии по группам: корпус с крышкой — одна сборка, винт — отдельная деталь
GROUPS = ("корпус = box size=[92,58,18] color=#d9e2f2\n"
          "крышка = box size=[92,58,6] at=[0,0,12] color=#d9e2f2\n"
          "кнопка = cylinder radius=8 height=8 at=[22,0,19] color=#e05252\n"
          "винт = cylinder radius=3.4 height=6 at=[-34,17,19] color=#8a94a4\n"
          "сборка = group [корпус, крышка, кнопка]")

# (подпись, сценарий, вид, мелкая подпись, стиль)
CASES = [
    ("корона: зубья отдельно", CROWN, "iso", "число, высота, скругление, бортик", None),
    ("инь-ян: форма-«запятая»", YIN, "iso", "две половины складываются в знак", None),
    ("линза: выпуклая и вогнутая", LENS, "iso", "sag, кромка, край сам по себе", None),
    ("патроны: два вида", CARTRIDGE, "front", "длина ровно 56 и 29 мм", None),
    ("скетч: штриховка и бумага", SKETCH, "iso", "hatch, hatch_angle, paper_tex",
     {"mode": "скетч", "hatch": 0.9, "hatch_angle": 50, "hatch_step": 6,
      "paper_tex": 0.65}),
    ("линии по группам", GROUPS, "iso", "шов только между сборками",
     {"mode": "линия", "line": 1.6, "lines": "группы", "paper": "#f4f6fa"}),
]

TILE = 340
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2
DARK_BG = (0.042, 0.047, 0.058)


def shot(script: str, view: str, style: dict | None = None) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.10
    st = normalize_style(style) if style else None
    bg = DARK_BG if st is None else None
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=st is None, bg=bg, style=style)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.28 — четыре формы и карандаш",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "живые миниатюры без кнопок · корона, инь-ян, линза, патрон · "
                      "штриховка, бумага, линии по группам",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, note, style) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view, style)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 28), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_028.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
