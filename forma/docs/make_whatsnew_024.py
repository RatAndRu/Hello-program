"""Плакат 0.24: семь фигур-знаков на одном листе.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_024.py

Результат — docs/whatsnew_024.png (сетка 4 × 2, подписи по-русски).
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
F_NAME = _font("DejaVuSans-Bold.ttf", 26)
F_TEXT = _font("DejaVuSans.ttf", 19)

# (подпись, сценарий, вид)
CASES = [
    ("Стрелка", "стрелка = arrow length=120 width=26 head=42 head_width=68 depth=12 round=2", "top"),
    ("Форма Т", "тавр = tee arm=90 bar=20 stem=22 leg=60 depth=14 round=2", "iso"),
    ("Полумесяц", "луна = crescent radius=50 thickness=18 depth=12 round=1.5", "top"),
    ("Завиток", "куча = swirl radius=42 height=70 coils=3", "iso"),
    ("Молния", "молния = lightning height=96 width=46 depth=10 round=1.5", "top"),
    ("Банан / бровь", "банан = banana length=120 bend=110 thick=28 flat=0.75", "iso"),
    ("Форма Y", "рогатка = yoke height=110 spread=64 arm=16 fork=0.38 depth=14 round=2", "iso"),
    ("Табличка-указатель", None, "iso"),
]

SCENE = """\
стойка = cylinder radius=5 height=118 at=[0,0,0]
пятка = cylinder radius=22 height=8 round=2 at=[0,0,-12]
табличка = arrow length=104 width=20 head=34 head_width=54 depth=9 stand=да
табличка = translate [табличка] offset=[26,0,74]
табличка2 = arrow length=76 width=15 head=26 head_width=40 depth=7 stand=да
табличка2 = rotate [табличка2] angle=180 axis=z
табличка2 = translate [табличка2] offset=[-20,0,44]"""

TILE = 400
PAD = 26
HEAD = 96


def shot(script: str, view: str) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit(b.error)
    for o in b.scene.objects.values():
        o.color, o.metal, o.rough = "#d7dbe3", 0.0, 0.45
    meshes = _prepare([o for o in b.scene.objects.values() if o.visible])
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.1
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=(0.042, 0.047, 0.058))
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    cols, rows = 4, 2
    width = TILE * cols
    height = HEAD + rows * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 26), "ФОРМА 3D 0.24 — знаки и фигуры", font=F_TITLE,
            fill=(240, 243, 248))
    dr.text((28, 64), "arrow · tee · crescent · swirl · lightning · banana · yoke",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view) in enumerate(CASES):
        col, row = i % cols, i // cols
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(SCENE if script is None else script, view)
        sheet.paste(im, (x, y))
        dr.text((x + 16, y + TILE - 4), name, font=F_NAME, fill=(232, 236, 244))
        if script is None:
            dr.text((x + 16, y + TILE + 26), "stand=да, place, rotate, translate",
                    font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 16, y + TILE + 2), (x + TILE - 16, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_024.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
