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

FLAT = "л = sheet width=120 length=180 thickness=1.4"
WAVE = "л = sheet width=110 length=200 thickness=1 step=26 amp=7"
CROSS = "л = sheet width=150 length=170 thickness=1 step=22 amp=6 wave=крест"
ROLL = "л = sheet width=120 length=600 thickness=0.6 roll=6 gap=1.4"
FOLD = ("л = sheet width=100 length=200 thickness=1.5\n"
        "fold л parts=2 angle=180 gap=6")
CARD = "к = cardboard width=34 height=150 liner=0.9 flute=8 step=14"

# (подпись, сценарий, вид, мелкая подпись, приближение)
CASES = [
    ("плоскость-лист", FLAT, "iso", "тонкий параллелепипед, а не полигон", 1.0),
    ("волнистость", WAVE, "iso", "шаг и амплитуда волны", 1.0),
    ("волна крестом", CROSS, "iso", "wave=крест — вафельный лист", 1.0),
    ("рулон бумаги", ROLL, "iso", "roll и зазор между витками", 1.0),
    ("оригами: пополам", FOLD, "iso", "fold parts=2, просвет gap", 1.0),
    ("гофрокартон", CARD, "iso", "линеры и гофра одним телом", 0.92),
]

TILE = 340
PAD = 54
HEAD = 88
COLS, ROWS = 3, 2
DARK_BG = (0.042, 0.047, 0.058)


def shot(script: str, view: str, zoom: float = 1.0) -> Image.Image:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08 * zoom
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=False, bg=DARK_BG)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.30 — лист, рулон, сгиб и гофра",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "плоскость с объёмом · волнистость · свёртка в рулон · "
                      "оригами-сгиб · гофрирование и картон",
            font=F_TEXT, fill=(120, 128, 144))

    for i, (name, script, view, note, zoom) in enumerate(CASES):
        col, row = i % COLS, i // COLS
        x = col * TILE
        y = HEAD + row * (TILE + PAD)
        im = shot(script, view, zoom)
        sheet.paste(im, (x, y))
        dr.text((x + 14, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        dr.text((x + 14, y + TILE + 28), note, font=F_TEXT, fill=(128, 136, 150))
        dr.line([(x + 14, y + TILE + 2), (x + TILE - 14, y + TILE + 2)],
                fill=(46, 52, 62))
        if col:
            dr.line([(x, HEAD), (x, height)], fill=(30, 34, 42))

    out = ROOT / "whatsnew_030.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
