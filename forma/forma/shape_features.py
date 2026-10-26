"""Общие операции готовых фигур: кромки, полости и уровни сглаживания."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, manifold_from_arrays, manifold_mesh
from .primitive_topology import loop_smooth


def smooth_level(a, default: int = 0) -> int:
    return int(a.int("smooth", default, minv=0, maxv=4) or 0)


def apply_smooth(solid: mf.Manifold, a, what: str) -> mf.Manifold:
    """Loop-сглаживание целыми уровнями, без подмены радиусом кромки."""
    return loop_smooth(solid, smooth_level(a), what)


def transition_radius(a, limit: float) -> float:
    """Радиус четырёх ступеней скругления переходных рёбер.

    Некоторым деталям нужен именно ``smooth`` как уровень кромки, а не Loop
    всей сетки. Предел выбирает конструктор из толщины/стенки; функция лишь
    равномерно переводит в него ступени 0…4.
    """
    return smooth_level(a) * max(0.0, float(limit)) / 4.0


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


def varied_edge_thickness(solid: mf.Manifold, thickness: float, edge: float,
                          band: float, influence, what: str,
                          center_z: float | None = None) -> mf.Manifold:
    """Плавно меняет толщину только у заданной кромки исходной сетки.

    ``influence(xyz) -> 0…1`` выбирает полосу кромки. Сетка предварительно
    дробится по ширине этой полосы, поэтому верх/низ не натягиваются одной
    большой диагональю. При edge>thickness кромка утолщается, при меньшем
    значении — истончается. Прямые торцы можно исключить функцией influence.
    """
    thickness, edge, band = float(thickness), float(edge), float(band)
    if abs(edge - thickness) <= 1e-9:
        return solid
    if edge < 0.05:
        raise GeometryError(f"{what}: толщина кромки должна быть не меньше 0.05 мм.")
    if band <= 1e-6:
        raise GeometryError(f"{what}: edge_band должен быть больше нуля.")
    area = float(solid.surface_area())
    # Не меньше семи рядов в переходе и не более ~180 тысяч треугольников.
    step = max(0.08, band / 7.0, math.sqrt(2.0 * area / 180_000.0))
    refined = solid.refine_to_length(step)
    verts, faces = manifold_mesh(refined)
    verts = np.asarray(verts, dtype=np.float64).copy()
    weight = np.clip(np.asarray(influence(verts), dtype=np.float64), 0.0, 1.0)
    weight = weight * weight * (3.0 - 2.0 * weight)
    local = thickness + (edge - thickness) * weight
    if np.any(local < 0.049):
        raise GeometryError(f"{what}: переход дал почти нулевую толщину.")
    mid = thickness / 2.0 if center_z is None else float(center_z)
    verts[:, 2] = mid + (verts[:, 2] - mid) * (local / thickness)
    return manifold_from_arrays(verts, faces, what)


def ellipse_edge_influence(hx: float, hy: float, band: float):
    """Полоса постоянной радиальной ширины у эллиптической наружной кромки."""
    def influence(points: np.ndarray) -> np.ndarray:
        x, y = points[:, 0], points[:, 1]
        q = np.sqrt((x / hx) ** 2 + (y / hy) ** 2)
        ray_radius = np.where(q > 1e-12, np.hypot(x, y) / np.maximum(q, 1e-12),
                              max(hx, hy))
        radial_distance = np.maximum(0.0, 1.0 - q) * ray_radius
        return np.clip(1.0 - radial_distance / band, 0.0, 1.0)
    return influence


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


def slot_contour(length: float, width: float, segments: int = 24) -> np.ndarray:
    """Прямой овал (капсула) с точными общими длиной и шириной."""
    length, width = float(length), float(width)
    if length < width - 1e-9 or width <= 0.0:
        raise GeometryError("Для прямого овала длина должна быть не меньше ширины.")
    if abs(length - width) < 1e-9:
        return circle_contour(width / 2.0, segments=max(16, segments * 2))
    radius = width / 2.0
    center = (length - width) / 2.0
    pts = []
    for i in range(segments + 1):
        angle = -math.pi / 2.0 + math.pi * i / segments
        pts.append((center + radius * math.cos(angle), radius * math.sin(angle)))
    for i in range(segments + 1):
        angle = math.pi / 2.0 + math.pi * i / segments
        pts.append((-center + radius * math.cos(angle), radius * math.sin(angle)))
    return np.asarray(pts, dtype=np.float64)


def axis_hole_cutter(axis: str, shape: str, diameter: float,
                     oval_aspect: float, span: float) -> mf.Manifold:
    """Центрированный сквозной резец круга, квадрата или прямого овала."""
    shape = {"круг": "круг", "круглое": "круг", "circle": "круг",
             "квадрат": "квадрат", "square": "квадрат",
             "овал": "овал", "капсула": "овал", "slot": "овал",
             "oval": "овал"}.get(shape.strip().lower())
    if shape is None:
        raise GeometryError("Форма отверстия: круг, квадрат или овал.")
    if shape == "круг":
        profile = np.asarray(circle_profile(diameter / 2.0, 64), dtype=np.float64)
    elif shape == "квадрат":
        h = diameter / 2.0
        profile = np.asarray([(-h, -h), (h, -h), (h, h), (-h, h)], dtype=np.float64)
    else:
        profile = slot_contour(diameter, diameter / oval_aspect, 24)
    cutter = mf.Manifold.extrude(mf.CrossSection([profile]), span).translate((0, 0, -span / 2))
    matrices = {
        "z": np.eye(3, 4),
        "x": np.asarray([[0, 0, 1, 0], [0, -1, 0, 0], [1, 0, 0, 0]], dtype=float),
        "y": np.asarray([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], dtype=float),
    }
    return cutter.transform(np.asarray(matrices[axis], dtype=np.float64))


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
