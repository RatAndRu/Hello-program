"""Взаимная подсказка «тело ↔ голова»: одна часть помогает найти другую.

Кадр веб-камеры почти никогда не показывает человека целиком и одинаково
хорошо: то лицо размыто поворотом, то из тела видна только голова с руками.
Поэтому две модели работают на пару:

* **тело знает, где голова** — по точкам позы (нос, глаза, уши) считается
  рамка головы; если лицо потерялось на кадре, оно рисуется пунктиром там, где
  голова точно есть, а не «где-то в кадре»;
* **лицо знает, где голова тела** — если у скелета не видно точек головы
  (человек стоит спиной к свету, голова «залипла» в фон), голова скелета
  достраивается по лицу: скелет перестаёт быть обрубком на шее;
* если пропали оба — работает **предсказание по движению**: голова едет
  последней скоростью ещё несколько кадров, ровно как кисть в
  :mod:`airmouse.handtrack`.

Здесь нет ни MediaPipe, ни OpenCV — только numpy и точки, которые уже
принесла нейросеть.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from .body import B
from .landmarks import F, Face

Box = Tuple[float, float, float, float]        # x0, y0, x1, y1 — доли кадра

# точки позы, которыми описывается голова
HEAD_POSE = (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR, B.MOUTH_L, B.MOUTH_R)


def _vis(points: np.ndarray, index: int) -> float:
    return float(points[index, 3]) if points.shape[1] > 3 else 1.0


def _bbox(pts: np.ndarray, pad: float) -> Box:
    x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
    x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
    w = max(x1 - x0, 1e-4)
    h = max(y1 - y0, 1e-4)
    return (x0 - pad * w, y0 - pad * h, x1 + pad * w, y1 + pad * h)


def head_box_from_body(points: Optional[Sequence[Sequence[float]]],
                       min_visibility: float = 0.35) -> Optional[Box]:
    """Рамка головы по точкам позы. ``None`` — головы в кадре не видно.

    Нужны минимум три точки из семи (нос, глаза, уши, углы рта): по одной
    точке рамку не построить, а по двум она получается вытянутой в линию.
    """
    if points is None:
        return None
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 33:
        return None
    seen = [i for i in HEAD_POSE if _vis(pts, i) >= min_visibility]
    if len(seen) < 3:
        return None
    return _bbox(pts[seen, :2], pad=0.35)


def face_box(face: Optional[Face], pad: float = 0.06) -> Optional[Box]:
    """Рамка лица по его же точкам: лоб, подбородок, скулы."""
    if face is None:
        return None
    pts = np.asarray(face.points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 200:
        return None
    ids = [i for i in (F.FOREHEAD, F.CHIN, F.CHEEK_LEFT, F.CHEEK_RIGHT,
                       F.NOSE_TIP) if i < pts.shape[0]]
    return _bbox(pts[ids, :2], pad=pad)


def _box_center(box: Box) -> np.ndarray:
    return np.array([0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3])], dtype=float)


def _box_shift(box: Box, shift: np.ndarray) -> Box:
    dx, dy = float(shift[0]), float(shift[1])
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


@dataclass
class HeadAnchor:
    """Итог подсказки на этот кадр: где голова и откуда это известно."""

    box: Optional[Box] = None
    source: str = ""               # "face" | "body" | "track" | ""
    predicted: bool = False
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))

    @property
    def ok(self) -> bool:
        return self.box is not None

    @property
    def center(self) -> Optional[np.ndarray]:
        return None if self.box is None else _box_center(self.box)

    @property
    def size(self) -> float:
        if self.box is None:
            return 0.0
        return max(float(self.box[2] - self.box[0]), float(self.box[3] - self.box[1]))

    def note(self) -> str:
        if self.box is None:
            return ""
        if self.source == "face":
            return ""
        if self.source == "body":
            return "лицо не видно — показываю по телу"
        if self.source == "track":
            return "лицо не видно — веду по движению"
        return ""


# --------------------------------------------------------------------------- #
#  Голова из лица: те же точки, но для скелета тела
# --------------------------------------------------------------------------- #
def _eye_center(pts: np.ndarray, ids: Sequence[int]) -> np.ndarray:
    idx = [i for i in ids if i < pts.shape[0]]
    return pts[idx, :2].mean(axis=0) if idx else np.zeros(2)


def head_points_from_face(face: Optional[Face]) -> Dict[int, np.ndarray]:
    """Точки головы скелета, посчитанные по лицу: {индекс позы: (x, y)}.

    Углы рта берутся по внешним точкам губ, уши — по скулам (настоящих ушей
    FaceMesh не даёт), глаза — по центрам век.
    """
    if face is None:
        return {}
    pts = np.asarray(face.points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 400:
        return {}
    nose = pts[F.NOSE_TIP, :2].copy()
    eye_a = _eye_center(pts, F.EYE_A)
    eye_b = _eye_center(pts, F.EYE_B)
    left, right = sorted((eye_a, eye_b), key=lambda p: p[0])
    return {
        B.NOSE: nose,
        B.L_EYE: left,
        B.R_EYE: right,
        # «уши» = скулы с небольшим отступом наружу: скелет рисует по ним
        # ширину головы, а не настоящую раковину
        B.L_EAR: pts[F.CHEEK_LEFT, :2] + np.array([-0.01, 0.0]),
        B.R_EAR: pts[F.CHEEK_RIGHT, :2] + np.array([0.01, 0.0]),
        B.MOUTH_L: pts[F.MOUTH_LEFT, :2],
        B.MOUTH_R: pts[F.MOUTH_RIGHT, :2],
    }


def patch_head(body: Optional[np.ndarray], face: Optional[Face],
               min_visibility: float = 0.35) -> Optional[np.ndarray]:
    """Достраивает невидимые точки головы скелета по лицу.

    Возвращает копию (исходный массив не трогаем: он принадлежит трекеру и
    нужен другим подсказкам). Если достраивать нечего — возвращает то, что дали.
    """
    if body is None:
        return None
    pts = head_points_from_face(face)
    if not pts:
        return body
    out = np.array(body, dtype=np.float64, copy=True)
    if out.shape[1] < 4:
        out = np.hstack([out, np.ones((out.shape[0], 1))])
    changed = False
    for index, xy in pts.items():
        if _vis(out, index) < min_visibility:
            out[index, :2] = xy
            out[index, 3] = max(float(out[index, 3]), 0.9)
            changed = True
    return out if changed else body


# --------------------------------------------------------------------------- #
#  Сама подсказка: кто кого находит и что показываем
# --------------------------------------------------------------------------- #
class FaceBodyAnchor:
    """Держит голову «на связи», пока одна из моделей её не видит.

    Порядок доверия: **лицо** (точное измерение) → **тело** (голова в позе
    видна даже когда лицо потеряно поворотом) → **предсказание** (голова едет
    последней скоростью ``predict_frames`` кадров, ≈ 0.25 с).
    """

    def __init__(self, predict_frames: int = 8, smooth: float = 0.5,
                 body_visibility: float = 0.35) -> None:
        self.predict_frames = max(int(predict_frames), 0)
        self.smooth = float(smooth)
        self.body_visibility = float(body_visibility)
        self.anchor = HeadAnchor()
        self._last_box: Optional[Box] = None
        self._velocity = np.zeros(2)
        self._t = 0.0
        self.missed = 0

    def reset(self) -> None:
        self.anchor = HeadAnchor()
        self._last_box = None
        self._velocity = np.zeros(2)
        self._t = 0.0
        self.missed = 0

    # ------------------------------------------------------------------ #
    def update(self, face: Optional[Face], body: Optional[np.ndarray],
               now: float) -> HeadAnchor:
        measured = face_box(face)
        from_body = head_box_from_body(body, self.body_visibility)
        dt = max(now - self._t, 1e-3) if self._last_box is not None else 0.0
        self._t = now

        if measured is not None:
            center = _box_center(measured)
            if dt > 0.0 and self._last_box is not None:
                step = (center - _box_center(self._last_box)) / dt
                self._velocity = 0.6 * self._velocity + 0.4 * step
                # центр головы не может лететь быстрее кадра целиком
                speed = float(np.linalg.norm(self._velocity))
                if speed > 4.0:
                    self._velocity *= 4.0 / speed
            self._last_box = measured
            self.missed = 0
            self.anchor = HeadAnchor(box=measured, source="face",
                                     velocity=self._velocity.copy())
            return self.anchor

        self.missed += 1
        if from_body is not None:
            # тело — настоящее измерение: голова точно там, просто лица не видно
            self._last_box = from_body
            self.anchor = HeadAnchor(box=from_body, source="body", predicted=True,
                                     velocity=self._velocity.copy())
            return self.anchor

        if self._last_box is not None and self.missed <= self.predict_frames:
            shift = self._velocity * dt if dt > 0.0 else np.zeros(2)
            predicted = _box_shift(self._last_box, shift)
            self._last_box = predicted
            self.anchor = HeadAnchor(box=predicted, source="track", predicted=True,
                                     velocity=self._velocity.copy())
            return self.anchor

        self.anchor = HeadAnchor()
        return self.anchor

    # ------------------------------------------------------------------ #
    def patch_body(self, body: Optional[np.ndarray], face: Optional[Face]
                   ) -> Optional[np.ndarray]:
        """Дорисовка головы скелета по лицу — «лицо помогает телу»."""
        return patch_head(body, face, self.body_visibility)
