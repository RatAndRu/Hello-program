"""Окно предпросмотра и тело: картинка крупная, скелет не мигает."""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.body import BodySmoother, arm_points, synthetic_body
from airmouse.config import AppConfig
from airmouse.gestures import synthetic_hand
from airmouse.overlay import OverlayState, render
import airmouse.app as app_module


def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    app = AirMouseApp(cfg, dry_run=True, show_window=True)
    app._prepared = True
    app._frame_size = (960, 540)
    return app


# --------------------------------------------------------------------------- #
#  Размер окна: доля экрана и пропорции кадра
# --------------------------------------------------------------------------- #
def test_window_target_is_a_share_of_the_screen():
    app = _app(window_scale=0.85)
    app.screen_size = lambda: (1920, 1080)
    w, h = app.window_target_size()
    assert w == int(1920 * 0.85)
    assert h == pytest.approx(w * 540 / 960, abs=1)

    app.cfg.window_scale = 1.0
    w, h = app.window_target_size()
    assert w <= 1920 and h <= 1080
    assert (w, h) == (1920, 1080)


def test_window_target_keeps_camera_aspect():
    app = _app(window_scale=0.8)
    app.screen_size = lambda: (1920, 1080)
    app._frame_size = (640, 480)          # камера 4:3
    w, h = app.window_target_size()
    assert h == pytest.approx(w * 480 / 640, abs=1)


def test_preview_frame_is_scaled_to_the_window(monkeypatch):
    app = _app()
    monkeypatch.setattr(app_module.cv2, "getWindowImageRect",
                        lambda name: (0, 0, 1440, 810))
    app._preview_cache = None
    app._preview_at = 0.0
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    scaled = app._preview_frame(frame)
    assert scaled.shape[:2] == (810, 1440), "кадр растянут до окна, а не наоборот"


def test_preview_frame_untouched_when_sizes_match(monkeypatch):
    app = _app()
    monkeypatch.setattr(app_module.cv2, "getWindowImageRect",
                        lambda name: (0, 0, 960, 540))
    app._preview_cache = None
    app._preview_at = 0.0
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    assert app._preview_frame(frame) is frame


def test_overlay_layout_is_bigger_on_a_big_canvas():
    """На большом холсте панели рисуются крупнее — интерфейс не «мылится»."""
    state = OverlayState(hand_seen=True, face_seen=True, fps=29.0,
                         gaze_text="взгляд: прямо")
    small = render(np.zeros((540, 960, 3), dtype=np.uint8), state, hands=[], face=None)
    big = render(np.zeros((1080, 1920, 3), dtype=np.uint8), state, hands=[], face=None)
    assert big.shape[:2] == (1080, 1920)
    # доля занятой панелью площади примерно одна и та же
    small_panel = np.count_nonzero(small[0:200, 0:500].sum(axis=2))
    big_panel = np.count_nonzero(big[0:400, 0:1000].sum(axis=2))
    assert big_panel > small_panel * 2


# --------------------------------------------------------------------------- #
#  Тело: подтверждение, удержание, исчезновение
# --------------------------------------------------------------------------- #
def _body(**kw):
    return synthetic_body(center=(0.5, 0.5), height=0.8, **kw)


def test_body_needs_several_frames_to_appear():
    smoother = BodySmoother(confirm_frames=3)
    assert smoother.update(_body(), 0.0) is None
    assert smoother.update(_body(), 0.1) is None
    assert smoother.update(_body(), 0.2) is not None
    assert smoother.active is True


def test_single_missed_frame_does_not_blink_the_skeleton():
    smoother = BodySmoother(confirm_frames=2, hold_frames=6)
    for i in range(3):
        smoother.update(_body(), i * 0.1)
    assert smoother.update(None, 0.4) is not None, "один пропуск — поза держится"
    assert smoother.active is True


def test_body_disappears_when_gone_for_long():
    smoother = BodySmoother(confirm_frames=2, hold_frames=2)
    for i in range(3):
        smoother.update(_body(), i * 0.1)
    for i in range(3, 10):
        smoother.update(None, i * 0.1)
    assert smoother.active is False


def test_body_points_are_smoothed():
    smoother = BodySmoother(confirm_frames=1, min_cutoff=0.5)
    first = smoother.update(_body(), 0.0)
    moved = _body()
    moved[:, 0] += 0.05
    second = smoother.update(moved, 1 / 30)
    assert first is not None and second is not None
    # фильтр не прыгает на всю дельту сразу
    assert float(second[11, 0] - first[11, 0]) < 0.05


def test_arms_are_available_for_drawing_when_hand_is_lost():
    body = _body()
    body[:, 3] = 0.9
    arms = arm_points(body)
    assert arms, "по телу должно быть видно хотя бы одно плечо-локоть"


def test_hand_is_drawn_with_a_forearm(monkeypatch):
    """Кисть без предплечья выглядит обрубком: дорисовываем пунктиром."""
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    st = OverlayState(hand_seen=True, fps=30.0)
    hand = synthetic_hand(center=(0.5, 0.6), scale=0.2)
    with_arm = render(frame.copy(), st, hands=[hand], face=None)
    assert with_arm.shape == frame.shape
    # под запястьем появились пиксели предплечья (зелёный пунктир)
    assert int(with_arm.sum()) != int(frame.sum())
