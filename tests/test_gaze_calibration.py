"""Калибровка взгляда: «куда смотрю» → «куда поставить курсор»."""

import math
import time

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gaze import (
    CALIBRATION_TARGETS,
    GazeCalibration,
    GazeCursor,
    average_gaze,
)
from airmouse.settings_ui import SettingsPanel
from airmouse.synthetic import synthetic_face
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)
# простая «анатомия»: зрачок ходит на ±0.3 по горизонтали и ±0.15 по вертикали
GAZE_RANGE_X = 0.6
GAZE_RANGE_Y = 0.3


def gaze_for(screen_x: float, screen_y: float):
    return ((screen_x - 0.5) * GAZE_RANGE_X, (screen_y - 0.5) * GAZE_RANGE_Y)


def _calibrated() -> GazeCalibration:
    calib = GazeCalibration()
    for sx, sy in CALIBRATION_TARGETS:
        gx, gy = gaze_for(sx, sy)
        calib.add(gx, gy, sx, sy)
    assert calib.fit()
    return calib


# --------------------------------------------------------------------------- #
#  Математика
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("point", [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.25, 0.75)])
def test_affine_mapping_restores_screen_point(point):
    calib = _calibrated()
    sx, sy = calib.apply(*gaze_for(*point))
    assert sx == pytest.approx(point[0], abs=0.02)
    assert sy == pytest.approx(point[1], abs=0.02)


def test_mapping_clamps_to_screen():
    calib = _calibrated()
    sx, sy = calib.apply(10.0, -10.0)
    assert 0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0


def test_single_axis_fallback():
    """Если человек двигал глазами только по горизонтали — каждая ось своя."""
    calib = GazeCalibration()
    for gx, sx in ((-0.3, 0.1), (0.0, 0.5), (0.3, 0.9)):
        calib.add(gx, 0.0, sx, 0.5)
    assert calib.fit() and calib.ready
    assert calib.apply(0.15, 0.0)[0] == pytest.approx(0.7, abs=0.05)


def test_round_trip_and_broken_data():
    calib = _calibrated()
    again = GazeCalibration.from_dict(calib.to_dict())
    assert again.ready
    assert again.apply(0.1, 0.05) == pytest.approx(calib.apply(0.1, 0.05))
    assert GazeCalibration.from_dict({}).ready is False
    assert GazeCalibration.from_dict({"points": "мусор", "coef_x": 5}).ready is False
    assert GazeCalibration().apply(0.1, 0.1) == (0.5, 0.5)


def test_cursor_teleports_and_ignores_jitter():
    cursor = GazeCursor(deadzone_px=12, alpha=1.0)
    assert cursor.update(300, 300) == (300, 300)      # первый раз — сразу туда
    assert cursor.update(305, 304) is None            # дрожание — стоим
    assert cursor.update(1000, 800) == (1000, 800)    # перевели взгляд — телепорт


def test_average_gaze():
    assert average_gaze([(0.1, 0.2), (0.3, 0.4)]) == pytest.approx((0.2, 0.3))
    assert average_gaze([]) == (0.0, 0.0)


# --------------------------------------------------------------------------- #
#  Мастер калибровки в приложении
# --------------------------------------------------------------------------- #
def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for path, value in overrides.items():
        node = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    if "face.gaze_head_check_s" not in overrides:
        # в тестах точек вторая фаза (поворот головы) не нужна
        cfg.face.gaze_head_check_s = 0.0
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    app.face_fsm.gaze_valid = True
    return app


def _look(app: AirMouseApp, sx: float, sy: float) -> None:
    gx, gy = gaze_for(sx, sy)
    app.face_fsm.gaze_valid = True
    # и «сырой», и компенсированный взгляд (в мышку идёт второй)
    app.face_fsm.gaze_x, app.face_fsm.gaze_y = gx, gy
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
    for _ in range(5):
        app._collect_gaze_sample()


def test_wizard_collects_five_points_and_saves():
    app = _app()
    app.start_gaze_calibration()
    assert app.calibrating
    assert app.calibration_target() == CALIBRATION_TARGETS[0]
    assert f"1/{len(CALIBRATION_TARGETS)}" in app.calibration_text()

    for index, (sx, sy) in enumerate(CALIBRATION_TARGETS):
        assert app.calibration_target() == (sx, sy)
        _look(app, sx, sy)
        app.confirm_gaze_point()
        if index < len(CALIBRATION_TARGETS) - 1:
            assert app.calibrating

    assert app.calibrating is False
    assert app.gaze_calib.ready
    # калибровка сохранилась в конфиг — после перезапуска не нужна заново
    assert app.cfg.face.gaze_calibration["H"]
    assert app.cfg.face.gaze_absolute is True
    sx, sy = app.gaze_calib.apply(*gaze_for(0.5, 0.5))
    assert sx == pytest.approx(0.5, abs=0.03)


def test_wizard_requires_a_moment_of_looking():
    app = _app()
    app.start_gaze_calibration()
    _look(app, *CALIBRATION_TARGETS[0])
    app._calib["samples"] = app._calib["samples"][:1]      # слишком мало кадров
    text = app.confirm_gaze_point()
    assert "ещё мгновение" in text
    assert app.calibration_target() == CALIBRATION_TARGETS[0]


def test_wizard_cancel_and_reset():
    app = _app()
    app.start_gaze_calibration()
    app.cancel_gaze_calibration()
    assert app.calibrating is False and not app.gaze_calib.ready

    app.gaze_calib = _calibrated()
    app.cfg.face.gaze_calibration = app.gaze_calib.to_dict()
    app.reset_gaze_calibration()
    assert not app.gaze_calib.ready
    assert app.cfg.face.gaze_calibration == {}


def test_hotkeys_start_and_confirm_calibration():
    from airmouse import keys

    app = _app()
    assert app.handle_hotkey(ord("b")) is True            # B — начать (латиница)
    assert app.calibrating
    _look(app, *CALIBRATION_TARGETS[0])
    assert app.handle_hotkey(32) is True                  # пробел — подтвердить
    assert app.calibration_target() == CALIBRATION_TARGETS[1]
    assert app.handle_hotkey(27) is True                  # Esc — отмена
    assert app.calibrating is False
    assert keys.matches(ord("и"), "b")                    # «и» — та же клавиша


# --------------------------------------------------------------------------- #
#  Абсолютный режим: курсор телепортируется
# --------------------------------------------------------------------------- #
def test_absolute_mode_teleports_cursor():
    app = _app()
    app.gaze_calib = _calibrated()
    app.router.gaze_pointer = True
    app._metrics = object()                               # «лицо видно»
    _look(app, 0.9, 0.9)
    app._last_now = 1.0
    events = app._gaze_pointer_events(1.05)
    assert events and events[0].kind == "pointer"
    x, y = events[0].value
    assert x == pytest.approx(0.9 * 1920, abs=40)
    assert y == pytest.approx(0.9 * 1080, abs=40)
    # после телепорта мелкое дрожание курсор не двигает
    assert app._gaze_pointer_events(1.1) == []


def test_without_calibration_falls_back_to_velocity():
    app = _app()
    app.router.gaze_pointer = True
    app._metrics = object()
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_x = app.face_fsm.gaze_u = 0.3
    app.face_fsm.gaze_y = 0.0
    app._last_now = 1.0
    events = app._gaze_pointer_events(1.05)
    assert events and events[0].kind == "pointer_rel"


# --------------------------------------------------------------------------- #
#  Глаза работают и без режима «Лицо»
# --------------------------------------------------------------------------- #
class FaceOnlyTracker:
    name = "fake"

    def __init__(self) -> None:
        self.face = synthetic_face(gaze=(0.25, 0.0))

    def process(self, frame, ts_ms):
        return FrameResult(hands=[], face=self.face, backend="fake")

    def close(self):
        pass


def test_gaze_works_when_face_mode_is_off():
    app = _app(**{"face.enabled": False})
    app.tracker = FaceOnlyTracker()
    for i in range(40):
        app.process_frame(EMPTY, 100.0 + i * 0.05, i * 50)
    assert app._metrics is not None, "метрики лица нужны и без режима «Лицо»"
    assert app.face_fsm.gaze_valid
    assert abs(app.face_fsm.gaze_x) > 0.1


def test_face_gestures_stay_off_when_face_mode_is_off():
    app = _app(**{"face.enabled": False})
    app.tracker = FaceOnlyTracker()
    events = []
    for i in range(60):
        events += app.process_frame(EMPTY, 100.0 + i * 0.05, i * 50)
    assert all(e.kind not in ("smile_hold", "brow_hold") for e in events)


# --------------------------------------------------------------------------- #
#  Кнопки в панели настроек
# --------------------------------------------------------------------------- #
def test_gaze_buttons_only_on_eyes_page():
    panel = SettingsPanel(AppConfig())
    panel.open()
    panel.goto_page(0)
    assert panel.gaze_buttons() == []
    panel.goto_page(4)
    names = [name for name, _rect in panel.gaze_buttons()]
    assert names == ["КАЛИБРОВАТЬ ВЗГЛЯД (B)", "СБРОСИТЬ КАЛИБРОВКУ"]


def test_gaze_calibrate_button_calls_hook():
    called = {}

    def hook():
        called["done"] = True
        return "калибровка взгляда: старт"

    panel = SettingsPanel(AppConfig(), hooks={"gaze_calibrate": hook})
    panel.open()
    panel.goto_page(4)
    _name, (bx, by, bw, bh) = panel.gaze_buttons()[0]
    action = panel.on_mouse(1, bx + bw // 2, by + bh // 2)   # LBUTTONDOWN
    assert called.get("done")
    assert action == "save"


# --------------------------------------------------------------------------- #
#  Качество калибровки: честная проверка «адекватности»
# --------------------------------------------------------------------------- #
def test_error_is_zero_on_exact_points():
    calib = _calibrated()
    worst, mean = calib.error()
    assert worst < 0.01 and mean < 0.01
    assert "ошибка" in calib.quality_text()


def test_error_grows_when_points_do_not_fit():
    """Точки «не по местам» — калибровка честно говорит, что промахивается."""
    calib = GazeCalibration()
    for i, (sx, sy) in enumerate(CALIBRATION_TARGETS):
        gx, gy = gaze_for(sx, sy)
        # на одной точке зрачок «уехал»: человек смотрел мимо или веко мешало
        if i == 2:
            gx, gy = gaze_for(0.5, 0.5)
        calib.add(gx, gy, sx, sy)
    assert calib.fit()
    worst, mean = calib.error()
    assert worst > 0.08
    assert "макс" in calib.quality_text()


def test_uneasy_calibration_warns_user():
    app = _app()
    app.start_gaze_calibration()
    for sx, sy in CALIBRATION_TARGETS:
        _look(app, sx, sy)
        app.confirm_gaze_point()
    text = app._events_log[0]
    assert "калибровка взгляда готова" in text
    assert "ошибка" in text


def test_bad_calibration_is_reported_as_bad():
    """Смотрели всё время в центр — калибровка так и говорит: промах 50%."""
    app = _app()
    app.start_gaze_calibration()
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_x = app.face_fsm.gaze_y = 0.0
    app.face_fsm.gaze_u = app.face_fsm.gaze_v = 0.0
    for _ in CALIBRATION_TARGETS:
        for _ in range(5):
            app._collect_gaze_sample()
        app.confirm_gaze_point()
    assert any("калибровка неточная" in line for line in app._events_log)
    worst, _mean = app.gaze_calib.error()
    assert worst > 0.08


# --------------------------------------------------------------------------- #
#  Гомография: девять точек лучше, чем «по осям»
# --------------------------------------------------------------------------- #
def _perspective_gaze(sx: float, sy: float):
    """Как зрачок видит наклонённую плоскость экрана: проективно, не аффинно."""
    w = 1.0 + 0.55 * (sx - 0.5) + 0.35 * (sy - 0.5)
    return (0.9 * (sx - 0.5) / w, 0.5 * (sy - 0.5) / w)


def test_nine_points_beat_affine_on_perspective():
    from airmouse.gaze import _affine_fallback

    calib = GazeCalibration()
    data = []
    for sx, sy in CALIBRATION_TARGETS:
        gx, gy = _perspective_gaze(sx, sy)
        calib.add(gx, gy, sx, sy)
        data.append((gx, gy, sx, sy))
    assert calib.fit()
    worst_h, mean_h = calib.error()
    assert worst_h < 0.01 and mean_h < 0.01        # гомография попадает точно

    # для сравнения — та же калибровка, но «по осям», без перспективы
    affine = _affine_fallback(np.asarray(data, dtype=np.float64))
    worst_a = 0.0
    for gx, gy, sx, sy in data:
        p = affine @ np.array([gx, gy, 1.0])
        p = p[:2] / p[2]
        worst_a = max(worst_a, abs(p[0] - sx), abs(p[1] - sy))
    assert worst_a > 0.1
    assert worst_a > worst_h * 5


def test_homography_interpolates_between_points():
    calib = GazeCalibration()
    for sx, sy in CALIBRATION_TARGETS:
        calib.add(*_perspective_gaze(sx, sy), sx, sy)
    assert calib.fit()
    for sx, sy in ((0.25, 0.25), (0.5, 0.75), (0.75, 0.5), (0.9, 0.1)):
        px, py = calib.apply(*_perspective_gaze(sx, sy))
        assert (px, py) == pytest.approx((sx, sy), abs=0.01)


# --------------------------------------------------------------------------- #
#  Поворот головы: «смотрю в ту же точку — курсор там же»
# --------------------------------------------------------------------------- #
HEAD_DRIFT = (0.30, -0.15)                     # насколько зрачок «уезжает» на tan


def _head_samples(center, drift=HEAD_DRIFT):
    """Кадры «человек вертит головой, а смотрит в центр»."""
    samples = []
    for yaw in range(-20, 21, 4):
        for pitch in (-12, 0, 12):
            gx = center[0] + drift[0] * math.tan(math.radians(yaw))
            gy = center[1] + drift[1] * math.tan(math.radians(pitch))
            samples.append((gx, gy, float(yaw), float(pitch)))
    return samples


def test_head_gain_learns_drift_from_samples():
    calib = _calibrated()
    center = gaze_for(0.5, 0.5)
    assert calib.fit_head(_head_samples(center)) is True
    assert calib.head_gain == pytest.approx(HEAD_DRIFT, abs=0.02)
    assert "поправка" in calib.head_gain_text()

    # любой поворот головы теперь даёт одну и ту же точку экрана
    points = []
    for gx, gy, yaw, pitch in _head_samples(center):
        u, v = calib.head_correct(gx, gy, yaw, pitch)
        points.append(calib.apply(u, v))
    points = np.asarray(points)
    assert float(np.ptp(points[:, 0])) < 0.01
    assert float(np.ptp(points[:, 1])) < 0.01
    assert points.mean(axis=0) == pytest.approx((0.5, 0.5), abs=0.02)


def test_head_gain_needs_real_movement():
    calib = _calibrated()
    center = gaze_for(0.5, 0.5)
    still = [(center[0], center[1], 0.0, 0.0) for _ in range(30)]
    assert calib.fit_head(still) is False
    assert calib.head_gain == [0.0, 0.0]
    assert "без компенсации" in calib.head_gain_text()
    # слишком мало кадров — тоже не выдумываем коэффициент
    assert calib.fit_head(_head_samples(center)[:4]) is False


def test_head_gain_survives_restart():
    calib = _calibrated()
    calib.fit_head(_head_samples(gaze_for(0.5, 0.5)))
    again = GazeCalibration.from_dict(calib.to_dict())
    assert again.head_gain == pytest.approx(calib.head_gain)


def test_wizard_turns_head_after_nine_points():
    app = _app(**{"face.gaze_head_check_s": 6.0})
    app.start_gaze_calibration()
    for index, (sx, sy) in enumerate(CALIBRATION_TARGETS):
        _look(app, sx, sy)
        app.confirm_gaze_point()
        if index < len(CALIBRATION_TARGETS) - 1:
            assert app._calib["phase"] == "points"
    # точки сняты, но мастер ещё не закончил: вторая фаза — поворот головы
    assert app.calibrating is True
    assert app._calib["phase"] == "head"
    assert app.calibration_target() == (0.5, 0.5)
    assert "голов" in app.calibration_text().lower()

    center = gaze_for(0.5, 0.5)
    for gx, gy, yaw, pitch in _head_samples(center):
        app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
        app.face_fsm.head_yaw, app.face_fsm.head_pitch = yaw, pitch
        app._tick_gaze_calibration(0.0)
    assert app.calibrating is True            # время ещё не вышло
    app._calib["head_since"] = time.monotonic() - 100.0
    app._tick_gaze_calibration(0.0)

    assert app.calibrating is False
    assert app.gaze_calib.ready
    assert app.gaze_calib.head_gain == pytest.approx(HEAD_DRIFT, abs=0.03)
    assert app.cfg.face.gaze_calibration["head_gain"] == pytest.approx(HEAD_DRIFT, abs=0.03)


def test_wizard_head_phase_can_be_skipped_with_space():
    app = _app(**{"face.gaze_head_check_s": 6.0})
    app.start_gaze_calibration()
    for sx, sy in CALIBRATION_TARGETS:
        _look(app, sx, sy)
        app.confirm_gaze_point()
    assert app._calib["phase"] == "head"
    app.confirm_gaze_point()                  # пробел во второй фазе = «готово»
    assert app.calibrating is False
    assert app.gaze_calib.ready
    assert app.gaze_calib.head_gain == [0.0, 0.0]


# --------------------------------------------------------------------------- #
#  Курсор не прыгает при повороте головы (весь путь до пикселей)
# --------------------------------------------------------------------------- #
def _pointer_point(app: AirMouseApp, u: float, v: float, yaw: float, pitch: float):
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = u, v
    app.face_fsm.head_yaw, app.face_fsm.head_pitch = yaw, pitch
    if app._metrics is None:
        app._metrics = app.face_fsm.metrics if hasattr(app.face_fsm, "metrics") else object()
    app.gaze_cursor.reset()
    events = app._gaze_pointer_events(1.0)
    assert events and events[0].kind == "pointer"
    return events[0].value


def test_cursor_stays_put_while_head_turns():
    app = _app(**{"face.gaze_head_check_s": 6.0})
    app.start_gaze_calibration()
    for sx, sy in CALIBRATION_TARGETS:
        _look(app, sx, sy)
        app.confirm_gaze_point()
    center = gaze_for(0.5, 0.5)
    for gx, gy, yaw, pitch in _head_samples(center):
        app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
        app.face_fsm.head_yaw, app.face_fsm.head_pitch = yaw, pitch
        app._tick_gaze_calibration(0.0)
    app._calib["head_since"] = time.monotonic() - 100.0
    app._tick_gaze_calibration(0.0)
    assert app.calibrating is False

    width, height = app.screen_size()
    points = []
    for gx, gy, yaw, pitch in _head_samples(center):
        points.append(_pointer_point(app, gx, gy, yaw, pitch))
    points = np.asarray(points, dtype=np.float64)
    # ни одного прыжка больше 2% экрана на поворотах до ±20°
    assert float(np.ptp(points[:, 0])) <= 0.02 * width
    assert float(np.ptp(points[:, 1])) <= 0.02 * height
    assert points.mean(axis=0) == pytest.approx((width / 2, height / 2), abs=0.03 * width)
