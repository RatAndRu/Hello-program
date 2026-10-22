"""Команда сопряжения: деталь ставится на место отношением, а не координатами."""

from __future__ import annotations

from .errors import DslError
from .mates import KIND_RU, apply, describe, parse_kind
from .ops import op


@op("сопряжение", aliases=("соединить", "привязать", "mate"), category="Массивы и преобразования",
    summary="Ставит деталь на место отношением: плоскость к плоскости, на ось, в паз-рейку, "
            "с зазором, точкой или вокруг петли. Программа сама сдвигает деталь и запоминает связь, "
            "а `check имя связь` следит, чтобы связь не разъехалась после правок.",
    example="колесо = wheel diameter=120 width=24 rim=12 spokes=3 hub=30\n"
            "рейка = box size=[64, 400, 11] center=да at=[0, 0, 100]\n"
            "сопряжение колесо рейка type=паз axis=y\n"
            "check колесо связь",
    params={"target": "какая деталь встаёт на место (подвижная)",
            "base": "к чему ставим (основание)",
            "type": "плоскость, ось, паз, зазор, точка, петля",
            "axis": "ось сопряжения: x, y или z",
            "offset": "отступ или зазор в мм",
            "point": "точка на оси петли или точка детали [x,y,z]",
            "to": "куда должна попасть точка — [x,y,z]",
            "angle": "поворот вокруг петли в градусах"},
    positional=["target", "base"])
def mate(a, name):
    target = (a.text("target") or "").strip()
    base = (a.text("base") or "").strip()
    if not target or not base:
        raise DslError("Укажите две детали: сопряжение колесо рейка type=паз axis=y",
                       hint="Первая — что ставим, вторая — к чему ставим.",
                       line=a.cmd.line, command=a.cmd.text)
    kind = parse_kind(a.text("type") or a.text("kind") or "плоскость")
    moving = a.scene.resolve(target)
    other = a.scene.resolve(base)
    axis = (a.text("axis") or "z").strip().lower()
    offset = a.num("offset", 0.0) or 0.0
    angle = a.num("angle", 0.0) or 0.0
    point = a.vec("point", dims=3)
    to = a.vec("to", dims=3)
    if kind == "hinge" and point is None:
        raise DslError("Для петли укажите точку оси: point=[x, y, z]",
                       hint="сопряжение дверь корпус type=петля axis=z point=[-486, -212, 0] angle=30",
                       line=a.cmd.line, command=a.cmd.text)
    record = apply(a.scene, moving, other, kind, axis=axis, offset=offset,
                   point=point, target_point=to, angle=angle, line=a.cmd.line)
    a.scene.log("info", "сопряжение: " + describe(record), a.cmd.line)
    return moving
