"""Воронка — конус с носком, сквозным каналом и настоящей стенкой.

Собирается вращением **замкнутого профиля**: снаружи конус и трубка, изнутри
то же самое с отступом на стенку. Поэтому это одна герметичная деталь, а не
«конус минус конус»: кромка сверху открыта, канал в носке сквозной, стенка
одинаковая по всей высоте.

    воронка = воронка top=120 bottom=16 height=80 spout=40 wall=3
    сопло = воронка top=60 bottom=8 height=50 spout=25 wall=2 lip=1.5
"""

from __future__ import annotations

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import anchor, make_solid, op
from .shape_features import apply_smooth


@op("воронка", aliases=("funnel", "лейка_воронка", "конус_воронка", "сыпучка"),
    category="Примитивы",
    summary="Воронка: широкий конус сверху, трубка-носок снизу, сквозной канал "
            "и стенка заданной толщины. Кромка сверху открыта, снизу канал "
            "проходит насквозь — деталь герметична и печатается. Для кухни, "
            "засыпки, маслёнки, сопла. low — низ детали на z=0, носок вниз.",
    example="воронка = воронка top=120 bottom=16 height=80 spout=40 wall=3\n"
            "сопло = воронка top=60 bottom=8 height=50 spout=25 wall=2 lip=1.5\n"
            "кухонная = воронка top=150 bottom=20 height=70 spout=35 wall=2.5 "
            "at=[0,0,120]",
    params={"top": "диаметр широкой части сверху, мм (120)",
            "bottom": "наружный диаметр носка, мм (16)",
            "height": "высота конуса, мм (80)",
            "wall": "толщина стенки, мм (3)",
            "spout": "длина трубки-носка, мм (40)",
            "lip": "выступ верхнего бортика наружу, мм (2.5; 0 — без бортика)",
            "rim": "то же, что lip — как у короны",
            "rim_height": "высота верхнего бортика, мм (0.5·lip), как у короны",
            "smooth": "уровни Loop-сглаживания всей воронки 0…4 (0)",
            "segments": "сегментов по кругу (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]: низ носка на z=0",
            "center": "центрировать по высоте"})
def funnel(a, name):
    top = float(a.num("top", 120.0, minv=2.0, maxv=5000.0))
    bottom = float(a.num("bottom", 16.0, minv=0.6, maxv=5000.0))
    height = float(a.num("height", 80.0, minv=1.0, maxv=5000.0))
    wall = float(a.num("wall", 3.0, minv=0.2, maxv=1000.0))
    spout = float(a.num("spout", 40.0, minv=0.0, maxv=5000.0))
    lip = float(a.num("lip", 2.5, minv=0.0, maxv=1000.0))
    rim_value = a.num("rim", None, minv=0.0, maxv=1000.0)
    if rim_value is not None:
        lip = float(rim_value)
    rim_h = float(a.num("rim_height", max(0.0, lip * 0.5), minv=0.0,
                         maxv=1000.0) or 0.0)
    if lip > 1e-6 and rim_h <= 1e-6:
        rim_h = lip * 0.5
    detail = int(a.num("detail", 3, minv=0, maxv=5))
    at = a.vec("at", 3, default=(0.0, 0.0, 0.0))
    center = a.boolean("center", False)

    if bottom > top:
        raise GeometryError("воронка: носок шире верха — это уже не воронка.",
                            hint="bottom — диаметр трубки снизу, top — широкий верх.")
    r_out = bottom / 2.0
    R_out = top / 2.0
    if wall >= r_out - 0.15:
        limit = max(0.2, r_out - 0.3)
        raise GeometryError(
            f"воронка: стенка {wall:g} мм не оставляет канала в носке "
            f"(Ø {bottom:g} мм).",
            hint=f"Уменьшите wall до {limit:.2f} мм или увеличьте bottom.")
    if wall >= R_out - 0.3:
        raise GeometryError("воронка: стенка почти съела широкую часть.",
                            hint="Уменьшите wall или увеличьте top.")
    ri = r_out - wall
    Ri = R_out - wall
    H = spout + height

    profile = [[r_out, 0.0], [r_out, spout], [R_out, H]]
    if lip > 1e-6:
        # Прямой бортик как у короны: наружный выступ и плоская верхняя
        # кромка на H+rim_height; полость доходит до той же плоскости.
        profile += [[R_out + lip, H], [R_out + lip, H + rim_h],
                    [Ri, H + rim_h], [Ri, H]]
    else:
        rim_h = 0.0
        profile.append([Ri, H])
    profile += [[ri, spout], [ri, 0.0]]

    segments = a.int("segments", None, minv=12, maxv=512)
    if segments is None:
        segments = int(np.clip(36 * (1.0 + 0.35 * detail) * (R_out / 60.0) ** 0.35
                               + 12, 32, 240))

    cs = mf.CrossSection([np.asarray(profile, dtype=np.float64)])
    solid = mf.Manifold.revolve(cs, int(segments))
    solid = apply_smooth(solid, a, "воронка")
    if solid.is_empty() or solid.volume() <= 0:
        raise GeometryError("воронка не построилась.", hint="Проверьте top/bottom/wall.")

    solid = anchor(solid, at, center)
    a.scene.log("info", f"воронка: верх Ø{top:g}, носок Ø{bottom:g}, стенка {wall:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    made = make_solid(a.scene, name, solid, a, kind="воронка")
    made.notes.append(f"воронка Ø{top:g}→Ø{bottom:g}, высота {H:g} мм, "
                      f"стенка {wall:g} мм")
    return made
