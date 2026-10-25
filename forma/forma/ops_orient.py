"""Ориентация детали: где у неё верх, перёд и бока после поворотов.

`rotate` запекает поворот в геометрию, и «верх» детали перестаёт быть +Z.
Нейросеть (и человек) по числам этого не видит, поэтому здесь есть команда
`ориентация`: она показывает, куда смотрят локальные оси, где центр габарита
и где центр массы — и предупреждает, если центр габарита попал в пустоту
(у тора, воронки, кольца коробка внутри пустая).

    кольцо = torus major=40 minor=8
    кольцо = rotate [кольцо] angle=90 axis=x
    ориентация кольцо
    # верх +Y, перёд −Z, право +X; центр габарита в пустоте

Верх и перёд можно и **задать** — если деталь пришла из другого редактора:

    ориентация [деталь] верх=+x перед=-y
"""

from __future__ import annotations

import numpy as np

from . import orient
from .errors import GeometryError
from .ops import make_solid, op

_WORDS = {
    "x": (1.0, 0.0, 0.0), "+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0), "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0),
    "z": (0.0, 0.0, 1.0), "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0),
    "вверх": (0.0, 0.0, 1.0), "вниз": (0.0, 0.0, -1.0),
    "право": (1.0, 0.0, 0.0), "лево": (-1.0, 0.0, 0.0),
    "перед": (0.0, -1.0, 0.0), "перёд": (0.0, -1.0, 0.0), "зад": (0.0, 1.0, 0.0),
}


def _direction(a, key: str):
    raw = (a.text(key) or "").strip().lower().replace(" ", "")
    if not raw:
        return None
    if raw in _WORDS:
        return np.array(_WORDS[raw], dtype=np.float64)
    vec = a.vec(key, 3, default=None)
    if vec is None:
        raise GeometryError(f"ориентация: непонятное направление «{raw}».",
                            hint="Пишите x, -x, y, -y, z, -z или вектор [x, y, z].")
    return np.asarray(vec, dtype=np.float64)


@op("ориентация", aliases=("стороны", "orientation", "куда_смотрит", "axes",
                           "разметка_сторон"),
    category="Проверка",
    summary="Показывает, куда смотрят верх, низ, бока и перёд детали после "
            "поворотов, где центр габарита и где центр массы. Предупреждает, "
            "если центр габарита попал в пустоту (тор, воронка, кольцо). "
            "Можно и задать стороны: верх=+x перед=-y — памятка сохранится "
            "для относительной посадки. Ничего не двигает.",
    example="кольцо = torus major=40 minor=8\n"
            "кольцо = rotate [кольцо] angle=90 axis=x\n"
            "ориентация кольцо\n"
            "деталь = box size=[30,20,10]\n"
            "ориентация [деталь] верх=+x перед=-y",
    params={"objects": "деталь",
            "верх": "куда смотрит верх детали: x, -x, y, -y, z, -z или [x,y,z]",
            "перед": "куда смотрит перёд: то же (нужен вместе с верх)",
            "печать": "вывести разбор в отчёт, да (да)"},
    positional=["objects"])
def orientation(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("ориентация смотрит одну деталь за раз.",
                            hint="Формат: ориентация кольцо")
    base = solids[0]
    up = _direction(a, "верх")
    front = _direction(a, "перед")
    if (up is None) != (front is None):
        raise GeometryError("ориентация: верх и перёд задаются вместе.",
                            hint="Например: ориентация [деталь] верх=+x перед=-y")
    notes = list(base.notes)
    made = make_solid(a.scene, name or base.name, base.manifold, a, base=base,
                      kind="ориентация")
    made.notes[:] = notes
    if up is not None and front is not None:
        try:
            matrix = orient.basis(up, front)
        except ValueError as exc:
            raise GeometryError(f"ориентация: {exc}") from exc
        orient.set_axes(made, matrix)
        made.notes.append("стороны заданы вручную")
        a.scene.log("info",
                    f"ориентация {made.name}: верх {orient.describe_direction(matrix[:, 2])}, "
                    f"перёд {orient.describe_direction(-matrix[:, 1])}", a.cmd.line)
        made.meta["orientation"] = orient.report(made)
        return made

    data = orient.report(made)
    made.meta["orientation"] = data
    made.notes.append("ориентация: " + ", ".join(
        f"{key} {value}" for key, value in data["faces"].items()))
    if a.boolean("печать", True):
        faces = ", ".join(f"{key} {value}" for key, value in data["faces"].items())
        center = data["bbox_center"]
        mass = data["mass_center"]
        text = (f"ориентация {made.name}: {faces}; поворот: {data['rotation']}. "
                f"Центр габарита ({center[0]:g}, {center[1]:g}, {center[2]:g})")
        if data["center_empty"]:
            text += " — в пустоте (полость внутри габарита)"
        text += (f"; центр массы ({mass[0]:g}, {mass[1]:g}, {mass[2]:g})")
        a.scene.log("info", text, a.cmd.line)
    return made
