"""Режимы управления: рука, вторая рука, две руки, лицо — и их сочетания."""

import cv2
import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gestures import synthetic_hand
from airmouse.settings_ui import (
    PRESETS,
    TOGGLES,
    SettingsPanel,
    apply_preset,
    current_preset,
    cycle_preset,
    modes_summary,
)
from airmouse.synthetic import synthetic_face
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)


def _toggle(key: str):
    return next(t for t in TOGGLES if t.key == key)


class FakeTracker:
    """Отдаёт заранее заданные кадры: список (руки, лицо)."""

    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.index = 0

    def process(self, frame, ts_ms):
        hands, face = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return FrameResult(hands=list(hands), face=face, backend="fake")

    def close(self):
        pass


def make_app(script, **overrides):
    cfg = AppConfig()
    for key, value in overrides.items():
        parts = key.split(".")
        node = cfg
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = FakeTracker(script)
    app._prepared = True
    return app


def _point_hand(x=0.45):
    return synthetic_hand(center=(x, 0.70), curl={"middle": 1.0, "ring": 1.0, "pinky": 1.0})


def _palm(x=0.70):
    return synthetic_hand(center=(x, 0.60))


# --------------------------------------------------------------------------- #
#  По умолчанию — только одна рука
# --------------------------------------------------------------------------- #
def test_default_is_single_hand():
    cfg = AppConfig()
    assert cfg.hand.enabled is True
    assert cfg.hand.roles == "single"
    assert cfg.hand.two_hand == "off"
    assert current_preset(cfg) == "РУКА + ЛИЦО"
    assert "2-я рука" not in modes_summary(cfg)


def test_second_hand_does_nothing_by_default():
    """В стандартном режиме вторая рука не масштабирует и не нажимает."""
    left, right = _palm(0.32), _palm(0.72)
    script = []
    for i in range(14):
        # руки разводятся — раньше это крутило «масштаб»
        script.append(([synthetic_hand(center=(0.32 - i * 0.01, 0.6)),
                        synthetic_hand(center=(0.72 + i * 0.01, 0.6))], None))
    app = make_app(script)
    for i in range(len(script)):
        app.process_frame(EMPTY, 100.0 + i * 0.033, i * 33)
    assert not [entry for entry in app.backend.log if "zoom" in entry], app.backend.log


# --------------------------------------------------------------------------- #
#  Переключатели и наборы режимов
# --------------------------------------------------------------------------- #
def test_toggle_rows_flip_modes():
    cfg = AppConfig()
    panel = SettingsPanel(cfg)
    panel.open()
    panel.goto_page(0)
    rows = {toggle.key: rect for toggle, rect in panel.toggle_rows()}

    def click(key):
        x, y, w, h = rows[key]
        return panel.on_mouse(cv2.EVENT_LBUTTONDOWN, x + w - 20, y + h // 2)

    assert cfg.hand.roles == "single"
    click("mode.second_hand")
    assert cfg.hand.roles == "split"
    # режим нажатий исключает «две руки масштаб»
    click("mode.two_zoom")
    assert cfg.hand.two_hand == "zoom"
    assert cfg.hand.roles == "single"
    click("mode.face")
    assert cfg.face.enabled is False
    click("mode.face")
    assert cfg.face.enabled is True
    assert panel.dirty is True


def test_two_hand_modes_are_exclusive():
    cfg = AppConfig()
    runtime = type("R", (), {"head_pointer": False})()
    _toggle("mode.two_zoom").set(cfg, runtime, True)
    assert cfg.hand.two_hand == "zoom"
    _toggle("mode.two_scroll").set(cfg, runtime, True)
    assert cfg.hand.two_hand == "scroll"
    assert _toggle("mode.two_zoom").state(cfg, runtime) is False
    _toggle("mode.second_hand").set(cfg, runtime, True)
    assert cfg.hand.roles == "split"
    _toggle("mode.second_hand").set(cfg, runtime, False)
    assert cfg.hand.roles == "single"


def test_presets_cover_all_combinations():
    runtime = type("R", (), {"head_pointer": False})()
    cfg = AppConfig()

    apply_preset(cfg, runtime, "РУКА")
    assert cfg.hand.enabled and cfg.face.enabled is False and cfg.hand.roles == "single"
    assert cfg.hand.two_hand == "off"

    apply_preset(cfg, runtime, "РУКА + ЛИЦО")
    assert cfg.hand.enabled and cfg.face.enabled

    apply_preset(cfg, runtime, "ДВЕ РУКИ")
    assert cfg.hand.roles == "split" and cfg.hand.two_hand == "off"

    apply_preset(cfg, runtime, "ТОЛЬКО ЛИЦО")
    assert cfg.hand.enabled is False and cfg.face.enabled is True
    assert "рука" not in modes_summary(cfg, runtime)

    apply_preset(cfg, runtime, "РУКА + ЛИЦО")
    assert current_preset(cfg, runtime) == "РУКА + ЛИЦО"


def test_cycle_preset_goes_round():
    runtime = type("R", (), {"head_pointer": False})()
    cfg = AppConfig()
    apply_preset(cfg, runtime, "РУКА + ЛИЦО")
    seen = [cycle_preset(cfg, runtime) for _ in range(len(PRESETS))]
    assert set(seen) == set(PRESETS)


def test_head_pointer_toggle_switches_runtime():
    cfg = AppConfig()
    runtime = type("R", (), {"head_pointer": False})()
    assert _toggle("mode.head_pointer").state(cfg, runtime) is False
    _toggle("mode.head_pointer").set(cfg, runtime, True)
    assert runtime.head_pointer is True and cfg.head_pointer is True


# --------------------------------------------------------------------------- #
#  Сочетания: лицо + рука, только лицо
# --------------------------------------------------------------------------- #
def _blink_script(hands, frames=26):
    """Рука + два моргания подряд (двойное моргание -> левый клик)."""
    script = []
    for i in range(frames):
        closed = i in (14, 15, 18, 19)
        ear = (0.08, 0.08) if closed else (0.30, 0.30)
        script.append((hands, synthetic_face(ear=ear)))
    return script


def test_face_and_hand_work_together():
    app = make_app(_blink_script([_point_hand()]))
    for i in range(26):
        app.process_frame(EMPTY, 100.0 + i * 0.05, i * 50)
    log = app.backend.log
    assert any("move_to" in entry for entry in log), "рука должна вести курсор"
    assert any("click" in entry for entry in log), "моргание должно кликать"


def test_face_only_mode_ignores_hand():
    """«Только лицо»: рука в кадре ничего не нажимает, мимика работает."""
    pinch_hand = synthetic_hand(pinch_index=True)
    script = _blink_script([pinch_hand])
    app = make_app(script, **{"hand.enabled": False})
    for i in range(26):
        app.process_frame(EMPTY, 100.0 + i * 0.05, i * 50)
    log = app.backend.log
    assert not any("move_to" in entry for entry in log), log
    assert any("click" in entry for entry in log), log
    app._update_state([], 30.0)
    assert app.state.modes_text == "режимы: лицо", app.state.modes_text


def test_two_hand_mode_cursor_and_face_together():
    """«Две руки» + лицо: первая ведёт курсор, вторая нажимает, лицо кликает."""
    pointer_hand = synthetic_hand(center=(0.30, 0.62), scale=0.26)
    click_hand = synthetic_hand(center=(0.72, 0.60), scale=0.17, pinch_index=True)
    script = _blink_script([pointer_hand, click_hand], frames=30)
    app = make_app(script, **{"hand.roles": "split"})
    for i in range(30):
        app.process_frame(EMPTY, 100.0 + i * 0.05, i * 50)
    log = app.backend.log
    assert any("move_to" in entry for entry in log)
    assert any("click" in entry for entry in log)
    app._update_state([], 30.0)
    assert "2-я рука" in app.state.modes_text


def test_cycle_modes_key_updates_state():
    app = make_app([([_point_hand()], None)] * 3)
    app.process_frame(EMPTY, 100.0, 0)
    first = app.cycle_modes()
    assert first in PRESETS
    assert any("режим:" in line for line in app._events_log)
    assert app.state.modes_text == "" or app.state.modes_text.startswith("режимы:")
