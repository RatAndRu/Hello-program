"""Готовые детали: косынка, скоба, люверс, червяк, рог и накатка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_mesh
from .ops import anchor, make_solid, op
from .ops_kit import (_dedupe, _one, _pair, _placed, _profile, _rect_profile,
                      _revolve_profile, _seg, _shifted, _triple, _tube_mesh)
from .shape_features import apply_smooth


@op("gusset", aliases=("косынка", "усилитель_угла", "треугольник_жесткости"),
    category="Примитивы",
    summary="Косынка — ровный прямоугольный треугольный лист. Катеты идут "
            "по +X и +Z, прямой угол находится в начале координат, гипотенуза "
            "— одна чистая прямая без впадин, фасок и лишних вершин.",
    example="косынка = gusset leg=70 height=55 thickness=6",
    params={"leg": "горизонтальный катет по X, мм (60)",
            "height": "вертикальный катет по Z, мм (60)",
            "thickness": "толщина листа по Y, мм (6)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def gusset(a, name):
    leg = float(a.num("leg", 60.0, minv=0.2, maxv=10000.0))
    height = float(a.num("height", 60.0, minv=0.2, maxv=10000.0))
    thick = float(a.num("thickness", 6.0, minv=0.05, maxv=2000.0))
    triangle = mf.CrossSection([_profile([(0.0, 0.0), (leg, 0.0), (0.0, height)])])
    solid = mf.Manifold.extrude(triangle, thick).rotate((90.0, 0.0, 0.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="gusset")
    out.notes.append(f"прямоугольный треугольник {leg:g}×{height:g} мм, лист {thick:g} мм")
    return out


@op("скоба", aliases=("скоба_п", "п-образная", "п_образная", "п-профиль", "u-профиль",
                      "u_channel", "staple"),
    category="Примитивы",
    summary="Единая скоба: прямоугольная П/U или овальная U с круглым дном. "
            "shape=овал задаёт настоящее овальное сечение, open переворачивает "
            "его. sides=4 — прямоугольная замкнутая рамка. smooth сглаживает "
            "всю деталь. Длина идёт по X, сечение — по Y и Z.",
    example="кронштейн = скоба length=120 width=40 height=30 wall=3\n"
            "овальная = скоба length=120 width=40 height=35 wall=3 shape=овал smooth=1\n"
            "рамка = скоба length=160 width=90 height=60 wall=4 стороны=4",
    params={"length": "длина, мм (120)", "width": "ширина, мм (40)",
            "height": "высота, мм (30)", "wall": "толщина листа, мм (3)",
            "sides": "3 — открытая скоба, 4 — замкнутая рамка (3)",
            "shape": "прямоугольная или овал/U — круглое дно и прямые полки",
            "open": "куда открыта скоба: вверх (U) или вниз (П) — «вверх»",
            "smooth": "уровни Loop-сглаживания всей скобы 0…4 (0)",
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
        solid = mf.CrossSection([_profile(prof)]).extrude(length)
        # (u,v,l) → (l,u,v): циклическая перестановка, ориентация сохраняется.
        matrix = np.array([[0.0, 0.0, 1.0, -length / 2.0],
                           [1.0, 0.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0, 0.0]])
        solid = solid.transform(matrix)
        if opening == "вниз":
            solid = solid.rotate((180.0, 0.0, 0.0))
    else:
        outer = mf.Manifold.cube((length, width, height), center=True)
        if sides >= 4:
            inner = mf.Manifold.cube((length + 2.0, width - 2 * wall, height - 2 * wall),
                                     center=True)
        else:
            inner = mf.Manifold.cube((length + 2.0, width - 2 * wall, height - wall),
                                     center=True)
            inner = inner.translate((0.0, 0.0, wall / 2.0 if opening == "вверх"
                                     else -wall / 2.0))
        solid = outer - inner
    solid = apply_smooth(solid, a, "скоба")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="скоба")
    where = ("овальная U" if shape == "овал" else
             "замкнутая рамка" if sides >= 4 else
             "U, открыта вверх" if opening == "вверх" else "П, открыта вниз")
    out.notes.append(f"{where}: {length:g}×{width:g}×{height:g} мм, лист {wall:g} мм")
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
            "smooth": "уровни Loop-сглаживания всего люверса 0…4 (0)",
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
    solid = apply_smooth(solid, a, "люверс")
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
