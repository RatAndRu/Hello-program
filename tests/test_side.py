"""Сторона кисти: ладонь или тыл — и разные команды для них."""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, HandConfig
from airmouse.gestures import (
    HandFSM,
    HandSide,
    SideEstimator,
    hand_normal_score,
    synthetic_hand,
)
from airmouse.settings_ui import SettingsPanel


def _ok_hand(back: bool = False):
    return synthetic_hand(pinch_index=True,
                          curl={"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0},
                          back=back)


def _warm(fsm, back: bool = False, frames: int = 6):
    """Держим в кадре нейтральную кисть нужной стороной, пока оценщик успокоится."""
    neutral = synthetic_hand(curl={"index": 0.45, "middle": 0.45,
                                   "ring": 0.45, "pinky": 0.45}, back=back)
    _feed(fsm, neutral, frames=frames)


def _feed(fsm, hand, frames=5, start=0.0, step=0.04):
    events = []
    for i in range(frames):
        events += fsm.update(hand, start + i * step)
    return events


# --------------------------------------------------------------------------- #
#  Оценка нормали
# --------------------------------------------------------------------------- #
def test_normal_score_distinguishes_sides():
    assert hand_normal_score(synthetic_hand()) > 0.5
    assert hand_normal_score(synthetic_hand(back=True)) < -0.5


def test_estimator_needs_calibration():
    cfg = HandConfig()
    est = SideEstimator(cfg)
    for _ in range(6):
        assert est.update(synthetic_hand()) is HandSide.UNKNOWN
        assert est.calibrated is False
    assert est.calibrate() is True
    assert est.side is HandSide.PALM
    assert cfg.side_reference > 0


def test_estimator_has_hysteresis():
    cfg = HandConfig()
    est = SideEstimator(cfg)
    palm, back = synthetic_hand(), synthetic_hand(back=True)
    for _ in range(4):
        est.update(palm)
    est.calibrate()
    est.update(back)
    est.update(back)                       # двух кадров мало (плюс медиана)
    assert est.side is HandSide.PALM
    est.update(back)
    est.update(back)                       # кадр медианы + гистерезис — теперь тыл
    assert est.side is HandSide.BACK
    est.update(palm)
    assert est.side is HandSide.BACK       # возврат тоже с гистерезисом


def test_estimator_keeps_side_when_hand_edge_on():
    cfg = HandConfig()
    est = SideEstimator(cfg)
    palm = synthetic_hand()
    for _ in range(4):
        est.update(palm)
    est.calibrate()
    # рука «ребром»: запястье и основания пальцев на одной прямой
    edge = synthetic_hand()
    pts = edge.points.copy()
    for idx in (5, 9, 17):
        pts[idx, :2] = pts[0, :2] + (pts[idx, :2] - pts[0, :2]) * 0.0
    est.update(type(edge)(pts))
    assert est.side is HandSide.PALM


def test_flip_inverts_calibration():
    cfg = HandConfig()
    est = SideEstimator(cfg)
    for _ in range(4):
        est.update(synthetic_hand())
    est.calibrate()
    reference = cfg.side_reference
    est.flip()
    assert cfg.side_reference == pytest.approx(-reference)
    for _ in range(4):
        est.update(synthetic_hand(back=True))
    assert est.side is HandSide.PALM     # после инверсии тыл считается ладонью


# --------------------------------------------------------------------------- #
#  Жесты: одно и то же движение, разные команды
# --------------------------------------------------------------------------- #
def _fsm(calibrated: bool = True, **overrides):
    cfg = HandConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    fsm = HandFSM(cfg)
    if calibrated:
        # калибруемся на ладони, как это делает пользователь клавишей K
        _feed(fsm, synthetic_hand(), frames=4)
        fsm.side_est.calibrate()
    return fsm


def test_ok_sign_palm_and_back_give_different_events():
    palm_fsm = _fsm()
    palm_events = [e.kind for e in _feed(palm_fsm, _ok_hand(), frames=10)
                   if e.kind.startswith("ok_sign")]
    assert palm_events == ["ok_sign"]
    assert palm_fsm.side is HandSide.PALM

    back_fsm = _fsm()
    _warm(back_fsm, back=True)
    back_events = [e.kind for e in _feed(back_fsm, _ok_hand(back=True), frames=10)
                   if e.kind.startswith("ok_sign")]
    assert back_events == ["ok_sign_back"]
    assert back_fsm.side is HandSide.BACK


def test_side_actions_can_be_switched_off():
    fsm = _fsm(side_actions=False)
    _warm(fsm, back=True)
    events = [e.kind for e in _feed(fsm, _ok_hand(back=True), frames=10)
              if e.kind.startswith("ok_sign")]
    assert events == ["ok_sign"]


def test_rock_and_three_with_back_side():
    rock_back = synthetic_hand(back=True,
                               curl={"index": 0.0, "middle": 1.0, "ring": 1.0, "pinky": 0.0})
    fsm = _fsm()
    _warm(fsm, back=True)
    events = [e.kind for e in _feed(fsm, rock_back, frames=10)
              if e.kind.startswith("rock_sign")]
    assert events == ["rock_sign_back"]

    three_back = synthetic_hand(back=True, curl={"pinky": 1.0})
    fsm = _fsm()
    _warm(fsm, back=True)
    events = [e.kind for e in _feed(fsm, three_back, frames=10)
              if e.kind.startswith("three_fingers")]
    assert events == ["three_fingers_back"]


def test_overlay_draws_side_line():
    """Строка «сторона кисти» реально попадает в кадр (а не только в state)."""
    import numpy as np

    from airmouse import overlay

    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    base = dict(fps=30.0, backend="ИИ MediaPipe (нейросеть)", actions_on=True,
                hand_seen=True, face_seen=False, version="тест")
    quiet = overlay.render(frame.copy(), overlay.OverlayState(**base), hands=[])
    loud = overlay.render(frame.copy(),
                          overlay.OverlayState(side_text="сторона кисти: тыл", **base),
                          hands=[])
    assert not np.array_equal(quiet, loud)


def test_default_mapping_gives_other_actions():
    mapping = AppConfig().actions.mapping
    assert mapping["ok_sign"] == "double_click"
    assert mapping["ok_sign_back"] == "right_click"
    assert mapping["rock_sign_back"] == "double_click"
    assert mapping["three_fingers_back"] == "toggle_pause"


# --------------------------------------------------------------------------- #
#  Приложение и панель настроек
# --------------------------------------------------------------------------- #
class _Tracker:
    name = "fake"

    def __init__(self, hand):
        self.hand = hand

    def process(self, frame, ts_ms):
        from airmouse.tracker import FrameResult

        return FrameResult(hands=[self.hand], face=None, backend="fake")

    def close(self):
        pass


def _app(hand):
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app.tracker = _Tracker(hand)
    app._prepared = True
    return app


def test_app_calibration_and_state_line():
    app = _app(_ok_hand())
    for i in range(6):
        app.process_frame(np.zeros((360, 640, 3), np.uint8), 100.0 + i * 0.04, i * 40)
    app._update_state([], 30.0)
    assert "не определена" in app.state.side_text
    assert app.calibrate_side() is True
    assert app.cfg.hand.side_reference != 0
    app._update_state([], 30.0)
    assert app.state.side_text == "сторона кисти: ладонь"
    assert any("калибровка" in line for line in app._events_log)


def test_app_flip_side():
    app = _app(_ok_hand())
    for i in range(6):
        app.process_frame(np.zeros((360, 640, 3), np.uint8), 100.0 + i * 0.04, i * 40)
    app.calibrate_side()
    reference = app.cfg.hand.side_reference
    app.flip_side()
    assert app.cfg.hand.side_reference == pytest.approx(-reference)


def test_panel_calibration_buttons():
    cfg = AppConfig()
    calls = {"calibrate": 0, "flip": 0}
    panel = SettingsPanel(cfg, runtime=None, hooks={
        "calibrate": lambda: calls.__setitem__("calibrate", calls["calibrate"] + 1) or True,
        "flip": lambda: calls.__setitem__("flip", calls["flip"] + 1),
        "side": lambda: "ладонь",
    })
    panel.open()
    panel.goto_page(0)
    buttons = {name: rect for name, rect in panel.side_buttons()}
    assert "КАЛИБРОВАТЬ ЛАДОНЬ (K)" in buttons
    assert panel.side_state() == "ладонь"

    def click(rect):
        x, y, w, h = rect
        return panel.on_mouse(1, x + w // 2, y + h // 2)   # cv2.EVENT_LBUTTONDOWN

    click(buttons["КАЛИБРОВАТЬ ЛАДОНЬ (K)"])
    assert calls["calibrate"] == 1
    assert "ладонь" in panel.status
    click(buttons["ИНВЕРТИРОВАТЬ"])
    assert calls["flip"] == 1
    toggle_name = [n for n in buttons if n.startswith("ТЫЛОМ")][0]
    click(buttons[toggle_name])
    assert cfg.hand.side_actions is False
