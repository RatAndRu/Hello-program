"""Плакат 0.42: девять настоящих сцен, построенных текстовым DSL.

Запуск из forma/: PYTHONPATH=. python docs/make_whatsnew_042.py
Результат: docs/whatsnew_042.png (3 × 3, русские подписи).
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
TILE, PAD, HEAD = 380, 54, 88
COLS = ROWS = 3
DARK_BG = (0.055, 0.062, 0.075)


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = font("DejaVuSans-Bold.ttf", 27)
F_NAME = font("DejaVuSans-Bold.ttf", 17)
F_TEXT = font("DejaVuSans.ttf", 14)

# Подпись, пояснение, сценарий. В каждом ряду уровни идут слева направо.
CASES = [
    ("Независимый верх", "размер · сдвиг · эллиптический масштаб",
     "б = box size=[70,55,50] top_size=[45,32] top_offset=[10,0] at=[-65,0,0]\n"
     "ц = cylinder radius=28 r2=22 height=55 top_scale=[1.25,0.75] top_offset=[8,0] at=[65,0,0]\n"
     "color б color=steel\ncolor ц color=cyan"),
    ("Параллелограмм и вершина", "base_angle=60 · tip_at=corner",
     "б = box size=[65,45,38] base_angle=60 at=[-65,0,0]\n"
     "п = pyramid sides=4 radius=35 height=65 base_angle=60 tip_at=corner at=[65,0,0]\n"
     "color б color=gold\ncolor п color=copper"),
    ("Сдвиг к ребру и сглаживание", "пирамида: edge · smooth=0/2",
     "п = pyramid sides=4 radius=35 height=65 tip_at=edge tip_index=1 at=[-60,0,0]\n"
     "с = pyramid sides=4 radius=35 height=65 smooth=2 at=[60,0,0]\n"
     "color п color=violet\ncolor с color=green"),
    ("Октаэдр", "исходный · divisions=2 · divisions=1 smooth=2",
     "а = octa radius=30 height=70 at=[-90,0,0]\n"
     "б = octa radius=30 height=70 divisions=2 at=[0,0,0]\n"
     "в = octa radius=30 height=70 divisions=1 smooth=2 at=[90,0,0]\n"
     "color а color=orange\ncolor б color=gold\ncolor в color=red"),
    ("Плоский срез сферы", "целая · slice=0.5 · slice=1 round=3",
     "а = sphere radius=38 at=[-100,0,38]\n"
     "б = sphere radius=38 slice=0.5 at=[0,0,38]\n"
     "в = sphere radius=38 slice=1 round=3 at=[100,0,38]\n"
     "color а color=cyan\ncolor б color=red\ncolor в color=pink"),
    ("Эллипсоид", "divisions=0 / 1 / 2 · полуоси сохранены",
     "а = ellipsoid x=40 y=28 z=32 divisions=0 at=[-100,0,0]\n"
     "б = ellipsoid x=40 y=28 z=32 divisions=1 at=[0,0,0]\n"
     "в = ellipsoid x=40 y=28 z=32 divisions=2 at=[100,0,0]\n"
     "color а color=green\ncolor б color=mint\ncolor в color=cyan"),
    ("Треугольная икосфера", "20 / 80 / 320 панелей · уровни 0 / 1 / 2",
     "а = icosphere radius=35 mode=triangle divisions=0 at=[-90,0,35]\n"
     "б = icosphere radius=35 mode=triangle divisions=1 at=[0,0,35]\n"
     "в = icosphere radius=35 mode=triangle divisions=2 at=[90,0,35]\n"
     "color а color=orange\ncolor б color=gold\ncolor в color=yellow"),
    ("Квадратная куб-сфера", "6 / 24 / 96 квадратов · уровни 0 / 1 / 2",
     "а = icosphere radius=35 mode=quad divisions=0 at=[-90,0,35]\n"
     "б = icosphere radius=35 mode=quad divisions=1 at=[0,0,35]\n"
     "в = icosphere radius=35 mode=quad divisions=2 at=[90,0,35]\n"
     "color а color=blue\ncolor б color=cyan\ncolor в color=mint"),
    ("Двойственная сота", "12 / 42 / 162 панели · 12 пятиугольников",
     "а = icosphere radius=35 mode=pentagon divisions=0 at=[-90,0,35]\n"
     "б = icosphere radius=35 mode=сота divisions=1 at=[0,0,35]\n"
     "в = icosphere radius=35 mode=сота divisions=2 at=[90,0,35]\n"
     "color а color=pink\ncolor б color=violet\ncolor в color=purple"),
]


def shot(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit((result.error or {}).get("message"))
    solids = [o for o in result.scene.objects.values() if o.visible]
    meshes = _prepare(solids, result.scene.groups)
    vertices = np.concatenate([m["verts"] for m in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08
    image, _ = _render_view(meshes, center, radius, "iso", TILE, 2,
                            [*lo, *hi], grid=False, shadow=True,
                            bg=DARK_BG, style=None)
    path = ROOT / "_tile042.png"
    write_png(path, (np.clip(image, 0, 1) * 255).astype(np.uint8))
    return Image.open(path).convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((28, 20), "ФОРМА 3D 0.42 — плоскости, срезы и топология",
              font=F_TITLE, fill=(240, 243, 248))
    draw.text((28, 56), "независимый верх · параллелограмм · Loop · срез сферы · "
                       "треугольники / квадраты / пятиугольники / сота",
              font=F_TEXT, fill=(120, 128, 144))
    for index, (name, note, script) in enumerate(CASES):
        col, row = index % COLS, index // COLS
        x, y = col * TILE, HEAD + row * (TILE + PAD)
        sheet.paste(shot(script), (x, y))
        draw.text((x + 12, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        draw.text((x + 12, y + TILE + 26), note, font=F_TEXT, fill=(128, 136, 150))
        if col:
            draw.line([(x, HEAD), (x, height)], fill=(30, 34, 42))
    output = ROOT / "whatsnew_042.png"
    sheet.save(output)
    (ROOT / "_tile042.png").unlink(missing_ok=True)
    print("сохранено:", output, sheet.size)


if __name__ == "__main__":
    main()
