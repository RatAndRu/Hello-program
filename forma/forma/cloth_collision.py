"""Контакт деформируемой сетки с самой собой.

В отличие от поиска близких вершин, треугольник может остановить вершину даже
посреди своей грани. Для каждого шага проверяются и предыдущие, и новые
координаты: столкновение не пропускается только потому, что частица оказалась
по другую сторону плоскости к концу шага. Неподвижных опор здесь нет.
"""

from __future__ import annotations

import numpy as np

from .errors import GeometryError


def _cell_keys(index: np.ndarray) -> np.ndarray:
    index = np.asarray(index, dtype=np.int64) + 1_000_000
    big = 2_000_003
    return (index[:, 0] * big + index[:, 1]) * big + index[:, 2]


def _expanded_cells(lo: np.ndarray, hi: np.ndarray):
    """Все ячейки AABB, вместе с индексом исходной вершины/грани."""
    size = np.maximum(hi - lo + 1, 1)
    counts = size.prod(axis=1, dtype=np.int64)
    owners = np.repeat(np.arange(len(lo), dtype=np.int64), counts)
    total = int(counts.sum())
    if not total:
        return np.zeros((0, 3), dtype=np.int64), owners
    inner = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
    sx, sy = size[owners, 0], size[owners, 1]
    cells = lo[owners] + np.stack((inner % sx, (inner // sx) % sy, inner // (sx * sy)), axis=1)
    return cells, owners


def _excluded_triangles(faces: np.ndarray, count: int, shell: np.ndarray) -> np.ndarray:
    """Треугольники в окрестности вершины не являются самостолкновением.

    Два кольца рёбер включают и связи через толщину стенки: противоположные
    поверхности одного куска материала нельзя расталкивать как разные слои.
    """
    adjacent: list[set[int]] = [set() for _ in range(count)]
    for face in faces:
        a, b, c = (int(v) for v in face)
        for u, v in ((a, b), (b, c), (c, a)):
            adjacent[u].add(v)
            adjacent[v].add(u)
    for a, b in shell:
        u, v = int(a), int(b)
        adjacent[u].add(v)
        adjacent[v].add(u)
    incident: list[list[int]] = [[] for _ in range(count)]
    for tid, face in enumerate(faces):
        for vertex in face:
            incident[int(vertex)].append(tid)
    codes: set[int] = set()
    nfaces = len(faces)
    for vertex, neighbours in enumerate(adjacent):
        ring = {vertex} | neighbours
        for neighbour in neighbours:
            ring.update(adjacent[neighbour])
        for neighbour in ring:
            for tid in incident[neighbour]:
                codes.add(vertex * nfaces + tid)
    return np.asarray(sorted(codes), dtype=np.int64)


def _barycentric(points: np.ndarray, triangles: np.ndarray):
    """Барицентрические координаты ортогональной проекции на плоскость грани."""
    a = triangles[:, 0]
    ab = triangles[:, 1] - a
    ac = triangles[:, 2] - a
    ap = points - a
    aa = np.einsum('ij,ij->i', ab, ab)
    bb = np.einsum('ij,ij->i', ab, ac)
    cc = np.einsum('ij,ij->i', ac, ac)
    dd = np.einsum('ij,ij->i', ap, ab)
    ee = np.einsum('ij,ij->i', ap, ac)
    denominator = aa * cc - bb * bb
    good = np.abs(denominator) > 1e-18
    denom = np.where(good, denominator, 1.0)
    v = (cc * dd - bb * ee) / denom
    w = (aa * ee - bb * dd) / denom
    return np.column_stack((1.0 - v - w, v, w)), good


class SurfaceContacts:
    """Вершина—треугольник между несоседними участками поверхности."""

    def __init__(self, vertices: np.ndarray, faces: np.ndarray,
                 shell: np.ndarray, gap: float, components: np.ndarray,
                 up: np.ndarray):
        self.rest = np.asarray(vertices, dtype=np.float64)
        self.components = np.asarray(components)
        up = np.asarray(up, dtype=np.float64)
        length = np.linalg.norm(up)
        self.up = up / length if length > 1e-12 else np.array([0.0, 0.0, 1.0])
        self.height = np.zeros(len(vertices))
        for part in np.unique(self.components):
            ids = self.components == part
            self.height[ids] = float(np.mean(self.rest[ids] @ self.up))
        self.faces = np.asarray(faces, dtype=np.int64)
        self.nvertices = len(vertices)
        self.nfaces = len(faces)
        self.gap = float(max(gap, 1e-4))
        edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
        typical = lengths[lengths > max(self.gap * 2.0, 1e-6)]
        self.cell = max(float(np.median(typical)) * 1.5 if len(typical) else 1.0,
                        self.gap * 2.0, 0.5)
        self.excluded = _excluded_triangles(self.faces, self.nvertices, shell)
        # Контакт двигает обе стороны одного участка стенки вместе, иначе
        # встреченная опора сворачивает лист в нулевую толщину.
        parent = np.arange(self.nvertices)

        def root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index
        for a, b in shell:
            ra, rb = root(int(a)), root(int(b))
            if ra != rb:
                parent[rb] = ra
        _roots, self.groups = np.unique([root(i) for i in range(self.nvertices)], return_inverse=True)
        self.ngroups = len(_roots)

    def candidates(self, previous: np.ndarray, current: np.ndarray):
        """Пересечение AABB за весь шаг, а не только в его конце."""
        old_tri, new_tri = previous[self.faces], current[self.faces]
        reach = max(self.gap, min(2.0, 0.5 * self.cell))
        tri_lo = np.minimum(old_tri.min(axis=1), new_tri.min(axis=1)) - reach
        tri_hi = np.maximum(old_tri.max(axis=1), new_tri.max(axis=1)) + reach
        point_lo = np.minimum(previous, current)
        point_hi = np.maximum(previous, current)
        cell = self.cell
        origin = np.minimum(tri_lo.min(axis=0), point_lo.min(axis=0)) - cell
        # У длинных треугольников или большого шага подбираем размер ячейки так,
        # чтобы память на их растеризацию не росла без границы.
        for _ in range(12):
            tlo = np.floor((tri_lo - origin) / cell).astype(np.int64)
            thi = np.floor((tri_hi - origin) / cell).astype(np.int64)
            plo = np.floor((point_lo - origin) / cell).astype(np.int64)
            phi = np.floor((point_hi - origin) / cell).astype(np.int64)
            total = int(np.maximum(thi - tlo + 1, 1).prod(axis=1).sum())
            total += int(np.maximum(phi - plo + 1, 1).prod(axis=1).sum())
            if total <= 1_500_000:
                break
            cell *= 1.5
        else:
            raise GeometryError('drape: слишком сложная сетка для проверки столкновений.',
                                hint='Увеличьте mesh или уменьшите число деталей.')
        tcells, tids = _expanded_cells(tlo, thi)
        pcells, pids = _expanded_cells(plo, phi)
        keys = _cell_keys(tcells)
        order = np.argsort(keys, kind='stable')
        keys, tids = keys[order], tids[order]
        query = _cell_keys(pcells)
        left = np.searchsorted(keys, query, side='left')
        right = np.searchsorted(keys, query, side='right')
        sizes = right - left
        active = sizes > 0
        if not np.any(active):
            empty = np.zeros(0, dtype=np.int64)
            return empty, empty
        amount = int(sizes.sum())
        if amount > 5_000_000:
            raise GeometryError('drape: слишком много кандидатов самостолкновения.',
                                hint='Увеличьте mesh или разделите сложную сцену.')
        starts = np.repeat(left[active], sizes[active])
        inner = np.arange(amount, dtype=np.int64) - np.repeat(
            np.cumsum(sizes[active]) - sizes[active], sizes[active])
        owners = np.repeat(pids[active], sizes[active])
        triangles = tids[starts + inner]
        # Точный AABB-отбор выполняем до сортировки: большая часть общих
        # ячеек даёт ложные пары, особенно у сжатой многослойной трубки.
        overlap = np.all((point_hi[owners] >= tri_lo[triangles])
                         & (point_lo[owners] <= tri_hi[triangles]), axis=1)
        codes = owners[overlap] * self.nfaces + triangles[overlap]
        if not len(codes):
            empty = np.zeros(0, dtype=np.int64)
            return empty, empty
        codes.sort()
        codes = codes[np.r_[True, codes[1:] != codes[:-1]]]
        if len(self.excluded):
            slot = np.minimum(np.searchsorted(self.excluded, codes), len(self.excluded) - 1)
            codes = codes[self.excluded[slot] != codes]
        return codes // self.nfaces, codes % self.nfaces

    def project(self, previous: np.ndarray, current: np.ndarray,
                free: np.ndarray, anchored: np.ndarray | None = None, rounds: int = 3):
        """Раздвигает вершины и треугольники; возвращает число и глубину контактов."""
        owners, triangles = self.candidates(previous, current)
        if not len(owners):
            return 0, 0.0
        faces = self.faces[triangles]
        old_tri = previous[faces]
        old_normal = np.cross(old_tri[:, 1] - old_tri[:, 0], old_tri[:, 2] - old_tri[:, 0])
        old_length = np.linalg.norm(old_normal, axis=1)
        old_normal /= np.maximum(old_length, 1e-12)[:, None]
        old_distance = np.einsum('ij,ij->i', previous[owners] - old_tri[:, 0], old_normal)
        # У двух разных кусков сохраняем сторону касания, с которой они
        # начинали: если точка уже чуть проникла, её всё равно надо вернуть.
        different = self.components[owners] != self.components[faces[:, 0]]
        recovery = np.zeros(len(owners), dtype=bool)
        if np.any(different):
            ids = np.nonzero(different)[0]
            rest_tri = self.rest[faces[ids]]
            rest_normal = np.cross(rest_tri[:, 1] - rest_tri[:, 0], rest_tri[:, 2] - rest_tri[:, 0])
            rest_normal /= np.maximum(np.linalg.norm(rest_normal, axis=1), 1e-12)[:, None]
            rest_distance = np.einsum('ij,ij->i', self.rest[owners[ids]] - rest_tri[:, 0], rest_normal)
            recovery[ids] = rest_distance > self.gap
        was_outside = ((old_distance >= -max(self.gap * 0.1, 1e-5)) | recovery) & (old_length > 1e-12)
        initial_tri = current[faces]
        initial_normal = np.cross(initial_tri[:, 1] - initial_tri[:, 0], initial_tri[:, 2] - initial_tri[:, 0])
        initial_length = np.linalg.norm(initial_normal, axis=1)
        initial_distance = np.einsum('ij,ij->i', current[owners] - initial_tri[:, 0], initial_normal)
        active = was_outside & (initial_length > 1e-12) & (initial_distance < self.gap * initial_length)
        if not np.any(active):
            return 0, 0.0
        owners, faces, old_tri = owners[active], faces[active], old_tri[active]
        old_distance, different, recovery = old_distance[active], different[active], recovery[active]
        was_outside = np.ones(len(owners), dtype=bool)
        group_free = np.ones(self.ngroups, dtype=bool)
        np.logical_and.at(group_free, self.groups, np.asarray(free, dtype=bool))
        group_anchored = np.zeros(self.ngroups, dtype=bool)
        if anchored is not None:
            np.logical_or.at(group_anchored, self.groups, np.asarray(anchored, dtype=bool))
        largest = 0.0
        max_contacts = 0
        for _ in range(max(1, int(rounds))):
            tri = current[faces]
            normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            length = np.linalg.norm(normal, axis=1)
            normal /= np.maximum(length, 1e-12)[:, None]
            distance = np.einsum('ij,ij->i', current[owners] - tri[:, 0], normal)
            hit = was_outside & (length > 1e-12) & (distance < self.gap)
            if not np.any(hit):
                break
            ids = np.nonzero(hit)[0]
            # В момент пересечения (или в конце шага при касании) проекция
            # действительно должна попадать внутрь треугольника.
            denom = old_distance[ids] - distance[ids]
            t = np.clip((old_distance[ids] - self.gap) / np.where(
                np.abs(denom) > 1e-12, denom, 1.0), 0.0, 1.0)
            t = np.where((old_distance[ids] < 0.0) & recovery[ids], 1.0, t)
            tri_at = old_tri[ids] + (tri[ids] - old_tri[ids]) * t[:, None, None]
            point_at = previous[owners[ids]] + (current[owners[ids]] - previous[owners[ids]]) * t[:, None]
            bary, valid = _barycentric(point_at, tri_at)
            valid &= np.all(bary >= -0.015, axis=1) & np.all(bary <= 1.015, axis=1)
            ids, bary = ids[valid], bary[valid]
            if not len(ids):
                break
            bary = np.clip(bary, 0.0, 1.0)
            bary /= np.maximum(bary.sum(axis=1), 1e-12)[:, None]
            own, corners = owners[ids], faces[ids]
            depth = self.gap - distance[ids]
            max_contacts = max(max_contacts, len(ids))
            largest = max(largest, float(depth.max()))
            # Градиенты ограничения: +normal у вершины и -bary*normal у граней.
            own_group, tri_groups = self.groups[own], self.groups[corners]
            wv = group_free[own_group].astype(np.float64)
            wt = group_free[tri_groups].astype(np.float64)
            # Из двух разных слоёв разрешаем освободиться верхнему, даже если
            # он уже ошибочно дошёл до пола. Нижний же не продавливаем в пол.
            diff = different[ids]
            height_v, height_t = self.height[own], self.height[corners[:, 0]]
            owner_lower = ((height_v < height_t) | ((height_v == height_t)
                           & (self.components[own] < self.components[corners[:, 0]])))
            av = group_anchored[own_group]
            at = group_anchored[tri_groups]
            anchor_v = av & np.where(diff, owner_lower, ~np.any(at, axis=1))
            anchor_t = at & np.where(diff[:, None], (~owner_lower)[:, None], (~av)[:, None])
            wv *= ~anchor_v
            wt *= ~anchor_t
            denominator = wv + (wt * bary * bary).sum(axis=1)
            # Не делим на исчезающе малый вес зажатого треугольника: его
            # единственная свободная вершина не должна улететь на километры.
            active = denominator > 0.04
            amount = depth / np.maximum(denominator, 0.04)
            move = normal[ids] * amount[:, None]
            # Одна группа содержит обе стороны материала. Все её вершины
            # получают одинаковое перемещение, контакты усредняются.
            degree = np.bincount(own_group, weights=wv * active, minlength=self.ngroups)
            for corner in range(3):
                degree += np.bincount(tri_groups[:, corner], weights=wt[:, corner] * active,
                                      minlength=self.ngroups)
            displacement = np.zeros((self.ngroups, 3), dtype=np.float64)
            for axis in range(3):
                accum = np.bincount(own_group, weights=move[:, axis] * wv * active,
                                    minlength=self.ngroups)
                for corner in range(3):
                    accum -= np.bincount(tri_groups[:, corner],
                        weights=move[:, axis] * bary[:, corner] * wt[:, corner] * active,
                        minlength=self.ngroups)
                displacement[:, axis] = 0.9 * accum / np.maximum(degree, 1.0)
            # При одновременном контакте со многими гранями ограничиваем
            # поправку за проход: это не даёт единичным острым углам взорвать
            # сетку, а несколько проходов всё равно разводят слои.
            length = np.linalg.norm(displacement, axis=1)
            cap = min(0.5, self.cell * 0.15)
            displacement *= np.minimum(1.0, cap / np.maximum(length, 1e-12))[:, None]
            current += displacement[self.groups]
        return int(max_contacts), float(largest)
