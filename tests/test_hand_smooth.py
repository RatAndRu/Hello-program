"""Сглаживание кисти: ладонь жёстко, пальцы в её системе, предсказание без каши."""

import math

import numpy as np

from airmouse.gestures import synthetic_hand
from airmouse.handsmooth import HandSmoother, from_local, to_local
from airmouse.landmarks import FINGERS, INDEX_TIP, MIDDLE_MCP, WRIST

OPEN = {name: 0.0 for name in FINGERS}
DT = 1 / 30


def _finger_lengths(pts: np.ndarray) -> np.ndarray:
    out = []
    for mcp, pip, dip, tip in FINGERS.values():
        for a, b in ((mcp, pip), (pip, dip), (dip, tip)):
            out.append(float(np.linalg.norm(pts[a, :2] - pts[b, :2])))
    return np.asarray(out)


def test_local_frame_round_trips():
    hand = synthetic_hand(center=(0.4, 0.6), rotation_deg=25.0, curl={"index": 0.4})
    pts = hand.points.astype(np.float64)
    local = to_local(pts)
    wrist = pts[WRIST, :2]
    axis = pts[MIDDLE_MCP, :2] - wrist
    back = from_local(local, wrist, math.atan2(axis[1], axis[0]), float(np.linalg.norm(axis)))
    assert np.allclose(back[:, :2], pts[:, :2], atol=1e-6)


def test_local_coordinates_do_not_change_when_hand_moves_rigidly():
    a = synthetic_hand(center=(0.3, 0.5), curl=OPEN)
    b = synthetic_hand(center=(0.7, 0.4), scale=0.3, curl=OPEN)
    assert np.allclose(to_local(a.points)[:, :2], to_local(b.points)[:, :2], atol=1e-5)
    # честный поворот всей кисти вокруг запястья — тоже те же локальные координаты
    pts = a.points.astype(np.float64).copy()
    c, s = math.cos(0.7), math.sin(0.7)
    rel = pts[:, :2] - pts[WRIST, :2]
    pts[:, :2] = pts[WRIST, :2] + np.stack([rel[:, 0] * c - rel[:, 1] * s,
                                            rel[:, 0] * s + rel[:, 1] * c], axis=1)
    assert np.allclose(to_local(a.points)[:, :2], to_local(pts)[:, :2], atol=1e-5)


def test_jitter_is_damped_but_shape_is_kept():
    rng = np.random.default_rng(1)
    sm = HandSmoother()
    base = synthetic_hand(center=(0.5, 0.55), curl=OPEN)
    outs = []
    for i in range(40):
        noisy = base.points.astype(np.float64).copy()
        noisy[:, :2] += rng.normal(0, 0.004, size=(21, 2))
        outs.append(sm.update(type(base)(noisy.astype(np.float32)), i * DT).points)
    tail = np.asarray(outs[20:])
    raw_jitter = 0.004
    smooth_jitter = float(tail[:, INDEX_TIP, :2].std(axis=0).mean())
    assert smooth_jitter < raw_jitter * 0.5
    # длины фаланг — как у настоящей руки (кисть не «расползлась»)
    assert np.allclose(_finger_lengths(outs[-1]), _finger_lengths(base.points), atol=0.006)


def test_fast_hand_motion_passes_without_lag():
    sm = HandSmoother()
    xs = []
    for i in range(20):
        hand = synthetic_hand(center=(0.2 + 0.03 * i, 0.55), curl=OPEN)
        xs.append(float(sm.update(hand, i * DT).points[WRIST, 0]))
    # на 20-м кадре запястье реально в 0.77; сглаженное отстаёт меньше чем на кадр
    assert abs(xs[-1] - (0.2 + 0.03 * 19)) < 0.03


def test_finger_bend_passes_quickly():
    sm = HandSmoother()
    for i in range(10):
        sm.update(synthetic_hand(curl=OPEN), i * DT)
    bent = synthetic_hand(curl=dict(OPEN, index=1.0))
    out = None
    for j in range(4):
        out = sm.update(bent, (10 + j) * DT)
    target = bent.points[INDEX_TIP, :2]
    assert float(np.linalg.norm(out.points[INDEX_TIP, :2] - target)) < 0.02


def test_prediction_is_rigid_and_slows_down():
    sm = HandSmoother()
    for i in range(12):
        sm.update(synthetic_hand(center=(0.3 + 0.01 * i, 0.55), curl=OPEN), i * DT)
    last = sm.points
    steps = []
    for j in range(6):
        pred = sm.predict((12 + j) * DT)
        assert pred is not None
        pts = pred.points.astype(np.float64)
        # форма пальцев заморожена: локальные координаты те же
        assert np.allclose(to_local(pts)[:, :2], to_local(last)[:, :2], atol=1e-4)
        steps.append(float(pts[WRIST, 0] - last[WRIST, 0]))
        last = pts
    assert steps[0] > 0                     # едет дальше вправо
    assert steps[-1] < steps[0] * 0.5       # и замедляется
