"""Плакат 0.33: место в пространстве, меры в выражениях и бюджет кубов.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_033.py

Результат — docs/whatsnew_033.png: сетка 3 × 2, подписи по-русски. Каждая
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
    ("зазор при пересечении", "деталь входила в плиту — встала ровно в 5 мм",
     "плита = box size=[110,110,16] at=[0,0,0]\n"
     "деталь = box size=[28,28,28] at=[0,0,12]\n"
     "сопряжение деталь плита type=зазор axis=z offset=5\n"
     "color плита color=#7c8798\ncolor деталь color=#d9a15b", "iso", 1.0, (0, 0, 0.2)),
    ("плоскость на наклонной плите", "шапка легла на грань, а не на угол габарита",
     "плита = box size=[120,120,10]\n"
     "плита = rotate [плита] angle=28 axis=x\n"
     "шапка = box size=[40,40,30] round=2 at=[0,0,30]\n"
     "сопряжение шапка плита type=плоскость axis=z\n"
     "color плита color=#6f7a8b\ncolor шапка color=#cfe0ee", "iso", 1.0, None),
    ("паз на повёрнутой рейке", "колесо село на верхнюю грань наклонной рейки",
     "рейка = box size=[36,260,12] center=да at=[0,0,30]\n"
     "рейка = rotate [рейка] angle=18 axis=x\n"
     "колесо = cylinder radius=16 height=14 center=да\n"
     "сопряжение колесо рейка type=паз axis=y\n"
     "color рейка color=#8d93a4\ncolor колесо color=#e0b46c", "iso", 1.0, None),
    ("меры прямо в командах", "крышка на top(кружка)+2, ручка на height(…)",
     "кружка = cylinder radius=34 height=84 segments=64\n"
     "крышка = cylinder radius=36 height=8 at=[0,0,top(кружка)+2]\n"
     "ручка = torus major=26 minor=6 at=[cx(кружка)+40,0,height(кружка)*0.55]\n"
     "color кружка color=#b9c6d4\ncolor крышка color=#8b6f5a\ncolor ручка color=#8b6f5a",
     "iso", 1.0, (0, 0, 0.1)),
    ("точное место проверяется", "check … положение x=… y=… z=… с допуском",
     "осн = box size=[120,90,10]\n"
     "а = cylinder radius=12 height=26 at=[-34,-22,10]\n"
     "б = box size=[24,24,26] at=[0,22,10]\n"
     "в = sphere radius=14 at=[36,-22,24]\n"
     "check а положение -46 -34 10 допуск=0.5\n"
     "check б центр 0 22 23\n"
     "color осн color=#59616f\ncolor а color=#c9d6e3\ncolor б color=#d9a15b\n"
     "color в color=#8fd0b0", "iso", 1.0, (0, 0, 0.2)),
    ("бюджет кубической сетки", "сетка 20 мм + вписать — срезано лишнее",
     "сетка cell=20 origin=[-60,-60,0] size=[4,4,3]\n"
     "корпус = cylinder radius=46 height=76 segments=64 at=[0,0,0]\n"
     "корпус = вписать корпус\n"
     "check корпус в_сетке\n"
     "color корпус color=#9fb6c9", "iso", 1.0, (0, 0, 0.15)),
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
    dr.text((28, 20), "ФОРМА 3D 0.33 — место в пространстве, меры и бюджет",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "check положение/центр · меры в любых командах · "
                      "зазор по факту · грани вместо коробки · кубы-бюджет",
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

    out = ROOT / "whatsnew_033.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
