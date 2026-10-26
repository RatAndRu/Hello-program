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
from .ops_shape import _parts_follow

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


# --------------------------------------------------------------------------- #
#  Отношения осей двух деталей
# --------------------------------------------------------------------------- #
def _local_axis(a, key: str, default: str = "top") -> np.ndarray:
    """Ось в ЛОКАЛЬНЫХ координатах: x/y/z, верх/перёд/право или вектор."""
    if not a.has(key):
        return np.asarray(orient.SIDE_VECTORS[default], dtype=np.float64)
    raw = (a.text(key) or "").strip().lower()
    side = orient.side_key(raw)
    if side in orient.SIDE_VECTORS and side != "center":
        return np.asarray(orient.SIDE_VECTORS[side], dtype=np.float64)
    vec = _direction(a, key)
    if vec is None or float(np.linalg.norm(vec)) < 1e-9:
        raise GeometryError(f"{key}: направление не задано или нулевое.",
                            hint="Например: axis=top, axis=x или axis=[1,0,1].")
    return np.asarray(vec, dtype=np.float64)


def _unit(vec, what: str) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-9:
        raise GeometryError(f"{what}: нулевое направление.")
    return arr / norm


def _perpendicular_target(host_direction: np.ndarray, requested) -> np.ndarray:
    """Направление в плоскости, перпендикулярной оси хозяина.

    По умолчанию берём проекцию мирового +Z («как можно ближе к верху»).
    Если ось вертикальна, последовательно пробуем перед −Y и право +X.
    """
    if requested is not None:
        candidates = [_unit(requested, "direction")]
    else:
        candidates = [np.array([0.0, 0.0, 1.0]),
                      np.array([0.0, -1.0, 0.0]),
                      np.array([1.0, 0.0, 0.0])]
    for candidate in candidates:
        projected = candidate - host_direction * float(np.dot(candidate, host_direction))
        if float(np.linalg.norm(projected)) > 1e-8:
            return _unit(projected, "перпендикуляр")
    raise GeometryError("direction параллелен оси хозяина: перпендикуляр не определён.",
                        hint="Задайте другое direction, например direction=+x.")


def _align_axes(a, name, relation: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{relation} работает с одной деталью за раз.")
    part = solids[0]
    host_name = (a.text("on") or "").strip()
    if not host_name:
        raise GeometryError(f"{relation}: укажите on=имя_хозяина.")
    host = a.scene.resolve(host_name)
    if host is part:
        raise GeometryError(f"{relation}: деталь и хозяин должны быть разными.")

    part_axis = _local_axis(a, "axis", "top")
    host_axis = _local_axis(a, "host_axis", "top")
    A = orient.axes_of(part)
    H = orient.axes_of(host)
    source = _unit(A @ part_axis, "axis детали")
    host_direction = _unit(H @ host_axis, "ось хозяина")
    if relation == "parallel":
        target = host_direction
    else:
        target = _perpendicular_target(host_direction, _direction(a, "direction"))
    if a.boolean("flip", False):
        target = -target
    R = orient.rotation_between(source, target)

    pivot = orient.bbox_center(part.manifold)
    mat = np.hstack([R, (pivot - R @ pivot).reshape(3, 1)])

    def _turn(m):
        return m.transform(np.ascontiguousarray(mat, dtype=np.float64))

    moved = _turn(part.manifold)
    _parts_follow(a, part, _turn, rotation=R)
    made = make_solid(a.scene, name, moved, a, base=part, kind=relation)
    a.scene.consume(part)
    orient.set_axes(made, R @ A)
    made.meta["axis_relation"] = {
        "kind": relation, "host": host.name,
        "axis": (a.text("axis") or "top"),
        "host_axis": (a.text("host_axis") or "top"),
        "direction": [float(x) for x in target],
    }
    check = float(np.dot(_unit((R @ A) @ part_axis, "результат"), host_direction))
    if relation == "parallel" and abs(abs(check) - 1.0) > 1e-6:
        raise GeometryError("parallel: не удалось совместить оси.")
    if relation == "perpendicular" and abs(check) > 1e-6:
        raise GeometryError("perpendicular: оси не получились перпендикулярными.")
    a.scene.log("info", f"{relation}: {part.name} относительно {host.name}; "
                        f"центр детали сохранён, ось → "
                        f"{orient.describe_direction(target)}", a.cmd.line)
    return made


@op("parallel", aliases=("параллельно", "параллельность", "align_parallel"),
    category="Массивы и преобразования",
    summary="Разворачивает выбранную локальную ось детали параллельно локальной "
            "оси другой детали. axis — ось детали, host_axis — ось хозяина; "
            "можно писать x/y/z, верх/перёд/право или вектор. Центр не двигается, "
            "лишний оборот вокруг оси не добавляется; flip=да даёт антипараллельность.",
    example="стойка = cylinder radius=8 height=80\n"
            "стойка = rotate [стойка] angle=90 axis=x\n"
            "рейка = box size=[60,12,12]\n"
            "рейка = parallel [рейка] on=стойка axis=top host_axis=top",
    params={"objects": "деталь", "on": "объект-хозяин",
            "axis": "локальная ось детали: top/верх (по умолчанию), front/перёд, "
                    "right/право, x/y/z или [x,y,z]",
            "host_axis": "локальная ось хозяина, те же значения (top)",
            "flip": "направить против оси хозяина, да/нет (нет)"},
    positional=["objects"])
def parallel(a, name):
    return _align_axes(a, name, "parallel")


@op("perpendicular", aliases=("перпендикулярно", "перпендикулярность",
                              "align_perpendicular"),
    category="Массивы и преобразования",
    summary="Разворачивает локальную ось детали перпендикулярно локальной оси "
            "другой детали. direction задаёт мировое направление результата и "
            "проецируется в перпендикулярную плоскость. Без direction выбирается "
            "проекция +Z; для вертикальной оси — −Y, затем +X. Центр сохраняется.",
    example="основа = cylinder radius=20 height=80\n"
            "планка = box size=[70,10,16] at=[100,0,40]\n"
            "планка = perpendicular [планка] on=основа axis=top host_axis=top direction=+x",
    params={"objects": "деталь", "on": "объект-хозяин",
            "axis": "локальная ось детали (top/верх)",
            "host_axis": "локальная ось хозяина (top/верх)",
            "direction": "мировое направление результата: +x, −y, +z или [x,y,z]; "
                         "проецируется в плоскость, перпендикулярную оси хозяина",
            "flip": "обратить полученное направление, да/нет (нет)"},
    positional=["objects"])
def perpendicular(a, name):
    return _align_axes(a, name, "perpendicular")
