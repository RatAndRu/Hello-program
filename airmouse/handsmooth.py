"""Сглаживание кисти «аналитически»: ладонь как жёсткое тело, пальцы — в её системе.

Зачем. Нейросеть отдаёт 21 точку независимо, и каждая дрожит по-своему. Если
сглаживать их по отдельности (или, хуже, предсказывать каждую своей
скоростью), кисть расползается: пальцы «плывут» относительно ладони, а при
потере кадра — разлетаются. Глазу это видно как каша из линий.

Что делается вместо этого:

* **Поза ладони** — три величины: положение запястья, угол (запястье →
  основание среднего пальца) и масштаб (размер ладони). Они фильтруются
  1€-фильтром (Casiez et al., 2012): стоит рука — дрожание давится, пошла —
  проходит без запаздывания.
* **Пальцы — в системе координат ладони**: каждая точка записывается как
  (вдоль оси ладони, поперёк, глубина) в долях размера ладони. Палец, который
  не двигается относительно ладони, в этой системе **стоит**, даже когда вся
  рука едет по кадру — и фильтр его честно удерживает. Сгиб пальца — быстрое
  изменение локальных координат — проходит сразу (тот же 1€, свой порог).
* **Предсказание при потере** — только жёсткое: кисть целиком едет дальше со
  скоростью ладони, скорость гаснет с каждым кадром, форма пальцев заморожена.
  Никаких «пальцев, которые продолжают сгибаться по инерции».

На выходе — та же 21 точка в координатах кадра, но ровная, цельная и
совпадающая с настоящим движением. Модуль чистый (numpy).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .filters import OneEuroFilter
from .landmarks import Hand, MIDDLE_MCP, WRIST

# Скорость ладони при потере гаснет на столько за кадр: через пять кадров от
# неё остаётся четверть, кисть мягко останавливается, а не улетает.
PREDICT_DAMPING = 0.75
# Быстрее этого (в размерах ладони за секунду) кисть не двигается; всё, что
# выше, — скачок детектора, его в предсказание не пускаем.
MAX_PALM_SPEED = 8.0


def palm_frame(points: np.ndarray):
    """Система координат ладони: (запястье, ось u, ось v, масштаб)."""
    pts = np.asarray(points, dtype=np.float64)
    wrist = pts[WRIST, :2].copy()
    axis = pts[MIDDLE_MCP, :2] - wrist
    scale = float(np.linalg.norm(axis))
    if scale < 1e-6:
        return wrist, np.array([1.0, 0.0]), np.array([0.0, 1.0]), 1e-6
    u = axis / scale
    v = np.array([-u[1], u[0]])
    return wrist, u, v, scale


def to_local(points: np.ndarray) -> np.ndarray:
    """Точки кадра → локальные (21, 3): вдоль, поперёк, глубина — в долях ладони."""
    pts = np.asarray(points, dtype=np.float64)
    wrist, u, v, scale = palm_frame(pts)
    rel = pts[:, :2] - wrist
    local = np.zeros((pts.shape[0], 3), dtype=np.float64)
    local[:, 0] = rel @ u / scale
    local[:, 1] = rel @ v / scale
    if pts.shape[1] > 2:
        local[:, 2] = (pts[:, 2] - pts[WRIST, 2]) / scale
    return local


def from_local(local: np.ndarray, wrist: np.ndarray, angle: float, scale: float,
               wrist_z: float = 0.0) -> np.ndarray:
    """Локальные координаты + поза ладони → точки кадра (21, 3)."""
    u = np.array([math.cos(angle), math.sin(angle)])
    v = np.array([-u[1], u[0]])
    pts = np.zeros((local.shape[0], 3), dtype=np.float64)
    pts[:, :2] = wrist + scale * (np.outer(local[:, 0], u) + np.outer(local[:, 1], v))
    pts[:, 2] = wrist_z + scale * local[:, 2]
    return pts


class _PointwiseOneEuro:
    """1€-фильтр для облака точек: у каждой точки **своя** скорость и отсечка.

    Общий фильтр усредняет скорость по всем точкам, и один согнувшийся палец
    «тонет» среди двадцати неподвижных — его сгиб приходил с запозданием.
    Здесь точка, которая двигается, проходит быстро, а соседние стоят ровно.
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x: Optional[np.ndarray] = None
        self._dx: Optional[np.ndarray] = None
        self._t: Optional[float] = None

    def reset(self) -> None:
        self._x = self._dx = None
        self._t = None

    @staticmethod
    def _alpha(cutoff, dt: float):
        tau = 1.0 / (2.0 * math.pi * np.maximum(cutoff, 1e-6))
        return 1.0 / (1.0 + tau / dt)

    def filter(self, value: np.ndarray, t: float) -> np.ndarray:
        value = np.asarray(value, dtype=np.float64)
        if self._t is None or self._x is None:
            self._t = t
            self._x = value.copy()
            self._dx = np.zeros_like(value)
            return value.copy()
        dt = max(t - self._t, 1e-4)
        self._t = t
        raw_dx = (value - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * raw_dx + (1.0 - a_d) * self._dx
        speed = np.linalg.norm(self._dx, axis=-1, keepdims=True)   # на точку
        cutoff = self.min_cutoff + self.beta * speed
        a = self._alpha(cutoff, dt)
        self._x = a * value + (1.0 - a) * self._x
        return self._x.copy()


def _unwrap(angle: float, reference: float) -> float:
    """Угол, ближайший к ``reference`` (без скачка через ±π)."""
    while angle - reference > math.pi:
        angle -= 2.0 * math.pi
    while angle - reference < -math.pi:
        angle += 2.0 * math.pi
    return angle


class HandSmoother:
    """Сглаживание одной кисти + жёсткое предсказание на потерянных кадрах."""

    def __init__(self, pose_cutoff: float = 1.5, finger_cutoff: float = 1.8,
                 finger_beta: float = 1.2) -> None:
        # beta у каждого фильтра свой, потому что единицы скорости разные:
        # запястье — доли кадра в секунду (0.3…3), угол — радианы, масштаб —
        # доли кадра, локальные координаты пальцев — размеры ладони (до ~15).
        self._wrist = OneEuroFilter(min_cutoff=pose_cutoff, beta=25.0)
        self._angle = OneEuroFilter(min_cutoff=pose_cutoff, beta=1.5)
        self._scale = OneEuroFilter(min_cutoff=pose_cutoff, beta=40.0)
        self._local = _PointwiseOneEuro(min_cutoff=finger_cutoff, beta=finger_beta)
        self._depth = OneEuroFilter(min_cutoff=pose_cutoff, beta=0.0)
        self._angle_prev: Optional[float] = None
        self._last: Optional[np.ndarray] = None      # последние сглаженные точки
        self._last_t: Optional[float] = None
        self._velocity = np.zeros(2)                   # скорость запястья, ед./с
        self._prev_wrist: Optional[np.ndarray] = None
        self.handedness = "Right"
        self.score = 1.0

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        for f in (self._wrist, self._angle, self._scale, self._local, self._depth):
            f.reset()
        self._angle_prev = None
        self._last = None
        self._last_t = None
        self._velocity = np.zeros(2)
        self._prev_wrist = None

    @property
    def points(self) -> Optional[np.ndarray]:
        return None if self._last is None else self._last.copy()

    # ------------------------------------------------------------------ #
    def update(self, hand: Hand, now: float) -> Hand:
        """Измеренная кисть → сглаженная (та же сторона и уверенность)."""
        pts = np.asarray(hand.points, dtype=np.float64)
        self.handedness = hand.handedness
        self.score = float(getattr(hand, "score", 1.0))
        wrist, u, _v, scale = palm_frame(pts)
        angle = math.atan2(u[1], u[0])
        if self._angle_prev is not None:
            angle = _unwrap(angle, self._angle_prev)
        wrist_z = float(pts[WRIST, 2]) if pts.shape[1] > 2 else 0.0

        sw = np.asarray(self._wrist.filter(wrist, now), dtype=np.float64)
        sa = float(self._angle.filter(angle, now))
        ss = float(self._scale.filter(scale, now))
        sl = np.asarray(self._local.filter(to_local(pts), now), dtype=np.float64)
        sz = float(self._depth.filter(wrist_z, now))
        self._angle_prev = sa

        # скорость запястья — для предсказания; дребезг и скачки отсекаем
        if self._prev_wrist is not None and self._last_t is not None:
            dt = max(now - self._last_t, 1e-3)
            raw = (sw - self._prev_wrist) / dt
            limit = MAX_PALM_SPEED * max(ss, 1e-6)
            raw = np.clip(raw, -limit, limit)
            self._velocity = 0.5 * self._velocity + 0.5 * raw
        self._prev_wrist = sw.copy()
        self._last_t = now

        out = from_local(sl, sw, sa, ss, sz)
        np.clip(out[:, :2], 0.0, 1.0, out=out[:, :2])
        self._last = out
        return Hand(out.astype(np.float32), hand.handedness, self.score)

    def predict(self, now: float) -> Optional[Hand]:
        """Кадр без кисти: сдвинуть всю руку жёстко, форму пальцев не трогать."""
        if self._last is None or self._last_t is None:
            return None
        dt = max(now - self._last_t, 1e-3)
        self._velocity = self._velocity * PREDICT_DAMPING
        step = self._velocity * dt
        out = self._last.copy()
        out[:, :2] += step
        np.clip(out[:, :2], 0.0, 1.0, out=out[:, :2])
        self._last = out
        self._last_t = now
        if self._prev_wrist is not None:
            self._prev_wrist = self._prev_wrist + step
        # фильтры «едут» вместе с рукой: после возврата кисти они не дёргают
        # её назад к точке, где она пропала
        if self._wrist._x is not None:
            self._wrist._x = np.asarray(self._wrist._x, dtype=np.float64) + step
            self._wrist._t = now
        return Hand(out.astype(np.float32), self.handedness, self.score * 0.85)
