"""Тело в окне: «скелет» поверх человека, кадр «по пояс» и настройки режима.

Раньше режим тела только писал строку в панель — никакой картинки поверх
человека не было, и понять, что тело вообще распознаётся, было нельзя. Здесь
проверяется, что скелет рисуется, что при кадре «по пояс» он рисуется без ног,
и что настройки тела доступны ползунками (страница «Тело»).
"""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.body import B, BodyFSM, measure_body, synthetic_body
from airmouse.config import AppConfig, BodyConfig
from airmouse.overlay import OverlayState, draw_body_ar, render
from airmouse.settings_ui import PAGE_BODY, SettingsPanel

BG = np.full((540, 960, 3), 18, dtype=np.uint8)


def _app(**overrides) -> AirMouseApp:
    cfg = AppConfig()
    for path, value in overrides.items():
        node = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    return app


def _without_legs(body: np.ndarray) -> np.ndarray:
    out = np.array(body, dtype=np.float64)
    for index in (B.L_KNEE, B.R_KNEE, B.L_ANKLE, B.R_ANKLE,
                  B.L_HEEL, B.R_HEEL, B.L_FOOT, B.R_FOOT):
        out[index, 3] = 0.0
    return out


# --------------------------------------------------------------------------- #
#  Скелет
# --------------------------------------------------------------------------- #
def test_body_skeleton_is_drawn_over_person():
    only_hand_free = BG.copy()
    assert draw_body_ar(only_hand_free, synthetic_body()) > 15
    assert int(np.abs(only_hand_free.astype(int) - BG.astype(int)).sum()) > 0


def test_body_skeleton_skips_invisible_parts():
    """«По пояс» — рисуется без ног, а не с пустыми линиями в угол кадра."""
    full = BG.copy()
    waist = BG.copy()
    drawn_full = draw_body_ar(full, synthetic_body())
    drawn_waist = draw_body_ar(waist, _without_legs(synthetic_body()))
    assert drawn_waist < drawn_full
    # ниже пояса на картинке ничего не появилось
    hips_y = int(float(synthetic_body()[B.L_HIP, 1]) * (waist.shape[0] - 1))
    below = waist[hips_y + 30:, :, :]
    assert int(below.sum()) - int(BG[hips_y + 30:, :, :].sum()) == pytest.approx(0, abs=20000)


def test_body_skeleton_is_drawn_by_render():
    state = OverlayState(body_enabled=True, body_text="тело: стоит · приседаний 0")
    img = render(BG.copy(), state, hands=[], face=None, body=synthetic_body())
    assert int(np.abs(img.astype(int) - BG.astype(int)).sum()) > 0


def test_body_skeleton_can_be_hidden():
    state = OverlayState(body_enabled=True)
    without = render(BG.copy(), state, hands=[], face=None, body=None)
    with_body = render(BG.copy(), state, hands=[], face=None, body=synthetic_body())
    assert np.array_equal(without, render(BG.copy(), state, hands=[], face=None))
    assert not np.array_equal(without, with_body)


def test_body_drawing_survives_broken_points():
    assert draw_body_ar(BG.copy(), np.zeros((10, 4))) == 0
    assert draw_body_ar(BG.copy(), None) == 0


# --------------------------------------------------------------------------- #
#  Кадр «по пояс»
# --------------------------------------------------------------------------- #
def test_waist_up_body_is_measured_partially():
    metrics = measure_body(_without_legs(synthetic_body()))
    assert metrics.visible is True
    assert metrics.partial is True
    assert metrics.legs_ok is False
    assert metrics.depth == 0.0
    assert metrics.where == "видно по пояс"


def test_waist_up_body_does_not_count_squats_but_still_reads_lean():
    cfg = BodyConfig()
    fsm = BodyFSM(cfg)
    body = _without_legs(synthetic_body(squat=0.9))
    t = 0.0
    for _ in range(60):
        fsm.update(measure_body(body), t)
        t += 1 / 30
    assert fsm.reps == 0                       # глубины нет — и счёта нет
    assert "по пояс" in fsm.text

    lean_fsm = BodyFSM(cfg)
    lean_body = _without_legs(synthetic_body(lean=40))
    for _ in range(10):
        lean_fsm.update(measure_body(lean_body), t)
        t += 1 / 30
    assert lean_fsm.posture == "lean"
    assert lean_fsm.metrics.lean > cfg.lean_deg


def test_waist_up_body_also_counts_arms_up():
    fsm = BodyFSM(BodyConfig())
    body = _without_legs(synthetic_body(arms_up=1.0))
    events = []
    t = 0.0
    for _ in range(60):
        events.extend(fsm.update(measure_body(body), t))
        t += 1 / 30
    assert any(e.kind == "arms_up_hold" for e in events)


def test_body_without_legs_never_fires_body_actions_in_app():
    app = _app(**{"body.enabled": True, "body.every_n_frames": 1})
    app.cfg.actions.mapping["squat_rep"] = "toggle_pause"
    body = _without_legs(synthetic_body(squat=0.9))
    events = []
    for i in range(40):
        events.extend(app._handle_body(body, i / 30.0))
    assert events == []
    assert app.body_fsm.reps == 0
    assert "по пояс" in app.body_fsm.text


# --------------------------------------------------------------------------- #
#  Режим и настройки
# --------------------------------------------------------------------------- #
def test_state_says_body_is_off_by_default():
    app = _app()
    app._update_state([], 30.0)
    assert app.state.body_enabled is False
    assert "выключено" in app.state.body_text
    assert "T" in app.state.body_text


def test_set_body_off_clears_state():
    app = _app(**{"body.enabled": True})
    app._body_points = synthetic_body()
    text = app.set_body(False)
    assert "выключено" in text
    assert app._body_points is None
    app._update_state([], 30.0)
    assert app.state.body_enabled is False


def test_settings_have_body_page_with_sliders():
    panel = SettingsPanel(AppConfig())
    page = panel.pages[PAGE_BODY]
    assert page.title == "Тело"
    keys = {s.key for s in page.sliders}
    assert {"body.min_visibility", "body.squat_down", "body.squat_up",
            "body.squat_min_s", "body.lean_deg", "body.arms_up_hold_s",
            "body.every_n_frames"} <= keys
    cfg = AppConfig()
    slider = next(s for s in page.sliders if s.key == "body.squat_down")
    slider.set(cfg, 0.60)
    assert cfg.body.squat_down == pytest.approx(0.60)
    assert slider.text(cfg.body.squat_down) == "0.60"


def test_body_toggle_exists_and_flips_config():
    panel = SettingsPanel(AppConfig())
    toggle = next(t for t in panel.toggle_items if t.key == "mode.body")
    cfg = AppConfig()
    assert toggle.state(cfg) is False
    toggle.flip(cfg)
    assert cfg.body.enabled is True


def test_reconcile_body_switches_mode_when_slider_moves():
    """Ползунок в окне настроек переключает режим — без перезапуска."""
    app = _app()
    app._body_want = False
    calls = []
    app.set_body = lambda on, note=True: calls.append(bool(on)) or "ok"
    app.cfg.body.enabled = True
    app._reconcile_body()
    assert calls == [True]


def test_body_page_sliders_are_not_on_other_pages():
    panel = SettingsPanel(AppConfig())
    for index, page in enumerate(panel.pages):
        if index == PAGE_BODY:
            continue
        assert all(not s.key.startswith("body.") for s in page.sliders)
