"""Независимая ограниченная проверка самопересечений драпированной сетки.

Решатель работает по ограничениям точек и не обнаруживает все столкновения
рёбер. Здесь используются другие примитивы: AABB пар треугольников и затем
пересечение их рёбер с гранями (включая компланарный двумерный случай).
Пары с общей вершиной проверяются отдельно, с конечным разрешением: обе
грани немного уменьшаются к центру, чтобы исключить общую границу. Очень
малые пересечения рядом с этой границей могут остаться незамеченными. Это не
непрерывная проверка движения; вырожденные грани, недостаток точности и
исчерпание бюджета отмечаются флагом complete=False.
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
        scale = np.maximum(1e-12, np.maximum(np.ptp(x, axis=1).max(axis=1),
                                              np.ptp(y, axis=1).max(axis=1)))
        magnitude = np.maximum(np.abs(x).max(axis=(1, 2)), np.abs(y).max(axis=(1, 2)))
        tol = 1e-9 * scale + 16.0 * np.finfo(np.float64).eps * magnitude
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


# У соседних граней общая граница допустима. Уменьшение к центру её исключает,
# но пропускает пересечения внутри этой конечной полосы.
_ADJACENT_INSET = 1e-5


def _adjacent_intersections(first, second):
    """Пересечения за общей границей и маска недостаточной точности."""
    a = np.asarray(first, dtype=np.float64).reshape(-1, 3, 3)
    b = np.asarray(second, dtype=np.float64).reshape(-1, 3, 3)
    if len(a) != len(b):
        raise ValueError("число пар треугольников не совпадает")
    if not len(a):
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)

    def min_height(tri):
        lengths = np.stack([np.linalg.norm(tri[:, (i + 1) % 3] - tri[:, i], axis=1)
                            for i in range(3)], axis=1)
        area2 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                        tri[:, 2] - tri[:, 0]), axis=1)
        return area2 / np.maximum(lengths.max(axis=1), 1e-30)

    scale = np.maximum(1e-12, np.maximum(np.ptp(a, axis=1).max(axis=1),
                                         np.ptp(b, axis=1).max(axis=1)))
    magnitude = np.maximum(np.abs(a).max(axis=(1, 2)), np.abs(b).max(axis=(1, 2)))
    tolerance = 1e-9 * scale + 16.0 * np.finfo(np.float64).eps * magnitude
    inset = np.minimum(min_height(a), min_height(b)) * (_ADJACENT_INSET / 3.0)
    uncertain = inset <= 4.0 * tolerance
    inner_a = a + (a.mean(axis=1)[:, None, :] - a) * _ADJACENT_INSET
    inner_b = b + (b.mean(axis=1)[:, None, :] - b) * _ADJACENT_INSET
    bounds = np.all((inner_a.max(axis=1) >= inner_b.min(axis=1)) &
                    (inner_b.max(axis=1) >= inner_a.min(axis=1)), axis=1)
    test = bounds & ~uncertain
    hit = np.zeros(len(a), dtype=bool)
    if np.any(test):
        hit[test] = triangle_intersections(inner_a[test], inner_b[test])
    return hit, uncertain


def surface_intersections(first, second, *, max_candidates=2_000_000, max_scan=20_000_000):
    """Касания или пересечения двух наборов треугольников с ограничением бюджета.

    Общая граница у разных тел может быть допустимым касанием: этот тест не
    отличает его от проникновения и не проверяет полное вложение одного тела в
    другое. Вычисления независимы от контактных частиц решателя. При нехватке
    точности или бюджета ``complete`` равен False, а число найденных пар может
    относиться только к проверенной части кандидатов.
    """
    a = np.asarray(first, dtype=np.float64).reshape(-1, 3, 3)
    b = np.asarray(second, dtype=np.float64).reshape(-1, 3, 3)
    if max_candidates < 0 or max_scan < 0:
        raise ValueError("Бюджеты проверки поверхностей не могут быть отрицательными")
    empty = {"pairs": 0, "candidates": 0, "scanned": 0, "degenerate": 0,
             "uncertain": 0, "complete": True}
    if not len(a) or not len(b):
        return empty
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return {**empty, "uncertain": 1, "complete": False}

    def quality(tri):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            extent = np.maximum(np.ptp(tri, axis=1).max(axis=1), 1e-12)
            area2 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            edge = np.stack([np.linalg.norm(tri[:, (i + 1) % 3] - tri[:, i], axis=1)
                             for i in range(3)], axis=1).max(axis=1)
            magnitude = np.abs(tri).max(axis=(1, 2))
            tolerance = 1e-9 * np.maximum(extent, 1.0) + 16.0 * np.finfo(np.float64).eps * magnitude
            area_limit = 1e-12 * extent * extent
            height = area2 / np.maximum(edge, 1e-30)
        finite = (np.isfinite(extent) & np.isfinite(area2) & np.isfinite(edge) &
                  np.isfinite(tolerance) & np.isfinite(area_limit) & np.isfinite(height))
        degenerate = area2 <= area_limit
        uncertain = ~finite | (height <= 8.0 * tolerance)
        return degenerate, uncertain, float(tolerance.max()), bool(np.all(finite))

    da, ua, ta, fa = quality(a)
    db, ub, tb, fb = quality(b)
    degenerate = int(np.count_nonzero(da) + np.count_nonzero(db))
    uncertain = int(np.count_nonzero(ua | da) + np.count_nonzero(ub | db))
    complete = not degenerate and not uncertain
    if not fa or not fb:
        return {**empty, "degenerate": degenerate, "uncertain": uncertain, "complete": False}
    # Консервативная надбавка согласована с допустимой погрешностью при
    # проверке компланарных и близких к границе треугольников.
    tol = max(ta, tb, 1e-10)
    lo_a, hi_a = a.min(axis=1), a.max(axis=1)
    lo_b, hi_b = b.min(axis=1), b.max(axis=1)

    # Для каждого треугольника A выбираем меньший из двух диапазонов B:
    # начало отсортированных минимумов или конец отсортированных максимумов.
    # Ось с наименьшим суммарным диапазоном ограничивает число сканирований.
    best = None
    for axis in range(3):
        by_lo = np.argsort(lo_b[:, axis], kind="stable")
        by_hi = np.argsort(hi_b[:, axis], kind="stable")
        before = np.searchsorted(lo_b[by_lo, axis], hi_a[:, axis] + tol, side="right")
        after = np.searchsorted(hi_b[by_hi, axis], lo_a[:, axis] - tol, side="left")
        prefix = before <= len(b) - after
        sizes = np.minimum(before, len(b) - after).astype(np.int64)
        estimate = int(sizes.sum())
        if best is None or estimate < best[0]:
            best = estimate, by_lo, by_hi, after, prefix, sizes
    total, by_lo, by_hi, after, prefix, sizes = best
    ends = np.cumsum(sizes, dtype=np.int64)
    scan_limit = min(total, int(max_scan))
    if total > scan_limit:
        complete = False
    pairs = candidates = scanned = 0
    # В отличие от одной огромной матрицы A×B расход памяти ограничен
    # размером блока, даже когда сетки полностью перекрывают габариты.
    for start in range(0, scan_limit, 50_000):
        slots = np.arange(start, min(start + 50_000, scan_limit), dtype=np.int64)
        owner = np.searchsorted(ends, slots, side="right")
        local = slots - (ends[owner] - sizes[owner])
        ids_b = np.empty(len(slots), dtype=np.int64)
        select = prefix[owner]
        ids_b[select] = by_lo[local[select]]
        ids_b[~select] = by_hi[after[owner[~select]] + local[~select]]
        scanned += len(slots)
        overlap = np.all((hi_a[owner] + tol >= lo_b[ids_b]) &
                         (hi_b[ids_b] + tol >= lo_a[owner]), axis=1)
        ids_a, ids_b = owner[overlap], ids_b[overlap]
        remaining = int(max_candidates) - candidates
        exceeded = len(ids_a) > remaining
        if exceeded:
            ids_a, ids_b = ids_a[:remaining], ids_b[:remaining]
            complete = False
        candidates += len(ids_a)
        if len(ids_a):
            pairs += int(np.count_nonzero(triangle_intersections(a[ids_a], b[ids_b])))
        if exceeded:
            break
    return {"pairs": pairs, "candidates": candidates, "scanned": scanned,
            "degenerate": degenerate, "uncertain": uncertain, "complete": bool(complete)}


def self_intersections(vertices, faces, *, max_candidates=2_000_000, max_scan=20_000_000):
    """Проверка несоседних и соседних граней с признаком полноты.

    Используются sweep-and-prune и геометрический тест с конечной точностью.
    Соседние грани проверяются за пределами общей вершины или ребра; узкая
    полоса вокруг этой границы не проверяется. При достижении лимита,
    вырожденной грани или нехватке точности complete=False.
    """
    vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(faces):
        return {"pairs": 0, "candidates": 0, "adjacent_pairs": 0,
                "adjacent_candidates": 0, "adjacent_uncertain": 0,
                "adjacent_complete": True, "degenerate": 0, "complete": True}
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
    adjacent_candidates, adjacent_pairs, adjacent_uncertain = 0, 0, 0
    complete = degenerate == 0
    adjacent_complete = degenerate == 0
    other_axes = [k for k in range(3) if k != axis]
    for start in range(0, len(faces), 32):
        stop = min(start + 32, len(faces))
        counts = sizes[start:stop]
        amount = int(counts.sum())
        if not amount:
            continue
        if scanned + amount > max_scan:
            complete = False
            adjacent_complete = False
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
        if candidates + adjacent_candidates + len(ids1) > max_candidates:
            complete = False
            adjacent_complete = False
            break
        same_vertex = np.any(faces[ids1, :, None] == faces[ids2, None, :], axis=(1, 2))
        adjacent_candidates += int(np.count_nonzero(same_vertex))
        if np.any(same_vertex):
            hit, uncertain = _adjacent_intersections(tri[ids1[same_vertex]], tri[ids2[same_vertex]])
            adjacent_pairs += int(np.count_nonzero(hit))
            adjacent_uncertain += int(np.count_nonzero(uncertain))
        ids1, ids2 = ids1[~same_vertex], ids2[~same_vertex]
        candidates += len(ids1)
        if len(ids1):
            pairs += int(np.count_nonzero(triangle_intersections(tri[ids1], tri[ids2])))
    if adjacent_uncertain:
        adjacent_complete = False
        complete = False
    return {"pairs": pairs, "candidates": candidates, "adjacent_pairs": adjacent_pairs,
            "adjacent_candidates": adjacent_candidates, "adjacent_uncertain": adjacent_uncertain,
            "adjacent_complete": bool(adjacent_complete), "degenerate": degenerate,
            "complete": bool(complete)}
