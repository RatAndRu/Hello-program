"""Плакат 0.35: мерки соседа, размер по мерке, ряд с градацией силы.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_035.py

Результат — docs/whatsnew_035.png: сетка 3 × 2, подписи по-русски. Каждая
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

RINGS = ("к = torus major=12 minor=2\n"
         "к = rotate [к] angle=90 axis=x\n"
         "р = ряд [к] count=4 step=[115,0,0] grow=1.5\n")
TWISTED = ("б = box size=[20,20,80]\n"
          "б = refine [б] length=8\n"
          "р = ряд [б] count=5 step=[32,0,0] инструмент=скрутка "
          "сила=15 шаг_силы=1.35 axis=z\n")

# (подпись, мелкая подпись, сценарий, вид, приближение, сдвиг камеры)
CASES = [
    ("кольца всё больше", "ряд из колец: каждое следующее в 1.5 раза",
     RINGS, "front", 1.0, (0, 0, 0.1)),
    ("градация крутки", "пять брусков, крутка сильнее на 35% за копию",
     TWISTED, "iso", 1.05, (0, 0, 0.05)),
    ("сила инструмента ступенями", "вмятины всё глубже: шаг_силы=1.6",
     "ш = sphere radius=16 segments=64\n"
     "р = ряд [ш] count=5 step=[42,0,0] инструмент=вмятина сила=4 "
     "шаг_силы=1.3 soft=0.6 radius=11\n"
     "color р color=#cfd6e2 metal=0.45\n"
     "пол = box size=[260,120,4] at=[0,0,-20]\n"
     "color пол color=#6f7889", "iso", 1.25, (0, 0, 0.16)),
    ("размер по мерке", "вторая 1.5× по ширине и вдвое выше первой",
     "а = box size=[80,50,20] round=4\n"
     "color а color=#8a94a6\n"
     "б = box size=[10,10,10]\n"
     "б = размер [б] width=1.5*width(а) height=2*height(а)\n"
     "б = place [б] on=а side=right offset=6\n"
     "color б color=#cfd6e2 metal=0.2", "iso", 1.0, (0, 0, 0)),
    ("шаг ряда по ширине плиты", "ряд шайб через 0.28*width(плиты)",
     "плита = box size=[160,80,10] round=4\n"
     "color плита color=#8a94a6\n"
     "шайба = cylinder radius=10 height=8 segments=48\n"
     "ряд_шайб = ряд [шайба] count=4 step=[0.28*width(плита),0,0]\n"
     "ряд_шайб = place [ряд_шайб] on=плита side=top offset=0\n"
     "color ряд_шайб color=#dfe6ef metal=0.6", "iso", 1.0, (0, 0, 0.1)),
    ("рост и поворот", "ряд с grow=1.12 и turn=14: ступени изменения",
     "к = box size=[26,26,34] round=2\n"
     "р = ряд [к] count=6 step=[38,0,0] grow=1.12 turn=14 axis=z\n"
     "пол = box size=[260,90,4] at=[0,0,-4]\n"
     "color р color=#cfd6e2 metal=0.25\n"
     "color пол color=#6f7889", "iso", 1.0, (0, 0, 0.12)),
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
    dr.text((28, 20), "ФОРМА 3D 0.35 — мерки соседа, размер по мерке и градация",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "0.5*width(ящик) · размер=1.5× · ряд с grow и turn · сила ступенями"
                      ,
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

    out = ROOT / "whatsnew_035.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
