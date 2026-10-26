"""Визуальная приёмка 0.48: девять сцен из исполняемых текстовых сценариев.

Запуск из forma/: PYTHONPATH=. python docs/make_whatsnew_048.py
Результат: docs/whatsnew_048.png и отдельные виды в /tmp/forma048_acceptance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import export_glb, write_png
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parent
OUT = Path("/tmp/forma048_acceptance")
FONTS = Path("/usr/share/fonts/truetype/dejavu")
TILE, PAD, HEAD = 420, 58, 92
COLS = ROWS = 3
DARK_BG = (0.055, 0.062, 0.075)


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = font("DejaVuSans-Bold.ttf", 27)
F_NAME = font("DejaVuSans-Bold.ttf", 17)
F_TEXT = font("DejaVuSans.ttf", 14)

CASES = [
    ("Полости-лодочки", "смещённый контур · открытая сторона · дно", "iso",
     "полу = полуовал width=120 height=70 thickness=20 wall=3 cavity_depth=15 plane=плашмя at=[-75,0,0]\n"
     "сектор = pie diameter=120 angle=210 thickness=20 wall=3 cavity_depth=15 at=[75,0,0]\n"
     "color полу #d8a95f\ncolor сектор #68a8c8"),
    ("Глазное яблоко", "склера · радужка · зрачок · прозрачная роговица", "iso",
     "глаз = eyeball diameter=30 iris=13 pupil=5.2 bulge=.8 iris_color=#4b8b7b"),
    ("Капсульная паутина", "круг и сектор · настоящие сквозные ячейки", "top",
     "круг = web shape=круг radius=55 radials=12 rings=5 wire=.8 sag=.14 at=[-65,0,0]\n"
     "сектор = web shape=сектор radius=55 angle=230 radials=9 rings=4 wire=.8 at=[65,0,0]\n"
     "color круг #d9e4ef\ncolor сектор #e2b86a"),
    ("Крыло и плавник", "рёбра · мембрана · вогнутые промежутки", "iso",
     "крыло = web shape=крыло radius=75 angle=145 radials=7 scallop=.38 at=[-55,0,0]\n"
     "плавник = web shape=плавник radius=60 angle=105 radials=8 scallop=.3 at=[65,0,0]\n"
     "color крыло #9b647b\ncolor плавник #5f9ea6"),
    ("Shrinkwrap", "проекция сетки · gap=.6 · толщина сохранена", "iso",
     "цель = sphere radius=24\n"
     "плёнка = box size=[29,29,2] at=[0,0,24]\n"
     "color цель #6686a0\ncolor плёнка #d7765f\n"
     "плёнка = shrinkwrap [цель,плёнка] gap=.6 direction=вниз detail=2"),
    ("Горка люверса", "прямой уступ → вогнутый переход", "iso",
     "прямой = grommet diameter=12 height=10 wall=1.6 flange=4 at=[-18,0,0]\n"
     "горка = grommet diameter=12 height=10 wall=1.6 flange=4 transition=вогнутая transition_h=5 at=[18,0,0]\n"
     "color прямой #b9c2cf\ncolor горка #d7a757"),
    ("Поворот ступеней", "каждая проступь вокруг своего центра", "iso",
     "прямой = stairs steps=5 rise=16 run=24 width=80 at=[-105,0,0]\n"
     "поворот = stairs steps=5 rise=16 run=24 width=80 turn=30 at=[105,0,0]\n"
     "color прямой #8d9dad\ncolor поворот #d39a58"),
    ("Рыбья чешуя", "плоский веер · наклон · перекрытие корня", "iso",
     "рыба = sphere radius=34\n"
     "color рыба #5f9eaa\n"
     "scales рыба kind=рыба rows=9 per_row=15 length=7 tilt=18 overlap=.45"),
    ("Драконья чешуя", "острые пластинки · не выпуклые капли", "iso",
     "дракон = sphere radius=34\n"
     "color дракон #9b6b4f\n"
     "scales дракон kind=дракон rows=9 per_row=15 length=7 tilt=28 overlap=.45"),
]


def shot(script: str, view: str, index: int):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error))
    solids = [o for o in result.scene.objects.values() if o.visible]
    for solid in solids:
        if solid.manifold.is_empty() or solid.manifold.volume() <= 0:
            raise SystemExit(f"Пустое тело в сцене {index}: {solid.name}")
    meshes = _prepare(solids, result.scene.groups)
    vertices = np.concatenate([m["verts"] for m in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 * 1.08
    image, _ = _render_view(meshes, center, radius, view, TILE, 2,
                            [*lo, *hi], grid=False, shadow=True,
                            bg=DARK_BG, style=None)
    path = OUT / f"{index:02d}_{view}.png"
    write_png(path, (np.clip(image, 0, 1) * 255).astype(np.uint8))
    (OUT / f"{index:02d}_scene.glb").write_bytes(export_glb(solids))
    return Image.open(path).convert("RGB"), len(solids)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((28, 18), "ФОРМА 3D 0.48 — полости, проекция и перекрытия",
              font=F_TITLE, fill=(240, 243, 248))
    draw.text((28, 58), "глазное яблоко · Shrinkwrap · капсульная паутина · "
                       "мембраны · вогнутая горка · плоская чешуя",
              font=F_TEXT, fill=(120, 128, 144))
    total = 0
    for index, (name, note, view, script) in enumerate(CASES, 1):
        image, count = shot(script, view, index)
        total += count
        col, row = (index - 1) % COLS, (index - 1) // COLS
        x, y = col * TILE, HEAD + row * (TILE + PAD)
        sheet.paste(image, (x, y))
        draw.text((x + 12, y + TILE + 4), name, font=F_NAME, fill=(232, 236, 244))
        draw.text((x + 12, y + TILE + 27), note, font=F_TEXT, fill=(128, 136, 150))
        if col:
            draw.line([(x, HEAD), (x, height)], fill=(30, 34, 42))
    output = ROOT / "whatsnew_048.png"
    sheet.save(output)
    print("сохранено:", output, sheet.size, "тел в сценах:", total)


if __name__ == "__main__":
    main()
