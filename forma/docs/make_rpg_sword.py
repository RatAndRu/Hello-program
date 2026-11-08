"""Чертежи магического меча «Изумрудная жила» — лист 1 и лист 2.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_rpg_sword.py

Профиль клинка читается из самой сцены examples/rpg_sword_01.forma, поэтому
фасад на чертеже и геометрия в GLB совпадают по числам. Изометрия и крупные
планы — рендер той же сцены в стиле «линия».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from forma.render import _prepare, _render_view, _to_bytes, write_png  # noqa: E402
from forma.run import build  # noqa: E402

SRC = ROOT.parent / "examples" / "rpg_sword_01.forma"
OUT = ROOT / "sword"
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
GOLD = (176, 138, 56)
JADE = (36, 150, 100)

LINE_STYLE = {
    "mode": "линия", "line": 1.6, "color": "#141a26", "paper": "#ffffff",
    "inner": True, "crease": 34, "depth": 0.035, "seams": True,
    "toon": 3, "tone": 0.0, "hatch": 0.0, "lines": "все",
}


# --------------------------------------------------------------- утилиты ---
def rrect(dr, xa, xb, ya, yb, **kw):
    dr.rectangle([min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)], **kw)


def arrow(dr, x, y, dx, dy, size=9):
    px, py = -dy, dx
    dr.polygon([(x, y),
                (x + dx * size + px * size * 0.34, y + dy * size + py * size * 0.34),
                (x + dx * size - px * size * 0.34, y + dy * size - py * size * 0.34)], fill=DIM)


def dim_h(dr, x1, x2, y, label, above=True, font=F_DIM, color=DIM):
    dr.line([(x1, y), (x2, y)], fill=color, width=2)
    arrow(dr, x1, y, 1, 0)
    arrow(dr, x2, y, -1, 0)
    tw = dr.textlength(label, font=font)
    ty = y - 27 if above else y + 7
    dr.rectangle([(x1 + x2) / 2 - tw / 2 - 6, ty - 2, (x1 + x2) / 2 + tw / 2 + 6, ty + 23], fill=PAPER)
    dr.text(((x1 + x2) / 2 - tw / 2, ty), label, font=font, fill=color)


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


def paste_line(sh, img, box=None, scale=1.0):
    im = img.convert("RGB")
    arr = np.asarray(im).astype(np.int16)
    mask = (arr.min(axis=2) > 250)
    arr[mask] = np.array(PAPER, dtype=np.int16)
    im = Image.fromarray(arr.astype(np.uint8))
    if scale != 1.0:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    if box is None:
        box = (0, 0)
    sh.paste(im, box)
    return im


def trim(im):
    arr = np.asarray(im.convert("RGB")).astype(np.int16)
    ink = arr.min(axis=2) < 240
    ys, xs = np.where(ink)
    if len(xs) == 0:
        return im
    return im.crop((max(0, xs.min() - 6), max(0, ys.min() - 6),
                    min(im.width, xs.max() + 7), min(im.height, ys.max() + 7)))


def read_profile():
    """Ширина и толщина клинка по сечениям — прямо из сцены."""
    txt = SRC.read_text(encoding="utf-8")
    block = txt.split("сеч_клинка = [")[1].split("\n]")[0]
    secs = []
    for row in block.strip().splitlines():
        pts = re.findall(r"\[(-?\d+\.?\d*),(-?\d+\.?\d*)\]", row)
        if not pts:
            continue
        xs = [abs(float(a)) for a, _ in pts]
        ys = [abs(float(b)) for _, b in pts]
        secs.append((2 * max(xs), 2 * max(ys)))
    pos = re.search(r"клинок = loft .*positions=\[([^\]]+)\]", txt).group(1)
    zs = [float(v) for v in pos.split(",")]
    return zs, secs


ZS, SEC = read_profile()
W = [s[0] for s in SEC]
T = [s[1] for s in SEC]
TOTAL = ZS[-1]
POM = [(0, 6), (6, 22), (16, 29), (32, 31), (54, 30), (72, 26), (84, 18), (92, 10)]


# ----------------------------------------------------------------- лист 1 --
def sheet_main(r) -> None:
    Wd, H = 2600, 1760
    sh = Image.new("RGB", (Wd, H), PAPER)
    dr = ImageDraw.Draw(sh)
    dr.rectangle([36, 36, Wd - 36, H - 36], outline=INK, width=3)
    dr.text((72, 50), "ИЗУМРУДНАЯ ЖИЛА · МАГИЧЕСКИЙ ПОЛУТОРНЫЙ МЕЧ", font=F_TITLE, fill=INK)
    dr.text((74, 108), "RPG-ассет · общая длина 1 296 мм · клинок-кристалл с золотым ободом · "
                       "единицы — мм · +Z — острие", font=F_SUB, fill=SOFT)
    dr.line([(72, 148), (Wd - 72, 148)], fill=INK, width=2)

    # ---------------------------------------------------------------- ФАСАД --
    k = 0.66
    x0, yax = 150, 420

    def F(z, half_y=0.0):
        return (x0 + (TOTAL - z) * k, yax + half_y * k)

    dr.text((150, 188), "ФАСАД (вид на пласть) · М 1:15", font=F_CAP, fill=INK)

    top = [F(z, w / 2) for z, w in zip(ZS, W)]
    bot = [F(z, -w / 2) for z, w in zip(ZS, W)]
    dr.polygon(top + bot[::-1], fill=(236, 247, 240), outline=INK)

    dr.line(top, fill=GOLD, width=3)
    dr.line(bot, fill=GOLD, width=3)

    # жила по пласти
    vz = [430, 520, 620, 720, 820, 920, 1010, 1090, 1160]
    vx = [0, 9, 5, -4, 6, 3, -5, 3, 0]
    dr.line([(F(z)[0], yax + v * 0.62) for z, v in zip(vz, vx)], fill=(52, 200, 140), width=2)

    # перья гарды (по настоящему пути из сцены)
    qpath = [(6, 342), (42, 352), (80, 355), (110, 347), (130, 330)]
    for sgn in (1, -1):
        dr.line([(F(z)[0], yax + sgn * x * k) for x, z in qpath], fill=(198, 166, 96), width=8, joint="curve")
        dr.line([(F(z)[0], yax + sgn * x * k) for x, z in qpath], fill=(120, 96, 40), width=2, joint="curve")
    # шипы
    for sgn in (1, -1):
        cx, cy = F(330)[0], yax + sgn * 128 * k
        dr.polygon([(cx + 11, cy), (cx, cy - sgn * 11), (cx - 11, cy), (cx, cy + sgn * 11)],
                   fill=(244, 238, 222), outline=INK)
    # экюссон
    gx1, gx2 = F(356)[0], F(316)[0]
    rrect(dr, gx1, gx2, yax - 21 * k, yax + 21 * k, fill=(244, 238, 222), outline=INK, width=2)
    # обойма рикассо
    rx1, rx2 = F(412)[0], F(356)[0]
    rrect(dr, rx1 - 2, rx2 + 2, yax - 9 * k, yax + 9 * k, fill=(246, 241, 226), outline=INK, width=2)
    # рукоять с обмоткой
    gA, gB = F(324)[0], F(92)[0]
    rrect(dr, gB, gA, yax - 18 * k, yax + 18 * k, fill=(240, 232, 220), outline=INK, width=2)
    for i in range(9):
        gx = gB + (gA - gB) * (i + 0.5) / 9
        dr.line([(gx - 6, yax - 19 * k), (gx + 6, yax + 19 * k)], fill=GOLD, width=2)
    rrect(dr, gB - 3, gB + 12, yax - 20 * k, yax + 20 * k, fill=(246, 241, 226), outline=INK)
    rrect(dr, gA - 12, gA + 3, yax - 20 * k, yax + 20 * k, fill=(246, 241, 226), outline=INK)
    # навершие
    pom_top = [(F(z)[0], yax - r * k) for z, r in POM]
    pom_bot = [(F(z)[0], yax + r * k) for z, r in POM]
    dr.polygon(pom_top + pom_bot[::-1], fill=(244, 238, 222), outline=INK)

    # размеры
    dim_h(dr, F(TOTAL)[0], F(356)[0], yax - 158, "940 — клинок")
    dim_h(dr, F(356)[0], F(0)[0], yax - 112, "356 — гарда…пята")
    dim_h(dr, F(TOTAL)[0], F(0)[0], yax + 210, "1 296 — полная длина")
    dim_h(dr, F(324)[0], F(92)[0], yax + 130, "232 — рукоять")
    dim_h(dr, F(92)[0], F(0)[0], yax + 110, "92")
    dim_v(dr, F(356)[0] + 26, yax - 43 * k, yax + 43 * k, "86", left=False)
    dim_v(dr, min(gx1, gx2) - 34, yax - 130 * k, yax + 130 * k, "260")

    # ------------------------------------------------------------ ВИД СБОКУ --
    ky = 0.66
    sy = 700

    def S(z, half_y):
        return (x0 + (TOTAL - z) * ky, sy + half_y * ky)

    dr.text((150, 664), "ВИД СБОКУ (на кромку) · М 1:15", font=F_CAP, fill=INK)
    st = [S(z, t / 2) for z, t in zip(ZS, T)]
    sb = [S(z, -t / 2) for z, t in zip(ZS, T)]
    dr.polygon(st + sb[::-1], fill=(236, 247, 240), outline=INK)
    gx1s, gx2s = S(356, 0)[0], S(316, 0)[0]
    rrect(dr, gx2s, gx1s, sy - 21 * ky, sy + 21 * ky, fill=(244, 238, 222), outline=INK, width=2)
    rrect(dr, S(324, 0)[0], S(92, 0)[0], sy - 19 * ky, sy + 19 * ky, fill=(240, 232, 220), outline=INK, width=2)
    dr.polygon([(S(92, 0)[0], sy - 31 * ky), (S(60, 0)[0], sy - 31 * ky), (S(0, 0)[0], sy),
                (S(60, 0)[0], sy + 31 * ky), (S(92, 0)[0], sy + 31 * ky)], fill=(244, 238, 222), outline=INK)
    dim_v(dr, S(700, 0)[0], sy - 8.4 * ky / 2, sy + 8.4 * ky / 2, "8,4", left=False)
    dim_v(dr, S(1200, 0)[0] + 18, sy - 3.4 * ky / 2, sy + 3.4 * ky / 2, "3,4", left=False)
    dim_v(dr, min(gx1s, gx2s) - 44, sy - 21 * ky, sy + 21 * ky, "42")


    # ----------------------------------------------------------- СЕЧЕНИЯ ----
    dr.text((150, 800), "СЕЧЕНИЯ КЛИНКА · 4,2:1", font=F_CAP, fill=INK)
    for i, (zi, label) in enumerate([(0, "А–А · у пяты"), (6, "Б–Б · середина")]):
        w, t = W[zi], T[zi]
        kk = 4.2
        cx, cy = 300 + i * 400, 862
        hw, ht = w / 2 * kk, max(t / 2 * kk, 9)
        fh = 0.40 * hw
        pts = [(cx - hw, cy), (cx - fh, cy - ht), (cx + fh, cy - ht), (cx + hw, cy),
               (cx + fh, cy + ht), (cx - fh, cy + ht)]
        dr.polygon(pts, fill=(236, 247, 240), outline=INK)
        dr.text((cx - 52, cy + 54), label, font=F_SMALL, fill=SOFT)
        dim_h(dr, cx - hw, cx + hw, cy + 96, f"{w:.0f}", above=False, font=F_SMALL)
        dim_v(dr, cx + hw + 22, cy - ht, cy + ht, f"{t:.1f}", left=False, font=F_SMALL)

    # ---------------------------------------------------------- ИЗОМЕТРИЯ --
    dr.text((1090, 200), "ИЗОМЕТРИЯ · М 1:15", font=F_CAP, fill=INK)
    iso = trim(Image.open(OUT / "_iso.png"))
    sc = min(720 / iso.width, 1180 / iso.height)
    paste_line(sh, iso, box=(1120 + int((720 - iso.width * sc) / 2), 250), scale=sc)

    # ------------------------------------------------------- СПЕЦИФИКАЦИЯ ---
    tx, ty = 1856, 200
    dr.text((tx, ty - 40), "СОСТАВ ИЗДЕЛИЯ", font=F_CAP, fill=INK)
    rows = [
        ("1", "Клинок-кристалл", "940 × 86 × 10 → ост.", "кристалл"),
        ("2", "Обод кромки", "2 шт., Ø4,8", "золото"),
        ("3", "Жила светящаяся", "2 шт., Ø3,0", "эмиссия"),
        ("4", "Обойма рикассо", "92 × 18 × 56", "золото"),
        ("5", "Экюссон", "84 × 42 × 26", "золото"),
        ("6", "Лангеты", "2 шт., 28 × 4 × 62", "золото"),
        ("7", "Перо гарды", "2 шт., вылет 130", "золото"),
        ("8", "Шип гранёный", "2 шт., Ø24", "золото"),
        ("9", "Кабошон", "4 шт., Ø14…18", "эмиссия"),
        ("10", "Рукоять", "232, Ø31 в талии", "кожа"),
        ("11", "Обмотка", "9 витков, Ø4,2", "шнур"),
        ("12", "Феррулы", "2 шт., Ø41 × 14", "золото"),
        ("13", "Навершие", "Ø62 × 92, 8 граней", "золото"),
    ]
    cols = [(0, 44, "№"), (44, 300, "Деталь"), (300, 516, "Размер, мм"), (516, 704, "Материал")]
    rh = 33
    dr.rectangle([tx, ty, tx + 704, ty + rh * (len(rows) + 1)], outline=INK, width=2)
    for c0, c1, name in cols:
        dr.text((tx + c0 + 8, ty + 7), name, font=F_TAB_B, fill=INK)
        dr.line([(tx + c1, ty), (tx + c1, ty + rh * (len(rows) + 1))], fill=INK, width=1)
    for i, row in enumerate(rows):
        yy = ty + rh * (i + 1)
        dr.line([(tx, yy), (tx + 704, yy)], fill=INK, width=1)
        for (c0, c1, _), val in zip(cols, row):
            dr.text((tx + c0 + 8, yy + 7), val, font=F_TAB, fill=INK)

    # -------------------------------------------------------------- ШТАМП --
    sx0, sy0 = tx, ty + rh * (len(rows) + 1) + 34
    dr.rectangle([sx0, sy0, tx + 704, sy0 + 170], outline=INK, width=3)
    dr.line([(sx0, sy0 + 44), (tx + 704, sy0 + 44)], fill=INK, width=2)
    dr.text((sx0 + 12, sy0 + 9), "ИЗУМРУДНАЯ ЖИЛА — ЛИСТ 1", font=F_TAB_B, fill=INK)
    dr.text((sx0 + 12, sy0 + 54), "Фасад, вид сбоку, сечения, изометрия", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 12, sy0 + 78), "М 1:15 (сечения 3,4:1) · масштаб, мм", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 12, sy0 + 110), "Сцена: examples/rpg_sword_01.forma", font=F_SMALL, fill=SOFT)
    dr.text((sx0 + 12, sy0 + 134), "21 954 треугольника · 13 деталей", font=F_SMALL, fill=SOFT)

    # ------------------------------------------------------------ ПРИМЕЧАНИЯ
    nx, ny = tx, sy0 + 200
    dr.rectangle([nx, ny, tx + 704, ny + 300], outline=INK, width=2)
    dr.text((nx + 12, ny + 10), "КОНСТРУКЦИЯ — КАК У НАСТОЯЩЕГО МЕЧА", font=F_TAB_B, fill=INK)
    notes = [
        "1. Хвостовик идёт сквозь рукоять и расклёпан в навершии;",
        "   навершие — противовес; баланс по объёму ≈20 мм от гарды (тяжёлая гарда).",
        "2. Плечи клинка опираются на экюссон, стык закрыт обоймой;",
        "   лангеты не дают клинку качаться в гнезде.",
        "3. Профильный конус 86→1,5 и дистальный 10→0,6 мм:",
        "   клинок облегчён к острию, но жёсткий у пяты.",
        "4. Обод кромки — заточка/накладка, а не декор: он задаёт",
        "   линию реза и закрывает кромку кристалла.",
        "5. Гарда S-образная: перья отводят чужой клинок,",
        "   шипы — упор для пальца при фехтовании.",
    ]
    for i, t in enumerate(notes):
        dr.text((nx + 12, ny + 40 + i * 22), t, font=F_SMALL, fill=SOFT)

    # маленькие изометрии узлов в свободном поле
    acts = {k: v for k, v in r.scene.objects.items() if v.visible}

    def node(tx, ty, keys, title, center, radius, tile=360):
        meshes = _prepare([acts[k] for k in keys if k in acts], r.scene.groups)
        img, _ = _render_view(meshes, np.array(center, dtype=float), radius, "iso", tile, 2,
                              [0, 0, 0, 1, 1, 1], grid=False, shadow=True, bg=None, style=LINE_STYLE)
        paste_line(sh, Image.fromarray(_to_bytes(img)), (tx, ty))
        dr.rectangle([tx, ty, tx + tile, ty + tile], outline=(214, 216, 220), width=1)
        dr.text((tx + 2, ty + tile + 10), title, font=F_TAB_B, fill=INK)

    node(120, 1078, ["гарда", "перо_пр", "перо_лв", "шип_пр", "шип_лв", "камень_пр", "камень_лв"],
         "УЗЕЛ 1 · ГАРДА (см. лист 2)", (0, 0, 342), 122)
    node(560, 1078, ["навершие", "камень_навершия", "шишечка"],
         "УЗЕЛ 3 · НАВЕРШИЕ (см. лист 2)", (0, 0, 46), 56)
    node(120, 1420 + 30, [], "", (0, 0, 0), 1) if False else None

    sh.save(OUT / "sword_sheet_1.png")
    print("sheet 1 ok")


# ----------------------------------------------------------------- лист 2 --
DETAILS = [
    (["гарда", "перо_пр", "перо_лв", "шип_пр", "шип_лв", "камень_пр", "камень_лв", "камень_гарды"],
     "ГАРДА · УЗЕЛ 1", "экюссон 84 × 42 × 26 · вылет пера 130 · кабошоны Ø14"),
    (["рукоять", "обмотка", "кольцо_н", "кольцо_в"],
     "РУКОЯТЬ · УЗЕЛ 2", "длина 232 · талия Ø31 · 9 витков обмотки · феррулы Ø41"),
    (["навершие", "камень_навершия", "шишечка"],
     "НАВЕРШИЕ · УЗЕЛ 3", "Ø62 × 92 · 8 граней · кабошон Ø18 · расклёпка"),
    (["клинок", "обод_пр", "обод_лв", "жила_пр", "жила_лв"],
     "ОСТРИЕ · УЗЕЛ 4", "сход кромок в точке · обод Ø4,8 · жила гаснет", ((0, 0, 1252), 78)),
    (["рикассо", "клинок", "жила_пр"],
     "РИКАССО · УЗЕЛ 5", "обойма 92 × 18 × 56 · плечи клинка в экюссоне", ((-30, 0, 400), 90)),
    (["гарда", "перо_пр", "перо_лв", "шип_пр", "шип_лв", "камень_пр", "камень_лв"],
     "ПЕРО ГАРДЫ · УЗЕЛ 6", "S-образное перо · гранёный шип Ø24 · кабошон Ø14", ((-80, 0, 345), 80)),
]


def sheet_details(r) -> None:
    acts = {k: v for k, v in r.scene.objects.items() if v.visible}
    Wd, H = 2260, 1500
    sh = Image.new("RGB", (Wd, H), PAPER)
    dr = ImageDraw.Draw(sh)
    dr.rectangle([36, 36, Wd - 36, H - 36], outline=INK, width=3)
    dr.text((72, 54), "ИЗУМРУДНАЯ ЖИЛА · УЗЛЫ", font=F_TITLE, fill=INK)
    dr.text((74, 112), "Крупные планы: гарда, рукоять, навершие, острие, рикассо, перо · "
                       "изометрия в стиле «линия»", font=F_SUB, fill=SOFT)
    dr.line([(72, 152), (Wd - 72, 152)], fill=INK, width=2)

    tile = 360
    for i, item in enumerate(DETAILS):
        keys, title, note = item[0], item[1], item[2]
        zoom = item[3] if len(item) > 3 else None
        col, row = i % 3, i // 3
        tx = 96 + col * 720
        ty = 200 + row * (tile + 150)
        solids = [acts[k] for k in keys if k in acts]
        meshes = _prepare(solids, r.scene.groups)
        v = np.concatenate([m["verts"] for m in meshes])
        lo, hi = v.min(0), v.max(0)
        c = (lo + hi) / 2.0
        rad = float(np.linalg.norm(hi - lo)) / 2.0 * 1.06
        if zoom:
            c = np.array(zoom[0], dtype=float)
            rad = float(zoom[1])
        img, _ = _render_view(meshes, c, max(rad, 20.0), "iso", tile, 2,
                              [*map(float, lo), *map(float, hi)], grid=False,
                              shadow=True, bg=None, style=LINE_STYLE)
        paste_line(sh, Image.fromarray(_to_bytes(img)), (tx, ty))
        dr.rectangle([tx, ty, tx + tile, ty + tile], outline=(214, 216, 220), width=1)
        dr.text((tx + 2, ty + tile + 14), title, font=F_TAB_B, fill=INK)
        dr.text((tx + 2, ty + tile + 40), note, font=F_SMALL, fill=SOFT)

    bx0, by0 = Wd - 700, H - 210
    dr.rectangle([bx0, by0, Wd - 72, H - 72], outline=INK, width=3)
    dr.line([(bx0, by0 + 44), (Wd - 72, by0 + 44)], fill=INK, width=2)
    dr.text((bx0 + 12, by0 + 9), "ИЗУМРУДНАЯ ЖИЛА — ЛИСТ 2", font=F_TAB_B, fill=INK)
    dr.text((bx0 + 12, by0 + 54), "Узлы 1…6 · изометрия", font=F_SMALL, fill=SOFT)
    dr.text((bx0 + 12, by0 + 78), "Сцена: examples/rpg_sword_01.forma", font=F_SMALL, fill=SOFT)

    sh.save(OUT / "sword_sheet_2.png")
    print("sheet 2 ok")


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
    img, _ = _render_view(meshes, c, rad * 1.02, "iso", 1100, 2, bb,
                          grid=False, shadow=True, bg=None, style=LINE_STYLE)
    write_png(OUT / "_iso.png", _to_bytes(img))
    sheet_main(r)
    sheet_details(r)
    (OUT / "_iso.png").unlink()
    m = r.analysis["metrics"]
    print("tris", m["tris"], "objects", m["visible_count"])


if __name__ == "__main__":
    main()
