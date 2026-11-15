"""Распознавание жестов кисти и конечный автомат событий.

Слой полностью независим от камеры: на вход — 21 точка кисти, на выход —
список событий (движение указателя, щипок, прокрутка и т.д.).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import HandConfig
from .filters import Cooldown, HoldTimer, StabilityGate, clamp
from .landmarks import (
    FINGERS,
    INDEX_MCP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_TIP,
    PINKY_MCP,
    RING_TIP,
    THUMB_MCP,
    THUMB_TIP,
    WRIST,
    Hand,
    angle_deg,
    distance,
    safe_div,
)


class Pose(str, Enum):
    NONE = "none"
    OPEN_PALM = "open_palm"
    FIST = "fist"
    PINCH = "pinch"
    MIDDLE_PINCH = "middle_pinch"
    RING_PINCH = "ring_pinch"
    POINT = "point"
    PEACE = "peace"
    THREE = "three"
    THUMB_UP = "thumb_up"
    THUMB_DOWN = "thumb_down"
    OK = "ok"
    ROCK = "rock"


class HandSide(str, Enum):
    """Какая сторона кисти смотрит в камеру."""

    PALM = "palm"      # ладонь
    BACK = "back"      # тыльная сторона
    UNKNOWN = "unknown"  # ещё не откалибровано или рука «ребром»


SIDE_TITLES_RU = {
    HandSide.PALM: "ладонь",
    HandSide.BACK: "тыл",
    HandSide.UNKNOWN: "не определена",
}

POSE_TITLES_RU = {
    Pose.NONE: "—",
    Pose.OPEN_PALM: "ладонь",
    Pose.FIST: "кулак",
    Pose.PINCH: "щипок",
    Pose.MIDDLE_PINCH: "щипок ср.",
    Pose.RING_PINCH: "щипок без.",
    Pose.POINT: "указательный",
    Pose.PEACE: "два пальца",
    Pose.THREE: "три пальца",
    Pose.THUMB_UP: "большой палец",
    Pose.THUMB_DOWN: "большой вниз",
    Pose.OK: "ОК",
    Pose.ROCK: "коза",
}


@dataclass
class Event:
    """Событие распознавания. ``value`` — полезная нагрузка, ``label`` — для лога."""

    kind: str
    value: object = None
    label: str = ""

    def __repr__(self) -> str:  # для отладки и тестов
        if self.value is None:
            return f"Event({self.kind})"
        return f"Event({self.kind}, {self.value})"


@dataclass
class HandFeatures:
    """Числовые признаки кисти (всё нормировано на размер ладони)."""

    palm_size: float
    palm_center: np.ndarray
    pointer: np.ndarray
    extension: Dict[str, float]
    pinch: float
    pinch_middle: float
    pinch_ring: float
    thumb_dy: float = 0.0      # насколько кончик большого пальца выше основания
    thumb_spread: float = 0.0  # насколько большой палец отставлен от ладони      # насколько кончик большого пальца выше основания
    valid: bool = True
    fast_motion: float = 0.0

    @property
    def extended(self) -> Dict[str, bool]:
        return {name: val > 0.5 for name, val in self.extension.items()}

    @property
    def n_extended(self) -> int:
        return sum(1 for v in self.extended.values() if v)


def _finger_extension(hand: Hand, name: str) -> float:
    """0 — палец сжат в кулак, 1 — выпрямлен.

    Комбинация двух инвариантных к повороту признаков:
    * «прямизна» — угол в проксимальном суставе (у согнутого он мал);
    * «вытянутость» — во сколько раз кончик дальше от запястья, чем основание.
    """
    mcp, pip, dip, tip = FINGERS[name]
    base = THUMB_MCP if name == "thumb" else mcp
    straight = clamp((angle_deg(hand.xy(mcp), hand.xy(pip), hand.xy(tip)) - 55.0) / 95.0, 0.0, 1.0)
    stretch = safe_div(distance(hand.xy(tip), hand.xy(WRIST)), distance(hand.xy(base), hand.xy(WRIST)), 1.0)
    stretched = clamp((stretch - 0.95) / 0.50, 0.0, 1.0)
    return 0.55 * straight + 0.45 * stretched


def hand_normal_score(hand: Hand) -> float:
    """Куда смотрит ладонь: +1 — в камеру, −1 — тыльной стороной.

    Берём нормаль плоскости ладони (запястье, основания указательного, среднего
    и мизинца) по трём координатам: MediaPipe отдаёт z, а он честно меняет знак,
    когда кисть разворачивают. Знак нормали зависит ещё и от того, правая это
    рука или левая, поэтому «ладонь» означает «сторона, которую пользователь
    один раз показал при калибровке» (см. :class:`SideEstimator`).
    """
    pts = np.asarray(hand.points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 21 or pts.shape[1] < 3:
        return 0.0
    wrist = pts[WRIST]
    index = pts[INDEX_MCP]
    middle = pts[MIDDLE_MCP]
    pinky = pts[PINKY_MCP]
    normal = np.cross(index - wrist, pinky - wrist) + np.cross(middle - index, pinky - index)
    norm = float(np.linalg.norm(normal))
    if norm < 1e-12:
        return 0.0
    return float(normal[2] / norm)


class SideEstimator:
    """Сглаженная и с гистерезисом оценка «ладонь или тыл».

    Одна калибровка: пользователь один раз показывает ладонь (кнопка в
    настройках или клавиша K) — запоминается знак нормали. Дальше всё, у чего
    знак совпал, считается ладонью, а противоположный — тылом. Если рука
    повёрнута ребром (нормаль почти нулевая), сторона не меняется — так жест не
    «переобувается» на развороте.
    """

    def __init__(self, cfg: HandConfig) -> None:
        self.cfg = cfg
        self.side = HandSide.UNKNOWN
        self._median = Median3()
        self._candidate = HandSide.UNKNOWN
        self._count = 0
        self.last_score = 0.0

    # ---------------------------------------------------------------- #
    def reset(self) -> None:
        self.side = HandSide.UNKNOWN
        self._candidate = HandSide.UNKNOWN
        self._count = 0
        self._median.reset()
        self.last_score = 0.0

    @property
    def calibrated(self) -> bool:
        return abs(float(getattr(self.cfg, "side_reference", 0.0))) > 1e-6

    def calibrate(self) -> bool:
        """Запомнить текущую нормаль как «ладонь»."""
        if abs(self.last_score) < float(getattr(self.cfg, "side_min_score", 0.35)):
            return False
        self.cfg.side_reference = 1.0 if self.last_score > 0 else -1.0
        self.side = HandSide.PALM
        return True

    def flip(self) -> None:
        ref = float(getattr(self.cfg, "side_reference", 0.0))
        self.cfg.side_reference = -ref if abs(ref) > 1e-6 else ref
        if self.side is HandSide.PALM:
            self.side = HandSide.BACK
        elif self.side is HandSide.BACK:
            self.side = HandSide.PALM

    # ---------------------------------------------------------------- #
    def update(self, hand: Optional[Hand]) -> HandSide:
        if hand is None:
            self.reset()
            return self.side

        score = self._median.update(hand_normal_score(hand))
        self.last_score = score
        reference = float(getattr(self.cfg, "side_reference", 0.0))
        min_score = float(getattr(self.cfg, "side_min_score", 0.35))

        candidate = HandSide.UNKNOWN
        if abs(reference) > 1e-6 and abs(score) >= min_score:
            same = (score > 0) == (reference > 0)
            candidate = HandSide.PALM if same else HandSide.BACK

        if candidate is HandSide.UNKNOWN:
            # рука «ребром» или калибровки нет — оставляем как было
            self._candidate = HandSide.UNKNOWN
            self._count = 0
            return self.side

        if candidate is self._candidate:
            self._count += 1
        else:
            self._candidate = candidate
            self._count = 1

        need = max(int(getattr(self.cfg, "side_min_frames", 3)), 1)
        if self._count >= need:
            self.side = candidate
        return self.side


def analyze_hand(hand: Hand, pointer_source: str = "auto") -> HandFeatures:
    """Считает признаки кисти. Не бросает исключений — лучше отдать valid=False."""
    palm = hand.palm_size
    if palm < 1e-4:
        return HandFeatures(0.0, np.zeros(2), np.zeros(2), {}, 1.0, 1.0, 1.0, valid=False)

    ext = {name: _finger_extension(hand, name) for name in FINGERS}
    thumb_tip = hand.xy(THUMB_TIP)

    pinch = distance(thumb_tip, hand.xy(INDEX_TIP)) / palm
    pinch_middle = distance(thumb_tip, hand.xy(MIDDLE_TIP)) / palm
    pinch_ring = distance(thumb_tip, hand.xy(RING_TIP)) / palm

    palm_center = hand.palm_center
    index_tip = hand.xy(INDEX_TIP)
    if pointer_source == "index_tip":
        pointer = index_tip
    elif pointer_source == "palm":
        pointer = palm_center
    else:  # auto: указываем кончиком указательного, раскрытой ладонью — центром
        pointer = index_tip if ext["index"] > 0.5 else palm_center

    thumb_dy = float((thumb_tip[1] - hand.xy(THUMB_MCP)[1]) / palm)
    thumb_spread = distance(thumb_tip, hand.xy(INDEX_MCP)) / palm

    return HandFeatures(
        palm_size=palm,
        palm_center=palm_center,
        pointer=pointer,
        extension=ext,
        pinch=pinch,
        pinch_middle=pinch_middle,
        pinch_ring=pinch_ring,
        thumb_dy=thumb_dy,
        thumb_spread=thumb_spread,
        valid=True,
    )


# какие пальцы выпрямлены в каждой «счётной» позе — для гистерезиса
POSE_FINGERS: Dict[Pose, Tuple[str, ...]] = {
    Pose.FIST: (),
    Pose.OPEN_PALM: ("index", "middle", "ring", "pinky"),
    Pose.POINT: ("index",),
    Pose.PEACE: ("index", "middle"),
    Pose.THREE: ("index", "middle", "ring"),
    Pose.ROCK: ("index", "pinky"),
}


def _marginal(value: float, lo: float = 0.40, hi: float = 0.72) -> bool:
    """Палец «на границе» выпрямлен/согнут — по нему нельзя менять жест."""
    return lo <= value <= hi


class Median3:
    """Медиана трёх последних значений: гасит одиночные выбросы нейросети.

    Настоящее изменение проскакивает со второго кадра (задержка ~30 мс), а
    «моргнувший» на один кадр щипок не превращается во второй щипок.
    """

    def __init__(self) -> None:
        self.values: List[float] = []

    def reset(self) -> None:
        self.values.clear()

    def update(self, value: float) -> float:
        self.values.append(float(value))
        if len(self.values) > 3:
            del self.values[0]
        return float(np.median(self.values))


def _classify_raw(f: HandFeatures, cfg: HandConfig) -> Pose:
    """Статический жест по признакам кисти, без учёта прошлого кадра."""
    if not f.valid:
        return Pose.NONE
    e = f.extended
    n = f.n_extended

    # 1. Щипки — раньше счёта пальцев, иначе щипок не отличить от «указательного».
    if f.pinch < cfg.pinch_ratio and e["index"] and e["thumb"]:
        return Pose.PINCH
    if f.pinch_middle < cfg.pinch_ratio and e["middle"] and e["thumb"] and not e["index"]:
        return Pose.MIDDLE_PINCH
    if f.pinch_ring < cfg.pinch_ratio and e["ring"] and e["thumb"] and not e["index"] and not e["middle"]:
        return Pose.RING_PINCH

    # 1б. «ОК»: колечко из большого и указательного, остальные три выпрямлены.
    if (f.pinch < 0.40 and e["middle"] and e["ring"] and e["pinky"]
            and not e["index"]):
        return Pose.OK

    # 1в. «Коза»: указательный и мизинец вверх, средний и безымянный сжаты.
    if e["index"] and e["pinky"] and not e["middle"] and not e["ring"]:
        return Pose.ROCK

    # 2. Кулак / раскрытая ладонь.
    if n == 0:
        return Pose.FIST
    if all(e[k] for k in ("index", "middle", "ring", "pinky")):
        return Pose.OPEN_PALM

    # 3. Счёт выпрямленных пальцев (большой не учитываем — он почти всегда «полусогнут»).
    fingers = [e["index"], e["middle"], e["ring"], e["pinky"]]
    count = sum(fingers)
    if count == 1 and fingers[0]:
        return Pose.POINT
    if count == 2 and fingers[0] and fingers[1]:
        return Pose.PEACE
    if count == 3 and fingers[0] and fingers[1] and fingers[2]:
        return Pose.THREE
    if count == 0 and e["thumb"] and f.thumb_spread > 0.60:
        # Большой палец вверх/вниз — по направлению от основания к кончику.
        # ``thumb_spread`` отсекает кулак, в котором большой палец просто лежит
        # вдоль указательного, а не выставлен в сторону.
        return Pose.THUMB_UP if f.thumb_dy < -0.15 else Pose.THUMB_DOWN
    return Pose.NONE


def classify_pose(f: HandFeatures, cfg: HandConfig, prev: Optional[Pose] = None) -> Pose:
    """Жест с гистерезисом: «моргание» одного пальца не меняет жест.

    Если жест отличается от прошлого (``prev``) только состоянием пальца,
    который сейчас «на границе» выпрямлен/согнут, остаётся прошлый жест.
    """
    pose = _classify_raw(f, cfg)
    if prev is None or prev is pose or not f.valid:
        return pose
    a = POSE_FINGERS.get(prev)
    b = POSE_FINGERS.get(pose)
    if a is None or b is None:
        return pose
    for finger in set(a) ^ set(b):
        if _marginal(float(f.extension.get(finger, 1.0))):
            return prev
    return pose


def recognize_pose(hand: Optional[Hand], cfg: HandConfig) -> Pose:
    """Удобная обёртка: точки -> жест, без автомата состояний."""
    if hand is None:
        return Pose.NONE
    return classify_pose(analyze_hand(hand, cfg.pointer_source), cfg)


def analyze_with_pose(hand: Hand, cfg: HandConfig):
    feats = analyze_hand(hand, cfg.pointer_source)
    return feats, classify_pose(feats, cfg)


class HandFSM:
    """Превращает поток признаков в поток событий (клик, драг, прокрутка, пауза)."""

    def __init__(self, cfg: HandConfig) -> None:
        self.cfg = cfg
        self.pose_gate = StabilityGate(cfg.pose_stable_frames)
        self.cooldown = Cooldown(cfg.click_cooldown_s)
        self.open_palm_hold = HoldTimer(cfg.open_palm_hold_s)
        # отдельный «замок» на паузу: случайно мигнувшая ладонь не должна
        # переключать режим чаще, чем раз в pause_cooldown_s
        self.pause_cooldown = Cooldown(getattr(cfg, "pause_cooldown_s", 2.5))
        self._pinching = False
        self._pinch_since = 0.0
        self._dragging = False
        self._middle_pinching = False
        self._middle_since = 0.0
        self._fist_anchor_y: Optional[float] = None
        self._scroll_accum = 0.0
        self._prev_pointer: Optional[np.ndarray] = None
        self._last_pose = Pose.NONE
        self._thumb_fired = False
        self.approaching = False   # пальцы идут на смыкание: курсор заморожен
        self._approach_count = 0
        self._pose_once: dict = {}
        self.side_est = SideEstimator(cfg)
        self._med_pinch = Median3()
        self._med_middle = Median3()
        self._med_ring = Median3()
        self.aim_point: Optional[Tuple[float, float]] = None

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self.pose_gate.reset()
        self.open_palm_hold.reset()
        self._pinching = False
        self._dragging = False
        self._middle_pinching = False
        self._fist_anchor_y = None
        self._scroll_accum = 0.0
        self._prev_pointer = None
        self._last_pose = Pose.NONE
        self._thumb_fired = False
        self.side_est.reset()
        self._med_pinch.reset()
        self._med_middle.reset()
        self._med_ring.reset()

    @property
    def side(self) -> HandSide:
        """Какая сторона кисти смотрит в камеру (ладонь / тыл / не определена)."""
        return self.side_est.side

    @property
    def pinching(self) -> bool:
        return self._pinching

    @property
    def dragging(self) -> bool:
        return self._dragging

    # ------------------------------------------------------------------ #
    def update(self, hand: Optional[Hand], now: float) -> List[Event]:
        events: List[Event] = []
        if hand is None:
            if self._dragging:
                events.append(Event("drag_end", label="рука потеряна"))
                self._dragging = False
            self._pinching = False
            self._middle_pinching = False
            self._fist_anchor_y = None
            self.pose_gate.update(None)
            self.open_palm_hold.reset()
            self._prev_pointer = None
            return events

        f = analyze_hand(hand, self.cfg.pointer_source)
        if not f.valid:
            return events

        # Скорость указателя — для «рывков» и для индикатора в оверлее.
        if self._prev_pointer is not None:
            f.fast_motion = float(np.linalg.norm(f.pointer - self._prev_pointer))
        self._prev_pointer = f.pointer

        # Какая сторона кисти смотрит в камеру (ладонь / тыл) — с гистерезисом.
        self.side_est.update(hand)
        side_back = self.side is HandSide.BACK and bool(
            getattr(self.cfg, "side_actions", True)
        )

        # Антидребезг: медиана трёх кадров гасит одиночные «схлопывания» пальцев.
        f.pinch = self._med_pinch.update(f.pinch)
        f.pinch_middle = self._med_middle.update(f.pinch_middle)
        f.pinch_ring = self._med_ring.update(f.pinch_ring)

        pose = classify_pose(f, self.cfg, prev=self._last_pose)
        stable = self.pose_gate.update(pose.value)

        # ---------------- щипок указательным: клик / перетаскивание -------- #
        if self._pinching:
            if f.pinch > self.cfg.pinch_release_ratio:
                self._pinching = False
                if self._dragging:
                    self._dragging = False
                    events.append(Event("drag_end", label="отпустил"))
                elif (now - self._pinch_since) < getattr(self.cfg, "pinch_min_s", 0.0):
                    # щипок мигнул на 1–2 кадра — это дрожание точек, а не клик
                    pass
                elif self.cooldown.try_fire("pinch", now):
                    events.append(Event("pinch_release", label="левый клик"))
            else:
                if not self._dragging and (now - self._pinch_since) >= self.cfg.drag_delay_s:
                    self._dragging = True
                    events.append(Event("drag_start", label="перетаскивание"))
                if self._dragging:
                    events.append(Event("pointer", value=tuple(f.pointer)))
                else:
                    events.append(Event("pointer_freeze", label="щипок"))
        else:
            started = pose == Pose.PINCH and f.pinch < self.cfg.pinch_ratio
            if started:
                self._pinching = True
                self._pinch_since = now
                events.append(Event("pointer_freeze", label="щипок начат"))

        # ---------------- щипок средним: правый клик ---------------------- #
        if not self._pinching:
            if self._middle_pinching:
                if f.pinch_middle > self.cfg.pinch_release_ratio:
                    self._middle_pinching = False
                    if self.cooldown.try_fire("middle", now):
                        events.append(Event("middle_pinch_release", label="правый клик"))
            elif pose == Pose.MIDDLE_PINCH:
                self._middle_pinching = True
                self._middle_since = now
                events.append(Event("pointer_freeze", label="щипок средним"))

        # ---------------- прокрутка кулаком ------------------------------- #
        if pose == Pose.FIST and not self._pinching:
            y = float(f.palm_center[1])
            if self._fist_anchor_y is None:
                self._fist_anchor_y = y
            dy = self._fist_anchor_y - y
            self._fist_anchor_y = y
            if abs(dy) > self.cfg.fist_scroll_deadzone:
                self._scroll_accum += dy * self.cfg.fist_scroll_gain
                ticks = int(self._scroll_accum)
                if ticks:
                    self._scroll_accum -= ticks
                    events.append(Event("scroll", value=ticks, label="прокрутка"))
        else:
            self._fist_anchor_y = None
            self._scroll_accum = 0.0

        # ---------------- раскрытая ладонь: пауза ------------------------- #
        # Три условия разом, иначе пауза срабатывала от любого движения:
        # ладонь открыта и «устоялась», рука почти не двигается, ладонь
        # достаточно крупная в кадре (человек не махнул рукой вдалеке).
        still = f.fast_motion < self.cfg.pause_max_motion
        near = float(hand.palm_size) >= getattr(self.cfg, "pause_min_palm", 0.0)
        open_and_settled = (
            pose == Pose.OPEN_PALM
            and stable == Pose.OPEN_PALM.value
            and still
            and near
            and self.pause_cooldown.ready("open_palm", now)   # не «тратим» жест впустую
        )
        fired = self.open_palm_hold.update(open_and_settled, now)
        if fired and self.pause_cooldown.try_fire("open_palm", now):
            events.append(Event("open_palm_hold", label="ладонь"))
        if pose != Pose.OPEN_PALM:
            self.open_palm_hold.reset()

        # ------------- стабильные позы-команды: ОК, коза, три пальца ------ #
        STABLE_EVENTS = {
            Pose.OK: "ok_sign",
            Pose.ROCK: "rock_sign",
            Pose.THREE: "three_fingers",
        }
        for pose_value, kind in STABLE_EVENTS.items():
            if stable == pose_value.value:
                # тыльной стороной кисти те же позы дают другие команды
                event_kind = f"{kind}_back" if side_back else kind
                if not self._pose_once.get(kind) and self.cooldown.try_fire(kind, now):
                    self._pose_once[kind] = True
                    label = pose_value.value
                    if side_back:
                        label += " (тыл)"
                    events.append(Event(event_kind, label=label))
            else:
                self._pose_once[kind] = False

        # ---------------- большой палец вверх ----------------------------- #
        if stable == Pose.THUMB_UP.value:
            if not self._thumb_fired and self.cooldown.try_fire("thumb_up", now):
                self._thumb_fired = True
                events.append(Event("thumb_up", label="большой палец"))
        else:
            self._thumb_fired = False

        # ---------------- перемещение указателя --------------------------- #
        # «Прицел»: как только большой и указательный пошли навстречу друг
        # другу, курсор замирает на последней точке. Раньше он уезжал вместе
        # с пальцем, и клик приходился не туда, куда целились.
        approaching_now = f.pinch < self.cfg.pinch_approach_ratio
        self._approach_count = self._approach_count + 1 if approaching_now else 0
        # одного кадра мало: нейросеть иногда «моргает» на движении рукой
        self.approaching = self._approach_count >= 2
        if self.approaching:
            self.aim_point = tuple(f.pointer)
        frozen = self._pinching and not self._dragging
        if self.approaching:
            events.append(Event("pointer_freeze", label="прицел"))
        elif not frozen and not self._middle_pinching and pose != Pose.FIST:
            events.append(Event("pointer", value=tuple(f.pointer)))
            self.aim_point = tuple(f.pointer)
        elif self._middle_pinching:
            events.append(Event("pointer_freeze", label="щипок средним"))
        elif pose == Pose.FIST:
            events.append(Event("pointer_freeze", label="кулак"))

        self._last_pose = pose
        setattr(self, "last_features", f)
        return events


# --------------------------------------------------------------------------- #
#  Синтетическая кисть — для тестов и демо-режима без камеры
# --------------------------------------------------------------------------- #
_CANON: Dict[str, Tuple[Tuple[float, float], ...]] = {
    # (x, y) в единицах ладони, y вверх — отрицательный; запястье в (0, 0)
    "thumb": ((0.30, -0.42), (0.44, -0.62), (0.55, -0.80), (0.62, -0.96)),
    "index": ((-0.20, -0.95), (-0.25, -1.22), (-0.27, -1.36), (-0.29, -1.50)),
    "middle": ((-0.01, -1.00), (-0.01, -1.30), (-0.01, -1.46), (-0.01, -1.62)),
    "ring": ((0.17, -0.95), (0.21, -1.21), (0.23, -1.35), (0.24, -1.47)),
    "pinky": ((0.32, -0.84), (0.37, -1.03), (0.39, -1.14), (0.40, -1.24)),
}
_MCP_WRIST = {"thumb": 1, "index": 5, "middle": 9, "ring": 13, "pinky": 17}


def synthetic_hand(
    center: Tuple[float, float] = (0.5, 0.55),
    scale: float = 0.22,
    rotation_deg: float = 0.0,
    curl: Optional[Dict[str, float]] = None,
    pinch_index: bool = False,
    pinch_middle: bool = False,
    back: bool = False,
) -> Hand:
    """Строит правдоподобные 21 точку кисти по «степени сжатия» каждого пальца.

    ``curl`` — 0 (палец выпрямлен) .. 1 (полностью сжат). Полезно для тестов:
    поза строится детерминированно, без камеры.
    """
    curl = curl or {}
    pts = np.zeros((21, 2), dtype=np.float64)
    rot = math.radians(rotation_deg)

    def place(x: float, y: float) -> np.ndarray:
        c, s = math.cos(rot), math.sin(rot)
        v = np.array([x * c - y * s, x * s + y * c])
        return np.array([center[0] + v[0] * scale, center[1] + v[1] * scale])

    pts[0] = place(0.0, 0.0)
    chain_ids = {
        "thumb": (1, 2, 3, 4),
        "index": (5, 6, 7, 8),
        "middle": (9, 10, 11, 12),
        "ring": (13, 14, 15, 16),
        "pinky": (17, 18, 19, 20),
    }
    for name, ids in chain_ids.items():
        base = np.array(_CANON[name][0])
        c = float(np.clip(curl.get(name, 0.0), 0.0, 1.0))
        if name == "thumb":
            bend_per_joint = 1.05 * c
            foreshorten = 1.0 - 0.45 * c
        else:
            bend_per_joint = 1.35 * c
            foreshorten = 1.0 - 0.50 * c

        # Первая точка — основание пальца (MCP), взятое из канона как есть.
        pts[ids[0]] = place(base[0], base[1])
        direction = base - np.array([0.0, 0.0])  # от запястья наружу
        direction = direction / max(np.linalg.norm(direction), 1e-9)
        pos = base.copy()
        theta = 0.0
        for k in range(3):
            nxt = np.array(_CANON[name][k + 1])
            seg_len = float(np.linalg.norm(nxt - np.array(_CANON[name][k])))
            theta += bend_per_joint
            angle = theta + math.radians(rotation_deg)
            d = np.array([
                direction[0] * math.cos(angle) - direction[1] * math.sin(angle),
                direction[0] * math.sin(angle) + direction[1] * math.cos(angle),
            ])
            pos = pos + d * seg_len * foreshorten
            pts[ids[k + 1]] = place(pos[0], pos[1])

    if pinch_index:
        pts[4] = pts[8] + np.array([0.0, -0.004])
        pts[3] = pts[4] + (pts[3] - pts[4]) * 0.55
    if pinch_middle:
        pts[4] = pts[12] + np.array([0.0, -0.004])
        pts[3] = pts[4] + (pts[3] - pts[4]) * 0.55
    if back:
        # кисть развёрнута тыльной стороной: картинка зеркалится, нормаль
        # ладони меняет знак — ровно то, что видит нейросеть в кадре
        pts[:, 0] = 2.0 * center[0] - pts[:, 0]
    return Hand(np.hstack([pts, np.zeros((21, 1))]))


# --------------------------------------------------------------------------- #
#  Управление двумя руками
# --------------------------------------------------------------------------- #
TWO_HAND_MODES = ("off", "zoom", "scroll")


class TwoHandFSM:
    """Жесты двумя руками одновременно.

    ``zoom``  — обе ладони открыты: развели руки — приблизили (Ctrl+колесо),
                свели — отдалили. Как «щипок» двумя пальцами на телефоне, но
                без экрана.
    ``scroll`` — оба кулака: двигаем руки вверх/вниз — прокрутка (точнее, чем
                одним кулаком, потому что случайно сжать один кулак легче).
    """

    def __init__(self, cfg: HandConfig) -> None:
        self.cfg = cfg
        self.mode = (getattr(cfg, "two_hand", "off") or "off").lower()
        self.hint = ""
        self.active = False
        self._anchor: Optional[float] = None
        self._accum = 0.0

    def reset(self) -> None:
        self._anchor = None
        self._accum = 0.0
        self.active = False
        self.hint = ""

    def update(self, hands: List[Hand], now: float) -> List[Event]:
        if self.mode not in ("zoom", "scroll") or len(hands) < 2:
            self.reset()
            return []
        first, second = hands[0], hands[1]
        fa = analyze_hand(first, self.cfg.pointer_source)
        fb = analyze_hand(second, self.cfg.pointer_source)
        if not (fa.valid and fb.valid):
            self.reset()
            return []
        want = Pose.OPEN_PALM if self.mode == "zoom" else Pose.FIST
        if classify_pose(fa, self.cfg) != want or classify_pose(fb, self.cfg) != want:
            self.reset()
            return []

        if self.mode == "zoom":
            value = float(np.linalg.norm(fa.palm_center - fb.palm_center))
            gain = self.cfg.two_hand_zoom_gain
            self.hint = "масштаб: разведите или сведите руки"
        else:
            value = float((fa.palm_center[1] + fb.palm_center[1]) / 2.0)
            gain = self.cfg.two_hand_scroll_gain
            self.hint = "прокрутка двумя кулаками"

        if self._anchor is None:
            self._anchor = value
            self.active = True
            return []
        delta = value - self._anchor
        if abs(delta) < self.cfg.two_hand_deadzone:
            return []
        self._anchor = value
        self._accum += delta * gain
        ticks = int(self._accum)
        if not ticks:
            return []
        self._accum -= ticks
        if self.mode == "scroll":
            return [Event("scroll", value=-ticks, label="прокрутка двумя руками")]
        return [Event("zoom", value=ticks, label="масштаб")]
