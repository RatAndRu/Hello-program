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
# Скорость предсказания гаснет на столько за каждый пропущенный кадр.
PREDICT_DAMPING = 0.75


# «Ребром»: рука повёрнута к камере так, что кисть схлопывается в линию
# («полка»). Нейросеть в этом ракурсе выдаёт точки, по которым поза пальцев
# не восстанавливается: линия вместо ладони. Порог — по отношению ширины
# кулака (указательный MCP ↔ мизинец MCP) к размеру ладони: у ладони в камеру
# это ≈0.5, при повороте на 60° уже 0.28, на 75° — 0.17.
EDGE_ON_RATIO = 0.24

# Штраф к расстоянию (в размерах ладони) за несовпадение подписи «левая/правая».
# Подпись у MediaPipe ненадёжна (зависит от зеркала и ракурса), поэтому это
# именно штраф, а не запрет: близкая кисть с «не той» подписью — всё та же рука.
HANDEDNESS_PENALTY = 0.6
# Предсказанная рука ближе этого (в размерах ладони) к настоящей — это она и
# есть, второй ладони на экране не рисуем.
GHOST_RADIUS = 1.5


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

    def __init__(self, predict_frames: int = 6, match_radius: float = 1.6,
                 use_body: bool = True, max_tracks: int = 2) -> None:
        self.predict_frames = max(int(predict_frames), 0)
        self.match_radius = float(match_radius)
        self.use_body = bool(use_body)
        self.max_tracks = max(int(max_tracks), 1)
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

        # 1. детекции -> треки. Сопоставляем **глобально** по близости ладони:
        # сначала самые близкие пары. Подпись «левая/правая» — только штраф, а
        # не запрет: MediaPipe меняет её у одной и той же кисти от кадра к
        # кадру, и раньше каждая такая смена рождала новый трек, а старый ещё
        # шесть кадров ехал рядом «предсказанием» — на экране появлялась вторая
        # ладонь поверх настоящей.
        pairs = []
        det_pts = []
        for d_index, hand in enumerate(detections):
            pts = np.asarray(hand.points, dtype=np.float64).copy()
            det_pts.append(pts)
            palm, size = _palm(pts), max(_palm_size(pts), 1e-6)
            for t_index, track in enumerate(self._tracks):
                cost = float(np.linalg.norm(_palm(track.points) - palm)) / size
                if track.handedness and hand.handedness and track.handedness != hand.handedness:
                    cost += HANDEDNESS_PENALTY
                # потерянный трек мог уехать дальше: ему радиус шире
                radius = self.match_radius * (1.0 + 0.5 * min(track.missed, 4))
                if cost < radius:
                    pairs.append((cost, d_index, t_index))
        pairs.sort()
        matched_det: dict = {}
        adopted: set = set()           # детекции, «усыновившие» далёкий трек
        for cost, d_index, t_index in pairs:
            if d_index in matched_det or t_index in used:
                continue
            matched_det[d_index] = t_index
            used.add(t_index)

        # Детекция без пары, а трек без пары остался: кисть просто прыгнула
        # дальше радиуса (резкий взмах) — это та же рука, а не новая. Иначе
        # старый трек ещё полдесятка кадров ехал бы рядом второй ладонью.
        for d_index in range(len(detections)):
            if d_index in matched_det:
                continue
            orphans = [i for i in range(len(self._tracks)) if i not in used]
            if not orphans:
                continue
            palm = _palm(det_pts[d_index])
            best = min(orphans, key=lambda i: float(np.linalg.norm(_palm(self._tracks[i].points) - palm)))
            matched_det[d_index] = best
            used.add(best)
            adopted.add(d_index)

        for d_index, hand in enumerate(detections):
            pts = det_pts[d_index]
            if d_index not in matched_det:
                self._tracks.append(_Track(points=pts, velocity=np.zeros((21, 2)),
                                           handedness=hand.handedness,
                                           score=float(getattr(hand, "score", 1.0)),
                                           t=now, track_id=self._next_id,
                                           source=hand))
                self._next_id += 1
                used.add(len(self._tracks) - 1)
                order.append(len(self._tracks) - 1)
                continue
            best = matched_det[d_index]
            track = self._tracks[best]
            order.append(best)
            dt = max(now - track.t, 1e-3) if track.t else dt_default
            track.velocity = self._smooth_velocity(track, pts, dt)
            if d_index in adopted:
                track.velocity = np.zeros((21, 2))   # после прыжка скорость не знаем
            track.points = pts
            track.handedness = hand.handedness or track.handedness
            track.score = float(getattr(hand, "score", 1.0))
            track.source = hand            # та же рука, что дал движок
            track.missed = 0
            track.predicted = False
            track.age += 1
            track.t = now

        # 2. пропавшие треки: продолжаем движение и, если видно тело, тянем к нему
        ordered = [self._tracks[i] for i in order]   # измеренные, в порядке движка
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
            # Рядом с предсказанием есть **настоящая** рука — значит, это она
            # и есть (детектор сдвинул её дальше, чем мы ждали, или сменил
            # подпись). Второй, выдуманной, ладони на экране быть не должно.
            if self._near_measured(track, used):
                continue
            # Жёсткий сдвиг: вся кисть едет со скоростью ладони, и эта
            # скорость гаснет с каждым кадром. Раньше каждая из 21 точки
            # летела своей скоростью — пальцы разъезжались в кашу.
            palm_ids = (WRIST, 5, 9, 13, 17)
            palm_v = track.velocity[list(palm_ids)].mean(axis=0) * (PREDICT_DAMPING ** track.missed)
            step = np.clip(palm_v * dt, -MAX_POINT_SPEED, MAX_POINT_SPEED)
            track.points[:, :2] = track.points[:, :2] + step
            np.clip(track.points[:, :2], 0.0, 1.0, out=track.points[:, :2])
            if self.use_body and body is not None:
                self._anchor_to_body(track, body)
            self.last_notes.append(f"рука предсказана ({track.missed})")
            alive.append(track)

        # Предсказанных рук не больше, чем «не хватает» до двух: если видны обе
        # настоящие — выдуманных нет вовсе; если одна — не больше одной.
        measured_n = len(order)
        keep: List[_Track] = [t for t in alive if not t.predicted]
        ghosts = sorted((t for t in alive if t.predicted), key=lambda t: t.missed)
        keep.extend(ghosts[:max(0, self.max_tracks - measured_n)])
        kept_ids = {id(t) for t in keep}
        alive = [t for t in alive if id(t) in kept_ids]
        self.last_notes = [f"рука предсказана ({t.missed})" for t in alive if t.predicted]
        self._tracks = alive
        self.predicted_count = sum(1 for t in alive if t.predicted)
        # Сначала измеренные руки в том порядке, в каком их отдал движок (по нему
        # выбирается главная рука и работают жесты двумя руками), потом
        # предсказанные: выдуманная рука не должна «перехватывать» управление.
        result = []
        predicted_tracks = [t for t in alive if t.predicted]
        for track in ordered + predicted_tracks:
            hand = (track.source if track.source is not None
                    else Hand(track.points, track.handedness, track.score))
            result.append(TrackedHand(hand, predicted=track.predicted, missed=track.missed,
                                      age=track.age, track_id=track.track_id))
        self.result_order = order
        return result

    # ------------------------------------------------------------------ #
    def _near_measured(self, track: _Track, used: set) -> bool:
        """Есть ли рядом с предсказанным треком настоящая (измеренная) рука."""
        palm = _palm(track.points)
        size = max(_palm_size(track.points), 1e-6)
        for index in used:
            other = self._tracks[index]
            if other.predicted:
                continue
            dist = float(np.linalg.norm(_palm(other.points) - palm)) / size
            if dist < GHOST_RADIUS:
                return True
        return False

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
