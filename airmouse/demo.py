"""Демонстрация без камеры: синтетическая рука и лицо проходят весь конвейер.

Результат — анимированная GIF-ка, раскадровка PNG и журнал событий.
Полезно и для проверки логики, и как наглядное «что умеет» для человека,
которому лень запускать управление на своей машине.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .actions import ActionRouter, DryRunBackend
from .config import AppConfig
from .face import FaceFSM, measure_face
from .gestures import (
    Event,
    HandFSM,
    POSE_TITLES_RU,
    analyze_hand,
    classify_pose,
    synthetic_hand,
)
from .landmarks import Hand, Face
from .overlay import OverlayState, render
from .pointer import PointerMapper
from .synthetic import synthetic_face

FPS = 25
W, H = 640, 360
SCREEN = (1920, 1080)

OTHER_FINGERS = {"middle": 1, "ring": 1, "pinky": 1}
ALL_CURLED = {k: 1.0 for k in ("thumb", "index", "middle", "ring", "pinky")}


# --------------------------------------------------------------------------- #
@dataclass
class Segment:
    title: str
    duration: float
    fn: Callable[[float], Tuple[Optional[Hand], Optional[Face]]]


def _hand(center=(0.55, 0.74), scale=0.19, **kwargs) -> Hand:
    return synthetic_hand(center=center, scale=scale, **kwargs)


def _face(**kwargs) -> Face:
    params = dict(center=(0.5, 0.26), scale=0.55)
    params.update(kwargs)
    return synthetic_face(**params)


def build_segments() -> List[Segment]:
    def move(t):
        # указательный палец ведёт курсор (остальные сжаты)
        x = 0.36 + 0.30 * (t / 1.6)
        y = 0.76 + 0.04 * math.sin(2 * math.pi * t / 0.8)
        return _hand(center=(x, y), curl=dict(OTHER_FINGERS)), _face()

    def point(t):
        x = 0.66 - 0.22 * (t / 1.0)
        return _hand(center=(x, 0.72), curl=dict(OTHER_FINGERS)), _face()

    def click(t):
        pinch = 0.20 < t < 0.45
        return (
            _hand(center=(0.42, 0.72), curl=dict(OTHER_FINGERS), pinch_index=pinch),
            _face(),
        )

    def drag(t):
        pinch = 0.25 < t < 1.20
        x = 0.40 + (0.22 * (t / 1.4) if pinch else 0.0)
        return (
            _hand(center=(x, 0.70), curl=dict(OTHER_FINGERS), pinch_index=pinch),
            _face(),
        )

    def scroll(t):
        y = 0.85 - 0.28 * (t / 1.2)
        return _hand(center=(0.55, y), curl=dict(ALL_CURLED)), _face()

    def pause(t):
        return _hand(center=(0.5, 0.72)), _face()

    def no_hand(t):
        return None, _face()

    def resume(t):
        return _hand(center=(0.5, 0.72)), _face()

    def thumb(t):
        curl = {"index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0}
        return _hand(center=(0.6, 0.72), curl=curl), _face()

    def ok_sign(t):
        curl = {"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0}
        return _hand(center=(0.58, 0.72), curl=curl, pinch_index=True), _face()

    def rock(t):
        curl = {"index": 0.0, "middle": 1.0, "ring": 1.0, "pinky": 0.0}
        return _hand(center=(0.52, 0.72), curl=curl), _face()

    def three(t):
        curl = {"index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 1.0}
        return _hand(center=(0.52, 0.72), curl=curl), _face()

    def aim(t):
        # пальцы сходятся: курсор замирает на точке прицела
        pinch = 0.25 < t < 0.55      # коротко: только «прицел», без перетаскивания
        return _hand(center=(0.44, 0.72), curl=dict(OTHER_FINGERS), pinch_index=pinch), _face()

    def blink(t):
        closed = (0.40 <= t < 0.52) or (0.72 <= t < 0.84)
        ear = (0.08, 0.08) if closed else (0.30, 0.30)
        return None, _face(ear=ear)

    def smile(t):
        value = 0.035 if 0.30 < t < 1.25 else 0.0
        return None, _face(smile=value)

    def brows(t):
        value = 0.035 if 0.25 < t < 1.10 else 0.0
        phase = max(0.0, t - 1.10)
        yaw = 18.0 * math.sin(phase * 6.0) if phase > 0 else 0.0
        return None, _face(brow=value, yaw=yaw)

    return [
        Segment("указательный палец ведёт курсор", 1.6, move),
        Segment("указательный палец", 1.0, point),
        Segment("щипок = левый клик", 0.9, click),
        Segment("щипок с удержанием = перетаскивание", 1.4, drag),
        Segment("кулак + движение = прокрутка", 1.2, scroll),
        Segment("раскрытая ладонь = просто ведёт курсор", 1.0, pause),
        Segment("рука опущена", 0.4, no_hand),
        Segment("ладонь снова — ничего не нажимает", 1.0, resume),
        Segment("большой палец = двойной клик", 0.9, thumb),
        Segment("прицел: пальцы сходятся", 0.9, aim),
        Segment("жест ОК = двойной клик", 1.1, ok_sign),
        Segment("три пальца = мышь головой", 1.2, three),
        Segment("двойное моргание = клик", 1.4, blink),
        Segment("брови и поворот головы", 1.8, brows),
        Segment("улыбка — индикатор в окне", 1.5, smile),
        Segment("коза = пауза (в самом конце)", 1.3, rock),
    ]


# --------------------------------------------------------------------------- #
def _background(w: int = W, h: int = H) -> np.ndarray:
    """Синтетический «кадр с камеры»: мягкий градиент и лёгкий шум."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    y = (yy / h)[..., None]
    x = (xx / w)[..., None]
    top = np.array([52, 46, 40], dtype=np.float32)      # BGR, тёплый верх
    bottom = np.array([26, 24, 24], dtype=np.float32)
    img = top * (1 - y) + bottom * y
    img += (x - 0.5) * 10.0
    rng = np.random.default_rng(1)
    img += rng.normal(0, 1.6, (h, w, 1))
    # «винтетка» по краям
    d = np.sqrt((x - 0.5) ** 2 + (y - 0.5) ** 2)
    img *= np.clip(1.15 - 0.55 * d, 0.35, 1.0)
    return np.clip(img, 0, 255).astype(np.uint8)


def _draw_cursor(canvas: np.ndarray, pos: Tuple[int, int]) -> None:
    h, w = canvas.shape[:2]
    x = int(pos[0] / SCREEN[0] * w)
    y = int(pos[1] / SCREEN[1] * h)
    pts = np.array([[x, y], [x + 14, y + 13], [x + 8, y + 14], [x + 12, y + 21],
                    [x + 7, y + 23], [x + 4, y + 16], [x, y + 20]], dtype=np.int32)
    cv2.fillPoly(canvas, [pts], (60, 60, 240))
    cv2.polylines(canvas, [pts], True, (245, 245, 245), 1, cv2.LINE_AA)


@dataclass
class DemoResult:
    frames: int
    events: int
    gif: Path
    storyboard: Path
    log: Path
    event_names: List[str] = field(default_factory=list)


def run_demo(cfg: AppConfig, out_dir: Path | str = "output") -> DemoResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    hand_fsm = HandFSM(cfg.hand)
    face_fsm = FaceFSM(cfg.face)
    pointer = PointerMapper(cfg.pointer, SCREEN)
    backend = DryRunBackend(SCREEN)
    router = ActionRouter(backend, cfg)
    state = OverlayState(active_box=cfg.pointer.active_box,
                         hints="demo: synthetic hand + face")

    bg = _background()
    segments = build_segments()
    frames: List[np.ndarray] = []
    captions: List[str] = []
    log_lines: List[str] = []
    event_names: List[str] = []
    now = 0.0
    metrics = None

    for seg in segments:
        n = max(int(round(seg.duration * FPS)), 1)
        for i in range(n):
            t_local = i / FPS
            hand, face = seg.fn(t_local)
            metrics = measure_face(face) if face is not None else None

            events: List[Event] = []
            if hand is not None:
                for ev in hand_fsm.update(hand, now):
                    if ev.kind == "pointer":
                        if router.head_pointer:
                            continue
                        pt = pointer.absolute(ev.value, now)  # type: ignore[arg-type]
                        if pt is not None:
                            events.append(Event("pointer", pt))
                    else:
                        events.append(ev)
            else:
                events.extend(hand_fsm.update(None, now))

            if metrics is not None:
                events.extend(face_fsm.update(metrics, now))
                if router.head_pointer:
                    hdx, hdy = face_fsm.head_step(1.0 / FPS)
                    if abs(hdx) >= 1.0 or abs(hdy) >= 1.0:
                        events.append(Event("pointer_rel", value=(hdx, hdy)))
                if router.gaze_pointer:
                    gdx, gdy = face_fsm.gaze_step(1.0 / FPS)
                    if abs(gdx) >= 1.0 or abs(gdy) >= 1.0:
                        events.append(Event("pointer_rel", value=(gdx, gdy)))

            for ev in events:
                if ev.kind in ("pointer", "pointer_freeze", "pointer_rel"):
                    router.handle(ev, now)
                    continue
                was_paused, was_head = router.paused, router.head_pointer
                before = len(backend.log)
                router.handle(ev, now)
                applied = backend.log[before:]
                name = ev.kind if ev.kind != "scroll" else f"scroll({ev.value})"
                toggled = (router.paused != was_paused) or (router.head_pointer != was_head)
                if applied:
                    event_names.append(name)
                    suffix = "  => " + ", ".join(applied)
                elif toggled:
                    event_names.append(name)
                    suffix = "  => " + ("пауза" if router.paused else "продолжаем")
                    if router.head_pointer != was_head:
                        suffix += " / мышь головой " + ("вкл" if router.head_pointer else "выкл")
                elif was_paused:
                    suffix = "  (на паузе, действие не выполнено)"
                else:
                    suffix = "  (без действия)"
                log_lines.append(f"{now:6.2f}s  {name:24s}  {seg.title}{suffix}")

            # --- состояние оверлея -------------------------------------- #
            state.fps = FPS
            state.backend = "demo"
            state.paused = router.paused
            state.head_pointer = router.head_pointer
            state.hand_seen = hand is not None
            state.face_seen = metrics is not None
            state.gaze_pointer = router.gaze_pointer
            state.gaze_text = ("взгляд: зрачков не видно" if metrics is None or not face_fsm.gaze_valid
                               else "взгляд: рядом" if abs(face_fsm.gaze_x) < 0.2
                               else "взгляд: вправо" if face_fsm.gaze_x > 0 else "взгляд: влево")
            if metrics is not None:
                state.ear = min(metrics.ear_left, metrics.ear_right)
                state.smile = face_fsm.smile_score
                state.brow = face_fsm.brow_score
                state.mouth_open = metrics.mouth_open
            if hand is not None:
                feats = analyze_hand(hand, cfg.hand.pointer_source)
                state.pose = POSE_TITLES_RU.get(classify_pose(feats, cfg.hand), "—")
            else:
                state.pose = "—"
            for ev in events:
                if ev.kind in ("pinch_release", "drag_start", "drag_end", "thumb_up",
                               "rock_sign", "double_blink", "wink_left",
                               "wink_right", "smile_hold", "brow_hold"):
                    state.last_event = ev.label or ev.kind

            canvas = render(bg, state, [hand] if hand is not None else [],
                            face, metrics=metrics)
            _draw_cursor(canvas, backend.pos)
            cv2.putText(canvas, seg.title.encode("ascii", "ignore").decode() or "gesture",
                        (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1, cv2.LINE_AA)
            frames.append(canvas.copy())
            captions.append(seg.title)
            now += 1.0 / FPS

    # --- GIF ------------------------------------------------------------ #
    from PIL import Image, ImageDraw

    gif_path = out / "airmouse-demo.gif"
    pil_frames = []
    for i, frame in enumerate(frames):
        if i % 2:  # 12.5 fps достаточно для гифки
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_frames.append(Image.fromarray(rgb))
    duration_ms = int(1000 / (FPS / 2))
    pil_frames[0].save(
        gif_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )

    # --- раскадровка ----------------------------------------------------- #
    story_path = out / "airmouse-storyboard.png"
    font = _load_font(22)
    small = _load_font(18)
    picks = _pick_storyboard(frames)
    tiles = []
    for idx, caption in picks:
        rgb = cv2.cvtColor(frames[idx], cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((480, 270))
        canvas = Image.new("RGB", (480, 306), (22, 22, 26))
        canvas.paste(img, (0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((10, 278), caption, font=small, fill=(230, 230, 235))
        tiles.append(canvas)
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    board = Image.new("RGB", (cols * 490 + 10, rows * 316 + 40), (16, 16, 20))
    d = ImageDraw.Draw(board)
    d.text((14, 10), "AirMouse — жест -> действие", font=font, fill=(240, 240, 245))
    for i, tile in enumerate(tiles):
        board.paste(tile, (10 + (i % cols) * 490, 40 + (i // cols) * 316))
    board.save(story_path)

    # --- журнал ----------------------------------------------------------- #
    log_path = out / "airmouse-demo.log"
    header = [
        "AirMouse demo — журнал событий",
        f"кадров: {len(frames)} @ {FPS} fps, событий: {len(event_names)}",
        "кликов: %d, прокруток: %d" % (
            sum(1 for e in event_names if e.startswith("pinch_release")),
            sum(1 for e in event_names if e.startswith("scroll")),
        ),
        "-" * 56,
    ]
    log_path.write_text("\n".join(header + log_lines) + "\n", encoding="utf-8")

    return DemoResult(
        frames=len(frames),
        events=len(event_names),
        gif=gif_path,
        storyboard=story_path,
        log=log_path,
        event_names=event_names,
    )


def _load_font(size: int):
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _pick_storyboard(frames: List[np.ndarray]) -> List[Tuple[int, str]]:
    """Кадры, где происходило что-то интересное (первое событие каждого типа)."""
    picks: List[Tuple[int, str]] = []
    wanted = [
        (10, "указательный палец ведёт курсор"),
        (int(1.6 * FPS) + 12, "указательный палец"),
        (int(2.6 * FPS) + 14, "щипок -> клик"),
        (int(3.5 * FPS) + 24, "удержание -> перетаскивание"),
        (int(4.9 * FPS) + 18, "кулак -> прокрутка"),
        (int(7.5 * FPS) + 30, "ладонь -> только курсор"),
    ]
    segments = build_segments()
    offsets = []
    acc = 0.0
    for seg in segments:
        offsets.append(acc)
        acc += seg.duration
    # кадры для мимики — в конце
    face_start = int(offsets[-3] * FPS) if len(offsets) >= 3 else len(frames) - 100
    wanted.append((min(face_start + 14, len(frames) - 1), "двойное моргание"))
    wanted.append((min(face_start + int(1.4 * FPS) + 22, len(frames) - 1), "брови -> мышь головой"))
    wanted.append((min(face_start + int(3.2 * FPS) + 30, len(frames) - 1), "улыбка -> пауза"))
    for idx, caption in wanted:
        if 0 <= idx < len(frames):
            picks.append((idx, caption))
    return picks
