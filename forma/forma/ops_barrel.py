"""Геометрическая бочка с интегрированным боковым рельефом."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays
from .ops import anchor, make_solid, op


def _choice(raw: str, table: dict[str, str], what: str) -> str:
    value = table.get((raw or "").strip().lower())
    if value is None:
        raise GeometryError(f"{what}: неизвестное значение «{raw}».")
    return value


def _relief_profile(kind: str, u: np.ndarray) -> np.ndarray:
    """Профиль внутри одной ячейки; u=0 — центр, |u|=1 — край."""
    q = np.clip(np.abs(u), 0.0, 1.0)
    if kind == "круглые":
        return np.sqrt(np.maximum(0.0, 1.0 - q * q))
    if kind == "прямоугольные":
        return (q < 1.0).astype(float)
    if kind == "треугольные":
        return 1.0 - q
    # Плоская середина и два прямых ската — отдельная трапециевидная форма,
    # а не переименованный треугольник.
    return np.clip((1.0 - q) / 0.55, 0.0, 1.0)


def _barrel_mesh(radius: float, end_radius: float, height: float, bulge: float,
                 segments: int, rings: int, relief: str, shape: str, count: int,
                 depth: float, width: float, dashed: bool, dash_count: int,
                 dash_duty: float, rim_top: float, rim_bottom: float,
                 rim_top_h: float, rim_bottom_h: float) -> mf.Manifold:
    n = max(12, int(segments))
    if relief != "нет":
        # Для прямоугольников и пунктира нужны настоящие вершины на краях,
        # иначе профиль превращается в случайные диагональные треугольники.
        n = max(n, count * 8)
        n = int(math.ceil(n / count) * count)
    rows = max(8, int(rings))
    if dashed:
        rows = max(rows, dash_count * 8)
    rows = min(512, rows)
    angles = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    verts: list[tuple[float, float, float]] = []
    for j in range(rows + 1):
        t = j / rows
        z = height * t
        # Параболическая выпуклость: плоские торцы, одна гладкая бочкообразная
        # боковая поверхность, без повторяющихся «колец» реалистичной бочки.
        arch = max(0.0, 1.0 - (2.0 * t - 1.0) ** 2) ** bulge
        base_r = end_radius + (radius - end_radius) * arch
        rim = 0.0
        if rim_bottom > 0 and rim_bottom_h > 1e-9 and z < rim_bottom_h:
            q = 1.0 - z / rim_bottom_h
            rim += rim_bottom * (q * q * (3.0 - 2.0 * q))
        if rim_top > 0 and rim_top_h > 1e-9 and z > height - rim_top_h:
            q = 1.0 - (height - z) / rim_top_h
            rim += rim_top * (q * q * (3.0 - 2.0 * q))
        for angle in angles:
            displacement = 0.0
            if relief != "нет" and 0.0 < t < 1.0:
                cell = 2.0 * math.pi / count
                # Расстояние до ближайшего центра борозды/холмика.
                dist = (angle + cell * 0.5) % cell - cell * 0.5
                u = dist / (cell * width * 0.5)
                if abs(u) <= 1.0:
                    active = 1.0
                    if dashed:
                        phase = (t * dash_count) % 1.0
                        active = 1.0 if phase < dash_duty else 0.0
                    if active:
                        fade = min(1.0, t / 0.055, (1.0 - t) / 0.055)
                        displacement = (1.0 if relief == "холмики" else -1.0) * depth * float(
                            _relief_profile(shape, np.asarray([u]))[0]) * active * fade
            rr = max(0.05, base_r + rim + displacement)
            verts.append((rr * math.cos(angle), rr * math.sin(angle), z))
    faces: list[tuple[int, int, int]] = []
    for j in range(rows):
        for i in range(n):
            k = (i + 1) % n
            a, b = j * n + i, j * n + k
            c, d = (j + 1) * n + k, (j + 1) * n + i
            faces.extend(((a, b, c), (a, c, d)))
    bottom = len(verts)
    verts.append((0.0, 0.0, 0.0))
    top = len(verts)
    verts.append((0.0, 0.0, height))
    for i in range(n):
        k = (i + 1) % n
        faces.append((bottom, k, i))
        a, b = rows * n + i, rows * n + k
        faces.append((top, a, b))
    varr = np.asarray(verts, dtype=np.float64)
    farr = np.asarray(faces, dtype=np.int64)
    p0, p1, p2 = varr[farr[:, 0]], varr[farr[:, 1]], varr[farr[:, 2]]
    signed = float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6.0)
    if signed < 0:
        farr = farr[:, ::-1]
    solid = manifold_from_arrays(varr, farr, "бочки")
    if solid.is_empty() or solid.status() != mf.Error.NoError or solid.volume() <= 1e-8:
        raise GeometryError("Не удалось построить замкнутую бочку с боковым рельефом.")
    return solid


@op("barrel", aliases=("бочка", "бочонок", "barrel_shape"), category="Примитивы",
    summary="Выпуклая геометрическая бочка с плоскими верхом и дном. relief=борозды "
            "вдавливает боковые линии, relief=холмики выводит их наружу; shape "
            "выбирает круглый, прямоугольный, треугольный или трапециевидный "
            "профиль. dashed=да делает прерывистый пунктир, а rim_top/rim_bottom "
            "и их высоты управляют бортиками. Всё строится одной сеткой.",
    example="бочка = barrel radius=60 height=120 end_radius=46\n"
            "борозды = barrel radius=60 height=120 relief=борозды shape=треугольные groove_count=16 groove_depth=2\n"
            "пунктир = barrel radius=60 height=120 relief=холмики shape=круглые dashed=да dash_count=5 rim=4",
    params={"radius": "максимальный радиус выпуклой части, мм (60)",
            "height": "полная высота между плоскими торцами, мм (120)",
            "end_radius": "радиус плоского верха и дна, мм (0.78·radius)",
            "end": "синоним end_radius",
            "bulge": "показатель выпуклости 0.35…3 (1 — парабола)",
            "segments": "сегментов по окружности (64)",
            "rings": "рядов по высоте (24)",
            "relief": "нет, борозды или холмики (нет)",
            "mode": "синоним relief",
            "shape": "круглые, прямоугольные, треугольные или трапециевидные",
            "groove_shape": "форма борозд (синоним shape)",
            "bump_shape": "форма холмиков; если не задана — shape",
            "groove_count": "число линий по окружности (12)",
            "count": "синоним groove_count",
            "groove_depth": "глубина борозды/высота холмика, мм (1.5)",
            "depth": "синоним groove_depth",
            "groove_width": "ширина профиля в доле ячейки 0.02…0.98 (0.42)",
            "width": "синоним groove_width",
            "dashed": "да — прерывистые участки вместо сплошных линий",
            "dash": "пунктир или нет (текстовый синоним dashed)",
            "dash_count": "число пунктирных периодов по высоте (4)",
            "dash_duty": "доля видимой части периода 0.05…1 (0.58)",
            "rim": "одинаковый радиальный бортик сверху и снизу, мм (0)",
            "rim_top": "бортик сверху, мм (0)",
            "rim_bottom": "бортик снизу, мм (0)",
            "rim_height": "общая высота обоих бортиков, мм (6)",
            "rim_top_height": "высота верхнего бортика, мм",
            "rim_bottom_height": "высота нижнего бортика, мм",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius", "height"])
def barrel(a, name):
    radius = float(a.num("radius", 60.0, minv=1.0, maxv=100000.0))
    height = float(a.num("height", 120.0, minv=1.0, maxv=100000.0))
    end_radius = float(a.num("end_radius", a.num("end", radius * 0.78, minv=0.2), minv=0.2))
    if end_radius > radius:
        raise GeometryError("end_radius не должен быть больше максимального radius бочки.")
    bulge = float(a.num("bulge", 1.0, minv=0.35, maxv=3.0))
    segments = int(a.int("segments", 64, minv=12, maxv=512) or 64)
    rings = int(a.int("rings", 24, minv=8, maxv=512) or 24)
    relief_raw = a.text("relief", a.text("mode", "нет")) or "нет"
    relief = _choice(relief_raw, {"нет": "нет", "no": "нет", "none": "нет",
                                  "борозды": "борозды", "борозда": "борозды", "канавки": "борозды",
                                  "grooves": "борозды", "groove": "борозды",
                                  "холмики": "холмики", "холмик": "холмики", "наросты": "холмики",
                                  "bumps": "холмики", "bump": "холмики"}, "barrel.relief")
    shape_raw = a.text("shape", "круглые") or "круглые"
    groove_shape = a.text("groove_shape", shape_raw) or shape_raw
    bump_shape = a.text("bump_shape", shape_raw) or shape_raw
    shape = _choice(bump_shape if relief == "холмики" else groove_shape,
                    {"круглые": "круглые", "круглая": "круглые", "круг": "круглые", "round": "круглые",
                     "прямоугольные": "прямоугольные", "прямоугольная": "прямоугольные", "rect": "прямоугольные",
                     "треугольные": "треугольные", "треугольная": "треугольные", "triangle": "треугольные",
                     "трапециевидные": "трапециевидные", "трапецивидные": "трапециевидные",
                     "трапеция": "трапециевидные", "trapezoid": "трапециевидные"}, "barrel.shape")
    count = int(a.int("groove_count", a.int("count", 12, minv=1, maxv=256), minv=1, maxv=256) or 12)
    depth = float(a.num("groove_depth", a.num("depth", 1.5, minv=0.0), minv=0.0) or 0.0)
    width = float(a.num("groove_width", a.num("width", 0.42, minv=0.02, maxv=0.98),
                        minv=0.02, maxv=0.98))
    dashed = a.boolean("dashed", False) or (a.text("dash", "нет") or "нет").strip().lower() in {
        "да", "пунктир", "dashed", "yes", "true", "1"}
    dash_count = int(a.int("dash_count", 4, minv=1, maxv=128) or 4)
    dash_duty = float(a.num("dash_duty", 0.58, minv=0.05, maxv=1.0))
    if relief != "нет" and depth <= 1e-9:
        raise GeometryError("Для бокового рельефа задайте groove_depth>0.")
    if depth > radius * 0.45:
        raise GeometryError("groove_depth слишком велик для радиуса бочки.")
    rim = float(a.num("rim", 0.0, minv=0.0) or 0.0)
    rim_top = float(a.num("rim_top", rim, minv=0.0) or 0.0)
    rim_bottom = float(a.num("rim_bottom", rim, minv=0.0) or 0.0)
    rim_h = float(a.num("rim_height", 6.0, minv=0.1))
    rim_top_h = float(a.num("rim_top_height", rim_h, minv=0.1))
    rim_bottom_h = float(a.num("rim_bottom_height", rim_h, minv=0.1))
    if max(rim_top_h, rim_bottom_h) >= height * 0.48 and (rim_top > 0 or rim_bottom > 0):
        raise GeometryError("Высота бортика должна оставлять выпуклую боковую часть бочки.")
    solid = _barrel_mesh(radius, end_radius, height, bulge, segments, rings, relief,
                         shape, count, depth, width, dashed, dash_count, dash_duty,
                         rim_top, rim_bottom, rim_top_h, rim_bottom_h)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="barrel")
    out.meta.update(relief=relief, relief_shape=shape, groove_count=count,
                    dashed=dashed, rim_top=rim_top, rim_bottom=rim_bottom)
    out.notes.append(f"бочка: плоские торцы ø{2 * end_radius:g}, максимум ø{2 * radius:g}, "
                     f"relief={relief}, shape={shape}, пунктир={'да' if dashed else 'нет'}")
    return out
