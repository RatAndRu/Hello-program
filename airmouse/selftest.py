"""Самопроверка логики: без камеры, без экрана, без кликов.

Используется командой ``python -m airmouse selftest`` и тестами в ``tests/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import cv2
import numpy as np

from .actions import ActionRouter, DryRunBackend
from .config import AppConfig, BodyConfig, FaceConfig, HandConfig, PointerConfig
from .face import FaceFSM, FaceMetrics, measure_face, measure_gaze
from .filters import HysteresisGate, OneEuroFilter
from .gestures import (
    HandFSM,
    HandSide,
    Pose,
    analyze_hand,
    classify_pose,
    synthetic_hand,
)
from .lipreading import LipReader, TemplateStore, dtw_distance, normalize_sequence
from .pointer import PointerMapper
from .settings_ui import DEFAULTS, SettingsPanel, apply_preset
from .synthetic import synthetic_face


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


# --------------------------------------------------------------------------- #
def check_filters() -> Check:
    """1€-фильтр должен уменьшать дрожание и почти не портить медленное движение."""
    f = OneEuroFilter(min_cutoff=1.2, beta=0.015)
    values = [0.50 + 0.02 * ((-1) ** i) for i in range(60)]
    out = [f.filter(v, i / 30.0) for i, v in enumerate(values)]
    jitter_in = float(np.std(values[10:]))
    jitter_out = float(np.std(out[10:]))
    return Check(
        "фильтр 1€ гасит дрожание",
        jitter_out < jitter_in * 0.6,
        f"дрожание {jitter_in:.4f} -> {jitter_out:.4f}",
    )


def check_hysteresis() -> Check:
    gate = HysteresisGate(on=0.32, off=0.42, inverted=True)
    states = [gate.update(v) for v in (0.6, 0.30, 0.35, 0.45, 0.40)]
    ok = states == [False, True, True, False, False]
    return Check("гистерезис щипка", ok, f"состояния: {states}")


def check_gestures() -> Check:
    """Все базовые позы синтетической кисти распознаются правильно."""
    cfg = HandConfig()
    cases = {
        "open_palm": (dict(), Pose.OPEN_PALM),
        "fist": (dict(curl={k: 1.0 for k in ("thumb", "index", "middle", "ring", "pinky")}), Pose.FIST),
        "point": (dict(curl={"middle": 1, "ring": 1, "pinky": 1}), Pose.POINT),
        "peace": (dict(curl={"ring": 1, "pinky": 1}), Pose.PEACE),
        "three": (dict(curl={"pinky": 1}), Pose.THREE),
        "pinch": (dict(curl={"middle": 1, "ring": 1, "pinky": 1}, pinch_index=True), Pose.PINCH),
        "middle_pinch": (
            dict(curl={"index": 1, "ring": 1, "pinky": 1}, pinch_middle=True),
            Pose.MIDDLE_PINCH,
        ),
        "thumb_up": (dict(curl={k: 1.0 for k in ("index", "middle", "ring", "pinky")}), Pose.THUMB_UP),
    }
    bad: List[str] = []
    for name, (kwargs, expected) in cases.items():
        got = classify_pose(analyze_hand(synthetic_hand(**kwargs), cfg.pointer_source), cfg)
        if got != expected:
            bad.append(f"{name}: ожидалось {expected.value}, получено {got.value}")
    return Check("распознавание поз кисти", not bad, "; ".join(bad) or f"{len(cases)} поз")


def check_builtin_gestures() -> Check:
    """«ОК», «коза» и «три пальца» встроены — учатся не нужны."""
    cfg = HandConfig()
    cases = {
        "ok": (dict(pinch_index=True,
                    curl={"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0}), Pose.OK),
        "rock": (dict(curl={"index": 0.0, "middle": 1.0, "ring": 1.0, "pinky": 0.0}), Pose.ROCK),
        "three": (dict(curl={"pinky": 1.0}), Pose.THREE),
    }
    bad: List[str] = []
    for name, (kwargs, expected) in cases.items():
        got = classify_pose(analyze_hand(synthetic_hand(**kwargs), cfg.pointer_source), cfg)
        if got != expected:
            bad.append(f"{name}: ожидалось {expected.value}, получено {got.value}")
    return Check("встроенные жесты ОК / коза / три", not bad,
                 "; ".join(bad) or "ОК, коза, три пальца")


def check_debounce() -> Check:
    """Одиночный «моргнувший» кадр щипка не должен стать кликом."""
    fsm = HandFSM(HandConfig())
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    clicks = 0
    t = 0.0
    for i in range(9):
        for ev in fsm.update(pinched if i == 4 else opened, t):
            clicks += ev.kind == "pinch_release"
        t += 0.033
    return Check("одиночный выброс щипка не кликает", clicks == 0, f"кликов: {clicks}")


def check_hand_side() -> Check:
    """Ладонь и тыл различаются, калибровка снимает неоднозначность, жесты расходятся."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    palm, back = synthetic_hand(), synthetic_hand(back=True)
    for _ in range(4):
        fsm.update(palm, 0.0)
    calibrated = fsm.side_est.calibrate()
    for i in range(6):
        fsm.update(back, 0.1 + i * 0.04)
    switched = fsm.side is HandSide.BACK

    ok_back = synthetic_hand(pinch_index=True, back=True,
                             curl={"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0})
    back_fsm = HandFSM(HandConfig())
    for _ in range(4):
        back_fsm.update(palm, 0.0)
    back_fsm.side_est.calibrate()
    kinds = set()
    t = 1.0
    for i in range(14):
        for ev in back_fsm.update(ok_back if i >= 6 else back, t):
            kinds.add(ev.kind)
        t += 0.04
    mapping = AppConfig().actions.mapping
    ok = bool(calibrated and switched and "ok_sign_back" in kinds
              and mapping.get("ok_sign_back") != mapping.get("ok_sign"))
    return Check("сторона кисти: ладонь / тыл", ok,
                 f"калибровка={calibrated}, переключение={switched}, "
                 f"жест тылом={'ok_sign_back' in kinds}")


def check_keys_any_layout() -> Check:
    """Горячие клавиши понимаются в русской раскладке и в любом кодировании."""
    from . import keys

    variants = {
        "латиница": ord("q"),
        "кириллица (Unicode)": ord("й"),
        "кириллица (cp1251)": 0xE9,       # столько отдаёт waitKey на Windows
    }
    ok = all(keys.matches(code, "q") for code in variants.values())
    # стрелки в расширенных кодах не должны притворяться буквами
    arrow = keys.matches(65361, "q") is False
    return Check("клавиши в любой раскладке", ok and arrow,
                 "q: " + ", ".join(f"{name}={code}" for name, code in variants.items()))


def check_sad_not_smile() -> Check:
    """Опущенные уголки губ — это грусть, а не «улыбка» по ширине рта."""
    fsm = FaceFSM(FaceConfig())
    for _ in range(6):
        fsm.update(measure_face(synthetic_face()), 0.0)
    for i in range(12):
        fsm.update(measure_face(synthetic_face(frown=0.10)), 0.1 + i * 0.04)
    ok = fsm.sad_score > 0.03 and fsm.smile_score <= 0.0
    return Check("грусть не выдаётся за улыбку", ok,
                 f"грусть={fsm.sad_score:.3f}, улыбка={fsm.smile_score:.3f}")


def check_gaze() -> Check:
    """Зрачок виден: смотрит вправо — курсор едет вправо, в центр — стоит."""
    fsm = FaceFSM(FaceConfig())
    t = 0.0
    for _ in range(8):
        fsm.update(measure_face(synthetic_face()), t)
        t += 0.04
    centered = fsm.gaze_step(0.1) == (0.0, 0.0)
    for _ in range(12):
        fsm.update(measure_face(synthetic_face(gaze=(0.6, 0.0))), t)
        t += 0.04
    dx, dy = fsm.gaze_step(0.1)
    blind = FaceFSM(FaceConfig())
    for _ in range(4):
        blind.update(measure_face(synthetic_face(iris=False)), t)
        t += 0.04

    # вертикаль и «не затухает»: смотрим вниз три секунды подряд
    down = FaceFSM(FaceConfig())
    t2 = 0.0
    for _ in range(30):
        down.update(measure_face(synthetic_face()), t2)
        t2 += 0.04
    for _ in range(75):
        down.update(measure_face(synthetic_face(gaze=(0.0, 0.12))), t2)
        t2 += 0.04
    down_step = down.gaze_step(0.04)

    ok = bool(fsm.gaze_valid and centered and dx > 5 and abs(dy) < 1
              and not blind.gaze_valid
              and down_step[1] > 2.0 and abs(down_step[0]) < 1.0)
    return Check("зрачки и мышь глазами", ok,
                 f"вправо={dx:.1f}px, вниз={down_step[1]:.1f}px за 0.04с, "
                 f"без радужки — {blind.gaze_valid}")


def check_blink_rules() -> Check:
    """Моргание: время захвата, подмигивание только одним глазом, предел 4 с."""
    cfg = FaceConfig()
    fps = 25.0
    open_ear, closed_ear = 0.30, 0.08

    def play(ears, fsm=None):
        fsm = fsm or FaceFSM(cfg)
        t, out = 0.0, []
        for ear in ears:
            pair = (ear, ear) if isinstance(ear, (int, float)) else ear
            out += fsm.update(measure_face(synthetic_face(ear=pair)), t)
            t += 1.0 / fps
        return [e.kind for e in out]

    instant = play([open_ear] * 6 + [closed_ear] + [open_ear] * 4)
    both = play([open_ear] * 6 + [(closed_ear, closed_ear)] * 4 + [open_ear] * 4)
    wink = play([open_ear] * 6 + [(closed_ear, open_ear)] * 8 + [open_ear] * 4)
    long_closed = play([open_ear] * 6 + [closed_ear] * int(5 * fps) + [open_ear] * 6)
    ok = (instant == [] and not any(k.startswith("wink") for k in both)
          and wink == ["wink_left"] and long_closed.count("eyes_closed_hold") == 1)
    return Check("моргание: захват, один глаз, предел", ok,
                 f"мгновенное={instant}, оба={both}, подмигивание={wink}, 5с={long_closed}")


def check_hand_gate() -> Check:
    """Фантомные «руки» отсекаются: уверенность и размер ладони."""
    from .gestures import HandGate, synthetic_hand

    gate = HandGate(HandConfig())
    weak = synthetic_hand(scale=0.2)
    weak.score = 0.15
    tiny = synthetic_hand(scale=0.004)
    ok_hand = synthetic_hand(scale=0.2)
    passed = bool(not gate.update([weak]) and not gate.update([tiny])
                  and gate.update([ok_hand]))
    return Check("ложные руки отсекаются", passed,
                 f"слабая={weak.score:.2f}, крошечная={tiny.palm_size:.3f}")


def check_gaze_calibration() -> Check:
    """Калибровка взгляда: 9 точек по гомографии + поправка на поворот головы."""
    from .gaze import CALIBRATION_TARGETS, GazeCalibration

    def gaze(sx, sy):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    calib = GazeCalibration()
    for sx, sy in CALIBRATION_TARGETS:
        calib.add(*gaze(sx, sy), sx, sy)
    fitted = calib.fit()
    worst = 0.0
    for sx, sy in ((0.1, 0.1), (0.5, 0.5), (0.9, 0.9)):
        px, py = calib.apply(*gaze(sx, sy))
        worst = max(worst, abs(px - sx), abs(py - sy))
    # прицел рисуется на весь монитор, а не в окне: проверяем холст 1920x1080
    from .overlay import OverlayState, render_gaze_calibration

    canvas = render_gaze_calibration(
        (1920, 1080),
        OverlayState(calib_active=True, calib_target=CALIBRATION_TARGETS[1]),
    )
    full = canvas.shape[:2] == (1080, 1920)
    import numpy as _np

    green = _np.abs(canvas.astype("int16") - _np.array([90, 235, 130])).sum(axis=2) < 40
    corner = bool(green[:120, 1780:].any())      # прицел в правом верхнем углу
    # поворот головы: зрачок «уезжает», калибровка должна это вычитать
    import math as _math

    center = gaze(0.5, 0.5)
    drift = (0.30, -0.15)
    head = []
    for yaw in range(-20, 21, 4):
        for pitch in (-12, 0, 12):
            head.append((center[0] + drift[0] * _math.tan(_math.radians(yaw)),
                         center[1] + drift[1] * _math.tan(_math.radians(pitch)),
                         float(yaw), float(pitch)))
    head_learned = calib.fit_head(head)
    points = [calib.apply(*calib.head_correct(gx, gy, yaw, pitch))
              for gx, gy, yaw, pitch in head]
    jump = max(max(p[0] for p in points) - min(p[0] for p in points),
               max(p[1] for p in points) - min(p[1] for p in points))
    ok = bool(fitted and calib.ready and worst < 0.03 and full and corner
              and head_learned and jump < 0.02)
    return Check("калибровка взгляда в экран", ok,
                 f"точек={len(calib.points)}, ошибка={worst * 100:.1f}% экрана, "
                 f"холст {canvas.shape[1]}x{canvas.shape[0]}, "
                 f"угол={'да' if corner else 'нет'}, "
                 f"поворот головы ±20°: сдвиг {jump * 100:.1f}% экрана")


def check_gaze_pursuit() -> Check:
    """Калибровка «веди взгляд за точкой»: точность, задержка и фазы мастера."""
    import math

    from .gaze import PURSUIT_DURATION_S, GazeCalibration, pursuit_metrics, pursuit_point

    def gaze(sx, sy):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    # траектория: 13 секунд змейкой по пяти строкам — покрывает весь экран
    samples = []
    for i in range(390):
        t = i / 30.0
        sx, sy = pursuit_point(t, PURSUIT_DURATION_S)
        gx, gy = gaze(sx, sy)
        samples.append((t, gx, gy, sx, sy))
    calib = GazeCalibration(points=[(s[1], s[2], s[3], s[4]) for s in samples])
    fitted = calib.fit()
    worst = 0.0
    for sx, sy in ((0.1, 0.2), (0.5, 0.5), (0.85, 0.9)):
        px, py = calib.apply(*gaze(sx, sy))
        worst = max(worst, abs(px - sx), abs(py - sy))
    # та же траектория, но зрачок отстаёт на три кадра: мастер обязан это заметить
    lagged = [(s[0], *gaze(*pursuit_point(max(0.0, s[0] - 0.1), PURSUIT_DURATION_S)),
               s[3], s[4]) for s in samples]
    metrics = pursuit_metrics(lagged)
    latency_ok = abs(metrics["latency_ms"] - 100.0) <= 40.0
    ok = bool(fitted and calib.ready and worst < 0.03 and latency_ok
              and metrics["responsiveness"] > 0.5 and len(calib.points) > 300)
    return Check("калибровка взгляда по движущейся точке", ok,
                 f"проб={len(calib.points)}, ошибка={worst * 100:.1f}% экрана, "
                 f"задержка зрачка={metrics['latency_ms']:.0f} мс (ждали ~100), "
                 f"согласованность={metrics['responsiveness']:.2f}")


def check_motion_profile() -> Check:
    """Профиль движений: личные пороги вместо общих (щипок, улыбка, присед)."""
    from .profile import MotionProfile, MotionWizard

    wizard = MotionWizard()
    t = 0.0
    # щипок: человек сводит пальцы до 0.10 и разжимает до 0.34
    for i in range(4000):
        if wizard.done:
            break
        key = wizard.step.key
        value = {
            "pinch": 0.10 + 0.24 * (i % 2),
            "smile": 0.11,
            "brow": 0.12,
            "mouth": 0.78,
            "squat": 0.62,
        }[key]
        t += 1 / 30.0
        wizard.update(1 / 30.0, **{key: value})
    prof = wizard.finish()
    suggested = prof.suggest()
    limits = {
        "pinch_ratio": (0.18, 0.55),
        "smile_delta": (0.030, 0.120),
        "brow_delta": (0.025, 0.100),
        "mouth_open_ratio": (0.35, 0.80),
        "squat_down": (0.28, 0.80),
        "squat_up": (0.10, 0.40),
    }
    inside = all(low <= suggested.get(k, low) <= high
                 for k, (low, high) in limits.items())
    personal = (suggested.get("pinch_ratio", 0) > 0.18
                and suggested.get("smile_delta", 0) > 0.030
                and suggested.get("squat_down", 0) < 0.62)
    roundtrip = MotionProfile.from_dict(prof.to_dict()).pinch_open == prof.pinch_open
    ok = bool(prof.pinch_range > 0.15 and inside and personal and roundtrip
              and len(suggested) == 6)
    return Check("профиль движений под человека", ok,
                 f"щипок {prof.pinch_closed:.2f}…{prof.pinch_open:.2f}, "
                 f"порог щипка={suggested.get('pinch_ratio', 0):.2f}, "
                 f"улыбка={suggested.get('smile_delta', 0):.3f}, "
                 f"присед={suggested.get('squat_down', 0):.2f}")


def check_body_squats() -> Check:
    """Тело: приседания считаются, наклон и руки вверх ловятся."""
    from .body import BodyFSM, measure_body, synthetic_body

    cfg = BodyConfig()
    fsm = BodyFSM(cfg)
    t = 0.0
    events = []
    for _ in range(3):
        for squat in [0.0] * 12 + [0.9] * 16 + [0.0] * 16:
            events.extend(fsm.update(measure_body(synthetic_body(squat=squat)), t))
            t += 1 / 30.0
    reps = [e for e in events if e.kind == "squat_rep"]
    arms = measure_body(synthetic_body(arms_up=1.0)).posture == "arms_up"
    lean = measure_body(synthetic_body(lean=40)).posture == "lean"
    ok = len(reps) == 3 and arms and lean
    return Check("тело: приседания и позы", ok,
                 f"приседаний={len(reps)} (ждали 3), руки вверх={arms}, наклон={lean}")


def check_body_overlay() -> Check:
    """Тело видно: скелет рисуется, а «по пояс» — рисуется без ног и без счёта."""
    from .body import B, BodyFSM, measure_body, synthetic_body
    from .overlay import OverlayState, draw_body_ar, render

    frame = np.full((540, 960, 3), 18, dtype=np.uint8)
    full = frame.copy()
    drawn_full = draw_body_ar(full, synthetic_body())
    changed = int(np.abs(full.astype("int16") - frame.astype("int16")).sum()) > 0

    waist_body = synthetic_body()
    for index in (B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE,
                  B.L_HEEL, B.R_HEEL, B.L_FOOT, B.R_FOOT):
        waist_body[index, 3] = 0.0
    waist = frame.copy()
    drawn_waist = draw_body_ar(waist, waist_body)
    metrics = measure_body(waist_body)

    fsm = BodyFSM(BodyConfig())
    t = 0.0
    for squat in [0.0] * 15 + [0.9] * 16 + [0.0] * 16:      # один полный повтор
        fsm.update(measure_body(synthetic_body(squat=squat)), t)
        t += 1 / 30
    reps = fsm.reps
    for _ in range(60):
        fsm.update(measure_body(waist_body), t)     # «по пояс» на приседе
        t += 1 / 30
    no_extra = fsm.reps == reps

    state = OverlayState(body_enabled=True, body_text=fsm.text)
    image = render(frame.copy(), state, hands=[], face=None, body=waist_body)
    in_window = int(np.abs(image.astype("int16") - frame.astype("int16")).sum()) > 0

    ok = bool(changed and drawn_full > 15 and 0 < drawn_waist < drawn_full
              and metrics.visible and metrics.partial and metrics.depth == 0.0
              and reps == 1 and no_extra and "по пояс" in fsm.text and in_window)
    return Check("тело: скелет в окне и кадр «по пояс»", ok,
                 f"связей целиком={drawn_full}, по пояс={drawn_waist}, "
                 f"приседаний={reps}, лишних нет={no_extra}, "
                 f"текст: {fsm.text or '—'}")


def check_head_gain() -> Check:
    """Мышь головой: мёртвая зона стоит, большие углы разгоняются (HeadShift)."""
    from .config import FaceConfig
    from .face import FaceFSM

    fsm = FaceFSM(FaceConfig())
    fsm.rel_yaw = 1.0
    inside = abs(fsm.head_step(0.1)[0])
    fsm.rel_yaw = 6.0
    small = fsm.head_step(0.1)[0]
    fsm.rel_yaw = 20.0
    big = fsm.head_step(0.1)[0]
    ok = inside == 0.0 and big > (20.0 / 6.0) * small > 0.0
    return Check("мышь головой: нелинейный разгон", ok,
                 f"1°={inside:.0f}px, 6°={small:.0f}px, 20°={big:.0f}px")


def check_gaze_dwell() -> Check:
    """Клик удержанием взгляда: ~600 мс, сброс при переводе взгляда."""
    from .gaze import GazeDwell

    dwell = GazeDwell(dwell_s=0.6, radius_px=60)
    fired_at = None
    for i in range(40):
        t = i * 0.05
        _p, fired = dwell.update(500, 400, t)
        if fired:
            fired_at = t
            break
    fresh = GazeDwell(dwell_s=0.6, radius_px=60)
    for i in range(8):
        fresh.update(500, 400, i * 0.05)
    progress = fresh.progress
    _p, moved = fresh.update(900, 400, 0.45)
    ok = fired_at is not None and 0.5 <= fired_at <= 0.9 and progress > 0.5 and not moved
    return Check("клик удержанием взгляда", ok,
                 f"сработал на {0 if fired_at is None else fired_at * 1000:.0f} мс, "
                 f"сброс при переводе={not moved}")


def check_settings_panel() -> Check:
    """Ползунки настроек реально меняют конфиг и сохраняются в файл."""
    cfg = AppConfig()
    panel = SettingsPanel(cfg)
    panel.open()
    panel.goto_page(1)                    # страница «Курсор»
    rows = panel.layout()
    row = rows[4] if len(rows) > 4 else rows[0]
    slider = row.slider
    x0, _y, track_w, _h = row.track
    panel.on_mouse(cv2.EVENT_LBUTTONDOWN, x0 + track_w - 2, row.rect[1] + 4)
    moved = abs(slider.get(cfg) - DEFAULTS[slider.key]) > 1e-9
    before = slider.get(cfg)
    panel.reset()
    restored = abs(slider.get(cfg) - DEFAULTS[slider.key]) < 1e-9
    ok = bool(moved and restored and before is not None)
    return Check("ползунки настроек меняют конфиг", ok,
                 f"{slider.label}: {before:.3g} -> заводское {slider.get(cfg):.3g}")


def check_modes() -> Check:
    """Режимы включаются в любых сочетаниях, а вторая рука по умолчанию молчит."""
    cfg = AppConfig()
    runtime = type("R", (), {"head_pointer": False})()
    apply_preset(cfg, runtime, "РУКА")
    single = (cfg.hand.enabled and not cfg.face.enabled and cfg.hand.roles == "single")
    apply_preset(cfg, runtime, "РУКА + ЛИЦО")
    both = cfg.hand.enabled and cfg.face.enabled
    apply_preset(cfg, runtime, "ДВЕ РУКИ")
    two = cfg.hand.roles == "split" and cfg.hand.two_hand == "off"
    apply_preset(cfg, runtime, "ТОЛЬКО ЛИЦО")
    face_only = (not cfg.hand.enabled) and cfg.face.enabled
    default_silent = AppConfig().hand.roles == "single" and AppConfig().hand.two_hand == "off"
    ok = bool(single and both and two and face_only and default_silent)
    return Check("режимы: рука / две руки / лицо", ok,
                 "рука, рука+лицо, две руки, только лицо")


def check_head_pointer() -> Check:
    """Голова: движение заметное, возврат в нейтраль курсор не тянет назад."""
    fsm = FaceFSM(FaceConfig())
    fsm.baseline.samples = 20
    fsm.update(FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=0.4,
                           brow_height=0.2, yaw=30.0, valid=True), 0.0)
    dx, dy = fsm.head_step(1.0 / 30.0)
    fsm.update(FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=0.4,
                           brow_height=0.2, yaw=0.0, valid=True), 0.05)
    back = fsm.head_step(1.0 / 30.0)
    ok = dx > 20.0 and abs(dy) < 1e-6 and back == (0.0, 0.0)
    return Check("мышь головой: возврат не двигает курсор", ok,
                 f"наклон 30° -> {dx:.0f} px/кадр, возврат -> {back[0]:.0f} px")


def check_rotation() -> Check:
    """Поворот кисти на ±25° не должен менять жест."""
    cfg = HandConfig()
    bad = []
    for angle in (-25, -10, 10, 25):
        pose = classify_pose(
            analyze_hand(synthetic_hand(rotation_deg=angle), cfg.pointer_source), cfg
        )
        if pose != Pose.OPEN_PALM:
            bad.append(f"{angle}° -> {pose.value}")
    return Check("устойчивость к повороту кисти", not bad, "; ".join(bad) or "4 угла")


def _play(fsm: HandFSM, frames, fps: float = 30.0, start: float = 0.0):
    """Прогоняет кадры через автомат и собирает события."""
    events = []
    t = start
    for hand in frames:
        events.extend(fsm.update(hand, t))
        t += 1.0 / fps
    return events, t


def check_click_fsm() -> Check:
    """Щипок + короткое удержание + отпускание = ровно один клик."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    others = {"middle": 1, "ring": 1, "pinky": 1}
    frames = (
        [synthetic_hand(curl=others) for _ in range(4)]
        + [synthetic_hand(curl=others, pinch_index=True) for _ in range(4)]
        + [synthetic_hand(curl=others) for _ in range(5)]
    )
    events, _ = _play(fsm, frames)
    clicks = [e for e in events if e.kind == "pinch_release"]
    drags = [e for e in events if e.kind == "drag_start"]
    return Check(
        "щипок -> один клик",
        len(clicks) == 1 and not drags,
        f"кликов {len(clicks)}, перетаскиваний {len(drags)}",
    )


def check_drag_fsm() -> Check:
    """Долгий щипок с движением = перетаскивание, а не клик."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    others = {"middle": 1, "ring": 1, "pinky": 1}
    frames = [synthetic_hand(curl=others) for _ in range(3)]
    for i in range(15):
        frames.append(
            synthetic_hand(
                center=(0.45 + 0.01 * i, 0.6), curl=others, pinch_index=True
            )
        )
    frames += [synthetic_hand(curl=others) for _ in range(4)]
    events, _ = _play(fsm, frames)
    kinds = [e.kind for e in events]
    ok = "drag_start" in kinds and kinds.index("drag_end") > kinds.index("drag_start")
    return Check(
        "долгий щипок -> перетаскивание",
        ok and "pinch_release" not in kinds,
        f"события: drag_start={kinds.count('drag_start')}, drag_end={kinds.count('drag_end')}, "
        f"кликов={kinds.count('pinch_release')}",
    )


def check_scroll_fsm() -> Check:
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    fist = {k: 1.0 for k in ("thumb", "index", "middle", "ring", "pinky")}
    frames = []
    for i in range(18):
        frames.append(synthetic_hand(center=(0.5, 0.75 - 0.02 * i), curl=fist))
    events, _ = _play(fsm, frames)
    ticks = sum(int(e.value) for e in events if e.kind == "scroll")
    return Check("кулак + движение -> прокрутка", ticks > 0, f"тиков: {ticks}")


def check_pause_fsm() -> Check:
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    # держим ладонь дольше, чем требуется (open_palm_hold_s = 1.3 с)
    frames = [synthetic_hand() for _ in range(int(cfg.open_palm_hold_s * 30) + 25)]
    events, _ = _play(fsm, frames)
    fired = [e for e in events if e.kind == "open_palm_hold"]
    return Check(f"ладонь {cfg.open_palm_hold_s:.1f} с -> пауза", len(fired) == 1,
                 f"срабатываний: {len(fired)}")


def check_open_palm_flat() -> Check:
    """Ладонь — только плоская и в камеру: наискосок, ребром и тылом — нет."""
    from .gestures import analyze_hand, classify_pose, palm_hint, synthetic_hand

    cfg = HandConfig()
    flat = classify_pose(analyze_hand(synthetic_hand()), cfg)
    tilted = analyze_hand(synthetic_hand(yaw_deg=55))
    tilted_pose = classify_pose(tilted, cfg)
    hint = palm_hint(tilted, cfg)
    back = analyze_hand(synthetic_hand(back=True))
    ok = (flat == Pose.OPEN_PALM and tilted_pose != Pose.OPEN_PALM
          and back.palm_side < -0.5 and "углом" in hint)
    return Check("ладонь: только плоская и в камеру", ok,
                 f"ровно={flat.value}, наискосок={tilted_pose.value} "
                 f"({hint[:32]}), тыл={back.palm_side:+.2f}")


def check_face_blink() -> Check:
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    fps = 25.0
    # калибровка на нейтральном лице
    for _ in range(20):
        fsm.baseline.update(measure_face(synthetic_face()), alpha=0.4)
        fsm.update(measure_face(synthetic_face()), 0.0)
    events = []
    t = 0.0
    for i in range(70):
        closed = (10 <= i < 13) or (20 <= i < 23)
        face = synthetic_face(ear=(0.08, 0.08) if closed else (0.30, 0.30))
        events.extend(fsm.update(measure_face(face), t))
        t += 1.0 / fps
    clicks = [e for e in events if e.kind == "double_blink"]
    return Check("двойное моргание", len(clicks) == 1, f"событий: {[e.kind for e in events]}")


def check_face_smile() -> Check:
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    t = 0.0
    for _ in range(30):
        fsm.update(measure_face(synthetic_face()), t)
        t += 1 / 25.0
    events = []
    for _ in range(30):
        events.extend(fsm.update(measure_face(synthetic_face(smile=0.04)), t))
        t += 1 / 25.0
    fired = [e for e in events if e.kind == "smile_hold"]
    return Check("улыбка 0.45 с", len(fired) == 1, f"smile_score={fsm.smile_score:.3f}")


def check_face_brow() -> Check:
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    t = 0.0
    for _ in range(30):
        fsm.update(measure_face(synthetic_face()), t)
        t += 1 / 25.0
    events = []
    # порог бровей поднят (brow_delta * 1.5) — поднимаем заметно и держим дольше
    for _ in range(int(cfg.brow_hold_s * 25) + 25):
        events.extend(fsm.update(measure_face(synthetic_face(brow=0.09)), t))
        t += 1 / 25.0
    fired = [e for e in events if e.kind == "brow_hold"]
    return Check(f"брови {cfg.brow_hold_s:.1f} с", len(fired) == 1,
                 f"brow_score={fsm.brow_score:.3f}")


def check_face_wink() -> Check:
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    t = 0.0
    for _ in range(20):
        fsm.update(measure_face(synthetic_face()), t)
        t += 1 / 25.0
    events = []
    for _ in range(20):
        fsm.update(measure_face(synthetic_face(ear=(0.08, 0.30))), t)
        t += 1 / 25.0
    for _ in range(10):
        events.extend(fsm.update(measure_face(synthetic_face()), t))
        t += 1 / 25.0
    winks = [e for e in events if e.kind.startswith("wink")]
    return Check("подмигивание", len(winks) == 1, f"события: {[e.kind for e in events]}")


def check_head_pose() -> Check:
    yaw = measure_face(synthetic_face(yaw=25)).yaw
    pitch = measure_face(synthetic_face(pitch=15)).pitch
    ok = abs(yaw - 25) < 3 and abs(pitch - 15) < 3
    return Check("оценка поворота головы", ok, f"yaw={yaw:.1f}°, pitch={pitch:.1f}°")


def check_pointer() -> Check:
    cfg = PointerConfig()
    mapper = PointerMapper(cfg, (1920, 1080))
    positions = []
    for i in range(60):  # секунда плавного движения руки по диагонали
        u = 0.16 + (0.84 - 0.16) * i / 59.0
        v = 0.14 + (0.86 - 0.14) * i / 59.0
        pos = mapper.absolute((u, v), i / 30.0)
        if pos is not None:
            positions.append(pos)
    ok = len(positions) > 30
    if ok:
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        ok = xs[0] < 60 and ys[0] < 60 and xs[-1] > 1860 and ys[-1] > 1020
        ok = ok and all(b >= a - 1 for a, b in zip(xs, xs[1:]))
        ok = ok and all(b >= a - 1 for a, b in zip(ys, ys[1:]))
    mapper2 = PointerMapper(cfg, (1920, 1080))
    mapper2.absolute((0.5, 0.5), 0.0)
    tremor = mapper2.absolute((0.5005, 0.5), 0.05)  # микро-дрожание
    ok = ok and tremor is None
    detail = f"точек {len(positions)}, дрожание={tremor}"
    if positions:
        detail += f", старт={positions[0]}, финиш={positions[-1]}"
    return Check("указатель: активная зона и мёртвая зона", ok, detail)


def check_actions() -> Check:
    cfg = AppConfig()
    backend = DryRunBackend()
    router = ActionRouter(backend, cfg)
    from .gestures import Event

    for kind in ("pinch_release", "thumb_up", "middle_pinch_release"):
        router.handle(Event(kind), now=0.0)
    router.handle(Event("open_palm_hold"), now=1.0)
    paused = router.paused
    router.handle(Event("pointer", (10, 20)), now=2.0)  # на паузе игнорируется
    router.handle(Event("open_palm_hold"), now=3.0)
    ok = paused and not router.paused
    ok = ok and "click(leftx1)" in backend.log and "click(leftx2)" in backend.log
    ok = ok and "click(rightx1)" in backend.log and "move_to(10,20)" not in backend.log
    return Check("действия и пауза", ok, f"журнал: {backend.log[:6]}")


def _word_single(n: int = 36) -> np.ndarray:
    t = np.linspace(0, 1, n)
    a = np.zeros((n, 8))
    a[:, 0] = 1.3 * np.exp(-((t - 0.5) ** 2) / 0.030)   # один «слог»
    a[:, 1] = 1.0 - 0.4 * np.exp(-((t - 0.5) ** 2) / 0.05)
    return a


def _word_double(n: int = 36) -> np.ndarray:
    t = np.linspace(0, 1, n)
    a = np.zeros((n, 8))
    a[:, 0] = np.exp(-((t - 0.3) ** 2) / 0.012) + 0.9 * np.exp(-((t - 0.7) ** 2) / 0.012)
    a[:, 1] = 1.0
    return a


def check_lip_dtw() -> Check:
    """DTW отличает «своё» слово от чужого."""
    rng = np.random.default_rng(3)
    base = _word_single()
    other = _word_double()
    noisy = normalize_sequence(base + rng.normal(0, 0.012, base.shape))
    d_same = dtw_distance(noisy, normalize_sequence(base))
    d_diff = dtw_distance(normalize_sequence(other), normalize_sequence(base))
    ok = d_same < d_diff * 0.5
    return Check("DTW: своё слово ближе чужого", ok, f"своё={d_same:.4f}, чужое={d_diff:.4f}")


def check_lip_reader() -> Check:
    import tempfile
    from pathlib import Path

    rng = np.random.default_rng(5)
    with tempfile.TemporaryDirectory() as tmp:
        store = TemplateStore(Path(tmp))
        word_a = _word_single()
        word_b = _word_double()
        for _ in range(4):
            store.save("стоп", normalize_sequence(word_a + rng.normal(0, 0.012, word_a.shape)))
            store.save("дальше", normalize_sequence(word_b + rng.normal(0, 0.012, word_b.shape)))

        reader = LipReader(store, window_frames=36, stride_s=0.0, max_distance=0.06)
        got = None
        t = 0.0
        for i in range(36):
            feat = word_a[i] + rng.normal(0, 0.010, 8)
            got = reader.push(feat, t) or got
            t += 1 / 25.0
        ok = got is not None and got.word == "стоп"
        detail = f"распознано: {got.word if got else None}, d={got.distance:.4f}" if got else "не распознано"
        return Check("словарь по губам", ok, f"{detail}, словарь={reader.vocabulary}")


def _synthetic_hand_frame(open_hand: bool, cy: float = 260.0, cx: float = 320.0):
    """Рисует «кожу» нужного цвета и формы — для проверки классического CV."""
    import cv2

    h, w = 360, 640
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = np.linspace(60, 30, h)[:, None, None]
    skin = (140, 172, 224)  # BGR — телесный цвет
    cv2.ellipse(img, (int(cx), int(cy)), (48, 42), 0, 0, 360, skin, -1)
    if open_hand:
        for dx in (-33, -11, 11, 33):
            cv2.rectangle(img, (int(cx + dx) - 8, int(cy) - 130),
                          (int(cx + dx) + 8, int(cy) - 35), skin, -1)
        cv2.rectangle(img, (int(cx) - 78, int(cy) - 55),
                      (int(cx) - 40, int(cy) - 25), skin, -1)
    else:
        cv2.ellipse(img, (int(cx), int(cy) - 5), (52, 38), 0, 0, 360, skin, -1)
    return cv2.GaussianBlur(img, (5, 5), 0)


def check_classical_detector() -> Check:
    from .classical import find_hand

    open_shape = find_hand(_synthetic_hand_frame(True))
    fist_shape = find_hand(_synthetic_hand_frame(False))
    noise = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    ok = (
        open_shape is not None
        and fist_shape is not None
        and open_shape.radius > fist_shape.radius
        and 0.25 < open_shape.pointer[1] < 0.5
        and find_hand(noise) is None
    )
    detail = ""
    if open_shape is not None and fist_shape is not None:
        detail = (f"открытая: радиус={open_shape.radius:.3f}, лучи={open_shape.rays}; "
                  f"кулак: радиус={fist_shape.radius:.3f}")
    return Check("классическое CV находит силуэт", ok, detail)


def check_classical_fsm() -> Check:
    from .classical import ClassicalFSM, find_hand

    fsm = ClassicalFSM(HandConfig())
    open_shape = find_hand(_synthetic_hand_frame(True))
    fist_shape = find_hand(_synthetic_hand_frame(False))
    if open_shape is None or fist_shape is None:
        return Check("классическое CV: клик и прокрутка", False, "силуэт не найден")

    events = []
    t = 0.0
    for _ in range(5):                      # ладонь
        events += fsm.update(open_shape, t)
        t += 1 / 25.0
    for _ in range(3):                      # короткое сжатие
        events += fsm.update(fist_shape, t)
        t += 1 / 25.0
    for _ in range(5):                      # разжали
        events += fsm.update(open_shape, t)
        t += 1 / 25.0
    clicks = [e for e in events if e.kind == "pinch_release"]

    fsm2 = ClassicalFSM(HandConfig())
    events2 = []
    t = 0.0
    for _ in range(5):
        events2 += fsm2.update(open_shape, t)
        t += 1 / 25.0
    for i in range(30):                     # долгое сжатие + рука едет вверх
        moved = find_hand(_synthetic_hand_frame(False, cy=300 - 3 * i))
        events2 += fsm2.update(moved, t)
        t += 1 / 25.0
    scrolls = [e for e in events2 if e.kind == "scroll"]
    ticks = sum(int(e.value) for e in scrolls)
    ok = len(clicks) == 1 and not [e for e in events2 if e.kind == "pinch_release"] and ticks > 0
    return Check("классическое CV: клик и прокрутка", ok,
                 f"кликов={len(clicks)}, тиков прокрутки={ticks}")


def check_gaze_accuracy() -> Check:
    """«Мышь глазами»: верх-низ не путается, моргание не сдвигает взгляд.

    Проверяем две вещи, которые ломали направления:
    вертикальная координата зрачка не зависит от положения век (прищуривание
    больше не «уводит» взгляд вверх), а кадр с закрытыми глазами вообще не
    считается взглядом.
    """
    from .landmarks import F

    face = synthetic_face(gaze=(0.0, 0.6))
    _dx, dy_before, ok_before = measure_gaze(face)
    for group in (F.EYE_A, F.EYE_B):
        cy = (face.xy(group[0])[1] + face.xy(group[3])[1]) / 2.0
        for idx in group[1:3] + group[4:6]:
            x, y = face.xy(idx)[:2]
            face.points[idx, 1] = cy + (y - cy) * 0.35
    _dx, dy_after, ok_after = measure_gaze(face)
    blink = measure_face(synthetic_face(ear=(0.08, 0.08), gaze=(0.0, 0.9)))
    still = abs(dy_after - dy_before) < 1e-6
    ok = bool(ok_before and ok_after and still and not blink.gaze_valid)
    return Check("взгляд: веки не двигают взгляд", ok,
                 f"до={dy_before:+.2f}, после прищура={dy_after:+.2f}, "
                 f"моргание={'не взгляд' if not blink.gaze_valid else 'взгляд'}")


def check_gaze_direction() -> Check:
    """Слова «вверх/вниз/влево/вправо» совпадают с точкой на экране.

    Направление считается той же формулой, что и телепорт курсора, поэтому
    подпись в окне и поведение мыши не могут разойтись.
    """
    from .gaze import CALIBRATION_TARGETS, GazeCalibration

    def gaze_for(sx: float, sy: float):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    calib = GazeCalibration(feature="head2")
    for sx, sy in CALIBRATION_TARGETS:
        calib.add(*gaze_for(sx, sy), sx, sy)
    if not calib.fit():
        return Check("взгляд: направления по калибровке", False, "калибровка не сошлась")

    cases = [((0.5, 0.92), "вниз"), ((0.5, 0.08), "вверх"),
             ((0.92, 0.5), "вправо"), ((0.08, 0.5), "влево"),
             ((0.5, 0.5), "прямо")]
    words = []
    ok = True
    for (sx, sy), want in cases:
        u, v = calib.apply(*gaze_for(sx, sy))
        nx, ny = (u - 0.5) * 2.0, (v - 0.5) * 2.0
        if abs(nx) < 0.16 and abs(ny) < 0.16:
            got = "прямо"
        elif abs(nx) >= abs(ny):
            got = "вправо" if nx > 0 else "влево"
        else:
            got = "вниз" if ny > 0 else "вверх"
        words.append(got)
        ok = ok and got == want
    return Check("взгляд: направления по калибровке", ok, " ".join(words))


def check_hand_tracker() -> Check:
    """Трекер кисти: рука продолжает движение по инерции и потом исчезает."""
    from .handtrack import HandTracker
    from .landmarks import FINGERS

    tracker = HandTracker(predict_frames=4)
    curl = {name: 0.0 for name in FINGERS}
    tracker.update([synthetic_hand(center=(0.40, 0.60), curl=curl)], 0.0)
    tracker.update([synthetic_hand(center=(0.45, 0.60), curl=curl)], 1 / 30)
    predicted = tracker.update([], 2 / 30)
    kept = bool(predicted) and predicted[0].predicted
    moved = kept and float(predicted[0].hand.palm_center[0]) > 0.45
    for i in range(3, 12):
        tracker.update([], i / 30)
    forgotten = tracker.count == 0
    ok = bool(kept and moved and forgotten)
    return Check("трекер кисти: ведёт по инерции", ok,
                 f"предсказана={kept}, сдвинулась={moved}, забыта={forgotten}")


def check_hand_physics() -> Check:
    """Физика пальцев: живая рука не трогается, невозможная — исправляется."""
    from .handphysics import HandPhysics, FingerPose, coupling_error, rebuild_finger, poses
    from .landmarks import FINGERS

    natural = synthetic_hand(curl={name: 0.5 for name in FINGERS})
    clean = HandPhysics().update(natural, 0.0)
    broken = synthetic_hand(curl={name: 0.0 for name in FINGERS})
    rebuild_finger(broken, "index", FingerPose(mcp=6.0, pip=4.0, dip=58.0), sign=1.0)
    fixed = HandPhysics().update(broken, 0.0)
    ok = (not clean.suspect and not clean.rebuilt
          and "index" in fixed.suspect and fixed.rebuilt == 1
          and coupling_error(fixed.poses["index"]) < 20.0)
    return Check("физика пальцев: невозможная поза", ok,
                 f"живая рука: правок={clean.rebuilt}, "
                 f"невозможная: помечена={'index' in fixed.suspect}, "
                 f"DIP после правки={fixed.poses['index'].dip:.0f}°")


def check_body_stability() -> Check:
    """Тело не мигает: показывается не сразу и держится на пропущенном кадре."""
    from .body import BodySmoother, synthetic_body

    smoother = BodySmoother(confirm_frames=2, hold_frames=4)
    first = smoother.update(synthetic_body(center=(0.5, 0.5), height=0.8), 0.0)
    second = smoother.update(synthetic_body(center=(0.5, 0.5), height=0.8), 0.1)
    held = smoother.update(None, 0.2)
    ok = first is None and second is not None and held is not None
    return Check("тело: скелет не мигает", ok,
                 f"первый кадр={first is None}, со второго видно={second is not None}, "
                 f"пропуск держится={held is not None}")


def check_window_scale() -> Check:
    """Окно предпросмотра: доля экрана и пропорции кадра."""
    from .app import AirMouseApp
    from .config import AppConfig

    cfg = AppConfig()
    cfg.window_scale = 0.85
    app = AirMouseApp(cfg, dry_run=True, show_window=True)
    app._prepared = True
    app._frame_size = (960, 540)
    app.screen_size = lambda: (1920, 1080)
    w, h = app.window_target_size()
    ok = abs(w - int(1920 * 0.85)) <= 2 and abs(h - w * 540 / 960) <= 2
    return Check("окно: картинка на весь экран, а не окошко", ok,
                 f"экран 1920x1080 -> окно {w}x{h}")


CHECKS: List[Callable[[], Check]] = [
    check_filters,
    check_hysteresis,
    check_gestures,
    check_builtin_gestures,
    check_debounce,
    check_head_pointer,
    check_modes,
    check_hand_side,
    check_keys_any_layout,
    check_sad_not_smile,
    check_gaze,
    check_blink_rules,
    check_hand_gate,
    check_gaze_calibration,
    check_gaze_pursuit,
    check_motion_profile,
    check_body_squats,
    check_body_overlay,
    check_head_gain,
    check_gaze_dwell,
    check_gaze_accuracy,
    check_gaze_direction,
    check_hand_tracker,
    check_hand_physics,
    check_body_stability,
    check_window_scale,
    check_settings_panel,
    check_rotation,
    check_click_fsm,
    check_drag_fsm,
    check_scroll_fsm,
    check_pause_fsm,
    check_open_palm_flat,
    check_face_blink,
    check_face_smile,
    check_face_brow,
    check_face_wink,
    check_head_pose,
    check_pointer,
    check_actions,
    check_lip_dtw,
    check_lip_reader,
    check_classical_detector,
    check_classical_fsm,
]


def run_selftest(verbose: bool = True) -> int:
    results: List[Check] = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as exc:  # проверка не должна ронять весь прогон
            results.append(Check(fn.__name__, False, f"исключение: {exc}"))
    failed = [r for r in results if not r.ok]
    if verbose:
        width = max(len(r.name) for r in results)
        for r in results:
            mark = "OK  " if r.ok else "FAIL"
            print(f"[{mark}] {r.name:<{width}}  {r.detail}")
    return 0 if not failed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_selftest())
