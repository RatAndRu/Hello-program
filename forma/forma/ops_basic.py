"""Примитивы: куб, сфера, цилиндр, конус, тор, призма, капсула, оболочка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (FINENESS_MM, auto_segments, circle_profile, hull_of_manifolds,
                       limit_segments, manifold_from_arrays, manifold_mesh)
from .ops import anchor, detail_factor, detail_level, ensure_solid, make_solid, op


def _round_value(a) -> float:
    return float(a.num("round", 0.0, minv=0.0) or 0.0)


def _sphere_segments(radius: float, factor: float = 1.0) -> int:
    """Сегментов на скругление (Minkowski): чем выше детализация, тем глаже."""
    need = auto_segments(radius, tolerance=0.10, min_n=16, max_n=96)
    if factor != 1.0:
        need = int(min(160, max(10, round(need * factor))))
    return int(need)


def _segments(a, requested, radius: float, tolerance: float = FINENESS_MM,
              max_n: int = 512) -> int:
    """Сегменты по допуску и по степени детализации.

    ``detail=0…5`` (по умолчанию 3) умножает обычное число сегментов: это
    понятный ползунок «сколько треугольников», а не «сколько сегментов».
    """
    factor = detail_factor(a)
    if requested is None:
        return int(limit_segments(None, radius, tolerance=tolerance, max_n=max_n,
                                  factor=factor))
    got = limit_segments(requested, radius, tolerance=tolerance, max_n=max_n,
                         factor=factor)
    if got < int(requested):
        a.scene.log("info", f"гладкость {requested} → {got} сегментов "
                            f"(отклонение ≤ {tolerance:g} мм)", a.cmd.line)
    return int(got)


@op("box", aliases=("куб", "коробка", "cube", "параллелепипед", "брусок", "блок"),
    category="Примитивы",
    summary="Прямоугольный блок. По умолчанию стоит на полу: центр по XY, низ на z=0.",
    example="стол = box size=[1200,700,40]",
    params={"size": "размер [x,y,z], мм (обязательно)",
            "round": "радиус скругления рёбер, мм",
            "detail": "детализация скругления 0…5 (3): больше — глаже и тяжелее",
            "center": "центрировать в точке at (по умолчанию — низ на at)",
            "at": "положение [x,y,z]"},
    positional=[])
def box(a, name):
    size = a.vec("size", 3, required=True)
    if any(s <= 0 for s in size):
        raise GeometryError("Размеры блока должны быть больше нуля.")
    r = _round_value(a)
    solid = None
    if r > 1e-6:
        if min(size) < 2 * r - 1e-6:
            raise GeometryError(
                f"Скругление {r:g} мм слишком велико для блока {size}.",
                hint=f"Максимум — {min(size) / 2:.2f} мм (половина самой тонкой стороны).",
            )
        # ровно половина толщины — допустимый предельный случай:
        # средняя часть вырождается в плоскость, скругление даёт «таблетку»
        inner = [max(s - 2 * r, 1e-3) for s in size]
        solid = mf.Manifold.cube(inner, True).minkowski_sum(
            mf.Manifold.sphere(r, _sphere_segments(r, detail_factor(a))))
    else:
        solid = mf.Manifold.cube(size, True)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="box")


@op("sphere", aliases=("сфера", "шар", "ball"),
    category="Примитивы",
    summary="Сфера. Центр — в точке at (по умолчанию в начале координат).",
    example="шар = sphere radius=40 at=[0,0,40]",
    params={"radius": "радиус, мм (обязательно)",
            "detail": "детализация 0…5 (3): 0 — гранёный шар, 5 — гладкий",
            "segments": "число сегментов (по умолчанию — по детализации)",
            "at": "центр сферы [x,y,z]"},
    positional=["radius"])
def sphere(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    segments = _segments(a, a.int("segments", None, minv=8, maxv=512), radius)
    solid = mf.Manifold.sphere(radius, segments)
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    return make_solid(a.scene, name, solid, a, kind="sphere")


@op("cylinder", aliases=("цилиндр", "труба", "стакан"),
    category="Примитивы",
    summary="Цилиндр или усечённый конус. По умолчанию стоит на полу.",
    example="корпус = cylinder radius=40 height=90 segments=128 round=3",
    params={"radius": "радиус снизу, мм (обязательно)",
            "height": "высота, мм (обязательно)",
            "r2": "радиус сверху (по умолчанию равен нижнему)",
            "segments": "число сегментов (по умолчанию — по детализации)",
            "detail": "детализация 0…5 (3): больше — глаже и тяжелее",
            "round": "скругление верхней и нижней кромки, мм",
            "center": "центрировать по высоте",
            "at": "положение [x,y,z]"},
    positional=["radius", "height"])
def cylinder(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    r2 = a.num("r2", radius, minv=0.0)
    if r2 is None:
        r2 = radius
    segments = _segments(a, a.int("segments", None, minv=8, maxv=1024), max(radius, r2))
    r = _round_value(a)
    if r > 1e-6:
        if height <= 2 * r + 1e-6:
            raise GeometryError(f"Скругление {r:g} мм больше половины высоты {height:g} мм.")
        if min(radius, r2) <= r + 1e-6:
            raise GeometryError(f"Скругление {r:g} мм больше радиуса {min(radius, r2):g} мм.")
        inner_h = height - 2 * r
        solid = mf.Manifold.cylinder(inner_h, radius - r, r2 - r, segments)
        solid = solid.minkowski_sum(
            mf.Manifold.sphere(r, _sphere_segments(r, detail_factor(a))))
    else:
        solid = mf.Manifold.cylinder(height, radius, r2, segments)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="cylinder")


@op("cone", aliases=("конус",), category="Примитивы",
    summary="Конус с вершиной вверх, стоит на полу.",
    example="воронка = cone radius=30 height=60",
    params={"radius": "радиус основания, мм", "height": "высота, мм",
            "detail": "детализация 0…5 (3)", "segments": "сегментов (по детализации)",
            "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def cone(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    segments = _segments(a, a.int("segments", None, minv=8, maxv=1024), radius)
    solid = mf.Manifold.cylinder(height, radius, 0.0, segments)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="cone")


@op("torus", aliases=("тор", "бублик", "кольцо_тор", "torus_ring"), category="Примитивы",
    summary="Тор (бублик) в плоскости XY: кольцо с круглой трубкой. Можно задавать "
            "через наружный/внутренний радиус и толщину — как обычное кольцо, только "
            "сечение трубки круглое и гладкое.",
    example="бублик = torus outer=40 inner=24 thickness=8\n"
            "кольцо = torus major=35 minor=6",
    params={"outer": "наружный радиус, мм (= major + minor)",
            "inner": "радиус отверстия, мм (= major − minor)",
            "thickness": "толщина кольца по радиусу, мм (= 2·minor)",
            "major": "радиус кольца до центра трубки, мм",
            "minor": "радиус трубки, мм",
            "detail": "детализация 0…5 (3): сглаженность кольца и трубки",
            "segments": "сегментов по кругу (по детализации)",
            "minor_segments": "сегментов трубки (по детализации)",
            "at": "центр [x,y,z]"},
    positional=["major", "minor"])
def torus(a, name):
    major = a.num("major", None, minv=0.1)
    minor = a.num("minor", None, minv=0.01)
    outer = a.num("outer", None, minv=0.2)
    inner = a.num("inner", None, minv=0.0)
    thick = a.num("thickness", None, minv=0.02)
    if major is None or minor is None:
        # «кольцевая» форма записи: наружный/внутренний радиус и толщина
        if outer is not None and inner is not None:
            major = (outer + inner) / 2.0
            minor = (outer - inner) / 2.0
        elif thick is not None and outer is not None:
            minor = thick / 2.0
            major = outer - minor
        elif thick is not None and inner is not None:
            minor = thick / 2.0
            major = inner + minor
        elif major is not None and thick is not None:
            minor = thick / 2.0
        elif minor is not None and outer is not None:
            major = outer - minor
        else:
            raise GeometryError(
                "Для тора нужны размеры кольца.",
                hint="Например: torus outer=40 inner=24 thickness=8 "
                     "или torus major=35 minor=6")
    if outer is not None and minor is not None and major is not None and thick is None:
        # outer главнее: подгоняем major, чтобы наружный радиус был ровно задан
        major = max(0.1, outer - minor)
    if inner is not None and minor is not None and major is not None and thick is None:
        major = max(0.1, inner + minor)
    major = float(major)
    minor = float(minor)
    segments = a.int("segments", None, minv=12, maxv=512)
    mseg = a.int("minor_segments", None, minv=8, maxv=128)
    segments = _segments(a, segments, major + minor)
    if mseg is None:
        mseg = max(8, auto_segments(minor, tolerance=0.05))
    else:
        mseg = _segments(a, mseg, minor)
    if minor >= major:
        raise GeometryError("Радиус трубки тора должен быть меньше радиуса кольца.")
    prof = circle_profile(minor, mseg) + np.array([major, 0.0])
    solid = mf.Manifold.revolve(mf.CrossSection([prof]), segments)
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    return make_solid(a.scene, name, solid, a, kind="torus")


@op("prism", aliases=("призма", "многоугольник", "гайка"), category="Примитивы",
    summary="Правильная призма с n сторонами (по умолчанию стоит на полу).",
    example="гайка = prism sides=6 radius=20 height=12",
    params={"sides": "число сторон (6)", "radius": "радиус описанной окружности, мм",
            "r2": "радиус верхней грани — сужение к концу (по умолчанию равен нижнему)",
            "twist": "закрутка верхней грани, градусы",
            "height": "высота, мм", "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def prism(a, name):
    sides = a.int("sides", 6, minv=3, maxv=256)
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    r2 = a.num("r2", radius, minv=0.0)
    twist = a.num("twist", 0.0)
    prof = circle_profile(radius, sides)
    if (r2 is None or abs(r2 - radius) < 1e-9) and abs(twist) < 1e-9:
        solid = mf.CrossSection([prof]).extrude(height)
    else:
        solid = mf.CrossSection([prof]).extrude(
            float(height), 0, float(twist), (float(r2) / float(radius),) * 2)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="prism")


@op("pyramid", aliases=("пирамида", "tetra", "пирамидка"), category="Примитивы",
    summary="Правильная n-угольная пирамида: основание в плоскости XY, вершина вверху. "
            "Отдельный примитив, а не конус — грани плоские, рёбра читаются.",
    example="пирамида = pyramid sides=4 radius=60 height=90",
    params={"sides": "число сторон основания (4)",
            "radius": "радиус описанной окружности основания, мм (обязательно)",
            "height": "высота, мм (обязательно)",
            "tip": "смещение вершины от центра [x,y], мм — наклонная пирамида",
            "center": "центрировать по высоте", "at": "положение [x,y,z]"},
    positional=["radius", "height"])
def pyramid(a, name):
    sides = a.int("sides", 4, minv=3, maxv=128)
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    tip = a.vec("tip", 2, default=(0.0, 0.0))
    base = circle_profile(radius, sides)
    ring = np.column_stack([base, np.zeros(len(base))])
    pts = np.vstack([ring, np.asarray([[tip[0], tip[1], height]])])
    solid = mf.Manifold.hull_points(np.ascontiguousarray(pts, dtype=np.float64))
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="pyramid")


@op("icosphere", aliases=("икосфера", "ико", "ico"), category="Примитивы",
    summary="Икосфера — сфера из одинаковых треугольников, как в Blender. "
            "Ровный полигонаж без «полюсов»: удобно для камней, мячей и стеков.",
    example="шар = icosphere radius=40 divisions=2",
    params={"radius": "радиус, мм (обязательно)",
            "divisions": "уровень подразбиения 1..4 (2): 20 → 80 → 320 → 1280 граней",
            "at": "центр [x,y,z]"},
    positional=["radius"])
def icosphere(a, name):
    import trimesh

    radius = a.num("radius", required=True, minv=0.01)
    divisions = int(a.int("divisions", 2, minv=1, maxv=5) or 2)
    mesh = trimesh.creation.icosphere(subdivisions=divisions, radius=float(radius))
    solid = manifold_from_arrays(mesh.vertices, mesh.faces, "икосферы")
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    return make_solid(a.scene, name, solid, a, kind="icosphere")


@op("diamond", aliases=("алмаз", "бриллиант", "кристалл", "diamond_gem"), category="Примитивы",
    summary="Алмаз: снизу конус (павильон), сверху сужающаяся огранка с плоской "
            "площадкой. Параметр sharp=да делает верх острой трапецевидной призмой "
            "без площадки — «кристалл».",
    example="алмаз = diamond diameter=40 crown=14 pavilion=26 sides=8\n"
            "кристалл = diamond diameter=30 crown=18 pavilion=30 sides=6 sharp=да",
    params={"diameter": "диаметр пояса (рундиста), мм (30)",
            "crown": "высота верхней огранки (12)",
            "pavilion": "глубина нижнего конуса (20)",
            "table": "радиус верхней площадки, доля 0..1 (0.45)",
            "sides": "число граней по кругу (8)",
            "sharp": "да — верх сходится в ребро призмы, без площадки",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter"])
def diamond(a, name):
    diameter = float(a.num("diameter", 30.0, minv=1.0))
    crown = float(a.num("crown", max(2.0, diameter * 0.4), minv=0.2))
    pavilion = float(a.num("pavilion", max(3.0, diameter * 0.65), minv=0.2))
    table_share = float(a.num("table", 0.45, minv=0.0, maxv=0.95))
    sides = int(a.int("sides", 8, minv=3, maxv=64) or 8)
    sharp = a.boolean("sharp", False)
    radius = diameter / 2.0
    belt = np.stack([radius * np.cos(np.linspace(0, 2 * math.pi, sides, endpoint=False)),
                     radius * np.sin(np.linspace(0, 2 * math.pi, sides, endpoint=False))], axis=1)
    table_r = 0.0 if sharp else radius * table_share
    belt_ring = np.column_stack([belt, np.zeros(len(belt))])
    pts = [belt_ring, np.column_stack([belt, np.full(len(belt), -pavilion * 0.35)]),
           np.asarray([[0.0, 0.0, -pavilion]])]
    if table_r > 1e-6:
        table = belt * (table_r / radius)
        pts.append(np.column_stack([table, np.full(len(table), crown)]))
    else:
        # острая огранка: верх сходится к ребру призматической пирамидки
        pts.append(np.column_stack([belt * 0.55, np.full(len(belt), crown)]))
    solid = mf.Manifold.hull_points(np.ascontiguousarray(
        np.vstack(pts), dtype=np.float64))
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="diamond")
    out.notes.append(f"пояс ø{diameter:g} мм, огранка {crown:g}, конус {pavilion:g}")
    return out


@op("capsule", aliases=("капсула", "пилюля"), category="Примитивы",
    summary="Капсула: цилиндр с полусферами. Высота задаётся полная.",
    example="палец = capsule radius=9 height=70",
    params={"radius": "радиус, мм", "height": "полная высота, мм",
            "detail": "детализация 0…5 (3)", "segments": "сегментов (по детализации)",
            "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def capsule(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.02)
    segments = _segments(a, a.int("segments", None, minv=8, maxv=256), radius,
                         max_n=256)
    if height < 2 * radius - 1e-6:
        raise GeometryError(
            f"Высота капсулы {height:g} мм меньше двух радиусов ({2 * radius:g} мм).",
            hint="Высота капсулы включает полусферы.",
        )
    inner_h = max(height - 2 * radius, 1e-4)
    body = mf.Manifold.cylinder(inner_h, radius, radius, segments)
    top = mf.Manifold.sphere(radius, segments).translate((0, 0, inner_h))
    bottom = mf.Manifold.sphere(radius, segments)
    solid = body + top + bottom
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="capsule")


@op("hull", aliases=("оболочка", "выпуклая_оболочка", "обернуть"), category="Примитивы",
    summary="Выпуклая оболочка объектов или набора 3D-точек.",
    example='низ = box size=[300,120,40]\nкабина = box size=[160,110,80] at=[0,0,40]\nкузов = hull objects=[низ, кабина]',
    params={"objects": "объекты, которые нужно обернуть",
            "points": "точки [[x,y,z],...]"},
    positional="*")
def hull(a, name):
    pts_param = None
    if a.has("points"):
        pts_param = a.points("points", dims=3)
    solids = []
    if a.extra or a.has("objects"):
        solids = a.solids()
    clouds = []
    if pts_param is not None:
        clouds.append(np.asarray(pts_param, dtype=np.float64))
    for s in solids:
        v, _ = manifold_mesh(s.manifold)
        if len(v):
            clouds.append(v)
    if not clouds:
        raise GeometryError("Для оболочки нужны объекты или минимум 4 точки.",
                            hint="Например: hull objects=[корпус, кабина]")
    cloud = np.vstack(clouds)
    if len(cloud) > 80000:
        cloud = cloud[:: max(1, len(cloud) // 80000)]
    hull_m = mf.Manifold.hull_points(np.ascontiguousarray(cloud, dtype=np.float64))
    if hull_m.is_empty():
        raise GeometryError("Выпуклая оболочка не построена: точки лежат в одной плоскости.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, hull_m, a, base=solids[0] if solids else None, kind="hull")
    return make_solid(a.scene, name, hull_m, a, base=base, kind="hull")
