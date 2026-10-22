"""Готовые детали второго эшелона: панель, косынка, ножка, направляющая,
профиль 2020, люверс, червяк, рог, накатка и выдвижной ящик.

Правило то же, что и в ``ops_kit``: фигура попадает в реестр, если заменяет
три и более команды либо несёт стандарт, который нельзя выдумать (профиль
2020, люверс под шнур, червячная пара). Всё остальное собирается одной
строкой ``lathe``/``extrude``.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_mesh
from .ops import anchor, make_solid, op
from .ops_kit import (_dedupe, _one, _pair, _placed, _profile, _rect_profile,
                      _revolve_profile, _seg, _shifted, _triple, _tube_mesh)


# --------------------------------------------------------------------------- #
#  Панель с бортиком (лоток)
# --------------------------------------------------------------------------- #
@op("panel", aliases=("панель", "лоток", "поддон", "tray"),
    category="Примитивы",
    summary="Панель с бортиком по периметру: дно и четыре стенки одним телом. "
            "Основание приборной панели, лотка, поддона.",
    example="панель = panel size=[240, 160, 22] wall=3 round=8",
    params={"size": "размер в плане и высота бортика [x,y,h], мм (240,160,22)",
            "wall": "толщина стенки и дна (3)", "round": "скругление углов (6)",
            "segments": "сегментов в скруглении", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def panel(a, name):
    sx, sy, h = _triple(a, "size", (240.0, 160.0, 22.0))
    wall = float(a.num("wall", 3.0, minv=0.4))
    floor = max(1.2, wall * 0.8)
    if wall * 2 >= min(sx, sy) - 2.0:
        raise GeometryError("Стенки не оставляют места внутри панели.",
                            hint="wall должен быть меньше половины меньшей стороны.")
    if h < wall * 1.2:
        raise GeometryError("Бортик ниже стенки — увеличьте высоту.",
                            hint="Третье число в size — высота бортика над дном.")
    round_r = float(a.num("round", 6.0, minv=0.0) or 0.0)
    seg = _seg(a, "segments", 6, 2, 32)
    outer = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx, sy, round_r, seg)]), float(floor + h))
    inner = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx - 2 * wall, sy - 2 * wall,
                                       max(0.0, round_r - wall), seg)]),
        float(h + 1.0)).translate((0.0, 0.0, floor))
    solid = outer - inner
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="panel")
    out.notes.append(f"стенка {wall:g} мм, борт {h:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Косынка
# --------------------------------------------------------------------------- #
@op("gusset", aliases=("косынка", "угольник", "усилитель_угла"),
    category="Примитивы",
    summary="Треугольная косынка жёсткости с полками: катеты, толщина, "
            "скругление вершины. Ставится в угол рамы или полки.",
    example="косынка = gusset leg=70 height=55 thickness=6",
    params={"leg": "горизонтальный катет, мм (60)", "height": "вертикальный катет (60)",
            "thickness": "толщина листа (6)", "round": "скругление свободного угла (10)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gusset(a, name):
    leg = float(a.num("leg", 60.0, minv=5.0))
    height = float(a.num("height", 60.0, minv=5.0))
    thick = float(a.num("thickness", 6.0, minv=0.6))
    round_r = float(a.num("round", 10.0, minv=0.0) or 0.0)
    steps = 6
    pts = [(0.0, 0.0), (leg, 0.0)]
    # гипотенуза с небольшим скруглением у вершины
    hyp = math.hypot(leg, height)
    for i in range(1, steps):
        t = i / steps
        x = leg * (1.0 - t)
        y = height * t
        if round_r > 0:
            shrink = round_r * (1.0 - math.sin(math.pi * t))
            x -= shrink * leg / hyp * 0.4
            y -= shrink * height / hyp * 0.4
        pts.append((x, y))
    pts.append((0.0, height))
    solid = mf.Manifold.extrude(mf.CrossSection([_profile(pts)]), thick)
    solid = solid.rotate([90.0, 0.0, 0.0])
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="gusset")
    out.notes.append(f"катеты {leg:g}×{height:g} мм, лист {thick:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Мебельная ножка
# --------------------------------------------------------------------------- #
@op("leg", aliases=("ножка", "опора", "мебельная_ножка"),
    category="Примитивы",
    summary="Ножка с верхней и нижней площадками и сужением: конусная стойка, "
            "пятка и крепёжная площадка одним телом.",
    example="ножка = leg height=90 top=34 bottom=22 flange=8",
    params={"height": "высота ножки (90)", "top": "диаметр площадки сверху (34)",
            "bottom": "диаметр стойки снизу (22)", "flange": "высота площадок (8)",
            "waist": "сужение стойки 0…1 (0.55)", "segments": "сегментов (48)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def leg(a, name):
    height = float(a.num("height", 90.0, minv=10.0))
    top = float(a.num("top", 34.0, minv=4.0))
    bottom = float(a.num("bottom", 22.0, minv=4.0))
    flange = min(float(a.num("flange", 8.0, minv=1.0)), height * 0.45)
    waist = float(a.num("waist", 0.55, minv=0.0, maxv=1.0))
    seg = _seg(a, "segments", 48, 12, 160)
    rt, rb = top / 2.0, bottom / 2.0
    mid = (rt + rb) / 2.0 * (1.0 - 0.35 * waist)
    pts = [(0.0, 0.0), (rb, 0.0), (rb, flange), (mid, height * 0.45),
           (rt * 0.92, height - flange), (rt, height - flange), (rt, height),
           (0.0, height)]
    solid = _revolve_profile(pts, seg, "ножки")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="leg")
    out.notes.append(f"высота {height:g} мм, площадка ø{top:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Направляющая (швеллер)
# --------------------------------------------------------------------------- #
@op("rail", aliases=("направляющая", "швеллер", "рельс", "guide_rail"),
    category="Примитивы",
    summary="П-образная направляющая постоянного сечения: длина, ширина, "
            "высота и стенка. Для выдвижных ящиков, станков, полок.",
    example="направляющая = rail length=400 width=30 height=14 wall=2",
    params={"length": "длина, мм (400)", "width": "ширина профиля (30)",
            "height": "высота профиля (14)", "wall": "толщина стенки (2)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def rail(a, name):
    length = float(a.num("length", 400.0, minv=10.0))
    width = float(a.num("width", 30.0, minv=4.0))
    height = float(a.num("height", 14.0, minv=4.0))
    wall = float(a.num("wall", 2.0, minv=0.4))
    if wall * 2 >= min(width, height) - 1.0:
        raise GeometryError("Стенка слишком толстая для такого профиля.")
    outer = mf.Manifold.cube((length, width, height), center=True)
    inner = mf.Manifold.cube((length + 2.0, width - 2 * wall, height - wall),
                             center=True).translate((0.0, 0.0, wall))
    solid = (outer - inner).translate((0.0, 0.0, height / 2.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="rail")
    out.notes.append(f"профиль {width:g}×{height:g} мм, стенка {wall:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Конструкционный профиль 2020
# --------------------------------------------------------------------------- #
@op("profile2020", aliases=("профиль2020", "профиль_2020", "алюминиевый_профиль",
                            " extrusion_2020", "profile_2020"),
    category="Примитивы",
    summary="Алюминиевый конструкционный профиль 20×20 с четырьмя T-пазами и "
            "центральным каналом — стандарт станочных рам и 3D-принтеров.",
    example="профиль = profile2020 length=300 size=20",
    params={"length": "длина, мм (300)", "size": "сторона квадрата (20)",
            "slot": "ширина паза (6)", "depth": "глубина паза (4.2)",
            "bore": "центральный канал (5)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def profile2020(a, name):
    length = float(a.num("length", 300.0, minv=10.0))
    size = float(a.num("size", 20.0, minv=8.0))
    slot = float(a.num("slot", 6.0, minv=1.0))
    depth = float(a.num("depth", 4.2, minv=0.5))
    bore = float(a.num("bore", 5.0, minv=1.0))
    if slot >= size - 2.0 or depth >= size / 2.0:
        raise GeometryError("Паз не помещается в профиль.",
                            hint="slot ≤ size−2, depth < size/2.")
    base = mf.Manifold.cube((size, size, length), center=True)
    tools = []
    for axis in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        if axis[0]:
            box = mf.Manifold.cube((depth * 2, slot, length + 2.0), center=True)
        else:
            box = mf.Manifold.cube((slot, depth * 2, length + 2.0), center=True)
        box = box.translate((axis[0] * size / 2.0, axis[1] * size / 2.0, 0.0))
        tools.append(box)
    channel = mf.Manifold.cylinder(length + 2.0, bore / 2.0, bore / 2.0, 24)
    channel = channel.rotate([90.0, 0.0, 0.0])
    tools.append(channel)
    solid = base
    for tool in tools:
        solid = solid - tool
    if solid.is_empty():
        raise GeometryError("Профиль получился пустым — уменьшите пазы.")
    solid = solid.translate((0.0, 0.0, length / 2.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="profile2020")
    out.notes.append(f"профиль {size:g}×{size:g} мм, длина {length:g} мм, 4 паза")
    return out


# --------------------------------------------------------------------------- #
#  Люверс
# --------------------------------------------------------------------------- #
@op("grommet", aliases=("люверс", "втулка_с_бортиком", "блочка"),
    category="Примитивы",
    summary="Люверс (блочка): втулка с бортиком под шнур или провод. "
            "Внутренний диаметр, стенка, высота и ширина бортика.",
    example="люверс = grommet diameter=12 height=8 wall=1.6 flange=3",
    params={"diameter": "внутренний диаметр (12)", "height": "высота втулки (8)",
            "wall": "толщина стенки (1.6)", "flange": "вылет бортика (3)",
            "segments": "сегментов (48)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def grommet(a, name):
    d = float(a.num("diameter", 12.0, minv=1.0))
    height = float(a.num("height", 8.0, minv=1.0))
    wall = float(a.num("wall", 1.6, minv=0.3))
    flange = float(a.num("flange", 3.0, minv=0.2))
    seg = _seg(a, "segments", 48, 12, 160)
    ri = d / 2.0
    ro = ri + wall
    pts = [(ri, 0.0), (ro, 0.0), (ro, max(0.6, height - wall * 2.0)),
           (ro + flange, max(0.6, height - wall * 2.0)),
           (ro + flange, height), (ri, height)]
    solid = _revolve_profile(pts, seg, "люверса")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="grommet")
    out.notes.append(f"внутри ø{d:g} мм, борт {flange:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Червяк
# --------------------------------------------------------------------------- #
@op("worm", aliases=("червяк", "червячный_вал", "worm_shaft"),
    category="Примитивы",
    summary="Червяк: цилиндр с настоящим винтовым витком. Шаг, число заходов, "
            "глубина витка — как у червячной передачи.",
    example="червяк = worm length=90 diameter=30 pitch=8 depth=4",
    params={"length": "длина, мм (90)", "diameter": "наружный диаметр (30)",
            "pitch": "шаг витка, мм (8)", "depth": "глубина витка (4)",
            "starts": "число заходов (1)", "sides": "сегментов витка (10)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def worm(a, name):
    length = float(a.num("length", 90.0, minv=6.0))
    d = float(a.num("diameter", 30.0, minv=4.0))
    pitch = float(a.num("pitch", 8.0, minv=1.0))
    depth = float(a.num("depth", 4.0, minv=0.4))
    starts = int(a.int("starts", 1, minv=1, maxv=4) or 1)
    sides = _seg(a, "sides", 10, 6, 24)
    if depth >= d / 2.0 - 0.5:
        raise GeometryError("Виток глубже радиуса червяка.")
    core_r = d / 2.0 - depth * 0.9
    ridge_r = depth * 0.62
    core = mf.Manifold.cylinder(length, core_r, core_r, max(24, _seg(a, "segments", 48, 16, 96)))
    parts = [core]
    turns = max(1, int(round(length / pitch)))
    steps = max(12, turns * 20)
    for s in range(starts):
        phase = 2.0 * math.pi * s / starts
        pts = []
        for i in range(steps + 1):
            t = i / steps
            z = depth * 0.8 + t * (length - depth * 1.6)
            ang = phase + 2.0 * math.pi * z / pitch
            r = core_r + ridge_r * 0.55
            pts.append((r * math.cos(ang), r * math.sin(ang), z))
        parts.append(_tube_mesh(np.asarray(pts), ridge_r, sides, "витка"))
    solid = parts[0]
    for part in parts[1:]:
        solid = solid + part
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="worm")
    out.notes.append(f"шаг {pitch:g} мм, виток {depth:g} мм, заходов {starts}")
    return out


# --------------------------------------------------------------------------- #
#  Рог
# --------------------------------------------------------------------------- #
@op("horn", aliases=("рог", "бивень", "клык"),
    category="Примитивы",
    summary="Изогнутый сужающийся рог: радиус у основания, радиус у кончика, "
            "длина и изгиб. Для природы, трофеев, декора.",
    example="рог = horn length=160 radius=22 tip=3 bend=55",
    params={"length": "длина по прямой, мм (160)", "radius": "радиус у основания (22)",
            "tip": "радиус кончика (3)", "bend": "подъём кончика, мм (55)",
            "steps": "точек вдоль рога (26)", "sides": "сегментов (20)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def horn(a, name):
    length = float(a.num("length", 160.0, minv=10.0))
    radius = float(a.num("radius", 22.0, minv=1.0))
    tip = float(a.num("tip", 3.0, minv=0.3))
    bend = float(a.num("bend", 55.0, minv=-400.0, maxv=400.0) or 0.0)
    steps = max(6, int(a.int("steps", 26, minv=6, maxv=64) or 26))
    sides = _seg(a, "sides", 20, 8, 40)
    pts, radii = [], []
    for i in range(steps + 1):
        t = i / steps
        pts.append((length * t, 0.0, bend * t * t))
        radii.append(max(0.3, radius * (1.0 - t) ** 0.85 + tip * t))
    if radius <= 0.5:
        raise GeometryError("Радиус основания слишком мал.")
    solid = _tube_mesh(np.asarray(pts), radii, sides, "рога")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="horn")
    out.notes.append(f"длина {length:g} мм, изгиб {bend:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Накатка (модификатор)
# --------------------------------------------------------------------------- #
@op("knurl", aliases=("накатка", "рифление", "grip"),
    category="Форма и деформации",
    summary="Накатка на цилиндрической детали: частое рифление по окружности. "
            "Ручки, винты, крышки, колёсики.",
    example='ручка = cylinder radius=16 height=70 segments=48\nручка = knurl [ручка] count=24 depth=1',
    params={"objects": "цилиндрическая деталь", "count": "число канавок (24)",
            "depth": "глубина канавки, мм (1)", "width": "ширина канавки, мм (0.6)",
            "axis": "ось детали x/y/z (z)", "at": "сдвиг [x,y,z]",
            "center": "центрировать по высоте"},
    positional=["objects"])
def knurl(a, name):
    base = _one(a, "knurl")
    count = int(a.int("count", 24, minv=6, maxv=96) or 24)
    depth = float(a.num("depth", 1.0, minv=0.1))
    width = float(a.num("width", 0.6, minv=0.1))
    axis = (a.text("axis", "z") or "z").strip().lower().lstrip("+-")
    if axis not in ("x", "y", "z"):
        raise GeometryError("axis должен быть x, y или z.")
    bb = base.manifold.bounding_box()
    sx, sy, sz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    if axis in ("x", "y"):
        raise GeometryError("Накатка пока работает вдоль оси z.",
                            hint="Поставьте деталь осью по z (rotate) и повторите.")
    radius = max(sx, sy) / 2.0
    if radius <= depth * 2.0:
        raise GeometryError("Деталь слишком тонкая для такой накатки.")
    solid = base.manifold
    height = sz + 2.0
    for i in range(count):
        ang = 360.0 * i / count
        box = mf.Manifold.cube((depth * 2.0, width, height), center=True)
        box = box.translate((radius, 0.0, 0.0)).rotate([0.0, 0.0, ang])
        solid = solid - box
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Накатка сняла весь материал — уменьшите depth.")
    out = make_solid(a.scene, name, _shifted(a, solid), a, base=base, kind="knurl")
    a.scene.consume(base)
    out.notes.append(f"накатка {count} канавок, глубина {depth:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Выдвижной ящик
# --------------------------------------------------------------------------- #
@op("drawer", aliases=("выдвижной_ящик", "ящик_с_фасадом"),
    category="Примитивы",
    summary="Готовый ящик: корпус с полостью, фасад, ручка и направляющие. "
            "Всё одним телом — двигайте по рельсу анимацией move.",
    example="ящик = drawer size=[420, 480, 180] wall=14 front=18 handle=да",
    params={"size": "ширина, глубина, высота [x,y,z], мм (420,480,180)",
            "wall": "толщина стенок (14)", "bottom": "толщина дна (8)",
            "front": "толщина фасада (18)", "round": "скругление углов (6)",
            "handle": "поставить ручку да/нет (да)",
            "rail": "добавить направляющие да/нет (да)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def drawer(a, name):
    sx, sy, sz = _triple(a, "size", (420.0, 480.0, 180.0))
    wall = float(a.num("wall", 14.0, minv=1.0))
    bottom = float(a.num("bottom", 8.0, minv=1.0))
    front = float(a.num("front", 18.0, minv=2.0))
    round_r = float(a.num("round", 6.0, minv=0.0) or 0.0)
    seg = _seg(a, "segments", 6, 2, 32)
    if wall * 2 >= min(sx, sy) - 2.0 or front * 2 >= sy:
        raise GeometryError("Стенки ящика не оставляют полости.")
    body_d = max(10.0, sy - front)
    outer = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx, body_d, round_r, seg)]), float(sz))
    inner = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx - 2 * wall, body_d - 2 * wall,
                                       max(0.0, round_r - wall), seg)]),
        float(sz - bottom + 1.0)).translate((0.0, 0.0, bottom))
    solid = outer - inner
    front_panel = mf.Manifold.extrude(
        mf.CrossSection([_rect_profile(sx + 2.0, front + 1.0, round_r, seg)]),
        float(sz - 2.0)).translate((0.0, body_d / 2.0 + front / 2.0 - 0.5, 1.0))
    solid = solid + front_panel
    if a.boolean("rail", True):
        for side in (-1.0, 1.0):
            rail = mf.Manifold.cube((4.0, body_d - 20.0, 12.0), center=True)
            rail = rail.translate((side * (sx / 2.0 + 1.5), -5.0, sz * 0.35))
            solid = solid + rail
    if a.boolean("handle", True):
        h_len = min(sx * 0.55, 220.0)
        bar = mf.Manifold.cylinder(h_len + 16.0, 7.0, 7.0, 20, center=True)
        bar = bar.rotate([0.0, 90.0, 0.0]).translate((0.0, body_d / 2.0 + front + 16.0,
                                                      sz * 0.68))
        solid = solid + bar
        for side in (-1.0, 1.0):
            post = mf.Manifold.cylinder(20.0, 6.0, 6.0, 16, center=True)
            post = post.rotate([90.0, 0.0, 0.0]).translate(
                (side * h_len / 2.0, body_d / 2.0 + front + 6.0, sz * 0.68))
            solid = solid + post
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Ящик получился пустым — проверьте размеры.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="drawer")
    out.notes.append(f"корпус {sx:g}×{sy:g}×{sz:g} мм, фасад {front:g} мм")
    return out
