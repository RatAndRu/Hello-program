"""Поворот головы: восстановление углов и «курсор не прыгает».

Синтетическое лицо с ``depth`` объёмное, поэтому Kabsch видит поворот головы.
Углы — это поворот головы в кадре (голову повернули на +20° → ``yaw`` +20°);
в какую сторону сдвигается зрачок при таком повороте, знает только сам человек,
поэтому знак и величину поправки подбирает калибровка.
"""

import numpy as np
import pytest

from airmouse.face import FaceMetrics, measure_face
from airmouse.headpose import (
    HeadPose,
    HeadPoseEstimator,
    euler_angles,
    kabsch,
    rotation_matrix,
)
from airmouse.landmarks import Face
from airmouse.synthetic import synthetic_face


def _rotated(face: Face, yaw: float, pitch: float, roll: float) -> Face:
    R = rotation_matrix(yaw, pitch, roll)
    pts = np.asarray(face.points, dtype=np.float64)
    return Face((pts - pts.mean(axis=0)) @ R.T + pts.mean(axis=0))


# --------------------------------------------------------------------------- #
#  Математика
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "yaw, pitch, roll",
    [(0.0, 0.0, 0.0), (20.0, 15.0, 10.0), (-25.0, -12.0, 7.0), (7.5, -3.0, -14.0)],
)
def test_euler_round_trip(yaw, pitch, roll):
    got = euler_angles(rotation_matrix(yaw, pitch, roll))
    assert got == pytest.approx((yaw, pitch, roll), abs=1e-6)


def test_rotation_matrix_is_orthonormal():
    R = rotation_matrix(18.0, -9.0, 25.0)
    assert R @ R.T == pytest.approx(np.eye(3), abs=1e-12)
    assert float(np.linalg.det(R)) == pytest.approx(1.0, abs=1e-12)


def test_kabsch_recovers_rotation():
    base = np.asarray(synthetic_face(depth=1.0).points, dtype=np.float64)
    centered = base - base.mean(axis=0)
    R = rotation_matrix(16.0, -11.0, 6.0)
    rotated = centered @ R.T
    got = kabsch(centered, rotated)        # эталон -> текущее = поворот головы
    assert got is not None
    assert got @ centered.T == pytest.approx(rotated.T, abs=1e-6)
    assert euler_angles(got) == pytest.approx((16.0, -11.0, 6.0), abs=1e-6)
    back = kabsch(rotated, centered)       # и обратно — тоже поворот
    assert back is not None
    assert back @ rotated.T == pytest.approx(centered.T, abs=1e-6)


def test_flat_cloud_has_no_pose():
    """Плоское облако не даёт объёма — честно говорим «позы нет»."""
    flat = synthetic_face(depth=0.0)
    estimator = HeadPoseEstimator(reference_frames=5)
    pose = None
    for _ in range(6):
        pose = estimator.update(flat.points)
    assert pose is not None
    assert pose.ok is False
    assert pose.text() == ""


# --------------------------------------------------------------------------- #
#  Оценщик
# --------------------------------------------------------------------------- #
def _estimator_looking_neutral(frames: int = 25) -> HeadPoseEstimator:
    estimator = HeadPoseEstimator()
    neutral = synthetic_face(depth=1.0)
    for _ in range(frames):
        estimator.update(neutral.points)
    return estimator


def test_estimator_reads_turned_head():
    estimator = _estimator_looking_neutral()
    turned = _rotated(synthetic_face(depth=1.0), 15.0, 0.0, 0.0)
    pose = None
    for _ in range(20):
        pose = estimator.update(turned.points)
    assert pose.ok
    assert pose.rotated is True
    assert pose.yaw == pytest.approx(15.0, abs=1.5)
    assert pose.pitch == pytest.approx(0.0, abs=1.5)
    assert "yaw" in pose.text() and "крен" in pose.text()


def test_estimator_flat_face_is_ok_near_zero():
    """Прямо смотрящая голова — поворот ноль, компенсация не включается."""
    estimator = _estimator_looking_neutral()
    neutral = synthetic_face(depth=1.0)
    pose = None
    for _ in range(25):
        pose = estimator.update(neutral.points)
    assert pose.ok
    assert abs(pose.yaw) < 1.5 and abs(pose.pitch) < 1.5
    assert pose.rotated is False
    assert "yaw" in pose.text()


def test_pose_text_mentions_angles():
    pose = HeadPose(matrix=np.eye(3), yaw=12.4, pitch=-3.2, roll=0.4, ok=True)
    assert "+12" in pose.text() and "-3" in pose.text()
    assert HeadPose(ok=False).text() == ""


def test_measure_face_exposes_head_angles():
    estimator = _estimator_looking_neutral()
    face = _rotated(synthetic_face(depth=1.0), 12.0, 0.0, 0.0)
    metrics: FaceMetrics | None = None
    for _ in range(20):
        metrics = measure_face(face, estimator)
    assert metrics.head_ok
    assert metrics.head_yaw == pytest.approx(12.0, abs=2.0)
    # признак мыши — угол взгляда в «тангенсах», конечное число
    assert np.isfinite(metrics.gaze_u) and np.isfinite(metrics.gaze_v)
