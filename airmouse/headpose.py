"""Поворот головы: «глаз смотрит в ту же точку — курсор там же».

Зачем это нужно. Положение зрачка в глазнице — это направление взгляда
**относительно головы**. Если повернуть голову на 20°, но продолжать смотреть в
ту же точку экрана, глаз внутри головы повернётся на те же 20° назад, и «сырое»
положение зрачка уедет. Без компенсации курсор в этот момент прыгает, хотя
человек смотрит туда же.

Компенсация: берём точки лица (MediaPipe отдаёт их в 3D), сравниваем текущее
облако с эталонным (нейтральная поза, снятая в первые кадры) и находим поворот
по методу Кабша (SVD). Затем поворачиваем вектор «зрачок → взгляд» из системы
головы в систему эталонной позы: при повороте головы с неподвижным взглядом
результат остаётся прежним.

Здесь считается только **поворот головы** (градусы). Как именно он влияет на
измеренный зрачок — вопрос конкретного лица и камеры (параллакс века, посадка),
поэтому коэффициенты компенсации не зашиты, а снимаются с самого человека на
этапе калибровки (см. :meth:`airmouse.gaze.GazeCalibration.fit_head`).

Модуль чистый: только numpy, никакой камеры и ОС — поэтому проверяется тестами
на синтетических повёрнутых облаках точек.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np


# Сколько первых кадров усредняем, чтобы получить эталонную позу головы.
REFERENCE_FRAMES = 20
# Сглаживание углов: одиночный шумный кадр не должен дёргать курсор.
ANGLE_ALPHA = 0.35
# Меньше этого угла считаем «прямо»: компенсировать нечего.
ANGLE_DEADZONE_DEG = 1.0
# Насколько «плоским» может быть облако точек, чтобы поворот ещё считался.
MIN_DEPTH_RATIO = 0.02


def rotation_matrix(yaw_deg: float = 0.0, pitch_deg: float = 0.0,
                    roll_deg: float = 0.0) -> np.ndarray:
    """Матрица поворота: рыскание (yaw) вокруг y, тангаж (pitch) вокруг x, крен вокруг z.

    Оси как у MediaPipe: x — вправо, y — вниз, z — «вглубь» экрана.
    """
    y, p, r = (math.radians(v) for v in (yaw_deg, pitch_deg, roll_deg))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    rz = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]])
    return rz @ rx @ ry


def euler_angles(R: np.ndarray) -> Tuple[float, float, float]:
    """Матрица поворота -> (yaw, pitch, roll) в градусах."""
    r = np.asarray(R, dtype=np.float64)
    # порядок ровно как в rotation_matrix: R = Rz(крен) · Rx(тангаж) · Ry(рыскание)
    yaw = math.degrees(math.atan2(-float(r[2, 0]), float(r[2, 2])))
    pitch = math.degrees(math.asin(float(np.clip(r[2, 1], -1.0, 1.0))))
    roll = math.degrees(math.atan2(-float(r[0, 1]), float(r[1, 1])))
    return yaw, pitch, roll


def kabsch(points_from: np.ndarray, points_to: np.ndarray) -> Optional[np.ndarray]:
    """Поворот, переводящий ``points_from`` в ``points_to`` (без масштаба).

    Оба облака должны быть уже отцентрованы. Возвращает ``None``, если облако
    плоское: тогда поворот вокруг нормали не определён, и любая оценка — шум.
    """
    a = np.asarray(points_from, dtype=np.float64)
    b = np.asarray(points_to, dtype=np.float64)
    if a.shape != b.shape or a.shape[0] < 4:
        return None
    # нормируем масштаб: расстояние до камеры не должно влиять на поворот
    sa = float(np.sqrt((a ** 2).sum(axis=1).mean()))
    sb = float(np.sqrt((b ** 2).sum(axis=1).mean()))
    if sa < 1e-9 or sb < 1e-9:
        return None
    a = a / sa
    b = b / sb
    u, s, vt = np.linalg.svd(a.T @ b)
    if s[0] <= 1e-9 or (s[2] / s[0]) < MIN_DEPTH_RATIO:
        return None                    # облако плоское — поворот не определить
    d = 1.0 if np.linalg.det(vt.T @ u.T) > 0 else -1.0
    corr = np.diag([1.0, 1.0, d])
    return vt.T @ corr @ u.T


@dataclass
class HeadPose:
    """Текущая поза головы относительно эталона."""

    matrix: np.ndarray = field(default_factory=lambda: np.eye(3))
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    ok: bool = False

    @property
    def rotated(self) -> bool:
        """Голова заметно повёрнута — стоит показать это в окне."""
        return self.ok and (abs(self.yaw) > 5.0 or abs(self.pitch) > 5.0 or abs(self.roll) > 5.0)

    def text(self) -> str:
        if not self.ok:
            return ""
        return f"голова: yaw {self.yaw:+.0f}° · pitch {self.pitch:+.0f}° · крен {self.roll:+.0f}°"


class HeadPoseEstimator:
    """Следит за поворотом головы по точкам лица и компенсирует положение зрачка."""

    def __init__(self, reference_frames: int = REFERENCE_FRAMES) -> None:
        self.reference_frames = max(1, int(reference_frames))
        self._buffer: List[np.ndarray] = []
        self._reference: Optional[np.ndarray] = None
        self.pose = HeadPose()
        self.last_matrix: Optional[np.ndarray] = None
        self._smoothed: Optional[Tuple[float, float, float]] = None

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Забыть эталон (например, при смене движка или камеры)."""
        self._buffer.clear()
        self._reference = None
        self._smoothed = None
        self.pose = HeadPose()
        self.last_matrix = None

    @property
    def ready(self) -> bool:
        return self._reference is not None

    # ------------------------------------------------------------------ #
    def update(self, points: Sequence[Sequence[float]]) -> HeadPose:
        """Скормить 3D-точки лица, получить позу головы относительно эталона."""
        cloud = np.asarray(points, dtype=np.float64)[:, :3]
        if cloud.shape[0] < 8 or not np.all(np.isfinite(cloud)):
            return self.pose
        centred = cloud - cloud.mean(axis=0)

        if self._reference is None:
            self._buffer.append(centred)
            if len(self._buffer) > self.reference_frames:
                del self._buffer[0]
            if len(self._buffer) < self.reference_frames:
                return self.pose
            self._reference = np.median(np.stack(self._buffer), axis=0)
            self._buffer.clear()
            return self.pose

        # kabsch(эталон -> текущее) даёт поворот головы: именно им и надо
        # повернуть «зрачок в голове» в координаты эталонной позы
        R = kabsch(self._reference, centred)
        if R is None:
            self.pose = HeadPose(ok=False)
            return self.pose
        self.last_matrix = R
        yaw, pitch, roll = euler_angles(R)
        self.pose = HeadPose(matrix=R, yaw=yaw, pitch=pitch, roll=roll, ok=True)
        return self.pose

    # ------------------------------------------------------------------ #
    def smoothed_pose(self) -> HeadPose:
        """Поза со сглаживанием — именно она идёт в компенсацию.

        Сырой поворот по кадрам слегка дрожит (z у MediaPipe шумный). Если
        компенсировать дрожание, курсор начнёт звенеть, поэтому углы сглаживаем
        и «прямо» считаем всё, что меньше градуса.
        """
        pose = self.pose
        if not pose.ok:
            self._smoothed = None
            return HeadPose(ok=False)
        yaw, pitch, roll = pose.yaw, pose.pitch, pose.roll
        if self._smoothed is None:
            self._smoothed = (yaw, pitch, roll)
        else:
            a = ANGLE_ALPHA
            self._smoothed = (
                a * yaw + (1 - a) * self._smoothed[0],
                a * pitch + (1 - a) * self._smoothed[1],
                a * roll + (1 - a) * self._smoothed[2],
            )
        y, p, r = self._smoothed
        y = 0.0 if abs(y) < ANGLE_DEADZONE_DEG else y
        p = 0.0 if abs(p) < ANGLE_DEADZONE_DEG else p
        r = 0.0 if abs(r) < ANGLE_DEADZONE_DEG else r
        return HeadPose(matrix=rotation_matrix(y, p, r), yaw=y, pitch=p, roll=r, ok=True)
