"""Независимая ограниченная проверка самопересечений драпированной сетки.

Решатель работает по ограничениям точек и не обнаруживает все столкновения
рёбер. Здесь используются другие примитивы: AABB пар треугольников и затем
пересечение их рёбер с гранями (включая компланарный двумерный случай).
Соседние грани с общей вершиной не считаются пересечением. Результат — не
доказательство корректности для вырожденных граней или при исчерпании бюджета:
флаг complete в этих случаях равен False.
"""
from __future__ import annotations

import numpy as np


def _cross2(a, b):
    return a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]


def _coplanar_hits(a, b, normal):
    """Пересечения компланарных треугольников после проекции в 2D."""
    hits = np.zeros(len(a), dtype=bool)
    drop = np.argmax(np.abs(normal), axis=1)
    for axis in range(3):
        ids = np.nonzero(drop == axis)[0]
        if not len(ids):
            continue
        keep = [k for k in range(3) if k != axis]
        x, y = a[ids][:, :, keep], b[ids][:, :, keep]
        scale = np.maximum(1.0, np.maximum(np.ptp(x, axis=1).max(axis=1),
                                           np.ptp(y, axis=1).max(axis=1)))
        tol = 1e-9 * scale
        area_tol = tol * scale
        overlap = np.zeros(len(ids), dtype=bool)
        for i in range(3):
            p, q = x[:, i], x[:, (i + 1) % 3]
            for j in range(3):
                r, s = y[:, j], y[:, (j + 1) % 3]
                o1, o2 = _cross2(q - p, r - p), _cross2(q - p, s - p)
                o3, o4 = _cross2(s - r, p - r), _cross2(s - r, q - r)
                opposite1 = ((o1 <= area_tol) & (o2 >= -area_tol)) | \
                            ((o2 <= area_tol) & (o1 >= -area_tol))
                opposite2 = ((o3 <= area_tol) & (o4 >= -area_tol)) | \
                            ((o4 <= area_tol) & (o3 >= -area_tol))
                bounds = np.all((np.maximum(p, q) + tol[:, None] >= np.minimum(r, s)) &
                                (np.maximum(r, s) + tol[:, None] >= np.minimum(p, q)), axis=1)
                overlap |= opposite1 & opposite2 & bounds
        # Один треугольник может целиком лежать внутри другого.
        for point, tri in ((x[:, 0], y), (y[:, 0], x)):
            signs = np.stack([_cross2(tri[:, (i + 1) % 3] - tri[:, i], point - tri[:, i])
                              for i in range(3)], axis=1)
            overlap |= (np.all(signs >= -area_tol[:, None], axis=1) |
                        np.all(signs <= area_tol[:, None], axis=1))
        hits[ids] = overlap
    return hits


def triangle_intersections(first, second):
    """Булев массив попарного пересечения треугольников, включая касание.

    Вырожденные треугольники вызывающая сторона учитывает отдельно. Граничное
    касание несоседних граней отмечается, а не объявляется безопасным.
    """
    a = np.asarray(first, dtype=np.float64).reshape(-1, 3, 3)
    b = np.asarray(second, dtype=np.float64).reshape(-1, 3, 3)
    if len(a) != len(b):
        raise ValueError("число пар треугольников не совпадает")
    hit = np.zeros(len(a), dtype=bool)
    eps = 1e-9
    for src, tri in ((a, b), (b, a)):
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        for corner in range(3):
            origin = src[:, corner]
            direction = src[:, (corner + 1) % 3] - origin
            h = np.cross(direction, e2)
            det = np.einsum('ij,ij->i', e1, h)
            scale = (np.linalg.norm(direction, axis=1) * np.linalg.norm(e1, axis=1) *
                     np.linalg.norm(e2, axis=1))
            valid = np.abs(det) > 1e-12 * np.maximum(scale, 1e-30)
            inv = np.divide(1.0, det, out=np.zeros_like(det), where=valid)
            s = origin - tri[:, 0]
            u = np.einsum('ij,ij->i', s, h) * inv
            q = np.cross(s, e1)
            v = np.einsum('ij,ij->i', direction, q) * inv
            t = np.einsum('ij,ij->i', e2, q) * inv
            hit |= (valid & (u >= -eps) & (v >= -eps) & (u + v <= 1.0 + eps) &
                    (t >= -eps) & (t <= 1.0 + eps))
    n1 = np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0])
    n2 = np.cross(b[:, 1] - b[:, 0], b[:, 2] - b[:, 0])
    l1, l2 = np.linalg.norm(n1, axis=1), np.linalg.norm(n2, axis=1)
    parallel = np.linalg.norm(np.cross(n1, n2), axis=1) <= 1e-10 * l1 * l2
    extent = np.maximum(1.0, np.maximum(np.ptp(a, axis=1).max(axis=1),
                                         np.ptp(b, axis=1).max(axis=1)))
    plane_distance = np.abs(np.einsum('ij,ij->i', b[:, 0] - a[:, 0], n1))
    coplanar = (~hit & parallel & (l1 > 1e-18) & (l2 > 1e-18) &
                (plane_distance <= 1e-9 * extent * l1))
    if np.any(coplanar):
        hit[coplanar] = _coplanar_hits(a[coplanar], b[coplanar], n1[coplanar])
    return hit


def self_intersections(vertices, faces, *, max_candidates=2_000_000, max_scan=20_000_000):
    """Число пересекающихся пар несоседних граней и полнота проверки.

    Сначала работает sweep-and-prune по наиболее выгодной оси, затем точный
    тест геометрии. Проверка имеет явные лимиты памяти/времени. При достижении
    любого лимита или вырожденной грани complete=False, даже если пересечений
    пока не найдено. Отдельные компоненты одной сетки проверяются вместе.
    """
    vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(faces):
        return {"pairs": 0, "candidates": 0, "degenerate": 0, "complete": True}
    tri = vertices[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(normal, axis=1)
    extent = np.maximum(np.ptp(tri, axis=1).max(axis=1), 1e-12)
    degenerate = int(np.count_nonzero(area2 <= 1e-12 * extent * extent))
    lo, hi = tri.min(axis=1), tri.max(axis=1)
    best = None
    for axis in range(3):
        order = np.argsort(lo[:, axis], kind='stable')
        lower = lo[order, axis]
        end = np.searchsorted(lower, hi[order, axis] + 1e-10, side='right')
        size = np.maximum(end - np.arange(len(faces)) - 1, 0)
        total = int(size.sum())
        if best is None or total < best[0]:
            best = (total, axis, order, size)
    _total, axis, order, sizes = best
    candidates, scanned, pairs = 0, 0, 0
    complete = degenerate == 0
    other_axes = [k for k in range(3) if k != axis]
    for start in range(0, len(faces), 32):
        stop = min(start + 32, len(faces))
        counts = sizes[start:stop]
        amount = int(counts.sum())
        if not amount:
            continue
        if scanned + amount > max_scan:
            complete = False
            break
        scanned += amount
        owners = np.repeat(np.arange(start, stop), counts)
        local = np.arange(amount) - np.repeat(np.cumsum(counts) - counts, counts)
        ids1, ids2 = order[owners], order[owners + 1 + local]
        overlap = np.ones(amount, dtype=bool)
        for k in other_axes:
            overlap &= (hi[ids1, k] + 1e-10 >= lo[ids2, k]) & (hi[ids2, k] + 1e-10 >= lo[ids1, k])
        ids1, ids2 = ids1[overlap], ids2[overlap]
        if not len(ids1):
            continue
        same_vertex = np.any(faces[ids1, :, None] == faces[ids2, None, :], axis=(1, 2))
        ids1, ids2 = ids1[~same_vertex], ids2[~same_vertex]
        if candidates + len(ids1) > max_candidates:
            complete = False
            break
        candidates += len(ids1)
        if len(ids1):
            pairs += int(np.count_nonzero(triangle_intersections(tri[ids1], tri[ids2])))
    return {"pairs": pairs, "candidates": candidates, "degenerate": degenerate,
            "complete": bool(complete)}
