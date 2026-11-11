"""Исследовательская коррекция пересечений граней с опорой.

Только для контрольных прогонов drape_six_probe.py, НЕ часть решателя. Она
работает с уже пересекающимися треугольниками, а не гарантирует непрерывный
контакт или сохранение длин, толщины и равновесия. Вогнутые и пересекающиеся
опоры могут давать конфликтующие нормали.
"""
from __future__ import annotations

import numpy as np

from forma.cloth import _cell_keys
from forma.cloth_check import triangle_intersections
from forma.cloth_collision import _expanded_cells


class TriangleSupportProbe:
    """Отдельная приближённая коррекция пересекающих опору треугольников."""

    def __init__(self, field, faces, shell, clearance=0.03):
        self.field = field
        self.faces = np.asarray(faces, dtype=np.int64)
        self.shell = np.asarray(shell, dtype=np.int64).reshape(-1, 2)
        self.clearance = float(clearance)
        triangles = field.tri
        self.lo = triangles.min(axis=1)
        self.hi = triangles.max(axis=1)
        normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        self.normal = normal / np.maximum(np.linalg.norm(normal, axis=1)[:, None], 1e-12)
        self.applied_rounds = 0
        self.max_pairs = 0
        self.budget_exceeded = False

    def project(self, position, free, rounds=4):
        field, triangles = self.field, self.field.tri
        for _ in range(rounds):
            dynamic = position[self.faces]
            lo, hi = dynamic.min(axis=1), dynamic.max(axis=1)
            lower = np.floor((lo - field.origin) / field.cell).astype(np.int64)
            upper = np.floor((hi - field.origin) / field.cell).astype(np.int64)
            if int(np.maximum(upper - lower + 1, 1).prod(axis=1).sum()) > 1_000_000:
                self.budget_exceeded = True
                return
            cells, owners = _expanded_cells(lower, upper)
            keys = _cell_keys(cells)
            left = np.searchsorted(field.sorted_keys, keys, side="left")
            right = np.searchsorted(field.sorted_keys, keys, side="right")
            sizes = right - left
            active = sizes > 0
            if not np.any(active):
                return
            amount = int(sizes.sum())
            if amount > 3_000_000:
                self.budget_exceeded = True
                return
            starts = np.repeat(left[active], sizes[active])
            local = np.arange(amount) - np.repeat(
                np.cumsum(sizes[active]) - sizes[active], sizes[active])
            body_ids = np.repeat(owners[active], sizes[active])
            support_ids = field.sorted_tri[starts + local]
            overlapping = (np.all(hi[body_ids] >= self.lo[support_ids] - 1e-9, axis=1)
                           & np.all(self.hi[support_ids] >= lo[body_ids] - 1e-9, axis=1))
            codes = np.unique(body_ids[overlapping] * len(triangles) + support_ids[overlapping])
            body_ids, support_ids = codes // len(triangles), codes % len(triangles)
            if not len(body_ids):
                return
            hit = triangle_intersections(dynamic[body_ids], triangles[support_ids])
            body_ids, support_ids = body_ids[hit], support_ids[hit]
            if not len(body_ids):
                return
            self.max_pairs = max(self.max_pairs, len(body_ids))
            height = np.einsum("ijk,ik->ij", dynamic[body_ids] - triangles[support_ids, 0, None, :],
                               self.normal[support_ids])
            depth = np.minimum(np.maximum(self.clearance - height.min(axis=1), 0), field.cell * 0.35)
            correction = self.normal[support_ids] * depth[:, None]
            ids = self.faces[body_ids].reshape(-1)
            weights = np.repeat(correction, 3, axis=0)
            # Парную сторону стенки пробуем перемещать вместе с найденной,
            # но это не доказательство сохранения толщины.
            if len(self.shell):
                other = np.full(len(position), -1, dtype=np.int64)
                other[self.shell[:, 0]] = self.shell[:, 1]
                other[self.shell[:, 1]] = self.shell[:, 0]
                paired = other[ids]
                selected = paired >= 0
                ids = np.r_[ids, paired[selected]]
                weights = np.vstack((weights, weights[selected]))
            degree = np.bincount(ids, minlength=len(position))
            displacement = np.column_stack([
                np.bincount(ids, weights=weights[:, axis], minlength=len(position))
                for axis in range(3)
            ])
            position[free] += 0.85 * displacement[free] / np.maximum(degree[free, None], 1)
            self.applied_rounds += 1
