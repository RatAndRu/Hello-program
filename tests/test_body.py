"""Тело целиком: приседания, наклон, руки вверх — по 33 точкам Pose.

Камера одна, глубины нет, человек в кадре один. Поэтому глубина приседа
считается по двум сигналам (угол в колене сбоку и просадка таза спереди), а
счёт повторов — с гистерезисом и минимальной длительностью: дребезг точек не
должен превращаться в «сделал 40 приседаний».
"""

import numpy as np
import pytest

from airmouse.body import (
    B,
    BodyFSM,
    POSTURE_TITLES,
    measure_body,
    synthetic_body,
)
from airmouse.config import BodyConfig

CFG = BodyConfig()


def _frames(start: float = 0.0, fps: float = 30.0, **kwargs):
    """Сколько угодно кадров одной позы — с нормальным шагом времени."""
    dt = 1.0 / fps
    t = start
    while True:
        yield synthetic_body(**kwargs), t
        t += dt


def _play(fsm: BodyFSM, poses, fps: float = 30.0, start: float = 0.0):
    events = []
    t = start
    for pose in poses:
        events.extend(fsm.update(measure_body(synthetic_body(**pose)), t))
        t += 1.0 / fps
    return events, t


# --------------------------------------------------------------------------- #
#  Мерки
# --------------------------------------------------------------------------- #
def test_standing_body_is_measured():
    m = measure_body(synthetic_body())
    assert m.visible
    assert m.knee == pytest.approx(180.0, abs=6.0)
    assert m.depth < 0.1
    assert m.lean < 5.0
    assert m.arms_up < 0.2
    assert m.posture == "stand"


def test_squat_depth_grows_with_squat():
    depths = [measure_body(synthetic_body(squat=s)).depth for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert depths == sorted(depths)
    assert depths[0] < 0.1
    assert depths[-1] > 0.6


def test_lean_is_not_a_squat():
    """Наклон корпуса не должен выглядеть приседом — иначе счёт сбивается."""
    m = measure_body(synthetic_body(lean=40))
    assert m.lean == pytest.approx(40.0, abs=3.0)
    assert m.depth < 0.1
    assert m.posture == "lean"


def test_arms_up_detected():
    assert measure_body(synthetic_body(arms_up=1.0)).arms_up > 0.6
    assert measure_body(synthetic_body(arms_up=0.0)).arms_up < 0.2


def test_body_out_of_frame_is_not_measured():
    body = synthetic_body(visibility=0.1)
    assert measure_body(body).visible is False
    partial = synthetic_body()
    partial[B.L_KNEE, 3] = 0.0          # колено перекрыто столом
    assert measure_body(partial).visible is False
    assert measure_body(np.zeros((10, 4))).visible is False


# --------------------------------------------------------------------------- #
#  Счёт приседаний
# --------------------------------------------------------------------------- #
def test_squat_reps_are_counted():
    fsm = BodyFSM(CFG)
    poses = ([{"squat": 0.0}] * 20 + [{"squat": 0.9}] * 20 + [{"squat": 0.0}] * 20) * 3
    events, _ = _play(fsm, poses)
    reps = [e for e in events if e.kind == "squat_rep"]
    assert len(reps) == 3
    assert [e.value for e in reps] == [1, 2, 3]
    assert fsm.reps == 3


def test_partial_squat_is_not_counted():
    fsm = BodyFSM(CFG)
    poses = ([{"squat": 0.0}] * 15 + [{"squat": 0.35}] * 15) * 4
    events, _ = _play(fsm, poses)
    assert not [e for e in events if e.kind == "squat_rep"]


def test_jitter_near_threshold_does_not_double_count():
    """Дрожание точек у порога — не повод считать второй повтор."""
    fsm = BodyFSM(CFG)
    poses = [{"squat": 0.0}] * 20 + [{"squat": 0.9}] * 20 + [{"squat": 0.0}] * 6
    poses += ([{"squat": 0.47}, {"squat": 0.44}] * 6)     # болтается у порога
    poses += [{"squat": 0.0}] * 20
    events, _ = _play(fsm, poses)
    assert len([e for e in events if e.kind == "squat_rep"]) == 1


def test_too_fast_dip_is_not_a_rep():
    fsm = BodyFSM(CFG)
    # провалился и сразу встал — это промах детекции, а не присед
    poses = [{"squat": 0.0}] * 20 + [{"squat": 0.9}] * 2 + [{"squat": 0.0}] * 20
    events, _ = _play(fsm, poses, fps=30.0)
    assert not [e for e in events if e.kind == "squat_rep"]


def test_body_lost_does_not_break_counter():
    fsm = BodyFSM(CFG)
    _play(fsm, [{"squat": 0.0}] * 10 + [{"squat": 0.9}] * 10)
    assert fsm.update(None, 1.0) == []
    assert fsm.text == ""
    events, _ = _play(fsm, [{"squat": 0.0}] * 20, start=1.1)
    assert fsm.reps == 0               # честно: повтор не подтверждён
    assert not events


# --------------------------------------------------------------------------- #
#  Постур и руки
# --------------------------------------------------------------------------- #
def test_posture_text_is_human_readable():
    fsm = BodyFSM(CFG)
    _play(fsm, [{"squat": 0.9}] * 20)
    assert fsm.posture == "squat"
    assert "приседает" in fsm.text
    assert "присед" in POSTURE_TITLES["squat"]


def test_arms_up_hold_fires_once():
    fsm = BodyFSM(CFG)
    events, _ = _play(fsm, [{"arms_up": 0.0}] * 5 + [{"arms_up": 1.0}] * 60)
    fired = [e for e in events if e.kind == "arms_up_hold"]
    assert len(fired) == 1
    assert fsm.posture == "arms_up"


# --------------------------------------------------------------------------- #
#  Синтетика
# --------------------------------------------------------------------------- #
def test_synthetic_body_has_33_points():
    body = synthetic_body()
    assert body.shape == (33, 4)
    assert np.all(body[:, 3] == 1.0)
    assert 0.0 <= body[:, :2].min() and body[:, :2].max() <= 1.0
