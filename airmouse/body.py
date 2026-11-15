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
from typing import Dict, List, Optional, Sequence, Tuple

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

# точки, которыми описывается голова в позе
HEAD_POSE = (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR, B.MOUTH_L, B.MOUTH_R)

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
    upper_ok: bool = False         # плечи без таза: «по грудь»
    joints: int = 0                # сколько точек прошло порог видимости

    @property
    def partial(self) -> bool:
        """Видно, но не целиком: обычно «по пояс»."""
        return bool(self.visible and self.torso_ok and not self.legs_ok)

    @property
    def parts(self) -> str:
        """Что именно попало в кадр: «голова, корпус, руки»."""
        names = []
        if self.head_ok:
            names.append("голова")
        if self.torso_ok:
            names.append("корпус")
        elif self.upper_ok:
            names.append("плечи")
        if self.arms_ok:
            names.append("руки")
        if self.legs_ok:
            names.append("ноги")
        return ", ".join(names)

    @property
    def where(self) -> str:
        """Словесный охват кадра — для окна и журнала.

        Раньше было три состояния: целиком, по пояс, «не вижу». Но человек
        часто попадает в кадр **частично**: видно голову и руки, а корпуса с
        тазом уже нет (сел близко к камере, лёг, наклонился к клавиатуре).
        Это не «тела не видно» — скелет рисуется, руки работают.
        """
        if not self.visible:
            return "тела не видно"
        if self.legs_ok:
            return "видно целиком"
        if self.torso_ok:
            return "видно по пояс"
        if self.upper_ok:
            # «по грудь»: таза нет, но плечи, руки и голова — есть
            if self.arms_ok and self.head_ok:
                return "видно голову и руки"
            return "видно по грудь"
        return "тела не видно"

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


def _point_vis(points: np.ndarray, index: int) -> float:
    return float(points[index, 3]) if points.shape[1] > 3 else 1.0


def head_center(points: Optional[Sequence[Sequence[float]]],
                min_visibility: float = 0.35) -> Optional[np.ndarray]:
    """Центр головы по точкам позы. ``None`` — головы в кадре не видно.

    Нужны минимум три точки из семи: по одной рамку не построить, по двум она
    вытягивается в линию и «голова» уезжает вбок.
    """
    if points is None:
        return None
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 33:
        return None
    seen = [i for i in HEAD_POSE if _point_vis(pts, i) >= min_visibility]
    if len(seen) < 3:
        return None
    return pts[seen, :2].mean(axis=0)


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
    legs_ok = bool(len(hips_seen) == 2 and seen(B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE))
    arms_ok = seen(B.L_ELBOW, B.R_ELBOW, B.L_WRIST, B.R_WRIST)
    head_ok = bool(any(_point_vis(pts, i) >= min_visibility
                       for i in (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR)))
    # Плечи без таза («по грудь») и голова с руками — тоже человек в кадре.
    # Масштаб тогда берём по ширине плеч: 0.2 роста — так же, как
    # «плечи → таз» у полного корпуса.
    upper_ok = bool(shoulders_ok and not torso_ok)
    if not torso_ok and not upper_ok:
        # плеч не видно — рисовать скелет не из чего: руки «висят в воздухе»,
        # а голова без шеи. Это честное «человека нет в кадре».
        return BodyMetrics(visible=False, joints=joints, head_ok=head_ok)

    if torso_ok:
        shoulder = 0.5 * (xy[B.L_SHOULDER] + xy[B.R_SHOULDER])
        hip = np.mean([xy[i] for i in hips_seen], axis=0)
        scale = float(np.linalg.norm(hip - shoulder))
    else:
        # «по грудь»: таза нет — масштаб по ширине плеч
        shoulder = 0.5 * (xy[B.L_SHOULDER] + xy[B.R_SHOULDER])
        hip = shoulder + np.array([0.0, 0.2])
        scale = float(np.linalg.norm(xy[B.L_SHOULDER] - xy[B.R_SHOULDER])) * 1.6
    if scale < 1e-4:
        return BodyMetrics(visible=False, joints=joints, torso_ok=torso_ok,
                           upper_ok=upper_ok)

    tors = shoulder - hip
    lean = math.degrees(math.atan2(abs(float(tors[0])), max(1e-6, abs(float(tors[1])))))

    # Ноги: углы считаем, только если видно колени и стопы. Иначе оставляем
    # «разогнуто» — так поза не превращается в присед из-за невидимой ноги.
    if legs_ok and torso_ok:
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
        torso_ok=torso_ok, legs_ok=legs_ok, arms_ok=arms_ok, head_ok=head_ok,
        upper_ok=upper_ok, joints=joints,
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
        where = self.metrics.where
        if where != "видно целиком":
            # «по пояс», «по грудь», «голову и руки» — честно пишем, что попало
            # в кадр: по этому человек сразу понимает, что считается, а что нет
            parts.append(where)
        if self.metrics.legs_ok:
            parts.append(f"приседаний {self.reps}")
            if self.posture == "squat":
                parts.append(f"глубина {self.metrics.depth * 100:.0f}%")
        elif self.metrics.arms_ok:
            parts.append(f"руки {self.metrics.arms_up * 100:.0f}%")
        if self.metrics.arms_ok and self.metrics.legs_ok:
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
    arms: str = "auto",
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

        pose = arms
        if pose == "tpose":
            # руки в стороны: плечо, локоть и запястье на одной высоте
            el_x, el_y = sh_x + side * 0.5 * arm_len, sh_y
            wr_x, wr_y = sh_x + side * arm_len, sh_y
        elif pose == "curl":
            # «гантель у плеча»: локоть вниз у корпуса, запястье поднято к плечу
            el_x, el_y = sh_x + side * 0.02 * height, sh_y + 0.13 * height
            wr_x, wr_y = sh_x + side * 0.035 * height, sh_y + 0.005 * height
        elif pose == "curl_down":
            # сгибание только началось: локоть вниз, запястье ещё у бедра
            el_x, el_y = sh_x + side * 0.02 * height, sh_y + 0.13 * height
            wr_x, wr_y = sh_x + side * 0.03 * height, sh_y + 0.24 * height
        elif pose == "guard":
            # боксёрская стойка: локти у корпуса, кулаки у подбородка
            el_x, el_y = sh_x + side * 0.025 * height, sh_y + 0.10 * height
            wr_x, wr_y = sh_x - side * 0.005 * height, sh_y - 0.010 * height
        elif pose in ("punch_left", "punch_right"):
            # удар одной рукой: она вынесена вперёд и разогнута, вторая в стойке
            side_name = "left" if side < 0 else "right"
            if pose.endswith(side_name):
                el_x, el_y = sh_x + side * 0.16 * height, sh_y + 0.02 * height
                wr_x, wr_y = sh_x + side * 0.30 * height, sh_y + 0.01 * height
            else:
                el_x, el_y = sh_x + side * 0.025 * height, sh_y + 0.10 * height
                wr_x, wr_y = sh_x - side * 0.005 * height, sh_y - 0.010 * height
        put(el_idx, el_x, el_y)
        put(wr_idx, wr_x, wr_y)
        # «пальцы» Pose ставит чуть дальше запястья — по ним рисуется кисть
        pinky_idx, index_idx, thumb_idx = ((B.L_PINKY, B.L_INDEX, B.L_THUMB) if side < 0
                                           else (B.R_PINKY, B.R_INDEX, B.R_THUMB))
        put(pinky_idx, wr_x + side * 0.012 * height, wr_y + 0.012 * height)
        put(index_idx, wr_x + side * 0.004 * height, wr_y + 0.016 * height)
        put(thumb_idx, wr_x - side * 0.010 * height, wr_y + 0.006 * height)

    return pts


# --------------------------------------------------------------------------- #
#  Стабильность: тело не должно мигать, когда его почти не видно
# --------------------------------------------------------------------------- #
class BodySmoother:
    """Сглаживает точки позы по времени и гасит «скачущий» скелет.

    Модель позы отдаёт 33 точки по одному кадру, и когда человека почти не видно
    (в кадре только рука, половина корпуса за краем, кто-то прошёл фоном),
    скелет появляется и исчезает по нескольку раз в секунду. Глазами это
    читается как «моделька скачет», хотя человек стоит ровно.

    Правила простые и проверяемые:

    * скелет показываем только после ``confirm_frames`` кадров подряд с видимым
      ядром (плечи + хотя бы один таз) — случайный кадр его не включает;
    * точки сглаживаются 1€-фильтром: в покое не дрожат, при движении не
      отстают;
    * пропал на 1–2 кадра — держим последнюю позу (не мигаем), пропал надолго —
      честно убираем.
    """

    def __init__(self, min_visibility: float = 0.5, confirm_frames: int = 3,
                 hold_frames: int = 6, min_cutoff: float = 1.2, beta: float = 0.05) -> None:
        self.min_visibility = float(min_visibility)
        self.confirm_frames = max(int(confirm_frames), 1)
        self.hold_frames = max(int(hold_frames), 0)
        self._filter = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)
        self._seen = 0
        self._missing = 0
        self.active = False
        self._last: Optional[np.ndarray] = None
        self.metrics = BodyMetrics()
        self.held = 0                  # сколько кадров держим прошлую позу

    def reset(self) -> None:
        self._filter.reset()
        self._seen = 0
        self._missing = 0
        self.active = False
        self._last = None
        self.metrics = BodyMetrics()
        self.held = 0

    def update(self, body: Optional[np.ndarray], now: float,
               face_center: Optional[Sequence[float]] = None) -> Optional[np.ndarray]:
        """``face_center`` — где сейчас лицо: по нему «доезжает» удержанный скелет."""
        ok = False
        if body is not None:
            metrics = measure_body(body, self.min_visibility)
            ok = bool(metrics.torso_ok)
            if ok:
                self.metrics = metrics
        if ok:
            self._seen += 1
            self._missing = 0
            self.held = 0
            smoothed = np.array(body, dtype=np.float64, copy=True)
            smoothed[:, :2] = self._filter.filter(smoothed[:, :2], now)
            self._last = smoothed
            if self._seen >= self.confirm_frames:
                self.active = True
            return smoothed if self.active else None

        self._seen = 0
        self._missing += 1
        if not self.active:
            return None
        if self._missing <= self.hold_frames and self._last is not None:
            # короткий провал: держим позу, но не двигаем её — и не считаем, что
            # человек что-то делает (упражнения в это время не считаются).
            # Исключение — лицо: если оно видно, скелет сдвигается вместе с
            # головой, иначе «замороженная» моделька остаётся в стороне, пока
            # человек уже сдвинулся.
            self.held = self._missing
            self.metrics.visible = False
            held = self._last
            if face_center is not None:
                center = head_center(held, self.min_visibility)
                if center is not None:
                    shift = np.asarray(face_center, dtype=float)[:2] - center
                    if float(np.linalg.norm(shift)) <= 0.8:   # не телепортируем
                        held = np.array(held, dtype=np.float64, copy=True)
                        held[:, :2] += shift
                        self._last = held
            return held
        self.active = False
        self._last = None
        self.metrics = BodyMetrics()
        return None


# --------------------------------------------------------------------------- #
#  Спорт по телу: сгибания рук, T-поза, бокс
# --------------------------------------------------------------------------- #
SPORT_TITLES = {
    "curl": "сгибание рук",
    "tpose": "T-поза",
    "guard": "бокс: стойка",
    "punch": "удар",
}


@dataclass
class ArmPose:
    """Геометрия одной руки в одном кадре (в долях размера тела)."""

    elbow: float = 180.0           # угол в локте: 180 — рука прямая
    lateral: float = 0.0           # |запястье − плечо| по горизонтали
    vertical: float = 0.0          # запястье ниже плеча (отрицательное — выше)
    reach: float = 0.0             # расстояние плечо → запястье
    speed: float = 0.0             # скорость запястья, размеров тела в секунду
    above_elbow: bool = False      # запястье выше локтя (сгибание, а не мах)

    @property
    def straight(self) -> bool:
        return self.elbow >= 145.0

    @property
    def bent(self) -> bool:
        return self.elbow <= 110.0


def arm_pose(body: Optional[np.ndarray], side: str, scale: float,
             prev: Optional[np.ndarray] = None, dt: float = 0.0,
             min_visibility: float = 0.35) -> Optional[ArmPose]:
    """Считает геометрию руки по 33 точкам позы. ``None`` — руки не видно."""
    if body is None or scale <= 1e-6:
        return None
    pts = np.asarray(body, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 33:
        return None
    sh_i, el_i, wr_i = ((B.L_SHOULDER, B.L_ELBOW, B.L_WRIST) if side == "left"
                        else (B.R_SHOULDER, B.R_ELBOW, B.R_WRIST))
    if min(_point_vis(pts, sh_i), _point_vis(pts, el_i), _point_vis(pts, wr_i)) < min_visibility:
        return None
    sh, el, wr = pts[sh_i, :2], pts[el_i, :2], pts[wr_i, :2]
    speed = 0.0
    if prev is not None and dt > 1e-4:
        speed = float(np.linalg.norm(wr - prev) / dt / scale)
    return ArmPose(
        elbow=_angle(sh, el, wr),
        lateral=float(abs(wr[0] - sh[0]) / scale),
        vertical=float((wr[1] - sh[1]) / scale),
        reach=float(np.linalg.norm(wr - sh) / scale),
        speed=speed,
        above_elbow=bool(wr[1] < el[1]),
    )


class BodySport:
    """Упражнения и единоборства по скелету: сгибания рук, T-поза, бокс.

    Всё считается по углу в локте и положению запястья относительно плеча —
    то есть по тому, что видно с веб-камеры **спереди**, без 3D и без
    специальных моделей. Счёт — с гистерезисом и минимальной длительностью,
    иначе дребезг точек превращался бы в «сделал 80 сгибаний».

    * **сгибание рук** (как с гантелями): локоть у корпуса, запястье идёт от
      бедра к плечу. Повтор = угол в локте упал ниже ``curl_down`` и вернулся
      выше ``curl_up``, и это заняло не меньше ``curl_min_s``;
    * **T-поза**: обе руки выпрямлены и разведены в стороны — держится
      ``tpose_hold_s``, чтобы случайный взмах не считался позой;
    * **боксёрская стойка**: оба локтя согнуты, кулаки у подбородка;
    * **удар**: рука из стойки резко выносится вперёд (локоть разогнулся,
      запястье ушло в сторону со скоростью выше ``punch_speed``). Удар
      засчитывается один раз, пока рука не вернётся в стойку.
    """

    def __init__(self, cfg: Optional[BodyConfig] = None) -> None:
        self.cfg = cfg or BodyConfig()
        self.curls = 0
        self.tposes = 0
        self.punches = 0
        self.guard = False
        self.tpose = False
        self.poses: Dict[str, Optional[ArmPose]] = {"left": None, "right": None}
        self._prev: Dict[str, Optional[np.ndarray]] = {"left": None, "right": None}
        self._down = False
        self._down_since = 0.0
        self._t_downside = ""
        self._tpose_hold = HoldTimer(float(getattr(self.cfg, "tpose_hold_s", 0.35)))
        self._guard_hold = HoldTimer(float(getattr(self.cfg, "guard_hold_s", 0.30)))
        self._extended = False
        self._last_punch = -1e9
        self._last_guard = -1e9        # когда стойка была в последний раз
        self._t = 0.0

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self.poses = {"left": None, "right": None}
        self._prev = {"left": None, "right": None}
        self._down = False
        self._down_since = 0.0
        self._tpose_hold.reset()
        self._guard_hold.reset()
        self.guard = False
        self.tpose = False
        self._extended = False
        self._t = 0.0

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.cfg, "sport", True))

    @property
    def text(self) -> str:
        """Строка для окна: «спорт: сгибания рук 5 · T-поза · ударов 12»."""
        if not self.enabled:
            return ""
        parts = []
        if getattr(self.cfg, "curls", True) and self.curls:
            parts.append(f"сгибания рук {self.curls}")
        if getattr(self.cfg, "tpose", True) and self.tpose:
            parts.append("T-поза")
        if getattr(self.cfg, "boxing", True):
            if self.guard:
                parts.append("бокс: стойка")
            if self.punches:
                parts.append(f"ударов {self.punches}")
        return "спорт: " + " · ".join(parts) if parts else ""

    # ------------------------------------------------------------------ #
    def update(self, body: Optional[np.ndarray], metrics: Optional[BodyMetrics],
               now: float) -> List[Event]:
        events: List[Event] = []
        if not self.enabled or body is None or metrics is None or not metrics.visible:
            self.poses = {"left": None, "right": None}
            self._prev = {"left": None, "right": None}
            self.guard = self.tpose = False
            self._down = False
            return events
        dt = max(now - self._t, 1e-3)
        self._t = now
        scale = float(metrics.scale)
        # сгибания и бокс считаем только когда руки видны целиком
        if not metrics.arms_ok:
            self.poses = {"left": None, "right": None}
            self.guard = self.tpose = False
            self._down = False
            return events

        poses: Dict[str, Optional[ArmPose]] = {}
        for side in ("left", "right"):
            pose = arm_pose(body, side, scale, self._prev[side], dt)
            poses[side] = pose
            if pose is not None:
                idx = B.L_WRIST if side == "left" else B.R_WRIST
                self._prev[side] = np.asarray(body, dtype=np.float64)[idx, :2].copy()
            else:
                self._prev[side] = None
        self.poses = poses
        if getattr(self.cfg, "curls", True):
            events += self._curls(poses, now)
        if getattr(self.cfg, "tpose", True):
            events += self._tpose(poses, now)
        if getattr(self.cfg, "boxing", True):
            events += self._boxing(poses, now)
        return events

    # ------------------------------------------------------------------ #
    def _curls(self, poses: Dict[str, Optional[ArmPose]], now: float) -> List[Event]:
        down = up = False
        for side, pose in poses.items():
            if pose is None:
                continue
            if pose.elbow <= float(getattr(self.cfg, "curl_down", 72.0)) and pose.above_elbow:
                down = True
            if pose.elbow >= float(getattr(self.cfg, "curl_up", 148.0)):
                up = True
        if down:
            if not self._down:
                self._down = True
                self._down_since = now
            return []
        if up and self._down:
            self._down = False
            if now - self._down_since >= float(getattr(self.cfg, "curl_min_s", 0.30)):
                self.curls += 1
                return [Event("curl_rep", value=self.curls, label="сгибание рук")]
        return []

    def _tpose(self, poses: Dict[str, Optional[ArmPose]], now: float) -> List[Event]:
        def ok(pose: Optional[ArmPose]) -> bool:
            return bool(pose is not None and pose.straight
                        and pose.lateral >= 0.85 and abs(pose.vertical) <= 0.35)

        both = ok(poses["left"]) and ok(poses["right"])
        fired = self._tpose_hold.update(both, now)
        self.tpose = both
        if fired:
            self.tposes += 1
            return [Event("tpose_hold", value=self.tposes, label="T-поза")]
        return []

    def _boxing(self, poses: Dict[str, Optional[ArmPose]], now: float) -> List[Event]:
        events: List[Event] = []

        def guard_side(pose: Optional[ArmPose]) -> bool:
            # кулаки у подбородка, то есть на уровне плеч или выше, прижаты к
            # корпусу и **стоят**: сгибание рук — это движение, стойка — нет
            return bool(pose is not None and pose.bent and pose.lateral <= 0.55
                        and pose.vertical <= 0.10 and pose.speed <= 0.80)

        both = guard_side(poses["left"]) and guard_side(poses["right"])
        if self._guard_hold.update(both, now):
            events.append(Event("boxing_guard", label="боксёрская стойка"))
        self.guard = both
        if both:
            self._last_guard = now
        # удар начинается ИЗ стойки: в самом кадре удара одна рука уже
        # выпрямлена, поэтому «в стойке» проверяем по недавнему прошлому
        from_guard = (now - self._last_guard) <= float(
            getattr(self.cfg, "punch_guard_s", 0.7))

        # удар: рука выпрямилась и ушла вперёд быстро — из стойки
        for side, pose in poses.items():
            if pose is None:
                continue
            thrown = (pose.straight and pose.lateral >= 0.75
                      and pose.speed >= float(getattr(self.cfg, "punch_speed", 2.0)))
            if thrown and not self._extended and from_guard:
                if now - self._last_punch >= float(getattr(self.cfg, "punch_cooldown_s", 0.25)):
                    self.punches += 1
                    self._last_punch = now
                    self._extended = True
                    events.append(Event("punch", value=self.punches, label="удар"))
            elif pose.bent and self._extended:
                self._extended = False
        return events


def arm_points(body: Optional[np.ndarray], min_visibility: float = 0.5):
    """Видимые звенья рук: [(плечо, локоть, запястье, сколько видно), ...].

    Нужны, когда кисть потерялась: по телу видно, где рука **должна** быть, и
    можно дорисовать предплечье, а не показывать пустое место.
    """
    if body is None or len(body) < 17:
        return []
    result = []
    for shoulder, elbow, wrist in ((B.L_SHOULDER, B.L_ELBOW, B.L_WRIST),
                                   (B.R_SHOULDER, B.R_ELBOW, B.R_WRIST)):
        vis = [float(body[i, 3]) if body.shape[1] > 3 else 1.0
               for i in (shoulder, elbow, wrist)]
        if vis[0] < min_visibility or vis[1] < min_visibility:
            continue
        result.append((np.asarray(body[shoulder, :2], dtype=float),
                       np.asarray(body[elbow, :2], dtype=float),
                       np.asarray(body[wrist, :2], dtype=float) if vis[2] >= min_visibility else None,
                       min(vis)))
    return result
