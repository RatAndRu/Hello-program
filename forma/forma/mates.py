"""Сопряжения: деталь ставится на место отношением, а не координатами.

Это не деформация (как Shrinkwrap в Blender), а ограничение сборки — как
«mates» в SolidWorks/Fusion: сказали «колесо на рейку», «дверь на петлю»,
«плоскость к плоскости» — программа сама сдвинула деталь и запомнила связь.

Каждое сопряжение после пересборки проверяется: остаток (residual) должен
быть нулевым, иначе `check имя связь` покажет красную строку.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .errors import DslError, FormaError

KINDS = {
    "плоскость": "plane", "plane": "plane",
    "ось": "axis", "axis": "axis",
    "паз": "slot", "slot": "slot",
    "зазор": "gap", "gap": "gap",
    "точка": "point", "point": "point",
    "петля": "hinge", "hinge": "hinge",
}

KIND_RU = {"plane": "плоскость", "axis": "ось", "slot": "паз", "gap": "зазор",
           "point": "точка", "hinge": "петля"}

AXES = {"x": 0, "y": 1, "z": 2}


def parse_kind(raw: str) -> str:
    key = (raw or "плоскость").strip().lower()
    if key not in KINDS:
        raise DslError(
            f"Неизвестное сопряжение «{raw}».",
            hint="Доступно: плоскость, ось, паз, зазор, точка, петля",
        )
    return KINDS[key]


def _box(solid) -> list[float]:
    return [float(v) for v in solid.bbox]


def _center(box: list[float]) -> list[float]:
    return [(box[0] + box[3]) / 2, (box[1] + box[4]) / 2, (box[2] + box[5]) / 2]


def _gap(a, b) -> float:
    """Точный зазор между телами (мм), с ограничением поиска."""
    try:
        return float(a.manifold.min_gap(b.manifold, 400.0))
    except Exception:
        return 0.0


def point_gap(solid, point, probe: float = 0.05) -> float:
    """Расстояние от точки до поверхности тела (0, если точка внутри)."""
    p = [float(v) for v in point]
    try:
        from manifold3d import Manifold
        ball = Manifold.sphere(probe, 8).translate(p)
        gap = float(ball.min_gap(solid.manifold, 400.0))
    except Exception:
        return 0.0
    return 0.0 if gap <= 1e-6 else gap + probe


def anchor_of(solid, point) -> list[float]:
    """Смещение точки от нижнего угла габарита — чтобы точка «ехала» с телом."""
    bb = _box(solid)
    return [float(point[k]) - bb[k] for k in range(3)]


def anchor_now(solid, anchor) -> list[float]:
    bb = _box(solid)
    return [bb[k] + float(anchor[k]) for k in range(3)]


def move(solid, delta) -> None:
    """Сдвигает тело и сбрасывает кэш габаритов."""
    d = [float(x) for x in delta]
    if max(abs(x) for x in d) < 1e-9:
        return
    solid.manifold = solid.manifold.translate(d)
    solid._stats = None


def rotate_about(solid, point, axis: str, angle_deg: float) -> None:
    """Поворот вокруг оси через точку (мировые координаты, Z вверх)."""
    if abs(angle_deg) < 1e-9:
        return
    idx = AXES[axis]
    rot = np.eye(3)
    c = math.cos(math.radians(angle_deg))
    s = math.sin(math.radians(angle_deg))
    i, j = [k for k in range(3) if k != idx]
    rot[i, i] = c
    rot[i, j] = -s
    rot[j, i] = s
    rot[j, j] = c
    p = np.asarray(point, dtype=float)
    # Manifold принимает матрицу 3×4 (поворот + перенос), не 4×4.
    mat = np.hstack([rot, (p - rot @ p).reshape(3, 1)]).astype(np.float64)
    solid.manifold = solid.manifold.transform(mat)
    solid._stats = None


def apply(scene, moving, base, kind: str, axis: str = "z", offset: float = 0.0,
          point: Any = None, target_point: Any = None, angle: float = 0.0,
          line: int = 0) -> dict:
    """Ставит `moving` относительно `base` и возвращает запись сопряжения."""
    if moving.name == base.name:
        raise DslError("Деталь не может быть сопряжена сама с собой.",
                       hint="сопряжение колесо рейка type=паз axis=y")
    idx = AXES.get((axis or "z").lower())
    if idx is None:
        raise DslError(f"Ось «{axis}» неизвестна.", hint="Ось: x, y или z")

    before = _box(moving)
    moved = [0.0, 0.0, 0.0]
    residual = 0.0

    if kind == "plane":
        bb = _box(base)
        target = bb[3 + idx] + offset
        delta = target - before[idx]
        moved[idx] = delta
        move(moving, moved)
        residual = abs(_box(moving)[idx] - target)
    elif kind == "axis":
        cb = _center(_box(base))
        cm = _center(before)
        for k in range(3):
            if k != idx:
                moved[k] = cb[k] - cm[k]
        move(moving, moved)
        cm2 = _center(_box(moving))
        residual = max(abs(cm2[k] - cb[k]) for k in range(3) if k != idx)
    elif kind == "slot":
        # Паз = рейка: деталь по центру рейки (в осях, поперечных движению)
        # и стоит на её верхней грани.
        bb = _box(base)
        cbase = _center(bb)
        cm = _center(before)
        for k in range(3):
            if k != idx and k != 2:
                moved[k] = cbase[k] - cm[k]
        moved[2] = bb[5] - before[2] + offset
        move(moving, moved)
        after = _box(moving)
        cm2 = _center(after)
        residual = max([abs(after[2] - (bb[5] + offset))]
                       + [abs(cm2[k] - cbase[k]) for k in range(3) if k != idx and k != 2])
    elif kind == "gap":
        current = _gap(moving, base)
        # Сдвигаем вдоль оси: знак определяем по положению центров.
        cm = _center(before)
        cb = _center(_box(base))
        sign = 1.0 if cm[idx] >= cb[idx] else -1.0
        delta = (offset - current) * sign
        moved[idx] = delta
        move(moving, moved)
        residual = abs(_gap(moving, base) - offset)
    elif kind == "point":
        if point is None or target_point is None:
            raise DslError("Для сопряжения «точка» нужны point= и target=.",
                           hint="сопряжение ручка корпус type=точка point=[0,0,0] target=[10,0,40]")
        p = [float(v) for v in point]
        q = [float(v) for v in target_point]
        moved = [q[k] - p[k] for k in range(3)]
        anchor = anchor_of(moving, p)
        move(moving, moved)
        residual = math.dist(anchor_now(moving, anchor), q)
    elif kind == "hinge":
        pivot = [float(v) for v in point] if point else _center(_box(base))
        rotate_about(moving, pivot, (axis or "z"), angle)
        residual = point_gap(moving, pivot)
    else:  # pragma: no cover
        raise DslError(f"Сопряжение «{kind}» не реализовано.")

    record = {
        "moving": moving.name,
        "base": base.name,
        "kind": kind,
        "kind_ru": KIND_RU.get(kind, kind),
        "axis": (axis or "z").lower(),
        "offset": float(offset),
        "moved": [round(v, 4) for v in moved],
        "residual": round(float(residual), 4),
        "angle": float(angle),
        "line": int(line or getattr(scene, "line", 0) or 0),
    }
    if kind == "point":
        record["anchor"] = [round(v, 4) for v in anchor]
        record["target"] = [round(float(v), 4) for v in target_point]
    if kind == "hinge":
        record["pivot"] = [round(float(v), 4) for v in pivot]
    scene.mates.append(record)
    return record


def residual_of(record: dict, scene) -> float:
    """Пересчитывает остаток связи по текущей геометрии."""
    try:
        moving = scene.resolve(record["moving"])
        base = scene.resolve(record["base"])
    except FormaError:
        return 999.0
    kind = record["kind"]
    idx = AXES.get(record.get("axis") or "z", 2)
    if kind == "plane":
        bb = _box(base)
        target = bb[3 + idx] + record.get("offset", 0.0)
        return abs(_box(moving)[idx] - target)
    if kind == "axis":
        cb, cm = _center(_box(base)), _center(_box(moving))
        return max(abs(cm[k] - cb[k]) for k in range(3) if k != idx)
    if kind == "slot":
        bb, cm = _box(base), _center(_box(moving))
        return max([abs(_box(moving)[2] - (bb[5] + record.get("offset", 0.0)))]
                   + [abs(cm[k] - _center(bb)[k]) for k in range(3) if k != idx and k != 2])
    if kind == "gap":
        return abs(_gap(moving, base) - record.get("offset", 0.0))
    if kind == "point":
        anchor = record.get("anchor")
        target = record.get("target")
        if not anchor or not target:
            return 0.0
        return math.dist(anchor_now(moving, anchor), [float(v) for v in target])
    if kind == "hinge":
        pivot = record.get("pivot")
        return point_gap(moving, pivot) if pivot else _gap(moving, base)
    return 0.0


def describe(record: dict) -> str:
    """Человеческая строка для журнала и панели связей."""
    off = record.get("offset") or 0.0
    tail = f", зазор {off:g} мм" if record["kind"] in ("gap", "plane", "slot") and off else ""
    ang = f", поворот {record['angle']:g}°" if record.get("angle") else ""
    return (f"«{record['moving']}» → «{record['base']}»: "
            f"{record.get('kind_ru', record['kind'])}{tail}{ang}, "
            f"остаток {record.get('residual', 0):.3f} мм")
