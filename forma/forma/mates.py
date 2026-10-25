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


def settle_gap(moving, base, target: float) -> float:
    """Зазор после доводки, мм (для остатка связи)."""
    value = _gap_try(moving, base, max(float(target) * 3.0, 600.0))
    return 0.0 if value is None else value


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


def _gap_try(a, b, search: float = 600.0) -> float | None:
    try:
        return float(a.manifold.min_gap(b.manifold, search))
    except Exception:
        return None


def _proj_overlap(a, b, idx: int, tol: float = 0.05) -> bool:
    """Перекрываются ли проекции тел на две оси, поперечные движению.

    Если деталь стоит сбоку (например, «на плоскости» в стороне), зазор
    между телами — это диагональ, и подгонять его бессмысленно: тогда
    положение задаёт уровень грани, а не близость поверхностей.
    """
    for k in range(3):
        if k == idx:
            continue
        if min(a[3 + k], b[3 + k]) - max(a[k], b[k]) <= tol:
            return False
    return True


def _overlap(a, b) -> bool:
    """Пересекаются ли тела (не «касаются», а именно входят друг в друга)."""
    try:
        return float((a.manifold ^ b.manifold).volume()) > 1e-6
    except Exception:
        return False


def _nudge(solid, idx: int, delta: float) -> None:
    if abs(delta) < 1e-12:
        return
    vec = [0.0, 0.0, 0.0]
    vec[idx] = float(delta)
    move(solid, vec)


def settle(moving, base, idx: int, target: float) -> float:
    """Доводит РЕАЛЬНЫЙ зазор между телами до target, двигая вдоль оси idx.

    Раньше сопряжение считалось по габаритным коробкам и делало ровно один
    шаг: если детали уже пересекались, `min_gap` возвращал 0, поправка
    съедалась, и зазор не доходил до заданного. Здесь всё считается по
    фактической геометрии: деталь выводится из пересечения, подводится к
    контакту шагами «не больше зазора», а потом зазор уточняется бисекцией.
    Поэтому повёрнутое основание и фигурная деталь встают точно, а не
    «коробка на коробку».

    Возвращает суммарный сдвиг по оси, мм.
    """
    target = max(float(target), 0.0)
    search = max(target * 3.0, 600.0)
    total = 0.0

    def shift(delta: float) -> None:
        nonlocal total
        _nudge(moving, idx, delta)
        total += delta

    def goto(pos: float) -> None:
        shift(pos - total)

    def gap_now() -> float:
        value = _gap_try(moving, base, search)
        return 0.0 if value is None else max(float(value), 0.0)

    def inside() -> bool:
        return _overlap(moving, base)

    centre_diff = _center(_box(moving))[idx] - _center(_box(base))[idx]
    away = 1.0 if centre_diff >= 0 else -1.0
    box_m, box_b = _box(moving), _box(base)
    stride = max(0.5, 0.25 * min(box_m[3 + idx] - box_m[idx],
                                 box_b[3 + idx] - box_b[idx]))
    limit = max(600.0, 4.0 * max(
        box_m[3 + idx] - box_m[idx], box_b[3 + idx] - box_b[idx]))

    # 1) вывести деталь из пересечения, если она уже вошла в основание
    if inside():
        step = min(stride, 1.0)
        for _ in range(60):
            shift(away * step)
            if not inside():
                break
            step = min(step * 1.6, limit)
        else:
            return total

    # 2) подвести к контакту (зазор ~0), не перескакивая тело
    prev = total
    inside_pos = None
    for _ in range(240):
        gap = gap_now()
        if inside():
            inside_pos = total
            goto(prev)
            break
        if gap <= 0.05:
            break
        step = min(gap + 0.25, stride)
        shift(-away * step)
        if inside():
            inside_pos = total
            goto(prev)
            break
        new_gap = gap_now()
        if new_gap >= gap:              # деталь ушла мимо основания
            goto(prev)
            break
        prev = total

    # 3) уточняем границу контакта бисекцией «внутри / снаружи»
    if inside_pos is not None:
        lo, hi = inside_pos, prev
        for _ in range(34):
            mid = (lo + hi) / 2.0
            goto(mid)
            if inside():
                lo = mid
            else:
                hi = mid
            if abs(hi - lo) < 0.002:
                break
        goto(hi)

    if target <= 0.02:
        return total

    # 4) отводим на нужный зазор и уточняем бисекцией
    for _ in range(12):
        g = gap_now()
        if abs(g - target) <= 0.01:
            return total
        shift(away * (target - g))
        if inside() and g > target:
            # перестарались — назад на половину
            shift(-away * (target - g) * 0.5)
            continue
    g = gap_now()
    if abs(g - target) > 0.01:
        # бисекция по положению между «мало» и «много»
        lo, hi = total, None
        step = max(abs(target - g), 1.0)
        for _ in range(40):
            shift(away * step)
            gg = gap_now()
            if gg >= target and not inside():
                hi = total
                break
            lo = total
            step *= 1.6
        if hi is not None:
            for _ in range(40):
                mid = (lo + hi) / 2.0
                goto(mid)
                gg = gap_now()
                if abs(gg - target) <= 0.01:
                    break
                if inside() or gg < target:
                    lo = mid
                else:
                    hi = mid
                if abs(hi - lo) < 0.002:
                    break
    return total


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
        # у повёрнутого основания верх габарита — это угол, а не грань:
        # доводим положение по фактическому контакту тел (только если деталь
        # действительно стоит над основанием, а не сбоку от него)
        if _proj_overlap(_box(moving), _box(base), idx):
            moved[idx] += settle(moving, base, idx, offset)
            residual = abs(settle_gap(moving, base, offset) - offset)
        else:
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
        if _proj_overlap(_box(moving), _box(base), 2):
            moved[2] += settle(moving, base, 2, offset)
            seat = abs(settle_gap(moving, base, offset) - offset)
        else:
            seat = abs(_box(moving)[2] - (bb[5] + offset))
        after = _box(moving)
        cm2 = _center(after)
        residual = max([seat]
                       + [abs(cm2[k] - cbase[k]) for k in range(3) if k != idx and k != 2])
    elif kind == "gap":
        # Зазор задаётся реальным расстоянием между телами, а не коробками:
        # шаг повторяется, пока не получится ровно offset. Если детали уже
        # пересекались, прежняя версия делала один шаг и недолетала.
        moved[idx] = settle(moving, base, idx, offset)
        residual = abs(settle_gap(moving, base, offset) - offset)
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
        offset = record.get("offset", 0.0)
        if _proj_overlap(_box(moving), _box(base), idx):
            return abs(settle_gap(moving, base, offset) - offset)
        return abs(_box(moving)[idx] - (_box(base)[3 + idx] + offset))
    if kind == "axis":
        cb, cm = _center(_box(base)), _center(_box(moving))
        return max(abs(cm[k] - cb[k]) for k in range(3) if k != idx)
    if kind == "slot":
        offset = record.get("offset", 0.0)
        if _proj_overlap(_box(moving), _box(base), 2):
            return abs(settle_gap(moving, base, offset) - offset)
        return abs(_box(moving)[2] - (_box(base)[5] + offset))
    if kind == "gap":
        return abs(settle_gap(moving, base, record.get("offset", 0.0))
                   - record.get("offset", 0.0))
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
