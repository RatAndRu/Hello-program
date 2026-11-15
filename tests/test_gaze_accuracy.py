"""Точность «мыши глазами»: верх-низ не путается, моргание не сдвигает взгляд.

Пользователь жаловался, что направления определяются неверно: «даже не всегда
правильно понимает, когда нужно вниз, а когда вверх». Причины, которые здесь
закрыты:

* вертикаль считалась по подвижным векам — при моргании и прищуривании центр
  глазницы уезжал, и взгляд «прыгал» вверх-вниз;
* кадр с морганием всё равно давал координаты зрачка (радужка видна частично);
* подпись направления строилась по «сырому» зрачку, а курсор ехал по
  калиброванной карте — они расходились;
* если пропадал один глаз, управление замирало целиком.
"""

import numpy as np
import pytest

from airmouse.landmarks import F
from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.face import EYE_ASPECT, FaceFSM, _eye_box, measure_face, measure_gaze
from airmouse.gaze import CALIBRATION_TARGETS, GazeCalibration
from airmouse.synthetic import synthetic_face


def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for dotted, value in overrides.items():
        section, _, name = dotted.partition(".")
        setattr(getattr(cfg, section), name, value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    app.face_fsm.gaze_valid = True
    return app


def _squint(face, factor: float = 0.4) -> None:
    """Прищурить веки, не трогая зрачок: точки век едут к линии уголков."""
    for group in (F.EYE_A, F.EYE_B):
        cy = (face.xy(group[0])[1] + face.xy(group[3])[1]) / 2.0
        for idx in group[1:3] + group[4:6]:
            x, y = face.xy(idx)[:2]
            face.points[idx, 1] = cy + (y - cy) * factor


# --------------------------------------------------------------------------- #
#  Вертикаль не зависит от век
# --------------------------------------------------------------------------- #
def test_vertical_gaze_ignores_eyelid_movement():
    face = synthetic_face(gaze=(0.0, 0.6))
    dx0, dy0, ok0 = measure_gaze(face)
    assert ok0 and dy0 > 0.2, (dx0, dy0)      # +dy — вниз

    _squint(face, 0.35)                        # прищурился — зрачок на месте
    dx1, dy1, ok1 = measure_gaze(face)
    assert ok1
    assert dy1 == pytest.approx(dy0, abs=1e-6), (dy0, dy1)
    assert dx1 == pytest.approx(dx0, abs=1e-6)


def test_eye_box_height_is_a_fraction_of_the_width():
    face = synthetic_face(ear=(0.30, 0.30))
    cx, cy, half_w, half_h = _eye_box(face, F.EYE_A)
    assert half_h == pytest.approx(half_w * EYE_ASPECT)
    # центр по вертикали — линия уголков, а не середина век
    assert cy == pytest.approx((face.xy(F.EYE_A[0])[1] + face.xy(F.EYE_A[3])[1]) / 2.0)


def test_up_and_down_have_opposite_signs():
    up = measure_gaze(synthetic_face(gaze=(0.0, -0.7)))
    down = measure_gaze(synthetic_face(gaze=(0.0, 0.7)))
    left = measure_gaze(synthetic_face(gaze=(-0.7, 0.0)))
    right = measure_gaze(synthetic_face(gaze=(0.7, 0.0)))
    for (dx, dy, ok) in (up, down, left, right):
        assert ok
    assert up[1] < -0.2 and down[1] > 0.2
    assert left[0] < -0.3 and right[0] > 0.3


# --------------------------------------------------------------------------- #
#  Битые кадры отбрасываются, а не «перекашивают» взгляд
# --------------------------------------------------------------------------- #
def test_blink_does_not_report_gaze():
    m = measure_face(synthetic_face(ear=(0.08, 0.08), gaze=(0.0, 0.9)))
    assert m.gaze_valid is False


def test_eyes_must_agree():
    face = synthetic_face(gaze=(0.0, 0.0))
    assert measure_gaze(face)[2] is True
    # правый глаз «уехал» — веко прикрыло половину радужки
    for idx in F.IRIS_B:
        face.points[idx, 0] += 0.04
    assert measure_gaze(face)[2] is False


def test_one_visible_eye_is_enough():
    face = synthetic_face(gaze=(0.5, 0.0))
    original = face.iris_center
    face.iris_center = lambda group: None if group is F.IRIS_B else original(group)
    dx, dy, ok = measure_gaze(face)
    assert ok and dx > 0.3


def test_wild_iris_position_is_a_bad_frame():
    face = synthetic_face(gaze=(0.0, 0.0))
    for group in (F.IRIS_A, F.IRIS_B):
        for idx in group:
            face.points[idx, 0] += 0.3
    assert measure_gaze(face)[2] is False


# --------------------------------------------------------------------------- #
#  Фильтр: дрожание меньше, быстрый перевод — по-прежнему быстрый
# --------------------------------------------------------------------------- #
def _run(fsm: FaceFSM, gazes, times_out: list) -> None:
    """Прогнать кадры через FaceFSM и собрать сглаженный выход."""
    t = 0.0
    for value in gazes:
        t += 1 / 30
        fsm.update(measure_face(synthetic_face(gaze=(value, 0.0))), t)
        times_out.append(float(fsm.gaze_x))


def test_one_euro_damps_jitter():
    fsm = _app().face_fsm
    jitter = [0.30 if i % 2 else 0.24 for i in range(60)]
    out: list = []
    _run(fsm, jitter, out)
    raw = [measure_gaze(synthetic_face(gaze=(v, 0.0)))[0] for v in jitter]
    # размах «звена» на выходе фильтра заметно меньше, чем на входе
    assert np.std(out[-20:]) < np.std(raw[-20:]) * 0.6


def test_saccade_passes_through_quickly():
    app = _app()
    fsm = app.face_fsm
    t = 0.0
    for _ in range(10):                 # смотрим прямо
        t += 1 / 30
        fsm.update(measure_face(synthetic_face(gaze=(0.0, 0.0))), t)
    for _ in range(4):                  # перевели взгляд вправо
        t += 1 / 30
        fsm.update(measure_face(synthetic_face(gaze=(0.6, 0.0))), t)
    target = measure_gaze(synthetic_face(gaze=(0.6, 0.0)))[0]
    assert fsm.gaze_x > target * 0.6, (fsm.gaze_x, target)


# --------------------------------------------------------------------------- #
#  Слово о направлении совпадает с тем, куда едет курсор
# --------------------------------------------------------------------------- #
def _calibrated() -> GazeCalibration:
    def gaze_for(sx: float, sy: float):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    calib = GazeCalibration(feature="head2")
    for sx, sy in CALIBRATION_TARGETS:
        calib.add(*gaze_for(sx, sy), sx, sy)
    assert calib.fit()
    return calib


@pytest.mark.parametrize("sx,sy,word", [
    (0.5, 0.92, "вниз"),
    (0.5, 0.08, "вверх"),
    (0.92, 0.5, "вправо"),
    (0.08, 0.5, "влево"),
    (0.5, 0.5, "прямо"),
])
def test_direction_words_follow_calibrated_cursor(sx, sy, word):
    app = _app()
    app.gaze_calib = _calibrated()
    gx, gy = ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)
    app.face_fsm.gaze_u, app.face_fsm.gaze_v = gx, gy
    app.face_fsm.gaze_x, app.face_fsm.gaze_y = gx, gy
    where, point = app.gaze_direction()
    assert where == word
    assert point is not None
    # точка экрана — в той же половине, что и слово
    if word == "вниз":
        assert point[1] > 0.6
    if word == "вверх":
        assert point[1] < 0.4
    if word == "вправо":
        assert point[0] > 0.6
    if word == "влево":
        assert point[0] < 0.4


def test_direction_words_without_calibration():
    app = _app()
    app.gaze_calib = GazeCalibration()
    scale_y = app.cfg.face.gaze_full_scale_y
    for gy, word in ((2.0 * scale_y, "вниз"), (-2.0 * scale_y, "вверх")):
        app.face_fsm.gaze_y = app.face_fsm.baseline.gaze_y + gy
        app.face_fsm.gaze_x = app.face_fsm.baseline.gaze_x
        assert app.gaze_direction()[0] == word
    assert app.gaze_direction()[1] is None       # без калибровки точки нет


def test_gaze_text_reports_error_and_jitter():
    app = _app()
    app.gaze_calib = _calibrated()
    app._gaze_error_cache = app.gaze_calib.error()
    for i in range(12):
        app._gaze_track.append((0.5 + i * 0.001, 0.4))
    quality = app.gaze_quality()
    assert "ошибка" in quality and "дрожание" in quality
    # и это всё видно человеку в строке про взгляд
    text = app.gaze_text()
    assert "дрожание" in text
