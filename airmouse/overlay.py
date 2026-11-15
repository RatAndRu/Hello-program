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
    ("ладонь", "ладонь неподвижно 1.3 с", "пауза"),
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
    ("подмигивание", "один глаз", "правый клик"),
)

HELP_KEYS = (
    ("Q / Esc", "выход"),
    ("P", "пауза (действия не выполняются)"),
    ("H", "мышь головой вкл/выкл"),
    ("M", "сменить движок (нейросеть ↔ классический CV)"),
    ("I / Tab", "эта справка"),
    ("пробел", "статистика в журнал"),
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
    events: List[str] = field(default_factory=list)   # последние действия (готовые строки)
    active_box: Sequence[float] = (0.16, 0.14, 0.84, 0.86)
    hints: str = "Q выход   P пауза   H мышь головой   M движок   I справка"
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
def draw_hand_ar(
    img: np.ndarray,
    hand: Hand,
    dim: bool = False,
    show_names: bool = True,
    pinch_threshold: float = 0.32,
) -> None:
    """AR-«полосы» вдоль пальцев + контур ладони + индикатор щипка."""
    h, w = img.shape[:2]
    pts = hand.to_pixels(w, h).astype(np.int32)
    scale = max(float(hand.palm_size) * min(w, h), 20.0)
    thick = int(np.clip(scale * 0.17, 4, 16))

    for finger, chain in FINGERS.items():
        color = DIM if dim else FINGER_COLORS[finger]
        # у большого пальца цепочка начинается с CMC — иначе тянется лишняя
        # диагональ через всю ладонь
        joints = tuple(chain)
        for a, b in zip(joints[:-1], joints[1:]):
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
    text_w = max([T.measure(t, size)[0] for t, size in lines] + [T.measure("AirMouse 0.2.0", size_title)[0]])
    panel_w = text_w + int(24 * k)
    panel_h = int((134 if state.roles_text else 104) * k)
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
    if state.roles_text:            # кто чем занят в режиме «две руки на роли»
        T.draw(img, state.roles_text, (x + 12, y + 116), size_small, ACCENT)

    if state.backend_note:
        note_y = y + panel_h + int(8 * k)
        _panel(img, x, note_y, int(430 * k), int(30 * k), 0.62)
        T.draw(img, state.backend_note[:64], (x + 10, note_y + 6), int(13 * k), WARN)


def _draw_face_panel(img, state: OverlayState, k: float) -> None:
    if not state.face_seen:
        return
    w = img.shape[1]
    panel_w = int(250 * k)
    x = w - panel_w - int(12 * k)
    y = int(12 * k)
    _panel(img, x, y, panel_w, int(146 * k), 0.62)
    T.draw(img, "мимика лица", (x + 12, y + 8), int(16 * k), FG)
    bx, bw = x + 12, int(96 * k)
    _bar(img, bx, y + 58, bw, int(9 * k), state.ear, WARN, "глаза", 0.0, 0.45, int(12 * k))
    _bar(img, bx, y + 78, bw, int(9 * k), max(0.0, state.smile), ACCENT, "улыбка", -0.05, 0.15, int(12 * k))
    _bar(img, bx, y + 98, bw, int(9 * k), max(0.0, state.brow), ACCENT, "брови", -0.05, 0.15, int(12 * k))
    _bar(img, bx, y + 118, bw, int(9 * k), max(0.0, state.sad), WARN, "грусть", 0.0, 0.08, int(12 * k))


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
    head_gap = int(26 * k)
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
    for key, action in HELP_KEYS:
        T.draw(img, f"{key:<10} {action}", (left_x, y), body, FG)
        y += int(19 * k)

    # ---------------- правая колонка: мимика ----------------
    yy = pad + int(40 * k)
    yy = header("Мимика и голова:", right_x, yy)
    yy = rows(HELP_FACE, right_x, yy, name_w=12)
    yy += int(4 * k)
    T.draw(img, "жесты мимики только показываются в окне,", (right_x, yy), int(12 * k), DIM)
    yy += int(16 * k)
    T.draw(img, "действия включаются в config/airmouse.json", (right_x, yy), int(12 * k), DIM)
    yy += int(34 * k)
    yy = header("Роли рук:", right_x, yy)
    T.draw(img, "одна ведёт курсор, вторая нажимает", (right_x, yy), body, FG)
    yy += int(19 * k)
    T.draw(img, "включается: config set hand.roles=split", (right_x, yy), int(12 * k), DIM)

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
) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    k = max(min(h / 540.0, w / 960.0), 0.5)

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

    for i, hand in enumerate(hands or []):
        secondary = i != primary
        draw_hand_ar(img, hand, dim=state.paused or secondary,
                     show_names=state.show_names and not secondary,
                     pinch_threshold=state.pinch_threshold)
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
    if shape is not None:
        draw_classical(img, shape)

    if state.show_help:  # справка закрывает собой всю сводку, чтобы не мешала
        _draw_help(img, state, k)
        return img

    _draw_status(img, state, k)
    _draw_face_panel(img, state, k)
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
        hint_y = int((12 + (134 if state.roles_text else 104) + 8) * k)
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
