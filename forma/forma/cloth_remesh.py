"""Равномерное разбиение сеток, составленных из плоских четырёхугольников.

Плиты и фасетированные полые трубы обычно приходят как пары треугольников на
каждой плоской грани. Поочерёдное деление длинных диагоналей создаёт на таких
гранях длинные узкие клинья; при сжатии стенки они могут выворачиваться.
Здесь такие грани сначала объединяются, затем каждая разбивается согласованной
сеткой. Общие рёбра разбиваются одинаково, и замкнутость не меняется.

Произвольные треугольные сетки сюда не принуждаются: если всю исходную сетку
нельзя разбить на плоские выпуклые четырёхугольники, вызывающий код использует
обычное разбиение треугольников. Саму поверхность (включая толщину и отверстия)
мы не аппроксимируем и не меняем.
"""
from __future__ import annotations

import math

import numpy as np


def _quads(vertices, faces):
    if len(faces) == 0 or len(faces) % 2 or len(faces) > 30_000:
        return None
    tri = vertices[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nl = np.linalg.norm(n, axis=1)
    if np.any(nl < 1e-14):
        return None
    n /= nl[:, None]
    incident = {}
    for fid, face in enumerate(faces):
        for i in range(3):
            a, b = int(face[i]), int(face[(i + 1) % 3])
            incident.setdefault((min(a, b), max(a, b)), []).append(fid)
    choices = []
    for (a, b), ids in incident.items():
        if len(ids) != 2:
            continue
        f, g = ids
        if float(n[f] @ n[g]) < 1.0 - 1e-8:
            continue
        length = float(np.linalg.norm(vertices[a] - vertices[b]))
        extra = next(int(x) for x in faces[g] if x != a and x != b)
        if abs(float((vertices[extra] - vertices[a]) @ n[f])) > 1e-7 * max(length, 1.0):
            continue
        choices.append((-length, a, b, f, g))
    # Диагональ прямоугольной грани длиннее её общих с соседями рёбер.
    # На равных длинах порядок фиксирован индексами, без случайного seed.
    choices.sort()
    used = np.zeros(len(faces), dtype=bool)
    quads = []
    for _length, x, y, fid, gid in choices:
        if used[fid] or used[gid]:
            continue
        face = faces[fid]
        found = None
        for i in range(3):
            a, b, c = (int(face[(i + k) % 3]) for k in range(3))
            if {a, b} == {x, y}:
                found = (a, b, c)
                break
        if found is None:
            continue
        a, b, c = found
        other = faces[gid]
        # У корректной ориентированной поверхности общее ребро направлено
        # противоположно в двух соседних треугольниках.
        if not any(int(other[i]) == b and int(other[(i + 1) % 3]) == a for i in range(3)):
            continue
        d = next(int(v) for v in other if v != a and v != b)
        quad = (a, d, b, c)
        points = vertices[list(quad)]
        edges = np.roll(points, -1, axis=0) - points
        turns = np.einsum('ij,j->i', np.cross(edges, np.roll(edges, -1, axis=0)), n[fid])
        if np.any(turns <= 1e-12 * max(float(np.max(np.linalg.norm(edges, axis=1))) ** 2, 1.0)):
            continue
        used[fid] = used[gid] = True
        quads.append(quad)
    return quads if np.all(used) else None


def _edge(a, b):
    return (min(a, b), max(a, b))


def _sizes(vertices, quads, target):
    edges = {}
    quad_edges = []
    for q in quads:
        four = tuple(_edge(q[i], q[(i + 1) % 4]) for i in range(4))
        quad_edges.append(four)
        for edge in four:
            if edge not in edges:
                length = float(np.linalg.norm(vertices[edge[1]] - vertices[edge[0]]))
                # Диагональ ячейки не должна быть существенно длиннее mesh.
                edges[edge] = max(1, int(math.ceil(length / max(0.7 * target, 1e-12))))
    changed = True
    while changed:
        changed = False
        for e0, e1, e2, e3 in quad_edges:
            for a, b in ((e0, e2), (e1, e3)):
                value = max(edges[a], edges[b])
                if edges[a] != value or edges[b] != value:
                    edges[a] = edges[b] = value
                    changed = True
    used_vertices = len(set(v for q in quads for v in q))
    count = used_vertices + sum(n - 1 for n in edges.values())
    for e0, e1, _e2, _e3 in quad_edges:
        count += (edges[e0] - 1) * (edges[e1] - 1)
    return edges, quad_edges, count


def refine_quads(vertices, faces, target, max_vertices):
    """Согласованная сетка плоских граней, либо None для произвольной сетки."""
    quads = _quads(vertices, faces)
    if quads is None:
        return None
    target = max(float(target), 1e-3)
    limit = int(max_vertices)
    edges, quad_edges, count = _sizes(vertices, quads, target)
    if limit > 0 and count > limit:
        # Бюджет — ограничение именно на число вершин. Подбираем максимально
        # подробный допустимый шаг, а не отбрасываем целый уровень разбиения.
        lo, hi = target, target
        while count > limit and hi < target * 1e7:
            hi *= 2.0
            edges, quad_edges, count = _sizes(vertices, quads, hi)
        if count > limit:
            # Исходная сетка уже больше бюджета: она остаётся нетронутой.
            return vertices.copy(), faces.copy()
        for _ in range(28):
            mid = (lo + hi) * 0.5
            trial, trial_quads, number = _sizes(vertices, quads, mid)
            if number > limit:
                lo = mid
            else:
                hi = mid
                edges, quad_edges, count = trial, trial_quads, number
    points = []
    index = {}
    out_faces = []

    def node(key, position):
        if key not in index:
            index[key] = len(points)
            points.append(position)
        return index[key]

    def boundary(a, b, k, n):
        if k == 0:
            return node(('v', a), vertices[a])
        if k == n:
            return node(('v', b), vertices[b])
        if a < b:
            key = ('e', a, b, k, n)
        else:
            key = ('e', b, a, n - k, n)
        return node(key, vertices[a] * (1.0 - k / n) + vertices[b] * (k / n))

    for qid, (q, qe) in enumerate(zip(quads, quad_edges)):
        a, b, c, d = q
        nx, ny = edges[qe[0]], edges[qe[1]]
        grid = np.empty((nx + 1, ny + 1), dtype=np.int64)
        for i in range(nx + 1):
            for j in range(ny + 1):
                if j == 0:
                    slot = boundary(a, b, i, nx)
                elif i == nx:
                    slot = boundary(b, c, j, ny)
                elif j == ny:
                    slot = boundary(d, c, i, nx)
                elif i == 0:
                    slot = boundary(a, d, j, ny)
                else:
                    u, v = i / nx, j / ny
                    p = (vertices[a] * ((1-u)*(1-v)) + vertices[b] * (u*(1-v)) +
                         vertices[c] * (u*v) + vertices[d] * ((1-u)*v))
                    slot = node(('q', qid, i, j), p)
                grid[i, j] = slot
        for i in range(nx):
            for j in range(ny):
                p00, p10 = int(grid[i, j]), int(grid[i+1, j])
                p11, p01 = int(grid[i+1, j+1]), int(grid[i, j+1])
                x00, x10, x11, x01 = (points[k] for k in (p00, p10, p11, p01))
                diag1 = float(np.sum((x00 - x11) ** 2))
                diag2 = float(np.sum((x10 - x01) ** 2))
                eps = 1e-10 * max(1.0, diag1, diag2)
                # Выбор диагонали не зависит от обхода грани; поверхности
                # двух сторон плоской стенки получают согласованные ячейки.
                def key(p):
                    # Интерполяция с двух сторон может отличаться на несколько
                    # ulp; это не должно менять выбор диагонали.
                    return tuple(round(float(x), 8) for x in p)
                key1 = tuple(sorted((key(x00), key(x11))))
                key2 = tuple(sorted((key(x10), key(x01))))
                tie_first = key1 < key2
                if diag1 < diag2 - eps or (abs(diag1-diag2) <= eps and tie_first):
                    out_faces.extend(((p00, p10, p11), (p00, p11, p01)))
                else:
                    out_faces.extend(((p00, p10, p01), (p10, p11, p01)))
    return np.asarray(points, dtype=np.float64), np.asarray(out_faces, dtype=np.int64)
