"""Крюк и полуовальная пластина — мелкая фурнитура, которой не хватало.

* `крюк` — гнутый из прутка крючок: прямой хвост, загиб на 90…330° и, если
  нужно, ушко на конце хвоста. Одна деталь, а не «палка + тор»: изгиб
  разворачивается по настоящей дуге, поэтому и вешалка, и крючок для сумки
  получаются одинаково честными.
* `полуовал` — плоская пластина-полуовал: снизу прямая кромка, сверху дуга
  эллипса. Отверстие по центру можно сделать, а можно и не делать (`hole=0`):
  это и подвес, и подпятник, и накладка, и ушко.

    крюк = крюк wire=6 radius=22 length=70 open=240 eye=да
    подвес = полуовал width=90 height=55 thickness=8 hole=16
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, sweep_solid
from .ops import anchor, make_solid, op, stand_flat_sign


def _ring(major: float, minor: float, seg: int, mseg: int) -> mf.Manifold:
    """Кольцо (тор) по средней линии в плоскости XY."""
    prof = circle_profile(minor, mseg) + np.array([major, 0.0])
    return mf.Manifold.revolve(mf.CrossSection([prof]), seg)


@op("крюк", aliases=("крючок", "hook", "крюк_подвес", "вешалка_крюк", "hook_eye"),
    category="Примитивы",
    summary="Крюк из гнутого прутка: прямой хвост, дуга загиба и ушко на конце "
            "хвоста (можно выключить). Угол загиба задаётся: 180° — как у "
            "крючка для сумки, 270° — как у вешалки, 90° — крючок-кронштейн. "
            "Пруток круглый, торец скруглён.",
    example="крюк = крюк wire=6 radius=22 length=70 open=240 eye=да\n"
            "вешалка = крюк wire=8 radius=30 length=90 open=270 eye=нет\n"
            "кронштейн = крюк wire=10 radius=18 length=40 open=90 at=[0,0,120]",
    params={"wire": "толщина прутка, мм (6)",
            "radius": "радиус изгиба по средней линии, мм (22)",
            "length": "длина прямого хвоста, мм (70)",
            "open": "угол загиба, градусы: 90…330 (240)",
            "eye": "ушко-кольцо на конце хвоста, да/нет (да)",
            "eye_radius": "радиус ушка по средней линии, мм (1.6·wire)",
            "segments": "сегментов по дуге и кольцу (по размеру)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def hook(a, name):
    wire = float(a.num("wire", 6.0, minv=0.4, maxv=200.0))
    bend = float(a.num("radius", 22.0, minv=wire * 0.55, maxv=2000.0))
    length = float(a.num("length", 70.0, minv=0.0, maxv=5000.0))
    opening = float(a.num("open", 240.0, minv=90.0, maxv=330.0) or 240.0)
    eye = a.boolean("eye", True)
    eye_r = float(a.num("eye_radius", wire * 1.6, minv=wire * 0.6, maxv=bend * 1.5))
    detail = int(a.num("detail", 3, minv=0, maxv=5))
    at = a.vec("at", 3, default=(0.0, 0.0, 0.0))
    center = a.boolean("center", False)

    if length <= 1e-6 and not eye:
        raise GeometryError("крюк: нечего строить — хвост нулевой, ушко выключено.",
                            hint="Задайте length больше нуля или eye=да.")

    steps_arc = int(np.clip(24 * (1.0 + detail * 0.35) * opening / 180.0, 18, 180))
    path = []
    tail = max(2, int(np.clip(6 + length / max(wire, 0.1), 4, 60)))
    for i in range(tail):
        path.append([0.0, 0.0, length * i / (tail - 1)])
    # дуга начинается в верхней точке хвоста и идёт по часовой стрелке в XZ
    centre = np.array([bend, 0.0, length])
    for i in range(1, steps_arc + 1):
        ang = math.radians(180.0 - opening * i / steps_arc)
        path.append([centre[0] + bend * math.cos(ang), 0.0,
                     centre[2] + bend * math.sin(ang)])
    path = np.asarray(path, dtype=np.float64)

    seg = int(np.clip(10 + detail * 6, 12, 48))
    rod = sweep_solid(path, circle_profile(wire * 0.5, seg), what="крюка",
                      round_caps=1.0)
    parts = [rod]

    if eye:
        ring_seg = int(np.clip(round(2 * math.pi * eye_r / max(wire * 0.35, 0.4)),
                               24, 160))
        mseg = int(np.clip(8 + detail * 3, 8, 28))
        ring = _ring(eye_r, wire * 0.5, ring_seg, mseg)
        # ушко встаёт в плоскость крюка (XZ) и входит в хвост нижним концом
        ring = ring.rotate((90.0, 0.0, 0.0)).translate((0.0, 0.0, -eye_r * 0.6))
        parts.append(ring)

    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    solid = anchor(solid, at, center)
    a.scene.log("info", f"крюк: пруток {wire:g} мм, загиб {opening:g}°, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="крюк")


@op("полуовал", aliases=("полуовальный", "полуэллипс", "half_oval", "semioval",
                        "пластина_полуовал", "ушко_пластина"),
    category="Примитивы",
    summary="Плоская пластина-полуовал: снизу прямая кромка, сверху дуга "
            "эллипса; по центру можно сделать круглое отверстие, а можно "
            "оставить сплошной. Подвес, накладка, подпятник, ушко, шильдик.",
    example="подвес = полуовал width=90 height=55 thickness=8 hole=16\n"
            "накладка = полуовал width=140 height=60 thickness=5 hole=0\n"
            "ушко = полуовал width=40 height=24 thickness=4 hole=10 at=[0,0,80]",
    params={"width": "ширина по прямой кромке, мм (120)",
            "height": "высота полуовала, мм (70)",
            "thickness": "толщина пластины, мм (8)",
            "hole": "диаметр отверстия, мм (0 — без отверстия)",
            "hole_y": "где отверстие по высоте, 0…1 от низа (0.45)",
            "segments": "сегментов по дуге (по размеру)",
            "detail": "детализация дуги 0…5 (3)",
            "plane": "фронт — стоит лицом к зрителю (дуга вверх), плашмя — "
                     "лежит лицом вверх — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по толщине"})
def half_oval(a, name):
    width = float(a.num("width", 120.0, minv=0.5, maxv=5000.0))
    height = float(a.num("height", 70.0, minv=0.5, maxv=5000.0))
    thickness = float(a.num("thickness", 8.0, minv=0.2, maxv=1000.0))
    hole = float(a.num("hole", 0.0, minv=0.0, maxv=max(width, height)))
    hole_y = float(a.num("hole_y", 0.45, minv=0.12, maxv=0.88))
    detail = int(a.num("detail", 3, minv=0, maxv=5))
    at = a.vec("at", 3, default=(0.0, 0.0, 0.0))
    center = a.boolean("center", False)

    steps = int(np.clip(24 * (1.0 + 0.45 * detail), 24, 160))
    ts = np.linspace(0.0, math.pi, steps)
    arc = np.stack([width * 0.5 * np.cos(ts), height * np.sin(ts)], axis=1)
    cs = mf.CrossSection([arc])
    solid = cs.extrude(thickness)

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
    return saved
