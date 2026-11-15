"""Калибровка взгляда «веди взгляд за красной точкой» и фазы мастера.

Идея (как в Eye Tracking у Apple, iOS 18): точка не стоит в углу и ждёт
пробела, а плавно ползёт по всему экрану, человек ведёт её глазами. Из такой
траектории получается сразу два измерения: соответствие «зрачок → экран»
(гомография по сотням проб вместо девяти) и динамика зрачка — насколько он
отстаёт и насколько согласованно двигается.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gaze import (
    PURSUIT_DURATION_S,
    PURSUIT_ROWS,
    GazeCalibration,
    pursuit_metrics,
    pursuit_point,
)

GAZE_RANGE_X = 0.6
GAZE_RANGE_Y = 0.3


def gaze_for(sx: float, sy: float):
    return ((sx - 0.5) * GAZE_RANGE_X, (sy - 0.5) * GAZE_RANGE_Y)


def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for path, value in overrides.items():
        node = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    if "face.gaze_head_check_s" not in overrides:
        cfg.face.gaze_head_check_s = 0.0
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    app.face_fsm.gaze_valid = True
    return app


def _look(app: AirMouseApp, sx: float, sy: float) -> None:
    gx, gy = gaze_for(sx, sy)
    app.face_fsm.gaze_valid = True
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
    app.face_fsm.gaze_x, app.face_fsm.gaze_y = gx, gy


def _drive(app: AirMouseApp, lag_frames: int = 0, noise: float = 0.004,
           outlier_every: int = 0, fps: float = 30.0, valid: bool = True) -> None:
    """Прогнать мастер до конца траектории, ведя взгляд за точкой."""
    dt = 1.0 / fps
    duration = float(app.cfg.face.gaze_pursuit_s)
    history = []
    frames = int(duration * fps) + 5
    rng = np.random.default_rng(7)
    for i in range(frames):
        t = i * dt
        dot = pursuit_point(min(t, duration - 1e-6), duration)
        history.append(dot)
        src = history[-1 - lag_frames] if i >= lag_frames else history[0]
        gx, gy = gaze_for(*src)
        gx += float(rng.normal(0.0, noise))
        gy += float(rng.normal(0.0, noise))
        if outlier_every and i % outlier_every == 0:
            gx += 0.18          # «моргнул»: зрачок скакнул
            gy -= 0.10
        app.face_fsm.gaze_valid = valid
        app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
        app.face_fsm.gaze_x, app.face_fsm.gaze_y = gx, gy
        app._tick_gaze_calibration(t)


# --------------------------------------------------------------------------- #
#  Траектория точки
# --------------------------------------------------------------------------- #
def test_pursuit_path_goes_over_whole_screen():
    duration = float(PURSUIT_DURATION_S)
    points = np.array([pursuit_point(i * duration / 400, duration) for i in range(400)])
    assert points[:, 0].min() < 0.06 and points[:, 0].max() > 0.94
    # каждая из пяти строк действительно посещается
    for row in PURSUIT_ROWS:
        expected = 0.045 + 0.91 * row
        assert np.min(np.abs(points[:, 1] - expected)) < 0.01


def test_pursuit_path_is_smooth_and_starts_immediately():
    x0, y0 = pursuit_point(0.0)
    x1, y1 = pursuit_point(1 / 30)
    # за один кадр точка не прыгает на пол-экрана: глаз успевает её вести
    assert math.hypot(x1 - x0, y1 - y0) < 0.05
    assert pursuit_point(0.0) == pytest.approx(pursuit_point(0.0))
    # монотонно по времени внутри строки
    a = pursuit_point(0.50)
    b = pursuit_point(0.55)
    assert (b[0] - a[0]) * (1 if a[1] < 0.5 else -1) > 0 or a[1] != b[1]


def test_pursuit_path_wraps_end_and_keeps_inside_screen():
    duration = float(PURSUIT_DURATION_S)
    for t in (duration - 0.01, duration, duration * 3):
        x, y = pursuit_point(t, duration)
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


# --------------------------------------------------------------------------- #
#  Динамика зрачка
# --------------------------------------------------------------------------- #
def test_metrics_find_latency_of_delayed_gaze():
    dt = 1 / 30
    duration = 6.0
    frames = int(duration / dt)
    dot = np.array([pursuit_point(i * dt, duration) for i in range(frames)])
    lag = 3
    samples = []
    for i in range(frames):
        src = dot[max(0, i - lag)]
        gx, gy = gaze_for(*src)
        samples.append((i * dt, gx, gy, dot[i][0], dot[i][1]))
    metrics = pursuit_metrics(samples)
    assert metrics["latency_ms"] == pytest.approx(lag * dt * 1000, abs=1.5 * dt * 1000)
    assert metrics["responsiveness"] > 0.5


def test_metrics_report_zero_when_gaze_does_not_move():
    samples = [(i / 30, 0.0, 0.0, 0.1 + i * 0.001, 0.5) for i in range(90)]
    metrics = pursuit_metrics(samples)
    assert metrics["responsiveness"] == pytest.approx(0.0, abs=0.2)
    assert metrics["frames"] == 90


def test_metrics_need_enough_frames():
    assert pursuit_metrics([])["frames"] == 0
    assert pursuit_metrics([(0.0, 0.0, 0.0, 0.0, 0.0)])["responsiveness"] == 0.0


# --------------------------------------------------------------------------- #
#  Подгонка по траектории
# --------------------------------------------------------------------------- #
def test_pursuit_points_fit_screen_accurately():
    calib = GazeCalibration()
    rng = np.random.default_rng(3)
    for i in range(360):
        sx, sy = pursuit_point(i * PURSUIT_DURATION_S / 360)
        gx, gy = gaze_for(sx, sy)
        calib.add(gx + rng.normal(0, 0.004), gy + rng.normal(0, 0.004), sx, sy)
    assert calib.fit()
    worst, mean = calib.error()
    assert mean < 0.01 and worst < 0.03
    px, py = calib.apply(*gaze_for(0.37, 0.62))
    assert px == pytest.approx(0.37, abs=0.02)
    assert py == pytest.approx(0.62, abs=0.02)


def test_pursuit_fit_survives_blinks():
    """Моргания и сдвиги головы дают выбросы — подгонка их отбрасывает."""
    rng = np.random.default_rng(11)
    points = []
    for i in range(400):
        sx, sy = pursuit_point(i * PURSUIT_DURATION_S / 400)
        gx, gy = gaze_for(sx, sy)
        gx += rng.normal(0, 0.003)
        gy += rng.normal(0, 0.003)
        if i % 11 == 0:                       # ~9% кадров — выбросы
            gx += rng.choice([-0.2, 0.2])
            gy += rng.choice([-0.12, 0.12])
        points.append((gx, gy, sx, sy))
    robust = GazeCalibration(points=list(points))
    assert robust.fit()
    _worst, mean = robust.error()
    naive = GazeCalibration(points=list(points))
    naive.fit(robust=False)
    _nworst, naive_mean = naive.error()
    assert mean < 0.02
    assert mean < naive_mean
    # выбросы действительно выкинуты, но основная масса проб осталась
    assert 150 < len(robust.points) < 400


def test_calibration_keeps_gaze_dynamics_after_save():
    calib = GazeCalibration()
    for sx, sy in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)):
        gx, gy = gaze_for(sx, sy)
        calib.add(gx, gy, sx, sy)
    calib.fit()
    calib.latency_ms = 93.0
    calib.responsiveness = 0.71
    calib.pursuit_frames = 390
    calib.face_scale = 0.0625
    restored = GazeCalibration.from_dict(calib.to_dict())
    assert restored.latency_ms == pytest.approx(93.0)
    assert restored.responsiveness == pytest.approx(0.71)
    assert restored.pursuit_frames == 390
    assert restored.face_scale == pytest.approx(0.0625)


# --------------------------------------------------------------------------- #
#  Мастер в приложении
# --------------------------------------------------------------------------- #
def test_wizard_pursuit_finishes_with_calibration_and_dynamics():
    app = _app()
    app.start_gaze_calibration()
    assert app._calib["phase"] == "pursuit"
    assert "красной точкой" in app.calibration_text()
    _drive(app, lag_frames=2)

    assert app.calibrating is False
    assert app.gaze_calib.ready
    assert len(app.gaze_calib.points) > 100
    assert app.gaze_calib.pursuit_frames > 300
    assert 0 < app.gaze_calib.latency_ms < 300
    assert app.cfg.face.gaze_calibration["pursuit_frames"] > 300
    assert app.cfg.face.gaze_absolute is True


def test_wizard_autotunes_smoothing_from_measurements():
    app = _app()
    app.start_gaze_calibration()
    _drive(app)
    alpha = app.cfg.face.gaze_cursor_alpha
    deadzone = app.cfg.face.gaze_deadzone_px
    assert 0.35 <= alpha <= 0.90
    assert 6 <= deadzone <= 30
    # курсор пересоздан с новыми настройками — иначе они не подействуют
    assert app.gaze_cursor.alpha == pytest.approx(alpha)
    assert app.gaze_cursor.deadzone_px == deadzone


def test_autotune_can_be_switched_off():
    app = _app(**{"face.gaze_autotune": False})
    before = (app.cfg.face.gaze_cursor_alpha, app.cfg.face.gaze_deadzone_px)
    app.start_gaze_calibration()
    _drive(app)
    assert app.gaze_calib.ready
    assert (app.cfg.face.gaze_cursor_alpha, app.cfg.face.gaze_deadzone_px) == before


def test_pursuit_can_be_stopped_with_space_but_not_instantly():
    app = _app()
    app.start_gaze_calibration()
    for i in range(5):                      # пять кадров — слишком мало
        _look(app, *pursuit_point(i / 30))
        app._tick_gaze_calibration(i / 30)
    assert "рано" in app.confirm_gaze_point()
    for i in range(5, 90):                  # три секунды — уже нормально
        _look(app, *pursuit_point(i / 30))
        app._tick_gaze_calibration(i / 30)
    app.confirm_gaze_point()
    assert app.calibrating is False
    assert app.gaze_calib.ready


# --------------------------------------------------------------------------- #
#  «Прочитайте, потом вертите головой» — фазы разнесены по времени
# --------------------------------------------------------------------------- #
def test_head_phase_waits_for_reading():
    app = _app(**{"face.gaze_head_check_s": 6.0})
    app.start_gaze_calibration()
    _drive(app)                             # точка дошла до конца траектории
    assert app._calib["phase"] == "head_intro"
    assert "прочитали" in app.calibration_text().lower()
    # в фазе чтения ничего не снимаем: головой ещё никто не вертит
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = 0.0, 0.0
    app.face_fsm.head_yaw, app.face_fsm.head_pitch = 0.0, 0.0
    app._tick_gaze_calibration(14.0)
    assert app._calib["head"] == []
    # подсказка не «сгорает»: без пробела фаза держится заметное время
    assert float(app.cfg.face.gaze_head_intro_s) >= 5.0
    app._tick_gaze_calibration(14.0 + float(app.cfg.face.gaze_head_intro_s) + 0.1)
    assert app._calib["phase"] == "head_count"
    # отсчёт 3…2…1 — и только теперь просим вертеть головой
    t = float(app._calib["phase_since"]) + float(app.cfg.face.gaze_head_count_s) + 0.1
    app._tick_gaze_calibration(t)
    assert app._calib["phase"] == "head"
    assert "голов" in app.calibration_text().lower()


def test_space_skips_reading_immediately():
    app = _app(**{"face.gaze_head_check_s": 6.0})
    app.start_gaze_calibration()
    _drive(app)
    assert app._calib["phase"] == "head_intro"
    app.confirm_gaze_point()
    assert app._calib["phase"] == "head_count"


def test_calibration_does_not_start_without_face():
    app = _app()
    app.face_fsm.gaze_valid = False
    app.start_gaze_calibration()
    _drive(app, valid=False)
    # зрачков не видно — проб нет, калибровка честно говорит «не удалась»
    assert app.calibrating is False
    assert not app.gaze_calib.ready
    assert "не удалась" in app._events_log[0]


# --------------------------------------------------------------------------- #
#  Перекалибровка, когда лицо уехало (как у Apple)
# --------------------------------------------------------------------------- #
def test_face_drift_asks_for_recalibration():
    app = _app()
    app.start_gaze_calibration()
    _drive(app)
    app.gaze_calib.face_scale = 0.065
    app._metrics = SimpleNamespace(interocular=0.065 * 1.05)
    app._note_gaze_drift(100.0)
    assert not any("сместились" in line for line in app._events_log)
    app._metrics = SimpleNamespace(interocular=0.065 * 1.4)
    app._note_gaze_drift(200.0)
    assert any("сместились" in line for line in app._events_log)
    # второй раз молчим в течение паузы
    app._events_log.clear()
    app._note_gaze_drift(201.0)
    assert not any("сместились" in line for line in app._events_log)


def test_old_points_mode_still_works():
    app = _app(**{"face.gaze_calib_mode": "points"})
    app.start_gaze_calibration()
    assert app._calib["phase"] == "points"
    from airmouse.gaze import CALIBRATION_TARGETS
    for sx, sy in CALIBRATION_TARGETS:
        _look(app, sx, sy)
        for _ in range(4):
            app._collect_gaze_sample()
        app.confirm_gaze_point()
    assert app.calibrating is False
    assert app.gaze_calib.ready
