"""Резервный бэкенд «совсем без нейросетей»: классическое компьютерное зрение.

Что используется:
* цветовая сегментация кожи в YCrCb + HSV;
* морфология, поиск контуров, выпуклая оболочка;
* «звёздный скелет» — радиальный профиль контура (сколько лучей у силуэта).

Чего здесь принципиально нет: 21 точки скелета кисти. Поэтому управление
грубее: указатель — верхняя точка силуэта, «сжатие» кисти = клик, сжатие с
удержанием и движением = прокрутка. Работает при ровном свете и однотонном
фоне; на пёстром фоне точность падает — это ограничение метода, а не баг.

Управление целиком опирается на ОТНОСИТЕЛЬНЫЙ размер силуэта (радиус к
адаптивному эталону раскрытой ладони), поэтому не требует абсолютных порогов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import HandConfig
from .gestures import Event

SQUEEZE_RATIO = 0.80     # радиус меньше 80% эталона = кисть сжата
CLICK_MAX_HOLD = 0.70    # сжатие короче 0.7 с = клик, дольше = прокрутка


@dataclass
class HandShape:
    """Силуэт кисти, найденный цветовой сегментацией."""

    centroid: np.ndarray                 # нормализованные координаты
    pointer: np.ndarray                  # верхняя точка силуэта
    area_ratio: float                    # площадь контура / площадь кадра
    radius: float                        # ~радиус ладони, нормированный
    rays: int                            # «лучи» силуэта (пальцы, приблизительно)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    contour: Optional[np.ndarray] = None
    hull: Optional[np.ndarray] = None


class SkinDetector:
    """Маска кожи + подготовка к поиску контура."""

    def __init__(self, width: int = 400) -> None:
        self.width = width
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self.kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    def mask(self, bgr: np.ndarray) -> np.ndarray:
        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        y, cr, cb = cv2.split(ycrcb)
        h, s, v = cv2.split(hsv)

        skin_ycc = ((cr > 132) & (cr < 178) & (cb > 74) & (cb < 130) & (y > 35))
        skin_hsv = ((h < 25) | (h > 160)) & (s > 35) & (s < 210) & (v > 45)
        mask = ((skin_ycc | skin_hsv).astype(np.uint8)) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel_close)
        return mask


def radial_profile(contour: np.ndarray, centroid: np.ndarray, bins: int = 72) -> np.ndarray:
    """«Звёздный скелет»: максимальный радиус контура в каждом угловом секторе."""
    pts = contour.reshape(-1, 2).astype(np.float64) - np.asarray(centroid, dtype=np.float64)
    angles = np.arctan2(pts[:, 1], pts[:, 0])
    radii = np.linalg.norm(pts, axis=1)
    idx = ((angles + np.pi) / (2.0 * np.pi) * bins).astype(int) % bins
    profile = np.zeros(bins, dtype=np.float64)
    np.maximum.at(profile, idx, radii)
    for i in range(bins):  # пустые секторы заполняем соседями
        if profile[i] == 0:
            profile[i] = max(profile[(i - 1) % bins], profile[(i + 1) % bins])
    kernel = np.array([1.0, 2.0, 1.0]) / 4.0
    padded = np.concatenate([profile[-2:], profile, profile[:2]])
    return np.convolve(padded, kernel, mode="same")[2:-2]


def count_rays(profile: np.ndarray, min_prominence: float = 0.18) -> int:
    """Сколько заметных выступов у силуэта (для справки в оверлее)."""
    n = len(profile)
    hi, lo = float(profile.max()), float(profile.min())
    if hi <= 0:
        return 0
    threshold = lo + min_prominence * (hi - lo)
    candidates = [
        i for i in range(n)
        if profile[i] >= profile[(i - 1) % n]
        and profile[i] >= profile[(i + 1) % n]
        and profile[i] > threshold
    ]
    merged: List[int] = []
    for i in candidates:
        if merged and min(abs(i - merged[-1]), n - abs(i - merged[-1])) <= 2:
            if profile[i] > profile[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)
    if len(merged) > 1 and min(abs(merged[0] - merged[-1]), n - abs(merged[0] - merged[-1])) <= 2:
        merged.pop()
    return min(len(merged), 5)


def find_hand(
    frame_bgr: np.ndarray,
    detector: Optional[SkinDetector] = None,
    min_area_ratio: float = 0.008,
) -> Optional[HandShape]:
    """Ищет кисть в кадре. ``None``, если ничего похожего нет."""
    detector = detector or SkinDetector()
    h, w = frame_bgr.shape[:2]
    scale = detector.width / float(w)
    small = cv2.resize(frame_bgr, (detector.width, max(int(h * scale), 1)))
    mask = detector.mask(small)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    frame_area = float(small.shape[0] * small.shape[1])
    area = float(cv2.contourArea(contour))
    if area / frame_area < min_area_ratio:
        return None

    moments = cv2.moments(contour)
    if abs(moments["m00"]) < 1e-6:
        return None
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    radius = float(np.sqrt(area / np.pi))
    profile = radial_profile(contour, np.array([cx, cy]))

    pts = contour.reshape(-1, 2)
    top = pts[int(np.argmin(pts[:, 1]))].astype(np.float64)
    hull_pts = cv2.convexHull(contour, returnPoints=True)

    sx = w / float(small.shape[1])
    sy = h / float(small.shape[0])
    return HandShape(
        centroid=np.array([cx / small.shape[1], cy / small.shape[0]]),
        pointer=np.array([top[0] / small.shape[1], top[1] / small.shape[0]]),
        area_ratio=area / frame_area,
        radius=radius / max(small.shape[0], 1),
        rays=count_rays(profile),
        bbox=(int(cx * sx), int(cy * sy), int(radius * sx), int(radius * sy)),
        contour=(contour.reshape(-1, 2) * np.array([sx, sy])).astype(np.int32),
        hull=(hull_pts.reshape(-1, 2) * np.array([sx, sy])).astype(np.int32),
    )


class ClassicalFSM:
    """События без скелета: указатель, «сжатие» = клик, сжатие + движение = прокрутка."""

    def __init__(self, cfg: HandConfig) -> None:
        self.cfg = cfg
        self._open_ref = 0.0
        self._squeeze_since: Optional[float] = None
        self._last_click = -1e9
        self._anchor_y: Optional[float] = None
        self._scroll = 0.0
        self._scrolled = False

    @property
    def squeezing(self) -> bool:
        return self._squeeze_since is not None

    def update(self, shape: Optional[HandShape], now: float) -> List[Event]:
        events: List[Event] = []
        if shape is None:
            self._squeeze_since = None
            self._anchor_y = None
            self._scroll = 0.0
            self._scrolled = False
            return events

        # эталон «раскрытой ладони» — максимум радиуса с медленным забыванием
        self._open_ref = max(shape.radius, self._open_ref * 0.995)
        squeeze = self._open_ref > 1e-5 and shape.radius < SQUEEZE_RATIO * self._open_ref

        if squeeze:
            if self._squeeze_since is None:
                self._squeeze_since = now
                self._anchor_y = float(shape.centroid[1])
                self._scrolled = False
            held = now - self._squeeze_since
            if held > CLICK_MAX_HOLD:
                dy = (self._anchor_y or 0.0) - float(shape.centroid[1])
                self._anchor_y = float(shape.centroid[1])
                if abs(dy) > self.cfg.fist_scroll_deadzone:
                    self._scroll += dy * self.cfg.fist_scroll_gain
                    ticks = int(self._scroll)
                    if ticks:
                        self._scroll -= ticks
                        self._scrolled = True
                        events.append(Event("scroll", value=ticks, label="прокрутка"))
            events.append(Event("pointer_freeze", label="сжатие"))
        else:
            if self._squeeze_since is not None:
                held = now - self._squeeze_since
                if held < CLICK_MAX_HOLD and not self._scrolled and (now - self._last_click) > 0.4:
                    events.append(Event("pinch_release", label="сжатие"))
                    self._last_click = now
                self._squeeze_since = None
                self._scroll = 0.0
                self._scrolled = False
            events.append(Event("pointer", value=tuple(shape.pointer)))

        return events


class ClassicalTracker:
    """Обёртка под общий интерфейс: ``process`` + ``process_events``."""

    name = "classical"

    def __init__(
        self,
        hand_cfg: HandConfig,
        min_area_ratio: float = 0.008,
        width: int = 400,
    ) -> None:
        self.detector = SkinDetector(width=width)
        self.fsm = ClassicalFSM(hand_cfg)
        self.min_area_ratio = min_area_ratio
        self.last_shape: Optional[HandShape] = None

    def process(self, frame_bgr: np.ndarray, ts_ms: int):
        from .tracker import FrameResult

        self.last_shape = find_hand(frame_bgr, self.detector, self.min_area_ratio)
        return FrameResult(hands=[], face=None, backend="classical")

    def process_events(self, frame_bgr: np.ndarray, ts_ms: int, now: float):
        shape = find_hand(frame_bgr, self.detector, self.min_area_ratio)
        self.last_shape = shape
        return self.fsm.update(shape, now), shape

    def close(self) -> None:
        pass
