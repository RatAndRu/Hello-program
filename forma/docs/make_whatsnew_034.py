"""Плакат 0.34: объёмный аниме-бюст, волосы, оригами, складки, цепь, инструкция.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_034.py

Результат — docs/whatsnew_034.png: сетка 3 × 2, подписи по-русски. Каждая
плитка — настоящая сцена, построенная текстовым сценарием, а не рисунок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build
from forma.webui import load_example

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

BUST = load_example("anime_face")

# (подпись, мелкая подпись, сценарий, вид, приближение, сдвиг камеры)
CASES = [
    ("аниме-бюст: объём", "голова, шея и плечи одним SDF",
     BUST, "iso", 1.0, (0, 0, 0.1)),
    ("глаз с обводкой", "контур по всему глазу, купол глубины",
     "г1 = глаз width=70 height=46 at=[-44,0,60] iris=#8fa48f lash=4 depth=0.55\n"
     "г2 = глаз width=70 height=46 at=[44,0,60] iris=#6f7f96 lash=4 depth=0.9\n"
     "color г1 color=#f4d6c3\ncolor г2 color=#f4d6c3", "front", 1.0, None),
    ("локоны и волосинки", "три завитка и пучок волосков",
     "л1 = локон at=[-80,0,190] length=130 radius=17 turns=0.75 thick=15 thin=6 "
     "dir=[0,0,-1] side=[1,0,0]\n"
     "л2 = локон at=[-40,20,180] length=150 radius=20 turns=0.9 thick=17 thin=6 "
     "dir=[0,0,-1] side=[1,0,0]\n"
     "л3 = локон at=[0,-10,200] length=120 radius=14 turns=0.6 thick=13 thin=5 "
     "dir=[0,0,-1] side=[-1,0,0]\n"
     "в = волосинки from=[-60,-40,60] to=[80,-40,60] count=60 length=90 "
     "thick=1.8 bend=0.8 curl=0.5 dir=[0,-0.25,-1] base=да\n"
     "color л1 color=#ece4da\ncolor л2 color=#ece4da\ncolor л3 color=#ece4da\n"
     "color в color=#ece4da", "iso", 1.0, None),
    ("сгиб от угла", "лист сложен по диагонали от угла",
     "а = sheet width=110 length=110 thickness=1\n"
     "б = сгиб а at=[0,0,1] dir=45 angle=120\n"
     "б = translate [б] offset=[-70,0,0]\n"
     "в = sheet width=110 length=150 thickness=1\n"
     "г = сгиб в at=[0,-20,1] dir=0 angle=95 side=-1\n"
     "г = translate [г] offset=[75,0,0]\n"
     "color б color=#f3ecdf\ncolor г color=#dfe3cf", "iso", 1.0, None),
    ("складки на одежде", "гребни-складки и канавка на юбке",
     "чехол = cylinder radius=56 r2=34 height=140 segments=160\n"
     "с1 = складка чехол from=[-40,-24,132] to=[-55,-14,12] r=5 mode=гребень taper=0.55 bend=3\n"
     "с2 = складка с1 from=[-16,-35,136] to=[-22,-52,10] r=5 mode=гребень taper=0.55 bend=-3\n"
     "с3 = складка с2 from=[6,-37,136] to=[10,-55,10] r=5.5 mode=гребень taper=0.55 bend=3\n"
     "с4 = складка с3 from=[26,-30,132] to=[36,-40,12] r=5 mode=гребень taper=0.55 bend=-3\n"
     "с5 = складка с4 from=[42,-14,124] to=[52,-8,18] r=4.5 mode=канавка taper=0.6\n"
     "color с5 color=#8aa0b8", "iso", 1.0, None),
    ("цепь и соединение", "звенья зацеплены, балка и лампа",
     "балка = box size=[130,36,12] round=2 at=[0,0,200]\n"
     "лампа = hemisphere radius=26 at=[0,0,60]\n"
     "ц = соединить [балка, лампа] size=17 wire=2.4 sag=0.1\n"
     "прям = цепь links=7 size=24 wire=3.2 at=[-120,90,20] dir=[1,0,0]\n"
     "color балка color=#4a4f57\ncolor лампа color=#f0c46a\n"
     "color ц color=#c9ccd2\ncolor прям color=#c9ccd2", "iso", 1.0, (0, 0, 0.15)),
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
    dr.text((28, 20), "ФОРМА 3D 0.34 — объёмный бюст, волосы, оригами и цепь",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "бюст вместо панели · глаз с обводкой · локоны и волосинки · "
                      "сгиб от угла · складки · цепь",
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

    out = ROOT / "whatsnew_034.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
