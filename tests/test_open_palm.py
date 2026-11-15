"""Открытая ладонь: только плоская вытянутая рука, развёрнутая в камеру.

Раньше «ладонью» считалась любая кисть с четырьмя выпрямленными пальцами:
рука под углом, кисть ребром, мятая ладонь с поджатыми пальцами и даже тыл
кисти. Из-за этого пауза срабатывала случайно. Теперь жест проверяет геометрию:

* ``flatness`` — вылет точек кисти из плоскости (мятая ладонь отсекается);
* ``facing`` — косинус угла между ладонью и камерой (ребро и «наискосок»
  отсекаются);
* сторона кисти — тыл не считается ладонью (нужна калибровка ``K``, без неё
  сторона просто неизвестна и жест работает как раньше).
"""

import numpy as np
import pytest

from airmouse.config import HandConfig
from airmouse.gestures import (
    HandFSM,
    HandSide,
    Pose,
    analyze_hand,
    classify_pose,
    hand_plane,
    palm_hint,
    synthetic_hand,
)

CFG = HandConfig()


def _classify(**kwargs) -> Pose:
    hand = synthetic_hand(**kwargs)
    return classify_pose(analyze_hand(hand), CFG)


# --------------------------------------------------------------------------- #
#  Геометрия
# --------------------------------------------------------------------------- #
def test_flat_palm_has_no_depth_spread():
    normal, flatness, facing = hand_plane(synthetic_hand())
    assert flatness < 1e-6
    assert facing == pytest.approx(1.0)
    assert normal[2] > 0.9          # ладонью в камеру


def test_tilted_hand_reduces_facing():
    for yaw, want in ((30.0, 0.87), (45.0, 0.71), (60.0, 0.50)):
        _n, _flat, facing = hand_plane(synthetic_hand(yaw_deg=yaw))
        assert facing == pytest.approx(want, abs=0.02)
        assert facing < 1.0


def test_back_of_hand_flips_normal():
    palm = hand_plane(synthetic_hand())[0]
    back = hand_plane(synthetic_hand(back=True))[0]
    assert palm[2] > 0.9 and back[2] < -0.9


def test_curled_fingers_are_not_flat():
    flat = analyze_hand(synthetic_hand()).flatness
    curled = analyze_hand(synthetic_hand(curl={"index": 0.5, "middle": 0.5,
                                               "ring": 0.5, "pinky": 0.5})).flatness
    assert flat < 1e-6
    assert curled > CFG.palm_flat_max


# --------------------------------------------------------------------------- #
#  Классификация
# --------------------------------------------------------------------------- #
def test_flat_palm_facing_camera_is_open_palm():
    for yaw in (0.0, 15.0, 30.0):
        assert _classify(yaw_deg=yaw) == Pose.OPEN_PALM, yaw


def test_hand_at_angle_is_not_open_palm():
    """Рука «наискосок» — не жест ладони (раньше срабатывала как пауза)."""
    for yaw in (45.0, 60.0, 75.0, -50.0):
        assert _classify(yaw_deg=yaw) == Pose.NONE, yaw
    for pitch in (45.0, 60.0, -55.0):
        assert _classify(pitch_deg=pitch) == Pose.NONE, pitch


def test_crumpled_palm_is_not_open_palm():
    assert _classify(curl={"index": 0.45, "middle": 0.45,
                           "ring": 0.45, "pinky": 0.45}) == Pose.NONE


def test_fist_and_point_still_work():
    curled = {"thumb": 1.0, "index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0}
    assert _classify(curl=curled) == Pose.FIST
    assert _classify(curl={"middle": 1.0, "ring": 1.0, "pinky": 1.0}) == Pose.POINT


def test_hint_explains_why():
    hand = synthetic_hand(yaw_deg=60)
    f = analyze_hand(hand)
    text = palm_hint(f, CFG)
    assert "углом" in text and "60" in text
    curled = analyze_hand(synthetic_hand(curl={"index": 0.5, "middle": 0.5,
                                               "ring": 0.5, "pinky": 0.5}))
    assert "поджаты" in palm_hint(curled, CFG)
    assert "тыл" in palm_hint(f, CFG, side_back=True)
    assert palm_hint(analyze_hand(synthetic_hand()), CFG) == ""


# --------------------------------------------------------------------------- #
#  Автомат: пауза по ладони
# --------------------------------------------------------------------------- #
def _feed(fsm: HandFSM, hand, frames: int = 12, dt: float = 0.05, start: float = 0.0):
    events = []
    now = start
    for _ in range(frames):
        now += dt
        events.extend(fsm.update(hand, now))
    return events, now


def test_flat_palm_holds_to_pause():
    fsm = HandFSM(CFG)
    events, _ = _feed(fsm, synthetic_hand(), frames=40, dt=0.05)
    assert any(e.kind == "open_palm_hold" for e in events)


def test_tilted_palm_never_pauses():
    fsm = HandFSM(CFG)
    events, now = _feed(fsm, synthetic_hand(yaw_deg=55), frames=60, dt=0.05)
    assert not any(e.kind == "open_palm_hold" for e in events)
    # и человеку объяснили, почему
    assert "углом" in fsm.palm_reject


def test_back_of_hand_never_pauses():
    fsm = HandFSM(CFG)
    fsm.side_est.side = HandSide.BACK   # как после калибровки стороны клавишей K
    events, _ = _feed(fsm, synthetic_hand(back=True), frames=60, dt=0.05)
    assert not any(e.kind == "open_palm_hold" for e in events)
    assert "тыл" in fsm.palm_reject


def test_palm_side_can_be_ignored_by_config():
    """Кому пауза тылом нужна — оставляет её одной настройкой."""
    cfg = HandConfig()
    cfg.palm_need_side = False
    fsm = HandFSM(cfg)
    fsm.side_est.side = HandSide.BACK
    events, _ = _feed(fsm, synthetic_hand(back=True), frames=60, dt=0.05)
    assert any(e.kind == "open_palm_hold" for e in events)


def test_two_hand_relax_is_more_forgiving():
    """В двуручных режимах ладонь ловится мягче — там важнее поймать жест."""
    hand_at_47 = synthetic_hand(yaw_deg=47)
    strict = classify_pose(analyze_hand(hand_at_47), CFG, relax=0.0)
    relaxed = classify_pose(analyze_hand(hand_at_47), CFG, relax=1.0)
    assert strict == Pose.NONE
    assert relaxed == Pose.OPEN_PALM
