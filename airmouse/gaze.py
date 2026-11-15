"""Калибровка взгляда: «куда смотрю» → «куда поставить курсор».

Скоростной режим («зрачок отведён — курсор едет») требует косить глазами и
быстро утомляет. Абсолютный режим куда приятнее: человек смотрит в нужную часть
экрана, и курсор оказывается там. Для этого нужна одна калибровка: попросить
посмотреть в несколько точек экрана, запомнить положение зрачка в каждой и
подобрать преобразование «зрачок → экран».

Здесь только математика: точки, подгонка (наименьшие квадраты) и применение.
Ни камеры, ни окна — поэтому всё проверяется тестами без железа.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import numpy as np

# Куда просим посмотреть: 4 самых угла экрана + центр. Порядок — как обходим
# экран. Именно 0 и 1, а не «около угла»: калибровка идёт на весь монитор, а не
# на окно предпросмотра, иначе курсор не достаёт до краёв.
CALIBRATION_TARGETS: Tuple[Tuple[float, float], ...] = (
    (0.0, 0.0),        # левый верх
    (1.0, 0.0),        # правый верх
    (1.0, 1.0),        # правый низ
    (0.0, 1.0),        # левый низ
    (0.5, 0.5),        # центр — проверка и «середина»
)

TARGET_TITLES = (
    "левый верхний угол",
    "правый верхний угол",
    "правый нижний угол",
    "левый нижний угол",
    "центр экрана",
)


@dataclass
class GazeCalibration:
    """Преобразование «положение зрачка → точка экрана» (0..1)."""

    points: List[Tuple[float, float, float, float]] = field(default_factory=list)
    coef_x: List[float] = field(default_factory=list)
    coef_y: List[float] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return len(self.coef_x) == 3 and len(self.coef_y) == 3 and len(self.points) >= 3

    def add(self, gaze_x: float, gaze_y: float, screen_x: float, screen_y: float) -> None:
        self.points.append((float(gaze_x), float(gaze_y), float(screen_x), float(screen_y)))

    def fit(self) -> bool:
        """Подобрать коэффициенты по накопленным точкам."""
        if len(self.points) < 3:
            return False
        data = np.asarray(self.points, dtype=np.float64)
        gx, gy = data[:, 0], data[:, 1]
        # Если глаза двигались только по одной оси (или точки легли на линию),
        # полноценная аффинная подгонка вырождается — тогда каждая ось считается
        # только по своему зрачку.
        spread_x = float(gx.max() - gx.min())
        spread_y = float(gy.max() - gy.min())
        if len(self.points) >= 4 and spread_x > 1e-3 and spread_y > 1e-3:
            matrix = np.stack([gx, gy, np.ones_like(gx)], axis=1)
            cx, *_ = np.linalg.lstsq(matrix, data[:, 2], rcond=None)
            cy, *_ = np.linalg.lstsq(matrix, data[:, 3], rcond=None)
            self.coef_x = [float(v) for v in cx]
            self.coef_y = [float(v) for v in cy]
            return True

        def one_axis(values: np.ndarray, target: np.ndarray) -> List[float]:
            if float(np.ptp(values)) < 1e-6:
                return [0.0, 0.0, float(target.mean())]
            k, b = np.polyfit(values, target, 1)
            return [float(k), 0.0, float(b)]

        # по горизонтали — от gx, по вертикали — от gy
        self.coef_x = one_axis(gx, data[:, 2])
        self.coef_y = one_axis(gy, data[:, 3])
        return True

    def apply(self, gaze_x: float, gaze_y: float) -> Tuple[float, float]:
        """Куда поставить курсор: нормированные координаты экрана 0..1."""
        if not self.ready:
            return 0.5, 0.5
        cx, cy = self.coef_x, self.coef_y
        sx = cx[0] * gaze_x + cx[1] * gaze_y + cx[2]
        sy = cy[0] * gaze_x + cy[1] * gaze_y + cy[2]
        return float(min(1.0, max(0.0, sx))), float(min(1.0, max(0.0, sy)))

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, object]:
        return {"points": [[round(v, 5) for v in p] for p in self.points],
                "coef_x": [round(v, 6) for v in self.coef_x],
                "coef_y": [round(v, 6) for v in self.coef_y]}

    @classmethod
    def from_dict(cls, data: Dict[str, object] | None) -> "GazeCalibration":
        calib = cls()
        if not data:
            return calib
        try:
            points = data.get("points") or []
            calib.points = [tuple(float(v) for v in p) for p in points if len(p) == 4]
            calib.coef_x = [float(v) for v in (data.get("coef_x") or [])]
            calib.coef_y = [float(v) for v in (data.get("coef_y") or [])]
        except (TypeError, ValueError):
            return cls()
        if not calib.ready and calib.points:
            calib.fit()
        return calib

    def describe(self) -> str:
        if not self.ready:
            return "не калибровано"
        return f"калибровка взгляда: {len(self.points)} точек"


class GazeCursor:
    """Сглаживание абсолютной позиции курсора и мёртвая зона против дрожания.

    Зрачок дрожит (микросаккады), поэтому позицию сглаживаем, а мелкие
    перемещения в пределах ``deadzone_px`` игнорируем — иначе курсор «звенит»
    на месте. При этом крупные скачки (перевели взгляд в другой угол) проходят
    сразу — это и даёт эффект телепорта.
    """

    def __init__(self, deadzone_px: float = 12.0, alpha: float = 0.55) -> None:
        self.deadzone_px = float(deadzone_px)
        self.alpha = float(alpha)
        self.x: float | None = None
        self.y: float | None = None

    def reset(self) -> None:
        self.x = None
        self.y = None

    def update(self, target_x: float, target_y: float) -> Tuple[float, float] | None:
        """Вернуть новую позицию курсора или ``None``, если двигать не нужно."""
        if self.x is None or self.y is None:
            self.x, self.y = float(target_x), float(target_y)
            return self.x, self.y
        a = max(0.05, min(1.0, self.alpha))
        nx = a * float(target_x) + (1.0 - a) * self.x
        ny = a * float(target_y) + (1.0 - a) * self.y
        if abs(nx - self.x) < self.deadzone_px and abs(ny - self.y) < self.deadzone_px:
            return None
        self.x, self.y = nx, ny
        return nx, ny


def average_gaze(samples: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Среднее (по осям) положение зрачка за время «смотрения» на точку."""
    if not samples:
        return 0.0, 0.0
    arr = np.asarray(samples, dtype=np.float64)
    return float(arr[:, 0].mean()), float(arr[:, 1].mean())
