"""Модель данных распознавания: точки руки и лица + геометрия.

Здесь нет ни MediaPipe, ни OpenCV — только numpy. Источник точек
(нейросеть MediaPipe, классическое CV или синтетика) подставляется снаружи.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

import numpy as np

Point = np.ndarray  # (..., 2) или (..., 3), нормализованные координаты 0..1


# --------------------------------------------------------------------------- #
#  Кисть: 21 точка, нумерация как в MediaPipe Hand
# --------------------------------------------------------------------------- #
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

FINGERS: dict[str, Tuple[int, int, int, int]] = {
    "thumb": (THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP),
    "index": (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
    "ring": (RING_MCP, RING_PIP, RING_DIP, RING_TIP),
    "pinky": (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
}

HAND_CONNECTIONS: Tuple[Tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

FINGERTIPS = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)


@dataclass
class Hand:
    """21 точка кисти в нормализованных координатах кадра (0..1)."""

    points: np.ndarray                     # (21, 3)
    handedness: str = "Right"              # "Left" | "Right"
    score: float = 1.0

    def __post_init__(self) -> None:
        pts = np.asarray(self.points, dtype=np.float32)
        if pts.ndim != 2 or pts.shape[0] < 21:
            raise ValueError(f"ожидалось (21,>=2) точек, получено {pts.shape}")
        if pts.shape[1] == 2:
            pts = np.hstack([pts, np.zeros((pts.shape[0], 1), dtype=np.float32)])
        self.points = pts

    def xy(self, index: int) -> np.ndarray:
        return self.points[index, :2].astype(np.float64).copy()

    @property
    def palm_size(self) -> float:
        """Масштаб кисти: запястье -> основание среднего пальца."""
        return float(np.linalg.norm(self.points[MIDDLE_MCP, :2] - self.points[WRIST, :2]))

    @property
    def palm_center(self) -> np.ndarray:
        ids = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
        return self.points[list(ids), :2].mean(axis=0)

    def to_pixels(self, width: int, height: int) -> np.ndarray:
        pts = self.points[:, :2].astype(np.float64).copy()
        pts[:, 0] *= width
        pts[:, 1] *= height
        return pts


# --------------------------------------------------------------------------- #
#  Лицо: 468 точек FaceMesh (нужны только некоторые)
# --------------------------------------------------------------------------- #
class F:
    """Индексы точек FaceMesh, которые мы используем."""

    # глаза (EAR): внешний угол, верхние/нижние веки, внутренний угол
    EYE_A = (33, 160, 158, 133, 153, 144)
    EYE_B = (362, 385, 387, 263, 373, 380)
    BROW_A = 105          # середина левой брови
    BROW_B = 334          # середина правой брови
    EYE_A_TOP = 159
    EYE_B_TOP = 386
    MOUTH_LEFT = 61
    MOUTH_RIGHT = 291
    LIP_TOP_INNER = 13
    LIP_BOTTOM_INNER = 14
    LIP_LEFT_INNER = 78
    LIP_RIGHT_INNER = 308
    LIP_TOP_OUTER = 0
    LIP_BOTTOM_OUTER = 17
    NOSE_TIP = 1
    NOSE_BRIDGE = 168
    CHIN = 152
    FOREHEAD = 10
    CHEEK_LEFT = 234
    CHEEK_RIGHT = 454


LIPS_INNER: Tuple[int, ...] = (
    78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308,
    324, 318, 402, 317, 14, 87, 178, 88, 95,
)
LIPS_OUTER: Tuple[int, ...] = (
    61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291,
    375, 321, 405, 314, 17, 84, 181, 91, 146,
)


@dataclass
class Face:
    """Точки лица в нормализованных координатах (0..1)."""

    points: np.ndarray
    score: float = 1.0

    def __post_init__(self) -> None:
        pts = np.asarray(self.points, dtype=np.float32)
        if pts.ndim != 2 or pts.shape[0] < 468:
            raise ValueError(f"ожидалось (468,3) точек, получено {pts.shape}")
        if pts.shape[1] == 2:
            pts = np.hstack([pts, np.zeros((pts.shape[0], 1), dtype=np.float32)])
        self.points = pts

    def xy(self, index: int) -> np.ndarray:
        return self.points[index, :2].astype(np.float64).copy()

    def polygon(self, indices: Iterable[int]) -> np.ndarray:
        return self.points[list(indices), :2].astype(np.float64)

    @property
    def scale(self) -> float:
        """Межзрачковое расстояние — естественная единица масштаба лица."""
        return float(np.linalg.norm(self.points[F.EYE_A[0], :2] - self.points[F.EYE_B[3], :2]))

    @property
    def interocular(self) -> float:
        return self.scale

    def to_pixels(self, width: int, height: int) -> np.ndarray:
        pts = self.points[:, :2].astype(np.float64).copy()
        pts[:, 0] *= width
        pts[:, 1] *= height
        return pts


# --------------------------------------------------------------------------- #
#  Геометрия
# --------------------------------------------------------------------------- #
def angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Угол ABC в градусах (в точке b): 180 — прямая линия."""
    v1 = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    v2 = np.asarray(c, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return math.degrees(math.acos(cos))


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    """Площадь многоугольника по формуле шухлядок (знак не важен)."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def rotate2d(v: np.ndarray, angle_rad: float) -> np.ndarray:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    x, y = float(v[0]), float(v[1])
    return np.array([x * c - y * s, x * s + y * c], dtype=np.float64)


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.zeros_like(v, dtype=np.float64)


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    return float(num) / float(den) if abs(den) > 1e-9 else default
