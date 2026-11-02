"""Двумерные аналитические контуры и адаптивная дискретизация.

Contour2D не является твёрдым телом и не попадает в GLB сам по себе. Он хранит
линии, дуги, эллипсы и квадратичные/кубические Bézier, а при использовании
отдаёт операциям детерминированные точки с заданным допуском хорды.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Sequence

import numpy as np

from .errors import GeometryError
from .geometry import FINENESS_MM, dedupe_points, polygon_area


def _as_point(value, what: str = "точка") -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (2,) or not np.all(np.isfinite(arr)):
        raise GeometryError(f"{what}: ожидались две конечные координаты.")
    return arr


def _chord_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    chord = end - start
    length2 = float(chord @ chord)
    if length2 < 1e-24:
        return float(np.linalg.norm(point - start))
    t = float(np.clip(((point - start) @ chord) / length2, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + t * chord)))


def _budget_error(max_points: int) -> GeometryError:
    return GeometryError(
        f"Contour2D: адаптивная выборка превысила max_points={max_points}.",
        hint="Увеличьте tolerance или max_points; слишком мелкий допуск не нужен для печати.")


def _adaptive_parametric(fn: Callable[[float], np.ndarray], t0: float, t1: float,
                         tolerance: float, max_points: int,
                         max_depth: int = 14) -> np.ndarray:
    """Выборка гладкой кривой с контролем четвертей хорды.

    Четверть, середина и три четверти проверяются с запасом 0.45·tolerance.
    При исчерпании глубины или бюджета команда падает честно, а не возвращает
    кривую с неизвестной ошибкой.
    """
    p0, p1 = fn(t0), fn(t1)
    out = [p0]

    def visit(left: float, right: float, pa: np.ndarray, pb: np.ndarray, depth: int):
        tm = (left + right) * 0.5
        tq = (left + tm) * 0.5
        ts = (tm + right) * 0.5
        pm, pq, ps = fn(tm), fn(tq), fn(ts)
        error = max(_chord_distance(pq, pa, pb),
                    _chord_distance(pm, pa, pb),
                    _chord_distance(ps, pa, pb))
        if error > tolerance * 0.45 and depth < max_depth:
            visit(left, tm, pa, pm, depth + 1)
            visit(tm, right, pm, pb, depth + 1)
            return
        if error > tolerance and depth >= max_depth:
            raise GeometryError(
                "Contour2D: не удалось достичь допуска адаптивной кривой.",
                hint="Увеличьте tolerance; возможно, сегмент вырожден или содержит петлю.")
        if len(out) >= max_points:
            raise _budget_error(max_points)
        out.append(pb)

    visit(t0, t1, p0, p1, 0)
    return np.asarray(out, dtype=np.float64)


def _split_bezier(control: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    left = [control[0]]
    right = [control[-1]]
    work = control.copy()
    while len(work) > 1:
        work = (work[:-1] + work[1:]) * 0.5
        left.append(work[0])
        right.append(work[-1])
    return np.asarray(left), np.asarray(right[::-1])


def _sample_bezier(control: np.ndarray, tolerance: float,
                   max_points: int, max_depth: int = 16) -> np.ndarray:
    if len(control) not in (3, 4):
        raise GeometryError("Bézier поддерживает 3 управляющие точки (квадратичная) "
                            "или 4 (кубическая).")
    out = [control[0]]

    def visit(points: np.ndarray, depth: int):
        error = max((_chord_distance(p, points[0], points[-1]) for p in points[1:-1]),
                    default=0.0)
        if error > tolerance and depth < max_depth:
            left, right = _split_bezier(points)
            visit(left, depth + 1)
            visit(right, depth + 1)
            return
        if error > tolerance and depth >= max_depth:
            raise GeometryError("Bézier: исчерпана глубина адаптивного подразделения.",
                                hint="Увеличьте tolerance или проверьте управляющие точки.")
        if len(out) >= max_points:
            raise _budget_error(max_points)
        out.append(points[-1])

    visit(control, 0)
    return np.asarray(out, dtype=np.float64)


def _sample_ellipse(center: np.ndarray, rx: float, ry: float, a0: float, a1: float,
                    tolerance: float, max_points: int) -> tuple[np.ndarray, bool]:
    if (not all(math.isfinite(v) for v in (rx, ry, a0, a1)) or rx <= 0 or ry <= 0):
        raise GeometryError("Contour2D: полуоси и углы эллипса должны быть конечными, полуоси > 0.")
    if abs(a1 - a0) < 1e-9 or abs(a1 - a0) > 360.0 + 1e-7:
        raise GeometryError("Contour2D: эллиптическая дуга должна иметь угол от 0 до 360°.")
    full = abs(abs(a1 - a0) - 360.0) < 1e-7
    intervals = 4 if full else 1

    def point(deg: float) -> np.ndarray:
        angle = math.radians(deg)
        return center + np.array([rx * math.cos(angle), ry * math.sin(angle)])

    chunks = []
    for index in range(intervals):
        start = a0 + (a1 - a0) * index / intervals
        end = a0 + (a1 - a0) * (index + 1) / intervals
        chunk = _adaptive_parametric(point, start, end, tolerance, max_points)
        chunks.append(chunk if index == 0 else chunk[1:])
    points = np.concatenate(chunks)
    if full:
        points = points[:-1]
    return points, full


def _sample_segment(segment: dict, tolerance: float,
                    max_points: int) -> tuple[np.ndarray, dict, bool]:
    kind = segment["kind"]
    if kind == "line":
        points = np.asarray(segment["points"], dtype=np.float64)
        if points.shape != (2, 2) or not np.all(np.isfinite(points)):
            raise GeometryError("Contour2D: линия должна содержать две конечные точки [x,y].")
        if float(np.linalg.norm(points[1] - points[0])) < 1e-12:
            raise GeometryError("Contour2D: линия имеет нулевую длину или неверные точки.")
        return points, {"kind": kind, "samples": 2}, False
    if kind == "arc":
        center = _as_point(segment["center"], "центр дуги")
        radius = float(segment["radius"])
        a0, a1 = float(segment["from"]), float(segment["to"])
        sweep = a1 - a0
        if (not math.isfinite(radius) or not math.isfinite(a0) or not math.isfinite(a1)
                or radius <= 0 or abs(sweep) < 1e-9):
            raise GeometryError("Contour2D: дуга требует конечный radius>0 и ненулевой угол.")
        if abs(sweep) > 360.0 + 1e-7:
            raise GeometryError("Contour2D: дуга не может быть длиннее одного оборота (360°).")
        full = abs(abs(sweep) - 360.0) < 1e-7
        effective_tolerance = min(tolerance, radius * 0.5)
        full_n = max(3, int(math.ceil(
            math.pi / math.acos(max(-1.0, 1.0 - effective_tolerance / radius)))))
        n = max(1, int(math.ceil(full_n * abs(sweep) / 360.0)))
        if n + (0 if full else 1) > max_points:
            raise _budget_error(max_points)
        angles = np.linspace(math.radians(a0), math.radians(a1), n,
                             endpoint=not full)
        if full:
            # endpoint=False выше уже дал n уникальных точек.
            pass
        else:
            angles = np.linspace(math.radians(a0), math.radians(a1), n + 1)
        points = center[None, :] + radius * np.stack([np.cos(angles), np.sin(angles)], axis=1)
        return points, {"kind": kind, "samples": len(points)}, full
    if kind == "ellipse":
        center = _as_point(segment["center"], "центр эллипса")
        rx, ry = float(segment["rx"]), float(segment["ry"])
        if rx <= 0 or ry <= 0:
            raise GeometryError("Contour2D: полуоси эллипса должны быть положительными.")
        points, full = _sample_ellipse(center, rx, ry, float(segment["from"]),
                                       float(segment["to"]), tolerance, max_points)
        return points, {"kind": kind, "samples": len(points)}, full
    if kind == "bezier":
        control = np.asarray(segment["points"], dtype=np.float64)
        if control.ndim != 2 or control.shape[1] != 2 or not np.all(np.isfinite(control)):
            raise GeometryError("Bézier: управляющие точки должны быть конечными [x,y].")
        points = _sample_bezier(control, tolerance, max_points)
        return points, {"kind": kind, "samples": len(points),
                        "degree": len(control) - 1}, False
    raise GeometryError(f"Contour2D: неизвестный сегмент «{kind}».")


@dataclass
class Contour2D:
    """Именованный аналитический контур, переиспользуемый операциями сцены."""

    name: str
    segments: list[dict]
    closed: bool = False
    tolerance: float = FINENESS_MM
    join_tolerance: float = 1e-5
    max_points: int = 4096
    start: list[float] | None = None
    plane: str = "xy"
    at: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self):
        if not self.segments:
            raise GeometryError("Contour2D: нужен хотя бы один сегмент.")
        if not math.isfinite(self.tolerance) or self.tolerance <= 0:
            raise GeometryError("Contour2D: tolerance должен быть положительным числом.")
        if not math.isfinite(self.join_tolerance) or self.join_tolerance < 0:
            raise GeometryError("Contour2D: join_tolerance не может быть отрицательным.")
        if not 4 <= int(self.max_points) <= 16384:
            raise GeometryError("Contour2D: max_points должен быть в диапазоне 4…16384.")
        self.max_points = int(self.max_points)
        if not isinstance(self.plane, str):
            raise GeometryError("Contour2D: plane должен быть xy, xz или yz.")
        self.plane = self.plane.lower()
        if self.plane not in ("xy", "xz", "yz"):
            raise GeometryError("Contour2D: plane должен быть xy, xz или yz.")
        try:
            self.at = tuple(float(v) for v in self.at)
        except (TypeError, ValueError) as exc:
            raise GeometryError("Contour2D: at должен быть вектором [x,y,z].") from exc
        if len(self.at) != 3 or not all(math.isfinite(v) for v in self.at):
            raise GeometryError("Contour2D: at должен содержать три конечные координаты.")
        if self.start is not None:
            self.start = _as_point(self.start, "start").tolist()

    def sample(self, tolerance: float | None = None,
               max_points: int | None = None) -> np.ndarray:
        tol = float(self.tolerance if tolerance is None else tolerance)
        budget = int(self.max_points if max_points is None else max_points)
        if tol <= 0 or not math.isfinite(tol):
            raise GeometryError("Contour2D: tolerance должен быть положительным.")
        if budget < 4:
            raise GeometryError("Contour2D: max_points должен быть не меньше 4.")
        output: list[np.ndarray] = []
        full_segment = False
        for index, segment in enumerate(self.segments):
            remaining = max(2, budget - len(output))
            points, _, closed_full = _sample_segment(segment, tol, remaining)
            if closed_full:
                if len(self.segments) != 1:
                    raise GeometryError("Полный эллипс/окружность нельзя вставить в середину контура.")
                full_segment = True
            if output:
                gap = float(np.linalg.norm(output[-1] - points[0]))
                if gap > self.join_tolerance:
                    raise GeometryError(
                        f"Contour2D: разрыв на стыке сегмента {index + 1}: {gap:g} мм.",
                        hint=f"Допуск стыка join_tolerance={self.join_tolerance:g} мм; "
                             "проверьте конец предыдущего и начало следующего сегмента.")
                points = points.copy()
                points[0] = output[-1]
                points = points[1:]
            elif self.start is not None:
                start = _as_point(self.start, "start")
                gap = float(np.linalg.norm(start - points[0]))
                if gap > self.join_tolerance:
                    raise GeometryError(
                        f"Contour2D: start не совпадает с началом первого сегмента ({gap:g} мм).")
                points = points.copy()
                points[0] = start
            output.extend(points)
            if len(output) > budget:
                raise _budget_error(budget)
        if not output:
            raise GeometryError("Contour2D: выборка пуста.")
        points = np.asarray(output, dtype=np.float64)
        if len(points) > 1 and np.linalg.norm(points[0] - points[-1]) <= self.join_tolerance:
            points = points[:-1]
        points = dedupe_points(points, tol=max(self.join_tolerance, 1e-9))
        if len(points) < 2:
            raise GeometryError("Contour2D: после сварки стыков осталось меньше двух точек.")
        return points

    @property
    def is_closed(self) -> bool:
        return bool(self.closed or any(
            s["kind"] in ("arc", "ellipse")
            and abs(abs(float(s["to"]) - float(s["from"])) - 360.0) < 1e-7
            for s in self.segments))

    def points3d(self) -> np.ndarray:
        points = self.sample()
        if self.plane == "xy":
            out = np.column_stack([points[:, 0], points[:, 1], np.zeros(len(points))])
        elif self.plane == "xz":
            out = np.column_stack([points[:, 0], np.zeros(len(points)), points[:, 1]])
        else:
            out = np.column_stack([np.zeros(len(points)), points[:, 0], points[:, 1]])
        return out + np.asarray(self.at, dtype=np.float64)[None, :]

    def sample_report(self) -> dict:
        points = self.sample()
        rows = []
        for segment in self.segments:
            sampled, report, _ = _sample_segment(segment, self.tolerance, self.max_points)
            rows.append(report)
        return {"points": len(points), "segments": rows,
                "closed": self.is_closed, "tolerance": self.tolerance,
                "join_tolerance": self.join_tolerance, "max_points": self.max_points}

    def measurements(self) -> dict:
        points = self.sample()
        closed = self.is_closed
        chain = np.vstack([points, points[0]]) if closed else points
        length = float(np.linalg.norm(np.diff(chain, axis=0), axis=1).sum())
        return {"bbox": [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()],
                "length": length,
                "area": abs(polygon_area(points)) if closed and len(points) >= 3 else 0.0,
                "points": len(points)}

    def signature(self) -> dict:
        return {"segments": self.segments, "closed": self.is_closed,
                "tolerance": self.tolerance, "join_tolerance": self.join_tolerance,
                "plane": self.plane, "at": list(self.at)}

    def to_dict(self) -> dict:
        return {"name": self.name, "type": "Contour2D",
                "signature": self.signature(), "sample": self.sample_report(),
                "measurements": self.measurements()}


def resolve_contour(scene, value) -> Contour2D | None:
    if isinstance(value, Contour2D):
        return value
    if isinstance(value, str):
        return getattr(scene, "contours", {}).get(value.strip())
    return None


def resample_closed_profile(points: np.ndarray, count: int) -> np.ndarray:
    """Равномерная по длине выборка замкнутого контура без повтора конца."""
    pts = dedupe_points(np.asarray(points, dtype=np.float64), tol=1e-9)
    if len(pts) < 3:
        raise GeometryError("Замкнутый профиль должен содержать минимум 3 точки.")
    ring = np.vstack([pts, pts[0]])
    lengths = np.linalg.norm(np.diff(ring, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    total = float(cumulative[-1])
    if total <= 1e-9:
        raise GeometryError("Замкнутый профиль имеет нулевую длину.")
    targets = np.linspace(0.0, total, int(count), endpoint=False)
    return np.stack([np.interp(targets, cumulative, ring[:, axis]) for axis in range(2)], axis=1)


def unify_closed_profiles(profiles: Sequence[np.ndarray],
                          max_points: int = 16384) -> list[np.ndarray]:
    """Общее число точек, ориентация и стартовая вершина для loft.

    Число точек не уменьшается молча: иначе тонкий tolerance на одном сечении
    был бы отброшен при сопоставлении с другим.
    """
    if len(profiles) < 2:
        return [np.asarray(profiles[0], dtype=np.float64)] if profiles else []
    cleaned = [dedupe_points(np.asarray(p, dtype=np.float64), tol=1e-9) for p in profiles]
    if any(len(p) < 3 or abs(polygon_area(p)) < 1e-9 for p in cleaned):
        raise GeometryError("Каждое сечение loft должно быть невырожденным замкнутым контуром.")
    sign = 1.0 if polygon_area(cleaned[0]) >= 0 else -1.0
    aligned = []
    reference = cleaned[0][0]
    for profile in cleaned:
        current = profile if polygon_area(profile) * sign >= 0 else profile[::-1].copy()
        index = int(np.argmin(np.linalg.norm(current - reference, axis=1)))
        aligned.append(np.roll(current, -index, axis=0))
    count = max(len(p) for p in aligned)
    if count > int(max_points):
        raise GeometryError(f"Сопоставление сечений требует {count} точек, "
                            f"а предел max_points={int(max_points)}.")
    if count < 3:
        raise GeometryError("Недостаточно точек для сопоставления сечений.")
    result = [resample_closed_profile(p, count) for p in aligned]
    # После равномерной выборки повторно выбираем ближайший фазовый сдвиг.
    reference = result[0][0]
    for index in range(1, len(result)):
        current = result[index]
        shift = int(np.argmin(np.linalg.norm(current - reference, axis=1)))
        result[index] = np.roll(current, -shift, axis=0)
    return result
