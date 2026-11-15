"""Физика пальцев: пределы сгиба, связка PIP–DIP и «прыжки» точек.

Проверяем ровно то, что видит человек: настоящая рука не правится, а
невозможная поза — исправляется и помечается.
"""

import numpy as np
import pytest

from airmouse.gestures import synthetic_hand
from airmouse.handphysics import (
    DIP_TO_PIP,
    LIMITS,
    HandPhysics,
    coupling_error,
    finger_pose,
    harmonize,
    poses,
    rebuild_finger,
    FingerPose,
)
from airmouse.landmarks import FINGERS


def _hand(curl: float = 0.0):
    return synthetic_hand(curl={name: curl for name in FINGERS})


# --------------------------------------------------------------------------- #
#  Пределы взяты по литературе и не мешают живой руке
# --------------------------------------------------------------------------- #
def test_limits_are_anatomically_ordered():
    for name in FINGERS:
        mcp, pip, dip = LIMITS[name]
        assert 0 < mcp < 120 and 0 < pip < 130 and 0 < dip < 100
    # у четырёх пальцев PIP гнётся сильнее DIP (у большого своя анатомия)
    for name in ("index", "middle", "ring", "pinky"):
        _mcp, pip, dip = LIMITS[name]
        assert pip > dip


@pytest.mark.parametrize("curl", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_natural_hand_is_never_corrected(curl):
    out = HandPhysics().update(_hand(curl), 0.0)
    assert out.suspect == () and out.rebuilt == 0 and out.held == 0
    assert out.hand is not None


def test_open_palm_stays_open():
    out = HandPhysics().update(_hand(0.0), 0.0)
    for name in ("index", "middle", "ring", "pinky"):
        assert abs(out.poses[name].pip) < 5.0


# --------------------------------------------------------------------------- #
#  Невозможная поза: PIP прямой, а кончик загнут
# --------------------------------------------------------------------------- #
def test_impossible_dip_is_flagged_and_fixed():
    hand = _hand(0.0)
    rebuild_finger(hand, "index", FingerPose(mcp=8.0, pip=5.0, dip=60.0), sign=1.0)
    assert coupling_error(poses(hand)["index"]) > 30.0

    out = HandPhysics().update(hand, 0.0)
    assert "index" in out.suspect
    assert out.rebuilt == 1
    # после правки DIP снова согласован с PIP
    fixed = out.poses["index"]
    assert coupling_error(fixed) <= 0.3 * LIMITS["index"][1]
    assert "физика пальцев" in out.note()


def test_harmonize_pulls_the_weaker_joint():
    pose = harmonize(FingerPose(mcp=5.0, pip=90.0, dip=10.0), "index")
    assert pose.dip == pytest.approx(DIP_TO_PIP * pose.pip, abs=1e-6)
    # перегиб сверх предела тоже снимается
    pose = harmonize(FingerPose(mcp=5.0, pip=300.0, dip=200.0), "index")
    assert pose.pip <= LIMITS["index"][1] + 1e-6


# --------------------------------------------------------------------------- #
#  «Прыжок» одного пальца при неподвижной ладони — сбой, а не движение
# --------------------------------------------------------------------------- #
def test_single_finger_jump_is_held():
    physics = HandPhysics()
    base = {name: 0.15 for name in FINGERS}
    physics.update(synthetic_hand(curl=base, center=(0.5, 0.55)), 0.0)

    glitch = synthetic_hand(curl=base, center=(0.5, 0.55))
    mcp, pip, dip, tip = FINGERS["ring"]
    glitch.points[pip, :2] = glitch.points[mcp, :2] + (
        glitch.points[pip, :2] - glitch.points[mcp, :2]) * 0.4
    glitch.points[dip, :2] = glitch.points[pip, :2] + np.array([0.05, 0.0])
    glitch.points[tip, :2] = glitch.points[dip, :2] + np.array([0.04, 0.02])

    out = physics.update(glitch, 1 / 30)
    assert "ring" in out.suspect and out.held == 1
    # палец придержан на прошлой позе, а не выгнут по глитчу
    assert abs(out.poses["ring"].pip - 15.5) < 20.0


def test_slow_real_motion_is_not_held():
    physics = HandPhysics()
    physics.update(_hand(0.0), 0.0)
    out = physics.update(_hand(0.35), 1 / 30)      # нормальное сжатие за кадр
    assert out.held == 0 and out.suspect == ()


def test_physics_can_be_switched_off():
    physics = HandPhysics(enabled=False)
    hand = _hand(0.0)
    out = physics.update(hand, 0.0)
    assert out.hand is hand and out.suspect == ()
