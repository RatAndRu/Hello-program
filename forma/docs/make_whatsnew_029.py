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

TRI = "пила = saw diameter=200 thickness=2.5 teeth=24 shape=треугольные rake=12"
CARB = ("пила = saw diameter=180 thickness=2.4 teeth=30 shape=трапеция "
        "windows=6 kerf=3.2 color=#c9d4e2")
HOOK = "пила = saw diameter=200 thickness=2.6 teeth=18 shape=крюк rake=-14 kerf=3.6"
WAVE = "пила = saw diameter=200 thickness=2.5 teeth=20 shape=волна tooth=14"
RIM = ("пила = saw diameter=200 thickness=3 teeth=36 shape=трапеция "
       "kerf=4.6 color=#cfd9e6")
SET = ("вал = cylinder radius=11 height=34 at=[0,0,0] color=#8a94a4\n"
       "пила = saw diameter=220 thickness=3 teeth=36 shape=трапеция hole=24 "
       "at=[0,0,17] color=#dfe7f2\n"
       "гайка = nut d=22 pitch=2 h=12 at=[0,0,34] color=#b9c4d2")

# (подпись, сценарий, вид, мелкая подпись)
CASES = [
    ("треугольные зубья", TRI, "top", "rake=12° — остриё вперёд"),
    ("трапеция-карбид", CARB, "top", "площадка и 6 окон"),
    ("крюк", HOOK, "top", "загнутая вершина, rake=−14°"),
    ("волна", WAVE, "top", "плавный зуб без острых вершин"),
    ("торец и пропил", RIM, "iso", "kerf шире полотна"),
    ("пила на валу", SET, "iso", "hole, толщина, посадка"),
]

TILE = 340
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2
DARK_BG = (0.042, 0.047, 0.058)


def shot(script: str, view: str) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.10
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=DARK_BG)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.29 — дисковая пила и порядок в окнах",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "плоское полотно с настоящими зубьями · четыре формы · "
                      "пропил, окна, отверстие под вал",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, note) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 28), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_029.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
