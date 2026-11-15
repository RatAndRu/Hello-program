"""Прицел при щипке, управление двумя руками, кивок и «грусть»."""

import numpy as np

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, FaceConfig, HandConfig
from airmouse.face import FaceFSM, FaceMetrics, measure_face
from airmouse.gestures import HandFSM, TwoHandFSM, synthetic_hand
from airmouse.synthetic import synthetic_face


# ---------------------------------------------------------------- прицел
def test_pinch_freezes_pointer_before_fingers_touch():
    """Пока пальцы сходятся, курсор не двигается — иначе клик уезжает."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    open_hand = synthetic_hand()
    fsm.update(open_hand, 0.0)
    assert fsm.approaching is False

    pinching = synthetic_hand(pinch_index=True)
    events = fsm.update(pinching, 0.1)
    assert fsm.approaching is True
    assert fsm.aim_point is not None
    assert all(e.kind != "pointer" for e in events)  # курсор заморожен


# ------------------------------------------------------------ две руки
def test_two_hand_zoom_uses_distance_between_palms():
    cfg = HandConfig()
    cfg.two_hand = "zoom"
    fsm = TwoHandFSM(cfg)
    left = synthetic_hand(center=(0.35, 0.6), scale=0.2)
    right = synthetic_hand(center=(0.65, 0.6), scale=0.2)
    assert fsm.update([left, right], 0.0) == []          # запомнили расстояние
    assert fsm.active
    right_far = synthetic_hand(center=(0.80, 0.6), scale=0.2)
    events = fsm.update([left, right_far], 0.1)          # развели руки
    assert events and events[0].kind == "zoom" and events[0].value > 0


def test_two_hand_scroll_with_both_fists():
    cfg = HandConfig()
    cfg.two_hand = "scroll"
    fsm = TwoHandFSM(cfg)
    # настоящий кулак — все пальцы сжаты, включая большой
    fist = {"thumb": 1, "index": 1, "middle": 1, "ring": 1, "pinky": 1}
    top = [synthetic_hand(center=(0.35, 0.5), curl=fist),
           synthetic_hand(center=(0.65, 0.5), curl=fist)]
    lower = [synthetic_hand(center=(0.35, 0.62), curl=fist),
             synthetic_hand(center=(0.65, 0.62), curl=fist)]
    assert fsm.update(top, 0.0) == []
    events = fsm.update(lower, 0.1)
    assert events and events[0].kind == "scroll"


def test_two_hand_off_by_default_config_switch():
    cfg = HandConfig()
    cfg.two_hand = "off"
    fsm = TwoHandFSM(cfg)
    hands = [synthetic_hand(center=(0.35, 0.6)), synthetic_hand(center=(0.65, 0.6))]
    assert fsm.update(hands, 0.0) == []


# ------------------------------------------------------- голова и лицо
def test_head_shake_detected():
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    t = 0.0
    for _ in range(15):  # калибровка нейтрали
        fsm.update(measure_face(synthetic_face()), t)
        t += 1 / 25.0
    events = []
    for yaw in (10, -10, 10, -10):
        for _ in range(5):
            events.extend(fsm.update(measure_face(synthetic_face(yaw=yaw)), t))
            t += 1 / 25.0
    assert any(e.kind == "head_shake" for e in events)


def test_sad_expression_reported():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app.face_fsm.baseline.corner = 0.06            # нейтраль: уголки выше
    app.face_fsm.sad_score = 0.05                  # сейчас уголки опущены
    app._metrics = FaceMetrics(valid=True, ear_left=0.3, ear_right=0.3,
                               corner_lift=0.01, mouth_open=0.1)
    assert app._expression_text() == "грусть"


def test_surprise_expression_reported():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app.face_fsm.brow_score = 0.09
    app._metrics = FaceMetrics(valid=True, ear_left=0.3, ear_right=0.3,
                               mouth_open=0.5)
    assert app._expression_text() == "удивление"
