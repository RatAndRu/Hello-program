"""Плакат 0.32: степень детализации примитивов.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_detail_032.py

Результат — docs/detail_032.png: один и тот же примитив на уровнях 0…5,
под каждым — настоящее число треугольников из сборки.
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
F_TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 27)
F_LEVEL = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 17)
F_TEXT = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 13)

TILE = 250
HEAD = 96
ROW_LABEL = 26      # строка с названием примитива над рядом
ROW_CAPTION = 42    # подписи «detail=d» и число трисов под рядом
FOOT = 44
BG = (0.055, 0.062, 0.075)

# (подпись, сценарий без detail)
ROWS = [
    ("сфера radius=50", "ш = sphere radius=50"),
    ("цилиндр radius=40 height=100", "ц = cylinder radius=40 height=100"),
    ("куб 120×80×60 round=6", "к = box size=[120,80,60] round=6"),
    ("тор major=55 minor=12", "т = torus major=55 minor=12"),
]
LEVELS = range(6)


def shot(script: str) -> tuple[Image.Image, int]:
    b = build(script, analyze_model=False)
    if not b.ok:
        raise SystemExit((b.error or {}).get("message"))
    solids = [o for o in b.scene.objects.values() if o.visible]
    tris = int(sum(o.manifold.num_tri() for o in solids))
    meshes = _prepare(solids, b.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * 1.02
    img, _ = _render_view(meshes, c, r, "iso", TILE, 2, [*lo, *hi], grid=False,
                          shadow=True, bg=BG)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB"), tris


def main() -> None:
    width = TILE * len(LEVELS)
    height = HEAD + len(ROWS) * (ROW_LABEL + TILE + ROW_CAPTION) + FOOT
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 22), "ФОРМА 3D 0.32 — степень детализации примитива",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 60), "ползунок «детализация» 0…5 · число треугольников видно "
                      "прямо в карточке инструмента",
            font=F_TEXT, fill=(120, 128, 144))

    y = HEAD
    for name, script in ROWS:
        dr.text((10, y + 6), name, font=F_LEVEL, fill=(176, 190, 208))
        y += ROW_LABEL
        for level in LEVELS:
            x = level * TILE
            im, tris = shot(f"{script} detail={level}")
            sheet.paste(im, (x, y))
            dr.text((x + 12, y + TILE + 4), f"detail={level}",
                    font=F_LEVEL, fill=(226, 232, 240))
            dr.text((x + 12, y + TILE + 22), f"{tris} трис",
                    font=F_TEXT, fill=(138, 158, 180))
            if level:
                dr.line([(x, y), (x, y + TILE)], fill=(30, 34, 42))
        y += TILE + ROW_CAPTION

    foot = y + 6
    dr.text((28, foot), "0 — черновая сетка (быстро, видно грани) · 3 — обычная "
                        "(по умолчанию) · 5 — гладкая и тяжёлая",
            font=F_TEXT, fill=(150, 160, 176))
    out = ROOT / "detail_032.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
