"""Клинки и режущий инструмент: катана, ятоган, стилет, дисковая пила.

Клинок — это не выдавленный контур, а **лофт линзы по изогнутой оси**:
сечение меняется от толстой спинки к тонкой кромке, по длине сужается к
острию, ось изогнута по дуге (стрела прогиба у катаны 18–25 мм на 700 мм).
Поэтому в профиль видно дол, в плане — сужение к кончику, а кромка остаётся
тонкой (0.06–0.12 мм — тоньше ядро не держит и печатать бессмысленно).
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, triangulate_2d, ensure_ccw
from .ops import anchor, make_solid, op, stand_flat_sign

# Пропорции и характер разных клинков: длина, ширина, толщина, изгиб, кромки.
KINDS = {
    "катана": dict(width=32.0, thick=7.0, curve=0.032, edges="одна",
                   kissaki=0.06, spine=0.62, dol=0.0),
    "танто": dict(width=30.0, thick=8.0, curve=0.006, edges="одна",
                  kissaki=0.10, spine=0.66, dol=0.0),
    "ятоган": dict(width=42.0, thick=7.5, curve=0.028, edges="одна",
                   kissaki=0.05, spine=0.6, dol=0.18),
    "стилет": dict(width=14.0, thick=5.0, curve=0.0, edges="две",
                   kissaki=0.08, spine=0.5, dol=0.0),
    "двуручник": dict(width=52.0, thick=9.0, curve=0.004, edges="две",
                      kissaki=0.07, spine=0.5, dol=0.22),
    "серп": dict(width=46.0, thick=6.0, curve=0.16, edges="одна",
                 kissaki=0.03, spine=0.55, dol=0.0),
    "нож": dict(width=28.0, thick=4.0, curve=0.0, edges="одна",
                kissaki=0.12, spine=0.7, dol=0.0),
}


def _section(w: float, t: float, edges: str, spine: float, dol: float,
             n: int = 9) -> np.ndarray:
    """Сечение клинка: X — от кромки (−w/2) к спинке (+w/2), Y — толщина.

    Кромка сходится почти в ноль (0.5 % ширины), спинка скруглённая.
    ``dol`` — дол: неглубокая канавка вдоль клинка.
    """
    half_w = max(w, 1e-3) / 2.0
    half_t = max(t, 1e-3) / 2.0
    us = np.linspace(0.0, 1.0, n)
    upper = []
    for u in us:
        if edges == "две":
            h = math.sin(math.pi * u) ** 0.62
        else:
            # одна кромка: у кромки ноль, у спинки — почти полная толщина
            h = math.sin(math.pi * (0.16 + 0.72 * u)) ** 0.55
        if dol > 1e-6:
            # дол: плавная канавка от 30 % до 70 % ширины
            h *= 1.0 - dol * math.exp(-((u - 0.5) / 0.18) ** 2)
        upper.append(((-half_w + w * u), half_t * h))
    lower = [(-x, -y) for x, y in reversed(upper[1:-1])]
    pts = upper + lower
    arr = np.asarray(pts, dtype=np.float64)
    # кромка не должна быть идеально нулевой: ядро требует объём
    arr[:, 1] = np.where(np.abs(arr[:, 0] + half_w) < 1e-9,
                         np.sign(arr[:, 1] + 1e-12) * max(0.03, t * 0.004), arr[:, 1])
    return ensure_ccw(arr)


def _arc_path(length: float, sagitta: float, n: int) -> np.ndarray:
    """Дуга в плоскости XZ: от начала в 0 до конца в (length, 0), прогиб вверх."""
    n = max(3, int(n))
    if sagitta <= 1e-6:
        xs = np.linspace(0.0, length, n)
        return np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], axis=1)
    # радиус по стреле прогиба: R = L²/(8c) + c/2
    R = length * length / (8.0 * sagitta) + sagitta / 2.0
    half = math.asin(min(1.0, (length / 2.0) / R))
    theta = np.linspace(-half, half, n)
    xs = R * np.sin(theta) + length / 2.0
    zs = R * (math.cos(0.0) - np.cos(theta))
    zs -= zs[0]
    return np.stack([xs, np.zeros_like(xs), zs], axis=1)


def _rings_along(path: np.ndarray, sections: list[np.ndarray]) -> list[np.ndarray]:
    """Раскладывает сечения вдоль пути с параллельным переносом кадра."""
    pts = np.asarray(path, dtype=np.float64)
    tangents = np.zeros_like(pts)
    for i in range(len(pts)):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == len(pts) - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        n = np.linalg.norm(t)
        tangents[i] = t / max(n, 1e-12)
    # До финального поворота заготовка лежит плашмя: ширина — по Y,
    # толщина и стрела изгиба — по Z. stand_flat_sign ниже ставит её в XZ.
    up = np.array([0.0, 0.0, 1.0])
    rings = []
    for i, (p, tan) in enumerate(zip(pts, tangents)):
        up = up - tan * float(np.dot(up, tan))
        un = np.linalg.norm(up)
        if un < 1e-9:
            up = np.cross(tan, np.array([1.0, 0.0, 0.0]))
            un = np.linalg.norm(up)
        up = up / max(un, 1e-12)
        right = np.cross(up, tan)
        right /= max(np.linalg.norm(right), 1e-12)
        sec = sections[i]
        rings.append(p[None, :] + right[None, :] * sec[:, 0][:, None]
                     + up[None, :] * sec[:, 1][:, None])
    return rings


def _close_blade(rings: list[np.ndarray], profile: np.ndarray) -> mf.Manifold:
    """Сшивает кольца, закрывает основание и сводит кончик в одну точку."""
    n = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces: list[tuple[int, int, int]] = []
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((a + j, a + j2, b + j2))
            faces.append((a + j, b + j2, b + j))
    # основание — плоская крышка
    tris = triangulate_2d(profile)
    for t in tris:
        faces.append((int(t[2]), int(t[1]), int(t[0])))
    # кончик — веер к одной точке (середина последнего кольца)
    last = (len(rings) - 1) * n
    tip = np.mean(np.asarray(rings[-1]), axis=0)
    ti = len(verts)
    verts.append(tuple(float(c) for c in tip))
    for j in range(n):
        j2 = (j + 1) % n
        faces.append((last + j, last + j2, ti))
    return manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                np.asarray(faces, dtype=np.int64), "клинка")


@op("blade", aliases=("клинок", "клинка", "лезвие", "меч", "катана", "сабля", "sword", "knife"),
    category="Примитивы",
    summary="Клинок: лофт линзовидного сечения по изогнутой оси. kind выбирает "
            "характер — катана (одна кромка, изгиб, остриё киссаки), ятоган "
            "(шире), танто, стилет (две кромки, без изгиба), двуручник (широкий, "
            "с долом), серп (сильный изгиб, кромка внутри), нож. Длина, ширина, "
            "толщина и стрела прогиба задаются отдельно, так что можно сделать "
            "и прямую финку, и кривой ятаган. По умолчанию стоит вдоль X "
            "лицом −Y: остриё +X, ширина по Z, толщина по Y, изгиб уходит "
            "к передней стороне (−Y); plane=плашмя возвращает заготовку в XY.",
    example="катана = blade length=700 width=32 thick=7 kind=катана\n"
            "стилет = blade length=280 width=14 thick=5 kind=стилет\n"
            "серп = blade length=300 width=46 kind=серп curve=90",
    params={"length": "длина, мм (400)",
            "width": "ширина клинка у основания, мм (по kind)",
            "thick": "толщина у спинки, мм (по kind)",
            "curve": "стрела прогиба, мм (по kind): 0 — прямая, 25 — катана, 90 — серп",
            "kind": "катана, танто, ятоган, стилет, двуручник, серп или нож",
            "edges": "одна или две кромки (по kind)",
            "taper": "насколько сужается к кончику, 0…0.9 (0.55)",
            "kissaki": "длина скоса у острия в долях длины (по kind)",
            "dol": "глубина дола 0…0.35 (по kind)",
            "detail": "плотность сетки по длине (авто)",
            "plane": "фронт — клинок стоит на кромке лицом к зрителю, "
                     "плашмя — лежит на боку — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def blade(a, name):
    length = float(a.num("length", 400.0, minv=10.0))
    kind_raw = (a.text("kind") or "катана").strip().lower()
    if kind_raw not in KINDS:
        raise GeometryError(f"Неизвестный вид клинка «{kind_raw}».",
                            hint="kind: " + ", ".join(KINDS) + ".")
    preset = KINDS[kind_raw]
    scale = length / 400.0
    width = float(a.num("width", preset["width"] * max(scale, 0.55), minv=2.0))
    thick = float(a.num("thick", preset["thick"] * max(scale ** 0.6, 0.7), minv=0.6))
    curve_preset = preset["curve"] * length
    curve = float(a.num("curve", curve_preset, minv=0.0))
    edges = (a.text("edges") or preset["edges"]).strip().lower()
    if edges in ("1", "одна", "одна кромка", "single"):
        edges = "одна"
    elif edges in ("2", "две", "обе", "double"):
        edges = "две"
    if edges not in ("одна", "две"):
        raise GeometryError("edges: одна или две.")
    taper = float(a.num("taper", 0.55, minv=0.0, maxv=0.9))
    kissaki = float(a.num("kissaki", preset["kissaki"], minv=0.01, maxv=0.35))
    dol = float(a.num("dol", preset["dol"], minv=0.0, maxv=0.35))
    if thick >= width * 0.7:
        raise GeometryError(f"Клинок толщиной {thick:g} мм при ширине {width:g} мм "
                            f"не может быть тонким.", hint="thick ≈ 0.1…0.3 от width.")
    if curve > length * 1.2:
        raise GeometryError("Стрела прогиба больше длины: это уже кольцо.",
                            hint="curve ≤ 0.5 × length.")
    n_sec = a.int("detail", None, minv=8, maxv=200) or max(24, int(length / 12))
    # профиль по длине: ширина почти постоянна, к острию — скос
    path = _arc_path(length, curve, n_sec)
    sections = []
    for i in range(n_sec):
        u = i / (n_sec - 1)
        narrow = 1.0 - taper * (u ** 1.6)
        if u > 1.0 - kissaki:
            k = (u - (1.0 - kissaki)) / max(kissaki, 1e-6)
            narrow *= max(0.06, 1.0 - k ** 0.85)
        thin = 1.0 - 0.45 * u
        w = width * narrow
        t = thick * thin * (0.35 + 0.65 * min(1.0, narrow * 1.6))
        sections.append(_section(max(w, width * 0.01), max(t, 0.2), edges,
                                 preset["spine"], dol))
    rings = _rings_along(path, sections)
    solid = _close_blade(rings, sections[0])
    solid = stand_flat_sign(a, solid)      # лицо −Y, кромка вниз, длина по X
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    if parts != 1:
        raise GeometryError(f"Клинок распался на {parts} частей: уменьшите изгиб.")
    a.scene.log("info", f"клинок: {kind_raw}, {length:g} мм, прогиб {curve:g} мм, "
                        f"кромок {edges}, {solid.num_tri():,} трис".replace(",", " "),
                a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="blade")


# --------------------------------------------------------------------------- #
#  Дисковая пила
# --------------------------------------------------------------------------- #
_SAW_SHAPES = {
    "треугольные": "треугольные", "острые": "треугольные", "треугольник": "треугольные",
    "sharp": "треугольные", "triangle": "треугольные",
    "трапеция": "трапеция", "трапеции": "трапеция", "карбид": "трапеция",
    "carbide": "трапеция", "плоские": "трапеция", "flat": "трапеция",
    "крюк": "крюк", "крючья": "крюк", "hook": "крюк", "крючковатые": "крюк",
    "волна": "волна", "волны": "волна", "wave": "волна",
}


def _saw_tooth(u: float, shape: str, rake: float) -> float:
    """Высота зуба 0…1 внутри одного шага (u∈[0,1)), 0 — дно пазухи.

    У настоящего зуба длинная спинка (подъём) и короткая передняя кромка
    (спуск), поэтому вершина стоит не в середине шага. ``rake`` — передний
    угол: положительный сдвигает вершину вперёд по ходу реза.
    """
    peak = min(0.88, max(0.35, 0.70 - rake / 130.0))
    if shape == "треугольные":
        return (u / peak) if u <= peak else (1.0 - u) / max(1.0 - peak, 1e-6)
    if shape == "трапеция":
        # карбидная пластина: плоская площадка на вершине
        half = 0.09
        left, right = peak - half, peak + half
        if u <= left:
            return (u / max(left, 1e-6)) ** 0.85
        if u <= right:
            return 1.0
        return max(0.0, (1.0 - u) / max(1.0 - right, 1e-6))
    if shape == "крюк":
        # загнутая вперёд вершина: спинка вогнутая, передняя кромка почти отвесная
        if u <= peak:
            return (u / max(peak, 1e-6)) ** 1.6
        return ((1.0 - u) / max(1.0 - peak, 1e-6)) ** 2.4
    # волна: плавный синус без острых вершин
    return 0.5 + 0.5 * math.cos(2.0 * math.pi * (u - peak))


def _disc_solid(outer: list[tuple[float, float]], thickness: float,
                r_hole: float = 0.0) -> mf.Manifold:
    """Плоский диск по 2D-контуру с настоящим сквозным отверстием."""
    pts = ensure_ccw(np.asarray(outer, dtype=np.float64))
    cs = mf.CrossSection([pts])
    if cs.is_empty():
        raise GeometryError("Контур пилы не замкнулся: уменьшите пазуху gullet.")
    solid = cs.extrude(thickness)
    if r_hole > 0.5:
        shaft = mf.Manifold.cylinder(thickness * 6.0, r_hole, r_hole,
                                     max(48, int(r_hole * 6)), False)
        solid = solid - shaft.translate((0, 0, -thickness * 3.0))
    return solid


@op("saw", aliases=("пила", "дисковая_пила", "дисковая пила", "циркулярка", "saw_blade",
                    "circular_saw"),
    category="Примитивы",
    summary="Дисковая пила: плоское полотно с зубьями по кругу и посадочным "
            "отверстием под вал. Зубья настраиваются отдельно — число, высота, "
            "форма (треугольные, трапеция-карбид, крюк, волна), передний угол "
            "rake и глубина пазухи gullet. По желанию — компенсационные "
            "отверстия windows и расширенный пропил kerf. По умолчанию стоит "
            "в плоскости XZ лицом −Y: толщина по Y, ось вала и всех отверстий — Y; "
            "plane=плашмя кладёт пилу в XY, тогда ось — Z.",
    example="пила = saw diameter=200 thickness=2.5 teeth=24 tooth=6 hole=22\n"
            "настольная = saw diameter=150 teeth=40 shape=трапеция windows=5 kerf=3.2",
    params={"diameter": "наружный диаметр по зубьям, мм (200)",
            "thickness": "толщина полотна, мм (2.5)",
            "teeth": "число зубьев по кругу (24)",
            "tooth": "высота зуба над полотном, мм (5 % диаметра)",
            "shape": "треугольные, трапеция, крюк или волна — «трапеция»",
            "rake": "передний угол зуба, градусы: + вперёд, − назад (10)",
            "gullet": "глубина пазухи между зубьями, мм (2 % диаметра)",
            "kerf": "ширина пропила по зубьям, мм (толщина × 1.4)",
            "hole": "посадочное отверстие под вал, мм (11 % диаметра)",
            "windows": "число круглых отверстий в полотне 0…12 (0)",
            "detail": "точек на зуб, 4…40 (16)",
            "plane": "фронт — пила стоит на ребре лицом к зрителю, "
                     "плашмя — лежит — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def saw(a, name):
    diameter = float(a.num("diameter", 200.0, minv=20.0, maxv=4000.0))
    thickness = float(a.num("thickness", 2.5, minv=0.3, maxv=60.0))
    teeth = int(a.num("teeth", 24, minv=4, maxv=200))
    shape_raw = (a.text("shape") or "трапеция").strip().lower()
    shape = _SAW_SHAPES.get(shape_raw)
    if shape is None:
        raise GeometryError(f"Неизвестная форма зубьев «{a.text('shape')}».",
                            hint="shape: треугольные, трапеция, крюк или волна.")
    r_out = diameter / 2.0
    tooth = float(a.num("tooth", diameter * 0.05, minv=0.2, maxv=diameter * 0.16))
    rake = float(a.num("rake", 10.0, minv=-45.0, maxv=45.0))
    gullet = float(a.num("gullet", max(0.4, diameter * 0.02), minv=0.05,
                         maxv=diameter * 0.08))
    kerf = float(a.num("kerf", thickness * 1.4, minv=thickness, maxv=thickness * 4.0))
    hole = float(a.num("hole", diameter * 0.11, minv=1.0, maxv=r_out * 1.2))
    windows = int(a.num("windows", 0, minv=0, maxv=12))
    detail = int(a.num("detail", 16, minv=4, maxv=40))

    r_tip = r_out
    r_gullet = max(r_out - tooth - gullet, 1.0)   # дно пазухи между зубьями
    r_in = hole / 2.0
    if r_in >= r_gullet - 1.0:
        raise GeometryError(
            f"Отверстие ø{hole:g} мм не оставляет полотна при ø{diameter:g} мм.",
            hint="hole меньше 0.5 × diameter, обычно 0.1…0.2 от диаметра.")

    # Высоты зубьев по кругу; вершину ставим ровно на точку выборки, иначе
    # остриё «срезается» и зуб выглядит лепестком.
    steps = teeth * detail
    peak_u = min(0.88, max(0.35, 0.70 - rake / 130.0))
    heights = []
    for i in range(steps):
        u = (i * teeth / steps) % 1.0
        prev_u = ((i - 1) * teeth / steps) % 1.0
        at_peak = u >= peak_u >= prev_u and (u - peak_u) <= (peak_u - prev_u)
        heights.append(1.0 if at_peak else _saw_tooth(u, shape, rake))
    h_max = max(heights)
    radii = [r_gullet + (r_tip - r_gullet) * h / h_max for h in heights]

    angles = [2.0 * math.pi * i / steps for i in range(steps)]
    outline = [(r * math.cos(t), r * math.sin(t)) for r, t in zip(radii, angles)]
    solid = _disc_solid(outline, thickness, r_in)

    # Пропил: венчик по зубьям чуть толще полотна — так пилит настоящий диск.
    if kerf > thickness * 1.02:
        # венчик держим только у зубьев: глубже в полотне пропил не нужен
        band_r = max(r_gullet - tooth * 0.4, r_in + 2.0)
        inner_band = [(min(r, band_r) * math.cos(t), min(r, band_r) * math.sin(t))
                      for r, t in zip(radii, angles)]
        rim = _disc_solid(outline + list(reversed(inner_band)), kerf)
        solid = solid + rim

    if windows > 0:
        r_win = max(r_in + 3.0, (r_in + r_gullet) / 2.0)
        win_d = max(3.0, min((r_gullet - r_in) * 0.42, diameter * 0.06))
        if r_win - win_d / 2.0 <= r_in + 1.0:
            raise GeometryError(
                f"Отверстия ø{win_d:g} мм не помещаются в полотне пилы.",
                hint="Увеличьте diameter или уменьшите hole/windows.")
        tall = max(thickness, kerf) * 6.0
        holes = None
        for k in range(windows):
            ang = 2.0 * math.pi * k / windows + math.pi / windows
            cut = mf.Manifold.cylinder(tall, win_d / 2.0, win_d / 2.0, 32, False)
            cut = cut.translate((r_win * math.cos(ang), r_win * math.sin(ang), -tall / 2.0))
            holes = cut if holes is None else holes + cut
        solid = solid - holes

    # пила — как колесо: ось по Y, лицо в −Y, катится вдоль X
    solid = stand_flat_sign(a, solid)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    if parts != 1:
        raise GeometryError(f"Пила распалась на {parts} частей: уменьшите пазуху.",
                            hint="gullet меньше 6 % диаметра, tooth — меньше 12 %.")
    a.scene.log("info", f"дисковая пила: ø{diameter:g} мм, {teeth} зубьев, "
                        f"пропил {kerf:g} мм, {solid.num_tri():,} трис".replace(",", " "),
                a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="saw")
