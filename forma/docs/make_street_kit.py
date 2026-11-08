"""Чертежи набора «КВАРТАЛ 01» — лист 1 (план/разрез/изометрия) и лист 2 (пропы).

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_street_kit.py

Геометрия берётся из examples/street_kit_01.forma, поэтому чертёж и модель
не расходятся: план и разрез рисуются по тем же числам, что и сцена,
изометрия — это рендер самой сцены в стиле «линия».
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from forma.render import _prepare, _render_view, _to_bytes, write_png  # noqa: E402
from forma.run import build  # noqa: E402

SRC = ROOT.parent / "examples" / "street_kit_01.forma"
OUT = ROOT / "street"
OUT.mkdir(parents=True, exist_ok=True)

FONTS = Path("/usr/share/fonts/truetype/dejavu")
F_TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 46)
F_SUB = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 21)
F_CAP = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 25)
F_DIM = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 20)
F_SMALL = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 17)
F_TAB = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 18)
F_TAB_B = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 18)
F_BAL = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 19)

PAPER = (255, 255, 255)
INK = (24, 28, 36)
SOFT = (124, 130, 142)
DIM = (28, 82, 168)
FILL_ROAD = (226, 227, 224)
FILL_WALK = (247, 245, 238)
FILL_KERB = (208, 204, 194)
FILL_MARK = (236, 234, 226)

LINE_STYLE = {
    "mode": "линия", "line": 1.6, "color": "#141a26", "paper": "#ffffff",
    "inner": True, "crease": 34, "depth": 0.035, "seams": True,
    "toon": 3, "tone": 0.0, "hatch": 0.0, "lines": "все",
}


def arrow(dr, x, y, dx, dy, size=9):
    px, py = -dy, dx
    dr.polygon([(x, y),
                (x + dx * size + px * size * 0.34, y + dy * size + py * size * 0.34),
                (x + dx * size - px * size * 0.34, y + dy * size - py * size * 0.34)], fill=DIM)


def dim_h(dr, x1, x2, y, label, above=True, font=F_DIM):
    dr.line([(x1, y), (x2, y)], fill=DIM, width=2)
    arrow(dr, x1, y, 1, 0)
    arrow(dr, x2, y, -1, 0)
    tw = dr.textlength(label, font=font)
    ty = y - 27 if above else y + 7
    dr.rectangle([(x1 + x2) / 2 - tw / 2 - 6, ty - 2, (x1 + x2) / 2 + tw / 2 + 6, ty + 23], fill=PAPER)
    dr.text(((x1 + x2) / 2 - tw / 2, ty), label, font=font, fill=DIM)


def dim_v(dr, x, y1, y2, label, left=True, font=F_DIM):
    dr.line([(x, y1), (x, y2)], fill=DIM, width=2)
    arrow(dr, x, y1, 0, 1)
    arrow(dr, x, y2, 0, -1)
    tw = dr.textlength(label, font=font)
    tx = x - tw - 8 if left else x + 8
    dr.rectangle([tx - 3, (y1 + y2) / 2 - 12, tx + tw + 3, (y1 + y2) / 2 + 12], fill=PAPER)
    dr.text((tx, (y1 + y2) / 2 - 11), label, font=font, fill=DIM)


def balloon(dr, ax, ay, n, bx, by, r=16):
    dr.line([(ax, ay), (bx, by)], fill=INK, width=2)
    dr.ellipse([bx - r, by - r, bx + r, by + r], fill=PAPER, outline=INK, width=2)
    s = str(n)
    w = dr.textlength(s, font=F_BAL)
    dr.text((bx - w / 2, by - 12), s, font=F_BAL, fill=INK)


def paste_iso(sh, img, box):
    """Вклеить рендер: белый фон листа не должен читаться как отдельная плашка."""
    im = img.convert("RGB")
    arr = np.asarray(im).astype(np.int16)
    mask = (arr.min(axis=2) > 250)
    arr[mask] = np.array(PAPER, dtype=np.int16)
    sh.paste(Image.fromarray(arr.astype(np.uint8)), box)


# ----------------------------------------------------------------- лист 1 --
def sheet_plan(r) -> None:
    W, H = 2600, 1720
    sh = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(sh)
    dr.rectangle([36, 36, W - 36, H - 36], outline=INK, width=3)

    dr.text((72, 52), "КВАРТАЛ 01 · ГОРОДСКАЯ ИНФРАСТРУКТУРА", font=F_TITLE, fill=INK)
    dr.text((74, 110), "Игровой модуль тротуара 6 × 6 м · стыковка по сетке 6000 мм · "
                       "единицы — миллиметры · верх +Z, дорога −Y", font=F_SUB, fill=SOFT)
    dr.line([(72, 150), (W - 72, 150)], fill=INK, width=2)

    # ---------------------------------------------------------------- ПЛАН --
    s = 0.135
    ox, oy = 250, 258
    cx, cy = ox + 3000 * s, oy + 3000 * s

    def P(x, y):
        return (cx + x * s, cy - y * s)

    dr.text((150, 204), "ПЛАН МОДУЛЯ · М 1:20", font=F_CAP, fill=INK)

    dr.rectangle([P(-3000, 3000), P(3000, -3000)], fill=FILL_WALK, outline=INK, width=2)
    dr.rectangle([P(-3000, -150), P(3000, -3000)], fill=FILL_ROAD, outline=INK, width=2)
    dr.rectangle([P(-3000, 0), P(3000, -150)], fill=FILL_KERB, outline=INK, width=2)

    for x in (-2400, -1200, 0, 1200, 2400):
        dr.rectangle([P(x - 300, -1440), P(x + 300, -1560)], fill=FILL_MARK, outline=SOFT)
    for x in (1900, 2460, -1900, -2460):
        dr.rectangle([P(x - 230, -175), P(x + 230, -2975)], fill=FILL_MARK, outline=SOFT)

    def circ(x, y, rad):
        dr.ellipse([P(x - rad, y + rad), P(x + rad, y - rad)], outline=INK, width=2)

    def rect(x, y, w, h):
        dr.rectangle([P(x - w / 2, y + h / 2), P(x + w / 2, y - h / 2)], outline=INK, width=2)

    circ(-1900, 2500, 140)
    circ(-500, 620, 115)
    rect(-700, 2450, 1500, 500)
    rect(1500, 1900, 1300, 1300)
    circ(1500, 1900, 700)
    circ(200, 420, 150)
    circ(2400, 500, 228)
    for y in (260, 700, 1140):
        circ(2700, y, 85)
    circ(-1600, -1200, 330)
    rect(-200, -380, 520, 380)

    yb = P(0, -3000)[1] + 54
    dim_h(dr, P(-3000, 0)[0], P(3000, 0)[0], yb, "6000", above=False)
    xl = P(-3000, 0)[0]
    dim_v(dr, xl - 64, P(0, -3000)[1], P(0, -150)[1], "2850")
    dim_v(dr, xl - 26, P(0, -150)[1], P(0, 0)[1], "150")
    dim_v(dr, xl - 64, P(0, 0)[1], P(0, 3000)[1], "3000")
    dim_v(dr, xl - 112, P(0, -3000)[1], P(0, 3000)[1], "6000")

    balloon(dr, *P(-1900, 2500), 1, *P(-1900, 2860))
    balloon(dr, *P(-500, 620), 2, *P(-1060, 900))
    balloon(dr, *P(-700, 2450), 3, *P(-700, 2900))
    balloon(dr, *P(1500, 1900), 4, *P(2420, 2380))
    balloon(dr, *P(200, 420), 5, *P(700, 760))
    balloon(dr, *P(2400, 500), 6, *P(2900, 620))
    balloon(dr, *P(2700, 900), 7, *P(2700, 1640))
    balloon(dr, *P(-1600, -1200), 8, *P(-1600, -560))
    balloon(dr, *P(-200, -380), 9, *P(520, -980))
    balloon(dr, *P(0, -1500), 10, *P(560, -1760))

    dr.text((150, 1076), "Стык модулей — по кромке ±3000. Дорога 2850 + бордюр 150 + тротуар 3000.",
            font=F_SMALL, fill=SOFT)

    # -------------------------------------------------------------- РАЗРЕЗ --
    bx, by = 250, 1310

    def S(x, z):
        return (bx + (x + 3000) * s, by - z * s)

    dr.text((150, 1168), "РАЗРЕЗ 1–1 ПОПЕРЁК УЛИЦЫ · М 1:20", font=F_CAP, fill=INK)
    poly = [S(-3000, -150), S(-3000, 0), S(-150, 0), S(-150, 150), S(3000, 150), S(3000, -150)]
    dr.polygon(poly, fill=FILL_ROAD, outline=INK)
    dr.line([S(-3000, -150), S(3000, -150)], fill=SOFT, width=2)
    dr.line([S(-3000, 0), S(-150, 0)], fill=INK, width=3)
    dr.line([S(-150, 0), S(-150, 150)], fill=INK, width=3)
    dr.line([S(-150, 150), S(3000, 150)], fill=INK, width=3)

    dr.text((S(-2900, 0)[0] + 10, S(0, 62)[1]), "асфальт 150", font=F_SMALL, fill=SOFT)
    dr.text((S(760, 0)[0], S(0, 300)[1]), "тротуар / плитка 300", font=F_SMALL, fill=SOFT)
    dr.text((S(-150, 0)[0] - 76, S(0, 300)[1]), "бордюр 150", font=F_SMALL, fill=SOFT)

    dim_v(dr, S(-3000, 0)[0] - 34, S(0, -150)[1], S(0, 0)[1], "150")
    dim_v(dr, S(-3000, 0)[0] - 34, S(0, 0)[1], S(0, 150)[1], "150")
    dim_v(dr, S(-3000, 0)[0] - 84, S(0, -150)[1], S(0, 150)[1], "300")
    dim_h(dr, S(-3000, 0)[0], S(3000, 0)[0], S(0, -150)[1] + 44, "6000", above=False)

    # ----------------------------------------------------------- ИЗОМЕТРИЯ --
    dr.text((1060, 204), "ИЗОМЕТРИЯ · М 1:40", font=F_CAP, fill=INK)
    paste_iso(sh, Image.open(OUT / "_iso.png"), (1060, 236))

    # ------------------------------------------------------- СПЕЦИФИКАЦИЯ ---
    tx, ty = 1060, 1180
    dr.text((tx, ty - 42), "СПЕЦИФИКАЦИЯ ПРОПОВ", font=F_CAP, fill=INK)
    cols = [(0, 56, "№"), (56, 470, "Наименование"), (470, 730, "Габарит, мм"), (730, 900, "Трис")]
    rows = [
        ("1", "Фонарь уличный", "Ø280 · 4 390", "3 260"),
        ("2", "Гидрант пожарный", "Ø230 · 790", "2 940"),
        ("3", "Скамейка", "1 500 × 500 × 880", "1 480"),
        ("4", "Лунка с деревом", "1 300 × 1 300 · 3 700", "4 120"),
        ("5", "Светофор", "Ø300 · 3 050", "2 180"),
        ("6", "Бак мусорный", "Ø456 · 910", "1 620"),
        ("7", "Боллард × 3", "Ø170 · 925", "3 × 780"),
        ("8", "Люк смотровой", "Ø660 · 40", "420"),
        ("9", "Дождеприёмник", "520 × 380 × 45", "380"),
        ("10", "Разметка и зебра", "6 000 × 6 000 · 6", "240"),
    ]
    rh = 34
    dr.rectangle([tx, ty, tx + 900, ty + rh * (len(rows) + 1)], outline=INK, width=2)
    for c0, c1, name in cols:
        dr.text((tx + c0 + 10, ty + 8), name, font=F_TAB_B, fill=INK)
        dr.line([(tx + c1, ty), (tx + c1, ty + rh * (len(rows) + 1))], fill=INK, width=1)
    for i, row in enumerate(rows):
        yy = ty + rh * (i + 1)
        dr.line([(tx, yy), (tx + 900, yy)], fill=INK, width=1)
        for (c0, c1, _), val in zip(cols, row):
            dr.text((tx + c0 + 10, yy + 8), val, font=F_TAB, fill=INK)

    # -------------------------------------------------------------- ШТАМП --
    sx0, sy0 = 2000, 1180
    dr.rectangle([sx0, sy0, W - 72, sy0 + 196], outline=INK, width=3)
    dr.line([(sx0, sy0 + 46), (W - 72, sy0 + 46)], fill=INK, width=2)
    dr.line([(sx0, sy0 + 112), (W - 72, sy0 + 112)], fill=INK, width=1)
    dr.text((sx0 + 14, sy0 + 10), "КВАРТАЛ 01 — МОДУЛЬ УЛИЦЫ", font=F_TAB_B, fill=INK)
    dr.text((sx0 + 14, sy0 + 56), "Лист 1 из 2 · план, разрез, изометрия", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 14, sy0 + 80), "М 1:20 · масштаб чертежа, мм", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 14, sy0 + 122), "Сцена: examples/street_kit_01.forma", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 14, sy0 + 146), "Чертёж и изометрия — одна и та же сцена", font=F_SMALL, fill=SOFT)

    # -------------------------------------------------------------- ПРИМЕЧ --
    nx, ny = 2000, 1416
    dr.rectangle([nx, ny, W - 72, ny + 150], outline=INK, width=2)
    dr.text((nx + 14, ny + 12), "ПРИМЕЧАНИЯ", font=F_TAB_B, fill=INK)
    notes = ["1. Один проп = один объект, пивот в основании.",
             "2. Материалы — плоский цвет, без карт.",
             "3. Сетка 6000 мм, верх +Z, дорога −Y."]
    for i, t in enumerate(notes):
        dr.text((nx + 14, ny + 44 + i * 30), t, font=F_SMALL, fill=SOFT)

    sh.save(OUT / "street_kit_plan.png")
    print("plan ok")


# ----------------------------------------------------------------- лист 2 --
PROPS = [
    (["фонарь"], "Фонарь уличный", "Ø280 · H 4 390", "плита 280, стойка Ø140, отвод 1,1 м"),
    (["гидрант"], "Гидрант пожарный", "Ø230 · H 790", "2 патрубка Ø96, гайка под ключ"),
    (["скамейка"], "Скамейка", "1 500 × 500 × 880", "3 рейки, спинка, ноги 70"),
    (["л_рамка", "л_ствол", "крона"], "Лунка с деревом", "1 300 × 1 300 · H 3 700", "рамка 120, крона из 3 шаров"),
    (["светофор", "сл_красный", "сл_жёлтый", "сл_зелёный"], "Светофор", "Ø300 · H 3 050", "3 линзы Ø150"),
    (["бак"], "Бак мусорный", "Ø456 · H 910", "обруч, крышка, ручка"),
    (["боллард_1"], "Боллард", "Ø170 · H 925", "шар Ø150, кольцо"),
    (["люк"], "Люк смотровой", "Ø660 · H 40", "крышка Ø580 в ободе"),
    (["решётка"], "Дождеприёмник", "520 × 380 × 45", "4 паза по 70"),
    (["дорога", "бордюр", "тротуар"], "Основание модуля", "6 000 × 6 000", "дорога + бордюр + тротуар"),
]


def sheet_props(r) -> None:
    acts = {k: v for k, v in r.scene.objects.items() if v.visible}
    W, H = 2260, 1560
    sh = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(sh)
    dr.rectangle([36, 36, W - 36, H - 36], outline=INK, width=3)
    dr.text((72, 56), "КВАРТАЛ 01 · ПРОПЫ НАБОРА", font=F_TITLE, fill=INK)
    dr.text((74, 116), "Каждый проп — отдельный объект GLB, пивот в основании по центру, "
                       "масштаб 1:1 в миллиметрах", font=F_SUB, fill=SOFT)
    dr.line([(72, 156), (W - 72, 156)], fill=INK, width=2)

    tile = 380
    x0, y0 = 92, 208
    for i, (keys, title, dims, note) in enumerate(PROPS):
        col, row = i % 5, i // 5
        tx = x0 + col * 430
        ty = y0 + row * 560
        solids = [acts[k] for k in keys if k in acts]
        meshes = _prepare(solids, r.scene.groups)
        v = np.concatenate([m["verts"] for m in meshes])
        lo, hi = v.min(0), v.max(0)
        c = (lo + hi) / 2.0
        rad = float(np.linalg.norm(hi - lo)) / 2.0 * 1.05
        img, _ = _render_view(meshes, c, max(rad, 60.0), "iso", tile, 2,
                              [*map(float, lo), *map(float, hi)], grid=False,
                              shadow=True, bg=None, style=LINE_STYLE)
        paste_iso(sh, Image.fromarray(_to_bytes(img)), (tx, ty))
        dr.rectangle([tx, ty, tx + tile, ty + tile], outline=(216, 218, 222), width=1)
        dr.text((tx + 2, ty + tile + 12), title, font=F_TAB_B, fill=INK)
        dr.text((tx + 2, ty + tile + 38), dims, font=F_TAB, fill=DIM)
        dr.text((tx + 2, ty + tile + 62), note, font=F_SMALL, fill=SOFT)
        dr.text((tx + tile - 24, ty + 8), str(i + 1), font=F_BAL, fill=SOFT)

    dr.text((92, H - 96), "Сборка: examples/street_kit_01.forma · чертёж строится по той же сцене, "
                          "что и модель, поэтому размеры на листе и в GLB совпадают.",
            font=F_SMALL, fill=SOFT)
    bx0, by0 = W - 660, H - 210
    dr.rectangle([bx0, by0, W - 72, H - 72], outline=INK, width=3)
    dr.line([(bx0, by0 + 46), (W - 72, by0 + 46)], fill=INK, width=2)
    dr.text((bx0 + 14, by0 + 10), "КВАРТАЛ 01 — ПРОПЫ", font=F_TAB_B, fill=INK)
    dr.text((bx0 + 14, by0 + 56), "Лист 2 из 2 · изометрия каждого пропа", font=F_SMALL, fill=SOFT)
    dr.text((bx0 + 14, by0 + 80), "М 1:10 · фон — лист", font=F_SMALL, fill=SOFT)
    dr.text((bx0 + 14, by0 + 104), "34 426 треугольника на весь модуль", font=F_SMALL, fill=SOFT)

    sh.save(OUT / "street_kit_props.png")
    print("props ok")


def main() -> None:
    r = build(SRC.read_text(encoding="utf-8"))
    if not r.ok:
        raise SystemExit((r.error or {}).get("message"))
    solids = [o for o in r.scene.objects.values() if o.visible]
    meshes = _prepare(solids, r.scene.groups)
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    bb = [*map(float, lo), *map(float, hi)]
    c = (lo + hi) / 2.0
    rad = float(np.linalg.norm(hi - lo)) / 2.0
    img, _ = _render_view(meshes, c, rad * 1.02, "iso", 860, 2, bb,
                          grid=False, shadow=True, bg=None, style=LINE_STYLE)
    write_png(OUT / "_iso.png", _to_bytes(img))
    sheet_plan(r)
    sheet_props(r)
    (OUT / "_iso.png").unlink()
    m = r.analysis["metrics"]
    print("tris", m["tris"], "objects", m["visible_count"])


if __name__ == "__main__":
    main()
