"""Трекер кисти: держит руку, когда нейросеть её потеряла или видит «ребром».

Зачем. Кисть, повёрнутая к камере ребром («полка»), читается плохо: пальцы
сливаются в линию, кончик уезжает, а иногда детектор пропадает на пару кадров.
Из-за этого на экране рука «прыгает», курсор дёргается, а жест «ладонь» мигает.
Такое поведение знакомо всем, кто делал жест-интерфейсы: MediaPipe Hands — это
**детектор на одном кадре** плюс внутренний трекинг (palm detector + landmark
model, Zhang et al., 2020, «MediaPipe Hands»), и при потере трека он запускает
детектор заново, теряя непрерывность. Практика (см. обзоры по аннотации видео с
MediaPipe, egocentric-пайплайны) одна: сглаживать точки по времени и
**предсказывать** их на пропущенных кадрах, а не показывать пропуск.

Что здесь сделано:

* у каждой руки свой «трек»: последние точки и скорость каждой из 21 точки
  (скорость сглаживается, ограничивается правдоподобным максимумом);
* детекции сопоставляются трекам по положению ладони (в единицах размера
  ладони) и стороне кисти — так две руки не «меняются местами», а одна рука,
  которую перекрыли, не создаёт вторую;
* если рука пропала, точки **продолжают движение** с набранной скоростью
  (``hand.predict_frames`` кадров, по умолчанию 6 ≈ 0.2 с), уверенность падает;
* если видно **тело**, предсказанную кисть подтягиваем к запястью из тела и
  разворачиваем вдоль предплечья — это и есть «достроить по тому месту, где рука
  была»: тело знает, где рука должна быть, даже когда кисть закрыта другой
  кистью или ушла из кадра;
* что нарисовано предсказанием, помечается (пунктиром и подписью), чтобы никто
  не думал, что это точные данные.

Модуль чистый (numpy), проверяется синтетикой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .landmarks import Hand, MIDDLE_MCP, WRIST


# Правдоподобная скорость кисти: сколько размеров ладони в секунду она может
# пройти. Быстрый взмах рукой — примерно 4–6; больше — уже рывок детектора.
MAX_SPEED_PALM = 8.0
# Насколько точка может сместиться между кадрами относительно ладони.
MAX_POINT_SPEED = 10.0


# «Ребром»: рука повёрнута к камере так, что кисть схлопывается в линию
# («полка»). Нейросеть в этом ракурсе выдаёт точки, по которым поза пальцев
# не восстанавливается: линия вместо ладони. Порог — по отношению ширины
# кулака (указательный MCP ↔ мизинец MCP) к размеру ладони: у ладони в камеру
# это ≈0.5, при повороте на 60° уже 0.28, на 75° — 0.17.
EDGE_ON_RATIO = 0.24


def edge_on_ratio(hand: Hand) -> float:
    """Насколько кисть «схлопнута» в линию: < EDGE_ON_RATIO — мерить нечего."""
    from .landmarks import INDEX_MCP, PINKY_MCP

    palm = float(hand.palm_size)
    if palm < 1e-6:
        return 0.0
    width = float(np.linalg.norm(hand.points[INDEX_MCP, :2] - hand.points[PINKY_MCP, :2]))
    return width / palm


def is_edge_on(hand: Hand, limit: float = EDGE_ON_RATIO) -> bool:
    """Кисть повёрнута ребром: измерениям верить нельзя, лучше предсказать."""
    return edge_on_ratio(hand) < float(limit)


@dataclass
class TrackedHand:
    """Кисть, отданная наружу: с признаком «это предсказание, а не измерение»."""

    hand: Hand
    predicted: bool = False
    missed: int = 0                 # сколько кадров подряд её не видно
    age: int = 0                    # сколько кадров трек живёт
    track_id: int = 0               # постоянный номер трека (для своего состояния)

    @property
    def note(self) -> str:
        if not self.predicted:
            return ""
        return f"рука предсказана ({self.missed})"


@dataclass
class _Track:
    points: np.ndarray                     # (21, 3) — последние известные точки
    velocity: np.ndarray                   # (21, 2) — скорость, ед./с
    handedness: str = "Right"
    score: float = 1.0
    missed: int = 0
    age: int = 0
    t: float = 0.0
    predicted: bool = False
    track_id: int = 0
    source: Optional[Hand] = None      # исходная детекция (когда она настоящая)
    extra: dict = field(default_factory=dict)


def _palm(pts: np.ndarray) -> np.ndarray:
    ids = (WRIST, 5, 9, 13, 17)
    return pts[list(ids), :2].mean(axis=0)


def _palm_size(pts: np.ndarray) -> float:
    return float(np.linalg.norm(pts[MIDDLE_MCP, :2] - pts[WRIST, :2]))


class HandTracker:
    """Непрерывный трек до двух кистей: измерение → предсказание → забывание."""

    def __init__(self, predict_frames: int = 6, match_radius: float = 1.2,
                 use_body: bool = True) -> None:
        self.predict_frames = max(int(predict_frames), 0)
        self.match_radius = float(match_radius)
        self.use_body = bool(use_body)
        self._tracks: List[_Track] = []
        self.last_notes: List[str] = []
        self.predicted_count = 0
        self._next_id = 1

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self._tracks = []
        self.last_notes = []

    @property
    def count(self) -> int:
        return len(self._tracks)

    # ------------------------------------------------------------------ #
    def update(self, hands: Sequence[Hand], now: float,
               body: Optional[np.ndarray] = None) -> List[TrackedHand]:
        """Сопоставить детекции трекам, предсказать пропавшие, забыть старые."""
        detections = list(hands or [])
        used: set = set()
        order: List[int] = []          # порядок как у движка: он же порядок вывода
        dt_default = 1.0 / 30.0

        # 1. детекции -> треки
        for hand in detections:
            pts = np.asarray(hand.points, dtype=np.float64).copy()
            palm, size = _palm(pts), max(_palm_size(pts), 1e-6)
            best, best_cost = None, self.match_radius
            for index, track in enumerate(self._tracks):
                if index in used:
                    continue
                if track.handedness and hand.handedness and track.handedness != hand.handedness:
                    continue
                cost = float(np.linalg.norm(_palm(track.points) - palm)) / size
                if cost < best_cost:
                    best, best_cost = index, cost
            dt = dt_default
            if best is None:
                self._tracks.append(_Track(points=pts, velocity=np.zeros((21, 2)),
                                           handedness=hand.handedness,
                                           score=float(getattr(hand, "score", 1.0)),
                                           t=now, track_id=self._next_id,
                                           source=hand))
                self._next_id += 1
                used.add(len(self._tracks) - 1)
                order.append(len(self._tracks) - 1)
                continue
            track = self._tracks[best]
            used.add(best)
            order.append(best)
            dt = max(now - track.t, 1e-3) if track.t else dt_default
            track.velocity = self._smooth_velocity(track, pts, dt)
            track.points = pts
            track.score = float(getattr(hand, "score", 1.0))
            track.source = hand            # та же рука, что дал движок
            track.missed = 0
            track.predicted = False
            track.age += 1
            track.t = now

        # 2. пропавшие треки: продолжаем движение и, если видно тело, тянем к нему
        alive: List[_Track] = []
        self.last_notes = []
        for index, track in enumerate(self._tracks):
            if index in used:
                alive.append(track)
                continue
            dt = max(now - track.t, 1e-3) if track.t else dt_default
            track.missed += 1
            track.age += 1
            track.t = now
            track.predicted = True
            track.source = None            # это уже не измерение
            track.score *= 0.85
            if track.missed > self.predict_frames:
                continue                       # забываем: рука ушла по-настоящему
            step = np.clip(track.velocity * dt, -MAX_POINT_SPEED, MAX_POINT_SPEED)
            track.points[:, :2] = track.points[:, :2] + step
            np.clip(track.points[:, :2], 0.0, 1.0, out=track.points[:, :2])
            if self.use_body and body is not None:
                self._anchor_to_body(track, body)
            self.last_notes.append(f"рука предсказана ({track.missed})")
            alive.append(track)

        self._tracks = alive
        self.predicted_count = sum(1 for t in alive if t.predicted)
        # Сначала измеренные руки в том порядке, в каком их отдал движок (по нему
        # выбирается главная рука и работают жесты двумя руками), потом
        # предсказанные: выдуманная рука не должна «перехватывать» управление.
        result = []
        predicted_order = [i for i in range(len(self._tracks)) if i not in set(order)]
        for i in order + predicted_order:
            track = self._tracks[i]
            hand = (track.source if track.source is not None
                    else Hand(track.points, track.handedness, track.score))
            result.append(TrackedHand(hand, predicted=track.predicted, missed=track.missed,
                                      age=track.age, track_id=track.track_id))
        self.result_order = order
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _smooth_velocity(track: _Track, pts: np.ndarray, dt: float) -> np.ndarray:
        delta = (pts[:, :2] - track.points[:, :2]) / dt
        # ограничение правдоподобной скоростью: глитч на один кадр не должен
        # улетать в предсказание на все следующие
        limit = MAX_SPEED_PALM * max(_palm_size(pts), 1e-6)
        delta = np.clip(delta, -limit, limit)
        return 0.6 * track.velocity + 0.4 * delta

    @staticmethod
    def _anchor_to_body(track: _Track, body: np.ndarray) -> None:
        """Подтянуть предсказанную кисть к запястью и предплечью из тела."""
        if body is None or len(body) < 17:
            return
        # BlazePose: 13/14 — локти, 15/16 — запястья. Какое из них «наше»,
        # решаем по расстоянию, а не по подписи стороны: у MediaPipe подпись
        # зависит от того, зеркалится ли кадр, и ей нельзя верить на слово.
        candidates = []
        for wrist_id, elbow_id in ((15, 13), (16, 14)):
            visible = float(body[wrist_id, 3]) if body.shape[1] > 3 else 1.0
            if visible < 0.5:
                continue
            wrist = np.asarray(body[wrist_id, :2], dtype=np.float64)
            candidates.append((float(np.linalg.norm(wrist - track.points[WRIST, :2])),
                               wrist, elbow_id))
        if not candidates:
            return
        _dist, wrist, elbow_id = min(candidates, key=lambda item: item[0])
        shift = wrist - track.points[WRIST, :2]
        if float(np.linalg.norm(shift)) > 0.25:      # тело «врёт» — не тянем
            return
        track.points[:, :2] = track.points[:, :2] + 0.5 * shift

        # разворот вдоль предплечья: ладонь смотрит от локтя к запястью
        elbow = np.asarray(body[elbow_id, :2], dtype=np.float64)
        if float(body[elbow_id, 3]) < 0.5:
            return
        forearm = wrist - elbow
        norm = float(np.linalg.norm(forearm))
        if norm < 1e-6:
            return
        forearm = forearm / norm
        palm_dir = track.points[MIDDLE_MCP, :2] - track.points[WRIST, :2]
        pnorm = float(np.linalg.norm(palm_dir))
        if pnorm < 1e-6:
            return
        palm_dir = palm_dir / pnorm
        angle = float(np.arctan2(forearm[1], forearm[0]) - np.arctan2(palm_dir[1], palm_dir[0]))
        angle = (angle + np.pi) % (2 * np.pi) - np.pi
        turn = 0.25 * np.clip(angle, -0.6, 0.6)      # не больше ~35° за кадр
        if abs(turn) < 1e-3:
            return
        c, s = np.cos(turn), np.sin(turn)
        pivot = track.points[WRIST, :2]
        rel = track.points[:, :2] - pivot
        track.points[:, 0] = pivot[0] + rel[:, 0] * c - rel[:, 1] * s
        track.points[:, 1] = pivot[1] + rel[:, 0] * s + rel[:, 1] * c
