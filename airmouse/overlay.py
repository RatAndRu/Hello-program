"""Отрисовка окна предпросмотра (OpenCV).

Подписи намеренно латиницей: встроенные шрифты OpenCV не умеют кириллицу.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import cv2
import numpy as np

from .landmarks import F, HAND_CONNECTIONS, LIPS_INNER, LIPS_OUTER, Face, Hand
from .filters import clamp

BG = (28, 28, 32)
FG = (235, 235, 235)
ACCENT = (120, 220, 120)
WARN = (80, 170, 255)
BAD = (70, 70, 230)
DIM = (150, 150, 155)


@dataclass
class OverlayState:
    fps: float = 0.0
    backend: str = ""
    pose: str = "—"
    paused: bool = False
    warmup: bool = False
    head_pointer: bool = False
    hand_seen: bool = False
    face_seen: bool = False
    ear: float = 0.30
    smile: float = 0.0
    brow: float = 0.0
    mouth_open: float = 0.0
    lip_word: str = ""
    last_event: str = ""
    active_box: Sequence[float] = (0.16, 0.14, 0.84, 0.86)
    hints: str = "Q quit   P pause   H head-mouse"


def _panel(img: np.ndarray, x: int, y: int, w: int, h: int, alpha: float = 0.55) -> None:
    x2 = min(img.shape[1], x + w)
    y2 = min(img.shape[0], y + h)
    roi = img[max(y, 0):y2, max(x, 0):x2]
    if roi.size == 0:
        return
    rect = np.full_like(roi, BG, dtype=np.uint8)
    cv2.addWeighted(rect, alpha, roi, 1 - alpha, 0, roi)


def _bar(img, x, y, w, h, value, color, label, vmin=0.0, vmax=1.0) -> None:
    cv2.rectangle(img, (x, y), (x + w, y + h), (70, 70, 75), 1)
    frac = clamp((value - vmin) / max(vmax - vmin, 1e-6), 0.0, 1.0)
    if frac > 0:
        cv2.rectangle(img, (x + 1, y + 1), (x + 1 + int((w - 2) * frac), y + h - 1), color, -1)
    cv2.putText(img, label, (x + w + 8, y + h - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.42, DIM, 1, cv2.LINE_AA)


def draw_hand(img: np.ndarray, hand: Hand, color=ACCENT, thickness: int = 2) -> None:
    h, w = img.shape[:2]
    pts = hand.to_pixels(w, h).astype(np.int32)
    for a, b in HAND_CONNECTIONS:
        cv2.line(img, tuple(pts[a]), tuple(pts[b]), color, thickness, cv2.LINE_AA)
    for i, (x, y) in enumerate(pts):
        r = 4 if i in (4, 8, 12, 16, 20) else 3
        cv2.circle(img, (int(x), int(y)), r, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(y)), r, color, 1, cv2.LINE_AA)


_EYE_A_POLY = (F.EYE_A[0], F.EYE_A[1], F.EYE_A[2], F.EYE_A[3], F.EYE_A[4], F.EYE_A[5])
_EYE_B_POLY = (F.EYE_B[0], F.EYE_B[1], F.EYE_B[2], F.EYE_B[3], F.EYE_B[4], F.EYE_B[5])


def draw_face(img: np.ndarray, face: Face, metrics=None) -> None:
    """Схематичное лицо: глаза, брови, губы, нос."""
    h, w = img.shape[:2]
    pts = face.to_pixels(w, h)

    def poly(indices, color=WARN, closed=True, thickness=1) -> None:
        p = pts[list(indices)].astype(np.int32)
        cv2.polylines(img, [p], closed, color, thickness, cv2.LINE_AA)

    poly(_EYE_A_POLY, WARN)
    poly(_EYE_B_POLY, WARN)
    poly(LIPS_OUTER, (200, 200, 120))
    poly(LIPS_INNER, (120, 220, 220))
    cv2.line(img, tuple(pts[F.BROW_A - 8].astype(int)), tuple(pts[F.BROW_A + 8].astype(int)),
             ACCENT, 1, cv2.LINE_AA)
    cv2.line(img, tuple(pts[F.BROW_B - 8].astype(int)), tuple(pts[F.BROW_B + 8].astype(int)),
             ACCENT, 1, cv2.LINE_AA)
    cv2.line(img, tuple(pts[F.NOSE_BRIDGE].astype(int)), tuple(pts[F.NOSE_TIP].astype(int)),
             WARN, 1, cv2.LINE_AA)
    for idx in (F.NOSE_TIP, F.CHIN):
        cv2.circle(img, tuple(pts[idx].astype(int)), 2, WARN, -1, cv2.LINE_AA)


def render(
    frame: np.ndarray,
    state: OverlayState,
    hands: Optional[List[Hand]] = None,
    face: Optional[Face] = None,
    shape=None,
    metrics=None,
) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]

    # активная зона, в которой рука управляет курсором
    x0, y0, x1, y1 = state.active_box
    cv2.rectangle(
        img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (90, 90, 95), 1
    )

    for hand in hands or []:
        draw_hand(img, hand, ACCENT if not state.paused else DIM)
    if face is not None:
        draw_face(img, face, metrics)
    if shape is not None and getattr(shape, "contour", None) is not None:
        cv2.drawContours(img, [shape.contour], -1, ACCENT, 2)
        if shape.hull is not None:
            cv2.drawContours(img, [shape.hull], -1, WARN, 1)
        px, py = shape.pointer
        cv2.circle(img, (int(px * w), int(py * h)), 6, (0, 255, 255), 2)

    # ---------------------------------------------------------------- HUD
    _panel(img, 10, 10, 258, 134)
    cv2.putText(img, "AirMouse", (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7, FG, 2, cv2.LINE_AA)
    cv2.putText(
        img, f"{state.fps:5.1f} fps  {state.backend}", (20, 56),
        cv2.FONT_HERSHEY_SIMPLEX, 0.42, DIM, 1, cv2.LINE_AA,
    )
    if state.paused:
        status, color = "PAUSED", BAD
    elif state.warmup:
        status, color = "GET READY", WARN
    elif state.hand_seen:
        status, color = "TRACKING", ACCENT
    else:
        status, color = "no hand", WARN
    cv2.putText(img, status, (20, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    cv2.putText(
        img, f"pose: {state.pose}", (20, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.5, FG, 1, cv2.LINE_AA
    )
    mode = "head-mouse ON" if state.head_pointer else "hand-mouse"
    cv2.putText(img, mode, (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA)

    # метрики лица
    if state.face_seen:
        _panel(img, w - 250, 10, 240, 116)
        bx = w - 210
        _bar(img, bx, 24, 110, 10, state.ear, WARN, "EAR", 0.0, 0.45)
        _bar(img, bx, 48, 110, 10, max(0.0, state.smile), ACCENT, "smile", -0.05, 0.15)
        _bar(img, bx, 72, 110, 10, max(0.0, state.brow), ACCENT, "brow", -0.05, 0.15)
        _bar(img, bx, 96, 110, 10, state.mouth_open, WARN, "mouth", 0.0, 1.0)

    if state.lip_word:
        _panel(img, w // 2 - 90, 10, 180, 34, 0.7)
        cv2.putText(
            img, f'lip: {state.lip_word}', (w // 2 - 80, 33),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, ACCENT, 2, cv2.LINE_AA,
        )

    if state.last_event:
        cv2.putText(
            img, state.last_event, (18, h - 44),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2, cv2.LINE_AA,
        )
    cv2.putText(
        img, state.hints, (18, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA
    )

    if state.paused:
        cv2.putText(
            img, "PAUSED", (w // 2 - 90, h // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 1.4, BAD, 3, cv2.LINE_AA,
        )
    elif state.warmup:
        cv2.putText(
            img, "GET READY", (w // 2 - 110, h // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, WARN, 2, cv2.LINE_AA,
        )
    return img
