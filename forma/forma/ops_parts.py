"""Готовые детали: косынка, скоба, люверс, червяк, рог и накатка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (ensure_ccw, manifold_from_arrays, manifold_mesh,
                       _rings_to_arrays)
from .ops import anchor, make_solid, op
from .ops_kit import (_dedupe, _one, _pair, _placed, _profile, _rect_profile,
                      _revolve_profile, _seg, _shifted, _triple, _tube_mesh)
from .shape_features import apply_smooth, rounded_extrude, transition_radius


@op("gusset", aliases=("косынка", "усилитель_угла", "треугольник_жесткости"),
    category="Примитивы",
    summary="Косынка с шестью точно названными контурами: прямая, "
            "прямая_с_пазом, выпуклая, выпуклая_с_пазом, вогнутая и "
            "вогнутая_с_пазом. Паз прямоугольный; дуга и его наличие "
            "выбираются независимо. Старые прямо и горка сохранены как алиасы.",
    example="косынка = gusset leg=70 height=55 thickness=6\n"
            "паз = gusset leg=70 height=55 thickness=6 shape=прямая_с_пазом notch=8\n"
            "впадина = gusset leg=70 height=55 thickness=6 shape=вогнутая",
    params={"leg": "горизонтальный катет по X, мм (60)",
            "height": "вертикальный катет по Z, мм (60)",
            "thickness": "толщина листа по Y, мм (6)",
            "shape": "прямая, прямая_с_пазом, выпуклая, выпуклая_с_пазом, "
                     "вогнутая или вогнутая_с_пазом",
            "notch": "глубина паза для режима с_пазом, мм (8)",
            "notch_width": "ширина паза вдоль исходной гипотенузы, мм (24)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gusset(a, name):
    leg = float(a.num("leg", 60.0, minv=0.2, maxv=10000.0))
    height = float(a.num("height", 60.0, minv=0.2, maxv=10000.0))
    thick = float(a.num("thickness", 6.0, minv=0.05, maxv=2000.0))
    raw = (a.text("shape", "прямая") or "прямая").strip().lower()
    shape = {
        "прямо": "прямая", "прямая": "прямая", "треугольник": "прямая", "straight": "прямая",
        "прямая_с_пазом": "прямая_с_пазом", "прямо_с_пазом": "прямая_с_пазом",
        "прямая_с_вырезом": "прямая_с_пазом",
        "горка": "выпуклая_с_пазом", "круглая": "выпуклая_с_пазом", "дуга": "выпуклая_с_пазом",
        "hill": "выпуклая_с_пазом", "arc": "выпуклая_с_пазом",
        "горка_без_выреза": "выпуклая", "выпуклая": "выпуклая",
        "выпуклая_без_паза": "выпуклая",
        "выпуклая_с_пазом": "выпуклая_с_пазом", "горка_с_пазом": "выпуклая_с_пазом",
        "вогнутая": "вогнутая", "лодка": "вогнутая", "впадина": "вогнутая",
        "вогнутая_без_паза": "вогнутая",
        "вогнутая_с_пазом": "вогнутая_с_пазом", "лодка_с_пазом": "вогнутая_с_пазом",
    }.get(raw)
    if shape is None:
        raise GeometryError("gusset: shape=прямая, прямая_с_пазом, выпуклая, "
                            "выпуклая_с_пазом, вогнутая или вогнутая_с_пазом.")
    arc_kind = "прямая" if shape.startswith("прямая") else ("выпуклая" if shape.startswith("выпуклая") else "вогнутая")
    with_notch = shape.endswith("_с_пазом")
    points = [(0.0, 0.0), (leg, 0.0)]
    hyp = math.hypot(leg, height)
    hill = min(leg, height) * 0.14 if arc_kind != "прямая" else 0.0
    notch = float(a.num("notch", 8.0, minv=0.0,
                        maxv=min(leg, height) * 0.6) or 0.0) if with_notch else 0.0
    notch_w = float(a.num("notch_width", 24.0, minv=0.2,
                          maxv=hyp * 0.8)) if with_notch else 0.0
    normal = np.asarray([height / hyp, leg / hyp])
    radius = hyp * hyp / (8.0 * hill) + hill / 2.0 if hill > 1e-9 else 1.0

    def point(t, offset):
        base = np.asarray([leg * (1.0 - t), height * t])
        return tuple(base + normal * offset)

    def arc_offset(t):
        if hill <= 1e-9:
            return 0.0
        q = (t - 0.5) * hyp
        value = math.sqrt(max(0.0, radius * radius - q * q)) - (radius - hill)
        return value if arc_kind == "выпуклая" else -value

    t0 = 0.5 - notch_w / (2.0 * hyp)
    t1 = 0.5 + notch_w / (2.0 * hyp)
    if arc_kind == "прямая":
        # У прямой гипотенузы промежуточные коллинеарные вершины не нужны:
        # они засоряли сетку даже у обычного прямоугольного треугольника.
        if with_notch and notch > 1e-6:
            points.extend([point(t0, 0.0), point(t0, -notch),
                           point(t1, -notch), point(t1, 0.0)])
    else:
        edge = []
        for i in range(1, 65):
            t = i / 64.0
            if t >= t0:
                break
            edge.append(point(t, arc_offset(t)))
        edge.append(point(t0, arc_offset(t0)))
        if notch > 1e-6:
            bottom = arc_offset(t0) - notch
            edge.append(point(t0, bottom))
            edge.append(point(t1, bottom))
        edge.append(point(t1, arc_offset(t1)))
        for i in range(1, 65):
            t = i / 64.0
            if t > t1 and t < 1.0 - 1e-9:
                edge.append(point(t, arc_offset(t)))
        points.extend(edge)
    points.append((0.0, height))
    triangle = mf.CrossSection([_profile(points)])
    solid = mf.Manifold.extrude(triangle, thick).rotate((90.0, 0.0, 0.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="gusset")
    out.meta["gusset_shape"] = shape
    out.notes.append(f"косынка {shape}: катеты {leg:g}×{height:g} мм, лист {thick:g} мм")
    return out


@op("скоба", aliases=("скоба_п", "п-образная", "п_образная", "п-профиль", "u-профиль",
                      "u_channel", "staple"),
    category="Примитивы",
    summary="Единая скоба: прямоугольная П/U или овальная U с круглым дном. "
            "shape=овал задаёт настоящее овальное сечение, open переворачивает "
            "его. sides=4 — прямоугольная замкнутая рамка. smooth скругляет "
            "только переходные рёбра, не стягивая широкие полки. Длина идёт "
            "по X, сечение — по Y и Z.",
    example="кронштейн = скоба length=120 width=40 height=30 wall=3\n"
            "овальная = скоба length=120 width=40 height=35 wall=3 shape=овал smooth=1\n"
            "рамка = скоба length=160 width=90 height=60 wall=4 стороны=4",
    params={"length": "длина, мм (120)", "width": "ширина, мм (40)",
            "height": "высота, мм (30)", "wall": "толщина листа, мм (3)",
            "sides": "3 — открытая скоба, 4 — замкнутая рамка (3)",
            "shape": "прямоугольная или овал/U — круглое дно и прямые полки",
            "open": "куда открыта скоба: вверх (U) или вниз (П) — «вверх»",
            "smooth": "ступени скругления переходных рёбер 0…4 (0), "
                      "без Loop-деформации и сколов полок",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def скоба(a, name):
    length = float(a.num("length", 120.0, minv=1.0))
    width = float(a.num("width", 40.0, minv=2.0))
    height = float(a.num("height", 30.0, minv=2.0))
    wall = float(a.num("wall", 3.0, minv=0.2))
    sides = int(a.int("sides", 3, minv=3, maxv=4) or 3)
    opening = (a.text("open") or "вверх").strip().lower()
    if opening in ("вниз", "п", "down", "п-образная"):
        opening = "вниз"
    else:
        opening = "вверх"
    shape = (a.text("shape") or "прямоугольная").strip().lower()
    if shape in ("овал", "овальная", "oval", "u", "круглая"):
        shape = "овал"
    elif shape in ("прямоугольная", "прямая", "rect", "rectangle"):
        shape = "прямоугольная"
    else:
        raise GeometryError("скоба: shape=прямоугольная или овал.")
    if wall * 2 >= min(width, height) - 0.5:
        raise GeometryError(
            f"Стенка {wall:g} мм не оставляет места: ширина {width:g} и высота "
            f"{height:g} мм.",
            hint=f"Стенка должна быть меньше половины меньшего размера "
                 f"({min(width, height) / 2:g} мм).")
    if shape == "овал":
        if sides != 3:
            raise GeometryError("Овальная скоба — открытая U: используйте sides=3.")
        radius = width / 2.0
        if height < radius:
            raise GeometryError("Для овальной U высота должна быть не меньше width/2.",
                                hint="Так над дуговым дном остаются прямые полки.")
        ri = radius - wall
        if ri <= 0.2:
            raise GeometryError("Стенка съела овальное дно скобы.")
        n = 48
        prof = [(-radius, height), (-radius, radius)]
        for i in range(1, n + 1):
            t = math.pi + math.pi * i / n
            prof.append((radius * math.cos(t), radius + radius * math.sin(t)))
        prof.append((radius, height))
        prof.append((ri, height))
        prof.append((ri, radius))
        for i in range(1, n + 1):
            t = -math.pi * i / n
            prof.append((ri * math.cos(t), radius + ri * math.sin(t)))
        prof.append((-ri, height))
        cross = mf.CrossSection([_profile(prof)])
    else:
        hx, hz = width / 2.0, height / 2.0
        outer = mf.CrossSection([_profile([(-hx, -hz), (hx, -hz),
                                          (hx, hz), (-hx, hz)])])
        if sides >= 4:
            inner_pts = [(-hx + wall, -hz + wall), (hx - wall, -hz + wall),
                         (hx - wall, hz - wall), (-hx + wall, hz - wall)]
        elif opening == "вверх":
            inner_pts = [(-hx + wall, -hz + wall), (hx - wall, -hz + wall),
                         (hx - wall, hz + wall), (-hx + wall, hz + wall)]
        else:
            inner_pts = [(-hx + wall, -hz - wall), (hx - wall, -hz - wall),
                         (hx - wall, hz - wall), (-hx + wall, hz - wall)]
        inner = mf.CrossSection([_profile(inner_pts)])
        cross = mf.CrossSection.batch_boolean([outer, inner], mf.OpType.Subtract)
    edge_r = transition_radius(a, min(length * 0.45, wall * 0.45))
    solid = rounded_extrude(cross, length, edge_r, "скоба")
    # (u,v,l) → (l,u,v): единое сечение не даёт сколов на стыке полок.
    matrix = np.array([[0.0, 0.0, 1.0, -length / 2.0],
                       [1.0, 0.0, 0.0, 0.0],
                       [0.0, 1.0, 0.0, 0.0]])
    solid = solid.transform(matrix)
    if shape == "овал" and opening == "вниз":
        solid = solid.rotate((180.0, 0.0, 0.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="скоба")
    where = ("овальная U" if shape == "овал" else
             "замкнутая рамка" if sides >= 4 else
             "U, открыта вверх" if opening == "вверх" else "П, открыта вниз")
    out.notes.append(f"{where}: {length:g}×{width:g}×{height:g} мм, лист {wall:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Люверс
# --------------------------------------------------------------------------- #
def _fill_cap(r: float, radius: float, sag: float) -> float:
    sphere_r = (radius * radius + sag * sag) / (2.0 * sag)
    return sag - (math.sqrt(max(0.0, sphere_r * sphere_r - r * r))
                  - math.sqrt(max(0.0, sphere_r * sphere_r - radius * radius)))


@op("grommet", aliases=("люверс", "втулка_с_бортиком", "блочка"),
    category="Примитивы",
    summary="Люверс (блочка): втулка с бортиком. fill заполняет верхнее "
            "отверстие заподлицо, выпуклым куполом или вогнутой чашей; "
            "заполнение и втулка остаются одним телом.",
    example="люверс = grommet diameter=12 height=8 wall=1.6 flange=3\n"
            "кнопка = grommet diameter=12 height=8 fill=выпуклая fill_h=2\n"
            "чаша = grommet diameter=12 height=8 fill=вогнутая fill_h=1.5",
    params={"diameter": "внутренний диаметр (12)", "height": "высота втулки (8)",
            "wall": "толщина стенки (1.6)", "flange": "вылет бортика (3)",
            "fill": "нет, ровно, выпуклая или вогнутая верхняя крышка (нет)",
            "fill_h": "толщина ровной крышки / стрелка купола или чаши, мм (0.75 wall)",
            "smooth": "уровни Loop-сглаживания всего люверса 0…4 (0)",
            "segments": "сегментов (48)", "at": "положение [x,y,z]",
            "center": "центрировать по высоте"})
def grommet(a, name):
    d = float(a.num("diameter", 12.0, minv=1.0))
    height = float(a.num("height", 8.0, minv=1.0))
    wall = float(a.num("wall", 1.6, minv=0.3))
    flange = float(a.num("flange", 3.0, minv=0.2))
    fill = (a.text("fill", "нет") or "нет").strip().lower()
    fill = {"нет": "нет", "0": "нет", "ровно": "ровно", "плоско": "ровно",
            "плоская": "ровно", "выпуклая": "выпуклая", "линза": "выпуклая",
            "купол": "выпуклая", "вогнутая": "вогнутая", "чаша": "вогнутая"}.get(fill)
    if fill is None:
        raise GeometryError("grommet: fill=нет, ровно, выпуклая или вогнутая.")
    fill_h = float(a.num("fill_h", wall * 0.75, minv=0.1, maxv=1000.0))
    seg = _seg(a, "segments", 48, 12, 160)
    ri = d / 2.0
    ro = ri + wall
    pts = [(ri, 0.0), (ro, 0.0), (ro, max(0.6, height - wall * 2.0)),
           (ro + flange, max(0.6, height - wall * 2.0)),
           (ro + flange, height), (ri, height)]
    solid = _revolve_profile(pts, seg, "люверса")
    if fill != "нет":
        radius = ri + min(0.05, wall * 0.05)
        if fill == "ровно":
            plug = mf.Manifold.cylinder(fill_h, radius, radius, seg).translate(
                (0.0, 0.0, height - fill_h))
        else:
            base = height - (max(wall, 0.4) if fill == "выпуклая"
                             else max(wall, fill_h + 0.3))
            profile = [(0.0, base), (radius, base), (radius, height)]
            for i in range(23, -1, -1):
                r = radius * i / 24.0
                cap = _fill_cap(r, radius, fill_h)
                z = height + fill_h - cap if fill == "выпуклая" else height - fill_h + cap
                profile.append((r, z))
            plug = _revolve_profile(profile, seg, "заполнения люверса")
        solid = solid + plug
    solid = apply_smooth(solid, a, "люверс")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="grommet")
    out.meta["fill"] = fill
    out.notes.append(f"внутри ø{d:g} мм, борт {flange:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Червяк
# --------------------------------------------------------------------------- #
def _worm_thread(zs, phases, center_r, profile_ru, scales, what, root_radial=None):
    """Виток в рамке ось–радиус, без вращения профиля вокруг своей оси."""
    # Базис (ось Z, радиус er) имеет нормаль +e_theta — по направлению
    # обхода витка. Поэтому и крышки, и боковые грани получают одинаковую
    # наружную ориентацию; исходный профиль задан как (радиус, ось).
    profile = ensure_ccw(np.asarray([(v, u) for u, v in profile_ru], dtype=np.float64))
    rings = []
    for z, ang, scale in zip(zs, phases, scales):
        er = np.asarray([math.cos(ang), math.sin(ang), 0.0])
        center = np.asarray([center_r * er[0], center_r * er[1], z])
        rings.append(np.asarray([
            center + np.asarray([0.0, 0.0, axial * scale])
            + er * (radial * scale if root_radial is None else
                    root_radial + (radial - root_radial) * scale)
            for axial, radial in profile]))
    verts, faces = _rings_to_arrays(rings, profile)
    return manifold_from_arrays(verts, faces, what)


@op("worm_shaft", aliases=("червяк", "червячный_вал", "червячная_передача", "worm"),
    category="Примитивы",
    summary="Червячный вал с непрерывным витком. Профиль круглый, "
            "трапециевидный, прямоугольный или треугольный; концы срезанные, "
            "конусные или скруглённые. bore — осевое отверстие, channel — "
            "канал внутри самого витка, как у полого провода.",
    example="червяк = worm length=90 diameter=30 pitch=8 depth=4\n"
            "трапеция = worm length=90 diameter=30 pitch=8 depth=4 profile=трапеция thread_w=5 tip_w=2 end=конус\n"
            "полый = worm length=90 diameter=30 pitch=8 depth=4 bore=6 channel=1.2",
    params={"length": "длина, мм (90)", "diameter": "наружный диаметр (30)",
            "pitch": "шаг витка, мм (8)", "depth": "радиальная глубина витка (4)",
            "starts": "число заходов (1)",
            "profile": "круглый, трапеция, прямоугольник или треугольник",
            "thread_w": "ширина витка у основания по оси, мм (0.5 pitch)",
            "tip_w": "ширина вершины трапеции, мм (0.45 thread_w)",
            "end": "срез, конус или скругление обоих концов витка",
            "end_h": "длина перехода на каждом конце, мм (до 20% length)",
            "bore": "осевое отверстие вала, мм; 0 — сплошной (0)",
            "channel": "диаметр канала внутри винтового витка, мм; 0 — сплошной (0)",
            "sides": "сегментов круглого профиля и канала (10)",
            "segments": "сегментов сердечника (48)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def worm(a, name):
    length = float(a.num("length", 90.0, minv=6.0))
    d = float(a.num("diameter", 30.0, minv=4.0))
    pitch = float(a.num("pitch", 8.0, minv=1.0))
    depth = float(a.num("depth", 4.0, minv=0.4))
    starts = int(a.int("starts", 1, minv=1, maxv=4) or 1)
    sides = _seg(a, "sides", 10, 6, 32)
    profile_kind = (a.text("profile", "круглый") or "круглый").strip().lower()
    profile_kind = {"круг": "круглый", "круглый": "круглый", "round": "круглый",
                    "трапеция": "трапеция", "трапециевидный": "трапеция",
                    "прямоугольник": "прямоугольник", "прямоугольный": "прямоугольник",
                    "брусок": "прямоугольник", "треугольник": "треугольник",
                    "треугольный": "треугольник", "острый": "треугольник"}.get(profile_kind)
    if profile_kind is None:
        raise GeometryError("worm: profile=круглый, трапеция, прямоугольник или треугольник.")
    thread_w = float(a.num("thread_w", pitch * 0.5, minv=0.1, maxv=pitch * 2.0))
    tip_w = float(a.num("tip_w", thread_w * 0.45, minv=0.05, maxv=thread_w))
    end = (a.text("end", "срез") or "срез").strip().lower()
    end = {"срез": "срез", "плоский": "срез", "конус": "конус",
           "конический": "конус", "скругление": "скругление",
           "круглый": "скругление", "round": "скругление"}.get(end)
    if end is None:
        raise GeometryError("worm: end=срез, конус или скругление.")
    end_h = float(a.num("end_h", min(pitch, length * 0.2),
                        minv=0.05, maxv=length * 0.5))
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    channel = float(a.num("channel", 0.0, minv=0.0) or 0.0)
    if depth >= d / 2.0 - 0.5:
        raise GeometryError("Виток глубже радиуса червяка.")
    core_r = d / 2.0 - depth
    if core_r <= 0.3:
        raise GeometryError("Сердечник червяка слишком тонкий.")
    if bore >= core_r * 2.0 - 0.2:
        raise GeometryError("bore не оставляет стенки сердечника.")
    center_r = core_r + depth * 0.45
    if profile_kind == "круглый":
        rr = depth * 0.55
        profile_ru = [(rr * math.cos(2 * math.pi * i / sides),
                       rr * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
        available = 2.0 * rr
    else:
        outer_w = thread_w if profile_kind == "прямоугольник" else (0.0 if profile_kind == "треугольник" else tip_w)
        if outer_w <= 1e-9:
            profile_ru = [(-depth * 0.50, -thread_w / 2.0),
                          (depth * 0.55, 0.0),
                          (-depth * 0.50, thread_w / 2.0)]
        else:
            profile_ru = [(-depth * 0.50, -thread_w / 2.0),
                          (depth * 0.55, -outer_w / 2.0),
                          (depth * 0.55, outer_w / 2.0),
                          (-depth * 0.50, thread_w / 2.0)]
        available = thread_w + (outer_w - thread_w) * (0.50 / 1.05)
    if channel >= min(depth * 0.9, available * 0.85):
        raise GeometryError("channel не помещается внутри витка.",
                            hint=f"Для этого профиля нужен канал меньше {min(depth * 0.9, available * 0.85):g} мм.")
    segments = max(24, _seg(a, "segments", 48, 16, 96))
    core = mf.Manifold.cylinder(length, core_r, core_r, segments)
    turns = max(1.0, length / pitch)
    steps = max(24, int(math.ceil(turns * 32)))
    zs = np.linspace(0.0, length, steps + 1)
    scales = np.ones(len(zs))
    if end != "срез":
        for i, z in enumerate(zs):
            q = min(1.0, z / end_h, (length - z) / end_h)
            if q < 1.0:
                q = max(0.0, q)
                scales[i] = max(0.06, q if end == "конус" else math.sqrt(max(0.0, 1.0 - (1.0 - q) ** 2)))
    parts = [core]
    for start in range(starts):
        phase = 2.0 * math.pi * start / starts
        angles = phase + 2.0 * math.pi * zs / pitch
        parts.append(_worm_thread(zs, angles, center_r, profile_ru, scales, "витка",
                                  root_radial=min(u for u, _ in profile_ru)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    # Виток имеет осевую ширину: без этого среза его торцы увеличивали length.
    clip = mf.Manifold.cube((d * 2.0 + 4.0, d * 2.0 + 4.0, length), True).translate(
        (0.0, 0.0, length / 2.0))
    solid = solid ^ clip
    if bore > 1e-6:
        tool = mf.Manifold.cylinder(length + 2.0, bore / 2.0, bore / 2.0, segments).translate((0, 0, -1))
        solid = solid - tool
    if channel > 1e-6:
        cz = np.linspace(-0.75, length + 0.75, steps + 9)
        # Канал сужается вместе с витком, иначе на конусных концах резец
        # шире самого витка и разрезает его на отдельные куски.
        channel_scales = np.ones(len(cz))
        if end != "срез":
            for i, z in enumerate(cz):
                q = min(1.0, max(0.0, z) / end_h, max(0.0, length - z) / end_h)
                if 0.0 <= z <= length and q < 1.0:
                    q = max(0.0, q)
                    channel_scales[i] = max(0.06, q if end == "конус" else
                                            math.sqrt(max(0.0, 1.0 - (1.0 - q) ** 2)))
        circle = [(channel / 2.0 * math.cos(2.0 * math.pi * i / max(12, sides)),
                   channel / 2.0 * math.sin(2.0 * math.pi * i / max(12, sides)))
                  for i in range(max(12, sides))]
        for start in range(starts):
            phase = 2.0 * math.pi * start / starts
            angles = phase + 2.0 * math.pi * cz / pitch
            cutter = _worm_thread(cz, angles, center_r, circle, channel_scales,
                                  "канала витка")
            solid = solid - cutter
    solid = solid ^ clip
    if solid.is_empty() or solid.volume() <= 1e-6 or len(solid.decompose()) != 1:
        raise GeometryError("Червяк пуст или распался: проверьте bore/channel и размеры витка.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="worm")
    out.meta.update({"profile": profile_kind, "end": end, "bore": bore, "channel": channel})
    out.notes.append(f"шаг {pitch:g} мм, виток {profile_kind}, заходов {starts}, "
                     f"концы {end}, bore {bore:g}, channel {channel:g}")
    return out


# --------------------------------------------------------------------------- #
#  Рог
# --------------------------------------------------------------------------- #
@op("horn", aliases=("рог", "бивень", "клык"),
    category="Примитивы",
    summary="Изогнутый сужающийся рог. wall>0 делает настоящую полость "
            "вдоль кривой с открытым основанием и закрытым кончиком.",
    example="рог = horn length=160 radius=22 tip=3 bend=55\n"
            "полый = horn length=160 radius=22 tip=3 bend=55 wall=2",
    params={"length": "длина по прямой, мм (160)", "radius": "радиус у основания (22)",
            "tip": "радиус кончика (3)", "bend": "подъём кончика, мм (55)",
            "wall": "стенка полого рога, мм; 0 — сплошной (0)",
            "steps": "точек вдоль рога (26)", "sides": "сегментов (20)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def horn(a, name):
    length = float(a.num("length", 160.0, minv=10.0))
    radius = float(a.num("radius", 22.0, minv=1.0))
    tip = float(a.num("tip", 3.0, minv=0.3))
    bend = float(a.num("bend", 55.0, minv=-400.0, maxv=400.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
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
    if wall > 1e-6:
        if wall >= radius - 0.2:
            raise GeometryError("wall не оставляет стенки у основания рога.")
        parr = np.asarray(pts, dtype=np.float64)
        seglen = np.linalg.norm(np.diff(parr, axis=0), axis=1)
        from_tip = np.concatenate([np.cumsum(seglen[::-1])[::-1], [0.0]])
        end = -1
        for i in range(steps, 0, -1):
            if from_tip[i] >= wall and radii[i] > wall + 0.15:
                end = i
                break
        if end < 1:
            raise GeometryError("wall слишком велик: полость не помещается внутри рога.")
        cavity_pts = [tuple(p) for p in parr[:end + 1]]
        cavity_r = [float(r - wall) for r in radii[:end + 1]]
        tangent = parr[1] - parr[0]
        tangent = tangent / np.linalg.norm(tangent)
        cavity_pts.insert(0, tuple(parr[0] - tangent))
        cavity_r.insert(0, cavity_r[0])
        cavity = _tube_mesh(np.asarray(cavity_pts), cavity_r, sides, "полости рога")
        solid = solid - cavity
        if solid.is_empty() or solid.volume() <= 1e-6:
            raise GeometryError("Полость удалила рог — уменьшите wall.")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="horn")
    out.notes.append(f"длина {length:g} мм, изгиб {bend:g} мм, wall={wall:g}")
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
