"""Самопроверка логики: без камеры, без экрана, без кликов.

Используется командой ``python -m airmouse selftest`` и тестами в ``tests/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import cv2
import numpy as np

from .actions import ActionRouter, DryRunBackend
from .config import AppConfig, FaceConfig, HandConfig, PointerConfig
from .face import FaceFSM, FaceMetrics, measure_face
from .filters import HysteresisGate, OneEuroFilter
from .gestures import HandFSM, Pose, analyze_hand, classify_pose, synthetic_hand
from .lipreading import LipReader, TemplateStore, dtw_distance, normalize_sequence
from .pointer import PointerMapper
from .settings_ui import DEFAULTS, SettingsPanel
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


def check_settings_panel() -> Check:
    """Ползунки настроек реально меняют конфиг и сохраняются в файл."""
    cfg = AppConfig()
    panel = SettingsPanel(cfg)
    panel.open()
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


CHECKS: List[Callable[[], Check]] = [
    check_filters,
    check_hysteresis,
    check_gestures,
    check_builtin_gestures,
    check_debounce,
    check_head_pointer,
    check_settings_panel,
    check_rotation,
    check_click_fsm,
    check_drag_fsm,
    check_scroll_fsm,
    check_pause_fsm,
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
