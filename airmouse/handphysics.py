"""Физика пальцев: пределы сгиба, связка суставов и отбраковка невозможных кадров.

Зачем это нужно. Нейросеть отдаёт 21 точку кисти по одной картинке и ничего не
знает про анатомию: когда пальцы касаются друг друга, уходят за ладонь или
перекрываются, точки «прыгают» — палец за один кадр сгибается на 80°, хотя
человек держит руку ровно. Глазу это видно сразу, а жестам и AR-отрисовке
мешает: поза дёргается, жест «кулак» ловится там, где его нет.

Что здесь считается по литературе (а не «на глаз»):

* **Пределы сгиба.** Средние значения по обзору «Ergonomic Evaluation of
  Biomechanical Hand Function» (PMC4372184): PIP ≈ 105°, DIP ≈ 69°,
  MCP ≈ 84°. PIP и DIP назад (в тыльную сторону) практически не гнутся,
  у MCP переразгибание возможно примерно до 30°.
* **Связка PIP–DIP.** Кончик пальца не гнётся сам по себе: по данным Hahn et
  al. (1995), Cobos et al. (2007), Mentzel et al. (2011) DIP ≈ 0.75·PIP
  (разброс 0.65…0.88). Значит кадр, где PIP прямой, а DIP согнут на 60°, —
  ошибка распознавания, а не поза.
* **Скорость сгиба.** Кулак сжимается за 0.5–1.0 с (The Dynamics of Motion
  Sequences of the Finger Joints during Fist Closure), то есть порядка
  100–200 °/с на сустав. Скачок на 70° за кадр (≈2000 °/с) физически
  невозможен — это глитч точек, а не движение.
* **Соседние пальцы тянут друг друга.** Сухожилия сгибателей общие (quadriga
  effect), а между пальцами есть поперечные связки (juncturae tendinum). Одним
  пальцем «отыграть» назад, когда ладонь раскрыта, почти нельзя — за ним идут
  соседи. Здесь это используется как проверка: одиночный палец, который уехал
  далеко от соседей за один кадр при неподвижной ладони, считается сбоем и
  придерживается на прежнем месте.

Модуль чистый (numpy), поэтому проверяется синтетической кистью.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

from .gestures import angle_deg
from .landmarks import FINGERS, Hand, INDEX_MCP, MIDDLE_MCP, PINKY_MCP, RING_MCP, WRIST

PALM_IDS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

# Пределы сгиба в градусах (0 — палец прямой).
# Верхние пределы взяты с запасом (по обзору PMC4372184 средние 84/105/69,
# отдельные исследования дают до 95/110/80). Запас нужен, чтобы ловить именно
# невозможное, а не мешать человеку сжимать кулак: настоящий кулак по точкам
# MediaPipe нередко выходит за «средние» значения.
LIMITS: Dict[str, Tuple[float, float, float]] = {
    #            MCP            PIP            DIP
    "index":  (95.0, 110.0, 80.0),
    "middle": (95.0, 112.0, 82.0),
    "ring":   (95.0, 112.0, 78.0),
    "pinky":  (95.0, 108.0, 80.0),
    "thumb":  (70.0, 90.0, 90.0),      # у большого пальца своя анатомия
}

# Переразгибание (в «минус», тыльная сторона). PIP и DIP почти не гнутся назад.
HYPEREXTENSION: Dict[str, Tuple[float, float, float]] = {
    "index":  (-25.0, -3.0, 0.0),
    "middle": (-25.0, -3.0, 0.0),
    "ring":   (-25.0, -3.0, 0.0),
    "pinky":  (-25.0, -5.0, 0.0),
    "thumb":  (-15.0, -5.0, 0.0),
}

# DIP тянется за PIP: кончик не сгибается сам по себе.
DIP_TO_PIP = 0.75
# Разброс связи, который ещё считается нормой (по литературе 0.65…0.88).
DIP_TOLERANCE = 0.30
# Физический предел скорости изменения угла сустава.
MAX_JOINT_SPEED = 1200.0          # градусов в секунду
# Сколько градусов за кадр считаем глитчем при любой частоте кадров.
MAX_JUMP_PER_FRAME = 70.0
# Насколько «уехавший» от соседей палец считается сбоем (в долях сгиба 0..1).
NEIGHBOUR_JUMP = 0.45

SUSPECT_NAMES = {
    "thumb": "большой",
    "index": "указательный",
    "middle": "средний",
    "ring": "безымянный",
    "pinky": "мизинец",
}


@dataclass(frozen=True)
class FingerPose:
    """Сгиб одного пальца в градусах: 0 — прямой, + к ладони, − переразгиб."""

    mcp: float = 0.0
    pip: float = 0.0
    dip: float = 0.0

    @property
    def curl(self) -> float:
        """0 — палец прямой, 1 — сжат в кулак (по PIP и MCP)."""
        pip_max = LIMITS["index"][1]
        return max(0.0, min(1.0, 0.7 * abs(self.pip) / pip_max + 0.3 * abs(self.mcp) / 84.0))


@dataclass
class PhysicsOut:
    """Что получилось после проверки кадра."""

    hand: Hand
    poses: Dict[str, FingerPose] = field(default_factory=dict)
    suspect: Tuple[str, ...] = ()      # пальцы, которым не поверили
    violations: int = 0                # сколько пределов нарушено в этом кадре
    rebuilt: int = 0                   # сколько пальцев перерисовано по физике
    held: int = 0                      # сколько пальцев «придержано» на прошлом кадре

    @property
    def ok(self) -> bool:
        return not self.suspect

    def note(self) -> str:
        """Короткая строка для окна: «физика: придержан указательный»."""
        if not self.suspect:
            return ""
        names = ", ".join(SUSPECT_NAMES.get(name, name) for name in self.suspect)
        return f"физика пальцев: придержан {names}"


def _v(hand: Hand, index: int) -> np.ndarray:
    return hand.points[index, :2].astype(np.float64)


def finger_pose(hand: Hand, name: str) -> FingerPose:
    """Сгиб пальца по трём суставам — из точек кадра."""
    mcp, pip, dip, tip = FINGERS[name]
    base = _v(hand, WRIST)
    a_mcp = 180.0 - angle_deg(base, _v(hand, mcp), _v(hand, pip))
    a_pip = 180.0 - angle_deg(_v(hand, mcp), _v(hand, pip), _v(hand, dip))
    a_dip = 180.0 - angle_deg(_v(hand, pip), _v(hand, dip), _v(hand, tip))
    return FingerPose(mcp=a_mcp, pip=a_pip, dip=a_dip)


def poses(hand: Hand) -> Dict[str, FingerPose]:
    return {name: finger_pose(hand, name) for name in FINGERS}


def _bend_sign(hand: Hand, name: str) -> float:
    """В какую сторону гнётся палец в кадре (+1 / −1)."""
    mcp, pip, dip, _tip = FINGERS[name]
    a = _v(hand, pip) - _v(hand, mcp)
    b = _v(hand, dip) - _v(hand, pip)
    cross = float(a[0] * b[1] - a[1] * b[0])
    if abs(cross) < 1e-9:
        return 1.0
    return 1.0 if cross > 0 else -1.0


def clamp_pose(pose: FingerPose, name: str = "index") -> Tuple[FingerPose, int]:
    """Привести сгиб в физические пределы. Возвращает (поза, сколько нарушений)."""
    hi = LIMITS[name]
    lo = HYPEREXTENSION[name]
    bad = 0
    values = []
    for value, upper, lower in zip((pose.mcp, pose.pip, pose.dip), hi, lo):
        clamped = max(lower, min(upper, value))
        if abs(clamped - value) > 1.0:
            bad += 1
        values.append(clamped)
    return FingerPose(*values), bad


def coupling_error(pose: FingerPose) -> float:
    """Насколько DIP не согласован с PIP (в градусах, 0 — согласован).

    Кончик пальца не гнётся сам по себе: DIP ≈ 0.75·PIP. Поэтому «PIP прямой, а
    DIP согнут на 60°» — это тоже ошибка распознавания, хотя каждый сустав по
    отдельности в пределы укладывается.
    """
    expected = DIP_TO_PIP * pose.pip
    return abs(pose.dip - expected)


def harmonize(pose: FingerPose, name: str = "index") -> FingerPose:
    """Привести позу к пределам и согласовать DIP с PIP.

    Большему суставу верим больше: если согнут в основном PIP — подтягиваем
    DIP, если «сломался» DIP — подтягиваем PIP (так бывает, когда кончик
    пальца прикрыт ладонью и нейросеть дорисовала его сама).
    """
    mcp, pip, dip = pose.mcp, pose.pip, pose.dip
    if pip >= dip:
        dip = DIP_TO_PIP * pip
    else:
        pip = dip / DIP_TO_PIP
        dip = DIP_TO_PIP * pip
    return clamp_pose(FingerPose(mcp, pip, dip), name)[0]


def _rotate(vec: np.ndarray, radians: float) -> np.ndarray:
    c, s = math.cos(radians), math.sin(radians)
    return np.array([vec[0] * c - vec[1] * s, vec[0] * s + vec[1] * c])


def rebuild_finger(hand: Hand, name: str, pose: FingerPose,
                   sign: float = 1.0) -> None:
    """Перерисовать палец по физике, сохранив основание и направление.

    Меняет ``hand.points`` на месте: основание (MCP) остаётся там, где его
    увидела нейросеть, а длины фаланг берутся из этого же кадра — поэтому
    палец не «переезжает», а просто перестаёт выгибаться невозможным образом.
    """
    mcp, pip, dip, tip = FINGERS[name]
    base = _v(hand, mcp)
    seg = np.array([
        max(float(np.linalg.norm(_v(hand, pip) - base)), 1e-6),
        max(float(np.linalg.norm(_v(hand, dip) - _v(hand, pip))), 1e-6),
        max(float(np.linalg.norm(_v(hand, tip) - _v(hand, dip))), 1e-6),
    ])
    direction = _v(hand, pip) - base
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        return
    direction = direction / norm

    # Сгиб распределяем по суставам: MCP, затем PIP, DIP ≈ 0.75·PIP
    pip_angle = max(0.0, float(pose.pip))
    dip_angle = max(0.0, float(pose.dip))
    mcp_angle = max(0.0, float(pose.mcp))

    first = _rotate(direction, sign * math.radians(mcp_angle * 0.35))
    pos = base + first * seg[0]
    hand.points[pip, :2] = pos

    second = _rotate(first, sign * math.radians(max(pip_angle, 1.0)))
    pos = pos + second * seg[1]
    hand.points[dip, :2] = pos

    third = _rotate(second, sign * math.radians(max(dip_angle, 1.0)))
    pos = pos + third * seg[2]
    hand.points[tip, :2] = pos


class HandPhysics:
    """Проверяет позу кисти по анатомии и придерживает «прыгающие» пальцы.

    Возвращает новую кисть (копию) — входную не меняет, поэтому в тестах и в
    оверлее можно сравнить «до» и «после».
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self._prev_poses: Dict[str, FingerPose] = {}
        self._prev_points: Optional[np.ndarray] = None
        self._prev_t: Optional[float] = None
        self.last_note = ""

    def reset(self) -> None:
        self._prev_poses = {}
        self._prev_points = None
        self._prev_t = None
        self.last_note = ""

    def update(self, hand: Hand, now: float) -> PhysicsOut:
        if not self.enabled:
            return PhysicsOut(hand=hand)

        out_hand = Hand(hand.points.copy(), hand.handedness, hand.score)
        dt = 1.0 / 30.0 if self._prev_t is None else max(now - self._prev_t, 1e-3)
        frame_limit = min(MAX_JUMP_PER_FRAME, MAX_JOINT_SPEED * dt)

        measured = poses(out_hand)
        palm_shift = 0.0
        if self._prev_points is not None:
            palm_shift = float(np.linalg.norm(
                out_hand.palm_center
                - self._prev_points[list(PALM_IDS), :2].mean(axis=0)))
            palm_shift /= max(float(out_hand.palm_size), 1e-6)

        suspect: list = []
        violations = 0
        rebuilt = 0
        held = 0

        for name, pose in measured.items():
            clamped, bad = clamp_pose(pose, name)
            coupling = coupling_error(pose)
            violation = bad > 0 or coupling > DIP_TOLERANCE * LIMITS[name][1]
            if violation:
                clamped = harmonize(pose, name)

            jump = 0.0
            prev = self._prev_poses.get(name)
            if prev is not None:
                jump = max(abs(pose.pip - prev.pip), abs(pose.mcp - prev.mcp),
                           abs(pose.dip - prev.dip))

            # Сосед «уехал» один: смотрим, двигались ли остальные и ладонь.
            alone = False
            if prev is not None and jump > frame_limit * 0.7 and palm_shift < 0.10:
                others = [abs(p.pip - self._prev_poses[n2].pip)
                          for n2, p in measured.items()
                          if n2 != name and n2 in self._prev_poses]
                alone = bool(others) and max(others) < NEIGHBOUR_JUMP * 10.0

            if prev is not None and (jump > frame_limit or alone):
                # Глитч: придерживаем палец на прошлом кадре, но двигаем его
                # вместе с кистью (иначе палец «отклеится» от ладони).
                if self._prev_points is not None:
                    mcp_id = FINGERS[name][0]
                    shift = _v(out_hand, mcp_id) - self._prev_points[mcp_id, :2]
                    for idx in FINGERS[name][1:]:
                        out_hand.points[idx, :2] = self._prev_points[idx, :2] + shift
                held += 1
                suspect.append(name)
                continue

            if violation:
                rebuild_finger(out_hand, name, clamped, _bend_sign(out_hand, name))
                rebuilt += 1
                violations += bad
                suspect.append(name)

        self._prev_poses = poses(out_hand)
        self._prev_points = out_hand.points.copy()
        self._prev_t = now
        self.last_note = ""

        # Ничего не правили — отдаём ту же кисть, что пришла: лишняя копия
        # ломает сравнение «это та же рука» и тратит память каждый кадр.
        if rebuilt == 0 and held == 0:
            out_hand = hand
        out = PhysicsOut(hand=out_hand, poses=self._prev_poses,
                         suspect=tuple(suspect), violations=violations,
                         rebuilt=rebuilt, held=held)
        self.last_note = out.note()
        return out
