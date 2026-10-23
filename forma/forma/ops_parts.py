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
#  Косынка
# --------------------------------------------------------------------------- #
@op("gusset", aliases=("косынка", "усилитель_угла", "треугольник_жесткости"),
    category="Примитивы",
    summary="Косынка — треугольный лист жёсткости, который вваривают или "
            "прикручивают в прямой угол рамы, чтобы он не сложился. Прямой угол "
            "здесь — вершина с катетами, гипотенуза — свободная кромка. "
            "Впадина на гипотенузе задаётся: дуга, ступени или прямой рез.",
    example="косынка = gusset leg=70 height=55 thickness=6 notch=18 notch_shape=ступени\n"
            "уголок = gusset leg=60 height=60 thickness=5 notch=0",
    params={"leg": "горизонтальный катет, мм (60)",
            "height": "вертикальный катет (60)",
            "thickness": "толщина листа (6)",
            "notch": "глубина впадины на гипотенузе, мм (0 — прямой рез)",
            "notch_shape": "форма впадины: дуга, ступени или прямо (дуга)",
            "notch_steps": "ступеней во впадине, 2…12 (4)",
            "round": "скругление свободного угла, мм (10)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gusset(a, name):
    leg = float(a.num("leg", 60.0, minv=5.0))
    height = float(a.num("height", 60.0, minv=5.0))
    thick = float(a.num("thickness", 6.0, minv=0.6))
    round_r = float(a.num("round", 10.0, minv=0.0) or 0.0)
    notch = float(a.num("notch", 0.0, minv=0.0) or 0.0)
    shape = (a.text("notch_shape") or "дуга").strip().lower()
    steps_n = int(a.int("notch_steps", 4, minv=2, maxv=12) or 4)
    if shape in ("arc", "дуга", "круг", "радиус"):
        shape = "дуга"
    elif shape in ("steps", "ступени", "ступеньки", "лесенка"):
        shape = "ступени"
    elif shape in ("straight", "прямо", "прямой", "нет"):
        shape = "прямо"
    else:
        raise GeometryError("Форма впадины: дуга, ступени или прямо.")
    hyp = math.hypot(leg, height)
    # свободная кромка: от (leg,0) к (0,height); впадина — выемка внутрь листа
    samples = 24 if shape == "дуга" else max(2, steps_n)
    pts = [(0.0, 0.0), (leg, 0.0)]
    edge = []
    for i in range(1, samples):
        t = i / samples
        x = leg * (1.0 - t)
        y = height * t
        edge.append((x, y, t))
    if shape == "дуга" and notch > 0:
        shaped = []
        for x, y, t in edge:
            shrink = notch * math.sin(math.pi * t)
            shaped.append((x - shrink * leg / hyp * 0.55,
                           y - shrink * height / hyp * 0.55))
        edge_pts = shaped
    elif shape == "ступени" and notch > 0:
        # лесенка: каждый шаг заходит в лист и выходит обратно
        edge_pts = []
        for k in range(steps_n):
            t0 = (k + 0.15) / steps_n
            t1 = (k + 0.85) / steps_n
            depth = notch * (0.5 + 0.5 * math.sin(math.pi * (k + 0.5) / steps_n))
            for t in (t0, t1):
                x = leg * (1.0 - t)
                y = height * t
                edge_pts.append((x - depth * leg / hyp * 0.55,
                                 y - depth * height / hyp * 0.55))
    else:
        edge_pts = [(x, y) for x, y, _ in edge]
    # скругление свободного угла — в самом конце (у вершины с катетом height)
    if round_r > 0 and edge_pts:
        x, y = edge_pts[-1]
        norm = math.hypot(leg, height)
        shift = min(round_r, leg * 0.3, height * 0.3)
        edge_pts[-1] = (x + shift * leg / norm * 0.25, y + shift * height / norm * 0.25)
    pts.extend(edge_pts)
    pts.append((0.0, height))
    solid = mf.Manifold.extrude(mf.CrossSection([_profile(pts)]), thick)
    solid = solid.rotate([90.0, 0.0, 0.0])
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="gusset")
    note = f"катеты {leg:g}×{height:g} мм, лист {thick:g} мм"
    if notch > 0:
        note += f", впадина {notch:g} мм ({shape})"
    out.notes.append(note)
    return out


# --------------------------------------------------------------------------- #
#  Мебельная ножка
# --------------------------------------------------------------------------- #
@op("leg", aliases=("ножка", "опора", "мебельная_ножка", "стойка"),
    category="Примитивы",
    summary="Опора мебели: стойка с верхней и нижней площадками. Это именно "
            "ножка под корпус (кровать, комод, стол), а не стойка стеллажа: "
            "у неё есть пятка на полу и площадка под саморезы сверху. "
            "Круглая или квадратная, с сужением, с регулировочной пяткой.",
    example="ножка = leg height=90 top=34 bottom=22 flange=8\n"
            "квадратная = leg height=70 top=40 bottom=30 shape=квадрат",
    params={"height": "высота ножки, мм (90)",
            "top": "размер верхней площадки, мм (34)",
            "bottom": "размер стойки снизу, мм (22)",
            "flange": "высота площадок, мм (8)",
            "waist": "сужение стойки 0…1 (0.55)",
            "shape": "круглая или квадратная (круглая)",
            "adjust": "регулировочная пятка: крутить по высоте, мм (0 — нет)",
            "segments": "сегментов круглой ножки (48)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def leg(a, name):
    height = float(a.num("height", 90.0, minv=10.0))
    top = float(a.num("top", 34.0, minv=4.0))
    bottom = float(a.num("bottom", 22.0, minv=4.0))
    flange = min(float(a.num("flange", 8.0, minv=1.0)), height * 0.45)
    waist = float(a.num("waist", 0.55, minv=0.0, maxv=1.0))
    shape = (a.text("shape") or "круглая").strip().lower()
    if shape in ("square", "квадрат", "квадратная", "box"):
        shape = "квадрат"
    elif shape in ("round", "круг", "круглая", "cylinder"):
        shape = "круглая"
    else:
        raise GeometryError("Форма ножки: круглая или квадратная.")
    adjust = float(a.num("adjust", 0.0, minv=0.0) or 0.0)
    seg = _seg(a, "segments", 48, 12, 160)
    rt, rb = top / 2.0, bottom / 2.0
    mid = (rt + rb) / 2.0 * (1.0 - 0.35 * waist)
    pts = [(0.0, 0.0), (rb, 0.0), (rb, flange), (mid, height * 0.45),
           (rt * 0.92, height - flange), (rt, height - flange), (rt, height),
           (0.0, height)]
    if shape == "круглая":
        solid = _revolve_profile(pts, seg, "ножки")
    else:
        # квадратная: площадки-плиты и сужающаяся стойка (оболочка сечений)
        def plate(side, z0, h):
            return mf.Manifold.cube((side, side, h), True).translate((0.0, 0.0, z0 + h / 2.0))
        base = plate(bottom, 0.0, max(0.6, flange))
        head = plate(top, height - flange, flange)
        waist_side = (top + bottom) / 2.0 * (1.0 - 0.35 * waist)
        lower = plate(waist_side * 0.98, height * 0.40, 1.0)
        upper = plate(waist_side * 0.98, height * 0.58, 1.0)
        shaft = mf.Manifold.batch_boolean(
            [base, head, lower, upper], mf.OpType.Add).hull()
        solid = shaft
    if adjust > 0:
        # пятка-винт: тонкий цилиндр под основанием и насечка на пятке
        stem = mf.Manifold.cylinder(adjust, max(2.0, rb * 0.35), max(2.0, rb * 0.35),
                                    max(12, seg // 2))
        stem = stem.translate((0.0, 0.0, -adjust))
        pad = mf.Manifold.cylinder(2.0, rb * 1.05, rb * 0.9, max(12, seg // 2))
        pad = pad.translate((0.0, 0.0, -adjust - 2.0))
        solid = solid + stem + pad
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="leg")
    out.notes.append(f"высота {height:g} мм, площадка {top:g} мм, {shape}")
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
#  Конструкционный профиль (2020 и его аналоги)
# --------------------------------------------------------------------------- #
@op("profile2020", aliases=("профиль2020", "профиль_2020", "алюминиевый_профиль",
                            " extrusion_2020", "profile_2020", "конструкционный_профиль"),
    category="Примитивы",
    summary="Алюминиевый конструкционный профиль: квадрат со скруглёнными "
            "рёбрами и T-пазами с четырёх сторон. Внутри — не одно круглое "
            "отверстие, а рёбра жёсткости: при малом size профиль становится "
            "набором параллельных столбиков, число и сглаживание которых "
            "настраивается. Стандарт рам, станков и 3D-принтеров.",
    example="профиль = profile2020 length=300 size=20\n"
            "мини = profile2020 length=120 size=12 columns=5 smooth=0.5",
    params={"length": "длина, мм (300)", "size": "сторона квадрата (20)",
            "slot": "ширина T-паза (6)", "depth": "глубина паза (4.2)",
            "columns": "число внутренних столбиков (5); 0 — сплошной",
            "smooth": "сглаживание столбиков 0…1 (0.6): 0 — острые рёбра",
            "wall": "толщина стенки профиля, мм (size/8)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def profile2020(a, name):
    length = float(a.num("length", 300.0, minv=10.0))
    size = float(a.num("size", 20.0, minv=6.0))
    wall = float(a.num("wall", max(0.8, size / 9.0), minv=0.4))
    slot = float(a.num("slot", min(6.0, size * 0.3), minv=0.8))
    depth = float(a.num("depth", min(4.2, max(0.6, wall - 0.8)), minv=0.4))
    columns = int(a.int("columns", 5, minv=0, maxv=12) or 0)
    smooth = float(a.num("smooth", 0.6, minv=0.0, maxv=1.0) or 0.0)
    if slot >= size - 2.0 * wall:
        raise GeometryError("Паз шире просвета между стенками профиля.",
                            hint=f"slot ≤ size − 2·wall = {size - 2 * wall:g} мм.")
    if wall * 2 >= size - 1.0:
        raise GeometryError("Стенка профиля слишком толстая.",
                            hint="wall должна быть меньше половины size.")
    # T-паз остаётся ЗАКРЫТЫМ: его дно не доходит до внутренней полости,
    # иначе профиль распадается на четыре угловых куска (было в 0.19).
    if depth > wall - 0.6:
        a.scene.log("info", f"profile2020: глубина паза {depth:g} → {wall - 0.6:g} мм "
                            f"(чтобы паз не пробил стенку)", a.cmd.line)
        depth = max(0.4, wall - 0.6)
    base = mf.Manifold.cube((size, size, length), center=True)
    # T-паз: узкая горловина у поверхности и широкий канал под ней.
    lip_h = min(max(0.7, depth * 0.35), depth * 0.55)
    neck = max(0.9, slot * 0.72)
    channel = slot
    body_h = max(0.4, depth - lip_h)
    mid = size / 2.0 - lip_h - body_h / 2.0
    tools = []
    for axis in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        if axis[0]:
            neck_box = mf.Manifold.cube((lip_h * 2, neck, length + 2.0), center=True)
            body_box = mf.Manifold.cube((body_h * 2, channel, length + 2.0), center=True)
            neck_box = neck_box.translate((axis[0] * (size / 2.0 - lip_h),
                                           axis[1] * (size / 2.0 - lip_h * 0.0), 0.0))
            body_box = body_box.translate((axis[0] * mid, 0.0, 0.0))
        else:
            neck_box = mf.Manifold.cube((neck, lip_h * 2, length + 2.0), center=True)
            body_box = mf.Manifold.cube((channel, body_h * 2, length + 2.0), center=True)
            neck_box = neck_box.translate((0.0, axis[1] * (size / 2.0 - lip_h), 0.0))
            body_box = body_box.translate((0.0, axis[1] * mid, 0.0))
        tools.append(neck_box)
        tools.append(body_box)
    solid = base
    for tool in tools:
        solid = solid - tool
    # Внутри — не одно круглое отверстие, а параллельные каналы,
    # разделённые столбиками; при малом size это и есть «набор столбиков».
    inner_size = size - 2.0 * wall
    if columns <= 0:
        solid = solid - mf.Manifold.cube((inner_size, inner_size, length + 2.0), center=True)
    else:
        max_columns = max(1, int((inner_size - 0.6) / 1.2))
        if columns > max_columns:
            a.scene.log("info", f"profile2020: столбиков {columns} → {max_columns} "
                                f"(профиль {size:g} мм)", a.cmd.line)
            columns = max_columns
        rib = max(0.6, min(inner_size * 0.12,
                           (inner_size - columns * 0.9) / max(1, columns)))
        slot_w = (inner_size - rib * (columns - 1)) / columns
        if slot_w < 0.7:
            raise GeometryError("Столбики не помещаются внутри профиля.",
                                hint=f"Уменьшите columns (сейчас {columns}) или увеличьте size.")
        corner = min(rib * 0.6 * smooth, slot_w * 0.45, inner_size * 0.3)
        seg_r = 4 if corner > 1e-3 else 2
        tool = None
        for i in range(columns):
            center = -inner_size / 2.0 + slot_w / 2.0 + i * (slot_w + rib)
            prof = _rect_profile(slot_w, inner_size, corner, seg_r)
            cavity = mf.Manifold.extrude(mf.CrossSection([prof]), length + 2.0)
            cavity = cavity.translate((center, 0.0, 0.0))
            tool = cavity if tool is None else tool + cavity
        solid = solid - tool
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Профиль получился пустым — уменьшите пазы или полость.")
    if len(solid.decompose()) != 1:
        raise GeometryError(
            "Профиль распался на части: пазы пробили стенку.",
            hint="Уменьшите depth или увеличьте wall.")
    solid = solid.translate((0.0, 0.0, length / 2.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="profile2020")
    out.notes.append(f"профиль {size:g}×{size:g} мм, длина {length:g} мм, "
                     f"4 T-паза, каналов {columns}")
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
@op("worm_shaft", aliases=("червяк", "червячный_вал", "червячная_передача", "worm"),
    category="Примитивы",
    summary="Червячный вал (по-простому «червяк») — винт, который крутит "
            "червячное колесо. Это не крепёж и не шнек: виток непрерывный, "
            "шаг и число заходов задаются, как у настоящей передачи.",
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
    # канавки идут по всей высоте детали, а не только от нуля: ось — центр
    # габарита, иначе на детали, стоящей на столе, рифление закрывает низ
    cx = (bb[0] + bb[3]) / 2.0
    cy = (bb[1] + bb[4]) / 2.0
    cz = (bb[2] + bb[5]) / 2.0
    for i in range(count):
        ang = 360.0 * i / count
        box = mf.Manifold.cube((depth * 2.0, width, height), center=True)
        box = box.translate((radius, 0.0, 0.0)).rotate([0.0, 0.0, ang])
        box = box.translate((cx, cy, cz))
        solid = solid - box
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Накатка сняла весь материал — уменьшите depth.")
    out = make_solid(a.scene, name, _shifted(a, solid), a, base=base, kind="knurl")
    a.scene.consume(base)
    out.notes.append(f"накатка {count} канавок, глубина {depth:g} мм")
    return out
