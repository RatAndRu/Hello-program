"""Плакат 0.32: инструменты скульпта — как руками по поверхности.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_whatsnew_032.py

Результат — docs/whatsnew_032.png: сетка 4 × 3, подписи по-русски. Каждая
плитка — настоящая сцена, построенная текстовым сценарием, а не рисунок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.anime import normalize_style
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

TILE = 330
PAD = 52
HEAD = 88
COLS, ROWS = 4, 3
DARK_BG = (0.055, 0.062, 0.075)
PAPER_BG = (0.965, 0.955, 0.925)

ANIME = load_example("anime_face")

# (подпись, мелкая подпись, сценарий, вид, приближение, сдвиг камеры)
CASES = [
    ("полигонаж", "слева 12 трис — справа после refine",
     "грубая = box size=[54,46,10] at=[-34,0,0]\n"
     "грубая = dent [грубая] at=[-34,0,10] depth=5 radius=13 soft=0.7\n"
     "мелкая = box size=[54,46,10] at=[34,0,0]\n"
     "мелкая = refine [мелкая] length=1.2\n"
     "мелкая = dent [мелкая] at=[34,0,10] depth=5 radius=13 soft=0.7\n"
     "color грубая color=#ccd3e2\ncolor мелкая color=#ccd3e2", "iso", 1.0, (0, 0, 0.1)),
    ("вмятина от удара", "мягко: край широкий, валик мал",
     "ш = sphere radius=34 segments=48\n"
     "ш = dent [ш] at=[0,0,34] depth=11 radius=18 soft=0.85 rim=0.2", "iso", 1.05, (0, 0, 0.3)),
    ("жёсткая вмятина", "твёрдо: пятно уже, металл вспух",
     "к = box size=[58,58,58] round=4\n"
     "к = dent [к] at=[0,0,58] depth=7 radius=13 soft=0.15 rim=0.15", "iso", 1.0, (0, 0, 0.3)),
    ("выдувание объёма", "стеклодув: растёт вдоль нормалей",
     "ц = cylinder radius=9 height=62 segments=48\n"
     "ц = blow [ц] at=[0,0,62] radius=34 height=22 soft=0.55", "iso", 1.0, None),
    ("щипок", "сжали по X — материал вышел вбок",
     "ш = sphere radius=32 segments=48\n"
     "ш = pinch [ш] axis=z amount=0.35 radius=22 bulge=0.6", "iso", 1.0, None),
    ("отсечение плоскостью", "вся часть за плоскостью удалена",
     "б = box size=[54,54,88] round=3\n"
     "б = cut_plane [б] at=[0,0,88] dir=[0,0.55,1] depth=20", "iso", 1.0, None),
    ("заострение", "как точилка: конус с торца",
     "к = cylinder radius=9 height=88 segments=48\n"
     "к = point [к] length=26", "iso", 1.0, None),
    ("сверление: конус и зенковка", "дно 118°, вход расширен",
     "п = box size=[80,70,24] round=2\n"
     "п = bore [п] at=[-19,0,24] diameter=18 depth=15 tip=конус countersink=6\n"
     "п = bore [п] at=[21,0,24] diameter=18 depth=15 tip=сфера", "top", 1.0, None),
    ("разровнять в плоскость", "участок лёг ровно, переход мягкий",
     "ш = sphere radius=32 segments=64\n"
     "ш = flatten [ш] at=[0,0,22] radius=30 strength=1 soft=0.6", "iso", 1.0, None),
    ("разгладить", "шероховатость ушла, форма осталась",
     "ш = sphere radius=30 segments=48\n"
     "ш = wrinkle [ш] amp=1.0 freq=80 mode=шум\n"
     "ш = polish [ш] passes=20 strength=1", "iso", 1.0, None),
    ("острая складка", "sharp=1: ребро жёсткое, слои рядом",
     "л = sheet width=120 length=190 thickness=1\n"
     "fold л parts=2 angle=90 gap=2 sharp=1\n"
     "л = rotate [л] angle=0 axis=z", "iso", 1.1, None),
    ("аниме-портрет на плоскости", "контуры лица слоями, один объём",
     ANIME, "top", 1.0, None),
]


def shot(script: str, view: str, zoom: float, focus):
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
    style = normalize_style(b.scene.settings.get("anime"))
    bg = PAPER_BG if style is not None else DARK_BG
    img, _ = _render_view(meshes, c, r, view, TILE, 2, [*lo, *hi], grid=False,
                          shadow=style is None, bg=bg, style=style)
    write_png(ROOT / "_tile.png", (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(ROOT / "_tile.png").convert("RGB")


def main() -> None:
    width = TILE * COLS
    height = HEAD + ROWS * (TILE + PAD)
    sheet = Image.new("RGB", (width, height), (13, 15, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((28, 20), "ФОРМА 3D 0.32 — инструменты скульпта",
            font=F_TITLE, fill=(240, 243, 248))
    dr.text((28, 56), "полигонаж · стёсывание · выдувание · сверление с формой дна · "
                      "острая складка · вмятины · разровнять · разгладить · щипок",
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

    out = ROOT / "whatsnew_032.png"
    sheet.save(out)
    (ROOT / "_tile.png").unlink(missing_ok=True)
    print("сохранено:", out, sheet.size)


if __name__ == "__main__":
    main()
