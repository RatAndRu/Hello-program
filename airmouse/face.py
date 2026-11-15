"""Мимика: моргание, улыбка, брови, поворот головы.

Всё считается из геометрии 468 точек лица — без нейросетей-классификаторов
эмоций. Пороги относительные (в единицах межзрачкового расстояния), поэтому
не зависят от размера лица в кадре.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple, List, Optional

import numpy as np

from .config import FaceConfig
from .filters import Cooldown, HoldTimer, deadzone
from .gestures import Event
from .headpose import HeadPoseEstimator
from .landmarks import F, Face, distance, safe_div


@dataclass
class FaceMetrics:
    """Сырые измерения лица (без порогов и без сравнения с нейтралью)."""

    ear_left: float = 0.3
    ear_right: float = 0.3
    mouth_width: float = 0.0       # в единицах межзрачкового расстояния
    mouth_open: float = 0.0        # просвет между губами / ширина рта
    corner_lift: float = 0.0
    brow_height: float = 0.0
    yaw: float = 0.0               # градусы, приблизительно
    pitch: float = 0.0
    roll: float = 0.0
    interocular: float = 0.0
    gaze_x: float = 0.0            # зрачок в глазнице: 0 — центр, + — вправо
    gaze_y: float = 0.0            # + — вниз
    gaze_u: float = 0.0            # тот же взгляд, но с поправкой на поворот головы
    gaze_v: float = 0.0
    head_yaw: float = 0.0          # поворот головы относительно эталона, градусы
    head_pitch: float = 0.0
    head_roll: float = 0.0
    head_ok: bool = False          # поворот головы удалось оценить
    gaze_valid: bool = False       # есть ли точки радужки в этом кадре
    gaze_scale: float = 1.25       # зрачок -> угол (см. gaze_angle_scale)
    valid: bool = False

    def as_vector(self) -> np.ndarray:
        return np.array([
            self.mouth_open,
            self.mouth_width,
            self.corner_lift,
            self.brow_height,
        ])


def _ear(face: Face, idx) -> float:
    p1, p2, p3, p4, p5, p6 = (face.xy(i) for i in idx)
    horiz = distance(p1, p4)
    if horiz < 1e-6:
        return 0.0
    return (distance(p2, p6) + distance(p3, p5)) / (2.0 * horiz)


def _eye_box(face: Face, ids) -> Tuple[float, float, float, float]:
    """Прямоугольник глазницы: (cx, cy, полуширина, полувысота)."""
    outer = face.xy(ids[0])       # угол у виска
    inner = face.xy(ids[3])       # угол у носа
    top = (face.xy(ids[1]) + face.xy(ids[2])) / 2.0
    bottom = (face.xy(ids[4]) + face.xy(ids[5])) / 2.0
    cx = (outer[0] + inner[0]) / 2.0
    cy = (top[1] + bottom[1]) / 2.0
    half_w = max(abs(inner[0] - outer[0]) / 2.0, 1e-6)
    half_h = max((bottom[1] - top[1]) / 2.0, 1e-6)
    return cx, cy, half_w, half_h


# Отношение радиуса глазного яблока к радиусу радужки: у человека примерно
# 12 мм / 5.85 мм. Нужно, чтобы перевести «зрачок в глазнице» в угол поворота
# глаза, не подбирая коэффициенты под каждую камеру: масштаб считается по
# размерам самого глаза в кадре.
EYE_RADIUS_RATIO = 2.05


def gaze_angle_scale(face: Face) -> float:
    """Сколько «тангенсов» угла приходится на единицу смещения зрачка.

    ``dx`` в :func:`measure_gaze` — это смещение радужки в единицах полуширины
    глазницы. Поворот глаза φ даёт смещение ``r_eye * sin φ``, поэтому
    ``tan φ ≈ dx * half_width / (ratio * r_iris)``. Всё это видно в кадре, так
    что коэффициент получается сам, без калибровки и без «магических» чисел.
    """
    if not face.has_iris:
        return 1.25
    scales = []
    for eye_ids, iris_ids in ((F.EYE_A, F.IRIS_A), (F.EYE_B, F.IRIS_B)):
        _cx, _cy, half_w, _half_h = _eye_box(face, eye_ids)
        centre = face.iris_center(iris_ids)
        if centre is None or half_w < 1e-6:
            continue
        ring = face.points[list(iris_ids)[1:], :2].astype(np.float64)
        radius = float(np.linalg.norm(ring - centre, axis=1).mean())
        if radius < 1e-6:
            continue
        scales.append(half_w / (EYE_RADIUS_RATIO * radius))
    if not scales:
        return 1.25
    value = float(np.mean(scales))
    return float(min(max(value, 0.3), 5.0))


def measure_gaze(face: Face) -> Tuple[float, float, bool]:
    """Куда смотрит человек: положение зрачка внутри глазницы.

    Возвращает ``(dx, dy, ok)``, где ``dx``/``dy`` — смещение зрачка от центра
    глаза в единицах полуширины/полувысоты глазницы: 0 — смотрит прямо,
    ±1 — зрачок у самого края. Оба глаза должны давать согласованный знак,
    поэтому берём среднее, а радужку привязываем к ближайшему глазу.
    """
    if not face.has_iris:
        return 0.0, 0.0, False

    eyes = []
    for ids in (F.EYE_A, F.EYE_B):
        cx, cy, half_w, half_h = _eye_box(face, ids)
        eyes.append((cx, cy, half_w, half_h))

    irises = [face.iris_center(F.IRIS_A), face.iris_center(F.IRIS_B)]
    irises = [p for p in irises if p is not None]
    if len(irises) < 2:
        return 0.0, 0.0, False

    dxs, dys = [], []
    for ix, iy in ((float(p[0]), float(p[1])) for p in irises):
        # радужка относится к тому глазу, чей центр по x ближе
        cx, cy, half_w, half_h = min(eyes, key=lambda e: abs(e[0] - ix))
        dxs.append((ix - cx) / half_w)
        dys.append((iy - cy) / half_h)
    if any(abs(d) > 1.6 or abs(v) > 1.6 for d, v in zip(dxs, dys)):
        return 0.0, 0.0, False       # точка «улетела» — кадр битый

    dx = max(-1.0, min(1.0, sum(dxs) / len(dxs)))
    dy = max(-1.0, min(1.0, sum(dys) / len(dys)))
    return dx, dy, True


def measure_face(face: Face, head: "HeadPoseEstimator | None" = None) -> FaceMetrics:
    """Считает все метрики лица за один проход.

    ``head`` — оценщик поворота головы. Если он передан, взгляд пересчитывается
    в систему координат эталонной позы (``gaze_u``/``gaze_v``): при повороте
    головы с неподвижным взглядом такой признак не меняется, поэтому курсор не
    прыгает. Без оценщика ``gaze_u``/``gaze_v`` равны ``gaze_x``/``gaze_y``.
    """
    io = face.scale
    if io < 1e-5:
        return FaceMetrics(valid=False)

    ear_l = _ear(face, F.EYE_A)
    ear_r = _ear(face, F.EYE_B)

    m_left = face.xy(F.MOUTH_LEFT)
    m_right = face.xy(F.MOUTH_RIGHT)
    width = distance(m_left, m_right) / io

    inner_gap = distance(face.xy(F.LIP_TOP_INNER), face.xy(F.LIP_BOTTOM_INNER))
    inner_width = distance(face.xy(F.LIP_LEFT_INNER), face.xy(F.LIP_RIGHT_INNER))
    mouth_open = safe_div(inner_gap, max(inner_width, 1e-6))

    # Уголки губ вверх = улыбка. Меряем относительно середины линии рта.
    corners_y = (m_left[1] + m_right[1]) / 2.0
    lip_center_y = (face.xy(F.LIP_TOP_INNER)[1] + face.xy(F.LIP_BOTTOM_INNER)[1]) / 2.0
    corner_lift = (lip_center_y - corners_y) / io

    brow_h = (
        (face.xy(F.EYE_A_TOP)[1] - face.xy(F.BROW_A)[1])
        + (face.xy(F.EYE_B_TOP)[1] - face.xy(F.BROW_B)[1])
    ) / 2.0 / io

    eye_mid = (face.xy(F.EYE_A[0]) + face.xy(F.EYE_B[3])) / 2.0
    nose = face.xy(F.NOSE_TIP)
    yaw = math.degrees(math.atan2(nose[0] - eye_mid[0], io)) * 1.0
    pitch = math.degrees(math.atan2(nose[1] - eye_mid[1], io)) * 1.0
    eye_a = face.xy(F.EYE_A[0])
    eye_b = face.xy(F.EYE_B[3])
    roll = math.degrees(math.atan2(eye_b[1] - eye_a[1], eye_b[0] - eye_a[0]))

    gaze_x, gaze_y, gaze_ok = measure_gaze(face)

    # поворот головы -> компенсированный взгляд (одинаковый при поворотах)
    pose = None
    if head is not None and face.has_iris:
        head.update(face.points)
        pose = head.smoothed_pose()
    # Признак для мыши — тангенс угла поворота глаза (а не «попугаи» зрачка).
    # Поворот головы сюда не подмешивается: его компенсирует калибровка,
    # у которой есть коэффициенты, снятые на поворотах головы этого человека.
    k = gaze_angle_scale(face)
    gaze_u, gaze_v = (gaze_x * k, gaze_y * k) if gaze_ok else (gaze_x, gaze_y)

    return FaceMetrics(
        ear_left=ear_l,
        ear_right=ear_r,
        mouth_width=width,
        mouth_open=mouth_open,
        corner_lift=corner_lift,
        brow_height=brow_h,
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        interocular=io,
        gaze_x=gaze_x,
        gaze_y=gaze_y,
        gaze_u=gaze_u,
        gaze_v=gaze_v,
        head_yaw=pose.yaw if pose is not None else 0.0,
        head_pitch=pose.pitch if pose is not None else 0.0,
        head_roll=pose.roll if pose is not None else 0.0,
        head_ok=bool(pose is not None and pose.ok),
        gaze_scale=k,
        gaze_valid=gaze_ok,
        valid=True,
    )


class _BlinkTracker:
    """Гистерезис по EAR: глаз считается закрытым, пока EAR ниже порога."""

    def __init__(self, closed_below: float, open_above: float) -> None:
        self.closed_below = closed_below
        self.open_above = open_above
        self.closed = False
        self.since: Optional[float] = None

    def update(self, ear: float, now: float) -> Optional[float]:
        """Возвращает длительность закрытия, когда глаз снова открылся."""
        if self.closed:
            if ear > self.open_above:
                self.closed = False
                dur = 0.0 if self.since is None else now - self.since
                self.since = None
                return dur
        else:
            if ear < self.closed_below:
                self.closed = True
                self.since = now
        return None


@dataclass
class FaceBaseline:
    """Нейтральное выражение конкретного человека (калибруется на старте)."""

    smile: float = 0.0
    brow: float = 0.0
    corner: float = 0.0      # уголки губ: плюс — вверх (улыбка), минус — вниз (грусть)
    pitch: float = 0.0
    yaw: float = 0.0
    gaze_x: float = 0.0      # нейтральное положение зрачка (свой «ноль»)
    gaze_y: float = 0.0
    samples: int = 0

    def update(self, m: FaceMetrics, alpha: float = 0.05) -> None:
        if not m.valid:
            return
        if self.samples == 0:
            self.smile = m.mouth_width
            self.brow = m.brow_height
            self.corner = m.corner_lift
            self.pitch = m.pitch
            self.yaw = m.yaw
            self.gaze_x = m.gaze_x
            self.gaze_y = m.gaze_y
        else:
            self.smile = alpha * m.mouth_width + (1 - alpha) * self.smile
            self.brow = alpha * m.brow_height + (1 - alpha) * self.brow
            self.corner = alpha * m.corner_lift + (1 - alpha) * self.corner
            self.pitch = alpha * m.pitch + (1 - alpha) * self.pitch
            self.yaw = alpha * m.yaw + (1 - alpha) * self.yaw
            # ВАЖНО: gaze здесь НЕ подтягивается. Иначе нейтраль «догоняет»
            # взгляд, и относительное отклонение падает до нуля — курсор
            # перестаёт ехать. Свою нейтраль взгляда ведёт FaceFSM.
        self.samples += 1

    @property
    def ready(self) -> bool:
        return self.samples >= 10


class HeadGestures:
    """Кивок и поворот головы «нет» — по колебаниям углов, а не по одному кадру."""

    def __init__(self, cfg: FaceConfig) -> None:
        self.cfg = cfg
        self.cooldown = Cooldown(cfg.head_gesture_cooldown_s)
        self._yaw: List[Tuple[float, float]] = []
        self._pitch: List[Tuple[float, float]] = []

    def reset(self) -> None:
        self._yaw.clear()
        self._pitch.clear()
        self.cooldown.reset()

    @staticmethod
    def _turns(samples: List[Tuple[float, float]], eps: float = 0.6) -> int:
        """Сколько раз направление движения менялось (2 и больше — «качание»)."""
        turns = 0
        last_sign = 0
        for (_, a), (_, b) in zip(samples[:-1], samples[1:]):
            d = b - a
            if abs(d) < eps:
                continue
            sign = 1 if d > 0 else -1
            if last_sign and sign != last_sign:
                turns += 1
            last_sign = sign
        return turns

    @staticmethod
    def _amplitude(samples: List[Tuple[float, float]]) -> float:
        values = [v for _, v in samples]
        return (max(values) - min(values)) if values else 0.0

    def _trim(self, samples: List[Tuple[float, float]], now: float) -> List[Tuple[float, float]]:
        return [item for item in samples if now - item[0] <= self.cfg.head_gesture_window_s]

    def update(self, yaw: float, pitch: float, now: float) -> List[Event]:
        self._yaw = self._trim(self._yaw, now) + [(now, yaw)]
        self._pitch = self._trim(self._pitch, now) + [(now, pitch)]
        events: List[Event] = []
        if (self._turns(self._yaw) >= 2
                and self._amplitude(self._yaw) >= self.cfg.head_shake_deg
                and self.cooldown.try_fire("shake", now)):
            events.append(Event("head_shake", label="поворот головой"))
            self._yaw.clear()
        if (self._turns(self._pitch) >= 2
                and self._amplitude(self._pitch) >= self.cfg.head_nod_deg
                and self.cooldown.try_fire("nod", now)):
            events.append(Event("head_nod", label="кивок"))
            self._pitch.clear()
        return events


class FaceFSM:
    """Мимические жесты: двойное моргание, подмигивание, улыбка, брови."""

    def __init__(self, cfg: FaceConfig) -> None:
        self.cfg = cfg
        self.baseline = FaceBaseline()
        self.left = _BlinkTracker(cfg.ear_blink, cfg.ear_open)
        self.right = _BlinkTracker(cfg.ear_blink, cfg.ear_open)
        self.cooldown = Cooldown(0.5)
        self.smile_hold = HoldTimer(cfg.smile_hold_s)
        self.brow_hold = HoldTimer(cfg.brow_hold_s)
        # улыбка и брови — «медленные» жесты, им нужен свой кулдаун, иначе
        # одно и то же выражение лица стреляет очередью событий
        self.smile_cooldown = Cooldown(cfg.smile_cooldown_s)
        self.head = HeadGestures(cfg)
        self.brow_cooldown = Cooldown(cfg.brow_cooldown_s)
        self._last_blink_t: Optional[float] = None
        self._both_start: Optional[float] = None     # когда закрылись оба глаза
        self._closed_too_long = False                # держим закрытыми слишком долго
        self._closed_event_sent = False              # «глаза закрыты» уже сообщили
        self._eye = {"left": {"start": None, "other_closed": False},
                     "right": {"start": None, "other_closed": False}}
        self.smile_score = 0.0
        self.brow_score = 0.0
        self.sad_score = 0.0
        self.rel_yaw = 0.0
        self.rel_pitch = 0.0
        self.gaze_x = 0.0          # сглаженное положение зрачка (0 — центр)
        self.gaze_y = 0.0
        self.gaze_u = 0.0          # то же, но с поправкой на поворот головы
        self.gaze_v = 0.0
        self.gaze_valid = False
        self.head_ok = False
        self.head_yaw = 0.0
        self.head_pitch = 0.0
        self.head_roll = 0.0
        self.mouth_open = 0.0
        self.ear_value = 0.3

    # ------------------------------------------------------------------ #
    def calibrate(self, m: FaceMetrics) -> None:
        self.baseline = FaceBaseline()
        self.baseline.update(m)

    def reset(self) -> None:
        self.left = _BlinkTracker(self.cfg.ear_blink, self.cfg.ear_open)
        self.right = _BlinkTracker(self.cfg.ear_blink, self.cfg.ear_open)
        self.smile_hold.reset()
        self.brow_hold.reset()
        self.smile_cooldown.reset()
        self.brow_cooldown.reset()
        self.head.reset()
        self.cooldown.reset()
        self._last_blink_t = None
        self._both_start = None
        self._closed_too_long = False
        self._closed_event_sent = False
        self._eye = {"left": {"start": None, "other_closed": False},
                     "right": {"start": None, "other_closed": False}}

    # ------------------------------------------------------------------ #
    def update(self, m: Optional[FaceMetrics], now: float) -> List[Event]:
        events: List[Event] = []
        if m is None or not m.valid:
            self._both_start = None
            self._eye = {"left": {"start": None, "other_closed": False},
                         "right": {"start": None, "other_closed": False}}
            return events

        self.ear_value = min(m.ear_left, m.ear_right)
        self.mouth_open = m.mouth_open

        # --- базовая линия: медленно подтягивается, когда лицо спокойно --- #
        gesture_active = (m.mouth_width - self.baseline.smile) > self.cfg.smile_delta * 1.5
        if self.baseline.samples == 0:
            self.baseline.update(m)          # первый кадр — сразу нейтраль
        elif not gesture_active:
            self.baseline.update(m, alpha=0.02)

        # --- улыбка и грусть: их различает ЗНАК подъёма уголков губ ------- #
        # Ширина рта растёт и от улыбки, и от опущенных уголков (губы
        # растягиваются), поэтому одна ширина улыбку не отличает от грусти.
        lift_gain = m.corner_lift - self.baseline.corner   # + вверх, − вниз
        width_gain = m.mouth_width - self.baseline.smile
        self.sad_score = max(0.0, -lift_gain)
        if lift_gain < -self.cfg.sad_delta * 0.5:
            # уголки вниз — это не улыбка, даже если рот стал шире
            self.smile_score = 0.0
        else:
            self.smile_score = max(width_gain, lift_gain * 2.0)
        self.brow_score = m.brow_height - self.baseline.brow
        self.rel_yaw = m.yaw - self.baseline.yaw
        self.rel_pitch = m.pitch - self.baseline.pitch
        events.extend(self.head.update(self.rel_yaw, self.rel_pitch, now))

        # --- зрачок: куда смотрит человек (нужны точки радужки) ----------- #
        self.gaze_valid = bool(m.gaze_valid)
        self.head_ok = bool(getattr(m, "head_ok", False))
        self.head_yaw = float(getattr(m, "head_yaw", 0.0))
        self.head_pitch = float(getattr(m, "head_pitch", 0.0))
        self.head_roll = float(getattr(m, "head_roll", 0.0))
        if m.gaze_valid:
            a = max(0.05, min(1.0, self.cfg.gaze_smoothing))
            self.gaze_x = a * m.gaze_x + (1.0 - a) * self.gaze_x
            self.gaze_y = a * m.gaze_y + (1.0 - a) * self.gaze_y
            # компенсированный взгляд сглаживаем отдельно: он и идёт в мышку
            self.gaze_u = a * m.gaze_u + (1.0 - a) * self.gaze_u
            self.gaze_v = a * m.gaze_v + (1.0 - a) * self.gaze_v
            # «ноль» взгляда подстраивается только когда зрачок рядом с ним:
            # так уходит медленный дрейф, но намеренный взгляд в сторону не
            # «съедается» (иначе курсор замирал через пару секунд).
            dz_x = self.cfg.gaze_deadzone * 0.8
            dz_y = self.cfg.gaze_deadzone_y * 0.8
            if (abs(self.gaze_x - self.baseline.gaze_x) < dz_x
                    and abs(self.gaze_y - self.baseline.gaze_y) < dz_y):
                drift = max(0.001, min(0.2, self.cfg.gaze_neutral_drift))
                self.baseline.gaze_x += drift * (self.gaze_x - self.baseline.gaze_x)
                self.baseline.gaze_y += drift * (self.gaze_y - self.baseline.gaze_y)

        # --- моргание и подмигивание ------------------------------------ #
        # Считаем «эпизоды» закрытия, а не отдельные кадры:
        #  * оба глаза закрылись и открылись вместе — моргание (два подряд —
        #    двойное моргание);
        #  * закрылся ровно один глаз, а второй ЗА ВСЁ ВРЕМЯ ни разу не
        #    закрылся — подмигивание. Если во время «подмигивания» второй глаз
        #    тоже моргнул, это обычное моргание, а не подмигивание.
        #  * держим глаза закрытыми дольше eyes_closed_cap_s — не считаем это
        #    ни морганием, ни подмигиванием, пока глаза не откроются.
        self.left.update(m.ear_left, now)
        self.right.update(m.ear_right, now)
        closed = {"left": self.left.closed, "right": self.right.closed}
        both_open = not closed["left"] and not closed["right"]
        both_closed = closed["left"] and closed["right"]
        cap = self.cfg.eyes_closed_cap_s

        if both_closed:
            if self._both_start is None:
                self._both_start = now
            if now - self._both_start >= cap:
                if not self._closed_too_long:
                    # держим закрытыми слишком долго: дальше не считаем ничего,
                    # пока глаза не откроются (и не копим «моргание»)
                    self._closed_too_long = True
                    self._last_blink_t = None
            # Оба закрыты долго — «зажмурился», это не моргание. Одно событие
            # на эпизод, чтобы не сыпать им каждые полсекунды.
            if (not self._closed_too_long and not self._closed_event_sent
                    and now - self._both_start > self.cfg.blink_max_s):
                self._closed_event_sent = True
                events.append(Event("eyes_closed_hold", label="глаза закрыты"))
        elif self._both_start is not None:
            dur = now - self._both_start
            self._both_start = None
            too_long = self._closed_too_long
            if both_open:
                self._closed_too_long = False
            if (not too_long and not self._closed_too_long
                    and self.cfg.blink_min_s <= dur <= self.cfg.blink_max_s):
                # моргание обоими глазами: одно событие на эпизод
                if (self._last_blink_t is not None
                        and (now - self._last_blink_t) <= self.cfg.double_blink_window_s):
                    if self.cooldown.try_fire("double_blink", now):
                        events.append(Event("double_blink", label="двойное моргание"))
                    self._last_blink_t = None
                else:
                    self._last_blink_t = now

        for side, other in (("left", "right"), ("right", "left")):
            state = self._eye[side]
            if closed[side]:
                if state["start"] is None:
                    state["start"] = now
                    state["other_closed"] = False
                if closed[other]:
                    # второй глаз тоже закрыт — подмигивания тут быть не может
                    state["other_closed"] = True
            elif state["start"] is not None:
                dur = now - state["start"]
                other_closed = state["other_closed"]
                state["start"] = None
                state["other_closed"] = False
                if (not other_closed and not self._closed_too_long
                        and self.cfg.wink_min_s <= dur <= cap):
                    events.append(Event(f"wink_{side}", label=f"wink {side}"))

        if both_open:
            self._closed_too_long = False
            self._closed_event_sent = False

        # --- улыбка ---------------------------------------------------- #
        smile_now = self.smile_score > self.cfg.smile_delta * 1.2
        if self.smile_hold.update(smile_now, now):
            if self.smile_cooldown.try_fire("smile", now):
                events.append(Event("smile_hold", label="улыбка"))

        # --- брови ------------------------------------------------------ #
        # брови поднимаются и от разговора, поэтому порог выше и держать дольше
        brow_now = self.brow_score > self.cfg.brow_delta * 1.5
        if self.brow_hold.update(brow_now, now):
            if self.brow_cooldown.try_fire("brow", now):
                events.append(Event("brow_hold", label="брови"))

        return events

    # ------------------------------------------------------------------ #
    def gaze_step(self, dt: float) -> "tuple[float, float]":
        """Смещение курсора за ``dt`` секунд по положению зрачка.

        Как и у «мыши головой», это скорость, а не абсолютная позиция: пока
        зрачок отведён от нейтрали дальше мёртвой зоны, курсор едет; вернулся
        в центр — курсор встал. Так не нужно попадать зрачком в пиксель.
        """
        if not self.gaze_valid:
            return (0.0, 0.0)

        def excess(value: float, dz: float) -> float:
            if value > dz:
                return value - dz
            if value < -dz:
                return value + dz
            return 0.0

        # по горизонтали зрачок ходит шире, по вертикали — уже, поэтому
        # зона и «полный размах» у осей свои, иначе вверх-вниз не двигалось
        ex = excess(self.gaze_x - self.baseline.gaze_x, self.cfg.gaze_deadzone)
        ey = excess(self.gaze_y - self.baseline.gaze_y, self.cfg.gaze_deadzone_y)
        if not ex and not ey:
            return (0.0, 0.0)
        fx = max(self.cfg.gaze_full_scale_x, 1e-3)
        fy = max(self.cfg.gaze_full_scale_y, 1e-3)
        nx = max(-1.5, min(1.5, ex / fx))
        ny = max(-1.5, min(1.5, ey / fy))
        gain = self.cfg.gaze_speed_px_s
        return (nx * gain * dt, ny * gain * dt)

    # ------------------------------------------------------------------ #
    def head_step(self, dt: float) -> "tuple[float, float]":
        """Смещение курсора в пикселях за ``dt`` секунд по наклону головы.

        Скорость пропорциональна углу *сверх мёртвой зоны*: в нейтрали курсор
        стоит, а когда голова возвращается обратно, он не едет назад — новое
        движение начнётся только со следующего наклона за предел зоны.
        """
        dz = self.cfg.head_deadzone_deg

        def excess(angle: float) -> float:
            if angle > dz:
                return angle - dz
            if angle < -dz:
                return angle + dz
            return 0.0

        ex = excess(self.rel_yaw)
        ey = excess(self.rel_pitch)
        if not ex and not ey:
            return (0.0, 0.0)
        return (ex * self.cfg.head_gain_x * dt, ey * self.cfg.head_gain_y * dt)
