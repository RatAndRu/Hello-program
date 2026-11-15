"""Конвейер приложения целиком: синтетические точки -> события -> «мышь».

Трекер здесь подменяется: камера и MediaPipe не нужны, проверяется именно
склейка слоёв (app.process_frame + pointer + actions).
"""

from __future__ import annotations

import numpy as np

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gestures import synthetic_hand
from airmouse.synthetic import synthetic_face
from airmouse.tracker import FrameResult

OTHER = {"middle": 1, "ring": 1, "pinky": 1}
EMPTY_FRAME = np.zeros((360, 640, 3), dtype=np.uint8)


class FakeTracker:
    """Отдаёт заранее заготовленные кадры вместо работы с камерой."""

    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.index = 0

    def process(self, frame, ts_ms):
        hand, face = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return FrameResult(hands=[hand] if hand is not None else [], face=face, backend="fake")

    def close(self):
        pass


def make_app(script, **cfg_overrides) -> AirMouseApp:
    cfg = AppConfig()
    for path, value in cfg_overrides.items():
        node = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = FakeTracker(script)
    app._prepared = True
    return app


def test_pinch_produces_one_click():
    frames = []
    for _ in range(4):
        frames.append((synthetic_hand(curl=OTHER), None))
    for _ in range(4):
        frames.append((synthetic_hand(curl=OTHER, pinch_index=True), None))
    for _ in range(5):
        frames.append((synthetic_hand(curl=OTHER), None))
    app = make_app(frames)
    now = 100.0
    for _ in range(len(frames)):
        app.process_frame(EMPTY_FRAME, now, int(now * 1000))
        now += 1 / 30.0
    clicks = [entry for entry in app.backend.log if entry.startswith("click(left")]
    assert clicks == ["click(leftx1)"]
    assert app.stats.clicks == 1


def test_drag_holds_and_releases_button():
    frames = [(synthetic_hand(curl=OTHER), None)] * 3
    for i in range(16):
        frames.append(
            (synthetic_hand(center=(0.45 + 0.012 * i, 0.6), curl=OTHER, pinch_index=True), None)
        )
    frames += [(synthetic_hand(curl=OTHER), None)] * 4
    app = make_app(frames)
    now = 200.0
    for _ in range(len(frames)):
        app.process_frame(EMPTY_FRAME, now, int(now * 1000))
        now += 1 / 30.0
    log = app.backend.log
    assert "down(left)" in log and "up(left)" in log

    down = log.index("down(left)")
    up = log.index("up(left)")
    assert down < up


def test_double_blink_clicks():
    neutral = (None, synthetic_face())
    frames = [neutral] * 4  # калибровка нейтрали
    for _ in range(3):
        frames.append((None, synthetic_face(ear=(0.08, 0.08))))
    frames.append(neutral)
    for _ in range(3):
        frames.append((None, synthetic_face(ear=(0.08, 0.08))))
    frames += [neutral] * 4
    app = make_app(frames)
    now = 300.0
    for _ in range(len(frames)):
        app.process_frame(EMPTY_FRAME, now, int(now * 1000))
        now += 1 / 25.0
    assert "click(leftx1)" in app.backend.log


def test_open_palm_pauses_and_resumes():
    frames = [(synthetic_hand(), None)] * 40
    frames += [(None, None)] * 6
    frames += [(synthetic_hand(), None)] * 40
    app = make_app(frames)
    now = 400.0
    for _ in range(len(frames)):
        app.process_frame(EMPTY_FRAME, now, int(now * 1000))
        now += 1 / 30.0
    assert app.router.paused is False  # пауза была включена и снята
    assert any("paused=True" in entry for entry in app.router.log)
    assert app.router.log.count("paused=False") >= 1


def test_head_pointer_moves_cursor():
    frames = [(None, synthetic_face(yaw=0.0))] * 6
    frames += [(None, synthetic_face(yaw=20.0))] * 10
    app = make_app(frames, **{"head_pointer": True})
    start = app.backend.position()
    now = 500.0
    for _ in range(len(frames)):
        app.process_frame(EMPTY_FRAME, now, int(now * 1000))
        now += 1 / 30.0
    moved = app.backend.position()
    assert moved != start
    assert moved[0] > start[0]  # повернул голову вправо — курсор вправо


def test_pause_freezes_pointer():
    app = make_app([(synthetic_hand(curl=OTHER), None)] * 3)
    app.router.paused = True
    pos = app.backend.position()
    app.process_frame(EMPTY_FRAME, 600.0, 600000)
    assert app.backend.position() == pos


def test_window_close_detected(monkeypatch):
    """Крестик окна должен останавливать приложение, а не переоткрывать окно."""
    import cv2

    app = make_app([(None, None)])
    app._window_name = "AirMouse-test"

    monkeypatch.setattr(cv2, "getWindowProperty", lambda *a, **k: 1.0)
    assert app._window_closed() is False

    monkeypatch.setattr(cv2, "getWindowProperty", lambda *a, **k: 0.0)
    assert app._window_closed() is True

    def raise_error(*args, **kwargs):
        raise cv2.error("окна нет")

    monkeypatch.setattr(cv2, "getWindowProperty", raise_error)
    assert app._window_closed() is True


def test_switch_backend_reports_failure(monkeypatch):
    """Если второй движок не поднимается — приложение продолжает работать."""
    import airmouse.app as app_module

    app = make_app([(None, None)])
    original = app.tracker

    def boom(*args, **kwargs):
        raise RuntimeError("нет моделей")

    monkeypatch.setattr(app_module, "create_tracker", boom)
    assert app.switch_backend() == getattr(original, "name", "fake")
    assert "нет моделей" in app.state.backend_note
