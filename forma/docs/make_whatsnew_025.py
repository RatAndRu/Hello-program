"""Плакат 0.25: пятнадцать новых команд на одном листе.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_025.py

Результат — docs/whatsnew_025.png (сетка 5 × 3, подписи по-русски).
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


F_TITLE = _font("DejaVuSans-Bold.ttf", 30)
F_NAME = _font("DejaVuSans-Bold.ttf", 20)
F_TEXT = _font("DejaVuSans.ttf", 17)

# (подпись, сценарий, вид, подпись мелким шрифтом)
CASES = [
    ("wrinkle · складки", "к = box size=[70,70,70]\nwrinkle к amp=3 freq=5 mode=радиус", "iso",
     "amp, freq, mode, detail"),
    ("relief · рельеф", "к = box size=[70,70,70]\nrelief к image=docs/pattern.png depth=4 mode=обёртка",
     "iso", "image, depth, mode"),
    ("porous · поры", "ш = sphere radius=34\nporous ш mode=поры size=5 count=70", "iso",
     "поры · ячеи · пузыри"),
    ("scales · чешуя", "ш = sphere radius=34\nscales ш rows=10 per_row=16 length=7", "iso",
     "rows, per_row, length"),
    ("lattice · решётка", "ш = sphere radius=36\nlattice ш cell=14 wire=3 mode=ромб", "iso",
     "прямоуг · ромб · соты"),
    ("bark · кора", "дуб = bark height=300 radius=40 grooves=12 depth=6", "iso",
     "высота, борозды, сужение"),
    ("bricks · кладка", "стена = bricks width=300 height=200 thick=45 brick=[80,38] joint=6",
     "iso", "кирпич, шов, глубина"),
    ("blade — клинок", "к = blade length=700 width=44 thick=7 kind=катана curve=70", "iso",
     "катана · танто · серп"),
    ("hair · волосы", "в = hair length=170 style=аниме clumps=26 radius=60", "iso",
     "аниме · хвост · мех"),
    ("skirt · юбка", "ю = skirt waist=70 hem=190 length=220 pleats=14 depth=10 thick=3", "iso",
     "складки и толщина ткани"),
    ("jacket · пиджак", "п = jacket height=700 chest=1040 waist=920", "iso",
     "обхваты в мм, рукава"),
    ("display · часы", 'ч = display width=180 height=90 thick=45 style=будильник content=led',
     "iso", "led-цифры, стекло, подставка"),
    ("зеркало", "з = mirror_plate width=240 height=340 frame=16", "iso",
     "рама + отражающая пластина"),
    ("pattern · горошек", "куб = box size=[60,60,60]\npattern куб #d94f3d shape=круги size=12 step=24",
     "iso", "круги на всех гранях"),
    ("pattern · клетка", "куб = box size=[60,60,60]\npattern куб #2f6fb0 shape=клетка size=10 step=20 angle=45",
     "iso", "клетка с поворотом 45°"),
]

TILE = 300
PAD = 24
HEAD = 88
COLS, ROWS = 5, 3


def shot(script: str, view: str) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    # основной корпус красим в общий тон, экран/стекло/цифры оставляем как есть
    for o in solids:
        if "." not in o.name:
            o.color, o.metal, o.rough = "#d7dbe3", 0.0, 0.45
    meshes = _prepare(solids)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.12
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=(0.042, 0.047, 0.058))
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 22), "ФОРМА 3D 0.25 — поверхность, одежда, экраны, узоры", font=F_TITLE,
            fill=(240, 243, 248))
    dr.text((28, 58), "wrinkle · relief · porous · scales · lattice · bark · bricks · blade · "
                      "hair · skirt · jacket · display · mirror_plate · pattern",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, note) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE - 2), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 22), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_025.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
