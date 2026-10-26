"""Анатомическое глазное яблоко из отдельных объёмных оптических деталей."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .model import Solid
from .ops import make_solid, op
from .ops_figure import _anchor_all
from .ops_kit import _revolve_profile


def _spherical_disc(radius: float, angle: float, inner: float, outer: float,
                    segments: int, what: str) -> mf.Manifold:
    """Тонкий диск, повторяющий сферу, с перекрытием вместо щели.

    Диск строится телом вращения вокруг Z и затем поворачивается лицом в −Y.
    ``inner``/``outer`` — радиальные смещения от исходной сферы. Внутренний
    слой немного погружён в предыдущую деталь, поэтому на кромке нет щели;
    наружные поверхности разнесены и не дают z-fighting.
    """
    ri, ro = radius + inner, radius + outer
    if ri <= 0.05 or ro <= ri:
        raise GeometryError(f"{what}: неправильная толщина сферического диска.")
    steps = 20
    profile = []
    for i in range(steps + 1):
        theta = angle * i / steps
        profile.append((ro * math.sin(theta), -ro * math.cos(theta)))
    for i in range(steps, -1, -1):
        theta = angle * i / steps
        profile.append((ri * math.sin(theta), -ri * math.cos(theta)))
    return _revolve_profile(profile, segments, what).rotate((-90.0, 0.0, 0.0))


def _cornea(radius: float, aperture: float, bulge: float, edge_thickness: float,
            front_offset: float, iris_angle: float, segments: int) -> mf.Manifold:
    """Выпуклая оболочка, целиком проходящая ПЕРЕД оптическими дисками.

    Внутренняя сфера на ``clearance`` ближе к зрителю, чем зрачок и радужка:
    интервалы тел по оптической оси не пересекаются. За кромкой радужки эта
    дуга плавно уходит в склеру. Наружная дуга независимо задаёт выпуклость.
    """
    y_rim = -math.sqrt(max(1e-9, radius * radius - aperture * aperture))
    embed = edge_thickness + max(0.04, radius * 0.008)
    outer_rim = y_rim - embed
    inner_rim = outer_rim + edge_thickness
    clearance = max(0.02, edge_thickness * 0.2)
    inner_radius = radius + front_offset + clearance
    if bulge <= front_offset + clearance:
        raise GeometryError("Роговица схлопнулась: bulge должен быть больше толщины дисков.")
    inner_transition_r = inner_radius * math.sin(iris_angle)
    inner_transition_y = -inner_radius * math.cos(iris_angle)
    outer_radius = radius + bulge
    outer_transition_r = outer_radius * math.sin(iris_angle)
    outer_transition_y = -outer_radius * math.cos(iris_angle)
    if outer_transition_r >= aperture:
        raise GeometryError("Роговица должна быть шире радужки.")

    def smooth(q: float) -> float:
        q = min(1.0, max(0.0, q))
        return q * q * (3.0 - 2.0 * q)

    def outer(r: float) -> float:
        if r <= outer_transition_r:
            return -math.sqrt(max(1e-9, outer_radius * outer_radius - r * r))
        q = smooth((r - outer_transition_r) / (aperture - outer_transition_r))
        return outer_transition_y + (outer_rim - outer_transition_y) * q

    def inner(r: float) -> float:
        if r <= inner_transition_r:
            return -math.sqrt(max(1e-9, inner_radius * inner_radius - r * r))
        q = smooth((r - inner_transition_r) / (aperture - inner_transition_r))
        return inner_transition_y + (inner_rim - inner_transition_y) * q

    # Проверяем всю радиальную пару кривых, а не только центр и кромку:
    # между ними обязана оставаться положительная толщина.
    for i in range(101):
        r = aperture * i / 100.0
        if inner(r) - outer(r) <= 1e-5:
            raise GeometryError("Роговица схлопнулась между радужкой и кромкой; увеличьте bulge.")
    steps = 40
    profile = [(aperture * i / steps, outer(aperture * i / steps))
               for i in range(steps + 1)]
    profile.extend((aperture * i / steps, inner(aperture * i / steps))
                   for i in range(steps, -1, -1))
    return _revolve_profile(profile, segments, "роговицы").rotate((-90.0, 0.0, 0.0))


def _optical_part(a, main: Solid, suffix: str, manifold: mf.Manifold, kind: str,
                  color: str, rough: float, transmission: float = 0.0) -> Solid:
    part = Solid(name=f"{main.name}_{suffix}", manifold=manifold, color=color,
                 metal=0.0, rough=rough, transmission=transmission, kind=kind,
                 op=a.spec.name, line=a.cmd.line)
    part.meta["axes"] = [list(row) for row in main.meta.get("axes", np.eye(3).tolist())]
    part.meta["eyeball"] = main.name
    return a.scene.add(part)


@op("eyeball", aliases=("глазное_яблоко", "глаз_анатомический", "eye_ball", "ocular"),
    category="Примитивы",
    summary="Анатомическое глазное яблоко лицом в −Y: сфера склеры, два "
            "сферических диска радужки и зрачка и выпуклая прозрачная роговица. "
            "Это четыре независимых объёма с разными материалами, а не лицевой "
            "примитив «глаз» и не плоская текстура. Диски слегка перекрываются "
            "внутри, поэтому кромки не расходятся и не мерцают.",
    example="глаз = eyeball diameter=24 iris=11 pupil=4.6\n"
            "глаз = глазное_яблоко diameter=26 iris=12 pupil=5 bulge=0.8 iris_color=#4b8b7b",
    params={"diameter": "диаметр склеры, мм (24)",
            "iris": "диаметр радужки, мм (11)",
            "pupil": "диаметр зрачка, мм (4.6)",
            "cornea": "диаметр прозрачной роговицы, мм (авто 1.25 iris)",
            "bulge": "дополнительная выпуклость роговицы над дисками, мм (авто)",
            "cornea_t": "толщина роговицы у кромки, мм (авто 2.2% радиуса)",
            "sclera_color": "цвет склеры (#e9e6dc); общий color тоже работает",
            "iris_color": "цвет радужки (#467fa6)",
            "pupil_color": "цвет зрачка (#101318)",
            "segments": "сегментов вращения 24…192 (64)",
            "at": "положение центра по XY и низа по Z", "center": "at — центр склеры"},
    positional=["diameter"])
def eyeball(a, name):
    diameter = float(a.num("diameter", 24.0, minv=2.0, maxv=5000.0))
    radius = diameter / 2.0
    iris_d = float(a.num("iris", diameter * 11.0 / 24.0,
                         minv=0.2, maxv=diameter * 0.90))
    pupil_d = float(a.num("pupil", diameter * 4.6 / 24.0,
                          minv=0.1, maxv=iris_d * 0.95))
    cornea_d = float(a.num("cornea", iris_d * 1.25,
                           minv=iris_d * 1.02, maxv=diameter * 0.96))
    iris_t = max(0.06, radius * 0.014)
    pupil_t = max(0.04, radius * 0.009)
    bulge = float(a.num("bulge", iris_t + pupil_t + max(0.10, radius * 0.025),
                        minv=0.05, maxv=radius))
    cornea_t = float(a.num("cornea_t", max(0.08, radius * 0.022),
                           minv=0.03, maxv=radius * 0.25))
    segments = int(a.int("segments", 64, minv=24, maxv=192) or 64)
    if pupil_d >= iris_d:
        raise GeometryError("eyeball: pupil должен быть меньше iris.")
    if cornea_d <= iris_d:
        raise GeometryError("eyeball: роговица должна перекрывать радужку по кромке.")

    iris_r, pupil_r, cornea_r = iris_d / 2.0, pupil_d / 2.0, cornea_d / 2.0
    # Склера и все оптические слои строятся вокруг одного центра. Радужка
    # погружена в склеру на 0.08 мм, зрачок — в радужку на 0.04 мм.
    sclera = mf.Manifold.sphere(radius, segments)
    iris = _spherical_disc(radius, math.asin(iris_r / radius),
                           -min(0.08, radius * 0.01), iris_t, segments, "радужки")
    pupil = _spherical_disc(radius, math.asin(pupil_r / radius),
                            iris_t - min(0.04, iris_t * 0.3), iris_t + pupil_t,
                            segments, "зрачка")
    cornea = _cornea(radius, cornea_r, bulge, cornea_t, iris_t + pupil_t,
                     math.asin(iris_r / radius), segments)
    sclera, iris, pupil, cornea = _anchor_all(a, [sclera, iris, pupil, cornea])

    main = make_solid(a.scene, name, sclera, a, kind="eyeball")
    style = a.style()
    main.color = style.get("color") or (a.text("sclera_color", "#e9e6dc") or "#e9e6dc")
    main.rough = 0.38
    main.meta.update(eyeball_parts=[f"{main.name}_радужка", f"{main.name}_зрачок",
                                     f"{main.name}_роговица"],
                     iris=iris_d, pupil=pupil_d, cornea=cornea_d, bulge=bulge)
    _optical_part(a, main, "радужка", iris, "eyeball_iris",
                  a.text("iris_color", "#467fa6") or "#467fa6", 0.28)
    _optical_part(a, main, "зрачок", pupil, "eyeball_pupil",
                  a.text("pupil_color", "#101318") or "#101318", 0.20)
    _optical_part(a, main, "роговица", cornea, "eyeball_cornea",
                  "#dceeff", 0.025, transmission=1.0)
    main.notes.append(f"глазное яблоко ø{diameter:g} мм; радужка ø{iris_d:g}, "
                      f"зрачок ø{pupil_d:g}, роговица ø{cornea_d:g} мм")
    main.notes.append("склера, радужка, зрачок и роговица — четыре объекта; "
                      "лицо смотрит в −Y, роговица имеет transmission=1")
    return main
