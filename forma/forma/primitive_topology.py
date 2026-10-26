"""Топология стандартных тел: панели сфер и настоящее подразбиение.

Manifold хранит только треугольники. Поэтому генераторы квадратных и
двойственных панелей возвращают и число/размер исходных панелей отдельно от
треугольной поверхности, необходимой геометрическому ядру.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh


def linear_subdivide(vertices, faces, iterations: int = 1):
    """Делит каждый треугольник на четыре, сохраняя исходные плоскости.

    Середины рёбер вычисляются один раз для двух соседних граней, поэтому
    сетка остаётся замкнутой. Это НЕ сглаживание: координаты старых вершин
    не меняются, а новые лежат на исходных рёбрах.
    """
    verts = np.asarray(vertices, dtype=np.float64).copy()
    tris = np.asarray(faces, dtype=np.int64).copy()
    for _ in range(max(0, int(iterations))):
        edge_mid: dict[tuple[int, int], int] = {}
        extra = []

        def midpoint(i: int, j: int) -> int:
            key = (min(int(i), int(j)), max(int(i), int(j)))
            if key not in edge_mid:
                edge_mid[key] = len(verts) + len(extra)
                extra.append((verts[key[0]] + verts[key[1]]) * 0.5)
            return edge_mid[key]

        refined = []
        for a, b, c in tris:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            refined.extend(((a, ab, ca), (ab, b, bc),
                            (ca, bc, c), (ab, bc, ca)))
        if extra:
            verts = np.vstack([verts, np.asarray(extra, dtype=np.float64)])
        tris = np.asarray(refined, dtype=np.int64).reshape(-1, 3)
    return verts, tris


def loop_smooth(manifold: mf.Manifold, levels: int, what: str) -> mf.Manifold:
    """Loop-сглаживание 0…4 с возвратом исходного габарита по каждой оси."""
    levels = int(levels)
    if levels <= 0:
        return manifold
    if manifold.num_tri() * (4 ** levels) > 220_000:
        raise GeometryError(
            f"{what}: smooth={levels} даст больше 220 000 треугольников.",
            hint="Уменьшите smooth/divisions или число сторон основания.")
    import trimesh

    before = manifold.bounding_box()
    verts, faces = manifold_mesh(manifold)
    try:
        out_v, out_f = trimesh.remesh.subdivide_loop(
            np.asarray(verts, dtype=np.float64),
            np.asarray(faces, dtype=np.int64), iterations=levels)
    except Exception as exc:
        raise GeometryError(f"{what}: не удалось выполнить Loop-сглаживание: {exc}") from exc
    out_v = np.asarray(out_v, dtype=np.float64)
    lo = out_v.min(axis=0)
    hi = out_v.max(axis=0)
    old_lo = np.asarray(before[:3], dtype=np.float64)
    old_hi = np.asarray(before[3:], dtype=np.float64)
    span = np.maximum(hi - lo, 1e-12)
    # Сначала приводим фактические границы, затем возвращаем центр габарита.
    out_v = (out_v - (lo + hi) * 0.5) * ((old_hi - old_lo) / span)
    out_v += (old_lo + old_hi) * 0.5
    return manifold_from_arrays(out_v, out_f, what)


def _triangulate_panels(panels: list[list[int]]) -> np.ndarray:
    triangles = []
    for panel in panels:
        for i in range(1, len(panel) - 1):
            triangles.append((panel[0], panel[i], panel[i + 1]))
    return np.asarray(triangles, dtype=np.int64)


def cube_sphere(radius: float, divisions: int):
    """Куб-сфера: 6·4^divisions квадратных панелей.

    ``divisions=0`` — шесть квадратов (куб, вписанный в сферу). Каждый
    следующий уровень делит панель на четыре; вершины проецируются на радиус.
    """
    n = 2 ** int(divisions)
    verts: list[np.ndarray] = []
    lookup: dict[tuple[int, int, int], int] = {}

    def vertex(key: tuple[int, int, int]) -> int:
        if key not in lookup:
            p = np.asarray(key, dtype=np.float64) * (2.0 / n) - 1.0
            p *= float(radius) / np.linalg.norm(p)
            lookup[key] = len(verts)
            verts.append(p)
        return lookup[key]

    panels: list[list[int]] = []
    for axis in range(3):
        u = (axis + 1) % 3
        v = (axis + 2) % 3
        for sign in (-1, 1):
            for i in range(n):
                for j in range(n):
                    keys = []
                    for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        key = [0, 0, 0]
                        key[axis] = n if sign > 0 else 0
                        key[u] = i + du
                        key[v] = j + dv
                        keys.append(tuple(key))
                    panel = [vertex(k) for k in keys]
                    panels.append(panel if sign > 0 else panel[::-1])
    return (np.asarray(verts, dtype=np.float64), _triangulate_panels(panels),
            {"panels": len(panels), "quads": len(panels),
             "pentagons": 0, "hexagons": 0, "grid": n})


def dual_sphere(radius: float, divisions: int):
    """Двойственная икосфера: додекаэдр на нулевом уровне, далее соты.

    Каждая исходная треугольная грань даёт вершину, каждая исходная вершина —
    пяти- или шестиугольную панель. Двенадцать пятиугольников неизбежны для
    замкнутой сферической соты; остальные панели — шестиугольники.
    """
    import trimesh

    base = trimesh.creation.icosphere(subdivisions=int(divisions), radius=1.0)
    source_v = np.asarray(base.vertices, dtype=np.float64)
    source_f = np.asarray(base.faces, dtype=np.int64)
    centers = source_v[source_f].mean(axis=1)
    incident: list[list[int]] = [[] for _ in range(len(source_v))]
    for fi, tri in enumerate(source_f):
        for vi in tri:
            incident[int(vi)].append(fi)

    panels: list[list[int]] = []
    for vi, face_ids in enumerate(incident):
        normal = source_v[vi] / max(float(np.linalg.norm(source_v[vi])), 1e-12)
        ref = np.array([0.0, 0.0, 1.0])
        if abs(float(np.dot(normal, ref))) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        e1 = np.cross(normal, ref)
        e1 /= max(float(np.linalg.norm(e1)), 1e-12)
        e2 = np.cross(normal, e1)
        middle = centers[face_ids].mean(axis=0)
        ordered = sorted(
            face_ids,
            key=lambda fi: math.atan2(float(np.dot(centers[fi] - middle, e2)),
                                      float(np.dot(centers[fi] - middle, e1))))
        # Контроль ориентации нужен не только для красоты: веер треугольников
        # должен смотреть наружу на каждой из исходных вершин.
        p = centers[ordered]
        face_normal = np.cross(p[1] - p[0], p[2] - p[0])
        if float(np.dot(face_normal, normal)) < 0.0:
            ordered.reverse()
        panels.append(ordered)

    # Центры граней базового тела дают плоские додекаэдрические панели на
    # нулевом уровне. Единый масштаб задаёт наружный радиус без искажения сот.
    scale = float(radius) / max(float(np.linalg.norm(centers, axis=1).max()), 1e-12)
    verts = centers * scale
    sizes = [len(p) for p in panels]
    return (verts, _triangulate_panels(panels),
            {"panels": len(panels), "quads": 0,
             "pentagons": sizes.count(5), "hexagons": sizes.count(6),
             "grid": 2 ** int(divisions)})
