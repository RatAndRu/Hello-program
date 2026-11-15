"""Взаимная подсказка «тело ↔ голова» и спорт по скелету.

Проверяем то, что видит человек: лицо не исчезает бесследно, скелет не
остаётся без головы, а сгибания рук, T-поза и бокс считаются без ложных
срабатываний.
"""

import numpy as np
import pytest

from airmouse.anchor import (
    FaceBodyAnchor,
    face_box,
    head_box_from_body,
    head_points_from_face,
    patch_head,
)
from airmouse.body import (
    B,
    BodySport,
    BodySmoother,
    measure_body,
    synthetic_body,
)
from airmouse.synthetic import synthetic_face


def _face(x: float = 0.5, y: float = 0.35):
    return synthetic_face(center=(x, y), scale=0.6)


def _body(**kw):
    return synthetic_body(center=(0.5, 0.55), height=0.8, **kw)


# --------------------------------------------------------------------------- #
#  Тело знает, где голова
# --------------------------------------------------------------------------- #
def test_face_box_is_measured_from_the_face():
    box = face_box(_face())
    assert box is not None
    x0, y0, x1, y1 = box
    assert 0.0 < x0 < x1 < 1.0 and 0.0 < y0 < y1 < 1.0


def test_head_box_from_body_needs_three_points():
    body = _body()
    assert head_box_from_body(body) is not None
    for index in (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR, B.MOUTH_L, B.MOUTH_R)[:-2]:
        body[index, 3] = 0.0
    assert head_box_from_body(body) is None, "по одной-двум точкам голову не построить"


def test_face_lost_is_recovered_from_the_body():
    anchor = FaceBodyAnchor()
    assert anchor.update(_face(), _body(), 0.0).source == "face"
    lost = anchor.update(None, _body(), 0.033)
    assert lost.ok and lost.source == "body" and lost.predicted
    assert "по телу" in lost.note()


def test_face_lost_without_body_is_predicted_for_a_while():
    anchor = FaceBodyAnchor(predict_frames=4)
    anchor.update(_face(0.4), None, 0.0)
    moved = anchor.update(_face(0.5), None, 0.1)
    assert moved.source == "face"
    gone = anchor.update(None, None, 0.2)
    assert gone.ok and gone.source == "track"
    assert float(gone.center[0]) > 0.5, "голова продолжила движение вправо"
    for i in range(3, 12):
        anchor.update(None, None, 0.2 + i * 0.033)
    assert not anchor.update(None, None, 0.6).ok, "надолго — честно не вижу"


# --------------------------------------------------------------------------- #
#  Лицо знает, где голова скелета
# --------------------------------------------------------------------------- #
def test_head_points_from_face_land_on_the_head():
    pts = head_points_from_face(_face(0.5, 0.3))
    assert set(pts) == {B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR,
                        B.MOUTH_L, B.MOUTH_R}
    assert abs(float(pts[B.NOSE][1]) - 0.3) < 0.15
    assert float(pts[B.L_EYE][0]) < float(pts[B.R_EYE][0])


def test_missing_head_of_the_skeleton_is_filled_from_the_face():
    body = _body()
    for index in (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR, B.MOUTH_L, B.MOUTH_R):
        body[index, 3] = 0.0
    assert measure_body(body).head_ok is False
    patched = patch_head(body, _face())
    assert patched is not None
    assert measure_body(patched).head_ok is True
    assert patched is not body, "возвращается копия, массив трекера не трогаем"
    assert patched[B.NOSE, 3] > 0.5


def test_patch_head_keeps_measured_points():
    body = _body()
    before = body[B.NOSE, :2].copy()
    patched = patch_head(body, _face())
    assert np.allclose(patched[B.NOSE, :2], before), "видимые точки не перетираются"
    assert patched is body, "нечего править — отдаём тот же массив"


def test_held_skeleton_follows_the_face():
    smoother = BodySmoother(confirm_frames=1, hold_frames=4)
    for i in range(2):
        smoother.update(_body(), i * 0.1)
    held = smoother.update(None, 0.2, face_center=(0.9, 0.55))
    assert held is not None
    assert float(held[B.NOSE, 0]) > 0.6, "скелет сдвинулся вместе с головой"
    assert smoother.active is True and smoother.held == 1


# --------------------------------------------------------------------------- #
#  Любая видимая часть тела — уже тело
# --------------------------------------------------------------------------- #
def test_head_and_arms_without_hips_are_measured():
    body = _body()
    for index in (B.L_HIP, B.R_HIP, B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE,
                  B.L_HEEL, B.R_HEEL, B.L_FOOT, B.R_FOOT):
        body[index, 3] = 0.0
    metrics = measure_body(body)
    assert metrics.visible is True
    assert metrics.torso_ok is False and metrics.upper_ok is True
    assert metrics.arms_ok is True and metrics.head_ok is True
    assert metrics.where == "видно голову и руки"
    assert "голова" in metrics.parts and "руки" in metrics.parts


def test_shoulders_without_arms_are_waist_up_only():
    body = _body()
    for index in (B.L_HIP, B.R_HIP, B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE,
                  B.L_ELBOW, B.R_ELBOW, B.L_WRIST, B.R_WRIST):
        body[index, 3] = 0.0
    metrics = measure_body(body)
    assert metrics.visible is True
    assert metrics.where == "видно по грудь"
    assert metrics.arms_ok is False


def test_no_shoulders_means_no_body():
    body = _body()
    body[B.L_SHOULDER, 3] = 0.0
    assert measure_body(body).visible is False


# --------------------------------------------------------------------------- #
#  Сгибания рук
# --------------------------------------------------------------------------- #
def _feed(sport, poses, dt=0.4):
    events, t = [], 0.0
    for pose in poses:
        body = synthetic_body(arms=pose)
        t += dt
        events += sport.update(body, measure_body(body), t)
    return events


def test_curl_rep_is_counted_once():
    sport = BodySport()
    events = _feed(sport, ["curl_down", "curl", "curl_down"])
    assert sport.curls == 1
    assert [e.kind for e in events].count("curl_rep") == 1
    assert "сгибания рук 1" in sport.text


def test_fast_wiggle_is_not_a_curl():
    sport = BodySport()
    _feed(sport, ["curl_down", "curl", "curl_down", "curl"], dt=0.05)
    assert sport.curls == 0, "дребезг короче curl_min_s не считается повтором"


def test_curl_needs_the_wrist_above_the_elbow():
    """Мах рукой внизу — не сгибание: запястье должно идти к плечу."""
    sport = BodySport()
    body = synthetic_body(arms="curl_down")
    metrics = measure_body(body)
    for i in range(6):
        sport.update(body, metrics, i * 0.4)
    assert sport.curls == 0


# --------------------------------------------------------------------------- #
#  T-поза
# --------------------------------------------------------------------------- #
def test_tpose_needs_both_arms_and_a_hold():
    sport = BodySport()
    events = _feed(sport, ["tpose"], dt=0.1)
    assert sport.tpose is True
    assert not any(e.kind == "tpose_hold" for e in events), "одного кадра мало"
    events = _feed(sport, ["tpose"] * 5, dt=0.1)
    assert any(e.kind == "tpose_hold" for e in events)
    assert "T-поза" in sport.text


def test_one_arm_out_is_not_a_tpose():
    sport = BodySport()
    _feed(sport, ["tpose"] * 6, dt=0.1)
    body = synthetic_body(arms="tpose")
    body[B.R_WRIST, 1] = body[B.R_SHOULDER, 1] + 0.4 * measure_body(body).scale
    sport.update(body, measure_body(body), 1.0)
    assert sport.tpose is False


# --------------------------------------------------------------------------- #
#  Бокс: стойка и удары
# --------------------------------------------------------------------------- #
def test_guard_needs_both_fists_up():
    sport = BodySport()
    _feed(sport, ["guard"] * 3, dt=0.2)
    assert sport.guard is True
    assert "стойка" in sport.text


def test_punch_is_counted_from_the_guard():
    sport = BodySport()
    events = _feed(sport, ["guard"] * 3, dt=0.1)
    events += _feed(sport, ["punch_right"], dt=0.1)
    assert sport.punches == 1
    assert any(e.kind == "punch" for e in events)
    assert "ударов 1" in sport.text


def test_punch_is_not_counted_twice_in_a_row():
    sport = BodySport()
    _feed(sport, ["guard"] * 3, dt=0.1)
    _feed(sport, ["punch_right"], dt=0.1)
    _feed(sport, ["punch_right"], dt=0.1)
    assert sport.punches == 1, "пока рука не вернулась в стойку — это один удар"


def test_sport_can_be_switched_off():
    from airmouse.config import BodyConfig

    cfg = BodyConfig()
    cfg.sport = False
    sport = BodySport(cfg)
    _feed(sport, ["curl_down", "curl", "curl_down"])
    assert sport.curls == 0 and sport.text == ""


# --------------------------------------------------------------------------- #
#  Конвейер приложения: подсказки доходят до окна
# --------------------------------------------------------------------------- #
class _BodyTracker:
    """Отдаёт кадры тела и (необязательно) лица — вместо камеры."""

    name = "fake"

    def __init__(self, body_frames, faces):
        self.body_frames = list(body_frames)
        self.faces = list(faces)
        self.i = 0

    def process(self, frame, ts_ms):
        from airmouse.tracker import FrameResult

        body = self.body_frames[min(self.i, len(self.body_frames) - 1)]
        face = self.faces[min(self.i, len(self.faces) - 1)]
        self.i += 1
        return FrameResult(hands=[], face=face, body=body, backend="fake")

    def close(self):
        pass


def _pipeline(frames_body, faces, **overrides):
    from airmouse.app import AirMouseApp
    from airmouse.config import AppConfig

    cfg = AppConfig()
    cfg.body.enabled = True
    cfg.body.every_n_frames = 1        # без прореживания: каждый кадр — поза
    for key, value in overrides.items():
        setattr(cfg.body, key, value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = _BodyTracker(frames_body, faces)
    app._prepared = True
    app._frame_size = (960, 540)
    return app


def test_app_draws_head_hint_when_face_is_lost():
    app = _pipeline([_body()], [None])
    for i in range(6):
        app.process_frame(np.zeros((540, 960, 3), dtype=np.uint8), i * 0.1, i * 100)
    app._update_state([], 30.0)
    assert app.state.face_seen is False
    assert app.state.face_hint is not None, "голова найдена по телу"
    assert "по телу" in app.state.face_hint_note


def test_app_fills_its_skeleton_head_from_the_face():
    body = _body()
    for index in (B.NOSE, B.L_EYE, B.R_EYE, B.L_EAR, B.R_EAR, B.MOUTH_L, B.MOUTH_R):
        body[index, 3] = 0.0
    app = _pipeline([body], [_face()])
    for i in range(5):
        app.process_frame(np.zeros((540, 960, 3), dtype=np.uint8), i * 0.1, i * 100)
    assert app._body_points is not None
    assert float(app._body_points[B.NOSE, 3]) > 0.5, "голова скелета достроена по лицу"


def test_app_reports_sport_in_the_window_state():
    frames = ([_body(arms="curl_down")] * 2 + [_body(arms="curl")] * 2
              + [_body(arms="curl_down")] * 2)
    app = _pipeline(frames, [None] * len(frames))
    for i in range(len(frames)):
        app.process_frame(np.zeros((540, 960, 3), dtype=np.uint8), i * 0.3, int(i * 300))
    app._update_state([], 30.0)
    assert app.sport.curls == 1
    assert "сгибания рук" in app.state.sport_text
