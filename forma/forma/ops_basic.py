"""Примитивы: куб, сфера, цилиндр, конус, тор, призма, капсула, оболочка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (FINENESS_MM, auto_segments, circle_profile, hull_of_manifolds,
                       limit_segments, manifold_from_arrays, manifold_mesh)
from .ops import anchor, detail_factor, detail_level, ensure_solid, make_solid, op
from .primitive_topology import (cube_sphere, honeycomb_sphere, linear_subdivide,
                                 loop_smooth, pentagon_sphere)
from .shape_features import transition_radius


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


def _expansion_options(a):
    amount = float(a.num("expand", a.num("expansion", a.num("expand_degree", 0.0,
                         minv=0.0, maxv=2.0), minv=0.0, maxv=2.0), minv=0.0, maxv=2.0) or 0.0)
    raw = (a.text("expand_side", a.text("expanded_half", "верх")) or "верх").strip().lower()
    side = {"верх": 1.0, "верхняя": 1.0, "top": 1.0, "да": 1.0,
            "низ": -1.0, "нижняя": -1.0, "bottom": -1.0,
            "нет": 0.0, "none": 0.0, "no": 0.0}.get(raw)
    if side is None:
        raise GeometryError("expand_side/expanded_half: верх, низ или нет.")
    if side == 0.0:
        amount = 0.0
    smooth = float(a.num("expand_smooth", a.num("expand_transition", 0.0,
                         minv=0.0, maxv=1.0), minv=0.0, maxv=1.0))
    raw_joint = (a.text("expand_joint", "посадка") or "посадка").strip().lower()
    joint = {"посадка": "посадка", "колпачок": "посадка", "таблетка": "посадка",
             "нахлест": "посадка", "нахлёст": "посадка", "cap": "посадка",
             "стык": "стык", "точный": "стык", "ровный": "стык",
             "flush": "стык", "butt": "стык"}.get(raw_joint)
    if joint is None:
        raise GeometryError("expand_joint: посадка (колпачок) или стык (без нахлёста).")
    seat = a.num("expand_seat", None, minv=0.0)
    if joint == "стык" and seat is not None and float(seat) > 1e-9:
        raise GeometryError("expand_seat работает только при expand_joint=посадка.",
                            hint="Для точного стыка задайте expand_seat=0 или уберите параметр.")
    return amount, side, smooth, joint, None if seat is None else float(seat)


def _expansion_transition(cross: mf.CrossSection, center: tuple[float, float],
                          z0: float, z1: float, factor: float,
                          reverse: bool, what: str) -> mf.Manifold:
    """Гладкий loft от исходного сечения к увеличенному, с нулевым уклоном на концах."""
    polygons = cross.to_polygons()
    if len(polygons) != 1:
        raise GeometryError(f"{what}: посадка требует сплошное сечение без отверстий")
    ring = np.asarray(polygons[0], dtype=float)
    area = float(np.sum(ring[:, 0] * np.roll(ring[:, 1], -1)
                        - ring[:, 1] * np.roll(ring[:, 0], -1)))
    if area < 0.0:
        ring = ring[::-1]
    cx, cy = center
    steps = 20
    verts = []
    for i in range(steps + 1):
        t = i / steps
        w = t * t * (3.0 - 2.0 * t)
        if reverse:
            w = 1.0 - w
        scale = 1.0 + (factor - 1.0) * w
        xy = (ring - np.asarray([cx, cy])) * scale + np.asarray([cx, cy])
        verts.extend((float(x), float(y), z0 + (z1 - z0) * t) for x, y in xy)
    n = len(ring)
    faces: list[tuple[int, int, int]] = []
    for i in range(steps):
        for j in range(n):
            j2 = (j + 1) % n
            a0, b0 = i * n, (i + 1) * n
            faces.extend(((a0 + j, a0 + j2, b0 + j2),
                          (a0 + j, b0 + j2, b0 + j)))
    for tri in np.asarray(mf.triangulate([ring]), dtype=np.int64):
        i, j, k = (int(v) for v in tri)
        faces.append((k, j, i))
        faces.append((steps * n + i, steps * n + j, steps * n + k))
    varr = np.asarray(verts, dtype=float)
    farr = np.asarray(faces, dtype=np.int64)
    p0, p1, p2 = varr[farr[:, 0]], varr[farr[:, 1]], varr[farr[:, 2]]
    if float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum()) < 0.0:
        farr = farr[:, ::-1]
    return manifold_from_arrays(varr, farr, what)


def _expand_half(solid: mf.Manifold, amount: float, side: float, smooth: float,
                 what: str, joint: str = "посадка",
                 seat: float | None = None) -> tuple[mf.Manifold, dict]:
    """Собирает две половины с точным стыком или посадкой типа колпачка.

    Большая половина масштабируется только по X/Y. При посадке её пояс
    заходит на меньшую часть на ``seat`` миллиметров; объединение удаляет
    скрытые общие грани. При smooth>0 внешняя ступень заменяется гладким
    loft-переходом. Противоположная часть вне этой зоны не деформируется.
    """
    info = {"expand_joint": joint, "expand_seat": 0.0, "expand_transition_mm": 0.0}
    if amount <= 1e-9 or side == 0.0:
        return solid, info
    bb = solid.bounding_box()
    mid = (bb[2] + bb[5]) * 0.5
    span = max((bb[5] - bb[2]) * 0.5, 1e-9)
    seat = (span * 0.12 if joint == "посадка" else 0.0) if seat is None else float(seat)
    if seat > span * 0.45 + 1e-9:
        raise GeometryError(f"{what}: expand_seat не должен превышать {span * 0.45:g} мм.",
                            hint="Уменьшите посадочный пояс, чтобы оставить меньшую половину открытой.")
    transition = min(smooth * span * 0.55, max(0.0, span - seat - 1e-5))
    info.update(expand_seat=seat, expand_transition_mm=transition)
    upper = solid.trim_by_plane((0.0, 0.0, 1.0), mid)
    lower = solid.trim_by_plane((0.0, 0.0, -1.0), -mid)
    cx, cy = (bb[0] + bb[3]) * 0.5, (bb[1] + bb[4]) * 0.5
    factor = 1.0 + amount
    matrix = np.asarray([[factor, 0.0, 0.0, cx * (1.0 - factor)],
                         [0.0, factor, 0.0, cy * (1.0 - factor)],
                         [0.0, 0.0, 1.0, 0.0]], dtype=float)
    larger = (upper if side > 0 else lower).transform(matrix)
    smaller = lower if side > 0 else upper
    cross = solid.slice(mid)
    if cross.is_empty() or cross.area() <= 1e-9:
        raise GeometryError(f"{what}: не удалось получить сечение посадки")
    scaled_cross = cross.translate((-cx, -cy)).scale((factor, factor)).translate((cx, cy))
    parts = [smaller, larger]
    if seat > 1e-9:
        collar_z = mid - seat if side > 0 else mid
        parts.append(scaled_cross.extrude(seat).translate((0.0, 0.0, collar_z)))
    if transition > 1e-9:
        if side > 0:
            z1 = mid - seat
            z0 = z1 - transition
        else:
            z0 = mid + seat
            z1 = z0 + transition
        parts.append(_expansion_transition(cross, (cx, cy), z0, z1, factor,
                                           reverse=side < 0, what=what))
    elif seat <= 1e-9:
        # Точный стык: тонкая перемычка целиком находится внутри обеих
        # половин. Она даёт булеву объём пересечения, не меняя наружную форму.
        eps = max(1e-4, span * 1e-4)
        parts.append(cross.extrude(2.0 * eps).translate((0.0, 0.0, mid - eps)))
    result = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    positive = [p for p in result.decompose() if p.volume() > 1e-7]
    if (result.is_empty() or result.status() != mf.Error.NoError
            or result.volume() <= solid.volume() or len(positive) != 1):
        raise GeometryError(f"{what}: половины не образовали единое замкнутое тело.")
    return result, info


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
    summary="Параллелепипед с независимой верхней плоскостью и посадкой половин. "
            "top_size меняет верх, expand увеличивает выбранную половину по X/Y; "
            "expand_joint=посадка добавляет скрытый пояс колпачка, стык соединяет "
            "без нахлёста, expand_smooth сглаживает внешний переход. "
            "base_angle=не 90 делает в основании параллелограмм. Сильный round "
            "превращает коробку в овальную/круглую форму. Отверстий у обычного "
            "блока нет: для центральных сквозных отверстий используется cube_hole. "
            "По умолчанию стоит на полу.",
    example="блок = box size=[120,80,50] top_size=[80,50] top_offset=[15,-5]\n"
            "скошенный = box size=[100,70,40] base_angle=65",
    params={"size": "стороны нижнего основания и высота [x,y,z], мм (обязательно)",
            "top_size": "стороны верхней плоскости [x,y], мм (по умолчанию как снизу)",
            "top_offset": "сдвиг центра верхней плоскости относительно нижней [dx,dy], мм",
            "expand": "увеличение выбранной половины по X/Y 0…2 (0 — обычные половины)",
            "expand_side": "большая половина: верх или низ (верх)",
            "expand_joint": "посадка — колпачок с поясом; стык — без нахлёста (посадка)",
            "expand_seat": "скрытый заход пояса на меньшую половину, мм (авто: 12% полувысоты)",
            "expand_smooth": "плавный внешний переход 0…1; 0 — чёткая кромка (0)",
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
    hole_params = [f"hole_{axis}{suffix}" for axis in ("x", "y", "z")
                   for suffix in ("", "_shape")] + ["oval_aspect"]
    if any(a.has(key) for key in hole_params):
        raise GeometryError("У обычного box отверстий больше нет.",
                            hint="Используйте cube_hole: отверстия остаются по центру, "
                                 "поддерживаются hole_x/hole_y/hole_z и их формы.")
    expand, expand_side, expand_smooth, expand_joint, expand_seat = _expansion_options(a)
    solid, expand_info = _expand_half(solid, expand, expand_side, expand_smooth, "блока",
                                      expand_joint, expand_seat)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="box")
    if custom:
        out.notes.append(f"верх {tx:g}×{ty:g}, сдвиг {offset.tolist()}, угол основания {angle:g}°")
    if expand > 1e-9:
        out.meta.update(expanded_half="верх" if expand_side > 0 else "низ",
                        expand=expand, expand_smooth=expand_smooth, **expand_info)
        out.notes.append(f"половина {'верх' if expand_side > 0 else 'низ'} +{expand * 100:g}%, "
                         f"{expand_joint}, пояс {expand_info['expand_seat']:g} мм, "
                         f"переход {expand_info['expand_transition_mm']:g} мм")
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
            "expand": "расширение выбранной половины по радиусу 0…2 (0 — нет)",
            "expansion": "синоним expand",
            "expand_degree": "синоним expand",
            "expand_side": "расширяемая половина: верх или низ (верх)",
            "expanded_half": "синоним expand_side",
            "expand_smooth": "плавность внешнего перехода 0…1; 0 — чёткая кромка (0)",
            "expand_transition": "синоним expand_smooth",
            "expand_joint": "посадка — колпачок с поясом; стык — без нахлёста (посадка)",
            "expand_seat": "заход пояса на меньшую половину, мм (авто: 12% полувысоты)",
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
    expand, expand_side, expand_smooth, expand_joint, expand_seat = _expansion_options(a)
    solid, expand_info = _expand_half(solid, expand, expand_side, expand_smooth, "сферы",
                                      expand_joint, expand_seat)
    at = a.vec("at", 3, default=(0, 0, 0))
    # at остаётся центром исходного шара, поэтому slice=1 даёт ровную
    # нижнюю полусферу z∈[at.z-radius, at.z], а не перецентрированный обрезок.
    solid = solid.translate(tuple(float(v) for v in at))
    out = make_solid(a.scene, name, solid, a, kind="sphere")
    if cut > 1e-9:
        out.meta["slice"] = {"cut_mm": cut, "plane_z": float(at[2] + radius - cut),
                             "round": round_r}
        out.notes.append(f"срез сверху {cut:g} мм, кромка round={round_r:g}")
    if expand > 1e-9:
        out.meta.update(expanded_half="верх" if expand_side > 0 else "низ",
                        expand=expand, expand_smooth=expand_smooth, **expand_info)
        out.notes.append(f"расширенная половина {'верх' if expand_side > 0 else 'низ'}: "
                         f"+{expand * 100:g}%, {expand_joint}, пояс {expand_info['expand_seat']:g} мм, "
                         f"переход {expand_info['expand_transition_mm']:g} мм")
    return out


def _cavity_choice(raw: str) -> str:
    value = {"верх": "верх", "сверху": "верх", "top": "верх",
             "низ": "низ", "снизу": "низ", "bottom": "низ"}.get(
                 (raw or "верх").strip().lower())
    if value is None:
        raise GeometryError("cavity: верх или низ — сторона слепой полости.")
    return value


@op("cylinder", aliases=("цилиндр", "труба", "стакан"),
    category="Примитивы",
    summary="Цилиндр или усечённый конус с независимой верхней плоскостью. "
            "wall>0 создаёт НЕСКВОЗНУЮ полость: cavity выбирает открытый верх "
            "или низ, cavity_depth — глубину, а противоположное дно остаётся "
            "не тоньше wall. По умолчанию тело сплошное и стоит на полу.",
    example="корпус = cylinder radius=40 height=90 segments=128 round=3\n"
            "стакан = cylinder radius=40 height=90 wall=3 cavity=верх\n"
            "колпак = cylinder radius=40 height=70 wall=2 cavity=низ cavity_depth=55\n"
            "эллипс = cylinder radius=40 height=60 top_scale=[1.3,0.7]",
    params={"radius": "радиус снизу, мм (обязательно)",
            "height": "высота, мм (обязательно)",
            "r2": "радиус сверху до top_scale (по умолчанию равен нижнему)",
            "top_scale": "независимые множители верхней плоскости [sx,sy] (1,1)",
            "top_offset": "сдвиг центра верхней плоскости [dx,dy], мм (0,0)",
            "wall": "стенка и минимальное дно слепой полости, мм; 0 — сплошной (0)",
            "cavity": "открытая сторона при wall>0: верх или низ (верх)",
            "cavity_depth": "глубина от открытой стороны, мм (height−wall); "
                            "не пробивает противоположное дно",
            "segments": "число сегментов (по умолчанию — по детализации)",
            "detail": "детализация 0…5 (3): больше — глаже и тяжелее",
            "round": "скругление верхней и нижней кромки, мм",
            "center": "центрировать по высоте", "at": "положение [x,y,z]"},
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
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if wall > 1e-6:
        if wall >= height - 0.1:
            raise GeometryError("wall не оставляет высоты для слепой полости.")
        side = _cavity_choice(a.text("cavity", "верх"))
        depth = float(a.num("cavity_depth", height - wall,
                            minv=0.1, maxv=height - wall))
        angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)

        def inner_ring(z):
            t = float(z) / height
            center = offset * t
            rx = (1.0 - t) * radius + t * r2 * float(scale[0]) - wall
            ry = (1.0 - t) * radius + t * r2 * float(scale[1]) - wall
            if min(rx, ry) <= 0.05:
                raise GeometryError("wall слишком велик для радиуса на дне полости.",
                                    hint="Уменьшите wall или cavity_depth.")
            return np.column_stack([rx * np.cos(angles), ry * np.sin(angles)]) + center

        z0, z1 = ((height - depth, height + 1.0) if side == "верх"
                  else (-1.0, depth))
        tool = _two_ring_hull(inner_ring(z0), inner_ring(z1), height,
                              z_bottom=z0, z_top=z1)
        before = solid.volume()
        solid = solid - tool
        if solid.is_empty() or len(solid.decompose()) != 1 or solid.volume() >= before - 1e-6:
            raise GeometryError("Не удалось вырезать слепую полость цилиндра.")
    elif a.has("cavity_depth"):
        raise GeometryError("cavity_depth работает при wall>0.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="cylinder")
    if custom:
        out.notes.append(f"верх: полуоси {(r2 * scale).tolist()}, сдвиг {offset.tolist()}")
    if wall > 1e-6:
        out.meta.update({"wall": wall, "cavity": side, "cavity_depth": depth})
        out.notes.append(f"слепая полость: {side}, глубина {depth:g}, стенка {wall:g} мм")
    return out


def _cone_radius(radius: float, t: float, form: str) -> float:
    t = min(1.0, max(0.0, float(t)))
    if form == "парабола":
        return radius * (1.0 - t * t)
    if form == "холмик":
        return radius * math.sqrt(max(0.0, 1.0 - t * t))
    return radius * (1.0 - t)


def _cone_profile(radius: float, height: float, form: str,
                  samples: int = 32) -> list[tuple[float, float]]:
    count = 1 if form == "прямой" else max(12, int(samples))
    pts = [(0.0, 0.0)]
    for i in range(count + 1):
        t = i / count
        pts.append((_cone_radius(radius, t, form), height * t))
    return pts


def _cone_solid(radius: float, height: float, form: str,
                segments: int, samples: int = 32) -> mf.Manifold:
    profile = _cone_profile(radius, height, form, samples)
    solid = mf.Manifold.revolve(mf.CrossSection([profile]), int(segments))
    if solid.is_empty() or solid.volume() <= 1e-8:
        raise GeometryError("Не удалось построить профиль конуса.")
    return solid


@op("cone", aliases=("конус",), category="Примитивы",
    summary="Конус/горка на полу. form=прямой — линейный профиль; парабола — "
            "R·(1−t²); холмик — R·√(1−t²) с округлой вершиной. wall>0 "
            "открывает полость снизу и оставляет вершину; smooth сглаживает "
            "боковую поверхность с восстановлением наружных габаритов.",
    example="конус = cone radius=30 height=60\n"
            "горка = cone radius=40 height=55 form=парабола\n"
            "холм = cone radius=40 height=45 form=холмик smooth=1\n"
            "оболочка = cone radius=35 height=70 wall=2.5 cavity_depth=60",
    params={"radius": "радиус основания, мм", "height": "высота, мм",
            "form": "прямой, парабола или холмик (прямой)",
            "wall": "радиальная стенка и минимальная толщина вершины, мм; "
                    "0 — сплошной, >0 — полость открыта снизу (0)",
            "cavity_depth": "глубина полости от основания, мм (height−wall)",
            "smooth": "Loop-сглаживание 0…4; габариты сохраняются (0)",
            "detail": "детализация 0…5 (3)", "segments": "сегментов (по детализации)",
            "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def cone(a, name):
    radius = float(a.num("radius", required=True, minv=0.01))
    height = float(a.num("height", required=True, minv=0.01))
    raw_form = (a.text("form", "прямой") or "прямой").strip().lower()
    form = {"прямой": "прямой", "конус": "прямой", "straight": "прямой",
            "парабола": "парабола", "параболический": "парабола",
            "параболическая": "парабола", "горка": "парабола",
            "холмик": "холмик", "холм": "холмик", "купол": "холмик",
            "dome": "холмик"}.get(raw_form)
    if form is None:
        raise GeometryError("cone: form=прямой, парабола или холмик.")
    segments = _segments(a, a.int("segments", None, minv=8, maxv=1024), radius)
    solid = _cone_solid(radius, height, form, segments)
    if _smooth_level(a):
        solid = _smooth_primitive(solid, a, "конус")
        bb = solid.bounding_box()
        sx = 2.0 * radius / max(bb[3] - bb[0], 1e-9)
        sy = 2.0 * radius / max(bb[4] - bb[1], 1e-9)
        sz = height / max(bb[5] - bb[2], 1e-9)
        matrix = np.eye(3, 4)
        matrix[0, 0], matrix[1, 1], matrix[2, 2] = sx, sy, sz
        matrix[2, 3] = -bb[2] * sz
        solid = solid.transform(matrix)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if wall > 1e-6:
        if wall >= radius - 0.05 or wall >= height - 0.1:
            raise GeometryError("wall слишком велик для полого конуса.")
        depth = float(a.num("cavity_depth", height - wall,
                            minv=0.1, maxv=height - wall))
        inner = _cone_solid(radius - wall, depth, form, segments)
        opening = mf.Manifold.cylinder(1.2, radius - wall, radius - wall,
                                       segments).translate((0.0, 0.0, -1.05))
        before = solid.volume()
        solid = solid - (inner + opening)
        if solid.is_empty() or len(solid.decompose()) != 1 or solid.volume() >= before - 1e-6:
            raise GeometryError("Не удалось вырезать полость конуса.")
    elif a.has("cavity_depth"):
        raise GeometryError("cavity_depth работает при wall>0.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="cone")
    out.meta["form"] = form
    if wall > 1e-6:
        out.meta.update({"wall": wall, "cavity": "низ", "cavity_depth": depth})
        out.notes.append(f"полость снизу: глубина {depth:g}, стенка {wall:g} мм")
    return out


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
            "base_angle делает ромб/параллелограмм. smooth=0…4 — Loop-сглаживание. "
            "wall>0 вырезает слепую полость сверху или снизу с равномерным "
            "внутренним смещением многоугольных стенок.",
    example="гайка = prism sides=6 radius=20 height=12\n"
            "наклонная = prism sides=6 radius=30 r2=20 height=50 top_offset=[12,5]\n"
            "ромб = prism sides=4 radius=30 height=35 base_angle=60 smooth=1\n"
            "стакан = prism sides=6 radius=35 height=60 wall=3 cavity=верх",
    params={"sides": "число сторон (6)", "radius": "радиус описанной окружности, мм; "
            "для ромба sides=4 сторона равна √2·radius",
            "r2": "радиус верхней грани до top_scale (по умолчанию равен нижнему)",
            "top_scale": "независимые множители верхней грани [sx,sy] (1,1)",
            "top_offset": "сдвиг центра верхней грани [dx,dy], мм (0,0)",
            "base_angle": "угол ромба при sides=4, 15…165° (90 — обычная призма)",
            "twist": "закрутка верхней грани, градусы",
            "wall": "стенка и минимальное дно слепой полости, мм; 0 — сплошная (0)",
            "cavity": "открытая сторона при wall>0: верх или низ (верх)",
            "cavity_depth": "глубина полости от открытой стороны, мм (height−wall)",
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
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if wall > 1e-6:
        if wall >= height - 0.1:
            raise GeometryError("wall не оставляет высоты для слепой полости призмы.")
        side = _cavity_choice(a.text("cavity", "верх"))
        depth = float(a.num("cavity_depth", height - wall,
                            minv=0.1, maxv=height - wall))

        def inner_ring(z):
            t = float(z) / height
            center = offset * t
            ring = prof * ((1.0 - t) + t * (r2 / radius) * scale) + center
            if abs(twist) > 1e-9:
                theta = math.radians(twist * t)
                rot = np.array([[math.cos(theta), -math.sin(theta)],
                                [math.sin(theta), math.cos(theta)]])
                ring = (ring - center) @ rot.T + center
            cross = mf.CrossSection([ring]).offset(
                -wall, mf.JoinType.Miter, 3.0, 16)
            polygons = cross.to_polygons()
            if cross.is_empty() or len(polygons) != 1:
                raise GeometryError("wall не оставляет одну внутреннюю полость призмы.",
                                    hint="Уменьшите wall или cavity_depth.")
            return np.asarray(polygons[0], dtype=np.float64)

        z0, z1 = ((height - depth, height + 1.0) if side == "верх"
                  else (-1.0, depth))
        tool = _two_ring_hull(inner_ring(z0), inner_ring(z1), height,
                              z_bottom=z0, z_top=z1)
        before = solid.volume()
        solid = solid - tool
        if solid.is_empty() or len(solid.decompose()) != 1 or solid.volume() >= before - 1e-6:
            raise GeometryError("Не удалось вырезать слепую полость призмы.")
    elif a.has("cavity_depth"):
        raise GeometryError("cavity_depth работает при wall>0.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="prism")
    if custom:
        out.notes.append(f"верх: r2={r2:g}, scale={scale.tolist()}, сдвиг {offset.tolist()}")
    if _smooth_level(a):
        out.notes.append(f"Loop-сглаживание, уровень {_smooth_level(a)}")
    if wall > 1e-6:
        out.meta.update({"wall": wall, "cavity": side, "cavity_depth": depth})
        out.notes.append(f"слепая полость: {side}, глубина {depth:g}, стенка {wall:g} мм")
    return out


@op("pyramid", aliases=("пирамида", "tetra", "пирамидка"), category="Примитивы",
    summary="N-угольная пирамида с вершиной в произвольной точке, над стороной "
            "или углом основания. При sides=4 base_angle делает основание "
            "параллелограммом; smooth=0…4 скругляет именно рёбра эрозией и "
            "Minkowski-суммой, не деформируя широкие грани Loop-сеткой. "
            "wall>0 вырезает слепую полость снизу, сохраняя вершину.",
    example="пирамида = pyramid sides=4 radius=60 height=90\n"
            "на_угол = pyramid sides=4 radius=60 height=90 tip_at=corner tip_index=0\n"
            "ромб = pyramid sides=4 radius=60 height=80 base_angle=60 tip_at=edge\n"
            "полая = pyramid sides=4 radius=60 height=90 wall=3 cavity_depth=72",
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
            "wall": "стенка по основанию и минимальная толщина вершины, мм; "
                    "0 — сплошная, >0 — полость открыта снизу (0)",
            "cavity_depth": "глубина полости от основания, мм (height−wall)",
            "smooth": "радиусное скругление рёбер, ступени 0…4 (0 — острые)",
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
    edge_r = transition_radius(a, min(height, radius) * 0.12)
    if edge_r > 1e-6:
        solid = _rounded_convex(solid, edge_r, a, "пирамида")
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if wall > 1e-6:
        if wall >= height - 0.1:
            raise GeometryError("wall не оставляет толщины у вершины пирамиды.")
        center2 = base.mean(axis=0)
        distances = []
        for i in range(sides):
            p, q = base[i], base[(i + 1) % sides]
            edge = q - p
            delta = center2 - p
            distances.append(abs(float(edge[0] * delta[1] - edge[1] * delta[0])) /
                             max(float(np.linalg.norm(edge)), 1e-9))
        inradius = min(distances)
        if wall >= inradius - 0.05:
            raise GeometryError("wall слишком велик для основания пирамиды.")
        depth = float(a.num("cavity_depth", height - wall,
                            minv=0.1, maxv=height - wall))
        inner_base = center2 + (base - center2) * ((inradius - wall) / inradius)
        inner_tip = center2 + (tip - center2) * (depth / height)
        inner_ring = np.column_stack([inner_base, np.zeros(sides)])
        inner = mf.Manifold.hull_points(np.ascontiguousarray(np.vstack([
            inner_ring, np.asarray([[inner_tip[0], inner_tip[1], depth]])]), dtype=np.float64))
        opening = mf.CrossSection([inner_base]).extrude(1.2).translate((0.0, 0.0, -1.05))
        before = solid.volume()
        solid = solid - (inner + opening)
        if solid.is_empty() or len(solid.decompose()) != 1 or solid.volume() >= before - 1e-6:
            raise GeometryError("Не удалось вырезать полость пирамиды.")
    elif a.has("cavity_depth"):
        raise GeometryError("cavity_depth работает при wall>0.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="pyramid")
    out.meta["tip"] = {"mode": tip_mode, "xy_before_anchor": tip.tolist()}
    if tip_mode != "center":
        out.notes.append(f"вершина: {tip_mode}, XY {tip.tolist()}")
    if edge_r > 1e-6:
        out.notes.append(f"скруглены рёбра R{edge_r:g} мм; грани не подразделяются Loop")
    if wall > 1e-6:
        out.meta.update({"wall": wall, "cavity": "низ", "cavity_depth": depth})
        out.notes.append(f"слепая полость снизу: глубина {depth:g}, стенка {wall:g} мм")
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
            "divisions": "уровень 0…5 (2): дробит панели выбранного типа; сота уже "
                         "на уровне 0 содержит 20 шестиугольников и 12 пятиугольников",
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
        "pentagon": "pentagon", "pentagonal": "pentagon", "пятиугольник": "pentagon",
        "пятиугольный": "pentagon", "додекаэдр": "pentagon",
        "honeycomb": "honeycomb", "hex": "honeycomb", "hexagon": "honeycomb",
        "сота": "honeycomb", "соты": "honeycomb", "шестиугольник": "honeycomb",
        "шестиугольный": "honeycomb",
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
    elif mode == "pentagon":
        verts, faces, topology = pentagon_sphere(radius, divisions)
    else:
        verts, faces, topology = honeycomb_sphere(radius, divisions)
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
    summary="Октаэдр и симметричные двойные пирамиды: faces задаёт чётное "
            "число исходных треугольных граней (8 — обычный октаэдр), а "
            "divisions отдельно дробит каждую из них на 4^N без изменения "
            "формы. smooth=0…4 выполняет Loop-сглаживание. Стоит на полу.",
    example="кристалл = octa radius=30 height=80\n"
            "десятигранник = octa radius=30 height=80 faces=10\n"
            "подробный = octa radius=30 height=80 faces=8 divisions=2",
    params={"radius": "полуширина по X и Y, мм (обязательно)",
            "height": "полная высота, мм (по умолчанию 2·radius)",
            "depth": "полуширина по Y, если она отличается от X (radius)",
            "faces": "чётное число исходных граней 6…64 (8 — октаэдр); "
                     "это НЕ дробление сетки",
            "divisions": "дробление каждой исходной грани 0…4 (0): "
                         "faces·4^N треугольников без скругления",
            "smooth": "уровни Loop-сглаживания 0…4 (0 — исходные плоские грани)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius"])
def octa(a, name):
    radius = float(a.num("radius", required=True, minv=0.01))
    depth = a.num("depth", None, minv=0.01)
    depth = float(radius if depth is None else depth)
    height = a.num("height", None, minv=0.01)
    height = float(2.0 * radius if height is None else height)
    face_count = int(a.int("faces", 8, minv=6, maxv=64))
    if face_count % 2:
        raise GeometryError("octa: faces должно быть чётным: 6, 8, 10 … 64.",
                            hint="Каждая сторона экватора даёт по одной верхней и нижней грани.")
    divisions = int(a.int("divisions", 0, minv=0, maxv=4))
    half = height / 2.0
    sides = face_count // 2
    angles = np.arange(sides, dtype=np.float64) * (2.0 * math.pi / sides)
    ring = np.column_stack([radius * np.cos(angles), depth * np.sin(angles),
                            np.zeros(sides)])
    # У нечётного числа экваториальных вершин диаметр не совпадает с
    # габаритом: центрируем и нормируем X/Y, чтобы radius/depth оставались
    # честными полуширинами и для треугольной двойной пирамиды.
    lo = ring[:, :2].min(axis=0)
    hi = ring[:, :2].max(axis=0)
    ring[:, :2] = ((ring[:, :2] - (lo + hi) * 0.5)
                   / np.maximum((hi - lo) * 0.5, 1e-12)) * [radius, depth]
    pts = np.vstack([ring, [[0.0, 0.0, half], [0.0, 0.0, -half]]])
    top, bottom = sides, sides + 1
    triangles = []
    for i in range(sides):
        j = (i + 1) % sides
        triangles.extend(((top, i, j), (bottom, j, i)))
    faces = np.asarray(triangles, dtype=np.int64)
    pts, faces = linear_subdivide(pts, faces, divisions)
    solid = manifold_from_arrays(pts, faces, "октаэдра")
    solid = _smooth_primitive(solid, a, "октаэдр")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="octa")
    out.meta["faces"] = face_count
    out.notes.append(f"двойная пирамида {2 * radius:g}×{2 * depth:g}×{height:g} мм, "
                     f"исходных граней {face_count}, треугольников {solid.num_tri()}, "
                     f"divisions={divisions}, smooth={_smooth_level(a)}")
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
            "expand": "расширение выбранной половины по радиусу 0…2 (0 — нет)",
            "expansion": "синоним expand",
            "expand_degree": "синоним expand",
            "expand_side": "расширяемая половина: верх или низ (верх)",
            "expanded_half": "синоним expand_side",
            "expand_smooth": "плавность внешнего перехода 0…1; 0 — чёткая кромка (0)",
            "expand_transition": "синоним expand_smooth",
            "expand_joint": "посадка — колпачок с поясом; стык — без нахлёста (посадка)",
            "expand_seat": "заход пояса на меньшую половину, мм (авто: 12% полувысоты)",
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
    expand, expand_side, expand_smooth, expand_joint, expand_seat = _expansion_options(a)
    solid, expand_info = _expand_half(solid, expand, expand_side, expand_smooth, "эллипсоида",
                                      expand_joint, expand_seat)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="ellipsoid")
    out.notes.append(f"полуоси {x:g}×{y:g}×{z:g} мм, {detail_note}")
    if expand > 1e-9:
        out.meta.update(expanded_half="верх" if expand_side > 0 else "низ",
                        expand=expand, expand_smooth=expand_smooth, **expand_info)
        out.notes.append(f"расширенная половина {'верх' if expand_side > 0 else 'низ'}: "
                         f"+{expand * 100:g}%, {expand_joint}, пояс {expand_info['expand_seat']:g} мм, "
                         f"переход {expand_info['expand_transition_mm']:g} мм")
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
            "expand": "расширение выбранной половины по радиусу 0…2 (0 — нет)",
            "expansion": "синоним expand", "expand_degree": "синоним expand",
            "expand_side": "расширяемая половина: верх или низ (верх)",
            "expanded_half": "синоним expand_side",
            "expand_smooth": "плавность внешнего перехода 0…1; 0 — чёткая кромка (0)",
            "expand_transition": "синоним expand_smooth",
            "expand_joint": "посадка — колпачок с поясом; стык — без нахлёста (посадка)",
            "expand_seat": "заход пояса на меньшую половину, мм (авто: 12% полувысоты)",
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
    expand, expand_side, expand_smooth, expand_joint, expand_seat = _expansion_options(a)
    solid, expand_info = _expand_half(solid, expand, expand_side, expand_smooth, "капсулы",
                                      expand_joint, expand_seat)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="capsule")
    if expand > 1e-9:
        out.meta.update(expanded_half="верх" if expand_side > 0 else "низ",
                        expand=expand, expand_smooth=expand_smooth, **expand_info)
        out.notes.append(f"расширенная половина {'верх' if expand_side > 0 else 'низ'}: "
                         f"+{expand * 100:g}%, {expand_joint}, пояс {expand_info['expand_seat']:g} мм, "
                         f"переход {expand_info['expand_transition_mm']:g} мм")
    return out


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
