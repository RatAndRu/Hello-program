"""Тонкости управления: что говорят исследования и как это сделано у нас.

Три вещи, которые в литературе называют главными источниками «бесящих
моментов» в бесконтактном управлении:

* **Midas touch** — любое движение (глаз, головы) что-то нажимает. Лечится
  паузой удержания и видимым прогрессом (dwell 400–800 мс, 600 — удобнее;
  Majaranta et al.; usability study, Displays 2021).
* **Переходные движения** — рука влетает в кадр, пальцы ещё складываются,
  нейросеть видит «щипок» и «ладонь» по очереди. Лечится «затишьем» на входе.
* **Линейный gain головы** — на мелких целях промахи, на больших расстояниях
  «вяло». Лечится нелинейной передачей (HeadShift, CHI 2024).
"""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.body import synthetic_body
from airmouse.config import AppConfig, FaceConfig, HandConfig
from airmouse.face import FaceFSM
from airmouse.gaze import GazeDwell
from airmouse.gestures import HandFSM, synthetic_hand


# --------------------------------------------------------------------------- #
#  Мышь головой: нелинейная передача (HeadShift)
# --------------------------------------------------------------------------- #
def _head_px(angle: float, dt: float = 0.1) -> float:
    fsm = FaceFSM(FaceConfig())
    fsm.rel_yaw = angle
    fsm.rel_pitch = 0.0
    return fsm.head_step(dt)[0]


def test_head_inside_deadzone_does_not_move():
    assert _head_px(0.0) == 0.0
    assert _head_px(1.0) == 0.0            # меньше мёртвой зоны (2.5°)


def test_head_gain_grows_with_angle():
    small = _head_px(6.0)
    big = _head_px(20.0)
    assert small > 0.0 and big > small
    # нелинейность: 20° дают больше, чем 20/6 ≈ 3.3 раза от 6°
    assert big > (20.0 / 6.0) * small


def test_head_returns_to_neutral_smoothly():
    fsm = FaceFSM(FaceConfig())
    fsm.rel_yaw = 12.0
    first = fsm.head_step(0.1)[0]
    fsm.rel_yaw = 0.0
    assert fsm.head_step(0.1)[0] == 0.0
    assert first > 0.0


# --------------------------------------------------------------------------- #
#  Клик удержанием взгляда
# --------------------------------------------------------------------------- #
def test_gaze_dwell_fires_after_hold():
    dwell = GazeDwell(dwell_s=0.6, radius_px=60)
    fired_at = None
    for i in range(20):
        t = i * 0.05
        progress, fired = dwell.update(500, 400, t)
        if fired:
            fired_at = t
            break
    assert fired_at is not None
    assert 0.55 <= fired_at <= 0.85       # ~600 мс, а не «мгновенно»
    assert progress == 0.0                # после клика прогресс начинается заново


def test_gaze_dwell_resets_when_gaze_moves():
    dwell = GazeDwell(dwell_s=0.6, radius_px=60)
    for i in range(8):
        dwell.update(500, 400, i * 0.05)
    assert dwell.progress > 0.5
    _p, fired = dwell.update(900, 400, 0.45)      # посмотрел в сторону
    assert not fired
    assert dwell.progress == 0.0


def test_gaze_dwell_cooldown_prevents_machine_gun():
    dwell = GazeDwell(dwell_s=0.2, radius_px=60, cooldown_s=1.0)
    fires = 0
    for i in range(40):                   # 2 секунды непрерывного взгляда
        _p, fired = dwell.update(500, 400, i * 0.05)
        fires += int(fired)
    assert fires == 2                     # 0.2 с + пауза 1 с, а не 10 кликов


def test_gaze_dwell_ignored_when_invalid():
    dwell = GazeDwell(dwell_s=0.2)
    for i in range(10):
        dwell.update(500, 400, i * 0.05)
    assert dwell.update(500, 400, 1.0, valid=False) == (0.0, False)


# --------------------------------------------------------------------------- #
#  «Затишье на входе»: рука влетела в кадр — команд нет
# --------------------------------------------------------------------------- #
def _feed(fsm: HandFSM, hand, frames: int, start: float, dt: float = 0.05):
    events = []
    now = start
    for _ in range(frames):
        now += dt
        events.extend(fsm.update(hand, now))
    return events, now


def test_no_clicks_right_after_hand_returns():
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    others = {"middle": 1, "ring": 1, "pinky": 1}
    open_hand = synthetic_hand(curl=others)
    pinch = synthetic_hand(curl=others, pinch_index=True)

    _feed(fsm, open_hand, 10, 0.0)         # рука была в кадре
    fsm.update(None, 0.6)                  # детектор её потерял
    # вернулась — и сразу «щипок»: это переходное движение, не клик
    events, now = _feed(fsm, pinch, 4, 0.65)
    assert not [e for e in events if e.kind == "pinch_release"]

    # а после затишья обычный щипок снова даёт клик
    events2, now = _feed(fsm, open_hand, 14, now)
    events3, now = _feed(fsm, pinch, 5, now)
    events4, _ = _feed(fsm, open_hand, 6, now)
    clicks = [e for e in events3 + events4 if e.kind == "pinch_release"]
    assert len(clicks) == 1
    assert not [e for e in events3 + events4 if e.kind == "drag_start"]


def test_settle_gate_does_not_delay_first_use():
    """Первый показ руки не тормозим — за это отвечает разминка при запуске."""
    fsm = HandFSM(HandConfig())
    others = {"middle": 1, "ring": 1, "pinky": 1}
    events, now = _feed(fsm, synthetic_hand(curl=others), 6, 0.0)
    events2, _ = _feed(fsm, synthetic_hand(curl=others, pinch_index=True), 6, now)
    events3, _ = _feed(fsm, synthetic_hand(curl=others), 6, now + 0.3)
    assert [e for e in events2 + events3 if e.kind == "pinch_release"]


# --------------------------------------------------------------------------- #
#  Тело в приложении
# --------------------------------------------------------------------------- #
def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for key, value in overrides.items():
        node = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    return app


def _press(app: AirMouseApp, squat: float, frames: int = 20, start: float = 0.0) -> float:
    body = synthetic_body(squat=squat)
    t = start
    for _ in range(frames):
        app._handle_body(body, t)
        t += 1 / 30.0
    return t


def test_app_counts_squats_and_shows_text():
    app = _app(**{"body.enabled": True, "body.every_n_frames": 1})
    t = _press(app, 0.0)
    t = _press(app, 0.9, start=t)
    t = _press(app, 0.0, start=t)
    assert app.body_fsm.reps == 1
    assert "приседаний 1" in app.body_fsm.text
    assert any("приседание №1" in line for line in app._events_log)


def test_body_action_only_when_mapped():
    app = _app(**{"body.enabled": True, "body.every_n_frames": 1})
    body = synthetic_body(squat=0.9)
    for i in range(20):
        assert app._handle_body(body, i / 30.0) == []      # не привязано — молчим
    app.cfg.actions.mapping["squat_rep"] = "toggle_pause"
    events = []
    for i in range(20, 40):
        events += app._handle_body(body, i / 30.0)
    assert not [e for e in events if e.kind == "squat_rep"]  # ещё «приседаем»
    for i in range(40, 60):
        events += app._handle_body(synthetic_body(squat=0.0), i / 30.0)
    assert [e for e in events if e.kind == "squat_rep"]


def test_body_disabled_by_default():
    app = _app()
    assert app.cfg.body.enabled is False
    assert app._handle_body(synthetic_body(squat=0.9), 0.0) == []
