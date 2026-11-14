"""Преобразование нормализованных координат руки в пиксели экрана.

Отвечает за «ощущение» управления: активная зона кадра, мёртвая зона,
сглаживание (1€-фильтр) и защита от телепортов курсора.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .config import PointerConfig
from .filters import OneEuroFilter, clamp, deadzone


@dataclass
class PointerMapper:
    cfg: PointerConfig
    screen_size: Tuple[int, int]

    def __post_init__(self) -> None:
        self._fx = OneEuroFilter(self.cfg.min_cutoff, self.cfg.beta, self.cfg.d_cutoff)
        self._fy = OneEuroFilter(self.cfg.min_cutoff, self.cfg.beta, self.cfg.d_cutoff)
        self._last_input: Optional[np.ndarray] = None
        self._pos: Optional[np.ndarray] = None  # сглаженная позиция в пикселях
        self._last_t: Optional[float] = None

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self._fx.reset()
        self._fy.reset()
        self._last_input = None
        self._pos = None
        self._last_t = None

    @property
    def position(self) -> Optional[np.ndarray]:
        return None if self._pos is None else self._pos.copy()

    def screen_point(self, x_norm: float, y_norm: float) -> np.ndarray:
        """Нормализованная точка кадра -> пиксели экрана (без сглаживания)."""
        x0, y0, x1, y1 = self.cfg.active_box
        u = clamp((x_norm - x0) / max(x1 - x0, 1e-6), 0.0, 1.0)
        v = clamp((y_norm - y0) / max(y1 - y0, 1e-6), 0.0, 1.0)
        w, h = self.screen_size
        m = self.cfg.edge_margin_px
        return np.array([m + u * max(w - 1 - 2 * m, 1), m + v * max(h - 1 - 2 * m, 1)])

    # ------------------------------------------------------------------ #
    def absolute(self, point: Tuple[float, float], now: float) -> Optional[Tuple[int, int]]:
        """Абсолютное позиционирование: точка руки -> точка экрана.

        Возвращает ``None``, если рука дрогнула меньше мёртвой зоны —
        тогда курсор лучше не трогать вовсе.
        """
        p = np.asarray(point, dtype=np.float64)
        if not np.all(np.isfinite(p)):
            return None
        if self.cfg.relative_mode:
            raise RuntimeError("relative_mode=True: используйте delta()")

        if self._last_input is not None:
            step = float(np.linalg.norm(p - self._last_input))
            if step < self.cfg.deadzone_norm:
                return None
        self._last_input = p

        target = self.screen_point(float(p[0]), float(p[1]))
        sx = float(self._fx.filter(target[0], now))
        sy = float(self._fy.filter(target[1], now))
        smoothed = np.array([sx, sy])

        if self._pos is not None:
            step_px = float(np.linalg.norm(smoothed - self._pos))
            if step_px > self.cfg.max_step_px:
                smoothed = self._pos + (smoothed - self._pos) * (
                    self.cfg.max_step_px / max(step_px, 1e-6)
                )
        self._pos = smoothed
        self._last_t = now
        return int(round(smoothed[0])), int(round(smoothed[1]))

    # ------------------------------------------------------------------ #
    def delta(self, d_norm: Tuple[float, float], now: float) -> Optional[Tuple[int, int]]:
        """Относительный режим: смещение руки -> смещение курсора (как джойстик)."""
        dt = 1.0 / 60.0 if self._last_t is None else max(now - self._last_t, 1e-3)
        self._last_t = now

        dx = deadzone(float(d_norm[0]), self.cfg.deadzone_norm)
        dy = deadzone(float(d_norm[1]), self.cfg.deadzone_norm)
        if dx == 0.0 and dy == 0.0:
            return None

        w, h = self.screen_size
        if self._pos is None:
            self._pos = np.array([w / 2.0, h / 2.0])
        step = np.array([dx * self.cfg.relative_gain * dt, dy * self.cfg.relative_gain * dt])
        step = np.clip(step, -self.cfg.max_step_px, self.cfg.max_step_px)

        target = self._pos + step
        sx = float(self._fx.filter(target[0], now))
        sy = float(self._fy.filter(target[1], now))
        self._pos = np.array([
            clamp(sx, 0.0, w - 1.0),
            clamp(sy, 0.0, h - 1.0),
        ])
        return int(round(self._pos[0])), int(round(self._pos[1]))

    def set_screen_size(self, size: Tuple[int, int]) -> None:
        self.screen_size = size
