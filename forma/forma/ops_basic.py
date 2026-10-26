"""Примитивы: куб, сфера, цилиндр, конус, тор, призма, капсула, оболочка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (FINENESS_MM, auto_segments, circle_profile, hull_of_manifolds,
                       limit_segments, manifold_from_arrays, manifold_mesh)
from .ops import anchor, detail_factor, detail_level, ensure_solid, make_solid, op
from .primitive_topology import (cube_sphere, dual_sphere, linear_subdivide,
                                 loop_smooth)


def _top_offset(a) -> np.ndarray:
    return np.asarray(a.vec("top_offset", 2, default=(0.0, 0.0)), dtype=np.float64)


def _top_scale(a) -> np.ndarray:
    scale = np.asarray(a.vec("top_scale", 2, default=(1.0, 1.0)), dtype=np.float64)
    if np.any(scale <= 0.0):
        raise GeometryError("top_scale: оба множителя верхней плоскости должны быть больше нуля.")
    return scale


def _base_angle(a) -> float:
    return float(a.num("base_angle", 90.0, minv=15.0, maxv=165.0))


def _parallelogram(x: float, y: float, angle_deg: float) -> np.ndarray:
    """Центрированный параллелограмм со сторонами x/y и углом между ними."""
    angle = math.radians(angle_deg)
    u = np.array([float(x), 0.0])
    v = np.array([float(y) * math.cos(angle), float(y) * math.sin(angle)])
    return np.asarray([-(u + v) / 2, (u - v) / 2,
                       (u + v) / 2, (-u + v) / 2], dtype=np.float64)


def _base_profile(radius: float, sides: int, angle_deg: float) -> np.ndarray:
    if abs(angle_deg - 90.0) < 1e-9:
        return np.asarray(circle_profile(radius, sides), dtype=np.float64)
    if sides != 4:
        raise GeometryError("Параллелограмм в основании возможен только при sides=4.",
                            hint="Для многоугольника оставьте base_angle=90.")
    # Сторона исходного квадрата с описанным радиусом radius равна √2·radius.
    return _parallelogram(math.sqrt(2.0) * radius, math.sqrt(2.0) * radius,
                          angle_deg)


def _rounded_convex(solid: mf.Manifold, radius: float, a, what: str) -> mf.Manifold:
    """Настоящее скругление выпуклого тела: эрозия плоскостей + шар.

    Каждая исходная грань n·x≤c переносится внутрь до n·x≤c−r.
    Пересечение этих полупространств — точная эрозия тела шаром радиуса r;
    последующая Minkowski-сумма скругляет рёбра, не добавляя объём снаружи
    исходной формы. В отличие от уменьшения габаритной коробки это корректно
    и для наклонных боковых граней.
    """
    vertices, faces = manifold_mesh(solid)
    vertices = np.asarray(vertices, dtype=np.float64)[:, :3]
    faces = np.asarray(faces, dtype=np.int64)
    planes = {}
    for ia, ib, ic in faces:
        p0, p1, p2 = vertices[ia], vertices[ib], vertices[ic]
        normal = np.cross(p1 - p0, p2 - p0)
        length = float(np.linalg.norm(normal))
        if length < 1e-10:
            continue
        normal /= length
        offset = float(np.dot(normal, p0))
        key = tuple(np.round(normal, 5)) + (round(offset, 4),)
        planes[key] = (normal, offset)
    inner = solid
    for normal, offset in planes.values():
        # trim_by_plane оставляет сторону normal·x ≥ origin_offset.
        inner = inner.trim_by_plane(tuple(-normal), -(offset - radius))
        if inner.is_empty() or inner.volume() <= 1e-8:
            raise GeometryError(f"{what}: round={radius:g} мм стирает тело.",
                                hint="Уменьшите round или увеличьте размеры/высоту.")
    result = inner.minkowski_sum(
        mf.Manifold.sphere(radius, _sphere_segments(radius, detail_factor(a))))
    if result.is_empty() or result.volume() <= 1e-8:
        raise GeometryError(f"{what}: не удалось скруглить тело.")
    return result


def _two_ring_hull(bottom: np.ndarray, top: np.ndarray, height: float,
                   z_bottom: float = 0.0, z_top: float | None = None) -> mf.Manifold:
    if len(bottom) != len(top) or len(bottom) < 3:
        raise GeometryError("Верхнее и нижнее сечения должны иметь одинаковое число точек.")
    z_top = float(height if z_top is None else z_top)
    points = np.vstack([
        np.column_stack([bottom, np.full(len(bottom), float(z_bottom))]),
        np.column_stack([top, np.full(len(top), z_top)]),
    ])
    solid = mf.Manifold.hull_points(np.ascontiguousarray(points, dtype=np.float64))
    if solid.is_empty() or solid.volume() <= 1e-9:
        raise GeometryError("Верхнее и нижнее сечения образуют вырожденное тело.")
    return solid


def _smooth_level(a) -> int:
    return int(a.int("smooth", 0, minv=0, maxv=4) or 0)


def _smooth_primitive(solid: mf.Manifold, a, what: str) -> mf.Manifold:
    return loop_smooth(solid, _smooth_level(a), what)


def _sliced_sphere(radius: float, cut: float, round_r: float,
                   segments: int) -> mf.Manifold:
    """Сфера без верхней шапки; срез и фаска строятся одним профилем."""
    h = float(radius - cut)
    profile = [(0.0, -float(radius))]
    arc_steps = max(8, int(segments) // 2)
    if round_r <= 1e-9:
        beta = math.asin(max(-1.0, min(1.0, h / radius)))
        for i in range(1, arc_steps + 1):
            phi = -math.pi / 2 + (beta + math.pi / 2) * i / arc_steps
            profile.append((radius * math.cos(phi), radius * math.sin(phi)))
    else:
        # Центр дуги фаски находится на расстоянии r и от сферы, и от среза.
        max_round = (radius + h) / 2.0
        if round_r >= max_round - 1e-9:
            raise GeometryError(
                f"round={round_r:g} мм слишком велик для этого среза.",
                hint=f"При такой глубине среза радиус должен быть меньше {max_round:g} мм.")
        inner_r = radius - round_r
        zc = h - round_r
        alpha = math.asin(max(-1.0, min(1.0, zc / inner_r)))
        xc = inner_r * math.cos(alpha)
        for i in range(1, arc_steps + 1):
            phi = -math.pi / 2 + (alpha + math.pi / 2) * i / arc_steps
            profile.append((radius * math.cos(phi), radius * math.sin(phi)))
        fillet_steps = max(3, min(32, int(segments) // 8))
        for i in range(1, fillet_steps + 1):
            theta = alpha + (math.pi / 2 - alpha) * i / fillet_steps
            profile.append((xc + round_r * math.cos(theta),
                            zc + round_r * math.sin(theta)))
    profile.append((0.0, h))
    cross = mf.CrossSection([profile])
    if cross.is_empty() or cross.area() <= 0.0:
        raise GeometryError("Не удалось построить профиль срезанной сферы.")
    solid = mf.Manifold.revolve(cross, int(segments))
    if solid.is_empty() or solid.volume() <= 1e-9:
        raise GeometryError("Срезанная сфера получилась пустой.")
    return solid


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
    summary="Параллелепипед с независимой верхней плоскостью. top_size меняет её "
            "стороны, top_offset сдвигает центр, base_angle=не 90 делает в основании "
            "параллелограмм. Сильный round, близкий к половине меньшей стороны, "
            "превращает коробку в овальную/круглую форму. По умолчанию стоит на полу.",
    example="блок = box size=[120,80,50] top_size=[80,50] top_offset=[15,-5]\n"
            "скошенный = box size=[100,70,40] base_angle=65",
    params={"size": "стороны нижнего основания и высота [x,y,z], мм (обязательно)",
            "top_size": "стороны верхней плоскости [x,y], мм (по умолчанию как снизу)",
            "top_offset": "сдвиг центра верхней плоскости относительно нижней [dx,dy], мм",
            "base_angle": "угол между сторонами основания 15…165° (90 — прямоугольник)",
            "round": "радиус рёбер; у квадратной коробки около половины стороны — "
                     "овальная/круглая форма",
            "detail": "детализация скругления 0…5 (3): больше — глаже и тяжелее",
            "center": "центрировать в точке at (по умолчанию — низ на at)",
            "at": "положение [x,y,z]"},
    positional=[])
def box(a, name):
    size = a.vec("size", 3, required=True)
    if any(s <= 0 for s in size):
        raise GeometryError("Размеры блока должны быть больше нуля.")
    x, y, height = map(float, size)
    top_size = a.vec("top_size", 2, default=(x, y))
    if any(s <= 0 for s in top_size):
        raise GeometryError("top_size: стороны верхней плоскости должны быть больше нуля.")
    tx, ty = map(float, top_size)
    offset = _top_offset(a)
    angle = _base_angle(a)
    custom = (abs(angle - 90.0) > 1e-9 or a.has("top_size")
              or float(np.linalg.norm(offset)) > 1e-12)
    r = _round_value(a)
    if not custom:
        # Старый путь сохраняет точную геометрию и быстродействие обычного box.
        if r > 1e-6:
            if min(size) < 2 * r - 1e-6:
                raise GeometryError(
                    f"Скругление {r:g} мм слишком велико для блока {size}.",
                    hint=f"Максимум — {min(size) / 2:.2f} мм (половина самой тонкой стороны).")
            inner = [max(s - 2 * r, 1e-3) for s in size]
            solid = mf.Manifold.cube(inner, True).minkowski_sum(
                mf.Manifold.sphere(r, _sphere_segments(r, detail_factor(a))))
        else:
            solid = mf.Manifold.cube(size, True)
    else:
        bottom = _parallelogram(x, y, angle)
        top = _parallelogram(tx, ty, angle) + offset
        solid = _two_ring_hull(bottom, top, height)
        if r > 1e-6:
            if height < 2 * r - 1e-6:
                raise GeometryError(
                    f"Скругление {r:g} мм слишком велико для высоты {height:g} мм.",
                    hint="round не должен превышать половину высоты.")
            solid = _rounded_convex(solid, r, a, "блок")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="box")
    if custom:
        out.notes.append(f"верх {tx:g}×{ty:g}, сдвиг {offset.tolist()}, угол основания {angle:g}°")
    return out


@op("sphere", aliases=("сфера", "шар", "ball"),
    category="Примитивы",
    summary="Сфера с плоским срезом сверху. slice задаёт срезаемую долю радиуса "
            "0…1 (1 — полусфера), cut — ту же глубину в миллиметрах; round "
            "скругляет переход между сферической стенкой и плоскостью среза.",
    example="шар = sphere radius=40 at=[0,0,40]\n"
            "полусфера = sphere radius=40 slice=1 round=3\n"
            "срез = sphere radius=40 cut=12 round=2",
    params={"radius": "радиус, мм (обязательно)",
            "slice": "сколько отсечь сверху, доля радиуса 0…1 (0; 1 — полусфера)",
            "cut": "глубина среза сверху, мм 0…radius; нельзя вместе с slice",
            "round": "радиус скругления новой кромки, мм (0 — острый срез)",
            "detail": "детализация 0…5 (3): 0 — гранёный шар, 5 — гладкий",
            "segments": "число сегментов (по умолчанию — по детализации)",
            "at": "центр ИСХОДНОЙ сферы [x,y,z]; срез не перецентрирует деталь"},
    positional=["radius"])
def sphere(a, name):
    radius = float(a.num("radius", required=True, minv=0.01))
    segments = _segments(a, a.int("segments", None, minv=8, maxv=512), radius)
    slice_share = float(a.num("slice", 0.0, minv=0.0, maxv=1.0) or 0.0)
    cut_mm = a.num("cut", None, minv=0.0)
    if cut_mm is not None and a.has("slice"):
        raise GeometryError("Задайте только один размер среза: slice ИЛИ cut.")
    cut = float(cut_mm) if cut_mm is not None else slice_share * radius
    if cut > radius + 1e-9:
        raise GeometryError(f"Срез {cut:g} мм глубже радиуса {radius:g} мм.",
                            hint="Можно отсечь не больше верхней половины: cut≤radius, slice≤1.")
    cut = min(radius, max(0.0, cut))
    round_r = _round_value(a)
    if round_r > 1e-9 and cut <= 1e-9:
        raise GeometryError("round относится к кромке среза: задайте slice>0 или cut>0.")
    if cut > 1e-9:
        solid = _sliced_sphere(radius, cut, round_r, segments)
    else:
        solid = mf.Manifold.sphere(radius, segments)
    at = a.vec("at", 3, default=(0, 0, 0))
    # at остаётся центром исходного шара, поэтому slice=1 даёт ровную
    # нижнюю полусферу z∈[at.z-radius, at.z], а не перецентрированный обрезок.
    solid = solid.translate(tuple(float(v) for v in at))
    out = make_solid(a.scene, name, solid, a, kind="sphere")
    if cut > 1e-9:
        out.meta["slice"] = {"cut_mm": cut, "plane_z": float(at[2] + radius - cut),
                             "round": round_r}
        out.notes.append(f"срез сверху {cut:g} мм, кромка round={round_r:g}")
    return out


@op("cylinder", aliases=("цилиндр", "труба", "стакан"),
    category="Примитивы",
    summary="Цилиндр или усечённый конус с независимой верхней плоскостью: "
            "r2 и top_scale меняют её полуоси, top_offset сдвигает центр. "
            "По умолчанию стоит на полу.",
    example="корпус = cylinder radius=40 height=90 segments=128 round=3\n"
            "наклонный = cylinder radius=40 r2=30 height=70 top_offset=[18,-8]\n"
            "эллипс = cylinder radius=40 height=60 top_scale=[1.3,0.7]",
    params={"radius": "радиус снизу, мм (обязательно)",
            "height": "высота, мм (обязательно)",
            "r2": "радиус сверху до top_scale (по умолчанию равен нижнему)",
            "top_scale": "независимые множители верхней плоскости [sx,sy] (1,1)",
            "top_offset": "сдвиг центра верхней плоскости [dx,dy], мм (0,0)",
            "segments": "число сегментов (по умолчанию — по детализации)",
            "detail": "детализация 0…5 (3): больше — глаже и тяжелее",
            "round": "скругление верхней и нижней кромки, мм; со сдвигом/эллипсом "
                     "верха применяется общее скругление тела",
            "center": "центрировать по высоте",
            "at": "положение [x,y,z]"},
    positional=["radius", "height"])
def cylinder(a, name):
    radius = float(a.num("radius", required=True, minv=0.01))
    height = float(a.num("height", required=True, minv=0.01))
    r2 = float(a.num("r2", radius, minv=0.0) or 0.0)
    scale = _top_scale(a)
    offset = _top_offset(a)
    custom = a.has("top_scale") or float(np.linalg.norm(offset)) > 1e-12
    segments = _segments(a, a.int("segments", None, minv=8, maxv=1024),
                         max(radius, r2 * float(scale.max())))
    r = _round_value(a)
    if not custom:
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
    else:
        angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
        bottom = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
        top = np.column_stack([r2 * scale[0] * np.cos(angles),
                               r2 * scale[1] * np.sin(angles)]) + offset
        solid = _two_ring_hull(bottom, top, height)
        if r > 1e-6:
            if height <= 2 * r + 1e-6:
                raise GeometryError("round слишком велик для высоты цилиндра.")
            solid = _rounded_convex(solid, r, a, "цилиндр")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="cylinder")
    if custom:
        out.notes.append(f"верх: полуоси {(r2 * scale).tolist()}, сдвиг {offset.tolist()}")
    return out


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
    summary="N-угольная призма с независимой верхней гранью: r2/top_scale меняют "
            "размер, top_offset сдвигает, twist поворачивает. При sides=4 "
            "base_angle делает ромб/параллелограмм. smooth=0…4 — Loop-сглаживание.",
    example="гайка = prism sides=6 radius=20 height=12\n"
            "наклонная = prism sides=6 radius=30 r2=20 height=50 top_offset=[12,5]\n"
            "ромб = prism sides=4 radius=30 height=35 base_angle=60 smooth=1",
    params={"sides": "число сторон (6)", "radius": "радиус описанной окружности, мм; "
            "для ромба sides=4 сторона равна √2·radius",
            "r2": "радиус верхней грани до top_scale (по умолчанию равен нижнему)",
            "top_scale": "независимые множители верхней грани [sx,sy] (1,1)",
            "top_offset": "сдвиг центра верхней грани [dx,dy], мм (0,0)",
            "base_angle": "угол ромба при sides=4, 15…165° (90 — обычная призма)",
            "twist": "закрутка верхней грани, градусы",
            "smooth": "уровни Loop-сглаживания 0…4 (0 — плоские грани); габарит сохраняется",
            "height": "высота, мм", "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def prism(a, name):
    sides = int(a.int("sides", 6, minv=3, maxv=256))
    radius = float(a.num("radius", required=True, minv=0.01))
    height = float(a.num("height", required=True, minv=0.01))
    r2 = float(a.num("r2", radius, minv=0.0) or 0.0)
    twist = float(a.num("twist", 0.0) or 0.0)
    scale = _top_scale(a)
    offset = _top_offset(a)
    angle = _base_angle(a)
    custom = (a.has("top_scale") or float(np.linalg.norm(offset)) > 1e-12
              or abs(angle - 90.0) > 1e-9)
    prof = _base_profile(radius, sides, angle)
    if not custom:
        if abs(r2 - radius) < 1e-9 and abs(twist) < 1e-9:
            solid = mf.CrossSection([prof]).extrude(height)
        else:
            solid = mf.CrossSection([prof]).extrude(
                height, 0, twist, (r2 / radius,) * 2)
    else:
        top = prof * (r2 / radius) * scale + offset
        if abs(twist) > 1e-9:
            theta = math.radians(twist)
            rot = np.array([[math.cos(theta), -math.sin(theta)],
                            [math.sin(theta), math.cos(theta)]])
            top = (top - offset) @ rot.T + offset
        solid = _two_ring_hull(prof, top, height)
    solid = _smooth_primitive(solid, a, "призма")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="prism")
    if custom:
        out.notes.append(f"верх: r2={r2:g}, scale={scale.tolist()}, сдвиг {offset.tolist()}")
    if _smooth_level(a):
        out.notes.append(f"Loop-сглаживание, уровень {_smooth_level(a)}")
    return out


@op("pyramid", aliases=("пирамида", "tetra", "пирамидка"), category="Примитивы",
    summary="N-угольная пирамида с вершиной в произвольной точке, над стороной "
            "или углом основания. При sides=4 base_angle делает основание "
            "параллелограммом; smooth=0…4 сглаживает тело с сохранением габарита.",
    example="пирамида = pyramid sides=4 radius=60 height=90\n"
            "на_угол = pyramid sides=4 radius=60 height=90 tip_at=corner tip_index=0\n"
            "ромб = pyramid sides=4 radius=60 height=80 base_angle=60 tip_at=edge",
    params={"sides": "число сторон основания (4)",
            "radius": "радиус описанной окружности основания, мм; для ромба "
                      "сторона равна √2·radius",
            "height": "высота, мм (обязательно)",
            "tip": "точное смещение вершины от центра [x,y], мм; нельзя вместе с tip_at",
            "tip_at": "center — над центром, edge — над серединой стороны, "
                      "corner — над углом (center)",
            "tip_index": "номер стороны/угла 0…sides−1 (0); сторона идёт от "
                         "вершины i к i+1",
            "base_angle": "угол параллелограмма при sides=4, 15…165° (90 — обычное основание)",
            "smooth": "уровни Loop-сглаживания 0…4 (0 — плоские грани); габарит сохраняется",
            "center": "центрировать по высоте", "at": "положение [x,y,z]"},
    positional=["radius", "height"])
def pyramid(a, name):
    sides = int(a.int("sides", 4, minv=3, maxv=128))
    radius = float(a.num("radius", required=True, minv=0.01))
    height = float(a.num("height", required=True, minv=0.01))
    angle = _base_angle(a)
    base = _base_profile(radius, sides, angle)
    if a.has("tip") and a.has("tip_at"):
        raise GeometryError("Задайте вершину одним способом: tip=[x,y] ИЛИ tip_at.")
    if a.has("tip") and a.has("tip_index"):
        raise GeometryError("tip_index относится к tip_at, а не к числовому tip=[x,y].")
    if a.has("tip"):
        tip = np.asarray(a.vec("tip", 2), dtype=np.float64)
        tip_mode = "custom"
    else:
        raw_mode = (a.text("tip_at", "center") or "center").strip().lower()
        aliases = {"центр": "center", "центра": "center",
                   "сторона": "edge", "грань": "edge", "ребро": "edge",
                   "край": "edge", "boundary": "edge", "side": "edge",
                   "угол": "corner", "вершина": "corner", "vertex": "corner"}
        tip_mode = aliases.get(raw_mode, raw_mode)
        if tip_mode not in ("center", "edge", "corner"):
            raise GeometryError("tip_at: center, edge (сторона) или corner (угол).")
        index = int(a.int("tip_index", 0, minv=0, maxv=sides - 1))
        if tip_mode == "corner":
            tip = base[index].copy()
        elif tip_mode == "edge":
            tip = (base[index] + base[(index + 1) % sides]) * 0.5
        else:
            # Карточка держит tip_index видимым и при center: в этом режиме
            # индекс просто не участвует. Без явного tip_at такая команда
            # по-прежнему считается ошибочной, чтобы не скрывать опечатку.
            if a.has("tip_index") and not a.has("tip_at"):
                raise GeometryError("tip_index нужен только при tip_at=edge или corner.")
            tip = np.zeros(2, dtype=np.float64)
    ring = np.column_stack([base, np.zeros(len(base))])
    pts = np.vstack([ring, np.asarray([[tip[0], tip[1], height]])])
    solid = mf.Manifold.hull_points(np.ascontiguousarray(pts, dtype=np.float64))
    solid = _smooth_primitive(solid, a, "пирамида")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="pyramid")
    out.meta["tip"] = {"mode": tip_mode, "xy_before_anchor": tip.tolist()}
    if tip_mode != "center":
        out.notes.append(f"вершина: {tip_mode}, XY {tip.tolist()}")
    return out


@op("icosphere", aliases=("икосфера", "ико", "ico"), category="Примитивы",
    summary="Геодезическая сфера с четырьмя топологиями: triangle — треугольники, "
            "quad — квадратные панели куб-сферы, pentagon — додекаэдр на уровне 0, "
            "honeycomb — соты из шестиугольников и неизбежных 12 пятиугольников.",
    example="гранёный = icosphere radius=40 divisions=0\n"
            "квадраты = icosphere radius=40 mode=quad divisions=2\n"
            "сота = icosphere radius=40 mode=сота divisions=2",
    params={"radius": "радиус описанной сферы, мм (обязательно)",
            "mode": "triangle/треугольный, quad/квадратный, pentagon/пятиугольник, "
                    "honeycomb/сота/шестиугольник (triangle)",
            "divisions": "уровень 0…5 (2): 0 — базовые 20 треугольников, 6 квадратов "
                         "или 12 пятиугольников; каждый уровень делит панели на 4",
            "at": "центр [x,y,z]"},
    positional=["radius"])
def icosphere(a, name):
    import trimesh

    radius = float(a.num("radius", required=True, minv=0.01))
    divisions = int(a.int("divisions", 2, minv=0, maxv=5))
    raw_mode = (a.text("mode", "triangle") or "triangle").strip().lower()
    modes = {
        "triangle": "triangle", "tri": "triangle", "треугольный": "triangle",
        "треугольники": "triangle", "три": "triangle",
        "quad": "quad", "square": "quad", "квадратный": "quad",
        "квадрат": "quad", "квадраты": "quad",
        "pentagon": "dual", "pentagonal": "dual", "пятиугольник": "dual",
        "пятиугольный": "dual", "додекаэдр": "dual",
        "honeycomb": "dual", "hex": "dual", "hexagon": "dual",
        "сота": "dual", "соты": "dual", "шестиугольник": "dual",
        "шестиугольный": "dual",
    }
    if raw_mode not in modes:
        raise GeometryError("mode икосферы: triangle, quad, pentagon или honeycomb (сота).")
    mode = modes[raw_mode]
    if mode == "triangle":
        mesh = trimesh.creation.icosphere(subdivisions=divisions, radius=radius)
        verts, faces = mesh.vertices, mesh.faces
        topology = {"panels": len(faces), "quads": 0,
                    "pentagons": 0, "hexagons": 0, "grid": 2 ** divisions}
    elif mode == "quad":
        verts, faces, topology = cube_sphere(radius, divisions)
    else:
        verts, faces, topology = dual_sphere(radius, divisions)
    solid = manifold_from_arrays(verts, faces, "икосферы")
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    out = make_solid(a.scene, name, solid, a, kind="icosphere")
    topology.update({"mode": raw_mode, "family": mode, "divisions": divisions,
                     "triangles": int(solid.num_tri())})
    out.meta["topology"] = topology
    out.notes.append(f"икосфера {raw_mode}: панелей {topology['panels']}, "
                     f"треугольников ядра {solid.num_tri()}")
    return out


@op("octa", aliases=("октаэдр", "октаедр", "восьмигранник", "octahedron"), category="Примитивы",
    summary="Октаэдр с наращиваемой сеткой: divisions=0…4 делит каждую грань "
            "на 4^N треугольников без изменения формы, smooth=0…4 выполняет "
            "настоящее Loop-сглаживание с сохранением габарита. Стоит на полу.",
    example="кристалл = octa radius=30 height=80\n"
            "подробный = octa radius=30 height=80 divisions=2\n"
            "гладкий = octa radius=30 height=80 divisions=1 smooth=1",
    params={"radius": "полуширина по X и Y, мм (обязательно)",
            "height": "полная высота, мм (по умолчанию 2·radius)",
            "depth": "полуширина по Y, если она отличается от X (radius)",
            "divisions": "дополнительные вершины 0…4 (0): 6 вершин/8 граней, "
                         "далее каждая грань делится на 4 без скругления",
            "smooth": "уровни Loop-сглаживания 0…4 (0 — исходные плоские грани)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius"])
def octa(a, name):
    radius = float(a.num("radius", required=True, minv=0.01))
    depth = a.num("depth", None, minv=0.01)
    depth = float(radius if depth is None else depth)
    height = a.num("height", None, minv=0.01)
    height = float(2.0 * radius if height is None else height)
    divisions = int(a.int("divisions", 0, minv=0, maxv=4))
    half = height / 2.0
    pts = np.asarray([[radius, 0.0, 0.0], [-radius, 0.0, 0.0],
                      [0.0, depth, 0.0], [0.0, -depth, 0.0],
                      [0.0, 0.0, half], [0.0, 0.0, -half]], dtype=np.float64)
    faces = np.asarray([(4, 0, 2), (4, 2, 1), (4, 1, 3), (4, 3, 0),
                        (5, 2, 0), (5, 1, 2), (5, 3, 1), (5, 0, 3)], dtype=np.int64)
    pts, faces = linear_subdivide(pts, faces, divisions)
    solid = manifold_from_arrays(pts, faces, "октаэдра")
    solid = _smooth_primitive(solid, a, "октаэдр")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="octa")
    out.notes.append(f"октаэдр {2 * radius:g}×{2 * depth:g}×{height:g} мм, "
                     f"{solid.num_tri()} треугольников, divisions={divisions}, "
                     f"smooth={_smooth_level(a)}")
    return out


@op("ellipsoid", aliases=("эллипсоид", "яйцевидный_шар", "ellipsoid"), category="Примитивы",
    summary="Эллипсоид — шар, растянутый по осям отдельно. Полуоси задаются "
            "по X, Y и Z; ровный и гладкий, в отличие от масштабирования шара "
            "командой scale у него честные полуоси в миллиметрах.",
    example="дно = ellipsoid x=60 y=40 z=22\n"
            "капля = ellipsoid x=25 y=25 z=60 at=[0,0,20]\n"
            "геодезический = ellipsoid x=60 y=40 z=22 divisions=2",
    params={"x": "полуось по X, мм (обязательно)",
            "y": "полуось по Y (по умолчанию — как X)",
            "z": "полуось по Z (по умолчанию — как X)",
            "divisions": "геодезические уровни 0…5: 20 → 80 → 320… треугольников; "
                         "альтернатива detail/segments",
            "detail": "детализация UV-сферы 0…5 (3): 0 — гранёный, 5 — гладкий",
            "segments": "сегментов UV-сферы по кругу (по детализации)",
            "center": "центрировать по высоте",
            "at": "положение [x,y,z]"},
    positional=["x"])
def ellipsoid(a, name):
    x = float(a.num("x", required=True, minv=0.01))
    y = a.num("y", None, minv=0.01)
    z = a.num("z", None, minv=0.01)
    y = float(x if y is None else y)
    z = float(x if z is None else z)
    if a.has("divisions"):
        if a.has("detail") or a.has("segments"):
            raise GeometryError("Эллипсоид: выберите divisions ИЛИ detail/segments, не оба способа.")
        import trimesh
        divisions = int(a.int("divisions", 2, minv=0, maxv=5))
        mesh = trimesh.creation.icosphere(subdivisions=divisions, radius=1.0)
        unit = np.asarray(mesh.vertices, dtype=np.float64)
        # Даже у грубого икосаэдра полуоси остаются честными миллиметрами:
        # нормируем фактические границы до ±1 перед анизотропным масштабом.
        unit /= np.maximum(np.abs(unit).max(axis=0), 1e-12)
        solid = manifold_from_arrays(unit, mesh.faces, "эллипсоида")
        solid = solid.scale((x, y, z))
        detail_note = f"divisions={divisions}"
    else:
        segments = _segments(a, a.int("segments", None, minv=8, maxv=512), max(x, y, z))
        solid = mf.Manifold.sphere(1.0, segments).scale((x, y, z))
        detail_note = f"segments={segments}"
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="ellipsoid")
    out.notes.append(f"полуоси {x:g}×{y:g}×{z:g} мм, {detail_note}")
    return out


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
