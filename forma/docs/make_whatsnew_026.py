"""Плакат 0.26: аниме и манга — контуры по форме, тон, растр, бумага.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_026.py

Результат — docs/whatsnew_026.png (сетка 4 × 2, подписи по-русски).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.anime import normalize_style
from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build
from forma.webui import load_example

ROOT = Path(__file__).resolve().parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = _font("DejaVuSans-Bold.ttf", 30)
F_NAME = _font("DejaVuSans-Bold.ttf", 20)
F_TEXT = _font("DejaVuSans.ttf", 17)

BASE = ("ваза = lathe points=[[0,0],[26,0],[40,30],[30,62],[16,90],[0,92]]\n"
        "куб = box size=[56,56,56] at=[78,0,28] round=4\n"
        "шар = sphere radius=26 at=[-64,0,26]")

CLOCK = load_example("clock_led")
BRICKS = "стена = bricks width=280 height=190 thick=42 brick=[76,36] joint=6"
GEAR = ("ш = gear teeth=18 module=3 thickness=12 bore=12 hub=24 hub_height=4\n"
        "к = gear teeth=10 module=3 thickness=12 bore=8")

# (подпись, сценарий, вид, режим, мелкая подпись)
CASES = [
    ("обычный вид", BASE, "iso", None, "без стиля — как обычно"),
    ("аниме", BASE, "iso", "аниме", "контур по форме + ступени тона"),
    ("манга", BASE, "iso", "манга", "бумага, серый тон точками"),
    ("комикс", BASE, "iso", "комикс", "толстый контур, точки в тенях"),
    ("линия", BASE, "iso", "линия", "только контуры, без тона"),
    ("линия · часы", CLOCK, "iso", "линия", "линии по корпусу и цифрам"),
    ("аниме · кладка", BRICKS, "iso", "аниме", "каждый кирпич обведён"),
    ("манга · шестерня", GEAR, "iso", "манга", "контур по зубьям и ступице"),
]

TILE = 300
PAD = 24
HEAD = 88
COLS, ROWS = 4, 2


def shot(script: str, view: str, mode: str | None) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    for o in solids:
        if "." not in o.name:
            o.color, o.metal, o.rough = "#d7dbe3", 0.0, 0.45
    meshes = _prepare(solids)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.12
    style = normalize_style({"mode": mode}) if mode else None
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=(0.042, 0.047, 0.058), style=style)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 22), "ФОРМА 3D 0.26 — аниме и манга: контуры по форме",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 58), "anime mode=аниме · манга · комикс · линия — "
                      "силуэт, изломы, стыки деталей, ступени тона, растр и бумага",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, mode, note) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view, mode)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE - 2), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 22), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_026.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
