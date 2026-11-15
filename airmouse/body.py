"""Тело целиком: 33 точки MediaPipe Pose → поза, наклоны и упражнения.

Зачем это отдельно от кисти. Кисть отвечает за «мелкую моторику» (курсор,
клики), а тело — за «крупную»: приседания, наклоны, руки вверх. Это другой
масштаб движения и другие ошибки, поэтому и модуль свой.

Что здесь честно, а что нет:

* по одной камере **нет глубины** — поза восстанавливается по видимым точкам,
  человек в кадре должен быть **один** (MediaPipe Pose не различает людей);
* угол в колене по камере спереди сильно искажается (нога смотрит в объектив),
  поэтому глубина приседа считается по **двум** сигналам сразу: угол в колене
  (работает сбоку) и «насколько таз просел» относительно роста (работает
  спереди). Берём максимум — так упражнение ловится из любого ракурса;
* точность углов у BlazePose по данным валидаций — средняя ошибка около 7°
  (MAE), ICC ≈ 0.77 для приседа (Yue et al., 2026,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC13730411). Поэтому пороги широкие,
  а счёт повторов — с гистерезисом и минимальной длительностью, чтобы не
  считать дребезг точек за повторение.

Модуль чистый: только numpy, поэтому проверяется синтетическим телом.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .config import BodyConfig
from .filters import HoldTimer, OneEuroFilter, clamp
from .gestures import Event, angle_deg


class B:
    """Индексы точек MediaPipe Pose (33 точки, порядок BlazePose)."""

    NOSE = 0
    L_EYE_INNER = 1
    L_EYE = 2
    L_EYE_OUTER = 3
    R_EYE_INNER = 4
    R_EYE = 5
    R_EYE_OUTER = 6
    L_EAR = 7
    R_EAR = 8
    MOUTH_L = 9
    MOUTH_R = 10
    L_SHOULDER = 11
    R_SHOULDER = 12
    L_ELBOW = 13
    R_ELBOW = 14
    L_WRIST = 15
    R_WRIST = 16
    L_PINKY = 17
    R_PINKY = 18
    L_INDEX = 19
    R_INDEX = 20
    L_THUMB = 21
    R_THUMB = 22
    L_HIP = 23
    R_HIP = 24
    L_KNEE = 25
    R_KNEE = 26
    L_ANKLE = 27
    R_ANKLE = 28
    L_HEEL = 29
    R_HEEL = 30
    L_FOOT = 31
    R_FOOT = 32


# какие точки обязаны быть видны, чтобы вообще считать позу
CORE = (B.L_SHOULDER, B.R_SHOULDER, B.L_HIP, B.R_HIP)

# Точек кистей и стоп у Pose нет, поэтому «скелет» рисуется по этим связям —
# ровно как в MediaPipe Pose (POSE_CONNECTIONS), только сгруппированным по
# частям тела: так видно, какая часть тела реально попала в кадр.
POSE_EDGES = (
    # голова
    (B.NOSE, B.L_EYE_INNER), (B.L_EYE_INNER, B.L_EYE), (B.L_EYE, B.L_EYE_OUTER),
    (B.L_EYE_OUTER, B.L_EAR), (B.NOSE, B.R_EYE_INNER), (B.R_EYE_INNER, B.R_EYE),
    (B.R_EYE, B.R_EYE_OUTER), (B.R_EYE_OUTER, B.R_EAR),
    (B.MOUTH_L, B.MOUTH_R),
    # левая рука
    (B.L_SHOULDER, B.L_ELBOW), (B.L_ELBOW, B.L_WRIST),
    (B.L_WRIST, B.L_PINKY), (B.L_WRIST, B.L_INDEX), (B.L_WRIST, B.L_THUMB),
    # правая рука
    (B.R_SHOULDER, B.R_ELBOW), (B.R_ELBOW, B.R_WRIST),
    (B.R_WRIST, B.R_PINKY), (B.R_WRIST, B.R_INDEX), (B.R_WRIST, B.R_THUMB),
    # корпус
    (B.L_SHOULDER, B.R_SHOULDER), (B.L_SHOULDER, B.L_HIP),
    (B.R_SHOULDER, B.R_HIP), (B.L_HIP, B.R_HIP),
    # левая нога
    (B.L_HIP, B.L_KNEE), (B.L_KNEE, B.L_ANKLE), (B.L_ANKLE, B.L_HEEL),
    (B.L_ANKLE, B.L_FOOT), (B.L_HEEL, B.L_FOOT),
    # правая нога
    (B.R_HIP, B.R_KNEE), (B.R_KNEE, B.R_ANKLE), (B.R_ANKLE, B.R_HEEL),
    (B.R_ANKLE, B.R_FOOT), (B.R_HEEL, B.R_FOOT),
)

# мелкие «пальцы» (17..22) — их видно только на крупном плане
POSE_EDGES_SMALL = (
    (B.L_PINKY, B.L_INDEX), (B.R_PINKY, B.R_INDEX),
)

POSTURE_TITLES = {
    "stand": "стоит",
    "squat": "приседает",
    "lean": "наклон",
    "arms_up": "руки вверх",
}


@dataclass
class BodyMetrics:
    """Числа по телу в одном кадре (углы в градусах)."""

    knee_l: float = 180.0
    knee_r: float = 180.0
    hip_l: float = 180.0
    hip_r: float = 180.0
    lean: float = 0.0              # наклон корпуса от вертикали
    depth: float = 0.0             # «глубина приседа» 0..1 (0 — стоим)
    arms_up: float = 0.0           # 0..1, насколько руки выше плеч
    scale: float = 0.0             # размер тела в кадре (плечи→таз)
    center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    visible: bool = False
    # Что именно видно. У веб-камеры человек часто «по пояс», и требовать
    # стопы — значит не показывать вообще ничего. Считаем то, что видно.
    torso_ok: bool = False         # плечи и таз
    legs_ok: bool = False          # колени и стопы
    arms_ok: bool = False          # локти и запястья
    head_ok: bool = False          # нос
    joints: int = 0                # сколько точек прошло порог видимости

    @property
    def partial(self) -> bool:
        """Видно, но не целиком: обычно «по пояс»."""
        return bool(self.visible and self.torso_ok and not self.legs_ok)

    @property
    def where(self) -> str:
        """Словесный охват кадра — для окна и журнала."""
        if not self.visible:
            return "тела не видно"
        if self.partial:
            return "видно по пояс"
        return "видно целиком"

    @property
    def knee(self) -> float:
        return 0.5 * (self.knee_l + self.knee_r)

    @property
    def posture(self) -> str:
        """Словесная поза — для окна и для журнала."""
        cfg_depth = 0.5
        if self.arms_up >= 0.5:
            return "arms_up"
        if self.depth >= cfg_depth:
            return "squat"
        if self.lean >= 25.0:
            return "lean"
        return "stand"


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return angle_deg(a, b, c)


def measure_body(points: Sequence[Sequence[float]],
                 min_visibility: float = 0.5) -> BodyMetrics:
    """Считает углы и позу по 33 точкам кадра (x, y, z, visibility).

    Требуется только **корпус**: плечи и таз. Ноги и руки — по возможности.
    Если человек попал в кадр «по пояс», поза всё равно определяется: наклон
    корпуса и руки вверх считаются, а глубина приседа — нет (её физически
    не из чего взять без коленей и стоп), и это честно помечается в
    :attr:`BodyMetrics.partial`.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 33:
        return BodyMetrics(visible=False)
    if pts.shape[1] < 3:
        return BodyMetrics(visible=False)
    xy = pts[:, :2]
    vis = pts[:, 3] if pts.shape[1] >= 4 else np.ones(pts.shape[0])
    joints = int(np.sum(vis[:33] >= min_visibility))

    def seen(*idx: int) -> bool:
        return all(float(vis[i]) >= min_visibility for i in idx)

    shoulders_ok = seen(B.L_SHOULDER, B.R_SHOULDER)
    hips_seen = [i for i in (B.L_HIP, B.R_HIP) if float(vis[i]) >= min_visibility]
    # Достаточно обоих плеч и хотя бы одного тазобедренного сустава: на кадре
    # «по пояс» второй бедренный сустав часто уже за краем.
    torso_ok = bool(shoulders_ok and hips_seen)
    if not torso_ok:
        # без плеч и таза не определить ни масштаб, ни наклон — это не «пояс»,
        # а «человека нет в кадре»
        return BodyMetrics(visible=False, joints=joints)
    legs_ok = bool(len(hips_seen) == 2 and seen(B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE))
    arms_ok = seen(B.L_ELBOW, B.R_ELBOW, B.L_WRIST, B.R_WRIST)
    head_ok = seen(B.NOSE)

    shoulder = 0.5 * (xy[B.L_SHOULDER] + xy[B.R_SHOULDER])
    hip = np.mean([xy[i] for i in hips_seen], axis=0)
    scale = float(np.linalg.norm(hip - shoulder))
    if scale < 1e-4:
        return BodyMetrics(visible=False, joints=joints, torso_ok=True)

    tors = shoulder - hip
    lean = math.degrees(math.atan2(abs(float(tors[0])), max(1e-6, abs(float(tors[1])))))

    # Ноги: углы считаем, только если видно колени и стопы. Иначе оставляем
    # «разогнуто» — так поза не превращается в присед из-за невидимой ноги.
    if legs_ok:
        ankle = 0.5 * (xy[B.L_ANKLE] + xy[B.R_ANKLE])
        knee_l = _angle(xy[B.L_HIP], xy[B.L_KNEE], xy[B.L_ANKLE])
        knee_r = _angle(xy[B.R_HIP], xy[B.R_KNEE], xy[B.R_ANKLE])
        hip_l = _angle(xy[B.L_SHOULDER], xy[B.L_HIP], xy[B.L_KNEE])
        hip_r = _angle(xy[B.R_SHOULDER], xy[B.R_HIP], xy[B.R_KNEE])
        # Глубина приседа — максимум из двух независимых сигналов.
        # 1) угол в колене: сбоку он честно падает со 180° до ~90°;
        knee = 0.5 * (knee_l + knee_r)
        by_knee = clamp((180.0 - knee) / 90.0, 0.0, 1.0)
        # 2) просадка таза: спереди колено «смотрит в объектив» и угол врёт,
        #    зато таз опускается к стопам — это видно всегда. Берём только
        #    вертикаль: наклон корпуса в сторону не должен выглядеть приседом.
        drop = 0.0
        span = float(abs(ankle[1] - shoulder[1]))
        if span > 1e-4:
            drop = clamp((float(hip[1] - shoulder[1]) / span - 0.38) / 0.32, 0.0, 1.0)
        depth = max(by_knee, drop)
    else:
        knee_l = knee_r = 180.0
        hip_l = _angle(xy[B.L_SHOULDER], xy[B.L_HIP], xy[B.R_HIP])
        hip_r = _angle(xy[B.R_SHOULDER], xy[B.R_HIP], xy[B.L_HIP])
        depth = 0.0

    # Руки выше плеч: запястья подняты (y растёт вниз). Без запястий — 0.
    if arms_ok:
        up_l = shoulder[1] - xy[B.L_WRIST, 1]
        up_r = shoulder[1] - xy[B.R_WRIST, 1]
        up = 0.5 * (up_l + up_r) / scale
        arms_up = clamp((up - 0.25) / 0.75, 0.0, 1.0)
    else:
        arms_up = 0.0

    return BodyMetrics(
        knee_l=knee_l, knee_r=knee_r, hip_l=hip_l, hip_r=hip_r,
        lean=lean, depth=depth, arms_up=arms_up, scale=scale,
        center=hip.copy(), visible=True,
        torso_ok=True, legs_ok=legs_ok, arms_ok=arms_ok, head_ok=head_ok,
        joints=joints,
    )


class BodyFSM:
    """Поза тела и упражнения: приседания, наклон, руки вверх.

    Счёт повторов — с гистерезисом (вниз/вверх по разным порогам) и
    минимальной длительностью повторения: так дребезг точек не превращается
    в «сделал 40 приседаний».
    """

    def __init__(self, cfg: Optional[BodyConfig] = None) -> None:
        self.cfg = cfg or BodyConfig()
        self.metrics = BodyMetrics()
        self.posture = "stand"
        self.reps = 0
        self._down = False
        self._down_since = 0.0
        self._last_rep = -1e9
        self._knee = OneEuroFilter(min_cutoff=0.8, beta=0.02)
        self._depth = OneEuroFilter(min_cutoff=0.8, beta=0.05)
        self._lean = OneEuroFilter(min_cutoff=0.8, beta=0.05)
        self._arms = OneEuroFilter(min_cutoff=0.9, beta=0.05)
        self.arms_up_hold = HoldTimer(self.cfg.arms_up_hold_s)
        self.last_angle = 0.0

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        for f in (self._knee, self._depth, self._lean, self._arms):
            f.reset()
        self._down = False
        self.arms_up_hold.reset()

    @property
    def text(self) -> str:
        """Строка для окна: «тело: стоит · приседаний 3».

        Если человек попал в кадр «по пояс», приседания не считаются — об этом
        честно написано, иначе выглядело бы как «счётчик сломался».
        """
        if not self.metrics.visible:
            return ""
        parts = [f"тело: {POSTURE_TITLES.get(self.posture, self.posture)}"]
        if self.metrics.legs_ok:
            parts.append(f"приседаний {self.reps}")
            if self.posture == "squat":
                parts.append(f"глубина {self.metrics.depth * 100:.0f}%")
        else:
            parts.append("видно по пояс")
            if self.metrics.arms_ok:
                parts.append(f"руки {self.metrics.arms_up * 100:.0f}%")
        if self.metrics.arms_ok:
            parts.append(f"наклон {self.metrics.lean:.0f}°")
        return " · ".join(parts)

    # ------------------------------------------------------------------ #
    def update(self, metrics: Optional[BodyMetrics], now: float) -> List[Event]:
        events: List[Event] = []
        if metrics is None or not metrics.visible:
            self.metrics = metrics or BodyMetrics()
            self.posture = ""
            self.arms_up_hold.reset()
            self._down = False
            self.reset()
            return events

        # сглаживание: углы по кадрам дрожат на градусы
        depth = float(self._depth.filter(metrics.depth, now))
        knee = float(self._knee.filter(metrics.knee, now))
        lean = float(self._lean.filter(metrics.lean, now))
        arms = float(self._arms.filter(metrics.arms_up, now))
        self.metrics = BodyMetrics(
            knee_l=metrics.knee_l, knee_r=metrics.knee_r,
            hip_l=metrics.hip_l, hip_r=metrics.hip_r,
            lean=lean, depth=depth, arms_up=arms, scale=metrics.scale,
            center=metrics.center, visible=True,
            # какие части тела видно — переносим как есть: от этого зависит и
            # текст в окне, и то, можно ли вообще считать приседания
            torso_ok=metrics.torso_ok, legs_ok=metrics.legs_ok,
            arms_ok=metrics.arms_ok, head_ok=metrics.head_ok,
            joints=metrics.joints,
        )
        self.last_angle = knee

        posture = metrics.posture
        if arms >= 0.5:
            posture = "arms_up"
        elif depth >= self.cfg.squat_down:
            posture = "squat"
        elif lean >= self.cfg.lean_deg:
            posture = "lean"
        else:
            posture = "stand"
        self.posture = posture

        # --- приседания: гистерезис + минимальная длительность повтора --- #
        if depth >= self.cfg.squat_down:
            if not self._down:
                self._down = True
                self._down_since = now
        elif depth <= self.cfg.squat_up and self._down:
            self._down = False
            if now - self._down_since >= self.cfg.squat_min_s:
                self.reps += 1
                self._last_rep = now
                events.append(Event("squat_rep", value=self.reps, label="приседание"))
        # если человек замер внизу дольше, чем нужно, — это уже не повтор,
        # а просто присел; глубина «держится» без нового счёта

        # --- руки вверх: удержание --- #
        fired = self.arms_up_hold.update(arms >= 0.5, now)
        if fired:
            events.append(Event("arms_up_hold", label="руки вверх"))
        return events




def synthetic_body(
    center: Tuple[float, float] = (0.5, 0.62),
    height: float = 0.62,
    squat: float = 0.0,
    arms_up: float = 0.0,
    lean: float = 0.0,
    sit: float = 0.0,
    visibility: float = 1.0,
) -> np.ndarray:
    """Синтетическое тело: 33 точки (x, y, z, visibility).

    Параметры управляют позой так, как это видно камере **спереди**
    (основной сценарий: человек сидит/стоит перед веб-камерой) и допускают
    небольшой наклон. ``squat`` 0..1 — глубина приседа, ``arms_up`` 0..1 —
    насколько подняты руки, ``sit`` 0..1 — «сел на стул».
    """
    squat = clamp(squat, 0.0, 1.0)
    arms_up = clamp(arms_up, 0.0, 1.0)
    sit = clamp(sit, 0.0, 1.0)
    lean_rad = math.radians(lean)

    cx, top = center
    # рост: от темечка до стоп
    head_y = top - 0.5 * height
    shoulder_y = top - 0.32 * height
    hip_y = top - 0.02 * height
    knee_y = top + 0.28 * height
    ankle_y = top + 0.48 * height

    # присед: таз и колени опускаются, стопы на месте
    hip_y += 0.18 * height * squat
    knee_y += 0.10 * height * squat
    # посадка: таз на уровне колен, колени вперёд (по картинке — ниже)
    hip_y += 0.22 * height * sit
    knee_y += 0.02 * height * sit

    shoulder_w = 0.10 * height
    hip_w = 0.075 * height
    dx = 0.0
    # наклон корпуса: плечи уезжают в сторону, таз на месте
    dx = math.tan(lean_rad) * (hip_y - shoulder_y) if abs(lean) > 1e-6 else 0.0

    pts = np.zeros((33, 4), dtype=np.float64)
    pts[:, 3] = visibility

    def put(idx: int, x: float, y: float) -> None:
        pts[idx, 0] = x
        pts[idx, 1] = y

    # голова: нос, глаза, уши, рот — иначе на «скелете» от лица тянулись бы
    # линии в угол кадра (в синтетике остальные точки были нулями)
    eye_y = head_y - 0.018 * height
    ear_y = head_y + 0.004 * height
    put(B.NOSE, cx + dx, head_y + 0.012 * height)
    put(B.L_EYE_INNER, cx + dx - 0.012 * height, eye_y)
    put(B.L_EYE, cx + dx - 0.020 * height, eye_y)
    put(B.L_EYE_OUTER, cx + dx - 0.028 * height, eye_y)
    put(B.R_EYE_INNER, cx + dx + 0.012 * height, eye_y)
    put(B.R_EYE, cx + dx + 0.020 * height, eye_y)
    put(B.R_EYE_OUTER, cx + dx + 0.028 * height, eye_y)
    put(B.L_EAR, cx + dx - 0.042 * height, ear_y)
    put(B.R_EAR, cx + dx + 0.042 * height, ear_y)
    put(B.MOUTH_L, cx + dx - 0.014 * height, head_y + 0.028 * height)
    put(B.MOUTH_R, cx + dx + 0.014 * height, head_y + 0.028 * height)
    put(B.L_SHOULDER, cx + dx - shoulder_w, shoulder_y)
    put(B.R_SHOULDER, cx + dx + shoulder_w, shoulder_y)
    put(B.L_HIP, cx - hip_w, hip_y)
    put(B.R_HIP, cx + hip_w, hip_y)
    put(B.L_KNEE, cx - hip_w * 1.1, knee_y)
    put(B.R_KNEE, cx + hip_w * 1.1, knee_y)
    put(B.L_ANKLE, cx - hip_w * 1.05, ankle_y)
    put(B.R_ANKLE, cx + hip_w * 1.05, ankle_y)
    put(B.L_HEEL, cx - hip_w * 1.05, ankle_y + 0.01 * height)
    put(B.R_HEEL, cx + hip_w * 1.05, ankle_y + 0.01 * height)
    put(B.L_FOOT, cx - hip_w * 1.05, ankle_y + 0.02 * height)
    put(B.R_FOOT, cx + hip_w * 1.05, ankle_y + 0.02 * height)

    # руки: опущены вдоль корпуса или подняты вверх
    arm_len = 0.26 * height
    for side, sh_idx, el_idx, wr_idx in (
        (-1.0, B.L_SHOULDER, B.L_ELBOW, B.L_WRIST),
        (+1.0, B.R_SHOULDER, B.R_ELBOW, B.R_WRIST),
    ):
        sh_x = cx + dx + side * shoulder_w
        sh_y = shoulder_y
        # вниз: локоть и запястье ниже плеча; вверх: выше плеча
        el_y = sh_y + (1.0 - 2.0 * arms_up) * 0.5 * arm_len
        wr_y = sh_y + (1.0 - 2.0 * arms_up) * arm_len
        el_x = sh_x + side * 0.05 * height * (1.0 - arms_up)
        wr_x = sh_x + side * 0.08 * height * (1.0 - arms_up)
        put(el_idx, el_x, el_y)
        put(wr_idx, wr_x, wr_y)
        # «пальцы» Pose ставит чуть дальше запястья — по ним рисуется кисть
        pinky_idx, index_idx, thumb_idx = ((B.L_PINKY, B.L_INDEX, B.L_THUMB) if side < 0
                                           else (B.R_PINKY, B.R_INDEX, B.R_THUMB))
        put(pinky_idx, wr_x + side * 0.012 * height, wr_y + 0.012 * height)
        put(index_idx, wr_x + side * 0.004 * height, wr_y + 0.016 * height)
        put(thumb_idx, wr_x - side * 0.010 * height, wr_y + 0.006 * height)

    return pts
