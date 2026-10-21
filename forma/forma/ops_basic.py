"""Примитивы: куб, сфера, цилиндр, конус, тор, призма, капсула, оболочка."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, hull_of_manifolds, manifold_mesh
from .ops import anchor, ensure_solid, make_solid, op


def _round_value(a) -> float:
    return float(a.num("round", 0.0, minv=0.0) or 0.0)


def _sphere_segments(radius: float) -> int:
    return int(max(24, min(64, round(radius * 12))))


@op("box", aliases=("куб", "коробка", "cube", "параллелепипед", "брусок", "блок"),
    category="Примитивы",
    summary="Прямоугольный блок. По умолчанию стоит на полу: центр по XY, низ на z=0.",
    example="стол = box size=[1200,700,40]",
    params={"size": "размер [x,y,z], мм (обязательно)",
            "round": "радиус скругления рёбер, мм",
            "center": "центрировать в точке at (по умолчанию — низ на at)",
            "at": "положение [x,y,z]"},
    positional=[])
def box(a, name):
    size = a.vec("size", 3, required=True)
    if any(s <= 0 for s in size):
        raise GeometryError("Размеры блока должны быть больше нуля.")
    r = _round_value(a)
    solid = None
    if r > 1e-6:
        if min(size) <= 2 * r + 1e-6:
            raise GeometryError(
                f"Скругление {r:g} мм слишком велико для блока {size}.",
                hint=f"Максимум — {min(size) / 2 - 0.01:.2f} мм.",
            )
        inner = [s - 2 * r for s in size]
        solid = mf.Manifold.cube(inner, True).minkowski_sum(
            mf.Manifold.sphere(r, _sphere_segments(r)))
    else:
        solid = mf.Manifold.cube(size, True)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="box")


@op("sphere", aliases=("сфера", "шар", "ball"),
    category="Примитивы",
    summary="Сфера. Центр — в точке at (по умолчанию в начале координат).",
    example="шар = sphere radius=40 at=[0,0,40]",
    params={"radius": "радиус, мм (обязательно)",
            "segments": "число сегментов (по умолчанию 64)",
            "at": "центр сферы [x,y,z]"},
    positional=["radius"])
def sphere(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    segments = a.int("segments", 64, minv=8, maxv=512)
    solid = mf.Manifold.sphere(radius, segments)
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    return make_solid(a.scene, name, solid, a, kind="sphere")


@op("cylinder", aliases=("цилиндр", "труба", "стакан"),
    category="Примитивы",
    summary="Цилиндр или усечённый конус. По умолчанию стоит на полу.",
    example="корпус = cylinder radius=40 height=90 segments=128 round=3",
    params={"radius": "радиус снизу, мм (обязательно)",
            "height": "высота, мм (обязательно)",
            "r2": "радиус сверху (по умолчанию равен нижнему)",
            "segments": "число сегментов (по умолчанию 96)",
            "round": "скругление верхней и нижней кромки, мм",
            "center": "центрировать по высоте",
            "at": "положение [x,y,z]"},
    positional=["radius", "height"])
def cylinder(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    r2 = a.num("r2", radius, minv=0.0)
    if r2 is None:
        r2 = radius
    segments = a.int("segments", 96, minv=8, maxv=1024)
    r = _round_value(a)
    if r > 1e-6:
        if height <= 2 * r + 1e-6:
            raise GeometryError(f"Скругление {r:g} мм больше половины высоты {height:g} мм.")
        if min(radius, r2) <= r + 1e-6:
            raise GeometryError(f"Скругление {r:g} мм больше радиуса {min(radius, r2):g} мм.")
        inner_h = height - 2 * r
        solid = mf.Manifold.cylinder(inner_h, radius - r, r2 - r, segments)
        solid = solid.minkowski_sum(mf.Manifold.sphere(r, _sphere_segments(r)))
    else:
        solid = mf.Manifold.cylinder(height, radius, r2, segments)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="cylinder")


@op("cone", aliases=("конус",), category="Примитивы",
    summary="Конус с вершиной вверх, стоит на полу.",
    example="воронка = cone radius=30 height=60",
    params={"radius": "радиус основания, мм", "height": "высота, мм",
            "segments": "сегментов (96)", "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def cone(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    segments = a.int("segments", 96, minv=8, maxv=1024)
    solid = mf.Manifold.cylinder(height, radius, 0.0, segments)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="cone")


@op("torus", aliases=("тор", "бублик", "кольцо"), category="Примитивы",
    summary="Тор (кольцо) в плоскости XY, центр — в точке at.",
    example="кольцо = torus major=35 minor=6",
    params={"major": "радиус кольца до центра трубки, мм",
            "minor": "радиус трубки, мм",
            "segments": "сегментов по кругу (96)",
            "minor_segments": "сегментов трубки (28)",
            "at": "центр [x,y,z]"},
    positional=["major", "minor"])
def torus(a, name):
    major = a.num("major", required=True, minv=0.1)
    minor = a.num("minor", required=True, minv=0.01)
    segments = a.int("segments", 96, minv=12, maxv=512)
    mseg = a.int("minor_segments", 28, minv=8, maxv=128)
    if minor >= major:
        raise GeometryError("Радиус трубки тора должен быть меньше радиуса кольца.")
    prof = circle_profile(minor, mseg) + np.array([major, 0.0])
    solid = mf.Manifold.revolve(mf.CrossSection([prof]), segments)
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = anchor(solid, at, center=True)
    return make_solid(a.scene, name, solid, a, kind="torus")


@op("prism", aliases=("призма", "многоугольник", "гайка"), category="Примитивы",
    summary="Правильная призма с n сторонами (по умолчанию стоит на полу).",
    example="гайка = prism sides=6 radius=20 height=12",
    params={"sides": "число сторон (6)", "radius": "радиус описанной окружности, мм",
            "height": "высота, мм", "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def prism(a, name):
    sides = a.int("sides", 6, minv=3, maxv=256)
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.01)
    prof = circle_profile(radius, sides)
    solid = mf.CrossSection([prof]).extrude(height)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="prism")


@op("capsule", aliases=("капсула", "пилюля"), category="Примитивы",
    summary="Капсула: цилиндр с полусферами. Высота задаётся полная.",
    example="палец = capsule radius=9 height=70",
    params={"radius": "радиус, мм", "height": "полная высота, мм",
            "segments": "сегментов (48)", "center": "центрировать", "at": "положение"},
    positional=["radius", "height"])
def capsule(a, name):
    radius = a.num("radius", required=True, minv=0.01)
    height = a.num("height", required=True, minv=0.02)
    segments = a.int("segments", 48, minv=8, maxv=256)
    if height < 2 * radius - 1e-6:
        raise GeometryError(
            f"Высота капсулы {height:g} мм меньше двух радиусов ({2 * radius:g} мм).",
            hint="Высота капсулы включает полусферы.",
        )
    inner_h = max(height - 2 * radius, 1e-4)
    body = mf.Manifold.cylinder(inner_h, radius, radius, segments)
    top = mf.Manifold.sphere(radius, segments).translate((0, 0, inner_h))
    bottom = mf.Manifold.sphere(radius, segments)
    solid = body + top + bottom
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    return make_solid(a.scene, name, solid, a, kind="capsule")


@op("hull", aliases=("оболочка", "выпуклая_оболочка", "обернуть"), category="Примитивы",
    summary="Выпуклая оболочка объектов или набора 3D-точек.",
    example="кузов = hull objects=[низ, кабина]",
    params={"objects": "объекты, которые нужно обернуть",
            "points": "точки [[x,y,z],...]"},
    positional="*")
def hull(a, name):
    pts_param = None
    if a.has("points"):
        pts_param = a.points("points", dims=3)
    solids = []
    if a.extra or a.has("objects"):
        solids = a.solids()
    clouds = []
    if pts_param is not None:
        clouds.append(np.asarray(pts_param, dtype=np.float64))
    for s in solids:
        v, _ = manifold_mesh(s.manifold)
        if len(v):
            clouds.append(v)
    if not clouds:
        raise GeometryError("Для оболочки нужны объекты или минимум 4 точки.",
                            hint="Например: hull objects=[корпус, кабина]")
    cloud = np.vstack(clouds)
    if len(cloud) > 80000:
        cloud = cloud[:: max(1, len(cloud) // 80000)]
    hull_m = mf.Manifold.hull_points(np.ascontiguousarray(cloud, dtype=np.float64))
    if hull_m.is_empty():
        raise GeometryError("Выпуклая оболочка не построена: точки лежат в одной плоскости.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, hull_m, a, base=solids[0] if solids else None, kind="hull")
    return make_solid(a.scene, name, hull_m, a, base=base, kind="hull")
