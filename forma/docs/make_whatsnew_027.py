"""Плакат 0.27: превью, отражения соседей, честное свечение и вид сцены.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_027.py

Результат — docs/whatsnew_027.png (сетка 3 × 2, подписи по-русски).
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
F_NAME = _font("DejaVuSans-Bold.ttf", 18)
F_TEXT = _font("DejaVuSans.ttf", 15)

# зеркало стоит вертикально, перед ним — цветные детали
MIRROR = ("зеркало = mirror_plate width=340 height=250 frame=24 at=[0,150,0]\n"
          "зеркало = rotate [зеркало] angle=90 axis=x pivot=[0,150,125]\n"
          "шар = sphere radius=42 at=[-50,60,42] color=#e05a3a\n"
          "куб = box size=[66,66,66] at=[42,40,33] round=4 color=#3aa9e0\n"
          "конус = cone radius=30 height=92 at=[104,-46,46] color=#e0c23a")

CLOCK = ("ч = display width=180 height=90 thick=45 style=будильник content=led "
         "text=\"21:38\"")

# часы, повёрнутые целиком: корпус, панель, цифры и стекло едут вместе
CLOCK_TURN = (CLOCK + "\nч = rotate [ч] angle=24 axis=z pivot=[0,0,0]")

# тот же кадр, что показывает превью в карточке инструмента
GEAR = ("ш = gear teeth=20 module=2 thickness=8 bore=6\n"
        "в = washer outer=52 inner=20 thickness=5 at=[0,0,12]")

# (подпись, сценарий, вид, мелкая подпись)
CASES = [
    ("зеркало видит соседей", MIRROR, "iso", "шар, куб и конус — в пластине"),
    ("свечение без утечек", CLOCK, "iso", "ореол не идёт сквозь корпус"),
    ("экран у стекла", CLOCK, "front", "цифры целиком в рамке"),
    ("поворот двигает детали", CLOCK_TURN, "iso", "корпус, панель и стекло"),
    ("превью из карточки", GEAR, "iso", "крутится, не попадая в сцену"),
    ("отражение вблизи", MIRROR, "front", "луч от пикселя в PNG"),
]

TILE = 340
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2


def shot(script: str, view: str) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    meshes = _prepare(solids)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.10
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=(0.042, 0.047, 0.058))
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.27 — превью, отражения, свечение",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "3D-превью в карточках · зеркало отражает соседей · "
                      "свечение без утечек · вид сцены в сценарии",
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

    out = ROOT / "whatsnew_027.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
