"""Крюк и полуовальная пластина — мелкая фурнитура, которой не хватало.

* `крюк` — одна непрерывная гнутая линия без кольца: прямой хвостик,
  соединитель и овальная/пространственная дуга, острый или капсульный конец.
* `полуовал` — плоская пластина-полуовал: снизу прямая кромка, сверху дуга
  эллипса. Отверстие по центру можно сделать, а можно и не делать (`hole=0`):
  это и подвес, и подпятник, и накладка, и ушко.

    крюк = крюк wire=6 radius=22 length=70 open=240 tip=острый
    подвес = полуовал width=90 height=55 thickness=8 hole=16
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, sweep_solid
from .ops import anchor, make_solid, op, stand_flat_sign
from .shape_features import (open_top_cavity, rounded_extrude, transition_radius,
                             varied_edge_thickness)


@op("крюк", aliases=("крючок", "hook", "крюк_подвес", "вешалка_крюк"),
    category="Примитивы",
    summary="Крюк одной непрерывной линией без кольца: хвостик, соединитель "
            "и дуга. offset смещает дугу относительно хвостика, aspect делает "
            "её овальной, curve — боковой прогиб как у серпа. tip=острый или "
            "капсула; taper сужает только свободный кончик.",
    example="крюк = крюк wire=6 radius=22 length=70 open=240 tip=капсула\n"
            "острый = крюк wire=6 radius=24 length=60 open=250 tip=острый taper=.94\n"
            "смещённый = крюк wire=6 radius=22 length=70 offset=[12,8] curve=10 aspect=.8",
    params={"wire": "диаметр прутка, мм (6)",
            "radius": "радиус дуги по средней линии, мм (22)",
            "length": "высота хвостика до начала дуги, мм (70); при offset "
                      "его верхняя часть становится плавным сопряжением",
            "open": "угол дуги 45…350° (240)",
            "offset": "смещение начала дуги относительно хвостика [dx,dz], мм (0,0)",
            "aspect": "овальность дуги: радиус Z / радиус X, 0.35…2.5 (1)",
            "curve": "боковой прогиб дуги по Y в середине, мм (0)",
            "tip": "капсула — круглый торец; острый — суженное остриё",
            "taper": "сужение свободного кончика 0…0.98 при tip=острый (0.94)",
            "segments": "сегментов на полный круг дуги (авто)",
            "detail": "детализация сечения 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def hook(a, name):
    wire = float(a.num("wire", 6.0, minv=0.4, maxv=200.0))
    bend = float(a.num("radius", 22.0, minv=wire * 0.55, maxv=2000.0))
    length = float(a.num("length", 70.0, minv=0.0, maxv=5000.0))
    opening = float(a.num("open", 240.0, minv=45.0, maxv=350.0) or 240.0)
    offset = np.asarray(a.vec("offset", 2, default=(0.0, 0.0)), dtype=np.float64)
    aspect = float(a.num("aspect", 1.0, minv=0.35, maxv=2.5) or 1.0)
    curve = float(a.num("curve", 0.0, minv=-2000.0, maxv=2000.0) or 0.0)
    tip = (a.text("tip") or "капсула").strip().lower()
    if tip in ("острый", "остриё", "остро", "sharp", "point", "pointed"):
        tip = "острый"
    elif tip in ("капсула", "круглый", "круглая", "capsule", "round"):
        tip = "капсула"
    else:
        raise GeometryError("крюк: tip=капсула или острый.")
    taper = float(a.num("taper", 0.94, minv=0.0, maxv=0.98) or 0.0)
    detail = int(a.num("detail", 3, minv=0, maxv=5))
    asked = a.int("segments", None, minv=12, maxv=256)
    if asked is None:
        steps_arc = int(np.clip(24 * (1.0 + detail * 0.35) * opening / 180.0, 18, 180))
    else:
        steps_arc = max(8, int(round(asked * opening / 360.0)))
    at = a.vec("at", 3, default=(0.0, 0.0, 0.0))
    center = a.boolean("center", False)

    tail_top = np.array([0.0, 0.0, length])
    centre = np.array([bend + offset[0], 0.0, length + offset[1]])
    arc_start = np.array([offset[0], 0.0, length + offset[1]])
    delta = arc_start - tail_top
    end_tangent = np.array([0.0, curve * math.pi,
                            bend * aspect * math.radians(opening)])
    end_tangent /= max(float(np.linalg.norm(end_tangent)), 1e-12)
    if np.linalg.norm(delta) > 1e-8:
        # Не втискиваем S-образное сопряжение в короткую диагональ над
        # хвостиком. Для него резервируем достаточную часть length: обе
        # управляющие точки идут по возрастанию Z, поэтому петли и острого
        # перелома у начала дуги не возникает даже при почти нулевом dz.
        distance = float(np.linalg.norm(delta))
        handle = max(wire * 1.5, min(distance * 0.55, bend * 0.75))
        if length > 1e-9:
            required = handle * (1.0 + end_tangent[2]) - delta[2] + wire * 0.35
            join_h = min(length, max(2.0 * wire, abs(delta[0]) * 0.9, required))
            denominator = 1.0 + end_tangent[2]
            if denominator > 0.1:
                handle = min(handle, max(0.05,
                    (join_h + delta[2] - wire * 0.35) / denominator))
            straight = length - join_h
            p0 = np.array([0.0, 0.0, straight])
            if straight > 1e-9:
                tail_count = max(2, int(np.clip(6 + straight / max(wire, 0.1), 4, 60)))
                path = [p0 * (i / (tail_count - 1)) for i in range(tail_count)]
            else:
                path = [p0.copy()]
            p1 = p0 + np.array([0.0, 0.0, handle])
        else:
            p0 = tail_top
            path = [p0.copy()]
            p1 = p0 + delta / distance * handle
        p2 = arc_start - end_tangent * handle
        p3 = arc_start
        count = int(np.clip(16 + (distance + abs(delta[2])) / max(wire, 0.1), 16, 56))
        for i in range(1, count + 1):
            t = i / count
            q = 1.0 - t
            path.append(q ** 3 * p0 + 3 * q * q * t * p1
                        + 3 * q * t * t * p2 + t ** 3 * p3)
    else:
        if length > 1e-9:
            tail_count = max(2, int(np.clip(6 + length / max(wire, 0.1), 4, 60)))
            path = [tail_top * (i / (tail_count - 1)) for i in range(tail_count)]
        else:
            path = [tail_top.copy()]
    arc_index = len(path) - 1
    for i in range(1, steps_arc + 1):
        u = i / steps_arc
        ang = math.radians(180.0 - opening * u)
        path.append(np.array([centre[0] + bend * math.cos(ang),
                              curve * math.sin(math.pi * u),
                              centre[2] + bend * aspect * math.sin(ang)]))
    path = np.asarray(path, dtype=np.float64)
    scales = np.ones(len(path))
    if tip == "острый":
        for i in range(arc_index, len(path)):
            u = (i - arc_index) / max(1, len(path) - 1 - arc_index)
            q = min(1.0, max(0.0, (u - 0.52) / 0.48))
            q = q * q * (3.0 - 2.0 * q)
            scales[i] = 1.0 - taper * q
    seg = int(np.clip(10 + detail * 6, 12, 48))
    solid = sweep_solid(path, circle_profile(wire * 0.5, seg), what="крюка",
                        scale_curve=scales.tolist(),
                        round_caps=1.0 if tip == "капсула" else 0.0)
    solid = anchor(solid, at, center)
    a.scene.log("info", f"крюк: пруток {wire:g} мм, дуга {opening:g}°, "
                        f"tip={tip}, {solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    out = make_solid(a.scene, name, solid, a, kind="крюк")
    out.notes.append(f"крюк без кольца: offset={offset.tolist()}, aspect={aspect:g}, "
                     f"curve={curve:g}, tip={tip}")
    return out


@op("полуовал", aliases=("полуовальный", "полуэллипс", "half_oval", "semioval",
                        "пластина_полуовал", "ушко_пластина"),
    category="Примитивы",
    summary="Пластина-полуовал: снизу прямая кромка, сверху дуга эллипса. "
            "wall>0 вырезает объём изнутри и открывает полость с лицевой "
            "стороны: получается форма-лодочка, а не нарисованное углубление. "
            "отверстие hole остаётся независимым.",
    example="подвес = полуовал width=90 height=55 thickness=8 hole=16\n"
            "лодочка = полуовал width=160 height=90 thickness=24 wall=3 cavity_depth=19 plane=плашмя\n"
            "накладка = полуовал width=140 height=60 thickness=5 hole=0",
    params={"width": "ширина по прямой кромке, мм (120)",
            "height": "высота полуовала, мм (70)",
            "thickness": "толщина пластины, мм (8)",
            "wall": "толщина стенки и минимального дна, мм (0 — сплошной)",
            "cavity_depth": "глубина полости, мм (thickness − wall)",
            "hole": "диаметр отверстия, мм (0 — без отверстия)",
            "hole_y": "где отверстие по высоте, 0…1 от низа (0.45)",
            "edge": "толщина только эллиптической дуги, мм (= thickness)",
            "edge_band": "ширина перехода от дуги, мм (25% высоты)",
            "segments": "сегментов по дуге (по размеру)",
            "detail": "детализация дуги 0…5 (3)",
            "smooth": "ступени скругления наружных рёбер 0…4 (0); "
                      "широкие лицевые плоскости остаются плоскими",
            "plane": "фронт — стоит лицом к зрителю (дуга вверх), плашмя — "
                     "лежит лицом вверх — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по толщине"})
def half_oval(a, name):
    width = float(a.num("width", 120.0, minv=0.5, maxv=5000.0))
    height = float(a.num("height", 70.0, minv=0.5, maxv=5000.0))
    thickness = float(a.num("thickness", 8.0, minv=0.2, maxv=1000.0))
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    cavity_depth = float(a.num("cavity_depth", thickness - wall if wall > 0 else 0.0,
                               minv=0.0) or 0.0)
    if wall <= 1e-9 and cavity_depth > 1e-9:
        raise GeometryError("полуовал: cavity_depth требует wall>0.")
    edge = float(a.num("edge", thickness, minv=0.05))
    edge_band = float(a.num("edge_band", height * 0.25, minv=0.05))
    hole = float(a.num("hole", 0.0, minv=0.0, maxv=max(width, height)))
    hole_y = float(a.num("hole_y", 0.45, minv=0.12, maxv=0.88))
    detail = int(a.num("detail", 3, minv=0, maxv=5))
    at = a.vec("at", 3, default=(0.0, 0.0, 0.0))
    center = a.boolean("center", False)

    steps = int(np.clip(24 * (1.0 + 0.45 * detail), 24, 160))
    ts = np.linspace(0.0, math.pi, steps)
    arc = np.stack([width * 0.5 * np.cos(ts), height * np.sin(ts)], axis=1)
    cs = mf.CrossSection([arc])
    edge_r = transition_radius(a, min(thickness * 0.45, height * 0.08, width * 0.04))
    # Скругляем только наружный контур до сверления: отверстие и обе
    # широкие лицевые плоскости не подвергаются Loop-деформации.
    solid = rounded_extrude(cs, thickness, edge_r, "полуовал")
    solid = open_top_cavity(solid, cs, thickness, wall, cavity_depth, "полуовал")
    if abs(edge - thickness) > 1e-9:
        def only_ellipse_arc(points):
            x, y = points[:, 0], points[:, 1]
            q = np.sqrt((x / (width * 0.5)) ** 2 + (y / height) ** 2)
            ray_radius = np.where(q > 1e-12, np.hypot(x, y) / np.maximum(q, 1e-12),
                                  max(width * 0.5, height))
            distance = np.maximum(0.0, 1.0 - q) * ray_radius
            radial = np.clip(1.0 - distance / edge_band, 0.0, 1.0)
            theta = np.arctan2(y / height, x / (width * 0.5))
            fade = np.clip(np.sin(theta) * 5.0, 0.0, 1.0)
            return radial * fade

        solid = varied_edge_thickness(solid, thickness, edge, edge_band,
                                      only_ellipse_arc, "полуовал с профилем дуги")

    if hole > 1e-6:
        # отверстие не должно выходить за кромку: держим стенку не меньше
        # 2.5 мм до дуги и до прямой кромки
        cy = height * hole_y
        room = min(width * 0.5, cy, height - cy)
        allowed = max(0.0, room * 1.55)
        if hole > allowed:
            hole = allowed
            a.scene.log("warn", f"полуовал: отверстие уменьшено до {hole:g} мм, "
                                "иначе оно вышло бы за кромку.", a.cmd.line)
        if hole > 0.4:
            seg = int(np.clip(round(2 * math.pi * hole / 0.6), 24, 200))
            cutter = mf.Manifold.cylinder(thickness * 2 + 4, hole * 0.5, hole * 0.5, seg)
            cutter = cutter.translate((0.0, cy, -thickness * 0.5 - 2.0))
            solid = solid - cutter

    solid = stand_flat_sign(a, solid)     # по правилу: лицо −Y, купол вверх +Z
    solid = anchor(solid, at, center)
    a.scene.log("info", f"полуовал: {width:g}×{height:g}×{thickness:g} мм, "
                        f"отверстие {hole:g} мм", a.cmd.line)
    saved = make_solid(a.scene, name, solid, a, kind="полуовал")
    saved.notes.append(f"полуовал {width:g}×{height:g}, отверстие {hole:g} мм")
    if wall > 0:
        saved.meta.update(wall=wall, cavity_depth=cavity_depth, cavity="открыта с лицевой стороны")
        saved.notes.append(f"полость {cavity_depth:g} мм, стенка/дно ≥ {wall:g} мм")
    return saved
