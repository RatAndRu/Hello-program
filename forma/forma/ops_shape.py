"""Булевы операции, полые тела, массивы, преобразования и деформации."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import fibonacci_sphere
from .ops import (anchor, ensure_solid, make_solid, mirror as mirror_manifold,
                  merge_solids, op, rotate as rotate_manifold, scale as scale_manifold,
                  translate as translate_manifold)


def _derived(a, name, manifold, base, kind: str):
    solid = make_solid(a.scene, name or base.name, manifold, a, base=base, kind=kind)
    a.scene.consume(base)
    return solid


# --------------------------------------------------------------------------- #
#  Булевы операции
# --------------------------------------------------------------------------- #

@op("union", aliases=("объединить", "объединение", "плюс", "add"), category="Булевы операции",
    summary="Объединяет объекты в один. Исходные объекты скрываются.",
    example="кружка = union [корпус, ручка]",
    params={"objects": "список объектов [a, b, ...]"}, positional="*")
def union(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для объединения нужно минимум два объекта.")
    try:
        merged = merge_solids(solids, mf.OpType.Add)
    except Exception as exc:
        raise GeometryError(f"Не удалось объединить объекты: {exc}") from exc
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, merged, a, base=solids[0], kind="union")


@op("difference", aliases=("вычесть", "минус", "subtract", "отверстие"), category="Булевы операции",
    summary="Вычитает объекты из первого. Первый объект — основа, остальные — вычитаемые.",
    example="стакан = difference [заготовка, полость]",
    params={"objects": "список [основа, вычитаемое, ...]"}, positional="*")
def difference(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для вычитания нужны минимум два объекта: основа и вычитаемое.",
                           hint="Например: difference [корпус, отверстие]")
    try:
        merged = merge_solids(solids, mf.OpType.Subtract)
    except Exception as exc:
        raise GeometryError(f"Не удалось вычесть объекты: {exc}") from exc
    if merged.is_empty() or merged.volume() <= 1e-9:
        raise GeometryError("После вычитания ничего не осталось.",
                            hint="Вычитаемый объект полностью перекрыл основу.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, merged, a, base=solids[0], kind="difference")


@op("intersect", aliases=("пересечение", "пересечь", "and", "общее"), category="Булевы операции",
    summary="Оставляет только общий объём объектов.",
    example="линза = intersect [сфера1, сфера2]",
    params={"objects": "список объектов [a, b, ...]"}, positional="*")
def intersect(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для пересечения нужно минимум два объекта.")
    try:
        merged = merge_solids(solids, mf.OpType.Intersect)
    except Exception as exc:
        raise GeometryError(f"Не удалось пересечь объекты: {exc}") from exc
    if merged.is_empty() or merged.volume() <= 1e-9:
        raise GeometryError("Объекты не пересекаются — общий объём пуст.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, merged, a, base=solids[0], kind="intersect")


# --------------------------------------------------------------------------- #
#  Полые тела и скругления
# --------------------------------------------------------------------------- #

def shell_manifold(m: mf.Manifold, thickness: float, open_mode: str = "top") -> mf.Manifold:
    t = float(thickness)
    if t <= 1e-6:
        return m
    bb = m.bounding_box()
    smallest = min(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    if t * 2 >= smallest:
        raise GeometryError(
            f"Толщина стенки {t:g} мм слишком велика для объекта размером {smallest:.1f} мм.",
            hint="Стенка должна быть меньше половины наименьшего габарита.",
        )
    if m.num_tri() > 120_000:
        raise GeometryError(
            "Объект слишком подробный для полости этим способом "
            f"({m.num_tri():,} треугольников).".replace(",", " "),
            hint="Сделайте стенку прямо в lathe: thickness=4 open=top, "
                 "или упростите форму командой simplify.",
        )
    ball = mf.Manifold.sphere(t, 20)
    inner = m.minkowski_difference(ball)
    if inner.is_empty():
        raise GeometryError("Не удалось построить полость: уменьшите толщину стенки.")
    ibb = inner.bounding_box()
    extra = (bb[5] - bb[2]) + 4 * t + 10
    if open_mode in ("top", "both"):
        z = ibb[5] - t * 0.45
        if z > ibb[2] + 1e-6:
            cs = inner.slice(z)
            if cs.num_contour() > 0:
                inner = inner + cs.extrude(extra).translate((0, 0, z))
    if open_mode in ("bottom", "both"):
        z = ibb[2] + t * 0.45
        if z < ibb[5] - 1e-6:
            cs = inner.slice(z)
            if cs.num_contour() > 0:
                inner = inner + cs.extrude(extra).translate((0, 0, z - extra))
    result = m - inner
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После выдалбливания ничего не осталось: уменьшите толщину стенки.")
    return result


@op("shell", aliases=("оболочка", "полый", "выдолбить", "hollow"), category="Форма и деформации",
    summary="Делает объект полым с заданной толщиной стенки. Можно открыть верх, низ или оба.",
    example="кружка = shell [заготовка] thickness=4 open=top",
    params={"objects": "объект [a] или a", "thickness": "толщина стенки, мм (обязательно)",
            "open": "top (по умолчанию), bottom, both, none"},
    positional=["objects"])
def shell(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("shell работает с одним объектом.")
    thickness = a.num("thickness", required=True, minv=0.05)
    open_mode = a.text("open", "top", ["top", "bottom", "both", "none"]) or "top"
    result = shell_manifold(solids[0].manifold, float(thickness), open_mode)
    a.scene.consume(solids[0])
    return make_solid(a.scene, name, result, a, base=solids[0], kind="shell")


@op("offset", aliases=("смещение", "раздуть", "ужать", "inset", "outset"),
    category="Форма и деформации",
    summary="Расширяет (delta>0) или сжимает (delta<0) объект на заданную величину.",
    example="деталь = offset [деталь] delta=-0.4",
    params={"objects": "объект", "delta": "смещение, мм (плюс — наружу)",
            "segments": "качество скругления (32)"},
    positional=["objects"])
def offset(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("offset работает с одним объектом.")
    delta = a.num("delta", required=True)
    if abs(delta) < 1e-6:
        return _derived(a, name, solids[0].manifold, solids[0], "offset")
    ball = mf.Manifold.sphere(abs(delta), a.int("segments", 32, minv=8, maxv=96))
    source = solids[0]
    result = source.manifold.minkowski_sum(ball) if delta > 0 else \
        source.manifold.minkowski_difference(ball)
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После сжатия объект исчез.")
    a.scene.consume(source)
    return make_solid(a.scene, name, result, a, base=source, kind="offset")


@op("fillet", aliases=("скругление", "скруглить", "зализать"), category="Форма и деформации",
    summary="Скругляет внутренние стыки и углубления (наружные рёбра скругляйте параметром round у примитивов).",
    example="корпус = fillet [склеенный] radius=3",
    params={"objects": "объект", "radius": "радиус скругления, мм (обязательно)",
            "segments": "качество (32)"},
    positional=["objects"])
def fillet(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("fillet работает с одним объектом.")
    radius = a.num("radius", required=True, minv=0.05)
    ball = mf.Manifold.sphere(float(radius), a.int("segments", 32, minv=8, maxv=96))
    source = solids[0]
    grown = source.manifold.minkowski_sum(ball)
    result = grown.minkowski_difference(ball)
    a.scene.consume(source)
    return make_solid(a.scene, name, result, a, base=source, kind="fillet")


# --------------------------------------------------------------------------- #
#  Массивы
# --------------------------------------------------------------------------- #

def _rotate_about(m, axis: str, angle: float, center) -> mf.Manifold:
    axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    return rotate_manifold(m, angle, axis_vec, center)


@op("array", aliases=("массив", "копии", "повторить", "размножить"), category="Массивы и преобразования",
    summary="Создаёт копии объекта: линейно, по кругу или сеткой.",
    example="стойки = array [стойка] count=4 mode=radial around=z center=[0,0,0]",
    params={"objects": "исходный объект (или несколько — они объединяются)",
            "count": "количество копий (включая исходную)",
            "mode": "linear (по умолчанию), radial (по кругу), grid (сетка)",
            "offset": "шаг для linear [dx,dy,dz]",
            "around": "ось вращения для radial: x, y или z",
            "center": "центр вращения / точка отсчёта сетки",
            "angle": "полный угол для radial (360)",
            "start": "начальный угол для radial",
            "counts": "для grid: [nx,ny,nz]",
            "spacing": "для grid: шаг [dx,dy,dz]"},
    positional=["objects"])
def array(a, name):
    sources = a.solids()
    base = sources[0]
    source = merge_solids(sources) if len(sources) > 1 else sources[0].manifold
    mode = a.text("mode", "linear", ["linear", "radial", "grid"]) or "linear"
    count = a.int("count", 2, minv=1, maxv=400)
    if count is None:
        count = 2
    copies = [source]
    if mode == "linear":
        offset = a.vec("offset", 3, default=(20.0, 0.0, 0.0))
        for i in range(1, count):
            copies.append(translate_manifold(source, np.array(offset) * i))
    elif mode == "radial":
        axis = (a.text("around", "z", ["x", "y", "z"]) or "z").lower()
        center = a.vec("center", 3, default=(0.0, 0.0, 0.0))
        total = float(a.num("angle", 360.0) or 360.0)
        start = float(a.num("start", 0.0) or 0.0)
        step = total / count
        for i in range(1, count):
            copies.append(_rotate_about(source, axis, start + step * i, center))
    else:
        counts = a.vec("counts", 3, default=(2.0, 1.0, 1.0))
        counts_i = [max(1, int(round(c))) for c in counts]
        spacing = a.vec("spacing", 3, default=(20.0, 0.0, 0.0))
        center = a.vec("center", 3, default=(0.0, 0.0, 0.0))
        if counts_i[0] * counts_i[1] * counts_i[2] > 500:
            raise GeometryError("Слишком много копий в сетке (максимум 500).")
        for ix in range(counts_i[0]):
            for iy in range(counts_i[1]):
                for iz in range(counts_i[2]):
                    if ix == 0 and iy == 0 and iz == 0:
                        continue
                    off = np.array([ix * spacing[0], iy * spacing[1], iz * spacing[2]])
                    copies.append(translate_manifold(source, np.array(center) + off))
    for s in sources:
        a.scene.consume(s)
    merged = mf.Manifold.batch_boolean(copies, mf.OpType.Add)
    if merged.num_tri() > 1_500_000:
        a.scene.log("warn", "Массив получился очень тяжёлым — уменьшите количество копий.",
                    a.cmd.line)
    return make_solid(a.scene, name, merged, a, base=base, kind="array")


# --------------------------------------------------------------------------- #
#  Преобразования
# --------------------------------------------------------------------------- #

@op("translate", aliases=("сдвинуть", "переместить", "move", "сдвиг"), category="Массивы и преобразования",
    summary="Сдвигает объект на вектор.",
    example="деталь = translate [шкив] offset=[0,0,20]",
    params={"objects": "объект", "offset": "вектор [dx,dy,dz] или число",
            "x": "сдвиг по X", "y": "сдвиг по Y", "z": "сдвиг по Z"},
    positional=["objects"])
def translate(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("translate работает с одним объектом.")
    base = solids[0]
    if a.has("offset"):
        off = a.vec("offset", 3, default=(0, 0, 0))
    else:
        off = [a.num("x", 0.0) or 0.0, a.num("y", 0.0) or 0.0, a.num("z", 0.0) or 0.0]
    if abs(off[0]) + abs(off[1]) + abs(off[2]) < 1e-9:
        return _derived(a, name, base.manifold, base, "translate")
    result = translate_manifold(base.manifold, off)
    return _derived(a, name, result, base, "translate")


@op("rotate", aliases=("повернуть", "вращать", "поворот"), category="Массивы и преобразования",
    summary="Поворачивает объект вокруг оси (по умолчанию Z) на угол в градусах.",
    example="деталь = rotate [деталь] angle=90 axis=z",
    params={"objects": "объект", "angle": "угол, градусы",
            "axis": "x, y, z или вектор [x,y,z]",
            "pivot": "точка, вокруг которой вращать"},
    positional=["objects"])
def rotate(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("rotate работает с одним объектом.")
    base = solids[0]
    angle = a.num("angle", required=True)
    axis_raw = a.text("axis", "z")
    if axis_raw in ("x", "y", "z"):
        axis = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis_raw]
    else:
        axis = a.vec("axis", 3, default=(0, 0, 1))
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    return _derived(a, name, rotate_manifold(base.manifold, float(angle), axis, pivot),
                    base, "rotate")


@op("scale", aliases=("масштабировать", "увеличить", "size"), category="Массивы и преобразования",
    summary="Масштабирует объект: равномерно (factor=2) или по осям (factor=[1,2,1]).",
    example="деталь = scale [деталь] factor=[1,1,1.5]",
    params={"objects": "объект", "factor": "число или [sx,sy,sz]",
            "pivot": "точка отсчёта масштаба"},
    positional=["objects"])
def scale(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("scale работает с одним объектом.")
    base = solids[0]
    factor = a.vec("factor", 3, required=True)
    if any(f <= 0 for f in factor):
        raise GeometryError("Масштаб должен быть больше нуля.")
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    return _derived(a, name, scale_manifold(base.manifold, factor, pivot), base, "scale")


@op("place", aliases=("поставить", "позиционировать", "align"), category="Массивы и преобразования",
    summary="Ставит объект в точку: низом, центром или верхом.",
    example="деталь = place [деталь] at=[0,0,50] align=bottom",
    params={"objects": "объект", "at": "точка [x,y,z]",
            "align": "bottom (по умолчанию), center или top",
            "center_xy": "центрировать по X и Y (true)"},
    positional=["objects"])
def place(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("place работает с одним объектом.")
    base = solids[0]
    at = a.vec("at", 3, default=(0, 0, 0))
    align = (a.text("align", "bottom", ["bottom", "center", "top"]) or "bottom").lower()
    bb = base.manifold.bounding_box()
    size = (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    center = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2
    center_xy = a.boolean("center_xy", True)
    tx = at[0] if center_xy else at[0] + size[0] / 2
    ty = at[1] if center_xy else at[1] + size[1] / 2
    if align == "bottom":
        target = (tx, ty, at[2] + size[2] / 2)
    elif align == "top":
        target = (tx, ty, at[2] - size[2] / 2)
    else:
        target = (tx, ty, at[2])
    off = (target[0] - center[0], target[1] - center[1], target[2] - center[2])
    return _derived(a, name, translate_manifold(base.manifold, off), base, "place")


@op("mirror", aliases=("зеркало", "отразить", "симметрия"), category="Массивы и преобразования",
    summary="Отражает объект через плоскость. keep=true — оставляет и оригинал (симметричная сборка).",
    example="ножки = mirror [ножка] plane=x",
    params={"objects": "объект", "plane": "x (по умолчанию), y или z",
            "at": "координата плоскости (0)", "keep": "оставить оригинал (true)"},
    positional=["objects"])
def mirror(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("mirror работает с одним объектом.")
    base = solids[0]
    plane = (a.text("plane", "x", ["x", "y", "z"]) or "x").lower()
    at = float(a.num("at", 0.0) or 0.0)
    keep = a.boolean("keep", True)
    reflected = mirror_manifold(base.manifold, plane, at)
    result = mf.Manifold.batch_boolean([base.manifold, reflected], mf.OpType.Add) if keep else reflected
    return _derived(a, name, result, base, "mirror")


@op("refine", aliases=("уточнить", "подразбить", "subdivide"), category="Форма и деформации",
    summary="Повышает плотность сетки (плавнее поверхность).",
    example="деталь = refine [деталь] length=1.5",
    params={"objects": "объект", "length": "целевая длина ребра, мм",
            "levels": "число уровней подразбиения"},
    positional=["objects"])
def refine(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("refine работает с одним объектом.")
    base = solids[0]
    if a.has("levels"):
        levels = a.int("levels", 1, minv=1, maxv=4)
        result = base.manifold.refine(int(levels))
    else:
        length = a.num("length", 1.5, minv=0.05)
        result = base.manifold.refine_to_length(float(length))
    return _derived(a, name, result, base, "refine")


@op("simplify", aliases=("упростить", "облегчить"), category="Форма и деформации",
    summary="Упрощает сетку, сохраняя форму (меньше треугольников).",
    example="деталь = simplify [деталь] tolerance=0.3",
    params={"objects": "объект", "tolerance": "допуск, мм (0.3)"},
    positional=["objects"])
def simplify(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("simplify работает с одним объектом.")
    base = solids[0]
    tol = a.num("tolerance", 0.3, minv=0.0)
    result = base.manifold.simplify(float(tol))
    if result.is_empty():
        raise GeometryError("Не удалось упростить объект с таким допуском.")
    return _derived(a, name, result, base, "simplify")


# --------------------------------------------------------------------------- #
#  Деформации
# --------------------------------------------------------------------------- #

def _warp(a, base, fn, kind: str, name=None):
    try:
        result = base.manifold.warp(fn)
    except Exception as exc:
        raise GeometryError(f"Деформация не удалась: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После деформации объект исчез.")
    return _derived(a, name, result, base, kind)


@op("twist", aliases=("скрутить", "закрутить"), category="Форма и деформации",
    summary="Скручивает объект вокруг оси: угол растёт вдоль оси.",
    example="деталь = twist [деталь] angle=90 axis=z",
    params={"objects": "объект", "angle": "полный угол закрутки, градусы",
            "axis": "x, y или z", "pivot": "центр оси"},
    positional=["objects"])
def twist(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("twist работает с одним объектом.")
    base = solids[0]
    angle = float(a.num("angle", required=True))
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    bb = base.manifold.bounding_box()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    lo, hi = bb[idx], bb[idx + 3]
    span = max(hi - lo, 1e-9)
    ang = math.radians(angle)
    axis_vec = np.array([1.0 if axis == "x" else 0.0,
                         1.0 if axis == "y" else 0.0,
                         1.0 if axis == "z" else 0.0])
    pv = np.array(pivot, dtype=np.float64)

    def fn(p):
        t = (p[idx] - lo) / span
        teta = ang * t
        v = np.array([p[0], p[1], p[2]], dtype=np.float64) - pv
        c, s = math.cos(teta), math.sin(teta)
        x, y, z = v
        if axis == "z":
            v2 = np.array([x * c - y * s, x * s + y * c, z])
        elif axis == "x":
            v2 = np.array([x, y * c - z * s, y * s + z * c])
        else:
            v2 = np.array([x * c + z * s, y, -x * s + z * c])
        return [float(v2[0] + pv[0]), float(v2[1] + pv[1]), float(v2[2] + pv[2])]

    return _warp(a, base, fn, "twist", name)


@op("taper", aliases=("сузить", "конусность", "taper"), category="Форма и деформации",
    summary="Плавно сужает объект кверху (factor<1) или расширяет (factor>1).",
    example="деталь = taper [деталь] factor=0.6 axis=z",
    params={"objects": "объект", "factor": "масштаб на дальнем конце (0.6)",
            "axis": "x, y или z", "pivot": "центр по осям сечения"},
    positional=["objects"])
def taper(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("taper работает с одним объектом.")
    base = solids[0]
    factor = float(a.num("factor", 0.6, minv=0.01, maxv=100))
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    bb = base.manifold.bounding_box()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    lo, hi = bb[idx], bb[idx + 3]
    span = max(hi - lo, 1e-9)
    others = [i for i in range(3) if i != idx]

    def fn(p):
        t = (p[idx] - lo) / span
        s = 1.0 + (factor - 1.0) * t
        out = [float(p[0]), float(p[1]), float(p[2])]
        for i in others:
            out[i] = float(pivot[i] + (p[i] - pivot[i]) * s)
        return out

    return _warp(a, base, fn, "taper", name)


@op("bend", aliases=("согнуть", "изгиб", "дуга"), category="Форма и деформации",
    summary="Сгибает объект дугой. Ось Z изгибается в плоскости XZ.",
    example="прут = bend [прут] angle=60",
    params={"objects": "объект", "angle": "угол изгиба, градусы", "pivot": "смещение центра"},
    positional=["objects"])
def bend(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("bend работает с одним объектом.")
    base = solids[0]
    angle = float(a.num("angle", required=True))
    if abs(angle) > 350:
        raise GeometryError("Угол изгиба должен быть меньше 350 градусов.")
    bb = base.manifold.bounding_box()
    z0, z1 = bb[2], bb[5]
    length = max(z1 - z0, 1e-9)
    total = math.radians(angle)
    radius = length / total if abs(total) > 1e-9 else 1e12

    def fn(p):
        t = (p[2] - z0) / length
        teta = total * t
        r = radius + p[0]
        x = r * math.cos(teta) - radius
        z = r * math.sin(teta) + z0
        return [float(x), float(p[1]), float(z)]

    return _warp(a, base, fn, "bend", name)
