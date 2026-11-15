"""Калибровка взгляда идёт на весь монитор, а прицел — в самом углу экрана."""

import cv2
import numpy as np

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gaze import CALIBRATION_TARGETS, TARGET_TITLES
from airmouse.overlay import OverlayState, render, render_gaze_calibration
from airmouse.landmarks import Hand
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)
GREEN = np.array([90, 235, 130])        # цвет прицела (BGR)


def _state(target=(0.0, 0.0), done=0, text="ВЗГЛЯД: левый верхний угол экрана (1/5)"):
    return OverlayState(calib_active=True, calib_target=target, calib_done=done,
                        calib_text=text)


def _green_mask(img):
    return (np.abs(img.astype(np.int16) - GREEN).sum(axis=2) < 40)


# --------------------------------------------------------------------------- #
#  Геометрия: прицел в настоящих пикселях экрана
# --------------------------------------------------------------------------- #
def test_calibration_canvas_is_screen_sized():
    img = render_gaze_calibration((1920, 1080), _state())
    assert img.shape[:2] == (1080, 1920)
    img = render_gaze_calibration((1280, 720), _state())
    assert img.shape[:2] == (720, 1280)
    assert img.shape[:2] != (540, 960), "не окно предпросмотра, а весь экран"


def test_targets_are_exact_screen_corners():
    """Сетка 3×3: четыре самых угла, середины сторон и центр."""
    assert CALIBRATION_TARGETS[:4] == ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert CALIBRATION_TARGETS[-1] == (0.5, 0.5)
    assert len(CALIBRATION_TARGETS) == 9
    assert len(TARGET_TITLES) == len(CALIBRATION_TARGETS)
    # каждая точка — на сетке {0, 0.5, 1} по обеим осям
    for fx, fy in CALIBRATION_TARGETS:
        assert fx in (0.0, 0.5, 1.0) and fy in (0.0, 0.5, 1.0)


def test_corner_marker_is_in_the_far_corner():
    """Уголок нарисован в углу монитора, а не где-то в середине."""
    w, h = 1920, 1080
    img = render_gaze_calibration((w, h), _state((1.0, 0.0)))
    mask = _green_mask(img)
    ys, xs = np.nonzero(mask)
    assert xs.size and ys.size
    # прицел прижат к правому верхнему углу
    assert xs.max() >= w - 20 and xs.min() >= w // 2, (xs.min(), xs.max())
    assert ys.min() <= 20 and ys.max() <= h // 4, (ys.min(), ys.max())

    img = render_gaze_calibration((w, h), _state((0.0, 1.0)))
    mask = _green_mask(img)
    ys, xs = np.nonzero(mask)
    assert xs.min() <= 20 and ys.max() >= h - 20


def test_center_marker_is_in_the_middle():
    img = render_gaze_calibration((1920, 1080), _state((0.5, 0.5)))
    mask = _green_mask(img)
    ys, xs = np.nonzero(mask)
    cx, cy = xs.mean(), ys.mean()
    assert abs(cx - 960) < 60 and abs(cy - 540) < 60, (cx, cy)


def test_hint_and_progress_are_drawn():
    img = render_gaze_calibration((1920, 1080), _state((0.5, 0.5), done=3))
    assert img.mean() > 10, "фон не должен быть абсолютно чёрным"
    # точки прогресса: три зелёных + две серых внизу по центру
    bottom = img[1000:1080, :, :]
    assert _green_mask(bottom).sum() > 50


def test_all_five_targets_render_without_errors():
    for target in CALIBRATION_TARGETS:
        img = render_gaze_calibration((1366, 768), _state(target))
        assert img.shape[:2] == (768, 1366)
        assert _green_mask(img).sum() > 20, target


def test_preview_render_still_draws_calibration_on_frame():
    """Обычный кадр во время калибровки тоже показывает прицел (для скриншотов)."""
    frame = np.full((540, 960, 3), 40, dtype=np.uint8)
    img = render(frame, _state((0.0, 0.0)))
    assert img.shape == frame.shape
    assert img.mean() < frame.mean() + 60


# --------------------------------------------------------------------------- #
#  Приложение: полноэкранный режим и холст калибровки
# --------------------------------------------------------------------------- #
class ScriptedTracker:
    name = "fake"

    def __init__(self, hands):
        self.hands = hands

    def process(self, frame, ts_ms):
        return FrameResult(hands=list(self.hands), face=None, backend="fake")

    def close(self):
        pass


def _app(**overrides):
    cfg = AppConfig()
    for key, value in overrides.items():
        node = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    if "face.gaze_calib_mode" not in overrides:
        # эти тесты про запасной режим «девять прицелов»
        cfg.face.gaze_calib_mode = "points"
    if "face.gaze_head_check_s" not in overrides:
        cfg.face.gaze_head_check_s = 0.0     # вторая фаза не нужна
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = ScriptedTracker([])
    app._prepared = True
    return app


def test_screen_size_comes_from_backend():
    app = _app()
    app.backend.size = (1600, 900)
    assert app.screen_size() == (1600, 900)


def test_calibration_canvas_covers_whole_screen():
    app = _app()
    app.backend.size = (1920, 1080)
    app.start_gaze_calibration()
    canvas = app.calibration_canvas()
    assert canvas.shape[:2] == (1080, 1920)
    assert app.calibrating
    assert app.calibration_target() == CALIBRATION_TARGETS[0]
    app._update_state([], 30.0)
    assert app.state.calib_active and app.state.calib_done == 0
    assert app.state.calib_target == CALIBRATION_TARGETS[0]


def test_window_goes_fullscreen_during_calibration(monkeypatch):
    calls = []
    monkeypatch.setattr(cv2, "setWindowProperty",
                        lambda name, prop, value: calls.append(("prop", value)))
    monkeypatch.setattr(cv2, "moveWindow", lambda name, x, y: calls.append(("move", x, y)))
    monkeypatch.setattr(cv2, "resizeWindow", lambda name, w, h: calls.append(("resize", w, h)))

    app = _app()
    app._apply_window_mode()                     # обычный режим — ничего не меняем
    assert calls == []
    app.start_gaze_calibration()
    app._apply_window_mode()
    assert ("prop", cv2.WINDOW_FULLSCREEN) in calls
    assert ("move", 0, 0) in calls

    calls.clear()
    app.cancel_gaze_calibration()
    app._apply_window_mode()
    assert ("prop", cv2.WINDOW_NORMAL) in calls
    assert ("resize", 960, 540) in calls


def test_fullscreen_hotkey_toggles_window(monkeypatch):
    calls = []
    monkeypatch.setattr(cv2, "setWindowProperty",
                        lambda name, prop, value: calls.append(value))
    monkeypatch.setattr(cv2, "moveWindow", lambda *a: None)
    monkeypatch.setattr(cv2, "resizeWindow", lambda *a: None)
    app = _app()
    assert app.fullscreen is False
    app.handle_hotkey(ord("f"))                  # английская раскладка
    assert app.fullscreen is True
    app._apply_window_mode()
    assert cv2.WINDOW_FULLSCREEN in calls
    app.handle_hotkey(ord("а"))                  # та же клавиша по-русски
    assert app.fullscreen is False


def test_window_scale_maps_clicks_back_to_canvas(monkeypatch):
    """В полноэкранном окне клик приходит в пикселях экрана — пересчитываем."""
    monkeypatch.setattr(cv2, "getWindowImageRect", lambda name: (0, 0, 1920, 1080))
    app = _app()
    app._frame_size = (960, 540)
    sx, sy = app._window_scale()
    assert abs(sx - 0.5) < 1e-6 and abs(sy - 0.5) < 1e-6


GAZE_RANGE_X = 0.6
GAZE_RANGE_Y = 0.3


def gaze_for(screen_x: float, screen_y: float):
    return ((screen_x - 0.5) * GAZE_RANGE_X, (screen_y - 0.5) * GAZE_RANGE_Y)


def _look(app, sx: float, sy: float) -> None:
    gx, gy = gaze_for(sx, sy)
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_x, app.face_fsm.gaze_y = gx, gy
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
    for _ in range(5):
        app._collect_gaze_sample()


def test_calibration_on_screen_corners_covers_whole_screen():
    """Пять точек по настоящим углам дают точное преобразование по всему экрану."""
    from airmouse.gaze import GazeCalibration

    app = _app()
    app.backend.size = (1920, 1080)
    app.start_gaze_calibration()

    for index, (tx, ty) in enumerate(CALIBRATION_TARGETS):
        _look(app, tx, ty)
        app.confirm_gaze_point()
        if index < len(CALIBRATION_TARGETS) - 1:
            assert app.calibrating
    assert app.calibrating is False
    assert isinstance(app.gaze_calib, GazeCalibration)
    assert app.gaze_calib.ready
    # угол 0,0 и 1,1 отдаются как есть, без «сжатия» в окошко
    x0, y0 = app.gaze_calib.apply(*gaze_for(0.0, 0.0))
    x1, y1 = app.gaze_calib.apply(*gaze_for(1.0, 1.0))
    assert abs(x0) < 0.02 and abs(y0) < 0.02
    assert abs(x1 - 1.0) < 0.02 and abs(y1 - 1.0) < 0.02


def test_fullscreen_flag_from_cli(monkeypatch):
    """--fullscreen включает окно на весь экран."""
    from airmouse import cli

    captured = {}

    class FakeApp:
        tracker = None

        def __init__(self, cfg, **kw):
            captured["cfg"] = cfg

        def setup(self):
            pass

        def run(self):
            return 0

        def stop(self):
            pass

    monkeypatch.setattr("airmouse.app.AirMouseApp", FakeApp)
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **k: None)
    # в фоне без трея: не хотим поднимать настоящую иконку (в CI pystray есть)
    monkeypatch.setattr(cli, "tray_available", lambda: False)
    cli.main(["run", "--fullscreen", "--no-window"])
    assert captured["cfg"].fullscreen is True


# --------------------------------------------------------------------------- #
#  Точная геометрия: холст = окно, пиксель = пиксель
# --------------------------------------------------------------------------- #
def test_canvas_matches_window_not_pointer_space(monkeypatch):
    """Холст берётся из окна, а не из «настроек мыши» — иначе всё «раздувается».

    На экране с масштабом 125% система мыши говорит 1536×864, а окно на весь
    экран — 1920×1080. Раньше холст рисовался 1536×864 и растягивался окном,
    теперь холст ровно 1920×1080 и не масштабируется.
    """
    monkeypatch.setattr(cv2, "getWindowImageRect", lambda name: (0, 0, 1920, 1080))
    app = _app()
    app.backend.size = (1536, 864)              # «логический» размер системы мыши
    app.backend.size = (1536, 864)
    app.start_gaze_calibration()
    canvas = app.calibration_canvas()
    assert canvas.shape[:2] == (1080, 1920)
    assert "1920×1080" in app.state.calib_debug
    assert "1536×864" in app.state.calib_debug


def test_canvas_uses_window_size_even_if_not_fullscreen(monkeypatch):
    monkeypatch.setattr(cv2, "getWindowImageRect", lambda name: (0, 0, 1600, 900))
    app = _app()
    app.backend.size = (1920, 1080)
    app.start_gaze_calibration()
    canvas = app.calibration_canvas()
    assert canvas.shape[:2] == (900, 1600)
    assert "окно меньше экрана" in app.state.calib_debug


def test_corner_marker_touches_last_pixel():
    """Прицел стоит в самом угловом пикселе, а не «около»."""
    img = render_gaze_calibration((1920, 1080), _state((1.0, 1.0)))
    mask = _green_mask(img)
    assert mask[1079, 1919], "правый нижний угловой пиксель должен быть зелёным"
    assert not mask[0, 0], "а левый верхний — нет: прицел в правом нижнем"

    img = render_gaze_calibration((1920, 1080), _state((0.0, 0.0)))
    mask = _green_mask(img)
    assert mask[0, 0], "левый верхний угловой пиксель"
    assert not mask[1079, 1919]


def test_screen_point_is_exact_edge_to_edge():
    from airmouse.gaze import screen_point

    assert screen_point(0.0, 0.0, (1920, 1080), inset=0) == (0, 0)
    assert screen_point(1.0, 1.0, (1920, 1080), inset=0) == (1919, 1079)
    assert screen_point(0.5, 0.5, (1920, 1080), inset=0) == (960, 540)
    # с запасом в 1 пиксель: край достижим, но аварийный угол pyautogui не задет
    assert screen_point(0.0, 0.0, (1920, 1080)) == (1, 1)
    assert screen_point(1.0, 1.0, (1920, 1080)) == (1918, 1078)


def test_gaze_pointer_can_reach_far_edge_but_not_failsafe_corner():
    """Взгляд в угол ставит курсор в последний пиксель, не в (0,0)."""
    from airmouse.gaze import GazeCalibration

    app = _app()
    app.backend.size = (1920, 1080)
    calib = GazeCalibration()
    for gx, gy, sx, sy in ((0, 0, 0, 0), (1, 0, 1, 0), (1, 1, 1, 1), (0, 1, 0, 1), (.5, .5, .5, .5)):
        calib.add(gx, gy, sx, sy)
    assert calib.fit() and calib.ready
    app.gaze_calib = calib
    app.cfg.face.gaze_absolute = True
    app.gaze_cursor = __import__("airmouse.gaze", fromlist=["GazeCursor"]).GazeCursor(
        deadzone_px=0, alpha=1.0)
    app.face_fsm.gaze_valid = True
    app._metrics = object()

    app.face_fsm.gaze_x = app.face_fsm.gaze_y = 1.0
    app.face_fsm.gaze_u = app.face_fsm.gaze_v = 1.0
    events = app._gaze_pointer_events(1.0)
    point = events[-1].value
    assert point == (1918, 1078), point

    app.face_fsm.gaze_x = app.face_fsm.gaze_y = 0.0
    app.face_fsm.gaze_u = app.face_fsm.gaze_v = 0.0
    events = app._gaze_pointer_events(2.0)
    assert events[-1].value == (1, 1), events[-1].value


def test_corner_arms_are_flush_with_screen_edges():
    """«Г» прижата к краям: линии видны по всей толщине, внешняя кромка — край."""
    img = render_gaze_calibration((1920, 1080), _state((1.0, 0.0)))
    mask = _green_mask(img)
    # вдоль правого края — вертикальная линия от угла вниз
    assert mask[:100, 1919].sum() > 80
    assert mask[:100, 1915].sum() > 80
    # вдоль верхнего края — горизонтальная от угла влево
    assert mask[0, 1820:1919].sum() > 80
    assert mask[5, 1820:1919].sum() > 80
