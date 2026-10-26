"""Корона, инь-ян, линза и полукапсула — формы «по образу и подобию».

Все четыре — настоящие замкнутые тела (их можно резать, склеивать,
проверять и печатать), а не картинки:

* `crown` — кольцо с повторяющимися зазубринами с одной стороны: корона,
  тиара, зубчатый венец. Зубья настраиваются отдельно (число, высота,
  скругление, форма), у кольца своя стенка и необязательный бортик;
* `yin_yang` — знаменитая «запятая» тайцзи: половина круга, разрезанная
  двумя полукругами. Не рисунок, а именно форма;
* `lens` — оптическая линза: двояковыпуклая, двояковогнутая, плосковыпуклая,
  плосковогнутая и мениск;
* `полукапсула` — цилиндр с одним полусферическим окончанием и
  необязательным бортиком у плоского основания.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays
from .ops import make_solid, op, stand_flat_sign
from .ops_shapes import (_chamfered_prism, _cross, _placed, _revolve,
                         _segments, ensure_volume)
from .shape_features import cut_center_hole, hollow_cross, rounded_extrude


def _closed(verts, faces, what: str) -> mf.Manifold:
    """Сетка из массивов с проверкой обхода граней.

    Если грани вывернуты (отрицательный объём), разворачиваем их: ручная
    генерация поверхности иначе даёт «зеркальное» тело, которое нельзя
    склеить с другими.
    """
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    volume = float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6.0)
    if volume < 0:
        f = f[:, ::-1]
    return manifold_from_arrays(v, f, what)


def _sweep_ring(profiles: list[list[tuple[float, float]]], what: str) -> mf.Manifold:
    """Круговое заметание замкнутого профиля (r, z) вокруг оси Z.

    Профиль одинаков по числу точек на каждом угле, но его высоты могут
    гулять по кругу — так получается зубчатый венец короны.
    """
    if not profiles:
        raise GeometryError(f"Не удалось построить {what}: нет сечений.")
    k = len(profiles[0])
    if k < 3:
        raise GeometryError(f"Не удалось построить {what}: профиль слишком простой.")
    angles = np.linspace(0.0, 2.0 * math.pi, len(profiles), endpoint=False)
    verts = []
    for angle, prof in zip(angles, profiles):
        ca, sa = math.cos(angle), math.sin(angle)
        for r, z in prof:
            verts.append((r * ca, r * sa, z))
    faces = []
    n = len(profiles)
    for i in range(n):
        i2 = (i + 1) % n
        for j in range(k):
            j2 = (j + 1) % k
            a0 = i * k + j
            b0 = i * k + j2
            a1 = i2 * k + j
            b1 = i2 * k + j2
            faces.append((a0, b0, b1))
            faces.append((a0, b1, a1))
    return _closed(verts, faces, what)


# --------------------------------------------------------------------------- #
#  Корона
# --------------------------------------------------------------------------- #
_CROWN_SHAPES = {
    "треугольные": "треугольные", "острые": "треугольные", "зубцы": "треугольные",
    "sharp": "треугольные", "triangle": "треугольные",
    "скруглённые": "скруглённые", "скругленные": "скруглённые", "круглые": "скруглённые",
    "round": "скруглённые", "arc": "скруглённые",
    "волна": "волна", "волны": "волна", "wave": "волна", "плавные": "волна",
}


def _crown_height(u: float, shape: str, tip: float) -> float:
    """Высота зуба в долях 0…1 по положению внутри зуба u∈[0, 1)."""
    t = 2.0 * u - 1.0                     # -1 слева, 0 вершина, +1 справа
    if shape == "волна":
        return 0.5 + 0.5 * math.cos(math.pi * t)
    triangle = 1.0 - abs(t)
    if shape == "скруглённые":
        return math.sqrt(max(0.0, 1.0 - t * t))
    # треугольные: tip плавно превращает остриё в дугу — скругление вершин
    if tip <= 0.0:
        return triangle
    arc = math.sqrt(max(0.0, 1.0 - t * t))
    return (1.0 - tip) * triangle + tip * arc


@op("crown", aliases=("корона", "тиара", "венец", "зубчатый_венец", "tiara"),
    category="Примитивы",
    summary="Корона — кольцо с повторяющимися зазубринами сверху. Зубья "
            "настраиваются отдельно: число, высота, скругление вершин "
            "(tip=0 — острые, 1 — круглые) и форма (треугольные, скруглённые, "
            "волна). Кольцо полое, с толщиной стенки и необязательным бортиком "
            "по низу. Подходит и для тиары, и для зубчатого венца шестерни-короны.",
    example="корона = crown diameter=160 height=55 wall=4 teeth=12 tooth=30 tip=0.4\n"
            "тиара = crown diameter=120 height=30 wall=3 teeth=9 tooth=45 "
            "shape=скруглённые",
    params={"diameter": "наружный диаметр кольца, мм (160)",
            "height": "высота обода без зубьев, мм (50)",
            "wall": "толщина стенки, мм (4)",
            "teeth": "число зубьев по кругу (12)",
            "tooth": "высота зубьев, мм (половина обода)",
            "tip": "скругление вершин 0…1 (0.35)",
            "shape": "треугольные, скруглённые или волна",
            "rim": "бортик по низу: выступ наружу, мм (0)",
            "rim_height": "высота бортика, мм (8 % обода)",
            "detail": "точек на зуб (14 — гладко)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def crown(a, name):
    diameter = float(a.num("diameter", 160.0, minv=4.0))
    height = float(a.num("height", 50.0, minv=0.5))
    wall = float(a.num("wall", 4.0, minv=0.4))
    teeth = int(a.num("teeth", 12, minv=3, maxv=200))
    tooth = float(a.num("tooth", height * 0.5, minv=0.0))
    tip = float(a.num("tip", 0.35, minv=0.0, maxv=1.0) or 0.0)
    shape_raw = (a.text("shape") or "треугольные").strip().lower()
    shape = _CROWN_SHAPES.get(shape_raw)
    if shape is None:
        raise GeometryError(f"Неизвестная форма зубьев «{a.text('shape')}».",
                            hint="shape: треугольные, скруглённые или волна.")
    rim = float(a.num("rim", 0.0, minv=0.0) or 0.0)
    rim_h = float(a.num("rim_height", height * 0.08, minv=0.0) or 0.0)
    detail = int(a.num("detail", 14, minv=4, maxv=64))
    r_out = diameter / 2.0
    r_in = r_out - wall
    if r_in <= 0.5:
        raise GeometryError(f"Стенка {wall:g} мм съела всё кольцо ø{diameter:g} мм.",
                            hint="wall меньше половины диаметра, обычно 2–8 мм.")
    if rim > 0 and rim_h <= 0:
        rim_h = max(1.0, height * 0.08)
    rim_h = min(rim_h, height * 0.9) if rim > 0 else 0.0

    steps = teeth * detail
    profiles: list[list[tuple[float, float]]] = []
    for i in range(steps):
        u = (i * teeth / steps) % 1.0
        z_top = height + tooth * _crown_height(u, shape, tip)
        prof: list[tuple[float, float]] = []
        if rim > 0:
            prof.append((r_in, 0.0))
            prof.append((r_out + rim, 0.0))
            prof.append((r_out + rim, rim_h))
            prof.append((r_out, rim_h))
        else:
            prof.append((r_in, 0.0))
            prof.append((r_out, 0.0))
        prof.append((r_out, z_top))
        prof.append((r_in, z_top))
        profiles.append(prof)
    solid = _sweep_ring(profiles, "короны")
    solid = ensure_volume(solid, "корона")
    a.scene.log("info", f"корона: ø{diameter:g} мм, {teeth} зубьев, "
                        f"высота {height + tooth:g} мм", a.cmd.line)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="crown")


# --------------------------------------------------------------------------- #
#  Инь-ян (тайцзи)
# --------------------------------------------------------------------------- #
@op("yin_yang", aliases=("инь_ян", "инь-ян", "иньянь", "тайцзи", "тайцзиту",
                         "comma", "запятая", "инь"),
    category="Примитивы",
    summary="Одна отдельная «шестёрка» инь-ян площадью в половину исходного "
            "круга, а не две соединённые половины. Внутренние дуги идут в разные "
            "стороны; round — плавное скругление. hole делает отверстие в точке, "
            "wall>0 — контурную рамку; отдельного mode больше нет.",
    example="инь = yin_yang diameter=120 thick=16 round=3 hole=16\n"
            "рамка = yin_yang diameter=120 thick=10 wall=4\n"
            "зеркало = yin_yang diameter=120 thick=16 side=правый",
    params={"diameter": "диаметр исходного круга, мм (120)",
            "thick": "толщина, мм (16)",
            "round": "плавное скругление кромки, мм (0 — точное совмещение половин)",
            "side": "левый (по умолчанию) или правый — зеркальная одиночная фигура",
            "hole": "отверстие в центре точки этой половины, мм (0)",
            "wall": "толщина рамки, мм; 0 — сплошная фигура, wall>0 — рамка",
            "segments": "точек на дугу (по размеру)",
            "plane": "фронт — знак стоит в XZ лицом −Y; плашмя — лежит в XY "
                     "лицом +Z (фронт)",
            "at": "сдвиг от центра всего знака [x,y,z]; половины не привязываются "
                  "к полу по отдельности",
            "center": "центрировать по габариту (обычно не нужно)"})
def yin_yang(a, name):
    diameter = float(a.num("diameter", 120.0, minv=6.0))
    thick = float(a.num("thick", 16.0, minv=0.4))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    hole = float(a.num("hole", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    side_raw = (a.text("side") or "левый").strip().lower()
    if side_raw in ("правый", "правая", "right", "право"):
        side = "правый"
    elif side_raw in ("левый", "левая", "left", "лево", ""):
        side = "левый"
    else:
        raise GeometryError(f"Неизвестная сторона «{a.text('side')}».",
                            hint="side: левый или правый.")
    R = diameter / 2.0
    n = _segments(a.int("segments", None, minv=12, maxv=256),
                  max(24, min(128, int(R * 1.4))))
    pts: list[tuple[float, float]] = []
    # левая половина внешней окружности: сверху вниз через левый край
    for i in range(n + 1):
        t = math.radians(90.0 + 180.0 * i / n)
        pts.append((R * math.cos(t), R * math.sin(t)))
    # нижний малый полукруг: от (0,-R) к (0,0) через (R/2, -R/2)
    for i in range(1, n + 1):
        t = math.radians(-90.0 + 180.0 * i / n)
        pts.append((R / 2.0 * math.cos(t), -R / 2.0 + R / 2.0 * math.sin(t)))
    # Верхняя дуга идёт через ЛЕВУЮ сторону: знак минус принципиален.
    # При одинаковом знаке площадь ошибочно становилась 3/4 круга.
    for i in range(1, n):
        t = math.radians(-90.0 + 180.0 * i / n)
        pts.append((-R / 2.0 * math.cos(t), R / 2.0 + R / 2.0 * math.sin(t)))
    if side == "правый":
        # Вторая половина — поворот на 180°, а не зеркало: знак хирален.
        # Зеркальная копия перекрывает исходную на четверть круга.
        pts = [(-x, -y) for x, y in pts]
    cross = hollow_cross(_cross(pts), wall, "инь-ян")
    bevel = min(round_r, thick / 2.0 - 1e-3, R * 0.15)
    if wall > 1e-6:
        bevel = min(bevel, wall / 2.0 - 1e-3)
    solid = rounded_extrude(cross, thick, max(0.0, bevel), "инь-ян",
                            sphere_segments=18)
    # У левой половины точка внизу; поворот правой переносит её вверх.
    if hole >= R * 0.95:
        raise GeometryError("hole слишком велико для точки инь-ян.",
                            hint="Диаметр отверстия должен быть меньше R=diameter/2.")
    dot_y = R / 2.0 if side == "правый" else -R / 2.0
    solid = cut_center_hole(solid, thick, hole, center=(0.0, dot_y),
                            segments=n, what="инь-ян")
    solid = ensure_volume(solid, "инь-ян")
    # Общий канон плоских знаков: по умолчанию стоит в XZ лицом −Y.
    # Поворот делаем ДО сдвига: начало координат остаётся центром всего знака.
    solid = stand_flat_sign(a, solid)
    # Половинки знака не центрируем по габариту: у «запятой» габарит не
    # симметричен, и две половинки разъехались бы. Начало координат — центр
    # самого знака; at одинаково сдвигает обе половины и не привязывает их к полу.
    at = a.vec("at", 3, default=(0, 0, 0))
    if a.boolean("center", False):
        solid = _placed(a, solid)
    else:
        solid = solid.translate([float(at[0]), float(at[1]), float(at[2])])
    return make_solid(a.scene, name, solid, a, kind="yin_yang")


# --------------------------------------------------------------------------- #
#  Линза
# --------------------------------------------------------------------------- #
_LENS_MODES = {
    "выпуклая": "выпуклая", "двояковыпуклая": "выпуклая", "convex": "выпуклая",
    "двояко-выпуклая": "выпуклая", "положительная": "выпуклая",
    "вогнутая": "вогнутая", "двояковогнутая": "вогнутая", "concave": "вогнутая",
    "двояко-вогнутая": "вогнутая", "отрицательная": "вогнутая",
    "плосковыпуклая": "плосковыпуклая", "плоско-выпуклая": "плосковыпуклая",
    "plano-convex": "плосковыпуклая",
    "плосковогнутая": "плосковогнутая", "плоско-вогнутая": "плосковогнутая",
    "plano-concave": "плосковогнутая",
    "мениск": "мениск", "meniscus": "мениск", "выпукло-вогнутая": "мениск",
}


@op("lens", aliases=("линза", "оптическая_линза", "lens_glass", "optic"),
    category="Примитивы",
    summary="Оптическая линза с настоящими сферическими поверхностями: "
            "двояковыпуклая (увеличительная), двояковогнутая, плосковыпуклая, "
            "плосковогнутая и мениск. sag — глубина прогиба (стрела), edge — "
            "толщина по краю, rim — плоская шлифованная кромка. Плоскость "
            "линзы — XY, оптическая ось — Z: лицевые оптические стороны +Z и −Z; "
            "диаметр занимает X/Y, толщина — Z.",
    example="линза = lens diameter=70 sag=12 edge=4 mode=выпуклая\n"
            "вогнутая = lens diameter=60 sag=8 edge=20 mode=вогнутая rim=2",
    params={"diameter": "диаметр, мм (70)",
            "sag": "глубина прогиба, мм (12)",
            "edge": "толщина по краю, мм (4)",
            "mode": "выпуклая, вогнутая, плосковыпуклая, плосковогнутая, мениск",
            "rim": "плоская кромка по краю, мм (1.5 % диаметра)",
            "segments": "точек по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def lens(a, name):
    diameter = float(a.num("diameter", 70.0, minv=3.0))
    sag = float(a.num("sag", 12.0, minv=0.05))
    mode_raw = (a.text("mode") or "выпуклая").strip().lower()
    mode = _LENS_MODES.get(mode_raw)
    if mode is None:
        raise GeometryError(f"Неизвестный вид линзы «{a.text('mode')}».",
                            hint="mode: выпуклая, вогнутая, плосковыпуклая, "
                                 "плосковогнутая или мениск.")
    # У вогнутых линз край толще середины: по умолчанию даём такой край,
    # чтобы в центре осталось разумное тело (4 мм), а не ноль.
    edge_default = 4.0
    if mode == "вогнутая":
        edge_default = 2.0 * sag + 4.0
    elif mode == "плосковогнутая":
        edge_default = sag + 4.0
    edge = float(a.num("edge", edge_default, minv=0.2))
    R = diameter / 2.0
    rim = float(a.num("rim", max(0.4, diameter * 0.015), minv=0.0) or 0.0)
    rim = min(rim, R * 0.45)
    segments = _segments(a.int("segments", None, minv=16, maxv=256),
                         max(48, min(160, int(R * 4))))

    if mode == "выпуклая":
        def top(r):     # noqa: E306 — маленькие локальные профили читаются так
            return edge / 2.0 + sag * (1.0 - (r / R) ** 2)

        def bottom(r):
            return -top(r)
    elif mode == "вогнутая":
        center = edge - 2.0 * sag
        if center <= 0.4:
            raise GeometryError(
                f"При sag={sag:g} мм вогнутая линза становится тоньше нуля.",
                hint="Для вогнутой держите sag меньше половины edge.")

        def top(r):
            return (center + 2.0 * sag * (r / R) ** 2) / 2.0

        def bottom(r):
            return -top(r)
    elif mode == "плосковыпуклая":
        def top(r):
            return edge + sag * (1.0 - (r / R) ** 2)

        def bottom(r):
            return 0.0
    elif mode == "плосковогнутая":
        center = edge - sag
        if center <= 0.4:
            raise GeometryError(
                f"При sag={sag:g} мм середина плосковогнутой линзы тоньше нуля.",
                hint="sag должен быть меньше edge.")

        def top(r):
            return center + sag * (r / R) ** 2

        def bottom(r):
            return 0.0
    else:  # мениск: одинаковая кривизна обеих поверхностей, толщина по краю
        def top(r):
            return edge / 2.0 + sag * (1.0 - (r / R) ** 2)

        def bottom(r):
            return top(r) - edge

    steps = 28
    r_edge = max(1e-3, R - rim)
    prof: list[tuple[float, float]] = [(0.0, float(bottom(0.0)))]
    for i in range(1, steps + 1):
        r = r_edge * i / steps
        prof.append((r, float(bottom(r))))
    if rim > 1e-3:
        prof.append((R, float(bottom(R))))
        prof.append((R, float(top(R))))
    for i in range(steps, 0, -1):
        r = r_edge * i / steps
        prof.append((r, float(top(r))))
    prof.append((0.0, float(top(0.0))))
    solid = _revolve(prof, segments, "линзы")
    solid = ensure_volume(solid, "линза")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="lens")


# --------------------------------------------------------------------------- #
#  Полукапсула
# --------------------------------------------------------------------------- #
@op("полукапсула", aliases=("half_capsule", "halfcapsule", "cartridge",
                             "патрон", "patron"),
    category="Примитивы",
    summary="Полукапсула: плоское основание, цилиндр и одно полусферическое "
            "окончание. Никаких пистолетного/винтовочного режимов. rim и "
            "rim_height добавляют прямой бортик у основания, как у короны.",
    example="деталь = полукапсула diameter=20 length=50\n"
            "с_бортом = полукапсула diameter=20 length=50 rim=2 rim_height=3",
    params={"diameter": "диаметр цилиндра и полусферы, мм (9)",
            "length": "полная длина от плоского низа до вершины, мм (29)",
            "rim": "радиальный выступ бортика у основания, мм (0 — без него)",
            "rim_height": "высота бортика, мм",
            "segments": "точек по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def half_capsule(a, name):
    diameter = float(a.num("diameter", 9.0, minv=0.6))
    length = float(a.num("length", 29.0, minv=0.6))
    r0 = diameter / 2.0
    rim = float(a.num("rim", diameter * 0.08, minv=0.0) or 0.0)
    rim_h = float(a.num("rim_height", max(0.8, diameter * 0.08) if rim > 0 else 0.0,
                         minv=0.0) or 0.0)
    if rim <= 1e-6:
        rim_h = 0.0
    elif rim_h <= 1e-6:
        rim_h = max(0.8, diameter * 0.08)
    equator = length - r0
    if equator < rim_h - 1e-9 or equator <= 1e-9:
        raise GeometryError(
            "Полукапсула: length должен оставить место полусфере над бортиком.",
            hint="Нужно length ≥ diameter/2 + rim_height.")
    segments = _segments(a.int("segments", None, minv=16, maxv=256),
                         max(48, min(160, int(r0 * 6))))
    prof: list[tuple[float, float]] = [(0.0, 0.0)]
    if rim > 1e-6:
        prof += [(r0 + rim, 0.0), (r0 + rim, rim_h), (r0, rim_h)]
    else:
        prof.append((r0, 0.0))
    if equator > rim_h + 1e-9:
        prof.append((r0, equator))
    steps = max(16, segments // 4)
    for i in range(1, steps + 1):
        theta = math.pi / 2.0 * i / steps
        prof.append((r0 * math.cos(theta), equator + r0 * math.sin(theta)))
    solid = _revolve(prof, segments, "полукапсулы")
    solid = ensure_volume(solid, "полукапсула")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="half_capsule")
    out.notes.append(f"полукапсула ø{diameter:g}×{length:g}, rim={rim:g}, "
                     f"rim_height={rim_h:g}")
    return out
