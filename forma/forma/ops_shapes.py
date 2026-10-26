"""Готовые сложные фигуры: звезда, кружка, тарелка, пружина, шестерня,
шайба, кубик с отверстием и кольцо.

Это «заготовки»: вместо десятка строк с булевыми операциями достаточно одной
команды. Все фигуры — настоящие замкнутые тела, их можно резать, склеивать и
проверять как обычные объекты.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays
from .ops import anchor, face_front, make_solid, op, stand_flat_sign
from .shape_features import (apply_smooth, cut_center_hole, hollow_cross,
                             rounded_extrude)


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
def _signed_area(points: list[tuple[float, float]]) -> float:
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _profile(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Контур против часовой стрелки — иначе Clipper считает его отверстием."""
    return points if _signed_area(points) > 0 else points[::-1]


def _cross(outer: list[tuple[float, float]],
           holes: list[list[tuple[float, float]]] | None = None) -> mf.CrossSection:
    contours = [_profile(outer)]
    for hole in holes or []:
        pts = _profile(hole)
        contours.append(pts[::-1])   # отверстие — по часовой стрелке
    cs = mf.CrossSection(contours)
    if cs.is_empty() or cs.area() <= 0:
        raise GeometryError("Не удалось построить контур фигуры.",
                            hint="Проверьте размеры: контур не должен самопересекаться.")
    return cs


def _segments(value, default: int, minv: int = 16, maxv: int = 256) -> int:
    if value is None:
        return default
    return int(max(minv, min(maxv, int(value))))


def _chamfered_prism(cross: mf.CrossSection, height: float, bevel: float,
                     stages: int = 4) -> mf.Manifold:
    """Призма с фаской/скруглением сверху и снизу (без ступенек)."""
    height = float(height)
    bevel = max(0.0, min(float(bevel), height / 2 - 1e-4))
    if bevel <= 1e-4:
        return cross.extrude(height)
    # масштаб сечения в долях от центра: край чуть меньше, середина — полная
    bb = cross.bounds()
    span = max(bb[2] - bb[0], bb[3] - bb[1], 1e-6)
    ratio = max(0.05, 1.0 - 2.0 * bevel / span)
    stages = max(1, int(stages))
    parts: list[mf.Manifold] = []
    step = bevel / stages
    for i in range(stages):
        t = (i + 0.5) / stages
        # плавная кривая: у края сильнее, к середине — полный размер
        k = 1.0 - (1.0 - t) ** 2
        s = ratio + (1.0 - ratio) * k
        parts.append(cross.scale((s, s)).extrude(step, n_divisions=0)
                     .translate((0.0, 0.0, i * step)))
    parts.append(cross.extrude(height - 2 * bevel).translate((0.0, 0.0, bevel)))
    for i in range(stages):
        t = (i + 0.5) / stages
        k = 1.0 - (1.0 - t) ** 2
        s = 1.0 - (1.0 - ratio) * k
        parts.append(cross.scale((s, s)).extrude(step, n_divisions=0)
                     .translate((0.0, 0.0, height - bevel + i * step)))
    out = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    return out


def _revolve(points: list[tuple[float, float]], segments: int, what: str) -> mf.Manifold:
    cs = mf.CrossSection([_profile(points)])
    if cs.is_empty():
        raise GeometryError(f"Профиль {what} не замкнут.",
                            hint="Точки профиля задаются парой (радиус, высота).")
    solid = mf.Manifold.revolve(cs, int(segments))
    solid = ensure_volume(solid, what)
    return solid


def ensure_volume(m: mf.Manifold, what: str) -> mf.Manifold:
    if m.is_empty() or m.volume() <= 1e-6:
        raise GeometryError(f"{what.capitalize()} получилась пустой.",
                            hint="Проверьте размеры и толщину стенки.")
    return m


def _tube(path: np.ndarray, radius: float, segments: int = 16) -> mf.Manifold:
    """Труба круглого сечения вдоль ломаной — ручка кружки, витки пружины."""
    pts = np.asarray(path, dtype=np.float64)
    if len(pts) < 2:
        raise GeometryError("Для трубы нужна хотя бы одна точка пути.")
    tangents = []
    for i in range(len(pts)):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == len(pts) - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        norm = np.linalg.norm(t)
        if norm < 1e-9:
            raise GeometryError("Путь трубы содержит повторяющиеся точки.")
        tangents.append(t / norm)
    ref = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(tangents[0], ref))) > 0.95:
        ref = np.array([1.0, 0.0, 0.0])
    rings = []
    prev_n = None
    for p, t in zip(pts, tangents):
        if prev_n is None:
            nvec = np.cross(t, ref)
        else:
            nvec = prev_n - t * np.dot(prev_n, t)
        norm = np.linalg.norm(nvec)
        if norm < 1e-9:
            nvec = np.cross(t, ref)
            norm = np.linalg.norm(nvec)
        nvec = nvec / max(norm, 1e-9)
        bvec = np.cross(t, nvec)
        ring = [p + radius * (math.cos(2 * math.pi * j / segments) * nvec
                              + math.sin(2 * math.pi * j / segments) * bvec)
                for j in range(segments)]
        rings.append(ring)
        prev_n = nvec
    verts = [tuple(v) for ring in rings for v in ring]
    faces = []
    for i in range(len(rings) - 1):
        b0, b1 = i * segments, (i + 1) * segments
        for j in range(segments):
            j2 = (j + 1) % segments
            faces.append((b0 + j, b0 + j2, b1 + j2))
            faces.append((b0 + j, b1 + j2, b1 + j))
    c0 = len(verts)
    verts.append(tuple(pts[0]))
    c1 = len(verts)
    verts.append(tuple(pts[-1]))
    last = (len(rings) - 1) * segments
    for j in range(segments):
        j2 = (j + 1) % segments
        faces.append((c0, j2, j))
        faces.append((c1, last + j, last + j2))
    return manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                np.asarray(faces, dtype=np.int64), "труба")


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


# --------------------------------------------------------------------------- #
#  Звезда
# --------------------------------------------------------------------------- #
def _star_loft(points, depth: float, twist: float, bevel: float, smooth: float,
               outer: float, blade_weights=None, blade: float = 0.0,
               pad: float = 0.0) -> mf.Manifold:
    """Единый триангулированный loft без ступенчатых булевых слоёв."""
    pts = np.asarray(points, dtype=np.float64)
    if _signed_area([tuple(p) for p in pts]) < 0.0:
        pts = pts[::-1]
    n = len(pts)
    weights = np.zeros(n) if blade_weights is None else np.asarray(blade_weights, dtype=float)
    layers = max(18, min(72, 18 + int(abs(twist) / 8.0)))
    ratio = max(0.08, 1.0 - bevel / max(outer, 1e-6))
    bevel_z = min(bevel, depth * 0.45)
    verts: list[tuple[float, float, float]] = []
    for i in range(layers):
        actual_z = -pad + (depth + 2.0 * pad) * i / (layers - 1)
        t = min(1.0, max(0.0, actual_z / depth))
        scale = 1.0
        if bevel > 1e-9 and bevel_z > 1e-9:
            d = min(t, 1.0 - t) * depth
            q = max(0.0, 1.0 - d / bevel_z)
            q = (1.0 - smooth) * q + smooth * math.sin(q * math.pi / 2.0)
            scale = 1.0 - (1.0 - ratio) * q
        ang = math.radians(twist * (t - 0.5))
        ca, sa = math.cos(ang), math.sin(ang)
        for j, (x, y) in enumerate(pts):
            xx, yy = x * scale, y * scale
            z = actual_z
            if blade > 1e-9 and -1e-9 <= actual_z <= depth + 1e-9:
                lift = blade * depth * 0.5 * float(weights[j])
                z = lift + t * (depth - 2.0 * lift)
            verts.append((ca * xx - sa * yy, sa * xx + ca * yy, z))
    faces: list[tuple[int, int, int]] = []
    for i in range(layers - 1):
        b0, b1 = i * n, (i + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((b0 + j, b0 + j2, b1 + j2))
            faces.append((b0 + j, b1 + j2, b1 + j))
    caps = np.asarray(mf.triangulate([pts]), dtype=np.int64)
    last = (layers - 1) * n
    for tri in caps:
        a0, b0, c0 = (int(v) for v in tri)
        faces.append((c0, b0, a0))
        faces.append((last + a0, last + b0, last + c0))
    varr = np.asarray(verts, dtype=np.float64)
    farr = np.asarray(faces, dtype=np.int64)
    p0, p1, p2 = varr[farr[:, 0]], varr[farr[:, 1]], varr[farr[:, 2]]
    volume = float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6.0)
    if volume < 0.0:
        farr = farr[:, ::-1]
    return manifold_from_arrays(varr, farr, "звезда")


@op("star", aliases=("звезда", "звёздочка", "звездочка"), category="Примитивы",
    summary="Звезда и сюрикен: единый плавный loft вместо ступенчатой фаски. "
            "twist закручивает всё тело, bevel сужает кромки, blade утоньшает "
            "кончики лучей. hole делает центральное отверстие, wall — сквозную "
            "формочку/рамку с равномерной стенкой.",
    example="звезда = star points=5 outer=60 inner=25 depth=12 bevel=1.5\n"
            "сюрикен = star points=4 outer=70 inner=30 depth=8 twist=65 bevel=2 blade=.7 hole=12\n"
            "формочка = star points=6 outer=60 inner=35 depth=10 wall=3",
    params={"points": "число лучей (5)", "outer": "радиус кончика, мм (60)",
            "inner": "радиус впадины, мм (0.45 × outer)",
            "depth": "толщина, мм (12)",
            "bevel": "плавное сужение верхней и нижней кромок, мм (0)",
            "smooth": "плавность кромочного перехода 0…1 (0)",
            "twist": "закрутка всей звезды, градусы; работает вместе с bevel",
            "blade": "утоньшение кончиков 0…0.9 от полутолщины (0)",
            "hole": "центральное сквозное отверстие, мм (0)",
            "wall": "стенка сквозной формочки/рамки, мм; 0 — сплошная (0)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит вверх",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def star(a, name):
    points = int(a.num("points", 5, minv=3, maxv=64))
    outer = float(a.num("outer", 60.0, minv=0.5))
    inner = float(a.num("inner", outer * 0.45, minv=0.1))
    depth = float(a.num("depth", 12.0, minv=0.2))
    if inner >= outer - 1e-6:
        raise GeometryError(f"Впадина {inner:g} мм должна быть меньше кончика {outer:g} мм.",
                            hint="Для звезды inner ≈ 0.35…0.6 от outer.")
    bevel = float(a.num("bevel", 0.0, minv=0.0) or 0.0)
    if bevel >= outer * 0.8:
        raise GeometryError("bevel слишком велик: он стирает лучи звезды.")
    smooth = float(a.num("smooth", 0.0, minv=0.0, maxv=1.0) or 0.0)
    twist = float(a.num("twist", 0.0) or 0.0)
    blade = float(a.num("blade", 0.0, minv=0.0, maxv=0.9) or 0.0)
    hole = float(a.num("hole", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    pts = []
    for k in range(2 * points):
        angle = math.pi / 2 + k * math.pi / points
        radius = outer if k % 2 == 0 else inner
        pts.append((radius * math.cos(angle), radius * math.sin(angle)))
    cross = _cross(pts)
    weights = [1.0 if k % 2 == 0 else 0.0 for k in range(2 * points)]
    solid = _star_loft(pts, depth, twist, bevel, smooth, outer, weights, blade)
    if wall > 1e-6:
        cavity_cross = cross.offset(-wall, mf.JoinType.Miter, 3.0, 16)
        polygons = cavity_cross.to_polygons()
        if cavity_cross.is_empty() or len(polygons) != 1:
            raise GeometryError("wall стирает формочку или разделяет её на части.",
                                hint="Уменьшите wall или увеличьте inner/outer.")
        cavity_pts = np.asarray(polygons[0], dtype=np.float64)
        radii = np.linalg.norm(cavity_pts, axis=1)
        cavity_weights = np.clip((radii - inner) / max(outer - inner, 1e-6), 0.0, 1.0)
        cavity = _star_loft(cavity_pts, depth, twist, bevel, smooth, outer,
                            cavity_weights, blade, pad=1.0)
        solid = solid - cavity
    solid = cut_center_hole(solid, depth, hole, what="звезда")
    solid = ensure_volume(solid, "звезда")
    out = make_solid(a.scene, name, _placed(a, stand_flat_sign(a, solid)), a,
                     kind="star")
    out.notes.append(f"звезда: twist={twist:g}°, bevel={bevel:g}, blade={blade:g}, "
                     f"hole={hole:g}, wall={wall:g}")
    return out


# --------------------------------------------------------------------------- #
#  Тарелка
# --------------------------------------------------------------------------- #
@op("plate", aliases=("тарелка", "блюдо", "dish"), category="Примитивы",
    summary="Тарелка: плоское дно и плавная стенка. depth — независимая "
            "глубина, не вычисляется из радиуса. rim/rim_height задают прямой "
            "верхний бортик как у короны: радиальный выступ и его высоту.",
    example="тарелка = plate diameter=220 depth=26 wall=4 rim=6 rim_height=4\n"
            "блюдце = plate diameter=140 depth=12 wall=3 well=0.78 rim=4",
    params={"diameter": "диаметр, мм (220)",
            "depth": "независимая глубина от дна до верхней кромки, мм (26)",
            "wall": "толщина стенки и дна, мм (4)",
            "well": "доля плоского дна 0.2..0.9 (0.62)",
            "rim": "радиальный выступ верхнего бортика, мм (0 — без него)",
            "rim_height": "высота верхнего бортика внутри общей depth, мм",
            "round": "радиус перехода от дна к стенке, мм (0.35·глубины)",
            "foot": "диаметр кольцевой ножки снизу (0 — нет)",
            "segments": "сегментов по кругу",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def plate(a, name):
    diameter = float(a.num("diameter", 220.0, minv=5.0))
    depth = float(a.num("depth", 26.0, minv=1.0))
    wall = float(a.num("wall", 4.0, minv=0.3))
    well = float(a.num("well", 0.62, minv=0.2, maxv=0.9) or 0.62)
    rim_w = float(a.num("rim", max(0.8, wall * 1.2), minv=0.0) or 0.0)
    rim_h = float(a.num("rim_height", max(1.0, depth * 0.08) if rim_w > 0 else 0.0,
                         minv=0.0) or 0.0)
    if rim_w > 1e-6 and rim_h <= 1e-6:
        rim_h = max(1.0, depth * 0.08)
    rim_h = min(rim_h, depth * 0.45) if rim_w > 1e-6 else 0.0
    round_r = float(a.num("round", depth * 0.35, minv=0.0) or 0.0)
    foot = float(a.num("foot", 0.0, minv=0.0) or 0.0)
    r = diameter / 2.0
    if wall >= depth - 0.5 or wall >= r * 0.5:
        raise GeometryError(f"Стенка {wall:g} мм слишком толстая для тарелки {diameter:g}×{depth:g} мм.")
    segments = min(96, _segments(a.int("segments", None, minv=32, maxv=256), 96))
    rw = r * well
    if rw >= r - wall * 2.0 - 2.0:
        raise GeometryError("Дно почти во всю тарелку: уменьшите well или увеличьте диаметр.")
    rb = min(round_r, depth * 0.55, (r - rw) * 0.6)
    z_top = depth - rim_h
    # внешний профиль: дно → скругление → стенка → прямой бортик как у короны
    prof = [(0.0, 0.0), (rw, 0.0)]
    n_arc, n_wall = 5, 7
    for i in range(1, n_arc + 1):
        ang = (math.pi / 2.0) * i / n_arc
        prof.append((rw + rb * math.sin(ang), rb * (1.0 - math.cos(ang))))
    x0, z0 = rw + rb, rb
    wall_pts = []
    for i in range(1, n_wall + 1):
        u = i / n_wall
        z = z0 + (z_top - z0) * u
        f = (z - z0) / max(1e-6, z_top - z0)
        # стенка почти вертикальная у дна и мягко разваливается к борту
        x = x0 + (r - x0) * (0.35 * f + 0.65 * f * f)
        wall_pts.append((x, z))
    prof += wall_pts
    if rim_w > 1e-6:
        prof += [(r + rim_w, z_top), (r + rim_w, depth)]
    else:
        prof.append((r, depth))
    prof.append((0.0, depth))
    solid = _revolve(prof, segments, "тарелка")
    # полость: та же стенка, отступленная внутрь ровно на толщину wall
    cavity = [(0.0, wall), (rw, wall)]
    rb_i = max(0.4, rb - wall)
    for i in range(1, n_arc + 1):
        ang = (math.pi / 2.0) * i / n_arc
        cavity.append((rw + rb_i * math.sin(ang), wall + rb_i * (1.0 - math.cos(ang))))
    for x, z in wall_pts:
        cavity.append((max(0.6, x - wall), z))
    cavity += [(max(0.6, r - wall), depth + 2.0), (0.0, depth + 2.0)]
    solid = solid - _revolve(cavity, segments, "полость тарелки")
    if foot > 0:
        foot_r = min(rw * 0.9, r - wall - 1.0)
        if foot_r <= 1.0:
            raise GeometryError("Ножка не помещается под дном.")
        ring = (mf.Manifold.cylinder(float(foot), float(foot_r), float(foot_r), int(segments))
                - mf.Manifold.cylinder(float(foot + 1.0), float(foot_r - max(0.6, wall * 0.6)),
                                       float(foot_r - max(0.6, wall * 0.6)), int(segments))
                .translate((0.0, 0.0, -0.5)))
        solid = solid + ring.translate((0.0, 0.0, -foot))
        solid = solid.translate((0.0, 0.0, foot))
    return make_solid(a.scene, name, _placed(a, solid), a, kind="plate")


# --------------------------------------------------------------------------- #
#  Пружина
# --------------------------------------------------------------------------- #
@op("spring", aliases=("пружина", "винтовая_пружина", "coil"), category="Примитивы",
    summary="Винтовая пружина с круглым сечением проволоки: витки, шаг и толщина.",
    example="пружина = spring diameter=22 wire=3 turns=10 pitch=7",
    params={"diameter": "средний диаметр витка, мм (22)", "wire": "толщина проволоки, мм (3)",
            "turns": "число витков (8)", "pitch": "шаг витков, мм (6)",
            "right": "правая навивка (да)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def spring(a, name):
    diameter = float(a.num("diameter", 22.0, minv=1.0))
    wire = float(a.num("wire", 3.0, minv=0.2))
    turns = float(a.num("turns", 8.0, minv=0.5, maxv=200.0))
    pitch = float(a.num("pitch", 6.0, minv=0.2))
    if wire >= diameter / 2.0 - 0.2:
        raise GeometryError(f"Проволока {wire:g} мм не проходит в виток ø{diameter:g} мм.")
    if pitch < wire * 1.02:
        raise GeometryError(f"Шаг {pitch:g} мм меньше толщины проволоки {wire:g} мм — витки слипнутся.",
                            hint="pitch ≈ 1.5…3 × wire.")
    sign = 1.0 if a.boolean("right", True) else -1.0
    steps = max(24, int(turns * 32))
    radius = diameter / 2.0
    path = []
    for i in range(steps + 1):
        t = i / steps
        theta = sign * 2.0 * math.pi * turns * t
        path.append((radius * math.cos(theta), radius * math.sin(theta), t * turns * pitch))
    solid = _tube(np.asarray(path), wire / 2.0, segments=16)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="spring")


# --------------------------------------------------------------------------- #
#  Шестерня
# --------------------------------------------------------------------------- #
@op("gear", aliases=("шестерня", "зубчатое_колесо"), category="Примитивы",
    summary="Прямозубая шестерня: зубья, модуль, толщина, ступица и отверстие. "
            "Ступица выступает над телом на hub_height — так её видно и по ней "
            "шестерню сажают на вал; hub_round скругляет её кромку.",
    example="шестерня = gear teeth=20 module=2 thickness=8 bore=8 hub=18 hub_height=5",
    params={"teeth": "число зубьев (20)", "module": "модуль, мм (2)",
            "thickness": "толщина венца, мм (8)",
            "bore": "диаметр отверстия, мм (0 — без него)",
            "hub": "диаметр ступицы, мм (0 — без ступицы)",
            "hub_height": "насколько ступица выступает над телом, мм (0.6·толщины)",
            "hub_below": "выступ ступицы с обратной стороны, мм (0)",
            "hub_round": "скругление кромки ступицы, мм (0.4)",
            "web": "толщина диска между зубьями и ступицей (толщина)",
            "spokes": "окон в диске между ступицей и венцом (0)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gear(a, name):
    teeth = int(a.num("teeth", 20, minv=6, maxv=200))
    module = float(a.num("module", 2.0, minv=0.05))
    thickness = float(a.num("thickness", 8.0, minv=0.2))
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    hub = float(a.num("hub", 0.0, minv=0.0) or 0.0)
    hub_h = float(a.num("hub_height", thickness * 0.6, minv=0.0) or 0.0)
    hub_below = float(a.num("hub_below", 0.0, minv=0.0) or 0.0)
    hub_round = float(a.num("hub_round", 0.4, minv=0.0) or 0.0)
    web = float(a.num("web", thickness, minv=0.4))
    spokes = int(a.num("spokes", 0, minv=0, maxv=12) or 0)
    pitch_r = module * teeth / 2.0
    add = module
    ded = module * 1.25
    r_tip = pitch_r + add
    r_root = max(0.2, pitch_r - ded)
    if r_root <= 0.3:
        raise GeometryError(f"Модуль {module:g} слишком мал для {teeth} зубьев.")
    step = 2.0 * math.pi / teeth
    pts = []
    for i in range(teeth):
        a0 = i * step
        # трапеция зуба: основание шире вершины
        pts.append((r_root * math.cos(a0 - 0.30 * step), r_root * math.sin(a0 - 0.30 * step)))
        pts.append((r_tip * math.cos(a0 - 0.16 * step), r_tip * math.sin(a0 - 0.16 * step)))
        pts.append((r_tip * math.cos(a0 + 0.16 * step), r_tip * math.sin(a0 + 0.16 * step)))
        pts.append((r_root * math.cos(a0 + 0.30 * step), r_root * math.sin(a0 + 0.30 * step)))
    holes = []
    if bore > 0:
        if bore / 2.0 >= r_root - 0.5:
            raise GeometryError(f"Отверстие ø{bore:g} мм больше тела шестерни.")
        hole = [(bore / 2.0 * math.cos(2 * math.pi * i / 48),
                 bore / 2.0 * math.sin(2 * math.pi * i / 48)) for i in range(48)]
        holes.append(hole)
    cross = _cross(pts, holes)
    solid = cross.extrude(thickness)
    if web < thickness - 0.2:
        # облегчение венца: снимаем кольцо с обеих сторон, оставляя обод
        rim_w = max(module * 1.6, thickness * 0.35)
        for z0, h in ((0.0, thickness - web), (web, thickness - web)):
            if h <= 0.05:
                continue
            ring = mf.Manifold.cylinder(h + 0.4, r_root - 0.4, r_root - 0.4, 96)
            ring = ring - mf.Manifold.cylinder(h + 1.0, max(1.0, r_root - rim_w), 
                                              max(1.0, r_root - rim_w), 96).translate((0, 0, -0.5))
            solid = solid - ring.translate((0, 0, z0 - 0.2))
    if spokes > 0:
        # окна в диске: сектора между ступицей и венцом
        inner_r = max(1.0, (hub / 2.0 if hub > 0 else (bore / 2.0 if bore else 2.0)) + 2.0)
        outer_r = max(inner_r + 1.0, r_root - max(module * 1.6, thickness * 0.35))
        win = mf.Manifold.cylinder(thickness + 2.0, outer_r, outer_r, 96)
        win = win - mf.Manifold.cylinder(thickness + 3.0, inner_r, inner_r, 96).translate(
            (0, 0, -0.5))
        for i in range(spokes):
            a0 = 2.0 * math.pi * i / spokes
            a1 = a0 + 2.0 * math.pi / spokes * 0.60
            # вырезаем сектор: пересечение кольца-окна с клином
            rr = outer_r * 1.6
            pts_w = [(0.0, 0.0),
                     (rr * math.cos(a0), rr * math.sin(a0)),
                     (rr * math.cos(a1), rr * math.sin(a1))]
            cutter = mf.Manifold.extrude(mf.CrossSection([_profile(pts_w)]),
                                         thickness + 2.0).translate((0, 0, -1.0))
            window = mf.Manifold.batch_boolean([win, cutter], mf.OpType.Intersect)
            solid = solid - window
    if hub > 0:
        if hub / 2.0 <= (bore / 2.0 if bore else 0) + 0.5:
            raise GeometryError("Ступица должна быть толще отверстия.")
        if hub_h <= 0.05 and hub_below <= 0.05:
            # без выступа ступица просто не видна — предупреждаем в журнале
            a.scene.log("info", "gear: hub_height=0 — ступица спрятана в теле шестерни",
                        a.cmd.line)
        top = thickness + hub_h
        bottom = -hub_below
        height = top - bottom
        hub_m = mf.Manifold.cylinder(height, hub / 2.0, hub / 2.0, 96).translate((0, 0, bottom))
        if hub_round > 0:
            hr = min(hub_round, hub * 0.25, height * 0.3)
            hub_m = hub_m - mf.Manifold.cylinder(hr, hub / 2.0 - hr, hub / 2.0, 96).translate(
                (0, 0, top - hr))
            hub_m = hub_m - mf.Manifold.cylinder(hr, hub / 2.0, hub / 2.0 - hr, 96).translate(
                (0, 0, bottom))
        if bore > 0:
            hub_m = hub_m - mf.Manifold.cylinder(height + 2, bore / 2.0, bore / 2.0, 48).translate(
                (0, 0, bottom - 1))
        solid = solid + hub_m
    solid = ensure_volume(solid, "шестерня")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="gear")


# --------------------------------------------------------------------------- #
#  Шайба
# --------------------------------------------------------------------------- #
@op("washer", aliases=("шайба", "подкладка"), category="Примитивы",
    summary="Плоская шайба с фаской по наружному краю.",
    example="шайба = washer outer=40 inner=16 thickness=4",
    params={"outer": "наружный диаметр, мм (40)", "inner": "диаметр отверстия, мм (16)",
            "thickness": "толщина, мм (4)", "chamfer": "фаска, мм (10% толщины)",
            "segments": "сегментов по кругу", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def washer(a, name):
    outer = float(a.num("outer", 40.0, minv=1.0))
    inner = float(a.num("inner", 16.0, minv=0.2))
    thickness = float(a.num("thickness", 4.0, minv=0.2))
    r_out, r_in = outer / 2.0, inner / 2.0
    if r_in >= r_out - 0.4:
        raise GeometryError(f"Отверстие ø{inner:g} мм не меньше наружного ø{outer:g} мм.")
    chamfer = float(a.num("chamfer", min(thickness * 0.25, (r_out - r_in) * 0.25), minv=0.0) or 0.0)
    chamfer = min(chamfer, thickness / 2 - 1e-3, (r_out - r_in) / 2 - 1e-3)
    segments = _segments(a.int("segments", None, minv=32, maxv=256), 96)
    if chamfer > 1e-3:
        profile = [(r_in, 0.0), (r_out - chamfer, 0.0), (r_out, chamfer),
                   (r_out, thickness - chamfer), (r_out - chamfer, thickness),
                   (r_in, thickness)]
    else:
        profile = [(r_in, 0.0), (r_out, 0.0), (r_out, thickness), (r_in, thickness)]
    solid = _revolve(profile, segments, "шайба")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="washer")


# --------------------------------------------------------------------------- #
#  Кубик с отверстием
# --------------------------------------------------------------------------- #
@op("cube_hole", aliases=("кубик_с_отверстием", "блок_с_отверстием", "брусок_с_отверстием"),
    category="Примитивы",
    summary="Брусок с центральным сквозным отверстием по X, Y или Z. "
            "hole_shape=круг, квадрат или треугольник; hole — диаметр круга, "
            "сторона квадрата или диаметр описанной окружности треугольника.",
    example="кубик = cube_hole size=[40,40,40] hole=16 hole_shape=круг\n"
            "квадратный = cube_hole size=[45,45,35] hole=15 hole_shape=квадрат\n"
            "треугольный = cube_hole size=[50,45,40] hole=18 hole_shape=треугольник axis=y",
    params={"size": "размер [x,y,z], мм (40,40,40)",
            "hole": "размер отверстия, мм (40% размера)",
            "hole_shape": "форма отверстия: круг, квадрат или треугольник",
            "axis": "ось отверстия: z, x или y (z)", "round": "скругление рёбер, мм",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cube_hole(a, name):
    size = a.vec("size", 3, default=(40.0, 40.0, 40.0))
    if any(v <= 0 for v in size):
        raise GeometryError("Размеры бруска должны быть больше нуля.")
    hole = float(a.num("hole", min(size) * 0.4, minv=0.2))
    if hole >= min(size) - 1.0:
        raise GeometryError(f"Отверстие {hole:g} мм не помещается в брусок {size}.")
    axis = (a.text("axis", "z") or "z").strip().lower()
    if axis not in ("x", "y", "z"):
        raise GeometryError("Ось отверстия: z, x или y.")
    shape = (a.text("hole_shape", "круг") or "круг").strip().lower()
    shape = {"круг": "круг", "круглое": "круг", "круглый": "круг",
             "квадрат": "квадрат", "квадратное": "квадрат", "квадратный": "квадрат",
             "треугольник": "треугольник", "треугольное": "треугольник",
             "треугольный": "треугольник"}.get(shape)
    if shape is None:
        raise GeometryError("hole_shape=круг, квадрат или треугольник.")
    box = mf.Manifold.cube(size, True)
    rnd = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if rnd > 1e-6:
        rnd = min(rnd, min(size) / 2 - 1e-3)
        inner = [max(s - 2 * rnd, 1e-3) for s in size]
        box = mf.Manifold.cube(inner, True).minkowski_sum(mf.Manifold.sphere(rnd, 24))
    length = max(size) + 10
    if shape == "круг":
        cutter = mf.Manifold.cylinder(length, hole / 2.0, hole / 2.0, 64, center=True)
    elif shape == "квадрат":
        cutter = mf.Manifold.cube((hole, hole, length), True)
    else:
        radius = hole / 2.0
        pts = [(radius * math.cos(math.radians(90 + 120 * i)),
                radius * math.sin(math.radians(90 + 120 * i))) for i in range(3)]
        cutter = mf.CrossSection([_profile(pts)]).extrude(length).translate((0, 0, -length / 2))
    if axis == "x":
        cutter = cutter.rotate((0, 90, 0))
    elif axis == "y":
        cutter = cutter.rotate((90, 0, 0))
    solid = ensure_volume(box - cutter, "брусок с отверстием")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="cube_hole")
    out.meta["hole_shape"] = shape
    out.notes.append(f"сквозное отверстие {shape} по {axis.upper()}, {hole:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Кольцо
# --------------------------------------------------------------------------- #
def _rounded_rect(r0: float, r1: float, z0: float, z1: float, rad: float,
                  steps: int = 6) -> list[tuple[float, float]]:
    """Прямоугольник со скруглёнными углами в плоскости (радиус, высота)."""
    rad = max(0.0, min(rad, (r1 - r0) / 2 - 1e-4, (z1 - z0) / 2 - 1e-4))
    if rad <= 1e-4:
        return [(r0, z0), (r1, z0), (r1, z1), (r0, z1)]
    corners = [
        ((r1 - rad, z0 + rad), -90.0, 0.0),
        ((r1 - rad, z1 - rad), 0.0, 90.0),
        ((r0 + rad, z1 - rad), 90.0, 180.0),
        ((r0 + rad, z0 + rad), 180.0, 270.0),
    ]
    pts: list[tuple[float, float]] = []
    for (cx, cz), a0, a1 in corners:
        for i in range(steps + 1):
            ang = math.radians(a0 + (a1 - a0) * i / steps)
            pts.append((cx + rad * math.cos(ang), cz + rad * math.sin(ang)))
    return pts

@op("ring", aliases=("кольцо", "обручальное_кольцо", "band"), category="Примитивы",
    summary="Кольцо с плоским ободом и скруглёнными краями (обручальное, деталь опоры).",
    example="кольцо = ring diameter=20 width=6 thickness=2.2",
    params={"diameter": "внутренний диаметр, мм (20)",
            "outer": "наружный диаметр, мм — если задан, толщина считается сама",
            "inner": "внутренний диаметр (синоним diameter)",
            "width": "ширина обода (высота кольца), мм (6)",
            "height": "синоним width",
            "thickness": "толщина стенки по радиусу, мм (2.2)",
            "round": "скругление краёв (наружного и внутреннего), мм",
            "segments": "сегментов по кругу", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def ring(a, name):
    diameter = float(a.num("diameter", 20.0, minv=1.0))
    inner_d = a.num("inner", None, minv=0.5)
    outer_d = a.num("outer", None, minv=1.0)
    if inner_d is not None:
        diameter = float(inner_d)
    width = float(a.num("width", a.num("height", 6.0, minv=0.4) or 6.0, minv=0.4))
    thickness = a.num("thickness", None, minv=0.2)
    if outer_d is not None:
        if thickness is not None and abs(outer_d / 2.0 - diameter / 2.0 - thickness) > 1e-6:
            raise GeometryError(
                "Наружный диаметр не сходится с толщиной.",
                hint=f"outer = diameter + 2·thickness = {diameter + 2 * thickness:g} мм. "
                     "Уберите один из параметров.")
        thickness = max(0.2, (float(outer_d) - diameter) / 2.0)
    if thickness is None:
        thickness = 2.2
    thickness = float(thickness)
    r_in = diameter / 2.0
    r_out = r_in + thickness
    if thickness >= width:
        raise GeometryError(
            "Толщина кольца должна быть меньше его ширины.",
            hint="Геометрия кольца: отверстие diameter, наружу thickness, в высоту width.")
    rnd = float(a.num("round", min(thickness, width) * 0.3, minv=0.0) or 0.0)
    rnd = min(rnd, thickness * 0.45, width * 0.45)
    segments = _segments(a.int("segments", None, minv=32, maxv=256), 120)
    profile = _rounded_rect(r_in, r_out, -width / 2.0, width / 2.0, rnd, steps=5)
    solid = _revolve(profile, segments, "кольцо")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="ring")


# --------------------------------------------------------------------------- #
#  Яйцо
# --------------------------------------------------------------------------- #
@op("egg", aliases=("яйцо", "яичко", "овоид"), category="Примитивы",
    summary="Настоящее яйцо: широкий тупой низ, узкий острый верх, самая широкая "
            "точка ниже середины. proportion — насколько яйцо «яйцевидное»: "
            "0 — симметричный овоид, 0.5 — куриное яйцо, 1 — острое.",
    example="яйцо = egg height=60 diameter=42 proportion=0.55\n"
            "перепелиное = egg height=32 diameter=26 proportion=0.6",
    params={"height": "высота, мм (60)", "diameter": "наибольший диаметр, мм (42)",
            "proportion": "яйцевидность 0..1 (0.55)",
            "sharp": "какой конец острый: верх или низ (верх)",
            "segments": "сегментов по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def egg(a, name):
    height = float(a.num("height", 60.0, minv=1.0))
    diameter = float(a.num("diameter", 42.0, minv=1.0))
    prop = float(a.num("proportion", 0.55, minv=0.0, maxv=1.0) or 0.0)
    sharp = (a.text("sharp") or "верх").strip().lower()
    if sharp in ("bottom", "низ", "вниз", "снизу"):
        sharp = "низ"
    r_max = diameter / 2.0
    if r_max * 2.0 >= height * 1.02:
        raise GeometryError(
            f"Яйцо не может быть шире своей высоты: диаметр {diameter:g} при высоте {height:g}.",
            hint="Высота яйца примерно в 1.35–1.5 раза больше диаметра.")
    segments = _segments(a.int("segments", None, minv=16, maxv=256),
                         max(48, min(160, int(r_max * 3))))
    steps = max(28, int(segments * 0.75))

    # Самая широкая точка: у куриного яйца она ниже середины (≈42 % высоты),
    # у симметричного овоида — ровно посередине.
    zw = height * (0.5 - 0.06 * prop)
    prof: list[tuple[float, float]] = [(0.0, 0.0)]
    # Низ — четверть эллипса: широкое круглое дно без «шипа» в полюсе.
    n1 = max(12, int(steps * zw / height * 1.6))
    for i in range(1, n1 + 1):
        t = i / n1
        prof.append((r_max * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2)), zw * t))
    # Верх — кубическая кривая от экватора до острого полюса. Касательная
    # в начале вертикальная (гладкий стык), у полюса — наклонная: яйцо
    # сужается плавно, а не заканчивается куполом.
    u2 = 0.5523 - 0.0523 * prop        # радиус второй контрольной точки
    v2 = 1.0 - 0.10 * prop             # её высота (1.0 — как у эллипса)
    p0 = (r_max, zw)
    p1 = (r_max, zw + (0.5523 - 0.2523 * prop) * (height - zw))
    p2 = (u2 * r_max, zw + v2 * (height - zw))
    p3 = (0.0, height)
    n2 = max(16, int(steps * (height - zw) / height * 1.6))
    for i in range(1, n2 + 1):
        t = i / n2
        mt = 1.0 - t
        r = (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0]
             + 3 * mt * t * t * p2[0] + t ** 3 * p3[0])
        z = (mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1]
             + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])
        prof.append((max(0.0, r), z))
    if sharp == "низ":                       # переворачиваем: острый конец вниз
        prof = [(r, height - z) for r, z in prof]
        prof = sorted(prof, key=lambda p: p[1])
        prof[0] = (0.0, 0.0)
        prof[-1] = (0.0, height)
    solid = _revolve(prof, segments, "яйца")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="egg")


@op("drop", aliases=("капля", "дроп", "слеза", "teardrop"), category="Примитивы",
    summary="Капля: круглое дно и плавно сходящий на нет хвост — вода, слеза, стекло. "
            "tip задаёт остроту: 0 — почти сфера, 1 — длинная острая капля.",
    example="капля = drop radius=14 height=40 tip=0.5\n"
            "стекло = drop radius=9 height=52 tip=0.8",
    params={"radius": "радиус круглой части, мм (14)",
            "height": "полная высота, мм (36)",
            "tip": "острота хвоста 0…1 (0.5)",
            "segments": "сегментов по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def drop(a, name):
    radius = float(a.num("radius", 14.0, minv=0.5))
    height = float(a.num("height", 36.0, minv=1.0))
    tip = float(a.num("tip", 0.5, minv=0.0, maxv=1.0) or 0.0)
    if height < radius * 1.15:
        raise GeometryError(
            f"Высота капли {height:g} мм слишком мала для радиуса {radius:g} мм.",
            hint="Капля — шар с вытянутым хвостом: height от 1.2 до 4 радиусов.")
    segments = _segments(a.int("segments", None, minv=16, maxv=256),
                         max(48, min(160, int(radius * 3))))
    steps = max(40, int(segments * 0.9))

    # низ — полушарие: от полюса до экватора
    prof: list[tuple[float, float]] = [(0.0, 0.0)]
    n1 = max(16, steps // 3)
    for i in range(1, n1 + 1):
        t = i / n1
        prof.append((radius * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2)), radius * t))
    # хвост — кубическая кривая: в начале вертикальная касательная (гладкий
    # стык с шаром), в конце точка. Чем больше tip, тем ниже и левее опора.
    span = height - radius
    p0 = (radius, radius)
    p1 = (radius, radius + 0.45 * span)
    p2 = (radius * (0.46 - 0.24 * tip), radius + (0.80 - 0.10 * tip) * span)
    p3 = (0.0, height)
    n2 = max(24, int(steps * 0.7))
    for i in range(1, n2 + 1):
        t = i / n2
        mt = 1.0 - t
        r = (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0]
             + 3 * mt * t * t * p2[0] + t ** 3 * p3[0])
        z = (mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1]
             + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])
        prof.append((max(0.0, r), z))
    solid = _revolve(prof, segments, "капли")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="drop")


# --------------------------------------------------------------------------- #
#  Арка (полукольцо)
# --------------------------------------------------------------------------- #
@op("arch", aliases=("арка", "полукольцо", "арка_проём", "archway"), category="Примитивы",
    summary="Арка — половина кольца с прямоугольным сечением: проём окна, "
            "дверной проём, тоннель. Угол задаётся (180° — полукольцо), "
            "сечение — шириной и толщиной, торцы можно скруглить.",
    example="арка = arch radius=200 width=60 thickness=40 angle=180\n"
            "тоннель = arch radius=160 width=30 thickness=25 angle=120",
    params={"radius": "радиус по средней линии, мм (200)",
            "width": "ширина сечения вбок (радиально), мм (60)",
            "thickness": "толщина по оси, мм (40)",
            "angle": "угол дуги, градусы (180)",
            "round": "скругление торцов, мм (0)",
            "smooth": "уровни Loop-сглаживания всей арки 0…4 (0)",
            "segments": "сегментов по дуге (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def arch(a, name):
    radius = float(a.num("radius", 200.0, minv=2.0))
    width = float(a.num("width", 60.0, minv=1.0))
    thickness = float(a.num("thickness", 40.0, minv=1.0))
    angle = float(a.num("angle", 180.0, minv=5.0, maxv=360.0) or 180.0)
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if width >= radius * 1.9:
        raise GeometryError("Ширина сечения больше диаметра арки.",
                            hint="width должна быть меньше 2·radius.")
    r_in = max(0.2, radius - width / 2.0)
    r_out = radius + width / 2.0
    round_r = min(round_r, width * 0.45, thickness * 0.45)
    if round_r > 0.05:
        prof = _rounded_rect(r_in, r_out, -thickness / 2.0, thickness / 2.0, round_r, steps=4)
    else:
        prof = np.array([[r_in, -thickness / 2.0], [r_out, -thickness / 2.0],
                         [r_out, thickness / 2.0], [r_in, thickness / 2.0]])
    segments = _segments(a.int("segments", None, minv=8, maxv=360),
                         max(radius, width) * 2.0)
    segments = max(6, int(round(segments * angle / 360.0)) + 2)
    solid = mf.Manifold.revolve(mf.CrossSection([prof]), segments, angle)
    solid = apply_smooth(solid, a, "арка")
    # арка стоит на полу, как дверной проём: плоскость дуги — XZ,
    # толщина — по Y, торцы опираются на z = 0
    solid = solid.rotate([90.0, 0.0, 0.0])
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="arch")
    out.notes.append(f"дуга {angle:g}°, радиус {radius:g}, сечение {width:g}×{thickness:g}")
    return out


# --------------------------------------------------------------------------- #
#  Полусфера и миска
# --------------------------------------------------------------------------- #
@op("hemisphere", aliases=("полусфера", "полушар", "миска", "чаша", "bowl"),
    category="Примитивы",
    summary="Полусфера с плоским основанием. wall=0 — сплошное тело, "
            "wall>0 — открытая сверху чаша с ровной горизонтальной кромкой; "
            "отдельный mode больше не нужен. round строит касательное "
            "скругление наружной и внутренней стороны кромки, rim добавляет бортик.",
    example="купол = hemisphere radius=60\n"
            "чаша = hemisphere radius=70 wall=4 round=1.2\n"
            "с_бортом = hemisphere radius=70 wall=4 rim=3 round=1",
    params={"radius": "радиус, мм (50)",
            "wall": "стенка: 0 — сплошная полусфера, >0 — чаша (0)",
            "round": "радиус скругления кромки чаши, мм; меньше wall/2 (0)",
            "rim": "выступ бортика наружу у верхней кромки, мм (0)",
            "segments": "сегментов по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def hemisphere(a, name):
    radius = float(a.num("radius", 50.0, minv=1.0))
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    rim_w = float(a.num("rim", 0.0, minv=0.0) or 0.0)
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    segments = _segments(a.int("segments", None, minv=16, maxv=256),
                         max(48, min(160, int(radius * 3))))
    steps = max(20, int(segments * 0.65))
    if wall <= 1e-9:
        if round_r > 1e-9 or rim_w > 1e-9:
            raise GeometryError("У сплошной полусферы нет кромки чаши: задайте wall>0.",
                                hint="round/rim работают вместе с wall>0.")
        prof = [(0.0, 0.0), (0.0, radius)]
        for i in range(1, steps + 1):
            ang = math.pi / 2.0 * i / steps
            prof.append((radius * math.sin(ang), radius * math.cos(ang)))
        solid = _revolve(prof, segments, "полусферы")
        return make_solid(a.scene, name, _placed(a, solid), a, kind="hemisphere")
    if wall >= radius * 0.8:
        raise GeometryError("Стенка чаши слишком толстая для этого радиуса.")
    if round_r >= wall / 2.0 - 1e-9:
        raise GeometryError("round должен быть меньше wall/2, чтобы осталась плоская кромка.")
    inner_r = radius - wall
    if round_r <= 1e-9:
        prof = []
        for i in range(steps + 1):
            ang = math.pi / 2.0 * i / steps
            prof.append((radius * math.sin(ang), radius * (1.0 - math.cos(ang))))
        # Явная плоская перемычка (R,R) → (R−wall,R).
        for i in range(steps, -1, -1):
            ang = math.pi / 2.0 * i / steps
            prof.append((inner_r * math.sin(ang),
                         wall + inner_r * (1.0 - math.cos(ang))))
    else:
        r = round_r
        # Центры обеих дуг лежат на z=R−r. Наружная дуга внутренне
        # касается сферы R, внутренняя внешне касается полости R−wall.
        co = math.sqrt(max(0.0, (radius - r) ** 2 - r ** 2))
        ci = math.sqrt(max(0.0, (inner_r + r) ** 2 - r ** 2))
        if ci >= co - 1e-7:
            raise GeometryError("Скругление стирает плоскую кромку — уменьшите round.")
        phi_o = math.atan2(-r, co)
        phi_i = math.atan2(-r, ci)
        alpha_o = math.atan2(-r, co)
        alpha_i = math.atan2(r, -ci)
        prof = [(0.0, 0.0)]
        for i in range(1, steps + 1):
            phi = -math.pi / 2.0 + (phi_o + math.pi / 2.0) * i / steps
            prof.append((radius * math.cos(phi), radius + radius * math.sin(phi)))
        fillet_steps = max(5, min(24, segments // 5))
        for i in range(1, fillet_steps + 1):
            t = alpha_o + (math.pi / 2.0 - alpha_o) * i / fillet_steps
            prof.append((co + r * math.cos(t), radius - r + r * math.sin(t)))
        # ДВЕ явные вершины плоской кромки: иначе следующий сегмент
        # соединил бы наружную дугу с внутренней по наклонной.
        prof.append((ci, radius))
        for i in range(1, fillet_steps + 1):
            t = math.pi / 2.0 + (alpha_i - math.pi / 2.0) * i / fillet_steps
            prof.append((ci + r * math.cos(t), radius - r + r * math.sin(t)))
        for i in range(1, steps + 1):
            phi = phi_i + (-math.pi / 2.0 - phi_i) * i / steps
            prof.append((inner_r * math.cos(phi), radius + inner_r * math.sin(phi)))
    solid = _revolve(prof, segments, "чаши")
    if rim_w > 0.0:
        rim_w = min(rim_w, radius * 0.25)
        band_h = min(max(wall * 1.4, round_r * 2.2), radius * 0.45)
        ro = radius + rim_w
        z0, z1 = radius - band_h, radius
        br = min(round_r, band_h * 0.45, (ro - inner_r) / 2.0 * 0.95)
        band_prof = [(inner_r, z0), (ro, z0)]
        if br > 1e-6:
            band_prof.append((ro, z1 - br))
            for i in range(1, 9):
                t = math.pi / 2.0 * i / 8.0
                band_prof.append((ro - br + br * math.cos(t), z1 - br + br * math.sin(t)))
            band_prof.append((inner_r + br, z1))
            for i in range(1, 9):
                t = math.pi / 2.0 + math.pi / 2.0 * i / 8.0
                band_prof.append((inner_r + br + br * math.cos(t),
                                  z1 - br + br * math.sin(t)))
        else:
            band_prof += [(ro, z1), (inner_r, z1)]
        band_prof.append((inner_r, z0))
        solid = solid + _revolve(band_prof, segments, "бортика чаши")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="hemisphere")
    out.notes.append(f"чаша R{radius:g}, стенка {wall:g} мм, плоская кромка z={radius:g}, "
                     f"round={round_r:g}")
    return out


# --------------------------------------------------------------------------- #
#  Облако / вата
# --------------------------------------------------------------------------- #
@op("cloud", aliases=("облако", "вата", "облачко", "туча", "cloud_puff"),
    category="Примитивы",
    summary="Облако-вата: несколько сфер, сплавленных в одно пушистое тело. "
            "size — габарит, puffs — сколько шаров, seed повторяет форму, "
            "flat — подрезанное снизу дно, чтобы облако лежало на полке.",
    example="облако = cloud size=[180,90,70] puffs=9 seed=3\n"
            "вата = cloud size=[120,120,90] puffs=12 seed=7 flat=нет",
    params={"size": "габарит [x,y,z], мм (160,90,70)",
            "puffs": "число сфер (8)",
            "seed": "зерно формы (1)",
            "rough": "разброс размеров 0..1 (0.35)",
            "flat": "плоское дно да/нет (да)",
            "segments": "сегментов сферы (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cloud(a, name):
    size = a.vec("size", 3, default=(160.0, 90.0, 70.0))
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    puffs = int(a.num("puffs", 8, minv=3, maxv=40) or 8)
    seed = int(a.num("seed", 1, minv=0) or 0)
    rough = float(a.num("rough", 0.35, minv=0.0, maxv=1.0) or 0.0)
    flat = a.boolean("flat", True)
    seg = int(a.num("segments", max(12, min(32, int(8 + max(sx, sy, sz) / 8))),
                    minv=8, maxv=64) or 20)
    rng = np.random.default_rng(seed)
    # Шары должны ПЕРЕКРЫВАТЬСЯ, иначе это не облако, а гроздь шариков.
    # Кладём «грядку» перекрывающихся сфер по осям X и Y, сверху — бугры.
    unit = min(sx, sy, sz)
    base_r = unit * 0.45
    parts = []
    # нижний ряд: 3–5 шаров вдоль X, чтобы облако было вытянутым, а не шаром
    nx = max(3, min(6, int(round(sx / max(unit * 0.7, 1.0))) + 1))
    for i in range(nx):
        t = (i / (nx - 1)) - 0.5 if nx > 1 else 0.0
        r = base_r * (1.0 - 0.10 * abs(t) * 2.0)
        parts.append(mf.Manifold.sphere(r, seg).translate((sx * 0.42 * t, 0.0, r * 0.55)))
    # средний слой: бугры сбоку и сверху со случайным смещением
    bumps = max(3, puffs - nx)
    for i in range(bumps):
        ang = 2.0 * math.pi * i / bumps + float(rng.uniform(-0.3, 0.3))
        rad = float(rng.uniform(0.45, 0.72))
        k = 1.0 - rough * 0.25 * float(rng.random())
        r = base_r * 0.82 * k
        px = math.cos(ang) * sx * 0.30 * rad
        py = math.sin(ang) * sy * 0.34 * rad
        pz = base_r * (0.55 + 0.45 * float(rng.random()))
        parts.append(mf.Manifold.sphere(r, seg).translate((px, py, pz)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if solid.is_empty():
        raise GeometryError("Облако не собралось: увеличьте size или число сфер.")
    bb = solid.bounding_box()
    solid = solid.translate((0.0, 0.0, -bb[2]))
    if flat:
        cutter = mf.Manifold.cube([sx * 4.0, sy * 4.0, sz * 2.0], True)
        cutter = cutter.translate((0.0, 0.0, -sz * 0.10 - sz))
        solid = solid - cutter
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="cloud")
    out.notes.append(f"облако из {puffs} сфер, seed {seed}")
    return out
# --------------------------------------------------------------------------- #
#  Арка (полукольцо)
# --------------------------------------------------------------------------- #
#  Облако / вата
# --------------------------------------------------------------------------- #
@op("cloud", aliases=("облако", "вата", "облачко", "туча", "cloud_puff"),
    category="Примитивы",
    summary="Облако-вата: несколько сфер, сплавленных в одно пушистое тело. "
            "size — габарит, puffs — сколько шаров, seed повторяет форму, "
            "flat — подрезанное снизу дно, чтобы облако лежало на полке.",
    example="облако = cloud size=[180,90,70] puffs=9 seed=3\n"
            "вата = cloud size=[120,120,90] puffs=12 seed=7 flat=нет",
    params={"size": "габарит [x,y,z], мм (160,90,70)",
            "puffs": "число сфер (8)",
            "seed": "зерно формы (1)",
            "rough": "разброс размеров 0..1 (0.35)",
            "flat": "плоское дно да/нет (да)",
            "segments": "сегментов сферы (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cloud(a, name):
    size = a.vec("size", 3, default=(160.0, 90.0, 70.0))
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    puffs = int(a.num("puffs", 8, minv=3, maxv=40) or 8)
    seed = int(a.num("seed", 1, minv=0) or 0)
    rough = float(a.num("rough", 0.35, minv=0.0, maxv=1.0) or 0.0)
    flat = a.boolean("flat", True)
    seg = int(a.num("segments", max(12, min(32, int(8 + max(sx, sy, sz) / 8))),
                    minv=8, maxv=64) or 20)
    rng = np.random.default_rng(seed)
    # Шары должны ПЕРЕКРЫВАТЬСЯ, иначе это не облако, а гроздь шариков.
    # Кладём «грядку» перекрывающихся сфер по осям X и Y, сверху — бугры.
    unit = min(sx, sy, sz)
    base_r = unit * 0.45
    parts = []
    # нижний ряд: 3–5 шаров вдоль X, чтобы облако было вытянутым, а не шаром
    nx = max(3, min(6, int(round(sx / max(unit * 0.7, 1.0))) + 1))
    for i in range(nx):
        t = (i / (nx - 1)) - 0.5 if nx > 1 else 0.0
        r = base_r * (1.0 - 0.10 * abs(t) * 2.0)
        parts.append(mf.Manifold.sphere(r, seg).translate((sx * 0.42 * t, 0.0, r * 0.55)))
    # средний слой: бугры сбоку и сверху со случайным смещением
    bumps = max(3, puffs - nx)
    for i in range(bumps):
        ang = 2.0 * math.pi * i / bumps + float(rng.uniform(-0.3, 0.3))
        rad = float(rng.uniform(0.45, 0.72))
        k = 1.0 - rough * 0.25 * float(rng.random())
        r = base_r * 0.82 * k
        px = math.cos(ang) * sx * 0.30 * rad
        py = math.sin(ang) * sy * 0.34 * rad
        pz = base_r * (0.55 + 0.45 * float(rng.random()))
        parts.append(mf.Manifold.sphere(r, seg).translate((px, py, pz)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if solid.is_empty():
        raise GeometryError("Облако не собралось: увеличьте size или число сфер.")
    bb = solid.bounding_box()
    solid = solid.translate((0.0, 0.0, -bb[2]))
    if flat:
        cutter = mf.Manifold.cube([sx * 4.0, sy * 4.0, sz * 2.0], True)
        cutter = cutter.translate((0.0, 0.0, -sz * 0.10 - sz))
        solid = solid - cutter
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="cloud")
    out.notes.append(f"облако из {puffs} сфер, seed {seed}")
    return out


# --------------------------------------------------------------------------- #
#  Сердце
# --------------------------------------------------------------------------- #
def _heart_points(r: float, samples: int = 220) -> list[tuple[float, float]]:
    """Классическая кривая сердца, нормированная по ширине.

    Формула даёт сердце с остриём внизу по оси Y; масштаб подобран так,
    чтобы полуширина была ровно r, а не «примерно».
    """
    raw = []
    for i in range(samples):
        t = 2.0 * math.pi * i / samples
        x = 16.0 * math.sin(t) ** 3
        y = 13.0 * math.cos(t) - 5.0 * math.cos(2 * t) - 2.0 * math.cos(3 * t) - math.cos(4 * t)
        raw.append((x, y))
    span = max(abs(p[0]) for p in raw)
    k = r / span if span > 1e-9 else 1.0
    pts = [(x * k, y * k) for x, y in raw]
    # остриё вниз, верх посередине: сдвигаем по Y, чтобы низ был на z=0
    low = min(p[1] for p in pts)
    return [(x, y - low) for x, y in pts]


@op("heart", aliases=("сердце", "сердечко", "heart_shape"), category="Примитивы",
    summary="Сердце настоящей формы: два плавных лепестка сверху и остриё снизу. "
            "Ширина, высота, толщина и скругление рёбер задаются отдельно. "
            "По умолчанию стоит в плоскости XZ лицом −Y: лепестки сверху (+Z), "
            "остриё снизу (−Z), толщина по Y; plane=плашмя кладёт лицом +Z.",
    example="сердце = heart width=60 depth=20 round=2\n"
            "кулон = heart width=24 depth=8 round=1\n"
            "формочка = heart width=60 depth=12 wall=3",
    params={"width": "полная ширина, мм (60)", "depth": "толщина, мм (18)",
            "height": "высота, мм (по форме ≈ 0.9 ширины)",
            "wall": "стенка сквозной формочки/рамки, мм; 0 — сплошное (0)",
            "round": "радиус настоящего скругления кромок, мм (0); 0.2–0.5 от depth — "
                     "заметное округление, стоит ≈1 с",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом "
                     "вверх — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def heart(a, name):
    width = float(a.num("width", 60.0, minv=1.0))
    depth = float(a.num("depth", 18.0, minv=0.2))
    height = a.num("height", None, minv=0.5)
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    pts = _heart_points(width / 2.0)
    if height:
        cur = max(p[1] for p in pts)
        k = float(height) / max(cur, 1e-9)
        pts = [(x * k, y * k) for x, y in pts]
    cross = hollow_cross(_cross(pts), wall, "сердце")
    if round_r > 1e-3:
        # Скругление кромок: сжимаем контур на r и «надуваем» шаром радиуса r.
        # Кривая сердца на 220 точках — избыточно: 110 точек дают ту же форму,
        # а minkowski считается вдвое быстрее (1.0 с вместо 2.3 с).
        r = min(round_r, depth / 2.0 - 1e-4, width / 8.0)
        if wall > 1e-6:
            r = min(r, wall / 2.0 - 1e-4)
        if r > 1e-3:
            if wall <= 1e-6 and len(pts) > 110:
                step = int(round(len(pts) / 110.0))
                pts = pts[::step]
                cross = _cross(pts)
            core = cross.offset(-r, mf.JoinType.Round, 2.0, 16)
            solid = core.extrude(max(1e-3, depth - 2 * r)).translate((0, 0, r)) \
                .minkowski_sum(mf.Manifold.sphere(r, 14))
        else:
            solid = cross.extrude(depth)
    else:
        solid = cross.extrude(depth)
    return make_solid(a.scene, name, _placed(a, stand_flat_sign(a, solid)), a,
                      kind="heart")


# --------------------------------------------------------------------------- #
#  Плюс / перекрестие
# --------------------------------------------------------------------------- #
@op("plus", aliases=("плюс", "плюсик", "перекрестие", "крест", "cross_plus"),
    category="Примитивы",
    summary="Знак «плюс»: два пересекающихся бруса одинаковой толщины. "
            "По умолчанию стоит в XZ лицом −Y: arm задаёт оба размера в плоскости, "
            "thick — ширину бруса, depth — толщину по Y. Скругление скругляет "
            "внутренние углы и кромки.",
    example="плюс = plus arm=60 thick=18 depth=14 round=2\n"
            "аптечка = plus arm=120 thick=40 depth=20\n"
            "формочка = plus arm=60 thick=18 depth=10 wall=3",
    params={"plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом "
                     "вверх — «фронт»",
            "arm": "полная длина луча, мм (60)", "thick": "толщина бруса, мм (18)",
            "depth": "толщина по глубине, мм (14); у стоящего знака — по Y",
            "wall": "стенка сквозной формочки/рамки, мм; 0 — сплошной (0)",
            "round": "скругление, мм (0)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def plus(a, name):
    arm = float(a.num("arm", 60.0, minv=1.0))
    thick = float(a.num("thick", 18.0, minv=0.5))
    depth = float(a.num("depth", 14.0, minv=0.2))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if thick >= arm:
        raise GeometryError(f"Толщина бруса {thick:g} мм не может быть больше длины луча {arm:g} мм.",
                            hint="thick ≈ 0.2…0.45 от arm.")
    h = arm / 2.0
    t = thick / 2.0
    cs1 = mf.CrossSection([_profile([(-h, -t), (h, -t), (h, t), (-h, t)])])
    cs2 = mf.CrossSection([_profile([(-t, -h), (t, -h), (t, h), (-t, h)])])
    cross = mf.CrossSection.batch_boolean([cs1, cs2], mf.OpType.Add)
    cross = hollow_cross(cross, wall, "плюс")
    r = min(round_r, depth / 2.0 - 1e-4, thick / 3.0)
    if wall > 1e-6:
        r = min(r, wall / 2.0 - 1e-4)
    if r > 1e-3:
        core = cross.offset(-r, mf.JoinType.Round, 2.0, 24)
        solid = core.extrude(depth - 2 * r).translate((0, 0, r))
        solid = solid.minkowski_sum(mf.Manifold.sphere(r, 24))
    else:
        solid = cross.extrude(depth)
    return make_solid(a.scene, name, _placed(a, stand_flat_sign(a, solid)), a,
                      kind="plus")


# --------------------------------------------------------------------------- #
#  Сектор шара (и полусфера — его частный случай)
# --------------------------------------------------------------------------- #
@op("sector", aliases=("сектор", "долька", "ломтик", "доля_шара", "wedge"),
    category="Примитивы",
    summary="Сектор шара с любым углом: 90° — четвертинка, 180° — полусфера, "
            "360° — шар. Угол отсчитывается в плоскости XY и может быть повёрнут "
            "через start. Идеален для кусков арбуза, апельсина, сегментов купола.",
    example="долька = sector radius=50 angle=90 start=0\n" +
            "купол = sector radius=80 angle=180 thickness=6",
    params={"radius": "радиус шара, мм (50)", "angle": "угол сектора, ° (90)",
            "start": "откуда начинать угол, ° (0)", "thickness": "толщина стенки; "
            "0 — сплошной сектор (0)", "segments": "сегментов по дуге (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте",
            "up": "какая половина: верх, низ или обе (верх)"})
def sector(a, name):
    radius = float(a.num("radius", 50.0, minv=0.5))
    angle = float(a.num("angle", 90.0, minv=1.0, maxv=360.0))
    start = float(a.num("start", 0.0) or 0.0)
    thickness = float(a.num("thickness", 0.0, minv=0.0) or 0.0)
    up = (a.text("up") or "верх").strip().lower()
    seg = _segments(a.int("segments", None, minv=8, maxv=256),
                    max(24, min(180, int(angle / 2))))
    both = up in ("обе", "both", "полный")
    lower = up in ("низ", "low", "нижняя")
    if thickness >= radius - 1e-6:
        raise GeometryError(f"Стенка {thickness:g} мм больше радиуса {radius:g} мм.")
    two = max(48, seg * 2)
    ball = mf.Manifold.sphere(radius, two)
    # Стенку снимаем ДО разрезов: шар минус внутренний шар — без копланарных
    # граней. Если вычитать два пересечения с клином, на общей плоскости
    # получается «нулевая» стенка и булево рвёт сетку (род −8).
    if thickness > 1e-3:
        body = ball - mf.Manifold.sphere(radius - thickness, two)
    else:
        body = ball
    cut = mf.Manifold.cube((radius * 4.0, radius * 4.0, radius * 2.0), True)
    if not both:
        if lower:
            # оставляем нижнюю половину: снимаем всё, что выше пола
            body = body - cut.translate((0, 0, radius * 1.001))
            body = body.translate((0, 0, -radius))
        else:
            body = body - cut.translate((0, 0, -radius * 1.001))
    if angle < 359.9:
        # клин: центр плюс дуга. Треугольная «долька» на 180° вырождается
        # в отрезок и даёт пустое тело — дуга работает при любом угле.
        big = radius * 2.4
        n_arc = max(8, int(angle / 3.0))
        pts = [(0.0, 0.0)]
        for i in range(n_arc + 1):
            ang = math.radians(start + angle * i / n_arc)
            pts.append((big * math.cos(ang), big * math.sin(ang)))
        wedge = mf.Manifold.extrude(mf.CrossSection([_profile(pts)]), radius * 4.0) \
            .translate((0, 0, -radius * 2.0))
        body = mf.Manifold.batch_boolean([body, wedge], mf.OpType.Intersect)
    solid = ensure_volume(body, "сектора")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="sector")


# --------------------------------------------------------------------------- #
#  Спираль
# --------------------------------------------------------------------------- #
@op("spiral", aliases=("спираль", "улитка", "спираль_плоская", "helix_flat"),
    category="Примитивы",
    summary="Плоская спираль-улитка (архимедова): от центра наружу с заданным "
            "числом витков. По умолчанию стоит в плоскости XZ лицом −Y; "
            "plane=плашмя кладёт её в XY лицом +Z. wire — ширина нити в плоскости, "
            "height — её толщина по глубине (ось Y у стоящей спирали).",
    example="спираль = spiral radius=60 turns=3 wire=6 height=6\n" +
            "завиток = spiral radius=80 turns=4 wire=8 height=16 segments=48",
    params={"radius": "внешний радиус, мм (60)", "turns": "число витков (3)",
            "wire": "ширина нити в плоскости спирали, мм (6)",
            "height": "толщина по глубине, мм (6); у стоящей спирали — по Y",
            "gap": "зазор между витками, мм (авто)",
            "segments": "точек по витку (96)", "start": "угол начала, ° (0)",
            "plane": "фронт — стоит в XZ лицом −Y; плашмя — лежит в XY лицом +Z "
                     "(фронт)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def spiral(a, name):
    radius = float(a.num("radius", 60.0, minv=1.0))
    turns = float(a.num("turns", 3.0, minv=0.25, maxv=40.0))
    wire = float(a.num("wire", 6.0, minv=0.2))
    height = float(a.num("height", 6.0, minv=0.05))
    start = float(a.num("start", 0.0) or 0.0)
    seg = int(a.num("segments", 96, minv=24, maxv=400))
    pitch = radius / max(turns, 1e-6)
    gap = float(a.num("gap", max(0.0, pitch - wire)) or 0.0)
    if wire + max(0.0, gap) >= pitch + 1e-6 and turns > 1:
        raise GeometryError(
            f"Витки спирали налезут друг на друга: шаг между витками {pitch:g} мм, "
            f"а нить с зазором {wire + max(0.0, gap):g} мм.",
            hint=f"Уменьшите wire (сейчас {wire:g}) или увеличьте radius относительно turns.")
    r0 = max(wire / 2.0 + 0.5, 1.0)
    steps = int(max(seg * turns, 48))
    r_in = r0
    r_out = radius
    inner_pts, outer_pts = [], []
    for i in range(steps + 1):
        t = i / steps
        ang = math.radians(start) + 2 * math.pi * turns * t
        rr = r_in + (r_out - r_in) * t
        w = wire / 2.0
        # у самого центра нить сходит на нет остриём — иначе в середине
        # остаётся «пень» с плоским срезом, который видно при любом угле
        taper = min(1.0, t / 0.08) if t < 0.08 else 1.0
        w = max(0.02, w * taper)
        inner_pts.append(((rr - w) * math.cos(ang), (rr - w) * math.sin(ang)))
        outer_pts.append(((rr + w) * math.cos(ang), (rr + w) * math.sin(ang)))
    # контур: наружная кромка туда, круглая «пята» на внешнем конце,
    # внутренняя обратно, и остриё в центре
    ang_end = math.radians(start) + 2 * math.pi * turns
    w_end = wire / 2.0
    cx, cy = r_out * math.cos(ang_end), r_out * math.sin(ang_end)
    cap = []
    for k in range(1, 12):
        phi = ang_end + math.pi * k / 12
        cap.append((cx + w_end * math.cos(phi), cy + w_end * math.sin(phi)))
    pts = outer_pts + cap + inner_pts[::-1]
    cross = _cross([(x, y) for x, y in pts])
    solid = cross.extrude(height)
    solid = stand_flat_sign(a, solid)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="spiral")


# --------------------------------------------------------------------------- #
#  Верёвка из сплетённых нитей
# --------------------------------------------------------------------------- #
@op("rope", aliases=("верёвка", "веревка", "трос", "канат", "шнур", "cable", "cord"),
    category="Примитивы",
    summary="Кручёная верёвка: несколько нитей-цилиндров, обвивающих общую ось. "
            "Каждая нить — настоящая винтовая линия с круглым сечением, поэтому "
            "верёвка выглядит сплетённой при любом угле обзора. Ось — Z, "
            "длина и шаг свивки настраиваются.",
    example="канат = rope length=300 diameter=24 strands=3 twist=40\n" +
            "шнур = rope length=120 diameter=12 strands=3 twist=16",
    params={"length": "длина, мм (200)", "diameter": "наружный диаметр, мм (20)",
            "strands": "число нитей (3)", "wire": "толщина нити, мм (авто)",
            "twist": "длина одного витка свивки (шаг), мм (диаметр × 2.5)",
            "segments": "точек по поверхности (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def rope(a, name):
    length = float(a.num("length", 200.0, minv=2.0))
    diameter = float(a.num("diameter", 20.0, minv=0.5))
    strands = int(a.num("strands", 3, minv=2, maxv=12))
    twist = float(a.num("twist", diameter * 2.5, minv=1.0))
    segments = int(a.num("segments", None, minv=8, maxv=32) or 12) if a.has("segments") else 12
    # Нити должны касаться друг друга — иначе это не верёвка, а пучок
    # отдельных прутьев. Условие касания: 2·r·sin(π/n) ≤ wire, где r — радиус
    # окружности центров нитей, а наружный диаметр = 2·r + wire.
    sin_n = math.sin(math.pi / max(strands, 2))
    wire_min = diameter * sin_n / (1.0 + sin_n)
    wire = float(a.num("wire", wire_min * 1.08, minv=0.05))
    if wire < wire_min * 0.98:
        raise GeometryError(
            f"Нити не сплетаются: при {strands} нитях и диаметре {diameter:g} мм "
            f"нужна толщина не меньше {wire_min:.2f} мм, а задано {wire:g} мм.",
            hint=f"Уберите wire или поставьте wire={wire_min * 1.08:.2f}.")
    # наружный диаметр = 2·r + wire, поэтому нить не может быть толще ~0.6 D
    if wire > diameter * 0.62:
        raise GeometryError(
            f"Нить {wire:g} мм не проходит в верёвку диаметром {diameter:g} мм.",
            hint=f"wire ≤ {diameter * 0.55:.2f} мм при диаметре {diameter:g}.")
    core_r = max(0.1, diameter / 2.0 - wire / 2.0)
    pitches = max(1.0, length / max(twist, 1e-6))
    steps = max(64, int(round(pitches * 36)))
    r_turn = core_r          # нити касаются наружного диаметра
    pieces = []
    for k in range(strands):
        phase = 2.0 * math.pi * k / strands
        path = []
        for i in range(steps + 1):
            t = i / steps
            ang = phase + 2.0 * math.pi * pitches * t
            z = t * length
            path.append((r_turn * math.cos(ang), r_turn * math.sin(ang), z))
        pieces.append(_tube(np.asarray(path, dtype=np.float64), wire / 2.0, segments=segments))
    solid = mf.Manifold.batch_boolean(pieces, mf.OpType.Add)
    # Торцы: режем по длине, но не плоскостью — иначе круглые нити дают
    # «срез» с острыми кромками. Скругляем кромку радиусом в четверть нити.
    trim = mf.Manifold.cube((diameter * 4.0, diameter * 4.0, length), True) \
        .translate((0.0, 0.0, length / 2.0))
    solid = mf.Manifold.batch_boolean([solid, trim], mf.OpType.Intersect)
    # лёгкая фаска на торце: срезаем кромку конусом-фаской, а не двойным
    # minkowski (он на 10 000 треугольников стоил 20 с)
    edge = min(wire * 0.3, length * 0.1)
    if edge > 0.3:
        for z0, sign in ((0.0, 1.0), (length, -1.0)):
            chamfer = mf.Manifold.cylinder(edge * 2.0, diameter * 0.5 + wire,
                                           max(0.1, diameter * 0.5 - edge), 48, False)
            if sign > 0:
                chamfer = chamfer.translate((0.0, 0.0, -edge))
            else:
                chamfer = chamfer.rotate((180.0, 0.0, 0.0)).translate((0.0, 0.0, length + edge))
            solid = solid - chamfer
    return make_solid(a.scene, name, _placed(a, solid), a, kind="rope")


# --------------------------------------------------------------------------- #
#  Семисегментный индикатор
# --------------------------------------------------------------------------- #
_SEG_MAP = {
    "0": "ABCDEF", "1": "BC", "2": "ABGED", "3": "ABGCD", "4": "FGBC",
    "5": "AFGCD", "6": "AFGEDC", "7": "ABC", "8": "ABCDEFG", "9": "ABCFGD",
    "A": "ABCEFG", "b": "CDEFG", "C": "ADEF", "d": "BCDEG", "E": "ADEFG",
    "F": "AEFG", "-": "G", "_": "D", " ": "", "°": "", "o": "CDEG",
}


def _seg_polygon(length: float, thick: float, vertical: bool) -> list[tuple[float, float]]:
    """Контур одного сегмента: шестиугольник со скошенными концами."""
    half = length / 2.0
    t = thick / 2.0
    bevel = min(t, half * 0.6)
    pts = [(-half + bevel, t), (half - bevel, t), (half, 0.0),
           (half - bevel, -t), (-half + bevel, -t), (-half, 0.0)]
    if vertical:
        pts = [(-y, x) for x, y in pts]
    return pts


@op("seven_seg", aliases=("индикатор", "семисегментный", "цифры", "дисплей", "display",
                          "sevenseg", "led_display"),
    category="Примитивы",
    summary="Семисегментный индикатор: цифры и знаки из светящихся штрихов-«спичек» "
            "со скруглёнными концами и правильными пропорциями — сразу готов к "
            "material=led, получится горящий циферблат. Понимает цифры 0-9, знаки "
            "-, :, точку, пробел и латинские A-F. Каждый знак — отдельное тело: "
            "цифры можно красить, подсвечивать и двигать по одной.",
    example='цифры = seven_seg text="21:38" height=56\n'
            'часы = seven_seg text="20:00" height=40 depth=2 color=#ff2d55 '
            'emissive=#ff2d55 emissive_strength=5',
    params={"text": "что показать, например 21:38 (0)",
            "height": "высота цифры, мм (40)",
            "width": "ширина цифры, мм (0.58 × height)",
            "thick": "толщина штриха, мм (0.15 × height)",
            "gap": "зазор между цифрами, мм (0.32 × height)",
            "depth": "высота штриха над панелью, мм (2)",
            "slant": "наклон курсивом, градусы (0)",
            "plane": "фронт — цифры стоят лицом к зрителю, плашмя — лежат "
                     "лицом вверх — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["text"])
def seven_seg(a, name):
    text = str(a.text("text") or "0")
    if len(text) > 24:
        raise GeometryError("Слишком длинная строка индикатора: не больше 24 знаков.")
    h = float(a.num("height", 40.0, minv=1.0))
    w = float(a.num("width", h * 0.58, minv=0.2))
    t = float(a.num("thick", h * 0.15, minv=0.05))
    gap = float(a.num("gap", h * 0.32, minv=0.0))
    depth = float(a.num("depth", 2.0, minv=0.05))
    slant = float(a.num("slant", 0.0) or 0.0)
    if t >= min(w, h) * 0.9:
        raise GeometryError(f"Штрих {t:g} мм слишком толстый для цифры {w:g}×{h:g}.",
                            hint="thick ≈ 0.12…0.2 от height.")
    # ширина одного знака: цифра w, двоеточие — половина, пробел — половина
    def char_w(ch: str) -> float:
        if ch == ":":
            return w * 0.34
        if ch == " ":
            return w * 0.45
        if ch == ".":
            return w * 0.28
        return w

    total = sum(char_w(c) for c in text) + gap * max(0, len(text) - 1)
    x = -total / 2.0
    parts: list[mf.Manifold] = []

    def add_seg(cx: float, cy: float, length: float, thick: float, vertical: bool):
        poly = _seg_polygon(length, thick, vertical)
        poly = [(cx + px, cy + py) for px, py in poly]
        cross = _cross(poly)
        parts.append(cross.extrude(depth))

    for ch in text:
        cw = char_w(ch)
        cx = x + cw / 2.0
        if ch == ":":
            r = t * 0.55
            for cy in (h * 0.22, -h * 0.22):
                parts.append(mf.Manifold.cylinder(depth, r, r, 24, True)
                             .translate((cx, cy, depth / 2.0)))
        elif ch == ".":
            r = t * 0.5
            parts.append(mf.Manifold.cylinder(depth, r, r, 24, True)
                         .translate((cx + cw / 2.0 - r, -h / 2.0 + r, depth / 2.0)))
        else:
            segs = _SEG_MAP.get(ch)
            if segs is None:
                raise GeometryError(f"Индикатор не умеет показывать «{ch}».",
                                    hint="Доступно: 0-9, A-F, «-», «:», «.», пробел.")
            hw = cw / 2.0
            hh = h / 2.0
            off = t * 0.28
            # Горизонтали внутри высоты цифры: верхняя кромка ровно на +h/2,
            # вертикали — между ними. Тогда общая высота точно равна height.
            if "A" in segs:
                add_seg(cx, hh - t / 2.0, cw - off, t, False)
            if "D" in segs:
                add_seg(cx, -hh + t / 2.0, cw - off, t, False)
            if "G" in segs:
                add_seg(cx, 0.0, cw - off, t, False)
            vlen = hh - t * 0.7     # концы вертикалей заходят в горизонтали
            if "F" in segs:
                add_seg(cx - hw + t / 2.0, hh / 2.0, vlen, t, True)
            if "B" in segs:
                add_seg(cx + hw - t / 2.0, hh / 2.0, vlen, t, True)
            if "E" in segs:
                add_seg(cx - hw + t / 2.0, -hh / 2.0, vlen, t, True)
            if "C" in segs:
                add_seg(cx + hw - t / 2.0, -hh / 2.0, vlen, t, True)
        x += cw + gap
    if not parts:
        raise GeometryError("Индикатор пустой: в text нет ни одного знака.")
    solid = parts[0] if len(parts) == 1 else mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if abs(slant) > 1e-6:
        # курсив: сдвигаем верх относительно низа
        shear = np.eye(3, 4)
        shear[0, 2] = math.tan(math.radians(slant)) * 0.0
        shear[0, 1] = math.tan(math.radians(slant))
        solid = solid.transform(shear)
    solid = ensure_volume(solid, "индикатора")
    return make_solid(a.scene, name, _placed(a, stand_flat_sign(a, solid)), a,
                      kind="seven_seg")
