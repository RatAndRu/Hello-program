"""Общие операции готовых фигур: кромки, полости и уровни сглаживания."""

from __future__ import annotations

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile
from .primitive_topology import loop_smooth


def smooth_level(a, default: int = 0) -> int:
    return int(a.int("smooth", default, minv=0, maxv=4) or 0)


def apply_smooth(solid: mf.Manifold, a, what: str) -> mf.Manifold:
    """Loop-сглаживание целыми уровнями, без подмены радиусом кромки."""
    return loop_smooth(solid, smooth_level(a), what)


def rounded_extrude(cross: mf.CrossSection, depth: float, radius: float,
                    what: str, sphere_segments: int = 20) -> mf.Manifold:
    """Выдавливание с настоящим радиусом вместо ступенчатой фаски.

    Отступ действует и на внешний контур, и на отверстия: у полой формочки
    скругляются обе стороны стенки, а не только наружные углы.
    """
    r = float(radius or 0.0)
    if r <= 1e-6:
        return cross.extrude(float(depth))
    if r >= depth / 2.0 - 1e-6:
        raise GeometryError(f"{what}: round={r:g} мм слишком велик для толщины {depth:g} мм.",
                            hint="round должен быть меньше половины толщины.")
    core = cross.offset(-r, mf.JoinType.Round, 2.0, 20)
    if core.is_empty() or core.area() <= 1e-9:
        raise GeometryError(f"{what}: скругление стирает контур или стенку.",
                            hint="Уменьшите round или увеличьте толщину стенки.")
    solid = core.extrude(float(depth) - 2.0 * r).translate((0.0, 0.0, r))
    return solid.minkowski_sum(mf.Manifold.sphere(r, int(sphere_segments)))


def hollow_cross(cross: mf.CrossSection, wall: float, what: str) -> mf.CrossSection:
    """Равномерная полая рамка из контура, открытая сквозь выдавливание."""
    if wall <= 1e-6:
        return cross
    inner = cross.offset(-float(wall), mf.JoinType.Miter, 3.0, 16)
    if inner.is_empty() or inner.area() <= 1e-9:
        raise GeometryError(f"{what}: wall={wall:g} мм не оставляет внутренней полости.",
                            hint="Уменьшите wall или увеличьте размер фигуры.")
    frame = mf.CrossSection.batch_boolean([cross, inner], mf.OpType.Subtract)
    if frame.is_empty() or frame.area() <= 1e-9:
        raise GeometryError(f"{what}: не удалось построить полую рамку.")
    return frame


def cut_center_hole(solid: mf.Manifold, depth: float, diameter: float,
                    center=(0.0, 0.0), segments: int = 64,
                    what: str = "фигура") -> mf.Manifold:
    """Сквозное круглое отверстие перпендикулярно исходной плоскости XY."""
    if diameter <= 1e-6:
        return solid
    tool = mf.Manifold.cylinder(float(depth) + 4.0, float(diameter) / 2.0,
                                float(diameter) / 2.0, int(segments))
    tool = tool.translate((float(center[0]), float(center[1]), -2.0))
    out = solid - tool
    if out.is_empty() or out.volume() <= 1e-8:
        raise GeometryError(f"{what}: отверстие удалило всё тело.")
    return out


def circle_contour(radius: float, center=(0.0, 0.0), segments: int = 64) -> np.ndarray:
    pts = np.asarray(circle_profile(float(radius), int(segments)), dtype=np.float64)
    return pts + np.asarray(center, dtype=np.float64)


def rect_between(p0, p1, width: float) -> np.ndarray:
    """Прямоугольная ветвь между двумя точками для Y и других знаков."""
    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    d = b - a
    length = float(np.linalg.norm(d))
    if length < 1e-9:
        raise GeometryError("Концы прямоугольной ветви совпали.")
    n = np.array([-d[1], d[0]]) / length * (float(width) / 2.0)
    return np.asarray([a - n, b - n, b + n, a + n])
