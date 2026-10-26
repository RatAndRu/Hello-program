"""Детали и узлы: коробка, труба, отверстия, вал, ручка, колесо, рейка,
муфта, радиатор, камень, лист, ветка и разброс деталей.

Правило отбора: фигура оправдана, если заменяет три и более команды или несёт
стандарт, который нельзя выдумать (M6, подшипник 608, профиль 2020, ячейка
18650). Всё остальное — одна строка ``lathe``/``extrude`` и в меню не нужно.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import anchor, make_solid, op, stand_flat_sign
from .shape_features import varied_edge_thickness


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
def _one(a, command: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{command} работает с одним объектом.",
                            hint=f"Формат: имя = {command} [объект] …")
    return solids[0]


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _shifted(a, solid: mf.Manifold) -> mf.Manifold:
    """Только сдвиг: для модификаторов, которые не должны ронять деталь на пол."""
    if not a.has("at"):
        return solid
    return solid.translate(tuple(float(v) for v in a.vec("at", 3, default=(0, 0, 0))))


def _axis_rotate(m: mf.Manifold, axis: str) -> mf.Manifold:
    axis = (axis or "z").strip().lower().lstrip("+-")
    if axis == "x":
        return m.rotate([0.0, 90.0, 0.0])
    if axis == "y":
        return m.rotate([-90.0, 0.0, 0.0])
    return m


def _seg(a, key: str = "segments", default: int = 64, minv: int = 12,
         maxv: int = 256) -> int:
    value = a.int(key, None, minv=minv, maxv=maxv)
    if value is None:
        return default
    return int(max(minv, min(maxv, int(value))))


def _pair(a, key: str, default):
    if not a.has(key):
        return tuple(default)
    raw = a.value(key)
    if isinstance(raw, (int, float)):
        return (float(raw), float(raw))
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (float(raw[0]), float(raw[1]))
    raise GeometryError(f"{key} должен быть парой чисел [x, y].",
                        hint="Например: pitch=[40, 30]")


def _triple(a, key: str, default):
    if not a.has(key):
        return tuple(default)
    raw = a.value(key)
    if isinstance(raw, (int, float)):
        return (float(raw),) * 3
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    raise GeometryError(f"{key} должен быть списком из трёх чисел [x, y, z].")


def _signed_area(points) -> float:
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _profile(points):
    return points if _signed_area(points) > 0 else points[::-1]


def _dedupe(points, tol: float = 1e-6):
    out = []
    for p in points:
        if not out or abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    if len(out) > 2 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def _rect_profile(width: float, depth: float, radius: float, seg: int = 8):
    """Прямоугольник со скруглёнными углами (контур против часовой стрелки)."""
    width, depth = float(width), float(depth)
    radius = max(0.0, min(float(radius), min(width, depth) / 2.0 - 1e-3))
    if radius <= 1e-6:
        return [(-width / 2, -depth / 2), (width / 2, -depth / 2),
                (width / 2, depth / 2), (-width / 2, depth / 2)]
    r = radius
    steps = max(2, int(seg))
    corners = [(width / 2 - r, -depth / 2 + r, -90.0),
               (width / 2 - r, depth / 2 - r, 0.0),
               (-width / 2 + r, depth / 2 - r, 90.0),
               (-width / 2 + r, -depth / 2 + r, 180.0)]
    points = []
    for cx, cy, start in corners:
        for i in range(steps + 1):
            angle = math.radians(start + 90.0 * i / steps)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _revolve_profile(points, segments: int, what: str) -> mf.Manifold:
    points = _dedupe(list(points))
    cs = mf.CrossSection([_profile(points)])
    if cs.is_empty():
        raise GeometryError(f"Профиль {what} не замкнут.",
                            hint="Точки профиля задаются парой (радиус, высота).")
    solid = mf.Manifold.revolve(cs, int(segments))
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError(f"{what.capitalize()} получилась пустой.",
                            hint="Проверьте размеры: профиль не должен самопересекаться.")
    return solid


def _tube_mesh(pts: np.ndarray, radius, sides: int, what: str,
               wall: float | None = None) -> mf.Manifold:
    """Труба по пути; при wall сразу строит полое тело с кольцевыми торцами."""
    pts = np.asarray(pts, dtype=np.float64)
    radii = np.asarray(radius if isinstance(radius, (list, tuple, np.ndarray))
                       else [radius] * len(pts), dtype=np.float64)
    if len(pts) < 2:
        raise GeometryError(f"Для {what} нужны хотя бы две точки пути.")
    tangents = []
    for i in range(len(pts)):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == len(pts) - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        norm = float(np.linalg.norm(t))
        if norm < 1e-9:
            raise GeometryError(f"Путь {what} содержит повторяющиеся точки.")
        tangents.append(t / norm)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(tangents[0], ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    rings = []
    frames = []
    prev_n = None
    for p, t in zip(pts, tangents):
        if prev_n is None:
            nvec = np.cross(t, ref)
        else:
            nvec = prev_n - t * float(np.dot(prev_n, t))
        norm = float(np.linalg.norm(nvec))
        if norm < 1e-9:
            nvec = np.cross(t, ref)
            norm = float(np.linalg.norm(nvec))
        nvec = nvec / max(norm, 1e-9)
        bvec = np.cross(t, nvec)
        ring = [p + radii[len(rings)] * (math.cos(2 * math.pi * j / sides) * nvec
                                         + math.sin(2 * math.pi * j / sides) * bvec)
                for j in range(sides)]
        rings.append(ring)
        frames.append((p, nvec.copy(), bvec.copy()))
        prev_n = nvec
    if wall is not None:
        inner = []
        for i, (p, nvec, bvec) in enumerate(frames):
            r = radii[i] - wall
            if r <= 0.0:
                raise GeometryError(f"Стенка {what} не оставляет просвета.")
            inner.append([p + r * (math.cos(2 * math.pi * j / sides) * nvec
                                   + math.sin(2 * math.pi * j / sides) * bvec)
                          for j in range(sides)])
        verts = []
        for outer_ring, inner_ring in zip(rings, inner):
            verts.extend(tuple(v) for v in outer_ring)
            verts.extend(tuple(v) for v in inner_ring)
        faces = []
        stride = sides * 2
        for i in range(len(rings) - 1):
            b0, b1 = i * stride, (i + 1) * stride
            for j in range(sides):
                j2 = (j + 1) % sides
                # Наружная поверхность.
                faces.append((b0 + j, b0 + j2, b1 + j2))
                faces.append((b0 + j, b1 + j2, b1 + j))
                # Внутренняя поверхность с противоположной ориентацией.
                faces.append((b0 + sides + j, b1 + sides + j2, b0 + sides + j2))
                faces.append((b0 + sides + j, b1 + sides + j, b1 + sides + j2))
        last = (len(rings) - 1) * stride
        for j in range(sides):
            j2 = (j + 1) % sides
            # Оба торца — плоские кольца, без центральных вершин и boolean.
            faces.append((j, sides + j, sides + j2))
            faces.append((j, sides + j2, j2))
            faces.append((last + j, last + j2, last + sides + j2))
            faces.append((last + j, last + sides + j2, last + sides + j))
        return manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                    np.asarray(faces, dtype=np.int64), what)
    verts = [tuple(v) for ring in rings for v in ring]
    faces = []
    for i in range(len(rings) - 1):
        b0, b1 = i * sides, (i + 1) * sides
        for j in range(sides):
            j2 = (j + 1) % sides
            faces.append((b0 + j, b0 + j2, b1 + j2))
            faces.append((b0 + j, b1 + j2, b1 + j))
    c0 = len(verts)
    verts.append(tuple(pts[0]))
    c1 = len(verts)
    verts.append(tuple(pts[-1]))
    last = (len(rings) - 1) * sides
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append((c0, j2, j))
        faces.append((c1, last + j, last + j2))
    return manifold_from_arrays(np.asarray(verts, dtype=np.float64),
                                np.asarray(faces, dtype=np.int64), what)


# --------------------------------------------------------------------------- #
#  Коробка с полостью
# --------------------------------------------------------------------------- #
@op("box_body", aliases=("ящик", "открытый_ящик", "open_box", "коробка_с_полостью"),
    category="Примитивы",
    summary="Коробка с дном и стенками — открытая сверху. Размеры, стенка, "
            "толщина дна и скругление углов.",
    example="коробка = box_body size=[200, 150, 80] wall=4 bottom=6 round=8",
    params={"size": "внешние размеры [x,y,z], мм (100,100,50)",
            "wall": "толщина стенок (4)", "bottom": "толщина дна (6)",
            "round": "радиус скругления углов в плане (0)",
            "relief": "припуск по стенкам для сборки, мм (0)",
            "segments": "сегментов в скруглении", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def box_body(a, name):
    sx, sy, sz = _triple(a, "size", (100.0, 100.0, 50.0))
    wall = float(a.num("wall", 4.0, minv=0.2))
    bottom = float(a.num("bottom", 6.0, minv=0.2))
    relief = float(a.num("relief", 0.0, minv=0.0) or 0.0)
    if wall * 2 >= min(sx, sy) - 1.0:
        raise GeometryError("Стенки не оставляют полости.",
                            hint="wall должен быть меньше половины меньшей стороны.")
    if bottom >= sz - 1.0:
        raise GeometryError("Дно выше высоты коробки.")
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    seg = _seg(a, "segments", 8, 2, 32)
    outer = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx, sy, round_r, seg)]), float(sz))
    inner_sx = sx - 2.0 * (wall + relief)
    inner_sy = sy - 2.0 * (wall + relief)
    inner_sz = sz - bottom + 1.0
    if inner_sx <= 0.5 or inner_sy <= 0.5 or inner_sz <= 0.5:
        raise GeometryError("Стенки не оставляют полости.")
    inner = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(inner_sx, inner_sy,
                                       max(0.0, round_r - wall - relief), seg)]),
        float(inner_sz))
    inner = inner.translate((0.0, 0.0, bottom))
    solid = outer - inner
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Коробка получилась пустой — уменьшите стенки.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="box_body")
    out.notes.append(f"стенка {wall:g} мм, дно {bottom:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Труба: простой прямой/согнутый режим и совместимый path
# --------------------------------------------------------------------------- #
def _simple_pipe_path(length: float, angle: float, radius: float,
                      joint: str, diameter: float) -> np.ndarray:
    """Центральная линия в XZ; length — развёрнутая длина прямых и дуги."""
    if abs(angle) < 1e-9:
        return np.asarray([[0.0, 0.0, 0.0], [length, 0.0, 0.0]])
    if joint == "острый":
        if abs(angle) >= 179.5:
            raise GeometryError("Острый стык на 180° вырождается в нулевую митру.",
                                hint="Используйте joint=плавный или уменьшите angle.")
        leg = length / 2.0
        theta = math.radians(angle)
        return np.asarray([[0.0, 0.0, 0.0], [leg, 0.0, 0.0],
                           [leg + leg * math.cos(theta), 0.0,
                            math.copysign(leg * math.sin(abs(theta)), angle)]])
    theta = math.radians(abs(angle))
    if radius <= diameter / 2.0 + 0.05:
        raise GeometryError("radius слишком мал: внутренняя сторона сгиба схлопнется.",
                            hint=f"Задайте radius больше {diameter / 2 + 0.05:g} мм.")
    arc_length = radius * theta
    if arc_length >= length - 0.05:
        raise GeometryError("Дуга не помещается в заданную length.",
                            hint="Увеличьте length, уменьшите radius или angle.")
    tail = (length - arc_length) / 2.0
    sign = 1.0 if angle > 0 else -1.0
    points = [[0.0, 0.0, 0.0]]
    if tail > 1e-8:
        points.append([tail, 0.0, 0.0])
    steps = max(8, min(180, int(math.ceil(abs(angle) / 4.0))))
    for i in range(1, steps + 1):
        phi = theta * i / steps
        points.append([tail + radius * math.sin(phi), 0.0,
                       sign * radius * (1.0 - math.cos(phi))])
    if tail > 1e-8:
        end = np.asarray(points[-1])
        tangent = np.asarray([math.cos(theta), 0.0, sign * math.sin(theta)])
        points.append((end + tail * tangent).tolist())
    return np.asarray(points, dtype=float)


@op("pipe", aliases=("трубка", "трубопровод", "tube"),
    category="Тела вращения и развёртки",
    summary="Труба с настоящей стенкой. Без path достаточно length, diameter "
            "и wall: angle −180…180° задаёт сгиб в XZ, joint=плавный/острый, "
            "radius — радиус центральной дуги. Оба открытых торца — плоские "
            "кольца одной сетки, без булева вычитания. Старый path сохранён.",
    example="прямая = pipe length=180 diameter=24 wall=2\n"
            "плавная = pipe length=220 angle=90 radius=70 joint=плавный diameter=24 wall=2\n"
            "острая = pipe length=180 angle=60 joint=острый diameter=20 wall=1.5",
    params={"length": "развёрнутая длина простой трубы, мм (200)",
            "angle": "угол сгиба −180…180°; знак задаёт сторону в XZ (0)",
            "radius": "радиус центральной линии плавного сгиба, мм (80)",
            "joint": "плавный или острый сгиб (плавный)",
            "path": "старое совместимое задание точками [[x,y,z],…]; отключает простой режим",
            "diameter": "наружный диаметр (32)", "wall": "толщина стенки (2)",
            "sides": "сегментов по кругу (24)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def pipe(a, name):
    diameter = float(a.num("diameter", 32.0, minv=1.0))
    wall = float(a.num("wall", 2.0, minv=0.2))
    if wall * 2 >= diameter - 0.4:
        raise GeometryError("Стенка не оставляет просвета в трубе.")
    sides = _seg(a, "sides", 24, 8, 96)
    legacy = a.has("path")
    if legacy:
        path = a.points("path", 3)
        if len(path) < 2:
            raise GeometryError("Для трубы нужны хотя бы две точки пути.",
                                hint="Например: труба = pipe path=[[0,0,0],[0,0,400]] diameter=32")
        pts = np.asarray(path, dtype=np.float64)
        joint = "path"
    else:
        length = float(a.num("length", 200.0, minv=1.0, maxv=100000.0))
        angle = float(a.num("angle", 0.0, minv=-180.0, maxv=180.0) or 0.0)
        radius = float(a.num("radius", 80.0, minv=0.5, maxv=100000.0))
        joint = (a.text("joint", "плавный") or "плавный").strip().lower()
        joint = {"плавный": "плавный", "плавная": "плавный", "скруглённый": "плавный",
                 "острый": "острый", "острая": "острый", "митра": "острый"}.get(joint)
        if joint is None:
            raise GeometryError("pipe.joint=плавный или острый.")
        pts = _simple_pipe_path(length, angle, radius, joint, diameter)
    solid = _tube_mesh(pts, diameter / 2.0, sides, "труба", wall=wall)
    if solid.is_empty() or solid.volume() <= 1e-6 or len(solid.decompose()) != 1:
        raise GeometryError("Труба получилась пустой или распалась на части.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="pipe")
    out.meta["path_mode"] = "legacy" if legacy else "simple"
    out.meta["joint"] = joint
    out.notes.append(f"ø{diameter:g}×{wall:g} мм, длина {_path_length(pts):.0f} мм, режим {joint}")
    return out


def _path_length(pts: np.ndarray) -> float:
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


# --------------------------------------------------------------------------- #
#  Отверстия и перфорация
# --------------------------------------------------------------------------- #
@op("holes", aliases=("отверстия", "просверлить", "drill", "перфорация"),
    category="Форма и деформации",
    summary="Сверлит сетку отверстий в готовой детали. Сквозные или на глубину, "
            "с зенковкой. Один вызов вместо десятка difference.",
    example='панель = box size=[120,90,10]\n'
            'панель = holes [панель] grid=[3,2] diameter=6 pitch=[40,30] offset=[12,-8]',
    params={"objects": "объект, в котором сверлим",
            "diameter": "диаметр отверстия, мм (6)",
            "grid": "сколько отверстий по двум осям [nx,ny] (2,2)",
            "pitch": "шаг между отверстиями [px,py], мм (3·диаметр)",
            "positions": "свои точки [[x,y], …] вместо сетки",
            "axis": "ось сверления: x, y или z (z)",
            "through": "сквозные да/нет (да)", "depth": "глубина, если не сквозное",
            "countersink": "зенковка: ширина фаски, мм (0)",
            "perforate": "шахматный порядок да/нет (нет)",
            "offset": "сдвиг всей сетки от центра детали [dx,dy], мм (0,0)",
            "corner": "отсчитывать offset от левого нижнего угла, а не от центра (нет)",
            "segments": "сегментов отверстия (24)", "at": "сдвиг [x,y,z]",
            "center": "центрировать по высоте"},
    positional=["objects"])
def holes(a, name):
    base = _one(a, "holes")
    axis = (a.text("axis", "z") or "z").strip().lower()
    if axis.lstrip("+-") not in ("x", "y", "z"):
        raise GeometryError("axis должен быть x, y или z.")
    axis = axis.lstrip("+-")
    diameter = float(a.num("diameter", 6.0, minv=0.4))
    segments = _seg(a, "segments", 24, 8, 64)
    through = a.boolean("through", True)
    bb = base.manifold.bounding_box()
    lo, hi = bb[{"x": 0, "y": 1, "z": 2}[axis]], bb[{"x": 3, "y": 4, "z": 5}[axis]]
    span = hi - lo
    depth = span + 3.0 if through else float(a.num("depth", 8.0, minv=0.5))
    countersink = float(a.num("countersink", 0.0, minv=0.0) or 0.0)
    center = [(bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0]
    # сдвиг сетки относительно центра детали: сверлим не только по центру,
    # но и в любом месте плоскости (например, ближе к кромке)
    offset = _pair(a, "offset", (0.0, 0.0))
    if a.has("positions"):
        raw = a.value("positions")
        if not isinstance(raw, (list, tuple)):
            raise GeometryError("positions должен быть списком точек [[x,y], …].")
        positions = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                positions.append((float(item[0]), float(item[1]),
                                  float(item[2]) if len(item) > 2 else center[2]))
        if not positions:
            raise GeometryError("positions пуст — нечего сверлить.")
    else:
        nx, ny = [max(1, int(v)) for v in _pair(a, "grid", (2, 2))]
        px, py = _pair(a, "pitch", (diameter * 3.0, diameter * 3.0))
        zigzag = a.boolean("perforate", False)
        positions = []
        for j in range(ny):
            for i in range(nx):
                dx = (i - (nx - 1) / 2.0) * px
                if zigzag and j % 2:
                    dx += px / 2.0
                positions.append((center[0] + dx + offset[0],
                                  center[1] + (j - (ny - 1) / 2.0) * py + offset[1],
                                  center[2]))
    solid = _drill(base.manifold, axis, positions, diameter, depth, through,
                   countersink, segments)
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("После сверления ничего не осталось.")
    out = make_solid(a.scene, name, _shifted(a, solid), a, base=base, kind="holes")
    a.scene.consume(base)
    out.notes.append(f"отверстий {len(positions)} по ø{diameter:g} мм")
    return out


def _drill(base: mf.Manifold, axis: str, positions, diameter: float,
           depth: float, through: bool, countersink: float,
           segments: int) -> mf.Manifold:
    bb = base.bounding_box()
    lo, hi = bb[{"x": 0, "y": 1, "z": 2}[axis]], bb[{"x": 3, "y": 4, "z": 5}[axis]]
    r = max(0.2, diameter / 2.0)
    if through:
        body_len = (hi - lo) + 4.0
        z0 = lo - 2.0
    else:
        body_len = float(depth) + 1.0
        z0 = hi - float(depth)
    tools = []
    for pos in positions:
        p = [float(pos[0]), float(pos[1]), float(pos[2])]
        tool = mf.Manifold.cylinder(body_len, r, r, segments).translate((0.0, 0.0, z0))
        if countersink > 0:
            cone = mf.Manifold.cylinder(countersink + 0.8, r, r + countersink, segments)
            cone = cone.translate((0.0, 0.0, hi - countersink - 0.8))
            tool = tool + cone
        if axis == "x":
            tool = tool.rotate([0.0, 90.0, 0.0]).translate((0.0, p[1], p[2]))
        elif axis == "y":
            tool = tool.rotate([90.0, 0.0, 0.0]).translate((p[0], 0.0, p[2]))
        else:
            tool = tool.translate((p[0], p[1], 0.0))
        tools.append(tool)
    if not tools:
        raise GeometryError("Не задано ни одного отверстия.")
    return mf.Manifold.batch_boolean([base] + tools, mf.OpType.Subtract)


# --------------------------------------------------------------------------- #
#  Вал со ступенями
# --------------------------------------------------------------------------- #
@op("shaft", aliases=("вал", "ось", "ступенчатый_вал"), category="Примитивы",
    summary="Ступенчатый вал: диаметры и длины ступеней, фаски на концах и "
            "осевое отверстие. Одно тело вращения. Отличие от кольца и тора: "
            "вал — сплошной стержень (с отверстием или без) с буртиком по оси; "
            "фланец у буртика задаётся шириной и радиусом, а не толщиной стенки.",
    example="вал = shaft diameter=20 length=120 bore=6\n"
            "вал_с_буртиком = shaft diameter=20 length=140 flange=6 flange_d=46",
    params={"diameter": "диаметр, мм (20)", "length": "длина, мм (100)",
            "steps": "ступени [[длина, диаметр], …] вместо одного диаметра",
            "flange": "ширина буртика по оси, мм (0 — без буртика)",
            "flange_d": "диаметр буртика (2·diameter)",
            "flange_at": "где стоит буртик, мм от начала (length/2)",
            "flange_round": "скругление кромок буртика, мм (0.5)",
            "chamfer": "фаска на концах, мм (1)",
            "bore": "осевое отверстие насквозь, мм (0)",
            "axis": "ось вала: x, y или z (z)", "segments": "сегментов (64)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def shaft(a, name):
    length = float(a.num("length", 100.0, minv=1.0))
    diameter = float(a.num("diameter", 20.0, minv=0.5))
    chamfer = float(a.num("chamfer", 1.0, minv=0.0) or 0.0)
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    segments = _seg(a, "segments", 64, 16, 256)
    steps = []
    if a.has("steps"):
        raw = a.value("steps")
        if not isinstance(raw, (list, tuple)):
            raise GeometryError("steps должен быть списком [[длина, диаметр], …].")
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                raise GeometryError("Каждая ступень — [длина, диаметр].")
            steps.append((max(0.2, float(item[0])), max(0.6, float(item[1]))))
        if not steps:
            raise GeometryError("steps пуст.")
    else:
        steps = [(length, diameter)]
    thin_side = min(min(s[0] for s in steps), min(s[1] for s in steps))
    chamfer = max(0.0, min(chamfer, thin_side / 2.0 - 1e-3))
    points = [(0.0, 0.0)]
    z = 0.0
    for i, (seg_len, seg_d) in enumerate(steps):
        r = seg_d / 2.0
        if i == 0:
            if chamfer > 0:
                points.append((max(0.0, r - chamfer), 0.0))
                points.append((r, chamfer))
            else:
                points.append((r, 0.0))
        else:
            points.append((r, z))
        z += seg_len
        if i == len(steps) - 1 and chamfer > 0:
            points.append((r, z - chamfer))
            points.append((max(0.0, r - chamfer), z))
        else:
            points.append((r, z))
    points.append((0.0, z))
    solid = _revolve_profile(points, segments, "вал")
    flange = float(a.num("flange", 0.0, minv=0.0) or 0.0)
    if flange > 0:
        flange_d = float(a.num("flange_d", diameter * 2.0, minv=diameter + 0.5))
        if flange_d >= max(s[1] for s in steps) - 0.01:
            pass  # буртик может быть больше ступени — это нормально
        pos = float(a.num("flange_at", max(0.0, length / 2.0 - flange / 2.0), minv=0.0))
        pos = min(max(0.0, pos), max(0.0, length - flange))
        fr = flange_d / 2.0
        fr_round = min(float(a.num("flange_round", 0.5, minv=0.0) or 0.0),
                       flange / 2.0 - 1e-3, (flange_d - diameter) / 3.0)
        prof = [(0.0, pos), (fr - max(fr_round, 0.0), pos), (fr, pos + fr_round),
                (fr, pos + flange - fr_round), (fr - max(fr_round, 0.0), pos + flange),
                (0.0, pos + flange)]
        collar = _revolve_profile(prof, segments, "буртик")
        solid = solid + collar
    if bore > 0:
        if bore >= min(s[1] for s in steps) - 0.4:
            raise GeometryError("Отверстие не оставляет стенки вала.")
        hole = mf.Manifold.cylinder(length + 2.0, bore / 2.0, bore / 2.0, segments)
        hole = hole.translate((0.0, 0.0, -1.0))
        solid = solid - hole
    solid = _axis_rotate(solid, a.text("axis", "z") or "z")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="shaft")


# --------------------------------------------------------------------------- #
#  Ручка мебельная
# --------------------------------------------------------------------------- #
@op("handle", aliases=("мебельная_ручка", "ручка_скоба"), category="Примитивы",
    summary="Мебельная ручка-скоба с независимыми формами перекладины и стоек: "
            "bar_shape/post_shape=цилиндр, капсула или брусок. Перекладина не "
            "выступает за наружные грани стоек. post_mode=сквозь продолжает "
            "одну или обе стойки над перекладиной; plates=нет убирает площадки.",
    example="ручка = handle length=160 height=34 diameter=10 bar_shape=капсула post_shape=капсула\n"
            "брусок = handle length=160 height=34 diameter=10 bar_shape=брусок post_shape=брусок plates=нет",
    params={"length": "длина по наружным граням стоек, мм (160)",
            "height": "высота оси перекладины над площадкой, мм (34)",
            "diameter": "толщина перекладины и стоек, мм (10)",
            "bar_shape": "перекладина: цилиндр, капсула или брусок",
            "post_shape": "стойки: цилиндр, капсула или брусок",
            "posts": "стоек: 1 по центру или 2 по краям (2)",
            "post_mode": "стык — заканчиваются в перекладине; сквозь — "
                         "непрерывные стойки видны над ней (стык)",
            "post_top": "видимый выход стойки над перекладиной при post_mode=сквозь, "
                        "мм (diameter)",
            "plates": "площадки-основания да/нет; нет полностью убирает их (да)",
            "plate_d": "диаметр площадки (2.4 × diameter)",
            "segments": "сегментов 8…96 (32)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def handle(a, name):
    def shape_of(key):
        raw = (a.text(key) or "цилиндр").strip().lower()
        got = {"цилиндр": "цилиндр", "труба": "цилиндр", "cylinder": "цилиндр",
               "капсула": "капсула", "capsule": "капсула",
               "брусок": "брусок", "параллелепипед": "брусок",
               "прямоугольный": "брусок", "box": "брусок"}.get(raw)
        if got is None:
            raise GeometryError(f"handle: {key}=цилиндр, капсула или брусок.")
        return got

    length = float(a.num("length", 160.0, minv=10.0, maxv=5000.0))
    height = float(a.num("height", 34.0, minv=2.0, maxv=2000.0))
    wire = float(a.num("diameter", 10.0, minv=1.0, maxv=500.0))
    bar_shape = shape_of("bar_shape")
    post_shape = shape_of("post_shape")
    posts = int(a.num("posts", 2, minv=1, maxv=2) or 2)
    post_mode = (a.text("post_mode", "стык") or "стык").strip().lower()
    if post_mode in ("сквозь", "сквозные", "непрерывные", "through", "continuous"):
        post_mode = "сквозь"
    elif post_mode in ("стык", "скрытые", "joint", "flush"):
        post_mode = "стык"
    else:
        raise GeometryError("handle: post_mode=стык или сквозь.")
    post_top = float(a.num("post_top", wire, minv=0.0, maxv=2000.0) or 0.0)
    if post_mode == "стык":
        post_top = 0.0
    plates = a.boolean("plates", True)
    segments = _seg(a, "segments", 32, 8, 96)
    r = wire / 2.0
    post_height = height + (r + post_top if post_mode == "сквозь" else 0.0)
    if length <= wire * 2.0:
        raise GeometryError("Длина ручки должна быть больше двух диаметров.")
    if height < wire * 1.2:
        raise GeometryError("height слишком мал для выбранной толщины стоек.")

    # Общий наружный габарит по X: от −length/2 до +length/2. Ни одна
    # форма перекладины не выходит за наружные плоскости боковых стоек.
    if bar_shape == "брусок":
        bar = mf.Manifold.cube((length, wire, wire), center=True).translate(
            (0.0, 0.0, height))
    elif bar_shape == "цилиндр":
        bar = mf.Manifold.cylinder(length, r, r, segments).rotate((0.0, 90.0, 0.0))
        bar = bar.translate((-length / 2.0, 0.0, height))
    else:
        middle = length - wire
        bar = mf.Manifold.cylinder(middle, r, r, segments).rotate((0.0, 90.0, 0.0))
        bar = bar.translate((-middle / 2.0, 0.0, height))
        caps = [mf.Manifold.sphere(r, max(8, segments // 2)).translate((x, 0.0, height))
                for x in (-middle / 2.0, middle / 2.0)]
        bar = mf.Manifold.batch_boolean([bar, *caps], mf.OpType.Add)
    parts = [bar]

    offsets = [0.0] if posts == 1 else [-(length / 2.0 - r), length / 2.0 - r]
    plate_r = float(a.num("plate_d", wire * 2.4, minv=wire * 1.2,
                           maxv=wire * 20.0)) / 2.0
    for dx in offsets:
        if post_shape == "брусок":
            post = mf.Manifold.cube((wire, wire, post_height), center=True).translate(
                (dx, 0.0, post_height / 2.0))
        elif post_shape == "цилиндр":
            post = mf.Manifold.cylinder(post_height, r, r, segments).translate((dx, 0.0, 0.0))
        else:
            # Нижний торец плоский на z=0, круглая только верхняя капсула.
            post = mf.Manifold.cylinder(post_height - r, r, r, segments).translate((dx, 0.0, 0.0))
            cap = mf.Manifold.sphere(r, max(8, segments // 2)).translate((dx, 0.0, post_height - r))
            post = post + cap
        parts.append(post)
        if plates:
            parts.append(mf.Manifold.cylinder(2.0, plate_r, plate_r, segments)
                         .translate((dx, 0.0, 0.0)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="handle")
    out.notes.append(f"ручка: перекладина {bar_shape}, стойки {post_shape}, "
                     f"post_mode={post_mode}, выход {post_top:g} мм, "
                     f"площадки={'да' if plates else 'нет'}")
    return out


# --------------------------------------------------------------------------- #
#  Колесо
# --------------------------------------------------------------------------- #
@op("wheel", aliases=("колесо", "колесо_с_ободом", "wheel_rim"), category="Примитивы",
    summary="Колесо целиком: шина, обод, спицы и ступица одним телом. "
            "Элементы: diameter — по наружной кромке шины, tire — толщина шины "
            "(отнимается от радиуса), rim — ширина обода внутрь, spokes — число "
            "спиц (при 1 вместо спиц сплошной диск), hub — диаметр ступицы. "
            "Ось по Y: катится вдоль X и готова для animate … roll. Кронштейн "
            "и ось в колесо не входят — их делают отдельно, чтобы они не крутились.",
    example="колесо = wheel diameter=600 width=140 rim=28 spokes=5 tire=42 hub=80\n"
            "диск = wheel diameter=120 width=24 rim=18 spokes=1",
    params={"diameter": "наружный диаметр по шине, мм (600)",
            "width": "ширина шины (140)",
            "rim": "ширина обода от шины внутрь, мм (28)",
            "spokes": "спиц (5); 1 — сплошной диск вместо спиц",
            "hub": "диаметр ступицы (80)", "tire": "толщина шины (7 % диаметра)",
            "segments": "сегментов (96)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def wheel(a, name):
    diameter = float(a.num("diameter", 600.0, minv=20.0))
    width = float(a.num("width", 140.0, minv=6.0))
    rim_w = float(a.num("rim", 28.0, minv=2.0))
    spokes = int(a.num("spokes", 5, minv=1, maxv=24) or 5)
    hub = float(a.num("hub", max(20.0, diameter * 0.13), minv=6.0))
    tire = float(a.num("tire", diameter * 0.07, minv=2.0))
    segments = _seg(a, "segments", 96, 24, 256)
    radius = diameter / 2.0
    if tire * 2 >= radius or rim_w >= radius or hub >= radius - tire:
        raise GeometryError("Шина, обод или ступица не помещаются в колесо.",
                            hint="Уменьшите tire, rim или hub либо увеличьте diameter.")
    inner = radius - tire
    half = width / 2.0
    shoulder = min(tire * 0.6, half * 0.5)
    tire_profile = [(inner, -half), (radius - shoulder, -half),
                    (radius, -half + shoulder), (radius, half - shoulder),
                    (radius - shoulder, half), (inner, half)]
    # Всё строим осью по Z, спицы — в той же плоскости, и только потом
    # поворачиваем готовое колесо: иначе спицы остаются поперёк шины.
    tire_solid = _revolve_profile(tire_profile, segments, "шина")
    rim_outer = inner + 1.0
    rim_inner = max(hub / 2.0 + 4.0, rim_outer - rim_w)
    rim_ring = (mf.Manifold.cylinder(width * 0.62, rim_outer, rim_outer, segments)
                - mf.Manifold.cylinder(width * 0.62 + 0.4, rim_inner, rim_inner, segments))
    rim_ring = rim_ring.translate((0.0, 0.0, -width * 0.31))
    hub_solid = mf.Manifold.cylinder(width * 0.9, hub / 2.0, hub / 2.0, segments)
    hub_solid = hub_solid.translate((0.0, 0.0, -width * 0.45))
    parts = [tire_solid, rim_ring, hub_solid]
    if spokes > 0:
        spoke_len = rim_inner - hub / 2.0 + 6.0
        if spoke_len <= 1.0:
            raise GeometryError("Между ступицей и ободом нет места спицам.")
        spoke = mf.Manifold.cube([spoke_len, width * 0.18, width * 0.22], True)
        spoke = spoke.translate((hub / 2.0 - 3.0 + spoke_len / 2.0, 0.0, 0.0))
        parts.append(mf.Manifold.batch_boolean(
            [spoke.rotate([0.0, 0.0, 360.0 * i / spokes]) for i in range(spokes)],
            mf.OpType.Add))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    # ось колеса — Y: катится вдоль X
    solid = solid.rotate([-90.0, 0.0, 0.0])
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="wheel")
    out.notes.append(f"ø{diameter:g} мм, ширина {width:g} мм, спиц {spokes}")
    return out


# --------------------------------------------------------------------------- #
#  Рейка, муфта, радиатор
# --------------------------------------------------------------------------- #
@op("rock", aliases=("камень", "валун", "булыжник"), category="Примитивы",
    summary="Камень выпуклой оболочкой: всегда замкнутый. Форма задаётся "
            "размером, шероховатостью и seed — повторяемая.",
    example="камень = rock size=[120,90,55] seed=3",
    params={"size": "габарит [x,y,z], мм (100,80,50)", "seed": "зерно формы (1)",
            "rough": "шероховатость 0..1 (0.35)", "points": "точек оболочки (48)",
            "flat": "плоское дно да/нет (да)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def rock(a, name):
    sx, sy, sz = _triple(a, "size", (100.0, 80.0, 50.0))
    seed = int(a.num("seed", 1, minv=0) or 0)
    rough = float(a.num("rough", 0.35, minv=0.0, maxv=1.0))
    count = int(a.num("points", 48, minv=8, maxv=200) or 48)
    rng = np.random.default_rng(seed)
    rays = []
    while len(rays) < count:
        v = rng.normal(size=3)
        norm = float(np.linalg.norm(v))
        if norm < 1e-6:
            continue
        v = v / norm
        k = 1.0 - rough * (0.15 + 0.35 * float(rng.random()))
        rays.append((sx / 2.0 * v[0] * k, sy / 2.0 * v[1] * k, sz / 2.0 * v[2] * k))
    for dx in (-0.3, 0.3):
        rays.append((sx * dx, 0.0, -sz / 2.0))
        rays.append((0.0, sy * dx, -sz / 2.0))
    hull = mf.Manifold.hull_points(np.ascontiguousarray(rays, dtype=np.float64))
    if a.boolean("flat", True):
        bb = hull.bounding_box()
        cutter = mf.Manifold.cube([sx * 4.0, sy * 4.0, sz * 2.0], True)
        cutter = cutter.translate((0.0, 0.0, bb[2] - sz))
        hull = hull - cutter
    if hull.is_empty() or hull.volume() <= 1e-6:
        raise GeometryError("Камень получился пустым — увеличьте размеры.")
    return make_solid(a.scene, name, _placed(a, hull), a, kind="rock")


def _leaf_outline(kind: str, length: float, width: float, count: int,
                  seed: int = 1, jitter: float = 0.0):
    """Контуры видов листа; ось длины X, черенок слева, кончик справа."""
    if kind in ("овал", "заострённый", "дуб"):
        upper = []
        samples = max(count, 72) if kind == "дуб" else count
        for i in range(1, samples):
            t = 0.5 - 0.5 * math.cos(math.pi * i / samples)
            x = -length / 2.0 + length * t
            base = math.sin(math.pi * t)
            if kind == "дуб":
                w = width / 2.0 * base ** 0.56 * (0.72 + 0.28 * math.cos(8.0 * math.pi * t))
            elif kind == "заострённый":
                w = width / 2.0 * base ** 1.28 * (1.16 - 0.32 * t)
            else:
                w = width / 2.0 * base ** 0.62
            upper.append((x, w))
        points = [(-length / 2.0, 0.0)] + upper + [(length / 2.0, 0.0)]
        points += [(x, -w) for x, w in reversed(upper)]
        if kind == "овал":
            return _dedupe(points, 1e-5)
    elif kind == "липа":
        def bezier(p0, p1, p2, p3, n):
            out = []
            for i in range(n):
                t = i / n
                u = 1.0 - t
                out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0]
                            + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                            u ** 3 * p0[1] + 3 * u * u * t * p1[1]
                            + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
            return out
        n = max(8, count // 2)
        notch = (-0.34 * length, 0.0)
        middle = (-0.08 * length, 0.42 * width)
        tip = (0.50 * length, 0.0)
        upper = bezier(notch, (-0.58 * length, 0.08 * width),
                       (-0.36 * length, 0.58 * width), middle, n)
        upper += bezier(middle, (0.10 * length, 0.38 * width),
                        (0.30 * length, 0.16 * width), tip, n)
        upper.append(tip)
        points = upper + [(x, -y) for x, y in reversed(upper[1:-1])]
    else:  # клен: пальчатые лопасти и настоящий черенок, не радиальная звезда
        # Канонический силуэт нарисован вертикально: центральная лопасть
        # вверх, две боковые и две базальные по сторонам, черенок вниз.
        # Мелкие зубцы не равны главным лопастям — так читается именно клён.
        right = [
            (0.00, 0.58),                  # длинная центральная лопасть
            (0.055, 0.40), (0.125, 0.45), (0.105, 0.32),
            (0.055, 0.17),                 # глубокая пазуха, а не луч звезды
            (0.19, 0.25), (0.25, 0.38), (0.29, 0.31),
            (0.38, 0.34),                  # широкая боковая лопасть
            (0.29, 0.18), (0.42, 0.17),
            (0.31, 0.06), (0.44, 0.02),    # базальная лопасть
            (0.24, -0.035), (0.27, -0.15),
            (0.12, -0.10),                 # вторая глубокая пазуха
            (0.10, -0.22), (0.055, -0.22), (0.055, -0.31),
            (0.026, -0.31), (0.026, -0.62),  # тонкий черенок
        ]
        canonical = right + [(-0.026, -0.62)] + [
            (-x, y) for x, y in reversed(right[1:-1])]
        # Поворот: остриё +X, черенок −X, как и у остальных видов leaf.
        rotated = [(y, -x) for x, y in canonical]
        points = []
        rng = np.random.default_rng(seed)
        area2 = sum(rotated[i][0] * rotated[(i + 1) % len(rotated)][1]
                    - rotated[(i + 1) % len(rotated)][0] * rotated[i][1]
                    for i in range(len(rotated)))
        orient = 1.0 if area2 > 0.0 else -1.0
        sub = max(6, int(math.ceil(count / len(rotated))))
        for i, p0 in enumerate(rotated):
            p1 = rotated[(i + 1) % len(rotated)]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            seg_len = math.hypot(dx, dy)
            outward = np.asarray([orient * dy, -orient * dx]) / max(seg_len, 1e-12)
            stem = (p0[0] + p1[0]) * 0.5 < -0.30
            teeth = 2 if seg_len > 0.075 else 1
            amplitude = min(0.007 + jitter * 0.024, seg_len * 0.17)
            random_gain = 1.0 + float(rng.uniform(-0.8, 0.8)) * jitter
            for j in range(sub):
                t = j / sub
                phase = (t * teeth) % 1.0
                tooth = 1.0 - abs(2.0 * phase - 1.0)
                shift = 0.0 if stem else amplitude * random_gain * tooth
                points.append((p0[0] * (1 - t) + p1[0] * t + outward[0] * shift,
                               p0[1] * (1 - t) + p1[1] * t + outward[1] * shift))
    # Новые виды нормируются по фактическому контуру: length/width точные.
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    sx = length / max(max(xs) - min(xs), 1e-9)
    sy = width / max(max(ys) - min(ys), 1e-9)
    return _dedupe([((x - cx) * sx, (y - cy) * sy) for x, y in points], 1e-5)


@op("leaf", aliases=("листок", "лист_растения", "лист_дерева", "leaf_plant"),
    category="Примитивы",
    summary="Лист растения с толщиной и изгибом. kind/shape: овал, "
            "липа/сердцевидный, дуб, клен или заострённый — контуры действительно "
            "различаются выемками и лопастями. У клёна мелкие зубцы повторяются "
            "по seed, jitter меняет их разброс, edge сужает наружную кромку.",
    example="лист = leaf length=90 width=45 thickness=2 curl=0.25\n"
            "клен = leaf length=90 width=70 kind=клен\n"
            "липа = leaf length=80 width=65 kind=липа",
    params={"length": "длина, мм (90)", "width": "ширина, мм (45)",
            "kind": "овал, липа/сердцевидный, дуб, клен, заострённый",
            "shape": "синоним kind; если задан, перекрывает kind",
            "thickness": "основная толщина, мм (2)", "curl": "изгиб 0..1 (0.25)",
            "edge": "толщина наружной кромки, мм (= thickness); меньше — сужение",
            "edge_band": "ширина перехода от кромки к полной толщине, мм (8% размера)",
            "seed": "зерно случайной кромки клёна (1)",
            "jitter": "случайная амплитуда мелких зубцов клёна 0..1 (0.18)",
            "segments": "детализация контура (48); у клёна добавляются мелкие зубцы",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом "
                     "вверх — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def leaf(a, name):
    length = float(a.num("length", 90.0, minv=5.0))
    width = float(a.num("width", 45.0, minv=3.0))
    thickness = float(a.num("thickness", 2.0, minv=0.3))
    curl = float(a.num("curl", 0.25, minv=0.0, maxv=1.0) or 0.0)
    count = int(a.num("segments", 48, minv=12, maxv=120) or 48)
    raw_kind = (a.text("shape") or a.text("kind") or "овал").strip().lower()
    kind = {
        "овал": "овал", "овальный": "овал", "oval": "овал",
        "липа": "липа", "сердцевидный": "липа", "сердце": "липа",
        "linden": "липа", "heart": "липа",
        "дуб": "дуб", "дубовый": "дуб", "oak": "дуб",
        "клен": "клен", "клён": "клен", "кленовый": "клен", "клёновый": "клен",
        "maple": "клен", "заострённый": "заострённый",
        "заостренный": "заострённый", "острый": "заострённый",
        "pointed": "заострённый", "lance": "заострённый",
    }.get(raw_kind)
    if kind is None:
        raise GeometryError("leaf: kind=овал, липа, дуб, клен или заострённый.")
    seed = int(a.num("seed", 1, minv=0) or 0)
    jitter = float(a.num("jitter", 0.18 if kind == "клен" else 0.0,
                         minv=0.0, maxv=1.0) or 0.0)
    edge = float(a.num("edge", thickness, minv=0.05, maxv=thickness))
    edge_band = float(a.num("edge_band", min(length, width) * 0.08, minv=0.05))
    points = _leaf_outline(kind, length, width, count, seed=seed, jitter=jitter)
    body = mf.Manifold.extrude(mf.CrossSection([_profile(points)]), float(thickness))
    if edge < thickness - 1e-9:
        contour = np.asarray(points, dtype=np.float64)

        def rim(points_xyz):
            # Точное расстояние до исходного контура в плоскости листа.
            xy = points_xyz[:, :2]
            result = np.full(len(xy), float(edge_band), dtype=np.float64)
            for i in range(len(contour)):
                p0 = contour[i]
                p1 = contour[(i + 1) % len(contour)]
                d = p1 - p0
                denom = float(np.dot(d, d))
                if denom < 1e-16:
                    continue
                t = np.clip(((xy - p0) @ d) / denom, 0.0, 1.0)
                nearest = p0 + t[:, None] * d
                result = np.minimum(result, np.linalg.norm(xy - nearest, axis=1))
            return np.clip(1.0 - result / edge_band, 0.0, 1.0)

        body = varied_edge_thickness(body, thickness, edge, edge_band, rim, "лист",
                                     center_z=thickness / 2.0)
    if curl > 0:
        verts, faces = manifold_mesh(body)
        out = verts.copy()
        out[:, 2] += curl * (out[:, 0] / max(length, 1e-6) + 0.5) ** 2 * (width * 0.5)
        body = manifold_from_arrays(out, faces, "лист")
    return make_solid(a.scene, name, _placed(a, stand_flat_sign(a, body)), a,
                      kind="leaf")


# --------------------------------------------------------------------------- #
#  Разброс деталей
# --------------------------------------------------------------------------- #
@op("scatter", aliases=("разброс", "рассыпать", "scatter_copy"),
    category="Массивы и преобразования",
    summary="Детерминированный разброс копий по площади: камни, трава, листва. "
            "seed повторяет узор, k — разброс масштаба.",
    example='камень = rock size=[80,60,40]\nкамни = scatter [камень] count=24 area=[400,300] seed=5',
    params={"objects": "объект, который разбрасываем",
            "count": "сколько копий (20)", "area": "площадь [x,y], мм (300,300)",
            "seed": "зерно (1)", "scale": "масштаб [min,max] (0.8,1.2)",
            "turn": "случайный поворот до, градусы (360)",
            "z": "высота пола (0)", "avoid": "не ставить в круг радиусом, мм (0)",
            "at": "сдвиг центра [x,y,z]", "center": "не используется"},
    positional=["objects"])
def scatter(a, name):
    base = _one(a, "scatter")
    count = int(a.num("count", 20, minv=1, maxv=400) or 20)
    ax, ay = _pair(a, "area", (300.0, 300.0))
    seed = int(a.num("seed", 1, minv=0) or 0)
    smin, smax = _pair(a, "scale", (0.8, 1.2))
    smin, smax = max(0.05, min(smin, smax)), max(0.05, max(smin, smax))
    turn = float(a.num("turn", 360.0, minv=0.0, maxv=360.0) or 0.0)
    z = float(a.num("z", 0.0) or 0.0)
    avoid = float(a.num("avoid", 0.0, minv=0.0) or 0.0)
    rng = np.random.default_rng(seed)
    copies = []
    tries = 0
    while len(copies) < count and tries < count * 20:
        tries += 1
        x = float(rng.uniform(-ax / 2.0, ax / 2.0))
        y = float(rng.uniform(-ay / 2.0, ay / 2.0))
        if avoid > 0 and math.hypot(x, y) < avoid:
            continue
        k = float(rng.uniform(smin, smax))
        angle = float(rng.uniform(0.0, turn)) if turn > 0 else 0.0
        piece = base.manifold.scale((k, k, k)).rotate([0.0, 0.0, angle])
        pb = piece.bounding_box()
        piece = piece.translate((x - (pb[0] + pb[3]) / 2.0,
                                 y - (pb[1] + pb[4]) / 2.0,
                                 z - pb[2]))
        copies.append(piece)
    if not copies:
        raise GeometryError("Не удалось разложить копии — уменьшите avoid.")
    solid = copies[0] if len(copies) == 1 else mf.Manifold.batch_boolean(copies, mf.OpType.Add)
    out = make_solid(a.scene, name, _shifted(a, solid), a, base=base, kind="scatter")
    a.scene.consume(base)
    out.notes.append(f"разброс: {len(copies)} копий")
    return out


__all__ = ["box_body", "pipe", "holes", "shaft", "handle", "wheel",
           "rock", "leaf", "branch", "scatter"]
