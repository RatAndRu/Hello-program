"""Трекер кисти: рука не пропадает, не путается и не врёт про позу ребром."""

import numpy as np
import pytest

from airmouse.gestures import synthetic_hand
from airmouse.handtrack import HandTracker, edge_on_ratio, is_edge_on
from airmouse.landmarks import FINGERS, WRIST

OPEN = {name: 0.0 for name in FINGERS}


def _hand(x: float = 0.4, y: float = 0.6, **kw):
    return synthetic_hand(center=(x, y), scale=0.22, curl=OPEN, **kw)


# --------------------------------------------------------------------------- #
#  Предсказание: рука продолжает движение, когда её не видно
# --------------------------------------------------------------------------- #
def test_prediction_continues_the_motion():
    tracker = HandTracker(predict_frames=4)
    tracker.update([_hand(0.40)], 0.0)
    tracker.update([_hand(0.45)], 1 / 30)
    out = tracker.update([], 2 / 30)
    assert out and out[0].predicted and out[0].missed == 1
    # точка продолжила путь: 0.45 -> дальше вправо
    assert float(out[0].hand.palm_center[0]) > 0.45


def test_hand_is_forgotten_after_the_prediction_window():
    tracker = HandTracker(predict_frames=3)
    tracker.update([_hand()], 0.0)
    for i in range(1, 4):
        out = tracker.update([], i / 30)
        assert out, "в пределах окна рука ещё ведётся"
    for i in range(4, 9):
        out = tracker.update([], i / 30)
    assert out == [], "после окна предсказания рука честно пропадает"


def test_real_detection_beats_prediction_in_order():
    tracker = HandTracker(predict_frames=6)
    tracker.update([_hand(0.3), _hand(0.7)], 0.0)
    tracker.update([_hand(0.3), _hand(0.7)], 1 / 30)
    out = tracker.update([_hand(0.7)], 2 / 30)      # левая рука пропала
    assert out[0].predicted is False, "настоящая рука идёт первой"
    assert any(item.predicted for item in out)


# --------------------------------------------------------------------------- #
#  Сопоставление: две руки не меняются местами
# --------------------------------------------------------------------------- #
def test_tracks_are_matched_by_position_not_by_order():
    tracker = HandTracker(predict_frames=6)
    a = _hand(0.25)
    b = _hand(0.75)
    tracker.update([a, b], 0.0)
    first = tracker.update([b, a], 1 / 30)          # движок вернул в другом порядке
    assert first[0].hand is b and first[1].hand is a
    ids = {item.track_id for item in first}
    assert len(ids) == 2


def test_a_track_keeps_its_identity_between_frames():
    tracker = HandTracker(predict_frames=6)
    tracker.update([_hand(0.4)], 0.0)
    one = tracker.update([_hand(0.42)], 1 / 30)[0]
    two = tracker.update([_hand(0.44)], 2 / 30)[0]
    assert one.track_id == two.track_id


# --------------------------------------------------------------------------- #
#  «Ребром»: поза не измеряется
# --------------------------------------------------------------------------- #
def test_flat_open_hand_is_not_edge_on():
    assert not is_edge_on(_hand())
    assert edge_on_ratio(_hand()) > 0.4


def test_hand_turned_edge_on_is_recognised():
    for yaw in (75, 85):
        hand = _hand(yaw_deg=yaw)
        assert is_edge_on(hand), f"поворот {yaw}° должен считаться «ребром»"
        assert edge_on_ratio(hand) < 0.24


# --------------------------------------------------------------------------- #
#  Тело подсказывает, где должна быть кисть
# --------------------------------------------------------------------------- #
def _body(wrist_x: float, wrist_y: float, vis: float = 0.9) -> np.ndarray:
    body = np.zeros((33, 4), dtype=np.float32)
    body[:, 3] = 0.0
    # правая рука: плечо 12, локоть 14, запястье 16
    body[12] = (wrist_x - 0.20, wrist_y + 0.05, 0.0, vis)
    body[14] = (wrist_x - 0.10, wrist_y + 0.02, 0.0, vis)
    body[16] = (wrist_x, wrist_y, 0.0, vis)
    body[11] = (wrist_x - 0.30, wrist_y + 0.08, 0.0, 0.0)
    body[13] = (wrist_x - 0.25, wrist_y + 0.10, 0.0, 0.0)
    body[15] = (wrist_x - 0.35, wrist_y + 0.10, 0.0, 0.0)
    return body


def test_predicted_wrist_is_pulled_to_the_body_wrist():
    tracker = HandTracker(predict_frames=6, use_body=True)
    tracker.update([_hand(0.40, 0.60)], 0.0)
    before = float(tracker.update([], 1 / 30)[0].hand.points[WRIST, 0])
    tracker2 = HandTracker(predict_frames=6, use_body=True)
    tracker2.update([_hand(0.40, 0.60)], 0.0)
    after = float(tracker2.update([], 1 / 30, body=_body(0.60, 0.60))[0].hand.points[WRIST, 0])
    assert after > before, "кисть подтянулась к запястью из тела"


def test_body_far_away_does_not_drag_the_hand():
    tracker = HandTracker(predict_frames=6, use_body=True)
    tracker.update([_hand(0.25, 0.60)], 0.0)
    out = tracker.update([], 1 / 30, body=_body(0.95, 0.10))
    assert abs(float(out[0].hand.points[WRIST, 0]) - 0.25) < 0.2
