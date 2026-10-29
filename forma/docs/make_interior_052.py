"""Визуальная приёмка 0.52: интерьерные сборки и ткань.

Запуск из forma/: PYTHONPATH=. python docs/make_interior_052.py
Нужны numpy, manifold3d и Pillow. Результат: docs/interior_052.png.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
OUT = Path("/tmp/forma052_interior")
FONTS = Path("/usr/share/fonts/truetype/dejavu")
TILE, PAD, HEAD = 420, 52, 112
COLS, ROWS = 3, 3
DARK_BG = (0.055, 0.062, 0.075)

F_TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 29)
F_SUBTITLE = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 16)
F_NAME = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 17)
F_TEXT = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 13)

CASES = [
    ("Стол", "столешница · 4 ножки · полка · splay=5", "iso",
     "стол = table width=180 length=100 height=75 shape=rounded corner=10 legs=4 splay=5 shelf=да"),
    ("Дверь", "полотно открыто на 35° · коробка неподвижна", "iso",
     "door = door width=90 height=210 panels=4 columns=2\n"
     "rotate [door.leaf] angle=35 axis=z pivot=[-44.4,-2.25,0]"),
    ("Штора", "объёмные складки · толщина · отдельные кольца", "iso",
     "штора = curtain width=140 height=220 folds=8 fold_depth=7 wave=2"),
    ("Ковёр", "кайма · узор · стежки · бахрома · поднятый угол", "iso",
     "ковёр = rug width=180 length=120 pattern=полосы wave=0.5 lift=8 fringe=ends"),
    ("Розетка", "2 места · сквозные отверстия · заземление", "iso",
     "розетка = socket sockets=2 ground=да screws=да"),
    ("Выключатель", "2 клавиши · наклон state=on · подсветка", "iso",
     "выключатель = switch rockers=2 state=on angle=8 led=да"),
    ("Лампочка E27", "полое стекло · спиральная резьба · контакт", "iso",
     "лампа = bulb shape=a60 base=E27 thread=да glow=да glow_strength=3"),
    ("Драпировка", "гравитация · длины · контакт · свободные края", "iso",
     "ткань = box size=[140,110,0.4] at=[0,0,35]\n"
     "опора = box size=[90,70,20] at=[0,0,0]\n"
     "скатерть = drape [ткань] on=опора detail=24 iterations=60 constraints=8"),
    ("Отдельные копии", "2 прототипа · pack · цвет и редактирование сохранены", "iso",
     "a = box size=[12,22,30] color=#b34c3f\n"
     "b = box size=[15,22,38] color=#3c718a\n"
     "опора = box size=[150,38,3]\n"
     "ряд = array [a,b] mode=pack on=опора count=8 gap=2 inset=4 as=objects seed=4"),
]


def shot(script: str, view: str, index: int) -> Image.Image:
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error))
    solids = result.visible_solids()
    for solid in solids:
        if solid.manifold.is_empty() or solid.manifold.volume() <= 0:
            raise SystemExit(f"Пустое тело в сцене {index}: {solid.name}")
    meshes = _prepare(solids, result.scene.groups)
    vertices = np.concatenate([mesh["verts"] for mesh in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08
    image, _ = _render_view(meshes, center, radius, view, TILE, 2,
                            [*lo, *hi], grid=False, shadow=True,
                            bg=DARK_BG, style=None)
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / f"{index:02d}_{view}.png",
              (np.clip(image, 0, 1) * 255).astype(np.uint8))
    return Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8), "RGB")


def main() -> None:
    width = COLS * TILE + (COLS + 1) * PAD
    height = HEAD + ROWS * (TILE + 66) + (ROWS + 1) * PAD
    canvas = Image.new("RGB", (width, height), (17, 22, 29))
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, 27), "ФОРМА 3D 0.52 — интерьер, копии и ткань",
              font=F_TITLE, fill=(237, 242, 249))
    draw.text((PAD, 70), "Отдельные редактируемые тела; живые параметры; никаких импортированных моделей.",
              font=F_SUBTITLE, fill=(158, 174, 192))
    for index, (title, subtitle, view, script) in enumerate(CASES):
        row, col = divmod(index, COLS)
        x = PAD + col * (TILE + PAD)
        y = HEAD + PAD + row * (TILE + 66 + PAD)
        canvas.paste(shot(script, view, index + 1), (x, y))
        draw.text((x + 3, y + TILE + 12), title, font=F_NAME, fill=(230, 236, 244))
        draw.text((x + 3, y + TILE + 39), subtitle, font=F_TEXT, fill=(147, 163, 181))
    canvas.save(ROOT / "interior_052.png", optimize=True)
    print(ROOT / "interior_052.png")


if __name__ == "__main__":
    main()
