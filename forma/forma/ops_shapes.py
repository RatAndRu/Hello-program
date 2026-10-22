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
#  Тарелка
# --------------------------------------------------------------------------- #
@op("plate", aliases=("тарелка", "блюдо", "dish"), category="Примитивы",
    summary="Тарелка: плоское дно, плавная стенка и борт. Форма задаётся "
            "глубиной, долей дна, шириной борта, радиусом перехода и толщиной "
            "стенки — от блюдца до глубокой пиалы.",
    example="тарелка = plate diameter=220 depth=26 wall=4 rim=6\n"
            "блюдце = plate diameter=140 depth=12 wall=3 well=0.78 rim=4",
    params={"diameter": "диаметр, мм (220)", "depth": "высота борта, мм (26)",
            "wall": "толщина стенки и дна, мм (4)",
            "well": "доля плоского дна 0.2..0.9 (0.62)",
            "rim": "ширина отогнутого борта, мм (4)",
            "round": "радиус перехода от дна к стенке, мм (0.35·глубины)",
            "foot": "диаметр кольцевой ножки снизу (0 — нет)",
            "segments": "сегментов по кругу",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def plate(a, name):
    diameter = float(a.num("diameter", 220.0, minv=5.0))
    depth = float(a.num("depth", 26.0, minv=1.0))
    wall = float(a.num("wall", 4.0, minv=0.3))
    well = float(a.num("well", 0.62, minv=0.2, maxv=0.9) or 0.62)
    rim_w = float(a.num("rim", max(0.8, wall * 1.2), minv=0.4))
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
    rim_r = min(rim_w, depth * 0.4, (r - rw) * 0.3, wall * 1.6)
    z_top = depth - rim_r
    # внешний профиль: дно → скругление → стенка с развалом → закатанный борт
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
    n_rim = 4
    for i in range(1, n_rim + 1):
        ang = (math.pi / 2.0) * i / n_rim
        prof.append((r - rim_r + rim_r * math.cos(ang), z_top + rim_r * math.sin(ang)))
    prof += [(r - rim_r, depth), (0.0, depth)]
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
    summary="Яйцо (овоид): тело вращения с плавной асимметрией — один конец "
            "шире и тупее, другой уже и острее. proportion задаёт «яйцевидность»: "
            "0 — сфера, 0.5 — куриное яйцо, 1 — острый овал.",
    example="яйцо = egg height=60 diameter=42 proportion=0.5\n"
            "капля = egg height=80 diameter=40 proportion=0.9",
    params={"height": "высота, мм (60)", "diameter": "наибольший диаметр, мм (42)",
            "proportion": "яйцевидность 0..1 (0.5)",
            "sharp": "какой конец острый: верх или низ (верх)",
            "segments": "сегментов по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def egg(a, name):
    height = float(a.num("height", 60.0, minv=1.0))
    diameter = float(a.num("diameter", 42.0, minv=1.0))
    prop = float(a.num("proportion", 0.5, minv=0.0, maxv=1.0) or 0.0)
    sharp = (a.text("sharp") or "верх").strip().lower()
    if sharp in ("bottom", "низ", "вниз", "снизу"):
        sharp = "низ"
    r_max = diameter / 2.0
    if r_max >= height / 2.0 + r_max * 0.2:
        pass
    segments = _segments(a.int("segments", None, minv=16, maxv=256), r_max)
    steps = max(24, int(segments * 0.6))
    prof = [(0.0, 0.0)]
    for i in range(1, steps):
        t = i / steps                     # от низа к верху
        # x = sin(pi*t) даёт ширину, деформированную к одному концу
        width = math.sin(math.pi * t) ** (1.0 + prop * 0.9)
        if sharp == "верх":
            width *= (1.0 - 0.35 * prop * t)      # верх уже
        else:
            width *= (1.0 - 0.35 * prop * (1.0 - t))
        prof.append((max(0.0, r_max * width), height * t))
    prof.append((0.0, height))
    solid = _revolve(prof, segments, "яйца")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="egg")


# --------------------------------------------------------------------------- #
#  Арка (полукольцо)
# --------------------------------------------------------------------------- #
@op("arch", aliases=("арка", "полукольцо", "дуга", "archway"), category="Примитивы",
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
    summary="Полусфера: выпуклая (купол) или вогнутая миска со стенкой. "
            "Купол — половина шара со ровным сечением; миска — та же половина, "
            "выдолбленная с заданной толщиной стенки и кромкой.",
    example="купол = hemisphere radius=60\n"
            "миска = hemisphere radius=70 mode=миска wall=4",
    params={"radius": "радиус, мм (50)",
            "mode": "купол (выпуклая) или миска (вогнутая); dome/bowl тоже",
            "wall": "толщина стенки миски, мм (4)",
            "rim": "ширина кромки бортика, мм (0 — без отворота)",
            "segments": "сегментов по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def hemisphere(a, name):
    radius = float(a.num("radius", 50.0, minv=1.0))
    mode = (a.text("mode") or "купол").strip().lower()
    if mode in ("dome", "купол", "выпуклая", "верх"):
        mode = "купол"
    elif mode in ("bowl", "миска", "чаша", "вогнутая"):
        mode = "миска"
    else:
        raise GeometryError("Полусфера: mode=купол или mode=миска.")
    wall = float(a.num("wall", 4.0, minv=0.2))
    rim_w = float(a.num("rim", 0.0, minv=0.0) or 0.0)
    segments = _segments(a.int("segments", None, minv=16, maxv=256), radius)
    steps = max(16, int(segments * 0.6))
    if mode == "купол":
        prof = [(0.0, 0.0)]
        for i in range(1, steps + 1):
            ang = math.pi / 2.0 * i / steps
            prof.append((radius * math.sin(ang), radius * math.cos(ang)))
        prof.append((radius, 0.0))
        # закрываем плоское дно
        prof = [(0.0, 0.0)] + [(p[0], p[1]) for p in prof[1:]]
        solid = _revolve(prof, segments, "купол")
        # купол стоит плоско: дно — плоскость z=0, вершина вверху
        return make_solid(a.scene, name, _placed(a, solid), a, kind="hemisphere")
    # миска: внешняя полусфера + кромка, внутренняя — со стенкой
    if wall >= radius * 0.8:
        raise GeometryError("Стенка миски слишком толстая для этого радиуса.")
    outer = [(0.0, 0.0)]
    for i in range(1, steps + 1):
        ang = math.pi / 2.0 * i / steps
        outer.append((radius * math.sin(ang), radius * math.cos(ang)))
    outer.append((0.0, radius))
    solid = _revolve(outer, segments, "миска")
    inner_r = radius - wall
    inner = [(0.0, wall)]
    for i in range(1, steps + 1):
        ang = math.pi / 2.0 * i / steps
        inner.append((inner_r * math.sin(ang), wall + inner_r * math.cos(ang)))
    cavity = _revolve(inner, segments, "полость миски")
    solid = solid - cavity
    if rim_w > 0:
        rim_w = min(rim_w, radius * 0.25)
        band = (mf.Manifold.cylinder(float(wall * 1.4), float(radius + rim_w),
                                     float(radius + rim_w), int(segments))
                - mf.Manifold.cylinder(float(wall * 1.4 + 1.0), float(radius - wall * 0.5),
                                       float(radius - wall * 0.5), int(segments))
                .translate((0.0, 0.0, -0.5)))
        solid = solid + band.translate((0, 0, wall * 0.15))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="hemisphere")
    out.notes.append(f"миска R{radius:g}, стенка {wall:g} мм")
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
