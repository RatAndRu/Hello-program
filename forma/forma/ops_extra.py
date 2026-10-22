"""Дополнительные инструменты: сглаживание, вырезы, выравнивание, срезы, канавки.

Эти команды появились после разбора моделей: не хватало безопасных способов
убрать «лесенки» на переходах, аккуратно вырезать окна и отверстия, выровнять
деталь и сделать канавки (например, на пробке бутылки).
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import make_solid, op

MAX_TRIS = 1_600_000


def _derived(a, name, manifold, base, kind: str):
    solid = make_solid(a.scene, name or base.name, manifold, a, base=base, kind=kind)
    a.scene.consume(base)
    return solid


def _one(a, command: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{command} работает с одним объектом.",
                            hint=f"Формат: имя = {command} [объект] …")
    return solids[0]


# --------------------------------------------------------------------------- #
#  Сглаживание и округление переходов
# --------------------------------------------------------------------------- #

@op("smooth", aliases=("сгладить", "сглаживание", "плавно", "умягчить", "soften"),
    category="Форма и деформации",
    summary="Сглаживает переходы и убирает «лесенки» на гранях: G1-непрерывность "
            "и дополнительное дробление поверхности.",
    example="кружка = smooth [кружка] angle=50 soft=0.35 levels=2",
    params={"objects": "объект",
            "angle": "угол, выше которого ребро остаётся острым, ° (50)",
            "soft": "мягкость острых рёбер 0…1 (0.3)",
            "levels": "дробление поверхности 1…3 (1 — без дробления)"},
    positional=["objects"])
def smooth(a, name):
    base = _one(a, "smooth")
    angle = a.num("angle", 50.0, minv=0.0, maxv=180.0)
    soft = a.num("soft", 0.3, minv=0.0, maxv=1.0)
    levels = a.int("levels", 1, minv=1, maxv=3)
    tris = base.manifold.num_tri()
    if tris * (levels ** 2) > MAX_TRIS:
        raise GeometryError(
            f"Сглаживание слишком тяжёлое: {tris:,} трис × {levels ** 2}.".replace(",", " "),
            hint="Уменьшите levels до 1 или сначала упростите объект (simplify).")
    try:
        result = base.manifold.smooth_out(float(angle), float(soft))
        if levels > 1:
            result = result.refine(int(levels))
    except Exception as exc:
        raise GeometryError(f"Не удалось сгладить объект: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После сглаживания объект исчез — уменьшите параметры.")
    return _derived(a, name, result, base, "smooth")


@op("bevel", aliases=("фаска", "скос", "округление", "кромка"), category="Форма и деформации",
    summary="Мягкая фаска на острых рёбрах без тяжёлых булевых операций.",
    example="плита = bevel [плита] angle=55 soft=0.5 levels=2",
    params={"objects": "объект", "angle": "угол острых рёбер, ° (55)",
            "soft": "ширина фаски 0…1 (0.5)", "levels": "дробление 1…3 (2)"},
    positional=["objects"])
def bevel(a, name):
    base = _one(a, "bevel")
    angle = a.num("angle", 55.0, minv=1.0, maxv=180.0)
    soft = a.num("soft", 0.5, minv=0.0, maxv=1.0)
    levels = a.int("levels", 2, minv=1, maxv=3)
    tris = base.manifold.num_tri()
    if tris * (levels ** 2) > MAX_TRIS:
        levels = 1
    try:
        result = base.manifold.smooth_out(float(angle), float(soft))
        if levels > 1:
            result = result.refine(int(levels))
    except Exception as exc:
        raise GeometryError(f"Не удалось сделать фаску: {exc}") from exc
    return _derived(a, name, result, base, "bevel")


# --------------------------------------------------------------------------- #
#  Вырезы готовыми формами
# --------------------------------------------------------------------------- #

def _cutter(a, at) -> mf.Manifold:
    shape = (a.text("shape", "sphere") or "sphere").strip().lower()
    shape = {"шар": "sphere", "сфера": "sphere", "блок": "box", "куб": "box",
             "цилиндр": "cylinder", "конус": "cone", "кольцо": "ring"}.get(shape, shape)
    seg = a.int("segments", 48, minv=6, maxv=256)
    if shape == "sphere":
        r = a.num("radius", required=True, minv=0.05)
        m = mf.Manifold.sphere(float(r), int(seg))
    elif shape == "box":
        size = a.vec("size", 3, default=None)
        if size is None:
            r = a.num("radius", 10.0, minv=0.1)
            size = [r * 2, r * 2, r * 2]
        m = mf.Manifold.cube([float(v) for v in size], True)
        r = a.num("round", 0.0, minv=0.0)
        if r > 1e-6:
            if min(size) <= 2 * r:
                raise GeometryError(f"Скругление {r:g} мм слишком велико для выреза {size}.")
            inner = [float(v) - 2 * r for v in size]
            m = mf.Manifold.cube(inner, True).minkowski_sum(mf.Manifold.sphere(float(r), 24))
    elif shape == "cylinder":
        r = a.num("radius", required=True, minv=0.05)
        r2 = a.num("r2", float(r), minv=0.0)
        h = a.num("height", a.num("depth", 40.0), minv=0.1)
        m = mf.Manifold.cylinder(float(h), float(r), float(r2), int(seg), True)
    elif shape == "cone":
        r = a.num("radius", required=True, minv=0.05)
        h = a.num("height", a.num("depth", 40.0), minv=0.1)
        m = mf.Manifold.cylinder(float(h), float(r), 0.0, int(seg), True)
    elif shape == "ring":
        r = a.num("radius", required=True, minv=0.1)
        width = a.num("width", 3.0, minv=0.05)
        h = a.num("height", a.num("depth", 10.0), minv=0.1)
        outer = mf.Manifold.cylinder(float(h), float(r) + width / 2, float(r) + width / 2, int(seg), True)
        inner = mf.Manifold.cylinder(float(h) * 1.5, max(0.01, float(r) - width / 2),
                                     max(0.01, float(r) - width / 2), int(seg), True)
        m = outer - inner
    else:
        raise GeometryError(f"Неизвестная форма выреза «{shape}».",
                            hint="shape=sphere | box | cylinder | cone | ring")
    return m.translate([float(v) for v in at])


@op("cut", aliases=("вырезать", "вырез", "отверстие", "прокол", "выемка"),
    category="Булевы операции",
    summary="Вырезает готовую форму из объекта одной командой: сфера, блок, "
            "цилиндр, конус или кольцо в точке at.",
    example="кружка = cut [кружка] shape=box size=[30,30,60] at=[0,0,80]",
    params={"objects": "объект", "shape": "sphere|box|cylinder|cone|ring (sphere)",
            "at": "центр выреза [x,y,z] (0,0,0)", "radius": "радиус, мм",
            "size": "размер блока [x,y,z]", "height": "высота цилиндра/конуса, мм",
            "round": "скругление блока, мм", "segments": "гладкость (48)"},
    positional=["objects"])
def cut(a, name):
    base = _one(a, "cut")
    at = a.vec("at", 3, default=(0, 0, 0))
    cutter = _cutter(a, at)
    try:
        result = base.manifold - cutter
    except Exception as exc:
        raise GeometryError(f"Не удалось вырезать: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После выреза ничего не осталось.",
                            hint="Вырез перекрыл весь объект — уменьшите размер или сдвиньте at.")
    return _derived(a, name, result, base, "cut")


@op("groove", aliases=("канавка", "борозда", "насечка", "рифление"), category="Форма и деформации",
    summary="Прорезает кольцевую канавку вокруг вертикальной оси — как на пробке "
            "или крышке. Можно задать несколько канавок.",
    example="пробка = groove [пробка] at=[0,0,20] radius=14 depth=1.2 height=2 count=3",
    params={"objects": "объект", "at": "центр первой канавки [x,y,z]",
            "radius": "радиус канавки, мм (обязательно)", "depth": "глубина, мм (1.2)",
            "height": "высота канавки, мм (2)", "count": "сколько канавок (1)",
            "step": "расстояние между канавками по Z, мм", "segments": "гладкость (64)"},
    positional=["objects"])
def groove(a, name):
    base = _one(a, "groove")
    at = a.vec("at", 3, default=(0, 0, 0))
    radius = a.num("radius", required=True, minv=0.2)
    depth = a.num("depth", 1.2, minv=0.05)
    height = a.num("height", 2.0, minv=0.05)
    count = a.int("count", 1, minv=1, maxv=40)
    step = a.num("step", height * 2, minv=0.01)
    seg = a.int("segments", 64, minv=8, maxv=256)
    result = base.manifold
    for i in range(count):
        z = float(at[2]) + i * float(step)
        outer = mf.Manifold.cylinder(float(height), float(radius) + float(depth) + 0.6,
                                     float(radius) + float(depth) + 0.6, int(seg), True)
        inner = mf.Manifold.cylinder(float(height) * 1.2, float(radius),
                                     float(radius), int(seg), True)
        ring = (outer - inner).translate([float(at[0]), float(at[1]), z])
        result = result - ring
    if result.is_empty():
        raise GeometryError("Канавка срезала объект целиком — уменьшите глубину.")
    return _derived(a, name, result, base, "groove")


# --------------------------------------------------------------------------- #
#  Выравнивание и срезы
# --------------------------------------------------------------------------- #

@op("align", aliases=("выровнять", "прижать", "поставить", "выравнивание"),
    category="Массивы и преобразования",
    summary="Выравнивает объект по осям: min|center|max или точное число. "
            "Например, align деталь z=min поставит её на пол.",
    example="деталь = align [деталь] x=center y=center z=min",
    params={"objects": "объект", "x": "min|center|max|число",
            "y": "min|center|max|число", "z": "min|center|max|число"},
    positional=["objects"])
def align(a, name):
    base = _one(a, "align")
    bb = base.manifold.bounding_box()
    lo = np.array(bb[:3], dtype=np.float64)
    hi = np.array(bb[3:], dtype=np.float64)
    offset = np.zeros(3)
    modes = {}
    for i, axis in enumerate("xyz"):
        raw = a.text(axis)
        if raw is None:
            continue
        val = raw.strip().lower()
        if val in ("min", "мин", "низ", "начало"):
            offset[i] = -lo[i]
        elif val in ("max", "макс", "верх", "конец"):
            offset[i] = -hi[i]
        elif val in ("center", "центр", "середина"):
            offset[i] = -(lo[i] + hi[i]) / 2
        else:
            try:
                offset[i] = float(val) - lo[i]
            except ValueError as exc:
                raise GeometryError(f"align {axis}={raw}: нужно min, center, max или число.") from exc
        modes[axis] = val
    if not modes:
        raise GeometryError("Укажите хотя бы одну ось: align деталь z=min.")
    result = base.manifold.translate([float(v) for v in offset])
    return _derived(a, name, result, base, "align")


@op("slice", aliases=("срез", "разрезать", "отрезать", "обрезать"), category="Булевы операции",
    summary="Отрезает объект плоскостью по X/Y/Z: keep=top|bottom|left|right|front|back.",
    example="корпус = slice [корпус] axis=z at=0 keep=top",
    params={"objects": "объект", "axis": "x|y|z (z)", "at": "координата плоскости, мм (0)",
            "keep": "top|bottom (top)", "size": "размер режущего блока, мм (10000)"},
    positional=["objects"])
def slice(a, name):
    base = _one(a, "slice")
    axis = (a.text("axis", "z") or "z").lower()
    if axis not in ("x", "y", "z"):
        raise GeometryError("axis должен быть x, y или z.")
    at = a.num("at", 0.0)
    keep = (a.text("keep", "top") or "top").lower()
    size = a.num("size", 10000.0, minv=10.0)
    positive = keep in ("top", "верх", "right", "справа", "back", "сзади", "max")
    idx = "xyz".index(axis)
    vec = [0.0, 0.0, 0.0]
    vec[idx] = float(at) + (size / 2 if positive else -size / 2)
    block = mf.Manifold.cube([size, size, size], True).translate(vec)
    result = mf.Manifold.batch_boolean([base.manifold, block], mf.OpType.Intersect)
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Срез не оставил ничего.",
                            hint="Проверьте at и keep — плоскость может быть вне модели.")
    return _derived(a, name, result, base, "slice")


@op("mirror_copy", aliases=("отразить_копию", "симметрия"), category="Массивы и преобразования",
    summary="Оставляет объект и добавляет его отражённую копию — удобно для парных деталей.",
    example="ручки = mirror_copy [ручка] plane=x",
    params={"objects": "объект", "plane": "x|y|z (x)", "gap": "зазор между половинами, мм (0)"},
    positional=["objects"])
def mirror_copy(a, name):
    base = _one(a, "mirror_copy")
    plane = (a.text("plane", "x") or "x").lower()
    if plane not in ("x", "y", "z"):
        raise GeometryError("plane должен быть x, y или z.")
    gap = a.num("gap", 0.0, minv=0.0)
    idx = "xyz".index(plane)
    shift = [0.0, 0.0, 0.0]
    if gap > 0:
        bb = base.manifold.bounding_box()
        shift[idx] = gap / 2 - bb[idx]
    source = base.manifold.translate(shift)
    mirrored = source.mirror([1.0 if i == idx else 0.0 for i in range(3)])
    result = source + mirrored
    return _derived(a, name, result, base, "mirror_copy")
