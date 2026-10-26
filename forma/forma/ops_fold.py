"""Сгибы листа и складки на исходной поверхности.

* `сгиб` поворачивает часть исходного листа вокруг произвольной линии, в том
  числе диагональной и проходящей через угол. `parts>2` делает гармошку. Лист
  не разрезается на независимые пластины и не дополняется новой плоскостью:
  его собственная разбираемая сетка непрерывно отображается на прямые участки
  и дуги сгибов.
* `складка` деформирует готовую поверхность: выдавливает настоящий гребень
  либо вдавливает канавку по линии from→to. Никаких прибавленных полуколец
  и вычитаемых трубок — меняются вершины самой детали.

    лист = sheet width=120 length=160 thickness=1
    сгиб лист at=[-60,-80,1] dir=45 angle=135

    ткань = box size=[80,40,120] round=6
    складка ткань from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import make_solid, op


def _one(a, command: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{command} работает с одним объектом.",
                            hint=f"Формат: имя = {command} [объект] …")
    return solids[0]


def _derived(a, name, solid, base, kind):
    out = make_solid(a.scene, name or base.name, solid, a, base=base, kind=kind)
    a.scene.consume(base)
    return out


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise GeometryError("Нулевое направление.", hint="Задайте другое dir/линию.")
    return v / n


@op("сгиб", aliases=("fold_line", "сложить_по_линии", "перегиб", "origami_fold",
                     "согнуть_по_линии", "fold_along"),
    category="Форма и деформации",
    summary="Сгибает исходный лист по произвольной линии — от угла, по "
            "диагонали, под любым углом к краю. at задаёт точку линии, dir — "
            "её направление в плоскости, angle — поворот от плоского состояния. "
            "parts=2 — один сгиб с выбором подвижной стороны; parts=3…12 — "
            "гармошка с равными плоскими полотнищами. Это деформация собственной "
            "сетки листа, без добавления второй плоскости сверху.",
    example="лист = sheet width=120 length=160 thickness=1\n"
            "сгиб лист at=[-60,-80,1] dir=45 angle=135\n"
            "гармошка = sheet width=140 length=300 thickness=1\n"
            "сгиб гармошка at=[0,0,1] dir=0 parts=6 angle=150 gap=1",
    params={"objects": "объект [a] или a",
            "at": "точка на линии сгиба [x,y,z] (центр, верх листа)",
            "dir": "направление линии в плоскости листа, градусы от +X (0)",
            "angle": "поворот каждого сгиба от плоского состояния, 1…180 (90)",
            "parts": "2 — один сгиб; 3…12 — гармошка (2)",
            "side": "при одиночном сгибе подвижная сторона: 1 или −1 (1)",
            "gap": "просвет между слоями, мм (половина толщины листа)",
            "sharp": "острота сгиба 0…1 (0)",
            "joint": "круг, широкая, сплайн или фаска — профиль дуги сгиба",
            "normal": "нормаль листа [x,y,z] (тонкая сторона габарита)"},
    positional=["objects"])
def fold_along(a, name):
    # Импорт локальный: ops_sheet содержит общий проверенный путь гармошки,
    # а модуль складок загружается после него.
    from .ops_sheet import _accordion_path, _fold_joint, _refine_for

    base = _one(a, "сгиб")
    m = base.manifold
    bb = m.bounding_box()
    ext = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=np.float64)
    if float(ext.max()) < 1e-6:
        raise GeometryError("Деталь пустая.")

    normal = a.vec("normal", 3, default=None)
    if normal is not None:
        up = int(np.argmax(np.abs(_unit(normal))))
    else:
        up = int(np.argmin(ext))
    up_vec = np.zeros(3)
    up_vec[up] = 1.0
    a1, a2 = [i for i in range(3) if i != up]

    center = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)], dtype=np.float64)
    center[up] = bb[up + 3]
    at = a.vec("at", 3, default=None)
    point = center if at is None else np.asarray(at, dtype=np.float64).reshape(3)
    # Толщину откладываем от нижней поверхности. Заданная пользователем z
    # точки по-прежнему описывает линию на верхнем листе, но не сдвигает её
    # в плоскости, потому что nrm и d перпендикулярны up_vec.
    origin = point.copy()
    origin[up] = bb[up]

    deg = float(a.num("dir", 0.0))
    rad = math.radians(deg)
    d = np.zeros(3)
    d[a1], d[a2] = math.cos(rad), math.sin(rad)
    nrm = np.zeros(3)
    nrm[a1], nrm[a2] = -math.sin(rad), math.cos(rad)

    angle = float(a.num("angle", 90.0, minv=1.0, maxv=180.0))
    parts = int(a.num("parts", 2, minv=2, maxv=12))
    side = 1.0 if float(a.num("side", 1.0)) >= 0 else -1.0
    thin = max(float(ext[up]), 1e-3)
    gap = float(a.num("gap", thin * 0.5, minv=0.0) or 0.0)
    sharp = float(a.num("sharp", 0.0, minv=0.0, maxv=1.0) or 0.0)
    joint = _fold_joint(a)

    # Проецируем углы габарита на нормаль к линии: так проверка пересечения
    # работает и для диагонали, и для произвольно повёрнутого листа.
    corners = np.array([[bb[0] if i & 1 else bb[3],
                         bb[1] if i & 2 else bb[4],
                         bb[2] if i & 4 else bb[5]] for i in range(8)])
    q_corners = side * ((corners - origin) @ nrm)
    lo, hi = float(q_corners.min()), float(q_corners.max())
    if lo > 1e-6 or hi < -1e-6:
        raise GeometryError("Линия сгиба не пересекает деталь.",
                            hint="Сдвиньте at внутрь детали или измените dir.")
    span = hi - lo
    if span < 1e-6:
        raise GeometryError("У детали нет длины поперёк линии сгиба.")
    offset = float(np.clip(-lo / span, 0.0, 1.0))

    ps, pu, pz, pt, radius, panel = _accordion_path(
        span, parts, angle, gap, sharp, thin, offset, joint)
    refine = max(0.08, min(radius / 2.5, max(panel, radius) / 14.0))
    fine = m.refine_to_length(_refine_for(m, refine))
    verts, faces = manifold_mesh(fine)
    dcoord = (verts - origin) @ d
    across = (verts - origin) @ nrm
    q = side * across
    off = (verts - origin) @ up_vec
    along = np.clip(q - lo, 0.0, ps[-1])
    mapped_q = np.interp(along, ps, pu) + lo
    tau = np.interp(along, ps, pt)
    base_z = np.interp(along, ps, pz)
    new_q = mapped_q - np.sin(tau) * off
    new_up = base_z + np.cos(tau) * off
    moved = (origin[None, :] + dcoord[:, None] * d[None, :]
             + (side * new_q)[:, None] * nrm[None, :]
             + new_up[:, None] * up_vec[None, :])
    solid = manifold_from_arrays(moved, faces, "сгибаемый лист")
    solid = solid.simplify(max(0.005, min(radius, max(panel, radius)) * 0.015))

    before, after = float(fine.volume()), float(solid.volume())
    tolerance = min(0.25, 0.02 + (parts - 1) * math.radians(angle) * thin
                    / max(span, 1e-6))
    if before > 1e-6 and abs(after - before) / before > tolerance:
        raise GeometryError("Сгиб замкнул лист в себя.",
                            hint="Увеличьте gap или уменьшите angle/parts.")
    a.scene.log("info", f"сгиб: линия {deg:g}°, parts={parts}, поворот {angle:g}°, "
                        f"толщина {thin:g} мм", a.cmd.line)
    out = _derived(a, name, solid, base, "fold")
    out.notes.append(f"сгиб исходной сетки: parts={parts}, dir={deg:g}°, "
                     f"angle={angle:g}°, joint={joint}")
    return out


@op("складка", aliases=("crease", "залом", "фалда", "cloth_fold", "сгиб_ткани",
                        "залом_ткани"),
    category="Форма и деформации",
    summary="Деформирует исходную поверхность по линии from→to: mode=гребень "
            "выдавливает настоящий валик, mode=канавка вдавливает углубление. "
            "r — полуширина, depth — высота/глубина; bend изгибает линию, taper "
            "плавно сводит складку на концах. Не добавляет полукольцо и не "
            "вычитает трубку: меняются вершины самой детали.",
    example="ткань = box size=[80,40,120] round=6\n"
            "складка ткань from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка\n"
            "лист = sheet width=160 length=120 thickness=1\n"
            "складка лист from=[-80,0,1] to=[80,0,1] r=3 mode=гребень",
    params={"objects": "объект [a] или a",
            "from": "начало складки [x,y,z]", "to": "конец складки [x,y,z]",
            "r": "полуширина складки, мм (4)",
            "depth": "высота гребня/глубина канавки, мм (0.8·r)",
            "mode": "гребень или канавка — гребень",
            "bend": "изгиб линии, мм (0)",
            "taper": "плавное сужение к концам 0…0.95 (0.35)",
            "smooth": "плотность профиля 6…64 (24): больше — мельче сетка",
            "normal": "необязательная общая нормаль тонкого листа [x,y,z]",
            "detail": "явная длина ребра перед деформацией, мм (авто)"},
    positional=["objects"])
def crease(a, name):
    from .ops_surface import _refine_for, _vertex_normals

    base = _one(a, "складка")
    p0 = np.asarray(a.vec("from", 3), dtype=np.float64).reshape(3)
    p1 = np.asarray(a.vec("to", 3), dtype=np.float64).reshape(3)
    r = float(a.num("r", 4.0, minv=0.2, maxv=200.0))
    depth = float(a.num("depth", r * 0.8, minv=0.02, maxv=400.0))
    mode = (a.text("mode") or "гребень").strip().lower()
    groove = mode.startswith("канав") or mode in ("groove", "cut", "вырез")
    if not groove and mode not in ("гребень", "валик", "ridge", "add"):
        raise GeometryError(f"Неизвестный вид складки «{mode}».", hint="mode: гребень или канавка.")
    bend = float(a.num("bend", 0.0, minv=-200.0, maxv=200.0))
    taper = float(a.num("taper", 0.35, minv=0.0, maxv=0.95))
    smooth = int(a.num("smooth", 24, minv=6, maxv=64))

    span = p1 - p0
    length = float(np.linalg.norm(span))
    if length < 1e-6:
        raise GeometryError("Начало и конец складки совпали.", hint="Разведите from и to.")
    d = span / length
    up_ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(d, up_ref))) > 0.95:
        up_ref = np.array([1.0, 0.0, 0.0])
    perp = _unit(np.cross(d, up_ref))

    m = base.manifold
    detail = a.num("detail", None, minv=0.02)
    # Двенадцать и более рёбер на полную ширину — канавка не распадается на
    # диагональные треугольники, а концы taper остаются плавными.
    refine = float(detail) if detail else max(0.05, 4.0 * r / smooth)
    fine = m.refine_to_length(_refine_for(m, refine, cap=300_000))
    verts, faces = manifold_mesh(fine)
    normals = _vertex_normals(verts, faces)

    rel = verts - p0
    t = np.clip((rel @ d) / length, 0.0, 1.0)
    centre = (p0[None, :] + t[:, None] * span[None, :]
              + (4.0 * t * (1.0 - t) * bend)[:, None] * perp[None, :])
    delta = verts - centre

    bb = m.bounding_box()
    ext = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])
    given_normal = a.vec("normal", 3, default=None)
    thin = float(ext.min()) <= float(ext.max()) * 0.08
    direction = None
    if given_normal is not None:
        direction = _unit(given_normal)
    elif thin:
        axis = int(np.argmin(ext))
        direction = np.zeros(3)
        direction[axis] = 1.0
        middle = (p0 + p1) * 0.5
        centre_bb = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)])
        if float(np.dot(middle - centre_bb, direction)) < 0:
            direction = -direction
    if direction is not None:
        # На тонком листе верх и низ движем вместе: толщина не прокалывается,
        # а гребень/канавка виден как настоящий изгиб материала.
        delta -= (delta @ direction)[:, None] * direction[None, :]

    distance = np.linalg.norm(delta, axis=1)
    q = np.clip(distance / r, 0.0, 1.0)
    profile = (1.0 - q * q) ** 2
    if taper > 1e-9:
        profile *= np.power(np.maximum(np.sin(math.pi * t), 0.0), 1.2 * taper)
    amount = (-1.0 if groove else 1.0) * depth * profile
    moved = (verts + direction[None, :] * amount[:, None] if direction is not None
             else verts + normals * amount[:, None])
    solid = manifold_from_arrays(moved, faces, "складки")
    a.scene.log("info", f"складка: {length:.1f} мм, r={r:g}, depth={depth:g}, "
                        f"{'канавка' if groove else 'гребень'}", a.cmd.line)
    out = _derived(a, name, solid, base, "crease")
    out.notes.append(f"деформация поверхности: {'канавка' if groove else 'гребень'}, "
                     f"r={r:g}, depth={depth:g}")
    return out
