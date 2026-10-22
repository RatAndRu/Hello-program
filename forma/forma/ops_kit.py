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
from .ops import anchor, make_solid, op


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


def _tube_mesh(pts: np.ndarray, radius, sides: int, what: str) -> mf.Manifold:
    """Труба переменного радиуса по пути: кольца по касательным, митры, торцы."""
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
        prev_n = nvec
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
#  Труба по ломаной
# --------------------------------------------------------------------------- #
@op("pipe", aliases=("трубка", "трубопровод", "tube"),
    category="Тела вращения и развёртки",
    summary="Труба с настоящей стенкой по ломаной: митры на поворотах и "
            "заглушки-кольца на концах. Одно замкнутое тело.",
    example="труба = pipe path=[[0,0,0],[0,0,400],[300,0,400]] diameter=32 wall=2",
    params={"path": "точки пути [[x,y,z], …], мм (обязательно)",
            "diameter": "наружный диаметр (32)", "wall": "толщина стенки (2)",
            "sides": "сегментов по кругу (24)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def pipe(a, name):
    path = a.points("path", 3)
    if len(path) < 2:
        raise GeometryError("Для трубы нужны хотя бы две точки пути.",
                            hint="Например: труба = pipe path=[[0,0,0],[0,0,400]] diameter=32")
    diameter = float(a.num("diameter", 32.0, minv=1.0))
    wall = float(a.num("wall", 2.0, minv=0.2))
    if wall * 2 >= diameter - 0.4:
        raise GeometryError("Стенка не оставляет просвета в трубе.")
    sides = _seg(a, "sides", 24, 8, 96)
    pts = np.asarray(path, dtype=np.float64)
    outer = _tube_mesh(pts, diameter / 2.0, sides, "труба")
    inner = _tube_mesh(pts, diameter / 2.0 - wall, sides, "труба")
    solid = outer - inner
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Труба получилась пустой.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="pipe")
    out.notes.append(f"ø{diameter:g}×{wall:g} мм, длина {_path_length(pts):.0f} мм")
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
    example='панель = box size=[120,90,10]\nпанель = holes [панель] grid=[3,2] diameter=6 pitch=[40,30]',
    params={"objects": "объект, в котором сверлим",
            "diameter": "диаметр отверстия, мм (6)",
            "grid": "сколько отверстий по двум осям [nx,ny] (2,2)",
            "pitch": "шаг между отверстиями [px,py], мм (3·диаметр)",
            "positions": "свои точки [[x,y], …] вместо сетки",
            "axis": "ось сверления: x, y или z (z)",
            "through": "сквозные да/нет (да)", "depth": "глубина, если не сквозное",
            "countersink": "зенковка: ширина фаски, мм (0)",
            "perforate": "шахматный порядок да/нет (нет)",
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
                positions.append((center[0] + dx,
                                  center[1] + (j - (ny - 1) / 2.0) * py,
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
            "осевое отверстие. Одно тело вращения.",
    example="вал = shaft diameter=20 length=120 bore=6",
    params={"diameter": "диаметр, мм (20)", "length": "длина, мм (100)",
            "steps": "ступени [[длина, диаметр], …] вместо одного диаметра",
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
@op("handle", aliases=("мебельная_ручка", "скоба"), category="Примитивы",
    summary="Мебельная ручка-скоба: перекладина, стойки и площадки крепления. "
            "Одно тело, готова к сборке.",
    example="ручка = handle length=160 height=34 diameter=10",
    params={"length": "длина по центрам, мм (160)", "height": "вынос, мм (34)",
            "diameter": "толщина стержня, мм (10)",
            "posts": "стоек: 1 по центру или 2 по краям (2)",
            "plates": "площадки крепления да/нет (да)",
            "segments": "сегментов (32)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def handle(a, name):
    length = float(a.num("length", 160.0, minv=10.0))
    height = float(a.num("height", 34.0, minv=2.0))
    wire = float(a.num("diameter", 10.0, minv=1.0))
    posts = int(a.num("posts", 2, minv=1, maxv=2) or 2)
    segments = _seg(a, "segments", 32, 8, 96)
    r = wire / 2.0
    if length <= wire * 2:
        raise GeometryError("Длина ручки меньше её толщины.")
    bar_len = length - wire
    parts = [mf.Manifold.cylinder(bar_len, r, r, segments)
             .rotate([0.0, 90.0, 0.0]).translate((-bar_len / 2.0, 0.0, height)),
             mf.Manifold.sphere(r, max(8, segments // 2)).translate((-bar_len / 2.0, 0.0, height)),
             mf.Manifold.sphere(r, max(8, segments // 2)).translate((bar_len / 2.0, 0.0, height))]
    offsets = [0.0] if posts == 1 else [-(length / 2.0 - r), length / 2.0 - r]
    for dx in offsets:
        parts.append(mf.Manifold.cylinder(height + r, r, r, segments)
                     .translate((dx, 0.0, 0.0)))
        if a.boolean("plates", True):
            parts.append(mf.Manifold.cylinder(2.0, r * 2.4, r * 2.4, segments)
                         .translate((dx, 0.0, 0.0)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="handle")


# --------------------------------------------------------------------------- #
#  Колесо
# --------------------------------------------------------------------------- #
@op("wheel", aliases=("колесо", "колесо_с_ободом", "wheel_rim"), category="Примитивы",
    summary="Колесо: шина, обод, спицы и ступица. Ось по Y — катится вдоль X, "
            "готово для animate … roll.",
    example="колесо = wheel diameter=600 width=140 rim=28 spokes=5",
    params={"diameter": "наружный диаметр, мм (600)", "width": "ширина шины (140)",
            "rim": "ширина обода, мм (28)", "spokes": "спиц (5)",
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
@op("rack", aliases=("рейка", "зубчатая_рейка", "gear_rack"), category="Примитивы",
    summary="Зубчатая рейка того же модуля, что gear: длина, зубья, модуль, "
            "толщина и высота тела.",
    example="рейка = rack length=200 teeth=20 module=2",
    params={"length": "длина, мм (200)", "teeth": "число зубьев (20)",
            "module": "модуль, мм (2)", "thickness": "толщина, мм (8)",
            "height": "высота тела, мм (10)", "tooth": "высота зуба (2.25·m)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def rack(a, name):
    length = float(a.num("length", 200.0, minv=10.0))
    teeth = int(a.num("teeth", 20, minv=2, maxv=400) or 20)
    module = float(a.num("module", 2.0, minv=0.2))
    thickness = float(a.num("thickness", 8.0, minv=1.0))
    height = float(a.num("height", 10.0, minv=1.0))
    tooth_h = float(a.num("tooth", module * 2.25, minv=0.3))
    pitch = length / teeth
    base = mf.Manifold.cube([length, thickness, height], True)
    base = base.translate((0.0, 0.0, height / 2.0))
    profile = [(-pitch * 0.38, 0.0), (pitch * 0.38, 0.0),
               (pitch * 0.22, tooth_h), (-pitch * 0.22, tooth_h)]
    tooth = mf.Manifold.extrude(mf.CrossSection([profile]), thickness)
    tooth = tooth.rotate([90.0, 0.0, 0.0]).translate((0.0, 0.0, height - 0.2))
    parts = [base]
    for i in range(teeth):
        parts.append(tooth.translate((-length / 2.0 + pitch * (i + 0.5), 0.0, 0.0)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="rack")


@op("coupling", aliases=("муфта", "соединительная_муфта"), category="Примитивы",
    summary="Муфта для двух валов: корпус, буртик и сквозное посадочное отверстие.",
    example="муфта = coupling diameter=40 length=60 bore=12",
    params={"diameter": "диаметр, мм (40)", "length": "длина, мм (60)",
            "bore": "отверстие под вал, мм (12)", "flange": "ширина буртика (6)",
            "segments": "сегментов (48)", "axis": "ось: x, y или z (z)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def coupling(a, name):
    diameter = float(a.num("diameter", 40.0, minv=6.0))
    length = float(a.num("length", 60.0, minv=6.0))
    bore = float(a.num("bore", 12.0, minv=0.5))
    flange = float(a.num("flange", 6.0, minv=1.0))
    segments = _seg(a, "segments", 48, 16, 128)
    if bore >= diameter - 6.0:
        raise GeometryError("Отверстие не оставляет стенки муфты.")
    r = diameter / 2.0
    body = mf.Manifold.cylinder(length, r, r, segments)
    hole = mf.Manifold.cylinder(length + 2.0, bore / 2.0, bore / 2.0, segments)
    hole = hole.translate((0.0, 0.0, -1.0))
    solid = body - hole
    band = mf.Manifold.cylinder(flange, r * 1.12, r * 1.12, segments)
    band = band.translate((0.0, 0.0, (length - flange) / 2.0))
    solid = solid + (band - hole)
    solid = _axis_rotate(solid, a.text("axis", "z") or "z")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="coupling")


@op("heatsink", aliases=("радиатор", "охладитель"), category="Примитивы",
    summary="Радиатор: основание и рёбра с заданным шагом. Одно тело.",
    example="радиатор = heatsink size=[80,60,30] fins=9",
    params={"size": "размер [x,y,z], мм (80,60,30)",
            "fins": "число рёбер (8)", "base": "толщина основания (5)",
            "fin": "толщина ребра (2)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def heatsink(a, name):
    sx, sy, sz = _triple(a, "size", (80.0, 60.0, 30.0))
    fins = int(a.num("fins", 8, minv=1, maxv=80) or 8)
    base_h = float(a.num("base", 5.0, minv=1.0))
    fin_t = float(a.num("fin", 2.0, minv=0.4))
    if base_h >= sz - 1.0:
        raise GeometryError("Основание выше радиатора.")
    base = mf.Manifold.cube([sx, sy, base_h], True).translate((0.0, 0.0, base_h / 2.0))
    fin_h = sz - base_h
    fin = mf.Manifold.cube([fin_t, sy, fin_h], True)
    fin = fin.translate((0.0, 0.0, base_h + fin_h / 2.0))
    step = sx / max(1, fins)
    parts = [base]
    for i in range(fins):
        parts.append(fin.translate((-sx / 2.0 + step * (i + 0.5), 0.0, 0.0)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    return make_solid(a.scene, name, _placed(a, solid), a, kind="heatsink")


# --------------------------------------------------------------------------- #
#  Природа: камень, лист, ветка
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


@op("leaf", aliases=("лист", "листок"), category="Примитивы",
    summary="Лист: контур с прожилкой, толщиной и изгибом. Годится для растений "
            "и декора.",
    example="лист = leaf length=90 width=45 thickness=2 curl=0.25",
    params={"length": "длина, мм (90)", "width": "ширина, мм (45)",
            "thickness": "толщина, мм (2)", "curl": "изгиб 0..1 (0.25)",
            "segments": "точек контура (48)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def leaf(a, name):
    length = float(a.num("length", 90.0, minv=5.0))
    width = float(a.num("width", 45.0, minv=3.0))
    thickness = float(a.num("thickness", 2.0, minv=0.3))
    curl = float(a.num("curl", 0.25, minv=0.0, maxv=1.0) or 0.0)
    count = int(a.num("segments", 48, minv=12, maxv=120) or 48)
    upper = []
    for i in range(count + 1):
        t = i / count
        x = -length / 2.0 + length * t
        w = max(0.6, width / 2.0 * math.sin(math.pi * t) ** 0.72)
        if i == 0 or i == count:
            w = 0.6
        upper.append((x, w))
    points = upper + [(x, -w) for x, w in reversed(upper[1:-1])]
    points = _dedupe(points, 1e-4)
    body = mf.Manifold.extrude(mf.CrossSection([_profile(points)]), float(thickness))
    if curl > 0:
        verts, faces = manifold_mesh(body)
        out = verts.copy()
        out[:, 2] += curl * (out[:, 0] / max(length, 1e-6) + 0.5) ** 2 * (width * 0.5)
        body = manifold_from_arrays(out, faces, "лист")
    return make_solid(a.scene, name, _placed(a, body), a, kind="leaf")


@op("branch", aliases=("ветка", "сучок"), category="Примитивы",
    summary="Ветка: сужающаяся труба по изогнутому пути. Одно тело.",
    example="ветка = branch length=240 diameter=26 taper=0.45 bend=[60, 20]",
    params={"length": "длина, мм (240)", "diameter": "толщина у корня (26)",
            "taper": "сужение к концу 0..0.9 (0.45)",
            "bend": "изгиб [вбок, вперёд], мм (30, 0)",
            "sides": "сегментов (16)", "steps": "точек пути (12)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def branch(a, name):
    length = float(a.num("length", 240.0, minv=10.0))
    diameter = float(a.num("diameter", 26.0, minv=1.0))
    taper = float(a.num("taper", 0.45, minv=0.0, maxv=0.9) or 0.0)
    bx, by = _pair(a, "bend", (30.0, 0.0))
    sides = _seg(a, "sides", 16, 6, 64)
    steps = int(a.num("steps", 12, minv=3, maxv=64) or 12)
    pts = np.asarray([(bx * (i / steps) ** 2, by * (i / steps) ** 2, length * i / steps)
                      for i in range(steps + 1)], dtype=np.float64)
    radii = [diameter / 2.0 * (1.0 - taper * (i / steps)) for i in range(steps + 1)]
    solid = _tube_mesh(pts, radii, sides, "ветка")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="branch")


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


__all__ = ["box_body", "pipe", "holes", "shaft", "handle", "wheel", "rack",
           "coupling", "heatsink", "rock", "leaf", "branch", "scatter"]
