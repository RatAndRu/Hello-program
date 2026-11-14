"""Двумерный Poisson-disk для scatter: только центры в прямоугольнике.

Самостоятельная реализация идеи Bridson, 2007: активные точки, кандидаты в
кольце и сетка соседей. Она не предполагает расстояний по 3D-поверхности.
"""
from __future__ import annotations

import math
import numpy as np


class PoissonDisk2D:
    def __init__(self, bounds, distance: float, rng: np.random.Generator,
                 *, attempts_per_point: int = 30, max_attempts: int = 48000):
        self.x0, self.y0, self.x1, self.y1 = map(float, bounds)
        self.r = float(distance)
        if (not all(math.isfinite(v) for v in (self.x0, self.y0, self.x1, self.y1, self.r))
                or self.x1 <= self.x0 or self.y1 <= self.y0 or self.r <= 0):
            raise ValueError("Poisson-disk: нужны конечная область и положительное расстояние")
        self.rng = rng
        self.cell = self.r / math.sqrt(2.0)
        self.k = max(1, int(attempts_per_point))
        self.max_attempts = max(1, int(max_attempts))
        self.attempts = 0
        self.points: list[tuple[float, float]] = []
        self.active: list[int] = []
        self.failures: dict[int, int] = {}
        self.grid: dict[tuple[int, int], list[int]] = {}
        self._parent: int | None = None
        self._pending: tuple[float, float] | None = None

    def _cell(self, x, y):
        return (int(math.floor((x - self.x0) / self.cell)),
                int(math.floor((y - self.y0) / self.cell)))

    def _spaced(self, x, y):
        gx, gy = self._cell(x, y)
        r2 = self.r * self.r
        for ix in range(gx - 2, gx + 3):
            for iy in range(gy - 2, gy + 3):
                for index in self.grid.get((ix, iy), ()):
                    px, py = self.points[index]
                    if (x - px) ** 2 + (y - py) ** 2 < r2:
                        return False
        return True

    def candidate(self) -> tuple[float, float] | None:
        """Новый кандидат; вызывающий код должен принять или отклонить его."""
        if self._pending is not None:
            raise RuntimeError("Сначала примите или отклоните предыдущую точку")
        while self.attempts < self.max_attempts:
            self.attempts += 1
            if not self.points:
                self._parent = None
                point = (float(self.rng.uniform(self.x0, self.x1)),
                         float(self.rng.uniform(self.y0, self.y1)))
                self._pending = point
                return point
            if not self.active:
                return None
            slot = int(self.rng.integers(0, len(self.active)))
            parent = self.active[slot]
            self.failures[parent] = self.failures.get(parent, 0) + 1
            if self.failures[parent] > self.k:
                self.active[slot] = self.active[-1]
                self.active.pop()
                continue
            angle = float(self.rng.uniform(0.0, 2.0 * math.pi))
            radius = self.r * math.sqrt(float(self.rng.uniform(1.0, 4.0)))
            px, py = self.points[parent]
            x, y = px + radius * math.cos(angle), py + radius * math.sin(angle)
            if not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1):
                continue
            if not self._spaced(x, y):
                continue
            self._parent, self._pending = parent, (x, y)
            return self._pending
        return None

    def accept(self):
        if self._pending is None:
            raise RuntimeError("Нет точки для принятия")
        x, y = self._pending
        index = len(self.points)
        self.points.append((x, y))
        self.grid.setdefault(self._cell(x, y), []).append(index)
        self.active.append(index)
        self.failures[index] = 0
        if self._parent is not None:
            self.failures[self._parent] = 0
        self._parent, self._pending = None, None

    def reject(self):
        if self._pending is None:
            raise RuntimeError("Нет точки для отклонения")
        self._parent, self._pending = None, None
