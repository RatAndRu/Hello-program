"""Плакат 0.31: часы без фризов, зеркало по метке и порядок в окнах.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_031.py

Результат — docs/whatsnew_031.png (сетка 3 × 2, подписи по-русски).
Рисуем тот самый скелетон-механизм, который раньше «не крутился»: окно
больше не строит зеркала по металлу и не пересобирает шейдеры на каждом
кадре, поэтому его можно вращать и запускать сцену «ход».
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
F_NAME = _font("DejaVuSans-Bold.ttf", 18)
F_TEXT = _font("DejaVuSans.ttf", 15)

CLOCK = load_example("clock")
MIRROR = ("плита = mirror_plate width=260 height=260 frame=22 shape=круг\n"
          "шар = sphere radius=48 at=[0, 0, 0]\n"
          "шар = translate [шар] offset=[0, 0, 52]")

# (подпись, сценарий, вид, мелкая подпись, приближение, точка наведения)
# точка наведения — доля габарита от центра модели: так крупный план
# наводится на баланс или на колёса, а не на пустоту по центру
CASES = [
    ("часы целиком", CLOCK, "iso", "101 деталь, 44 300 трис — крутится", 1.0, None),
    ("скелетон спереди", CLOCK, "front", "шесть колёс в зацеплении", 1.0, None),
    ("механизм крупно", CLOCK, "iso", "баланс, вилка и мостики", 2.2, (0.16, 0, 0.1)),
    ("зеркальная плита", MIRROR, "iso", "зеркало — только явная метка", 1.0, None),
    ("часы сбоку", CLOCK, "right", "толщина корпуса и головка", 1.0, None),
    ("колёса и мостики", CLOCK, "front", "animate … scene=ход, 8 секунд", 1.9,
     (0.05, 0, -0.16)),
]

TILE = 340
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2
DARK_BG = (0.042, 0.047, 0.058)


def shot(script: str, view: str, zoom: float = 1.0, focus=None) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    if focus:
        c = c + (hi - lo) * np.array(focus, dtype=float)
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08 / zoom
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=DARK_BG)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.31 — часы без фризов, зеркало по метке",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "меню у курсора · панели тянутся и сворачиваются · "
                      "часы крутятся и играют · GIF и видео — в «Загрузки»",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, note, zoom, focus) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view, zoom, focus)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 28), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_031.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
