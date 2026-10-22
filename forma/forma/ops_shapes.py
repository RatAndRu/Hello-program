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
from .ops import anchor, make_solid, op


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
@op("star", aliases=("звезда", "звёздочка", "звездочка"), category="Примитивы",
    summary="Плоская звезда с настраиваемым числом лучей, глубиной впадин, "
            "фаской и скруглением рёбер.",
    example="звезда = star points=5 outer=60 inner=25 depth=12 bevel=1.5",
    params={"points": "число лучей (5)", "outer": "радиус кончика, мм (60)",
            "inner": "радиус впадины, мм (0.45 × outer)",
            "depth": "толщина, мм (12)", "bevel": "фаска верхних и нижних кромок, мм",
            "smooth": "плавность фаски 0..1 (вместе с bevel)",
            "twist": "закрутка, градусы (вместо фаски)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def star(a, name):
    points = int(a.num("points", 5, minv=3, maxv=64))
    outer = float(a.num("outer", 60.0, minv=0.5))
    inner = float(a.num("inner", outer * 0.45, minv=0.1))
    depth = float(a.num("depth", 12.0, minv=0.2))
    if inner >= outer - 1e-6:
        raise GeometryError(f"Впадина {inner:g} мм должна быть меньше кончика {outer:g} мм.",
                            hint="Для звезды inner ≈ 0.35…0.6 от outer.")
    if depth <= 1e-6:
        raise GeometryError("Толщина звезды должна быть больше нуля.")
    bevel = float(a.num("bevel", 0.0, minv=0.0) or 0.0)
    smooth = float(a.num("smooth", 0.0, minv=0.0, maxv=1.0) or 0.0)
    twist = float(a.num("twist", 0.0) or 0.0)
    pts = []
    for k in range(2 * points):
        angle = math.pi / 2 + k * math.pi / points
        radius = outer if k % 2 == 0 else inner
        pts.append((radius * math.cos(angle), radius * math.sin(angle)))
    cross = _cross(pts)
    if abs(twist) > 1e-6:
        solid = cross.extrude(depth, n_divisions=24, twist_degrees=twist)
    else:
        stages = 2 + int(round(smooth * 5))
        solid = _chamfered_prism(cross, depth, bevel, stages=stages)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="star")


# --------------------------------------------------------------------------- #
#  Кружка
# --------------------------------------------------------------------------- #
@op("cup", aliases=("кружка", "чашка", "mug"), category="Примитивы",
    summary="Кружка с полостью, дном и ручкой: стенка, сужение и размеры задаются.",
    example="кружка = cup diameter=80 height=95 wall=4 handle=да",
    params={"diameter": "наружный диаметр сверху, мм (80)",
            "height": "высота, мм (90)", "wall": "толщина стенки, мм (4)",
            "bottom": "толщина дна, мм (6)", "taper": "сужение к низу 0..0.3 (0.1)",
            "handle": "сделать ручку (да)", "handle_radius": "радиус ручки, мм (26)",
            "handle_wire": "толщина ручки, мм (5)", "segments": "сегментов по кругу",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cup(a, name):
    diameter = float(a.num("diameter", 80.0, minv=1.0))
    height = float(a.num("height", 90.0, minv=1.0))
    wall = float(a.num("wall", 4.0, minv=0.2))
    bottom = float(a.num("bottom", 6.0, minv=0.2))
    taper = float(a.num("taper", 0.1, minv=0.0, maxv=0.45) or 0.0)
    r0 = diameter / 2.0
    rb = r0 * (1.0 - taper)
    if wall >= rb - 1.0:
        raise GeometryError(f"Стенка {wall:g} мм не оставляет полости при радиусе {rb:g} мм.",
                            hint="wall должен быть меньше радиуса минус 1 мм.")
    if bottom >= height - wall:
        raise GeometryError(f"Дно {bottom:g} мм выше стенки при высоте {height:g} мм.")
    segments = _segments(a.int("segments", None, minv=24, maxv=256), 96)
    profile = [(0.0, 0.0), (rb, 0.0), (r0, height), (r0 - wall, height),
               (rb - wall, bottom), (0.0, bottom)]
    solid = _revolve(profile, segments, "кружка")
    if a.boolean("handle", True):
        hrad = float(a.num("handle_radius", max(12.0, r0 * 0.65), minv=3.0))
        wire = float(a.num("handle_wire", max(2.0, r0 * 0.12), minv=1.0))
        if wire >= hrad * 0.8:
            raise GeometryError("Ручка слишком толстая для своего радиуса.")
        # Концы ручки входят в стенку на её середине, а дуга выходит наружу.
        # Иначе у маленькой кружки ручка протыкала бы полость.
        sin_end = math.sin(math.radians(82.0))
        hspan = min(hrad * sin_end, height * 0.42)
        cz = height * 0.5
        z_low, z_high = cz - hspan, cz + hspan
        r_low = rb + (r0 - rb) * (z_low / height)
        r_high = rb + (r0 - rb) * (z_high / height)
        x_attach = min(r_low, r_high) - wall * 0.5
        cx = x_attach - hrad * math.cos(math.radians(82.0))
        path = []
        for i in range(41):
            ang = math.radians(-82.0 + 164.0 * i / 40.0)
            path.append((cx + hrad * math.cos(ang), 0.0, cz + hspan * math.sin(ang)))
        handle = _tube(np.asarray(path), wire, segments=16)
        solid = ensure_volume(solid + handle, "кружка")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="cup")


# --------------------------------------------------------------------------- #
#  Тарелка
# --------------------------------------------------------------------------- #
@op("plate", aliases=("тарелка", "блюдо", "dish"), category="Примитивы",
    summary="Тарелка с бортом и плоским дном — глубокая или мелкая, стенка задаётся.",
    example="тарелка = plate diameter=220 depth=26 wall=4",
    params={"diameter": "диаметр, мм (220)", "depth": "высота борта, мм (26)",
            "wall": "толщина стенки и дна, мм (4)",
            "well": "доля плоского дна 0.2..0.9 (0.62)", "segments": "сегментов по кругу",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def plate(a, name):
    diameter = float(a.num("diameter", 220.0, minv=5.0))
    depth = float(a.num("depth", 26.0, minv=1.0))
    wall = float(a.num("wall", 4.0, minv=0.3))
    well = float(a.num("well", 0.62, minv=0.2, maxv=0.9) or 0.62)
    r = diameter / 2.0
    if wall >= depth - 0.5 or wall >= r * 0.5:
        raise GeometryError(f"Стенка {wall:g} мм слишком толстая для тарелки {diameter:g}×{depth:g} мм.")
    segments = _segments(a.int("segments", None, minv=32, maxv=256), 120)
    rw = r * well
    rim = max(0.6, wall * 0.35)
    profile = [
        (0.0, 0.0), (rw, 0.0), (r - rim, depth * 0.35), (r, depth * 0.75),
        (r, depth), (r - wall * 1.4, depth), (r - wall * 1.4, depth * 0.72),
        (r - wall * 2.2, depth * 0.36), (rw, wall), (0.0, wall),
    ]
    solid = _revolve(profile, segments, "тарелка")
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
    summary="Прямозубая шестерня: число зубьев, модуль, толщина, ступица и отверстие.",
    example="шестерня = gear teeth=20 module=2 thickness=8 bore=8",
    params={"teeth": "число зубьев (20)", "module": "модуль, мм (2)",
            "thickness": "толщина, мм (8)", "bore": "диаметр отверстия, мм (0 — без него)",
            "hub": "диаметр ступицы, мм (0 — без ступицы)", "hub_height": "высота ступицы (толщина)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gear(a, name):
    teeth = int(a.num("teeth", 20, minv=6, maxv=200))
    module = float(a.num("module", 2.0, minv=0.05))
    thickness = float(a.num("thickness", 8.0, minv=0.2))
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    hub = float(a.num("hub", 0.0, minv=0.0) or 0.0)
    hub_h = float(a.num("hub_height", thickness, minv=0.2))
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
    if hub > 0:
        if hub / 2.0 <= (bore / 2.0 if bore else 0) + 0.5:
            raise GeometryError("Ступица должна быть толще отверстия.")
        hub_m = mf.Manifold.cylinder(hub_h, hub / 2.0, hub / 2.0, 64)
        if bore > 0:
            hub_m = hub_m - mf.Manifold.cylinder(hub_h + 2, bore / 2.0, bore / 2.0, 48).translate((0, 0, -1))
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
    summary="Брусок с круглым отверстием по центру — учебная деталь и заготовка.",
    example="кубик = cube_hole size=[40,40,40] hole=16",
    params={"size": "размер [x,y,z], мм (40,40,40)", "hole": "диаметр отверстия, мм (40% размера)",
            "axis": "ось отверстия: z, x или y (z)", "round": "скругление рёбер, мм",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cube_hole(a, name):
    size = a.vec("size", 3, default=(40.0, 40.0, 40.0))
    if any(v <= 0 for v in size):
        raise GeometryError("Размеры бруска должны быть больше нуля.")
    hole = float(a.num("hole", min(size) * 0.4, minv=0.2))
    if hole >= min(size) - 1.0:
        raise GeometryError(f"Отверстие ø{hole:g} мм не помещается в брусок {size}.")
    axis = (a.text("axis", "z") or "z").strip().lower()
    if axis not in ("x", "y", "z"):
        raise GeometryError("Ось отверстия: z, x или y.")
    box = mf.Manifold.cube(size, True)
    rnd = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if rnd > 1e-6:
        rnd = min(rnd, min(size) / 2 - 1e-3)
        inner = [max(s - 2 * rnd, 1e-3) for s in size]
        box = mf.Manifold.cube(inner, True).minkowski_sum(mf.Manifold.sphere(rnd, 24))
    length = max(size) + 10
    cyl = mf.Manifold.cylinder(length, hole / 2.0, hole / 2.0, 64).translate((0, 0, -length / 2))
    if axis == "x":
        cyl = cyl.rotate((0, 90, 0))
    elif axis == "y":
        cyl = cyl.rotate((90, 0, 0))
    solid = ensure_volume(box - cyl, "брусок с отверстием")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="cube_hole")


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
    params={"diameter": "внутренний диаметр, мм (20)", "width": "ширина обода, мм (6)",
            "thickness": "толщина стенки, мм (2.2)", "round": "скругление краёв, мм",
            "segments": "сегментов по кругу", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def ring(a, name):
    diameter = float(a.num("diameter", 20.0, minv=1.0))
    width = float(a.num("width", 6.0, minv=0.4))
    thickness = float(a.num("thickness", 2.2, minv=0.2))
    r_in = diameter / 2.0
    r_out = r_in + thickness
    if thickness >= width:
        raise GeometryError("Толщина кольца должна быть меньше его ширины.")
    rnd = float(a.num("round", min(thickness, width) * 0.3, minv=0.0) or 0.0)
    rnd = min(rnd, thickness * 0.45, width * 0.45)
    segments = _segments(a.int("segments", None, minv=32, maxv=256), 120)
    profile = _rounded_rect(r_in, r_out, -width / 2.0, width / 2.0, rnd, steps=5)
    solid = _revolve(profile, segments, "кольцо")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="ring")
