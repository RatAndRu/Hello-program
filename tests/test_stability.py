"""Устойчивость управления: встроенные жесты, антидребезг, роли рук, мышь головой."""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, FaceConfig, HandConfig
from airmouse.face import FaceFSM, FaceMetrics
from airmouse.gestures import HandFSM, Pose, recognize_pose, synthetic_hand
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)


# --------------------------------------------------------------------------- #
#  Встроенные жесты: ОК, коза, три пальца — без обучения
# --------------------------------------------------------------------------- #
def _ok_hand(**kw):
    """«ОК»: указательный согнут в колечко с большим, три других выпрямлены."""
    return synthetic_hand(pinch_index=True,
                          curl={"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0}, **kw)


def test_ok_sign_pose_is_recognized():
    hand = _ok_hand()
    assert recognize_pose(hand, HandConfig()) is Pose.OK


def test_rock_sign_pose_is_recognized():
    hand = synthetic_hand(curl={"middle": 1.0, "ring": 1.0, "index": 0.0, "pinky": 0.0})
    assert recognize_pose(hand, HandConfig()) is Pose.ROCK


def test_three_fingers_pose_is_recognized():
    hand = synthetic_hand(curl={"index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 1.0})
    assert recognize_pose(hand, HandConfig()) is Pose.THREE


def test_ok_sign_fires_once_per_show():
    """Жест «ОК» даёт одно событие, а не поток событий каждый кадр."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    hand = _ok_hand()
    fired = []
    for i in range(12):
        fired += [e.kind for e in fsm.update(hand, 0.1 * i) if e.kind == "ok_sign"]
    assert len(fired) == 1


# --------------------------------------------------------------------------- #
#  Антидребезг: один «моргнувший» кадр не должен кликать
# --------------------------------------------------------------------------- #
def test_single_frame_pinch_spike_does_not_click():
    """Нейросеть на один кадр свела большой палец к указательному — не клик."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events = []
    t = 0.0
    for i in range(9):
        # одиночный выброс щипка в середине спокойного кадра
        hand = pinched if i == 4 else opened
        events += fsm.update(hand, t)
        t += 0.033
    assert not [e for e in events if e.kind == "pinch_release"]


def test_short_pinch_longer_than_median_but_below_min_s_does_not_click():
    """Щипок удержан 1 кадр (< hand.pinch_min_s) — это дрожание, а не клик."""
    cfg = HandConfig(pinch_min_s=0.20)
    fsm = HandFSM(cfg)
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events = []
    t = 0.0
    for _ in range(4):                      # «моргание» на два кадра
        events += fsm.update(pinched, t)
        t += 0.033
    events += fsm.update(opened, t)
    assert not [e for e in events if e.kind == "pinch_release"]


def test_real_pinch_still_clicks():
    """Настоящий щипок с удержанием по-прежнему даёт ровно один клик."""
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events = []
    t = 0.0
    for _ in range(4):
        events += fsm.update(opened, t)
        t += 0.033
    for _ in range(6):                      # держим щипок ~0.2 с (меньше drag_delay_s)
        events += fsm.update(pinched, t)
        t += 0.033
    for _ in range(3):                      # медиана отпускает с задержкой ~2 кадра
        events += fsm.update(opened, t)
        t += 0.033
    clicks = [e for e in events if e.kind == "pinch_release"]
    assert len(clicks) == 1


def test_marginal_finger_does_not_flicker_pose():
    """Палец «на границе» выпрямлен/согнут — жест не должен мигать."""
    from airmouse.gestures import HandFeatures, classify_pose

    feats = HandFeatures(
        palm_size=0.2,
        palm_center=np.zeros(2),
        pointer=np.zeros(2),
        extension={"thumb": 0.3, "index": 0.9, "middle": 0.55, "ring": 0.1, "pinky": 0.1},
        pinch=1.0,
        pinch_middle=1.0,
        pinch_ring=1.0,
        thumb_dy=0.0,
        thumb_spread=0.3,
    )
    # средний палец «на границе»: без прошлого кадра — PEACE, с прошлым POINT — держим POINT
    assert classify_pose(feats, HandConfig()) is Pose.PEACE
    assert classify_pose(feats, HandConfig(), prev=Pose.POINT) is Pose.POINT


# --------------------------------------------------------------------------- #
#  Роли рук: одна ведёт курсор, вторая только нажимает
# --------------------------------------------------------------------------- #
class ScriptedTracker:
    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.index = 0

    def process(self, frame, ts_ms):
        hands = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return FrameResult(hands=list(hands), face=None, backend="fake")

    def close(self):
        pass


def _app(script, **overrides):
    cfg = AppConfig()
    for key, value in overrides.items():
        parts = key.split(".")
        node = cfg
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = ScriptedTracker(script)
    app._prepared = True
    return app


def test_split_roles_cursor_only_from_first_hand():
    """Режим split: вторая рука щипком кликает, но курсор не сдвигает."""
    # главной становится рука крупнее в кадре (ближе к камере) — она ведёт курсор
    pointer_hand = synthetic_hand(center=(0.30, 0.55), scale=0.26)
    click_hand_open = synthetic_hand(center=(0.70, 0.55), scale=0.17)
    click_hand_pinch = synthetic_hand(center=(0.70, 0.62), scale=0.17, pinch_index=True)
    script = [[pointer_hand, click_hand_open]] * 4 + [[pointer_hand, click_hand_pinch]] * 10
    script += [[pointer_hand, click_hand_open]] * 3
    app = _app(script, **{"hand.roles": "split"})

    moves, clicks = [], []
    for i in range(len(script)):
        app.process_frame(EMPTY, 100.0 + i * 0.033, i * 33)
        moves += [entry for entry in app.backend.log if entry.startswith("move_to")]
        clicks += [entry for entry in app.backend.log if entry.startswith("click")]
        app.backend.log.clear()

    assert clicks, "щипок второй рукой должен дать клик"
    # первая рука стоит на месте, значит и курсор не должен гулять по экрану
    xs = [int(entry[len("move_to("):-1].split(",")[0]) for entry in moves]
    assert xs and max(xs) - min(xs) < 5, xs
    app._update_state([], 30.0)
    assert app.state.split_roles is True
    assert app.state.roles_text


def test_split_roles_second_hand_does_not_move_pointer():
    """Курсор не меняет позицию, пока вторая рука машет по кадру."""
    pointer_hand = synthetic_hand(center=(0.30, 0.55), scale=0.26)
    script = []
    for i in range(12):
        # вторая рука гуляет по кадру слева-направо, первая стоит на месте
        script.append([pointer_hand,
                       synthetic_hand(center=(0.55 + 0.02 * i, 0.3), scale=0.17)])
    app = _app(script, **{"hand.roles": "split"})

    positions = []
    for i in range(len(script)):
        app.process_frame(EMPTY, 100.0 + i * 0.033, i * 33)
        positions.append(app.backend.pos)

    steady = positions[4:]
    assert max(p[0] for p in steady) - min(p[0] for p in steady) < 40


# --------------------------------------------------------------------------- #
#  Мышь головой: чувствительность и «возврат не тянет курсор назад»
# --------------------------------------------------------------------------- #
def _face(yaw: float, pitch: float = 0.0) -> FaceMetrics:
    return FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=0.4,
                       mouth_open=0.02, brow_height=0.2, yaw=yaw, pitch=pitch, valid=True)


def _head_fsm(yaw_baseline: float = 0.0) -> FaceFSM:
    cfg = FaceConfig()
    fsm = FaceFSM(cfg)
    fsm.baseline.yaw = yaw_baseline
    fsm.baseline.pitch = 0.0
    fsm.baseline.samples = 20
    return fsm


def test_head_turn_moves_cursor_noticeably():
    """Раньше поворот головы давал «миллиметр»: теперь — десятки пикселей."""
    fsm = _head_fsm()
    fsm.update(_face(yaw=30.0), 0.0)
    dx, dy = fsm.head_step(1.0 / 30.0)
    assert dx > 20.0, dx
    assert abs(dy) < 1e-6


def test_head_return_to_neutral_does_not_drag_cursor_back():
    """Возврат головы в нормаль — курсор стоит, а не едет обратно."""
    fsm = _head_fsm()
    fsm.update(_face(yaw=30.0), 0.0)
    assert fsm.head_step(1.0 / 30.0)[0] > 20.0
    fsm.update(_face(yaw=0.0), 0.05)
    assert fsm.head_step(1.0 / 30.0) == (0.0, 0.0)
    # и в мёртвой зоне — тоже ничего
    fsm.update(_face(yaw=1.5), 0.1)
    assert fsm.head_step(1.0 / 30.0) == (0.0, 0.0)


def test_head_pointer_moves_cursor_relative():
    """При включённой «мыши головой» приложение шлёт относительное движение."""
    cfg = AppConfig()
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.router.head_pointer = True
    app.face_fsm.baseline.samples = 20
    app.face_fsm.update(_face(yaw=28.0), 0.0)
    app._metrics = _face(yaw=28.0)
    app._last_now = 0.0
    events = app._head_pointer_events(1.0 / 30.0)
    assert events and events[0].kind == "pointer_rel"
    assert events[0].value[0] > 10
