"""Окно предпросмотра: AR-подсветка руки и лица и понятная сводка происходящего.

Главные принципы оформления:

* **рука** — цветные «полосы» вдоль каждого пальца (как в AR-примерах), контур
  ладони и подсветка щипка: сразу видно, что нейросеть видит;
* **лицо** — овал лица, глаза, брови и губы, рядом — текущее выражение словами;
* **сводка** — каким движком работаем (нейросеть или классическое CV), сколько
  кадров в секунду, какой жест, включены ли действия и что произошло только что;
* все подписи — по-русски (см. :mod:`airmouse.text`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from . import text as T
from .body import B
from .landmarks import (
    FACE_OVAL,
    F,
    FINGERS,
    THUMB_CMC,
    HAND_CONNECTIONS,
    INDEX_TIP,
    LIPS_INNER,
    LIPS_OUTER,
    PINKY_MCP,
    MIDDLE_MCP,
    RING_MCP,
    THUMB_TIP,
    INDEX_MCP,
    WRIST,
    Face,
    Hand,
)

BG = (26, 28, 32)
FG = (238, 238, 238)
ACCENT = (120, 220, 120)
WARN = (80, 170, 255)
BAD = (70, 70, 230)
DIM = (160, 160, 165)
INFO = (230, 200, 120)

FINGER_COLORS = {
    "thumb": (60, 160, 255),
    "index": (110, 235, 120),
    "middle": (240, 225, 90),
    "ring": (235, 120, 200),
    "pinky": (150, 150, 255),
}
# цвета «скелета» тела: корпус, левая/правая сторона, голова
BODY_COLORS = {
    "torso": (110, 235, 120),
    "left": (60, 190, 255),
    "right": (235, 130, 90),
    "head": (230, 200, 120),
}

FINGER_NAMES = {
    "thumb": "большой",
    "index": "указательный",
    "middle": "средний",
    "ring": "безымянный",
    "pinky": "мизинец",
}


_EYE_A_POLY = (F.EYE_A[0], F.EYE_A[1], F.EYE_A[2], F.EYE_A[3], F.EYE_A[4], F.EYE_A[5])
_EYE_B_POLY = (F.EYE_B[0], F.EYE_B[1], F.EYE_B[2], F.EYE_B[3], F.EYE_B[4], F.EYE_B[5])

# жесты рукой (позы кисти)
HELP_GESTURES = (
    ("щипок", "большой + указательный", "левый клик"),
    ("щипок ср.", "большой + средний", "правый клик"),
    ("большой", "кулак, большой вверх", "двойной клик"),
    ("кулак", "двигать кулаком", "прокрутка"),
    ("ладонь", "раскрытая кисть", "ничего — просто ведёт курсор"),
    ("ОК", "колечко + три пальца", "двойной клик"),
    ("коза", "указат. + мизинец", "пауза"),
    ("три пальца", "указ., средний, безым.", "мышь головой"),
)

# мимика и голова — только показываются в окне (действия включаются настройками)
HELP_FACE = (
    ("улыбка", "улыбнуться", "только индикатор"),
    ("грусть", "уголки губ вниз", "только индикатор"),
    ("удивление", "брови вверх, рот открыт", "только индикатор"),
    ("кивок", "головой вверх-вниз", "настраивается"),
    ("поворот", "головой влево-вправо", "настраивается"),
    ("моргание", "двойное моргание", "левый клик"),
    ("подмигивание", "один глаз, ≥0.25 с", "правый клик"),
)

HELP_KEYS = (
    ("Q / Esc", "выход"),
    ("P", "пауза"),
    ("H", "мышь головой"),
    ("G", "мышь глазами"),
    ("B", "калибровка взгляда"),
    ("C", "настройки"),
    ("V", "режим по кругу"),
    ("K", "калибровка ладони"),
    ("F", "окно на весь экран"),
    ("M", "движок: ИИ ↔ CV"),
    ("I / Tab", "эта справка"),
    ("пробел", "статистика в лог"),
)

HELP_TWO_HANDS = (
    ("две ладони", "развести/свести руки", "масштаб"),
    ("два кулака", "двигать вверх/вниз", "прокрутка"),
)


@dataclass
class OverlayState:
    """Всё, что окно должно знать о текущем кадре."""

    fps: float = 0.0
    backend: str = ""                # человекочитаемое имя движка
    backend_note: str = ""           # почему включён запасной движок
    pose: str = "—"                  # текущий жест словами
    paused: bool = False
    warmup: bool = False
    head_pointer: bool = False
    hand_seen: bool = False
    face_seen: bool = False
    actions_on: bool = True          # выполняются ли реальные клики
    dry_run: bool = False
    ear: float = 0.30
    smile: float = 0.0
    brow: float = 0.0
    mouth_open: float = 0.0
    expression: str = ""             # «улыбка 78%», «грусть», «удивление» …
    lip_word: str = ""
    last_event: str = ""
    hand_count: int = 0              # сколько рук видит нейросеть
    sad: float = 0.0                 # насколько опущены уголки губ
    aiming: bool = False             # пальцы идут на смыкание, курсор заморожен
    aim: Optional[Sequence[float]] = None   # точка прицела (нормированные координаты)
    two_hand_hint: str = ""          # подсказка для жестов двумя руками
    split_roles: bool = False        # «одна рука — курсор, вторая — нажатия»
    roles_text: str = ""             # кто чем занят (режим hand.roles=split)
    settings_open: bool = False      # окно настроек с ползунками открыто
    modes_text: str = ""             # какие режимы включены: «режимы: рука + лицо»
    side_text: str = ""              # «сторона кисти: ладонь / тыл»
    gaze_pointer: bool = False       # курсор двигают глаза (зрачки)
    gaze_text: str = ""              # «взгляд: вправо · мышь глазами ВКЛ»
    hand_note: str = ""              # «рука предсказана (2)» / «физика пальцев: …»
    hand_predicted: bool = False     # главная кисть нарисована предсказанием
    body_text: str = ""              # «тело: стоит · приседаний 3»
    body_enabled: bool = False       # режим тела включён (иначе «тело: выключено»)
    body_where: str = ""             # «видно целиком» / «видно по пояс» / «голову и руки»
    sport_text: str = ""             # «спорт: сгибания рук 5 · T-поза · ударов 12»
    face_hint: Optional[Sequence[float]] = None   # рамка головы, когда лица не видно
    face_hint_note: str = ""         # «лицо не видно — показываю по телу»
    gaze_dwell: float = 0.0          # 0..1 — сколько ещё держать взгляд до клика
    gaze_absolute: bool = False      # курсор телепортируется по калибровке
    calib_active: bool = False       # идёт калибровка взгляда
    calib_target: Optional[Sequence[float]] = None   # куда просим посмотреть
    calib_text: str = ""             # «ВЗГЛЯД: левый верхний угол (1/5)…»
    calib_done: int = 0              # сколько точек калибровки уже снято
    calib_pursuit: bool = False      # калибровка «веди взгляд за точкой»
    calib_trail: Sequence[Sequence[float]] = ()   # след красной точки
    calib_progress: float = 0.0      # сколько времени откалибровано (0..1)
    profile_text: str = ""           # шаг «профиля движений» (клавиша N)
    profile_hint: str = ""           # что именно сделать и сколько осталось
    profile_progress: float = 0.0    # сколько шагов пройдено (0..1)
    calib_debug: str = ""            # «экран 1920×1080 · холст 1920×1080»
    events: List[str] = field(default_factory=list)   # последние действия (готовые строки)
    active_box: Sequence[float] = (0.16, 0.14, 0.84, 0.86)
    hints: str = "Q выход P пауза H голова G глаза B взгляд C настройки V режимы K ладонь F экран M движок I справка"
    show_help: bool = False
    show_names: bool = True
    pinch_threshold: float = 0.32
    version: str = ""


# --------------------------------------------------------------------------- #
#  Мелкие помощники рисования
# --------------------------------------------------------------------------- #
def _panel(img: np.ndarray, x: int, y: int, w: int, h: int, alpha: float = 0.6) -> None:
    x2 = min(img.shape[1], x + w)
    y2 = min(img.shape[0], y + h)
    roi = img[max(y, 0):y2, max(x, 0):x2]
    if roi.size == 0:
        return
    rect = np.full_like(roi, BG, dtype=np.uint8)
    cv2.addWeighted(rect, alpha, roi, 1 - alpha, 0, roi)


def _dashed_rect(img, p1, p2, color, dash: int = 12, thickness: int = 1) -> None:
    x1, y1 = p1
    x2, y2 = p2
    for x in range(x1, x2, dash * 2):
        cv2.line(img, (x, y1), (min(x + dash, x2), y1), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x, y2), (min(x + dash, x2), y2), color, thickness, cv2.LINE_AA)
    for y in range(y1, y2, dash * 2):
        cv2.line(img, (x1, y), (x1, min(y + dash, y2)), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x2, y), (x2, min(y + dash, y2)), color, thickness, cv2.LINE_AA)


def _bar(img, x, y, w, h, value, color, label, vmin=0.0, vmax=1.0, size=13) -> None:
    cv2.rectangle(img, (x, y), (x + w, y + h), (80, 80, 88), 1)
    span = max(vmax - vmin, 1e-6)
    frac = float(np.clip((value - vmin) / span, 0.0, 1.0))
    if frac > 0:
        cv2.rectangle(img, (x + 1, y + 1), (x + 1 + int((w - 2) * frac), y + h - 1), color, -1)
    T.draw(img, label, (x + w + 8, y - 2), size, DIM)


def _label(img, text: str, org: Tuple[int, int], size: int = 15,
           color=FG, padding: int = 5, alpha: float = 0.55) -> Tuple[int, int]:
    """Текст на полупрозрачной плашке — читается на любом фоне."""
    w, h = T.measure(text, size)
    x, y = int(org[0]), int(org[1])
    _panel(img, x - padding, y - padding, w + padding * 2, h + padding * 2, alpha)
    T.draw(img, text, (x, y), size, color)
    return w, h


# --------------------------------------------------------------------------- #
#  Рука
# --------------------------------------------------------------------------- #
# какую часть тела красим каким цветом
_BODY_LEFT = frozenset((
    B.L_SHOULDER, B.L_ELBOW, B.L_WRIST, B.L_PINKY, B.L_INDEX, B.L_THUMB,
    B.L_HIP, B.L_KNEE, B.L_ANKLE, B.L_HEEL, B.L_FOOT,
))
_BODY_RIGHT = frozenset((
    B.R_SHOULDER, B.R_ELBOW, B.R_WRIST, B.R_PINKY, B.R_INDEX, B.R_THUMB,
    B.R_HIP, B.R_KNEE, B.R_ANKLE, B.R_HEEL, B.R_FOOT,
))
_BODY_TORSO_PAIRS = frozenset((
    (B.L_SHOULDER, B.R_SHOULDER), (B.L_HIP, B.R_HIP),
    (B.L_SHOULDER, B.L_HIP), (B.R_SHOULDER, B.R_HIP),
))


def body_edge_color(a: int, b: int) -> Tuple[int, int, int]:
    """Цвет связи: корпус — зелёный, левая сторона — голубая, правая — оранжевая."""
    if (a, b) in _BODY_TORSO_PAIRS or (b, a) in _BODY_TORSO_PAIRS:
        return BODY_COLORS["torso"]
    if a in _BODY_LEFT or b in _BODY_LEFT:
        return BODY_COLORS["left"]
    if a in _BODY_RIGHT or b in _BODY_RIGHT:
        return BODY_COLORS["right"]
    return BODY_COLORS["head"]


def body_joint_color(index: int) -> Tuple[int, int, int]:
    if index in _BODY_LEFT:
        return BODY_COLORS["left"]
    if index in _BODY_RIGHT:
        return BODY_COLORS["right"]
    return BODY_COLORS["head"]


def draw_body_ar(
    img: np.ndarray,
    points,
    min_visibility: float = 0.5,
    alpha: float = 0.85,
    show_joints: bool = True,
) -> int:
    """AR-скелет тела по 33 точкам Pose. Возвращает число нарисованных связей.

    Рисуются **только видимые** части: если человек в кадре по пояс, ноги
    просто не появятся — никаких «дорисованных» суставов из ниоткуда. Это
    важно и честно: пустая нога сразу показывает, что ниже пояса камера
    ничего не знает (и счётчик приседаний там не работает).
    """
    from .body import POSE_EDGES, POSE_EDGES_SMALL

    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 33 or pts.shape[1] < 2:
        return 0
    h, w = img.shape[:2]
    vis = pts[:, 3] if pts.shape[1] >= 4 else np.ones(pts.shape[0])
    xy = np.empty((pts.shape[0], 2), dtype=np.int32)
    xy[:, 0] = np.clip(pts[:, 0], 0.0, 1.0) * (w - 1)
    xy[:, 1] = np.clip(pts[:, 1], 0.0, 1.0) * (h - 1)

    k = max(min(h / 540.0, w / 960.0), 0.5)
    thick = max(int(6 * k), 3)
    joint_r = max(int(4 * k), 2)

    def edge_color(a: int, b: int) -> tuple:
        return body_edge_color(a, b)

    visible = vis >= min_visibility
    over = img.copy()
    drawn = 0
    for a, b in POSE_EDGES:
        if not (visible[a] and visible[b]):
            continue
        cv2.line(over, tuple(xy[a]), tuple(xy[b]), edge_color(a, b), thick, cv2.LINE_AA)
        drawn += 1
    # шея: Pose не даёт отдельной точки, поэтому рисуем линию от середины плеч
    if visible[B.L_SHOULDER] and visible[B.R_SHOULDER] and visible[B.NOSE]:
        neck = ((xy[B.L_SHOULDER] + xy[B.R_SHOULDER]) // 2)
        cv2.line(over, (int(neck[0]), int(neck[1])), tuple(xy[B.NOSE]),
                 BODY_COLORS["head"], max(thick - 1, 2), cv2.LINE_AA)
        drawn += 1
    for a, b in POSE_EDGES_SMALL:
        if visible[a] and visible[b]:
            cv2.line(over, tuple(xy[a]), tuple(xy[b]), edge_color(a, b),
                     max(thick // 2, 1), cv2.LINE_AA)
    cv2.addWeighted(over, alpha, img, 1.0 - alpha, 0, dst=img)

    if show_joints:
        for index in range(min(33, pts.shape[0])):
            if not visible[index]:
                continue
            cv2.circle(img, tuple(xy[index]), joint_r, (250, 250, 252), -1, cv2.LINE_AA)
            cv2.circle(img, tuple(xy[index]), joint_r, body_joint_color(index),
                       max(int(2 * k), 1), cv2.LINE_AA)
    return drawn


def _dashed_line(img, p1, p2, color, thick: int = 1, dash: int = 6) -> None:
    """Пунктирная линия — «это догадка, а не измерение»."""
    x1, y1 = int(p1[0]), int(p1[1])
    x2, y2 = int(p2[0]), int(p2[1])
    length = max(int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5), 1)
    step = max(dash, 3)
    for start in range(0, length, step * 2):
        t0, t1 = start / length, min((start + step) / length, 1.0)
        a = (int(x1 + (x2 - x1) * t0), int(y1 + (y2 - y1) * t0))
        b = (int(x1 + (x2 - x1) * t1), int(y1 + (y2 - y1) * t1))
        if a != b:
            cv2.line(img, a, b, color, thick, cv2.LINE_AA)


def draw_arm_hint(img: np.ndarray, hand: Hand, color=(120, 200, 120),
                  thick: int = 3) -> None:
    """Дорисовать предплечье за запястьем: рука читается как рука, а не кисть-обрубок.

    Направление — от центра ладони через запястье, длина — примерно две ладони.
    Это подсказка, поэтому пунктиром.
    """
    h, w = img.shape[:2]
    wrist = hand.xy(0) * np.array([w, h])
    palm = hand.palm_center * np.array([w, h])
    out = wrist - palm
    norm = float(np.linalg.norm(out))
    if norm < 1e-6:
        return
    out = out / norm
    end = wrist + out * max(float(hand.palm_size) * min(w, h) * 2.0, 24.0)
    _dashed_line(img, wrist, end, color, thick, dash=max(int(thick * 2), 4))


def draw_hand_ar(
    img: np.ndarray,
    hand: Hand,
    dim: bool = False,
    show_names: bool = True,
    pinch_threshold: float = 0.32,
    predicted: bool = False,
) -> None:
    """AR-«полосы» вдоль пальцев + контур ладони + индикатор щипка."""
    h, w = img.shape[:2]
    pts = hand.to_pixels(w, h).astype(np.int32)
    scale = max(float(hand.palm_size) * min(w, h), 20.0)
    thick = int(np.clip(scale * 0.17, 4, 16))

    for finger, chain in FINGERS.items():
        color = DIM if (dim or predicted) else FINGER_COLORS[finger]
        # у большого пальца цепочка начинается с CMC — иначе тянется лишняя
        # диагональ через всю ладонь
        joints = tuple(chain)
        for a, b in zip(joints[:-1], joints[1:]):
            if predicted:      # предсказание рисуем пунктиром: видно, что это догадка
                _dashed_line(img, pts[a], pts[b], color, max(thick // 2, 1))
            else:
                cv2.line(img, tuple(pts[a]), tuple(pts[b]), color, thick, cv2.LINE_AA)
            cv2.circle(img, tuple(pts[a]), max(thick // 2, 2), color, -1, cv2.LINE_AA)
        tip = tuple(pts[chain[-1]])
        cv2.circle(img, tip, max(thick // 2, 2), color, -1, cv2.LINE_AA)
        cv2.circle(img, tip, max(thick // 2 + 3, 5), (255, 255, 255), 2, cv2.LINE_AA)
        if show_names and not dim:
            name = FINGER_NAMES[finger]
            wname, hname = T.measure(name, 12)
            T.draw(img, name, (tip[0] - wname // 2, tip[1] - hname - thick // 2 - 8), 12, color)

    # ладонь: полупрозрачная заливка, чтобы рука читалась как одна фигура
    palm = np.array([pts[i] for i in (WRIST, THUMB_CMC, INDEX_MCP, MIDDLE_MCP,
                                      RING_MCP, PINKY_MCP)])
    if not dim:
        overlay = img.copy()
        cv2.fillPoly(overlay, [palm], (210, 210, 215))
        cv2.addWeighted(overlay, 0.22, img, 0.78, 0, img)
    cv2.polylines(img, [palm], True, (215, 215, 220), 1, cv2.LINE_AA)

    # щипок: расстояние большой–указательный в масштабе ладони
    ratio = float(np.linalg.norm(pts[THUMB_TIP].astype(float) - pts[INDEX_TIP].astype(float))) / scale
    pinching = ratio < pinch_threshold
    a, b = tuple(pts[THUMB_TIP]), tuple(pts[INDEX_TIP])
    mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
    if pinching:
        cv2.line(img, a, b, (90, 255, 90), 3, cv2.LINE_AA)
        cv2.circle(img, mid, max(thick, 10), (90, 255, 90), 2, cv2.LINE_AA)
        _label(img, "щипок", (mid[0] + 12, mid[1] - 10), 14, (150, 255, 150))
    else:
        cv2.line(img, a, b, (140, 140, 140), 1, cv2.LINE_AA)

    if show_names and not dim:
        side = "правая рука" if hand.handedness == "Right" else "левая рука"
        width, height = T.measure(side, 13)
        label_y = min(int(pts[WRIST][1]) + thick + 6, h - height - 34)
        T.draw(img, side, (int(pts[WRIST][0]) - width // 2, label_y), 13, FG)


def _draw_head_hint(img: np.ndarray, box: Sequence[float], note: str, k: float) -> None:
    """Пунктирная рамка головы: здесь лицо, хотя его самого не видно.

    Рамку даёт либо скелет тела (голова в позе видна даже когда лицо потеряно
    поворотом), либо предсказание по движению. Рисуем её намеренно скромно:
    это подсказка, а не измерение.
    """
    h, w = img.shape[:2]
    x0, y0 = int(float(box[0]) * w), int(float(box[1]) * h)
    x1, y1 = int(float(box[2]) * w), int(float(box[3]) * h)
    if x1 <= x0 or y1 <= y0:
        return
    _dashed_rect(img, (x0, y0), (x1, y1), (90, 150, 230), dash=max(int(8 * k), 4))
    if note:
        size = int(12 * k)
        width, height = T.measure(note, size)
        bx = max(int(6 * k), min(x0, w - width - int(12 * k)))
        by = max(int(6 * k), y0 - height - int(8 * k))
        _panel(img, bx, by, width + int(14 * k), height + int(10 * k), 0.55)
        T.draw(img, note, (bx + int(7 * k), by + int(4 * k)), size, (110, 170, 235))


# --------------------------------------------------------------------------- #
#  Лицо
# --------------------------------------------------------------------------- #
def draw_face_ar(img: np.ndarray, face: Face, expression: str = "") -> None:
    """Овал лица, глаза, брови, губы + подпись выражения."""
    h, w = img.shape[:2]
    pts = face.to_pixels(w, h)
    count = pts.shape[0]

    def poly(indices, color, closed=True, thickness=1) -> None:
        idx = [i for i in indices if i < count]
        if len(idx) < 2:
            return
        cv2.polylines(img, [pts[idx].astype(np.int32)], closed, color, thickness, cv2.LINE_AA)

    if count >= 468:
        poly(FACE_OVAL, (200, 200, 205), thickness=1)
    poly(_EYE_A_POLY, WARN, thickness=2)
    poly(_EYE_B_POLY, WARN, thickness=2)
    poly(LIPS_OUTER, (110, 190, 240))
    poly(LIPS_INNER, (120, 220, 220))
    for brow, sign in ((F.BROW_A, -1), (F.BROW_B, 1)):
        p = pts[brow].astype(np.int32)
        cv2.line(img, (p[0] - 22, p[1]), (p[0] + 22, p[1]), ACCENT, 2, cv2.LINE_AA)
    cv2.line(img, tuple(pts[F.NOSE_BRIDGE].astype(int)), tuple(pts[F.NOSE_TIP].astype(int)),
             WARN, 1, cv2.LINE_AA)

    # зрачки: точки радужки есть только у нейросетевого движка (478 точек)
    if face.has_iris:
        for group in (F.IRIS_A, F.IRIS_B):
            idx = [i for i in group if i < count]
            if not idx:
                continue
            ring = pts[idx].astype(np.int32)
            center = ring.mean(axis=0).astype(int)
            radius = max(int(np.linalg.norm(ring - center, axis=1).max()), 2)
            cv2.circle(img, tuple(center), radius, INFO, 1, cv2.LINE_AA)
            cv2.circle(img, tuple(center), max(radius // 2, 1), INFO, -1, cv2.LINE_AA)

    if expression:
        anchor = pts[F.CHIN].astype(int)
        width, _ = T.measure(expression, 14)
        _label(img, expression, (anchor[0] - width // 2, anchor[1] + 10), 14, INFO)


# --------------------------------------------------------------------------- #
#  Классическое CV
# --------------------------------------------------------------------------- #
def draw_classical(img: np.ndarray, shape) -> None:
    """Силуэт руки/объекта для запасного движка (без нейросети)."""
    h, w = img.shape[:2]
    if getattr(shape, "contour", None) is not None:
        cv2.drawContours(img, [shape.contour], -1, (120, 220, 120), 2)
    if getattr(shape, "hull", None) is not None:
        cv2.drawContours(img, [shape.hull], -1, (80, 170, 255), 1)
    px, py = getattr(shape, "pointer", (0.5, 0.5))
    px, py = float(px) * w, float(py) * h
    cv2.circle(img, (int(px), int(py)), 7, (0, 255, 255), 2, cv2.LINE_AA)
    _label(img, "силуэт (классический движок)", (14, h - 92), 13, DIM, alpha=0.45)


# --------------------------------------------------------------------------- #
#  Сводка
# --------------------------------------------------------------------------- #
def _draw_status(img, state: OverlayState, k: float) -> None:
    x, y = int(12 * k), int(12 * k)
    size_title, size_main, size_small = int(20 * k), int(15 * k), int(14 * k)

    if state.paused:
        status, color = "ПАУЗА (действия выключены)", BAD
    elif state.warmup:
        status, color = "РАЗМИНКА: встаньте в кадр", WARN
    elif state.hand_seen or state.face_seen:
        status, color = "РАБОТАЕТ", ACCENT
    else:
        status, color = "не вижу руку/лицо", WARN
    backend_line = f"движок: {state.backend or '—'}"
    fps_line = f"{state.fps:4.1f} кадр/с   {status}"
    pose_line = f"жест: {state.pose}"
    if state.hand_count > 1:
        pose_line += f"   (рук в кадре: {state.hand_count})"
    if state.dry_run:
        actions, acolor = "действия: ВЫКЛ (предпросмотр)", WARN
    elif state.actions_on:
        actions, acolor = "действия: ВКЛ", ACCENT
    else:
        actions, acolor = "действия: ВЫКЛ", WARN

    lines = ((backend_line, size_main), (fps_line, size_small), (pose_line, size_small),
             (actions, size_small))
    extras = []
    if state.modes_text:
        extras.append((state.modes_text, INFO))
    if state.side_text:             # какая стороной повёрнута кисть
        extras.append((state.side_text, DIM))
    if state.gaze_text:             # куда смотрит человек (и включена ли мышь глазами)
        extras.append((state.gaze_text, ACCENT if state.gaze_pointer else DIM))
    if state.body_text:             # поза тела и счёт упражнений
        extras.append((state.body_text, INFO))
    if state.sport_text:            # сгибания рук, T-поза, бокс
        extras.append((state.sport_text, ACCENT))
    if state.hand_note:             # кисть: предсказание или поправка физики
        extras.append((state.hand_note, WARN if state.hand_predicted else INFO))
    if state.roles_text:            # кто чем занят в режиме «две руки на роли»
        extras.append((state.roles_text, ACCENT))
    if state.settings_open:
        extras.append(("настройки: ползунки, мышь на паузе", WARN))
    # запас 12%: T.measure считает по bbox глифов и чуть занижает реальную
    # ширину отрисовки — без запаса длинная строка обрезалась «на живом месте»
    text_w = int(1.12 * max([T.measure(t, size)[0] for t, size in lines]
                            + [T.measure(t, size_small)[0] for t, _c in extras]
                            + [T.measure("AirMouse 0.2.0", size_title)[0]]))
    # панель не должна занимать больше половины кадра: длинную строку обрежем
    panel_w = min(text_w + int(24 * k), int(0.56 * img.shape[1]))
    n_extra = (int(bool(state.modes_text)) + int(bool(state.side_text))
               + int(bool(state.gaze_text)) + int(bool(state.roles_text))
               + int(bool(state.body_text)) + int(bool(state.hand_note))
               + int(bool(state.sport_text)) + int(state.settings_open))
    panel_h = int((104 + 30 * n_extra) * k)
    _panel(img, x, y, panel_w, panel_h, 0.62)

    title = "AirMouse"
    if state.version:
        title += f" {state.version}"
    T.draw(img, title, (x + 12, y + 8), size_title, FG)

    backend_color = ACCENT if "MediaPipe" in state.backend else WARN
    T.draw(img, backend_line, (x + 12, y + 34), size_main, backend_color)
    T.draw(img, fps_line, (x + 12, y + 56), size_small, color)
    T.draw(img, pose_line, (x + 12, y + 76), size_small, FG)
    T.draw(img, actions, (x + 12, y + 96), size_small, acolor)
    for i, (text, color) in enumerate(extras):
        T.draw(img, T.fit(text, size_small, panel_w - int(22 * k)),
               (x + 12, y + 116 + i * 20), size_small, color)

    if state.backend_note:
        note_y = y + panel_h + int(8 * k)
        _panel(img, x, note_y, int(430 * k), int(30 * k), 0.62)
        T.draw(img, state.backend_note[:64], (x + 10, note_y + 6), int(13 * k), WARN)


def _draw_face_panel(img, state: OverlayState, k: float) -> None:
    if not state.face_seen:
        return
    w = img.shape[1]
    panel_w = int(250 * k)
    if state.gaze_text:                  # строка про взгляд может быть длиннее панели
        panel_w = max(panel_w, int(T.measure(state.gaze_text, int(12 * k))[0] * 1.12) + int(24 * k))
    panel_w = min(panel_w, int(0.45 * w))
    x = w - panel_w - int(12 * k)
    y = int(12 * k)
    _panel(img, x, y, panel_w,
           int((188 + 18 * int(state.gaze_dwell > 0)) * k if state.gaze_text else 164 * k), 0.62)
    T.draw(img, "мимика лица", (x + 12, y + 8), int(16 * k), FG)
    bx, bw = x + 12, int(96 * k)
    # Порядок полос — от «что видно всегда» к «что видно редко». Рот отдельной
    # полосой: раньше открытый рот проявлялся только через улыбку (ширина губ
    # растёт и от улыбки, и от открытой челюсти) — и «удивление» не показывалось.
    open_mouth = float(getattr(state, "mouth_open", 0.0) or 0.0)
    _bar(img, bx, y + 58, bw, int(9 * k), state.ear, WARN, "глаза", 0.0, 0.45, int(12 * k))
    _bar(img, bx, y + 78, bw, int(9 * k), max(0.0, state.smile), ACCENT, "улыбка", -0.05, 0.15, int(12 * k))
    _bar(img, bx, y + 98, bw, int(9 * k), max(0.0, state.brow), ACCENT, "брови", -0.05, 0.15, int(12 * k))
    _bar(img, bx, y + 118, bw, int(9 * k), max(0.0, state.sad), WARN, "грусть", 0.0, 0.08, int(12 * k))
    _bar(img, bx, y + 138, bw, int(9 * k), open_mouth, INFO, "рот", 0.0, 0.55, int(12 * k))
    if state.gaze_text:
        T.draw(img, T.fit(state.gaze_text, int(12 * k), panel_w - int(24 * k)),
               (x + 12, y + int(158 * k)), int(12 * k),
               ACCENT if state.gaze_pointer else DIM)
    if state.gaze_dwell > 0.0:
        # прогресс «удержание взгляда → клик»: видно, что вот-вот сработает
        _bar(img, bx, y + int(176 * k), bw, int(9 * k), state.gaze_dwell,
             ACCENT, "удержание", 0.0, 1.0, int(12 * k))


def _draw_gaze_calibration(img: np.ndarray, state: OverlayState, k: float) -> None:
    """Экран калибровки взгляда: затенение, прицел на точке и подсказка."""
    if not state.calib_active or state.calib_target is None:
        return
    h, w = img.shape[:2]
    shade = img.copy()
    cv2.rectangle(shade, (0, 0), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(shade, 0.72, img, 0.28, 0, img)

    tx = int(float(state.calib_target[0]) * w)
    ty = int(float(state.calib_target[1]) * h)
    r = int(28 * k)
    cv2.circle(img, (tx, ty), r, (60, 220, 120), 3, cv2.LINE_AA)
    cv2.circle(img, (tx, ty), int(6 * k), (60, 220, 120), -1, cv2.LINE_AA)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.line(img, (tx + dx * r, ty + dy * r),
                 (tx + dx * int(r * 1.8), ty + dy * int(r * 1.8)),
                 (60, 220, 120), 2, cv2.LINE_AA)

    text = state.calib_text or "смотрите на кружок и нажмите ПРОБЕЛ"
    size = int(15 * k)
    width, height = T.measure(text, size)
    bx = max(int(10 * k), w // 2 - width // 2 - int(16 * k))
    by = int(12 * k)
    _panel(img, bx, by, width + int(32 * k), height + int(18 * k), 0.72)
    T.draw(img, text, (bx + int(16 * k), by + int(8 * k)), size, FG)


def render_gaze_calibration(size: Tuple[int, int],
                            state: OverlayState) -> np.ndarray:
    """Полноэкранный экран калибровки взгляда — пиксель в пиксель с окном.

    ``size`` — размер **холста ровно как у окна** (``cv2.getWindowImageRect``).
    Это принципиально: если нарисовать холст «по размеру из настроек мыши», то
    окно на экране с масштабом 125% растянет картинку — всё станет крупнее, а
    прицел уедет с угла. Здесь холст и картинка в окне совпадают 1:1, поэтому
    прицел рисуется в самом угловом пикселе экрана.
    """
    w, h = max(int(size[0]), 320), max(int(size[1]), 240)
    img = np.full((h, w, 3), (16, 17, 20), dtype=np.uint8)
    # рамка по краю: видно, где кончается экран
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (48, 50, 56), 1)

    k = max(min(h / 1080.0, w / 1920.0), 0.55)
    if state.calib_pursuit:
        # след точки: видно, что она ползёт плавно, и куда она уползла
        trail = list(state.calib_trail or ())
        for i, point in enumerate(trail[-60:]):
            if len(point) < 2:
                continue
            px = int(round(float(point[0]) * (w - 1)))
            py = int(round(float(point[1]) * (h - 1)))
            fade = (i + 1) / max(len(trail[-60:]), 1)
            color = (int(40 + 30 * fade), int(40 + 40 * fade), int(120 + 60 * fade))
            cv2.circle(img, (px, py), max(int(3 * k), 1), color, -1, cv2.LINE_AA)
    if state.calib_target is not None:
        # доля экрана -> пиксель холста: 0 -> 0, 1 -> последний пиксель
        tx = int(round(float(state.calib_target[0]) * (w - 1)))
        ty = int(round(float(state.calib_target[1]) * (h - 1)))
        if state.calib_pursuit:
            _draw_pursuit_dot(img, tx, ty, k)
        else:
            _draw_calibration_target(img, tx, ty, k)

    # подсказка сверху по центру
    text = state.calib_text or "смотрите в точку и нажмите ПРОБЕЛ"
    size_px = int(20 * k)
    width, height = T.measure(text, size_px)
    bx = max(8, w // 2 - width // 2 - int(22 * k))
    by = int(16 * k)
    _panel(img, bx, by, width + int(44 * k), height + int(48 * k), 0.82)
    T.draw(img, text, (bx + int(22 * k), by + int(10 * k)), size_px, FG)
    hint = "ПРОБЕЛ — зафиксировать · ESC — отмена · B — начать заново"
    hint_size = int(13 * k)
    hw, _ = T.measure(hint, hint_size)
    T.draw(img, hint, (w // 2 - hw // 2, by + height + int(20 * k)), hint_size, DIM)

    # прогресс и точные размеры — чтобы можно было проверить глазами
    if state.calib_pursuit:
        _draw_pursuit_progress(img, state, k)
    else:
        _draw_calibration_progress(img, state, k)
    debug = state.calib_debug or f"холст {w}×{h}"
    dbg_size = int(11 * k)
    dw, _dh = T.measure(debug, dbg_size)
    T.draw(img, debug, (w // 2 - dw // 2, h - int(30 * k)), dbg_size, (110, 112, 120))
    return img


def _draw_calibration_target(img: np.ndarray, tx: int, ty: int, k: float) -> None:
    """Прицел в точке экрана: «Г» по самым краям монитора или кольцо в центре."""
    h, w = img.shape[:2]
    color = (90, 235, 130)
    arm = int(min(max(min(w, h) * 0.10, 60.0), 160.0) * k)
    thick = max(int(7 * k), 3)

    at_left, at_right = tx <= 4, tx >= w - 5
    at_top, at_bottom = ty <= 4, ty >= h - 5
    corner = (at_left or at_right) and (at_top or at_bottom)
    if corner:
        # Линии «Г» лежат вплотную к краю: их внешняя кромка — ровно край
        # экрана, а толщина целиком видна (сдвиг на полтолщины внутрь).
        half = thick // 2
        x_edge = half if at_left else w - 1 - half
        y_edge = half if at_top else h - 1 - half
        x_in = x_edge + arm if at_left else x_edge - arm
        y_in = y_edge + arm if at_top else y_edge - arm
        cv2.line(img, (x_edge, y_edge), (x_in, y_edge), color, thick, cv2.LINE_AA)
        cv2.line(img, (x_edge, y_edge), (x_edge, y_in), color, thick, cv2.LINE_AA)
        # яркая точка ровно в угловом пикселе (у края видна квадрантом)
        cv2.circle(img, (tx, ty), max(int(6 * k), 3), color, -1, cv2.LINE_AA)
        return

    r = int(34 * k)
    cv2.circle(img, (tx, ty), r, color, max(int(3 * k), 2), cv2.LINE_AA)
    cv2.circle(img, (tx, ty), max(int(7 * k), 3), color, -1, cv2.LINE_AA)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.line(img, (tx + dx * r, ty + dy * r),
                 (tx + dx * int(r * 1.7), ty + dy * int(r * 1.7)),
                 color, max(int(2 * k), 1), cv2.LINE_AA)


def _draw_profile_banner(img: np.ndarray, state: OverlayState, k: float) -> None:
    """Верхняя полоса «профиля движений»: шаг, подсказка, полоса прогресса."""
    h, w = img.shape[:2]
    title = state.profile_text
    hint = state.profile_hint or ""
    t_size = int(18 * k)
    h_size = int(13 * k)
    tw, th = T.measure(title, t_size)
    hw, hh = T.measure(hint, h_size) if hint else (0, 0)
    pad = int(20 * k)
    box_w = min(w - int(24 * k), max(tw, hw) + 2 * pad)
    bar_h = max(int(7 * k), 3)
    box_h = th + (hh + int(6 * k) if hint else 0) + bar_h + int(24 * k)
    x = w // 2 - box_w // 2
    # внизу по центру: сверху уже живут сводка и панель мимики, а там, где
    # идёт профиль, важнее не перекрыть лицо и цифры распознавания
    y = max(int(12 * k), h - box_h - int(34 * k))
    _panel(img, x, y, box_w, box_h, 0.86)
    T.draw(img, title, (x + pad, y + int(8 * k)), t_size, ACCENT)
    if hint:
        T.draw(img, hint, (x + pad, y + th + int(12 * k)), h_size, FG)
    bar_y = y + box_h - bar_h - int(8 * k)
    inner = box_w - 2 * pad
    cv2.rectangle(img, (x + pad, bar_y), (x + pad + inner, bar_y + bar_h),
                  (60, 62, 70), -1, cv2.LINE_AA)
    done = int(inner * min(max(float(state.profile_progress or 0.0), 0.0), 1.0))
    if done > 0:
        cv2.rectangle(img, (x + pad, bar_y), (x + pad + done, bar_y + bar_h),
                      (90, 235, 130), -1, cv2.LINE_AA)


def _draw_pursuit_dot(img: np.ndarray, tx: int, ty: int, k: float) -> None:
    """Красная точка калибровки взгляда: крупная, с ореолом и перекрестьем.

    Крупная и красная — потому что вести взгляд за маленькой серой точкой
    тяжело, а красный почти не смешивается с интерфейсом (Apple в Eye Tracking
    рисует точку того же размера, что и прицел мыши).
    """
    r = max(int(13 * k), 7)
    glow = max(int(30 * k), 16)
    over = img.copy()
    cv2.circle(over, (tx, ty), glow, (40, 40, 220), -1, cv2.LINE_AA)
    cv2.addWeighted(over, 0.22, img, 0.78, 0, dst=img)
    cv2.circle(img, (tx, ty), r, (40, 40, 235), -1, cv2.LINE_AA)
    cv2.circle(img, (tx, ty), r + max(int(6 * k), 3), (235, 235, 255),
               max(int(2 * k), 1), cv2.LINE_AA)
    cv2.circle(img, (tx, ty), max(int(3 * k), 2), (250, 250, 255), -1, cv2.LINE_AA)


def _draw_pursuit_progress(img: np.ndarray, state: OverlayState, k: float) -> None:
    """Полоска времени: сколько ещё вести взгляд за точкой."""
    h, w = img.shape[:2]
    bar_w = int(min(w * 0.5, 620 * k))
    bar_h = max(int(8 * k), 4)
    x0 = w // 2 - bar_w // 2
    y0 = h - int(52 * k)
    cv2.rectangle(img, (x0, y0), (x0 + bar_w, y0 + bar_h), (60, 62, 70), -1, cv2.LINE_AA)
    done = int(bar_w * min(max(float(state.calib_progress or 0.0), 0.0), 1.0))
    if done > 0:
        cv2.rectangle(img, (x0, y0), (x0 + done, y0 + bar_h), (90, 235, 130), -1,
                      cv2.LINE_AA)


def _draw_calibration_progress(img: np.ndarray, state: OverlayState, k: float) -> None:
    """Точки внизу: сколько шагов калибровки уже пройдено."""
    from .gaze import CALIBRATION_TARGETS

    total = len(CALIBRATION_TARGETS)
    done = getattr(state, "calib_done", 0) or 0
    r = max(int(7 * k), 4)
    gap = int(26 * k)
    h, w = img.shape[:2]
    y = h - int(58 * k)
    x = w // 2 - (total - 1) * gap // 2
    for i in range(total):
        color = (90, 235, 130) if i < done else (90, 92, 100)
        cv2.circle(img, (x + i * gap, y), r, color, -1, cv2.LINE_AA)


def _draw_events(img, state: OverlayState, k: float) -> None:
    lines = list(state.events)[-3:]
    if not lines:
        return
    h = img.shape[0]
    size = int(14 * k)
    width = max(T.measure(line, size)[0] for line in lines) + int(24 * k)
    left = int(12 * k)
    top = h - int(42 * k) - len(lines) * int(20 * k)
    _panel(img, left, top, width, len(lines) * int(20 * k) + int(22 * k), 0.55)
    T.draw(img, "что произошло:", (left + 10, top + 4), int(12 * k), DIM)
    for i, line in enumerate(lines):
        color = ACCENT if i == len(lines) - 1 else FG
        T.draw(img, line, (left + 12, top + int(20 * k) + i * int(19 * k)), size, color)


def _draw_help(img, state: OverlayState, k: float) -> None:
    """Справка: слева жесты рукой и клавиши, справа мимика и две руки."""
    h, w = img.shape[:2]
    _panel(img, 0, 0, w, h, 0.94)
    pad = int(26 * k)
    title_size = int(22 * k)
    body = int(14 * k)
    row = int(21 * k)
    T.draw(img, "Что умеет AirMouse", (pad, pad), title_size, FG)

    left_x = pad
    right_x = int(w * 0.50)
    action_dx = int(300 * k)          # где в колонке начинается «→ действие»
    y = pad + int(40 * k)

    def header(text: str, x: int, yy: int) -> int:
        T.draw(img, text, (x, yy), body, ACCENT)
        return yy + int(24 * k)

    def rows(items, x: int, yy: int, name_w: int = 13) -> int:
        for name, how, action in items:
            T.draw(img, f"{name:<{name_w}} {how}", (x, yy), body, FG)
            T.draw(img, f"→ {action}", (x + action_dx, yy), body, INFO)
            yy += row
        return yy

    # ---------------- левая колонка: рука, две руки, клавиши ----------------
    y = header("Жесты (рука):", left_x, y)
    y = rows(HELP_GESTURES, left_x, y)
    y += int(6 * k)
    y = header("Две руки одновременно:", left_x, y)
    y = rows(HELP_TWO_HANDS, left_x, y)
    y += int(6 * k)
    y = header("Клавиши:", left_x, y)
    # две колонки: иначе список клавиш не влезает в окно
    per_col = (len(HELP_KEYS) + 1) // 2
    col_dx = int(200 * k)
    for i, (key, action) in enumerate(HELP_KEYS):
        cx = left_x + (col_dx if i >= per_col else 0)
        cy = y + (i - per_col if i >= per_col else i) * int(19 * k)
        T.draw(img, f"{key:<9} {action}", (cx, cy), int(12.5 * k), FG)
    y += per_col * int(19 * k)

    # ---------------- правая колонка: мимика ----------------
    yy = pad + int(40 * k)
    yy = header("Мимика и голова:", right_x, yy)
    yy = rows(HELP_FACE, right_x, yy, name_w=12)
    yy += int(4 * k)
    T.draw(img, "моргание — оба глаза; подмигивание — ровно один.",
           (right_x, yy), int(12 * k), DIM)
    yy += int(16 * k)
    T.draw(img, "Закрыты дольше 4 с — не считается, пока не откроете.",
           (right_x, yy), int(12 * k), DIM)
    yy += int(16 * k)
    T.draw(img, "Действия мимики включаются в config/airmouse.json",
           (right_x, yy), int(12 * k), DIM)
    yy += int(30 * k)
    yy = header("Сторона кисти (клавиша K — калибровка):", right_x, yy)
    T.draw(img, "ладонью: двойной клик / пауза / мышь головой", (right_x, yy), int(12 * k), FG)
    yy += int(17 * k)
    T.draw(img, "тылом: правый клик / двойной клик / пауза", (right_x, yy), int(12 * k), FG)
    yy += int(24 * k)
    yy = header("Роли рук:", right_x, yy)
    T.draw(img, "одна ведёт курсор, вторая нажимает", (right_x, yy), body, FG)
    yy += int(19 * k)
    T.draw(img, "включается: config set hand.roles=split", (right_x, yy), int(12 * k), DIM)
    yy += int(24 * k)
    yy = header("Мышь глазами (клавиша G):", right_x, yy)
    T.draw(img, "B — калибровка на весь экран: смотрите в угол", (right_x, yy), int(12 * k), FG)
    yy += int(17 * k)
    T.draw(img, "без калибровки — скоростной режим (нужны зрачки)", (right_x, yy), int(12 * k), DIM)

    T.draw(img, "I или Tab — закрыть справку", (pad, h - int(28 * k)), int(13 * k), DIM)


# --------------------------------------------------------------------------- #
#  Главная функция
# --------------------------------------------------------------------------- #
def render(
    frame: np.ndarray,
    state: OverlayState,
    hands: Optional[List[Hand]] = None,
    face: Optional[Face] = None,
    shape=None,
    metrics=None,
    primary: int = 0,
    body=None,
    body_min_visibility: float = 0.35,
    predicted: Optional[List[bool]] = None,
) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    k = max(min(h / 540.0, w / 960.0), 0.5)

    if state.calib_active:
        # калибровка взгляда: на экране только прицел и подсказка, чтобы
        # человек смотрел в точку, а не на панели с цифрами
        _draw_gaze_calibration(img, state, k)
        return img

    if state.profile_text:
        # профиль движений: картинка с камерой остаётся видимой — человеку
        # нужно видеть, что его жест распознали, а не только читать текст
        _draw_profile_banner(img, state, k)

    # зона, в которой рука управляет курсором
    if not state.head_pointer and not state.paused:
        x0, y0, x1, y1 = state.active_box
        p1 = (int(x0 * w), int(y0 * h))
        p2 = (int(x1 * w), int(y1 * h))
        _dashed_rect(img, p1, p2, (95, 95, 100))
        zone_text = "зона управления курсором"
        zw, _ = T.measure(zone_text, int(12 * k))
        _label(img, zone_text, (p2[0] - zw - int(8 * k), p1[1] + int(6 * k)),
               int(12 * k), DIM, alpha=0.4)

    if body is not None:
        draw_body_ar(img, body, min_visibility=body_min_visibility)

    is_predicted = list(predicted or [])
    for i, hand in enumerate(hands or []):
        secondary = i != primary
        predicted_hand = bool(is_predicted[i]) if i < len(is_predicted) else False
        # у предсказанной кисти не подписываем пальцы: подписи по догадке
        # только путают, человек и так видит, что поза приблизительная
        draw_hand_ar(img, hand, dim=state.paused or secondary,
                     show_names=state.show_names and not secondary and not predicted_hand,
                     pinch_threshold=state.pinch_threshold,
                     predicted=predicted_hand)
        # предплечье: кисть без руки выглядит обрубком, а вместе с ним читается
        # как рука — особенно когда она «доехала» из предсказания
        draw_arm_hint(img, hand,
                      color=WARN if predicted_hand else (110, 170, 110),
                      thick=int(3 * k))
        if predicted_hand:
            # подпись над кистью: внутри ладони она закрывала точки
            pts = hand.to_pixels(w, h)
            text = "предсказано: кисти не видно"
            width, _ = T.measure(text, int(12 * k))
            top = int(pts[:, 1].min() - 22 * k)
            centre = int(pts[:, 0].mean() - width / 2)
            _label(img, text, (centre, max(top, int(8 * k))),
                   int(12 * k), WARN, alpha=0.5)
        if secondary:  # вторая рука курсор не двигает — только нажатия
            pts = hand.to_pixels(w, h)
            anchor = pts[MIDDLE_MCP].astype(int)
            text = ("вторая рука: нажатия и жесты" if state.split_roles
                    else "вторая рука (не управляет)")
            width, height = T.measure(text, 12)
            _label(img, text, (int(anchor[0] - width // 2), int(anchor[1] - height - 16)),
                   12, DIM, alpha=0.5)
    if face is not None:
        draw_face_ar(img, face, state.expression)
    elif state.face_hint is not None:
        # лица нет, но голова точно где-то здесь: по телу или по движению
        _draw_head_hint(img, state.face_hint, state.face_hint_note, k)
    if shape is not None:
        draw_classical(img, shape)

    if state.show_help:  # справка закрывает собой всю сводку, чтобы не мешала
        _draw_help(img, state, k)
        return img

    _draw_status(img, state, k)
    _draw_face_panel(img, state, k)
    if not state.profile_text:      # журнал не мешает полосе профиля внизу
        _draw_events(img, state, k)

    # прицел: показываем, куда именно попадёт клик
    if state.aiming and state.aim is not None:
        ax, ay = int(float(state.aim[0]) * w), int(float(state.aim[1]) * h)
        cv2.circle(img, (ax, ay), int(16 * k), (0, 255, 255), 2, cv2.LINE_AA)
        cv2.line(img, (ax - int(22 * k), ay), (ax + int(22 * k), ay), (0, 255, 255), 1, cv2.LINE_AA)
        cv2.line(img, (ax, ay - int(22 * k)), (ax, ay + int(22 * k)), (0, 255, 255), 1, cv2.LINE_AA)
        _label(img, "прицел: курсор заморожен", (ax + int(22 * k), ay - int(10 * k)),
               int(13 * k), (0, 255, 255), alpha=0.5)

    if state.two_hand_hint:      # подсказка двумя руками — под сводкой слева
        n_extra = (int(bool(state.modes_text)) + int(bool(state.side_text))
                   + int(bool(state.gaze_text)) + int(bool(state.roles_text))
                   + int(bool(state.body_text)) + int(bool(state.hand_note))
                   + int(state.settings_open))
        hint_y = int((12 + 104 + 30 * n_extra + 8) * k)
        _label(img, state.two_hand_hint, (int(12 * k), hint_y),
               int(14 * k), ACCENT, alpha=0.55)

    if state.lip_word:
        label = f"по губам: {state.lip_word}"
        width, height = T.measure(label, int(16 * k))
        _label(img, label, (w // 2 - width // 2, int(12 * k)),
               int(16 * k), ACCENT, alpha=0.7)

    hint_size = int(13 * k)
    hint_w, _ = T.measure(state.hints, hint_size)
    T.draw(img, state.hints, (w - hint_w - int(14 * k), h - int(24 * k)), hint_size, DIM)

    if state.paused:
        label = "ПАУЗА"
        size = int(38 * k)
        width, height = T.measure(label, size)
        _label(img, label, (w // 2 - width // 2, h // 2 - height // 2), size, BAD, alpha=0.35)
        sub = "нажмите P, чтобы продолжить"
        sub_w, _ = T.measure(sub, int(15 * k))
        T.draw(img, sub, (w // 2 - sub_w // 2, h // 2 + int(26 * k)), int(15 * k), FG)
    elif state.warmup:
        label = "ПРИГОТОВЬТЕСЬ"
        size = int(30 * k)
        width, height = T.measure(label, size)
        _label(img, label, (w // 2 - width // 2, h // 2 - height // 2), size, WARN, alpha=0.4)

    return img
