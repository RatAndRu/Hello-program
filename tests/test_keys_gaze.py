"""Горячие клавиши в любой раскладке, грусть ≠ улыбка, зрачки и мышь глазами."""

import numpy as np
import pytest

from airmouse import keys
from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, FaceConfig
from airmouse.face import FaceFSM, FaceMetrics, measure_face
from airmouse.settings_ui import SettingsPanel, modes_summary
from airmouse.synthetic import synthetic_face


# --------------------------------------------------------------------------- #
#  Раскладка
# --------------------------------------------------------------------------- #
def test_keys_work_in_russian_layout():
    # латиница, кириллица в Unicode и байт cp1251 (так отдаёт waitKey на Windows)
    for code in (ord("q"), ord("Q"), ord("й"), ord("Й"), 0xE9, 0xC9):
        assert keys.matches(code, "q"), hex(code)
    for code in (ord("k"), ord("л"), 0xEB):
        assert keys.matches(code, "k"), hex(code)
    for code in (ord("g"), ord("п")):
        assert keys.matches(code, "g"), hex(code)


def test_keys_ignore_arrows_and_unrelated_keys():
    arrow_left = 65361                       # OpenCV: стрелка влево
    assert keys.matches(arrow_left, "q") is False
    assert keys.matches(ord("z"), "q") is False
    assert keys.matches(-1, "q") is False    # клавиши не было


def test_special_keys():
    assert keys.matches(27, "esc")
    assert keys.matches(9, "tab")
    assert keys.matches(32, "space")
    assert keys.matches(27, "space") is False


def test_app_hotkeys_by_layout():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app._prepared = True
    assert app.handle_hotkey(ord("п")) is True          # «п» = G, мышь глазами
    assert app.router.gaze_pointer is True
    assert app.handle_hotkey(ord("G")) is True
    assert app.router.gaze_pointer is False
    assert app.handle_hotkey(ord("з")) is True          # «з» = P, пауза
    assert app.router.paused is True
    assert app.handle_hotkey(27) is True                # Esc — выход
    assert app.running is False


def test_settings_panel_keys_by_layout():
    panel = SettingsPanel(AppConfig())
    panel.open()
    assert panel.on_key(ord("2")) == "page"             # цифры страниц
    assert panel.page == 1
    assert panel.on_key(ord("ы")) == "save"             # «ы» — это клавиша S
    assert panel.is_open is False

    panel.open()
    assert panel.on_key(ord("к")) == "reset"            # «к» — это клавиша R
    assert panel.on_key(ord("с")) in ("save", "close")   # «с» — это клавиша C


# --------------------------------------------------------------------------- #
#  Грусть и улыбка
# --------------------------------------------------------------------------- #
def _warm(fsm, frames=6, t=0.0):
    for _ in range(frames):
        fsm.update(measure_face(synthetic_face()), t)
        t += 0.05
    return t


def test_frown_is_sadness_not_smile():
    fsm = FaceFSM(FaceConfig())
    t = _warm(fsm)
    events = []
    for _ in range(15):
        events += fsm.update(measure_face(synthetic_face(frown=0.10)), t)
        t += 0.05
    assert fsm.sad_score > 0.03
    assert fsm.smile_score <= 0.0
    assert all(e.kind != "smile_hold" for e in events)


def test_smile_still_works():
    fsm = FaceFSM(FaceConfig())
    t = _warm(fsm)
    events = []
    for _ in range(25):
        events += fsm.update(measure_face(synthetic_face(smile=0.04)), t)
        t += 0.05
    assert fsm.smile_score > 0.05
    assert fsm.sad_score == 0.0
    assert any(e.kind == "smile_hold" for e in events)


def test_expression_text_shows_sadness_not_smile():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app._prepared = True
    app.face_fsm.baseline.corner = 0.06
    app.face_fsm.sad_score = 0.05
    app.face_fsm.smile_score = 0.0
    app._metrics = FaceMetrics(valid=True, ear_left=0.3, ear_right=0.3,
                               corner_lift=0.01, mouth_open=0.1)
    text = app._expression_text()
    assert text.startswith("грусть")
    assert "улыбка" not in text


# --------------------------------------------------------------------------- #
#  Зрачки и мышь глазами
# --------------------------------------------------------------------------- #
def test_synthetic_face_has_iris_and_gaze():
    face = synthetic_face(gaze=(0.5, 0.0))
    assert face.has_iris and face.points.shape[0] == 478
    m = measure_face(face)
    assert m.gaze_valid and m.gaze_x > 0.3

    left = measure_face(synthetic_face(gaze=(-0.5, 0.0)))
    assert left.gaze_x < -0.3

    down = measure_face(synthetic_face(gaze=(0.0, 0.5)))
    assert down.gaze_y > 0.2


def test_without_iris_gaze_is_invalid():
    face = synthetic_face(iris=False)
    assert not face.has_iris
    m = measure_face(face)
    assert m.gaze_valid is False


def test_gaze_pointer_moves_cursor_only_when_looking_away():
    fsm = FaceFSM(FaceConfig())
    t = _warm(fsm, frames=8)
    assert fsm.gaze_step(1.0 / 30.0) == (0.0, 0.0)      # смотрит прямо — стоим

    for _ in range(12):
        fsm.update(measure_face(synthetic_face(gaze=(0.7, 0.0))), t)
        t += 0.04
    dx, dy = fsm.gaze_step(1.0 / 30.0)
    assert dx > 1.0 and abs(dy) < 0.5

    for _ in range(12):
        fsm.update(measure_face(synthetic_face(gaze=(-0.7, 0.0))), t)
        t += 0.04
    assert fsm.gaze_step(1.0 / 30.0)[0] < -1.0


def test_gaze_toggle_key_and_state():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app._prepared = True
    assert app.router.gaze_pointer is False
    assert app.toggle_gaze_pointer().endswith("on")
    assert app.cfg.gaze_pointer is True
    app._metrics = FaceMetrics(valid=True, ear_left=0.3, ear_right=0.3,
                              gaze_x=0.5, gaze_y=0.0, gaze_valid=True)
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_x = 0.5
    app.face_fsm.baseline.gaze_x = 0.0
    assert "вправо" in app.gaze_text()
    assert "ВКЛ" in app.gaze_text()

    app.toggle_gaze_pointer()
    assert app.router.gaze_pointer is False


def test_gaze_mode_in_panel_and_summary():
    cfg = AppConfig()
    runtime = type("R", (), {"head_pointer": False, "gaze_pointer": True})()
    assert "мышь глазами" in modes_summary(cfg, runtime)
    panel = SettingsPanel(cfg)
    keys_ = [t.key for t in __import__("airmouse.settings_ui", fromlist=["TOGGLES"]).TOGGLES]
    assert "mode.gaze_pointer" in keys_


def test_pointer_rel_from_gaze_reaches_router():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app._prepared = True
    app.router.gaze_pointer = True
    app._metrics = FaceMetrics(valid=True, ear_left=0.3, ear_right=0.3,
                               gaze_x=0.6, gaze_y=0.0, gaze_valid=True)
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_x = 0.6
    app.face_fsm.baseline.gaze_x = 0.0
    app._last_now = 1.0
    events = app._gaze_pointer_events(1.05)
    assert events and events[0].kind == "pointer_rel"
    assert events[0].value[0] > 0


def test_overlay_shows_gaze_line():
    from airmouse import overlay

    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    base = dict(fps=30.0, backend="ИИ MediaPipe (нейросеть)", actions_on=True,
                hand_seen=True, face_seen=True, version="тест")
    quiet = overlay.render(frame.copy(), overlay.OverlayState(**base), hands=[])
    loud = overlay.render(frame.copy(),
                          overlay.OverlayState(gaze_text="взгляд: вправо", **base),
                          hands=[])
    assert not np.array_equal(quiet, loud)
