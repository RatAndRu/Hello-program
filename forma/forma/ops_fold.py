"""Складывание бумаги и заломы ткани.

`fold` умеет складывать лист пополам, на треть и гармошкой, но линия сгиба
всегда идёт вдоль оси и делит деталь на равные части. Настоящее оригами так
не работает: сгиб идёт от угла, по диагонали, под любым углом к краю, а вторая
половина уезжает на произвольный угол — и лист при этом не тянется.

* `сгиб` — жёсткий поворот одной части вокруг произвольной линии. Деталь
  разрезается плоскостью по линии, подвижная сторона поворачивается как на
  шарнире. Длина сохраняется: это изометрия, как с настоящей бумагой.
* `складка` — след сгиба на поверхности: валик (гребень) или канавка по линии.
  Именно это делает одежду одеждой — заломы у локтя, складки на юбке, рёбра
  на бумаге. Ставится на готовую деталь и либо приращивает валик, либо
  вычитает канавку.

    лист = sheet width=120 length=160 thickness=1
    сгиб лист at=[-60,-80,1] dir=45 angle=135

    куртка = box size=[80,40,120] round=6
    складка куртка from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, sweep_solid
from .ops import make_solid, op


def _one(a, command: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{command} работает с одним объектом.",
                            hint=f"Формат: имя = {command} [объект] …")
    return solids[0]


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise GeometryError("Нулевое направление.", hint="Задайте другое dir/линию.")
    return v / n


def _rotate_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    """Матрица поворота вокруг единичной оси на angle радиан (Родриг)."""
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    k = 1.0 - c
    return np.array([
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ], dtype=np.float64)


@op("сгиб", aliases=("fold_line", "сложить_по_линии", "перегиб", "origami_fold",
                     "согнуть_по_линии", "fold_along"),
    category="Форма и деформации",
    summary="Складывает деталь по произвольной линии — от угла, по диагонали, "
            "под любым углом к краю. Линия задаётся точкой at и углом dir в "
            "плоскости листа, поворот — на angle градусов. Лист разрезается по "
            "линии, подвижная сторона поворачивается как на шарнире, поэтому "
            "длина не меняется: это честная изометрия, как с бумагой.",
    example="лист = sheet width=120 length=160 thickness=1\n"
            "сгиб лист at=[-60,-80,1] dir=45 angle=135\n"
            "квадрат = sheet width=140 length=140 thickness=1\n"
            "сгиб квадрат at=[-70,-70,1] dir=45 angle=90 side=-1",
    params={"objects": "объект [a] или a",
            "at": "точка на линии сгиба [x,y,z] (центр, верх листа)",
            "dir": "направление линии в плоскости листа, градусы от +X (0)",
            "angle": "угол сгиба, 1…180 (90): 180 — совсем пополам",
            "side": "какая сторона поворачивается: 1 или −1 (1)",
            "gap": "просвет между слоями, мм (толщина листа)",
            "normal": "нормаль листа [x,y,z] (тонкая сторона габарита)",
            "center": "центрировать деталь на at не нужно: at — точка линии"},
    positional=["objects"])
def fold_along(a, name):
    base = _one(a, "сгиб")
    m = base.manifold
    bb = m.bounding_box()
    ext = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=np.float64)
    if float(ext.max()) < 1e-6:
        raise GeometryError("Деталь пустая.")

    normal = a.vec("normal", 3, default=None)
    if normal is not None:
        up_vec = _unit(normal)
        up = int(np.argmax(np.abs(up_vec)))
    else:
        up = int(np.argmin(ext))
        up_vec = np.zeros(3)
        up_vec[up] = 1.0
    others = [i for i in range(3) if i != up]
    up_vec = np.zeros(3)
    up_vec[up] = 1.0
    a1, a2 = others[0], others[1]

    center = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)], dtype=np.float64)
    center[up] = bb[up + 3]                       # линия идёт по верхней поверхности
    at = a.vec("at", 3, default=None)
    point = center if at is None else np.asarray(at, dtype=np.float64).reshape(3)

    deg = float(a.num("dir", 0.0))
    rad = math.radians(deg)
    d = np.zeros(3)
    d[a1] = math.cos(rad)
    d[a2] = math.sin(rad)
    nrm = np.zeros(3)
    nrm[a1] = -math.sin(rad)
    nrm[a2] = math.cos(rad)

    angle = float(a.num("angle", 90.0, minv=1.0, maxv=180.0))
    side = float(a.num("side", 1.0))
    gap = a.num("gap", None, minv=0.0)
    gap = float(gap) if gap is not None else float(ext[up])
    thin = max(float(ext[up]), 1e-3)

    # Разрез по плоскости, содержащей нормаль листа и линию сгиба.
    offset = float(np.dot(point, nrm))
    try:
        moving, keep = m.split_by_plane(tuple(nrm), offset)
    except Exception as exc:                          # pragma: no cover
        raise GeometryError(f"Не удалось разрезать деталь по линии: {exc}",
                            hint="Проверьте at и dir — линия должна пересекать деталь.")
    if side < 0:
        moving, keep = keep, moving
    if moving.is_empty() or keep.is_empty():
        raise GeometryError("Линия сгиба не пересекает деталь.",
                            hint="Линия бесконечная: важна только точка at поперёк "
                                 "линии. Сдвиньте at внутрь детали или поменяйте side.")

    # Куда поворачивать: подвижная часть должна подниматься вверх (по нормали),
    # поэтому знак зависит и от направления линии, и от того, какая половина
    # подвижная: иначе одна из сторон складывалась бы сквозь стол.
    lift = np.cross(d, nrm)
    sign = 1.0 if float(np.dot(lift, up_vec)) >= 0.0 else -1.0
    mb = moving.bounding_box()
    m_center = np.array([(mb[i] + mb[i + 3]) * 0.5 for i in range(3)])
    across = float(np.dot(m_center - point, nrm))
    if abs(across) > 1e-6:
        sign *= 1.0 if across > 0 else -1.0
    theta = sign * math.radians(angle)

    rot = _rotate_matrix(d, theta)
    shift = point - rot @ point
    shift[up] += gap if angle > 90.0 else 0.0
    matrix = np.hstack([rot, shift.reshape(3, 1)])
    moved = moving.transform(np.ascontiguousarray(matrix, dtype=np.float64))
    solid = mf.Manifold.batch_boolean([keep, moved], mf.OpType.Add)

    a.scene.log("info",
                f"сгиб: линия {deg:g}°, поворот {angle:g}°, толщина {thin:g} мм",
                a.cmd.line)
    return make_solid(a.scene, name, solid, a, base=base, kind="fold")


@op("складка", aliases=("crease", "залом", "фалда", "cloth_fold", "сгиб_ткани",
                        "залом_ткани"),
    category="Форма и деформации",
    summary="След сгиба на поверхности: валик-гребень (mode=гребень) или канавка "
            "(mode=канавка) по линии from→to. bend изгибает линию, taper сужает "
            "края — складка выходит живой, как на одежде, а не по линейке. "
            "Ставится на готовую деталь: куртку, юбку, бумажную фигуру.",
    example="куртка = box size=[80,40,120] round=6\n"
            "складка куртка from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка\n"
            "складка куртка from=[-26,-20,30] to=[30,-20,40] r=4 bend=8\n"
            "лист = sheet width=160 length=120 thickness=1\n"
            "складка лист from=[-80,0,1] to=[80,0,1] r=2.2 mode=канавка",
    params={"objects": "объект [a] или a",
            "from": "начало складки [x,y,z]",
            "to": "конец складки [x,y,z]",
            "r": "радиус валика, мм (4)",
            "mode": "гребень (приращивает) или канавка (вырезает) — гребень",
            "bend": "изгиб линии, мм (0): плюс — вверх, минус — вниз",
            "taper": "сузить концы, 0…1 (0.35)",
            "smooth": "гладкость сечения (24)"},
    positional=["objects"])
def crease(a, name):
    base = _one(a, "складка")
    p0 = np.asarray(a.vec("from", 3), dtype=np.float64).reshape(3)
    p1 = np.asarray(a.vec("to", 3), dtype=np.float64).reshape(3)
    r = float(a.num("r", 4.0, minv=0.2, maxv=200.0))
    mode = (a.text("mode") or "гребень").strip().lower()
    groove = mode.startswith("канав") or mode in ("groove", "cut", "вырез")
    bend = float(a.num("bend", 0.0, minv=-200.0, maxv=200.0))
    taper = float(a.num("taper", 0.35, minv=0.0, maxv=0.95))
    smooth = int(a.num("smooth", 24, minv=6, maxv=64))

    span = p1 - p0
    length = float(np.linalg.norm(span))
    if length < 1e-6:
        raise GeometryError("Начало и конец складки совпали.",
                            hint="Разведите from и to.")
    d = span / length
    up_ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(d, up_ref))) > 0.95:
        up_ref = np.array([1.0, 0.0, 0.0])
    perp = _unit(np.cross(d, up_ref))

    steps = 15
    ts = np.linspace(0.0, 1.0, steps)
    bulge = 4.0 * (ts - ts * ts) * bend          # парабола: 0 на концах
    path = p0[None, :] + ts[:, None] * span[None, :] + perp[None, :] * bulge[:, None]

    # taper: валик толще в середине, к концам сходит на нет
    k = np.sin(np.pi * np.clip(ts, 0.0, 1.0)) ** 0.6
    curve = (1.0 - taper) + taper * k
    curve = np.clip(curve, 0.05, 1.0)
    prof = circle_profile(r, smooth)
    ridge = sweep_solid(path, prof, what="складки", scale_curve=curve.tolist(),
                        round_caps=0.6)

    if groove:
        solid = mf.Manifold.batch_boolean([base.manifold, ridge], mf.OpType.Subtract)
    else:
        solid = mf.Manifold.batch_boolean([base.manifold, ridge], mf.OpType.Add)
    a.scene.log("info",
                f"складка: {length:.0f} мм, r={r:g}, "
                f"{'канавка' if groove else 'гребень'}", a.cmd.line)
    return make_solid(a.scene, name, solid, a, base=base, kind="crease")
