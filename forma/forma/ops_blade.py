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
             n: int = 9, profile: str = "линза") -> np.ndarray:
    """Замкнутое несамопересекающееся сечение всей длины клинка.

    X — от режущей кромки (−w/2) к спинке (+w/2), Y — толщина.
    """
    half_w = max(w, 1e-3) / 2.0
    half_t = max(t, 1e-3) / 2.0
    edge = min(half_t * 0.5, max(0.03, t * 0.004))
    us = np.linspace(0.0, 1.0, max(4, n))
    upper = []
    for u in us:
        if edges == "две":
            if profile == "плоский":
                bevel = 0.18 + 0.16 * (1.0 - spine)
                h = min(1.0, u / bevel, (1.0 - u) / bevel)
            elif profile == "алмаз":
                h = 1.0 - abs(2.0 * u - 1.0)
            else:
                h = math.sin(math.pi * u) ** 0.62
        else:
            # Односторонняя заточка заканчивается у спинки, а не только в
            # одной математической точке: за пределом spine остаётся полная
            # толщина и замкнутый контур даёт прямоугольную тупую спинку.
            bevel_u = min(1.0, u / max(0.12, spine))
            if u >= spine:
                h = 1.0
            elif profile == "плоский":
                h = bevel_u
            elif profile == "алмаз":
                h = bevel_u
            else:
                h = math.sin(math.pi * 0.5 * bevel_u) ** (0.8 + spine)
        if dol > 1e-6:
            h *= 1.0 - dol * math.exp(-((u - 0.5) / 0.18) ** 2)
        y = edge + (half_t - edge) * max(0.0, h)
        upper.append((-half_w + w * u, y))
    # X сохраняется! Зеркалить нужно только толщину; старый (-x, -y)
    # перекрещивал контур и ломал изгиб/объём клинка.
    lower = [(x, -y) for x, y in reversed(upper)]
    return ensure_ccw(np.asarray(upper + lower, dtype=np.float64))


def _arc_path(length: float, sagitta: float, n: int) -> np.ndarray:
    """Дуга в плоскости ШИРИНЫ заготовки, а не через её толщину.

    До stand_flat_sign клинок лежит плашмя: ширина идёт по Y, толщина по Z.
    Поэтому сгиб обязан быть по Y; после установки фронтом он становится
    видимым движением кромки вверх/вниз, как сгиб пальца, а не сносом вбок.
    """
    n = max(3, int(n))
    if abs(sagitta) <= 1e-6:
        xs = np.linspace(0.0, length, n)
        return np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], axis=1)
    c = abs(sagitta)
    radius = length * length / (8.0 * c) + c / 2.0
    half = math.asin(min(1.0, (length / 2.0) / radius))
    theta = np.linspace(-half, half, n)
    xs = radius * np.sin(theta) + length / 2.0
    ys = radius * (np.cos(theta) - math.cos(half))
    if sagitta < 0.0:
        ys = -ys
    return np.stack([xs, ys, np.zeros_like(xs)], axis=1)


def _hook_path(length: float, curve: float, n: int) -> np.ndarray:
    """Дуга серпа/пиратского крюка с касательной +X у основания.

    В отличие от обычной сагитты конец не возвращается к исходной оси:
    последняя часть продолжает заворачиваться. curve меняет раствор дуги,
    но даже curve=0 не превращает выбранный kind=серп в прямую палку.
    """
    sign = -1.0 if curve < 0.0 else 1.0
    angle = min(4.35, max(1.55, 2.05 + 2.0 * abs(curve) / length))
    radius = length / angle
    theta = np.linspace(0.0, angle, max(3, int(n)))
    xs = radius * np.sin(theta)
    ys = sign * radius * (1.0 - np.cos(theta))
    return np.stack([xs, ys, np.zeros_like(xs)], axis=1)


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
    # До финального поворота заготовка лежит плашмя: локальная ширина и
    # стрела изгиба лежат в XY, толщина — по Z. stand_flat_sign ставит её
    # в XZ, сохраняя сгиб именно в плоскости ширины.
    up = np.array([0.0, 0.0, 1.0])
    # Векторное произведение — псевдовектор: при зеркальном пути оно само
    # разворачивает сечение и меняет спинку с кромкой местами. Фиксируем
    # сторону сечения относительно знака прогиба; одновременный разворот up
    # сохраняет правую ориентацию каркаса (толщина сечения симметрична).
    bend_sign = -1.0 if pts[len(pts) // 2, 1] < -1e-9 else 1.0
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
        frame_up = up
        if bend_sign < 0.0:
            right = -right
            frame_up = -frame_up
        sec = sections[i]
        rings.append(p[None, :] + right[None, :] * sec[:, 0][:, None]
                     + frame_up[None, :] * sec[:, 1][:, None])
    return rings


def _close_blade(rings: list[np.ndarray], profile: np.ndarray,
                 pointed: bool = True) -> mf.Manifold:
    """Сшивает кольца, закрывает основание и остриё/плоский конец."""
    n = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces: list[tuple[int, int, int]] = []
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((a + j, a + j2, b + j2))
            faces.append((a + j, b + j2, b + j))
    tris = triangulate_2d(profile)
    for tri in tris:
        faces.append((int(tri[2]), int(tri[1]), int(tri[0])))
    last = (len(rings) - 1) * n
    if pointed:
        tip = np.mean(np.asarray(rings[-1]), axis=0)
        ti = len(verts)
        verts.append(tuple(float(c) for c in tip))
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((last + j, last + j2, ti))
    else:
        for tri in tris:
            faces.append((last + int(tri[0]), last + int(tri[1]), last + int(tri[2])))
    return manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                np.asarray(faces, dtype=np.int64), "клинка")


@op("blade", aliases=("клинок", "клинка", "лезвие", "меч", "катана", "сабля", "sword", "knife"),
    category="Примитивы",
    summary="Клинок-лофт с независимыми силуэтом, сечением и остриём. kind "
            "задаёт геометрию: односторонние виды имеют квадратную тупую "
            "спинку, стилет/двуручник — две кромки, серп — продолжающийся "
            "крюк даже при curve=0. profile меняет ширину, section — сечение, "
            "tip — остриё. curve изгибает клинок вверх/вниз в его плоскости.",
    example="катана = blade length=700 width=32 thick=7 kind=катана curve=22 profile=прямой tip=киссаки\n"
            "стилет = blade length=280 kind=стилет section=алмаз tip=острое curve=0\n"
            "нож = blade length=300 kind=нож profile=листовой section=плоский tip=закруглённое",
    params={"length": "длина по X, мм (400)",
            "width": "ширина у основания, мм (по kind)",
            "thick": "толщина у основания, мм (по kind)",
            "curve": "сгиб в плоскости ширины, мм; + вверх, − вниз; у серпа "
                     "задаёт раствор крюка, но 0 не убирает его форму",
            "kind": "катана/танто/ятоган/нож — одна кромка и прямая толстая "
                    "спинка; стилет/двуручник — две кромки; серп — крюк",
            "edges": "одна или две кромки (по kind)",
            "profile": "силуэт всей длины: прямой, суженный или листовой",
            "section": "сечение всего клинка: линза, клин, плоский или алмаз",
            "tip": "заострение: острое, киссаки, закруглённое или тупое",
            "taper": "сила сужения профиля 0…0.9 (0.55)",
            "kissaki": "доля длины, занятая остриём, 0.01…0.35 (по kind)",
            "dol": "глубина дола 0…0.35 (по kind)",
            "detail": "колец по длине 8…200 (авто)",
            "plane": "фронт или плашмя — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def blade(a, name):
    length = float(a.num("length", 400.0, minv=10.0, maxv=10000.0))
    kind_raw = (a.text("kind") or "катана").strip().lower()
    if kind_raw not in KINDS:
        raise GeometryError(f"Неизвестный вид клинка «{kind_raw}». "
                            "kind: " + ", ".join(KINDS) + ".")
    preset = KINDS[kind_raw]
    scale = length / 400.0
    width = float(a.num("width", preset["width"] * max(scale, 0.55),
                        minv=2.0, maxv=2000.0))
    thick = float(a.num("thick", preset["thick"] * max(scale ** 0.6, 0.7),
                        minv=0.6, maxv=500.0))
    curve = float(a.num("curve", preset["curve"] * length,
                        minv=-length * 0.5, maxv=length * 0.5) or 0.0)
    edges = (a.text("edges") or preset["edges"]).strip().lower()
    edges = {"1": "одна", "одна": "одна", "одна кромка": "одна", "single": "одна",
             "2": "две", "две": "две", "обе": "две", "double": "две"}.get(edges, edges)
    if edges not in ("одна", "две"):
        raise GeometryError("edges=одна или две.")
    profile = (a.text("profile") or ("листовой" if kind_raw in ("нож", "ятоган")
                                      else "суженный" if kind_raw in ("танто", "стилет")
                                      else "прямой")).strip().lower()
    profile = {"прямой": "прямой", "прямая": "прямой", "straight": "прямой",
               "суженный": "суженный", "суженная": "суженный", "tapered": "суженный",
               "листовой": "листовой", "листовидный": "листовой", "leaf": "листовой"}.get(profile)
    if profile is None:
        raise GeometryError("profile=прямой, суженный или листовой.")
    section = (a.text("section") or ("алмаз" if kind_raw == "стилет" else
                                      "плоский" if kind_raw in ("танто", "нож") else
                                      "линза" if edges == "две" else "клин")).strip().lower()
    section = {"линза": "линза", "lenticular": "линза", "клин": "клин",
               "wedge": "клин", "плоский": "плоский", "плоская": "плоский",
               "flat": "плоский", "алмаз": "алмаз", "ромб": "алмаз", "diamond": "алмаз"}.get(section)
    if section is None:
        raise GeometryError("section=линза, клин, плоский или алмаз.")
    tip = (a.text("tip") or ("киссаки" if kind_raw in ("катана", "ятоган") else
                              "закруглённое" if kind_raw == "нож" else "острое")).strip().lower()
    tip = {"острое": "острое", "острый": "острое", "point": "острое",
           "киссаки": "киссаки", "kissaki": "киссаки",
           "закруглённое": "закруглённое", "закругленное": "закруглённое",
           "круглое": "закруглённое", "round": "закруглённое",
           "тупое": "тупое", "плоское": "тупое", "blunt": "тупое"}.get(tip)
    if tip is None:
        raise GeometryError("tip=острое, киссаки, закруглённое или тупое.")
    taper = float(a.num("taper", 0.55, minv=0.0, maxv=0.9))
    kissaki = float(a.num("kissaki", preset["kissaki"], minv=0.01, maxv=0.35))
    dol = float(a.num("dol", preset["dol"], minv=0.0, maxv=0.35))
    if thick >= width * 0.7:
        raise GeometryError("thick должен быть меньше 0.7 × width.")
    n_sec = a.int("detail", None, minv=8, maxv=200) or max(24, int(length / 12))
    path = (_hook_path(length, curve, n_sec) if kind_raw == "серп"
            else _arc_path(length, curve, n_sec))
    sections = []
    for i in range(n_sec):
        u = i / (n_sec - 1)
        # Силуэт действует от самого основания, а не только у кончика.
        if profile == "суженный":
            longitudinal = 1.0 - taper * u
        elif profile == "листовой":
            longitudinal = (1.0 + 0.30 * math.sin(math.pi * u)) * (1.0 - 0.65 * taper * u)
        else:
            longitudinal = 1.0 - 0.15 * taper * u
        v = max(0.0, (u - (1.0 - kissaki)) / max(kissaki, 1e-6))
        if tip == "закруглённое":
            tip_factor = max(0.025, math.sqrt(max(0.0, 1.0 - v * v)))
        elif tip == "тупое":
            tip_factor = 1.0 - 0.25 * v
        elif tip == "киссаки":
            tip_factor = max(0.025, 1.0 - v ** 0.75)
        else:
            tip_factor = max(0.025, 1.0 - v)
        w = max(width * 0.01, width * longitudinal * tip_factor)
        t = max(0.2, thick * (1.0 - 0.35 * u) * (0.45 + 0.55 * min(1.0, longitudinal)))
        sec = _section(w, t, edges, preset["spine"], dol, profile=section)
        if tip == "киссаки" and v > 0.0:
            # Смещение к спинке даёт характерную диагональ киссаки.
            sec = sec + np.asarray([width * 0.22 * v * v, 0.0])
        sections.append(sec)
    rings = _rings_along(path, sections)
    solid = _close_blade(rings, sections[0], pointed=tip != "тупое")
    solid = stand_flat_sign(a, solid)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    if parts != 1:
        raise GeometryError(f"Клинок распался на {parts} частей: уменьшите изгиб.")
    a.scene.log("info", f"клинок: {kind_raw}, profile={profile}, section={section}, "
                        f"tip={tip}, прогиб {curve:g} мм", a.cmd.line)
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
    peak = min(0.92, max(0.12, 0.70 - rake / 130.0))
    if shape == "треугольные":
        return (u / peak) if u <= peak else (1.0 - u) / max(1.0 - peak, 1e-6)
    if shape == "трапеция":
        # карбидная пластина: плоская площадка на вершине
        half = min(0.09, peak * 0.45, (1.0 - peak) * 0.45)
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
                r_hole: float = 0.0, radii=None, kerf: float | None = None,
                taper: float = 0.0, band_r: float = 0.0) -> mf.Manifold:
    """Единая сетка диска; никакого второго наложенного зубчатого венца."""
    pts = ensure_ccw(np.asarray(outer, dtype=np.float64))
    if radii is None:
        cs = mf.CrossSection([pts])
        if cs.is_empty():
            raise GeometryError("Контур пилы не замкнулся: уменьшите пазуху gullet.")
        solid = cs.extrude(thickness)
    else:
        rr = np.asarray(radii, dtype=np.float64)
        kerf = thickness if kerf is None else float(kerf)
        n = len(pts)
        local = []
        for r in rr:
            s = min(1.0, max(0.0, (float(r) - band_r) / max(1e-9, float(rr.max()) - band_r)))
            t = thickness + (kerf - thickness) * s
            t *= 1.0 - taper * s
            local.append(max(0.05, t))
        # При taper=0 и kerf=thickness все Z остаются строго 0/thickness.
        verts = []
        for i, (x, y) in enumerate(pts):
            z0 = (thickness - local[i]) / 2.0
            verts.append((float(x), float(y), z0))
        for i, (x, y) in enumerate(pts):
            z1 = (thickness + local[i]) / 2.0
            verts.append((float(x), float(y), z1))
        faces: list[tuple[int, int, int]] = []
        for i in range(n):
            j = (i + 1) % n
            faces.append((i, j, n + j))
            faces.append((i, n + j, n + i))
        for tri in triangulate_2d(pts):
            a0, b0, c0 = (int(v) for v in tri)
            faces.append((c0, b0, a0))
            faces.append((n + a0, n + b0, n + c0))
        solid = manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                     np.asarray(faces, dtype=np.int64), "пилы")
    if r_hole > 0.5:
        tall = max(thickness, thickness if kerf is None else kerf) * 8.0
        shaft = mf.Manifold.cylinder(tall, r_hole, r_hole,
                                     max(48, int(r_hole * 6)), False)
        solid = solid - shaft.translate((0, 0, thickness / 2.0 - tall / 2.0))
    return solid


@op("saw", aliases=("пила", "дисковая_пила", "дисковая пила", "циркулярка", "saw_blade",
                    "circular_saw"),
    category="Примитивы",
    summary="Дисковая пила одной сеткой: диск и зубья имеют одинаковую плоскую "
            "толщину по умолчанию, без наложенного круга. rake до ±75° даёт "
            "острые зубья; taper плавно утоньшает режущую кромку. kerf>thickness "
            "меняет толщину только внутри той же сетки, не добавляя венец.",
    example="пила = saw diameter=200 thickness=2.5 teeth=24 tooth=6 hole=22\n"
            "острая = saw diameter=150 teeth=40 shape=треугольные rake=65 taper=.4",
    params={"diameter": "наружный диаметр по зубьям, мм (200)",
            "thickness": "толщина полотна, мм (2.5)",
            "teeth": "число зубьев по кругу (24)",
            "tooth": "высота зуба над полотном, мм (5 % диаметра)",
            "shape": "треугольные, трапеция, крюк или волна — «трапеция»",
            "rake": "передний угол зуба −75…75°: + вперёд, − назад (10)",
            "gullet": "глубина пазухи между зубьями, мм (2 % диаметра)",
            "taper": "утоньшение наружной кромки 0…0.9; 0 — плоская пила (0)",
            "kerf": "толщина режущей зоны, мм (по умолчанию = thickness, без венца)",
            "hole": "посадочное отверстие под вал, мм; 0 — сплошной диск",
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
    rake = float(a.num("rake", 10.0, minv=-75.0, maxv=75.0))
    gullet = float(a.num("gullet", max(0.4, diameter * 0.02), minv=0.05,
                         maxv=diameter * 0.08))
    kerf = float(a.num("kerf", thickness, minv=thickness, maxv=thickness * 4.0))
    taper = float(a.num("taper", 0.0, minv=0.0, maxv=0.9) or 0.0)
    hole = float(a.num("hole", diameter * 0.11, minv=0.0, maxv=r_out * 1.2) or 0.0)
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
    peak_u = min(0.92, max(0.12, 0.70 - rake / 130.0))
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
    band_r = max(r_gullet - tooth * 0.4, r_in + 2.0)
    solid = _disc_solid(outline, thickness, r_in, radii=radii, kerf=kerf,
                        taper=taper, band_r=band_r)

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
