"""Профиль движений: личный размах рук, мимики и тела вместо общих порогов.

Для взгляда калибровка нужна по существу (зрачок сам по себе не говорит, куда
смотрит человек). Для жестов и мимики — нет: признаки уже нормированы на размер
ладони и лица. Зато размах у всех разный, поэтому измеряем его и ставим пороги
по человеку, как слайдер «Gesture size» в Camera Switches у Google.
"""

import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.profile import MotionProfile, MotionWizard, STEPS


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


# --------------------------------------------------------------------------- #
#  Мастер
# --------------------------------------------------------------------------- #
def test_wizard_walks_all_steps_by_time():
    wizard = MotionWizard()
    assert wizard.phase == STEPS[0].key
    assert "РАЗОЖМИТЕ" in wizard.text()
    for i in range(10_000):
        if wizard.update(0.05, pinch=0.10 + 0.002 * (i % 100)):
            break
    assert wizard.done
    assert wizard.progress == pytest.approx(1.0)
    assert len(wizard._values["pinch"]) > 50


def test_wizard_collects_only_its_own_step():
    wizard = MotionWizard()
    for _ in range(40):
        wizard.update(0.05, pinch=0.2, smile=0.5)      # шаг «щипок»
    assert len(wizard._values["pinch"]) == 40
    assert wizard._values["smile"] == []


def test_wizard_skips_step_and_finishes():
    wizard = MotionWizard()
    for _ in range(len(STEPS)):
        assert wizard.skip() is (wizard.index >= len(STEPS))
    assert wizard.done
    assert wizard.finish().missing        # ничего не мерили — честно пусто


def test_wizard_measures_pinch_range():
    wizard = MotionWizard()
    values = [0.10 + 0.20 * (i % 2) for i in range(200)]
    for v in values:
        if wizard.done:
            break
        wizard.update(0.04, pinch=v)
    # до конца не дошли — добиваем остальные шаги пропуском
    while not wizard.done:
        wizard.skip()
    prof = wizard.finish()
    assert prof.pinch_closed == pytest.approx(0.10, abs=0.02)
    assert prof.pinch_open == pytest.approx(0.30, abs=0.02)
    assert prof.pinch_range == pytest.approx(0.20, abs=0.04)


def test_profile_suggestions_are_personal_and_clamped():
    prof = MotionProfile(pinch_open=0.48, pinch_closed=0.30, smile=0.30,
                         brow=0.40, mouth=0.99, squat=0.95)
    out = prof.suggest()
    # щипок: порог между «свёл» и «разжал», но не выше общего 0.55
    assert 0.30 < out["pinch_ratio"] <= 0.55
    assert out["smile_delta"] <= 0.120
    assert out["brow_delta"] <= 0.100
    assert 0.35 <= out["mouth_open_ratio"] <= 0.80
    assert 0.28 <= out["squat_down"] <= 0.80
    assert out["squat_up"] < out["squat_down"]


def test_weak_movements_keep_defaults():
    """Человек почти не улыбнулся — порог не трогаем, иначе будут ложные клики."""
    prof = MotionProfile(pinch_open=0.12, pinch_closed=0.10, smile=0.002)
    out = prof.suggest()
    assert "smile_delta" not in out
    assert "pinch_ratio" not in out        # размах 0.02 — слишком мало
    assert out == {}


def test_profile_roundtrip_and_text():
    prof = MotionProfile(pinch_open=0.33, pinch_closed=0.11, smile=0.08,
                         brow=0.06, mouth=0.62, squat=0.5, frames=420,
                         missing=["squat"])
    restored = MotionProfile.from_dict(prof.to_dict())
    assert restored.pinch_open == pytest.approx(0.33)
    assert restored.frames == 420
    assert restored.missing == ["squat"]
    assert "щипок" in prof.text() and "улыбка" in prof.text()


# --------------------------------------------------------------------------- #
#  В приложении
# --------------------------------------------------------------------------- #
def _run_step(app: AirMouseApp, **values) -> None:
    """Прокрутить текущий шаг мастера с заданными признаками."""
    wizard = app.motion_wizard
    assert wizard is not None
    key = wizard.step.key
    t = app._motion_at
    guard = 0
    while app.motion_wizard is not None and wizard.step.key == key and guard < 5000:
        app._motion_features = lambda: {name: values.get(name) for name in
                                        ("pinch", "smile", "brow", "mouth", "squat")}
        t += 1 / 30
        app._tick_motion_profile(t)
        guard += 1


def test_app_profile_applies_personal_thresholds():
    app = _app()
    app.start_motion_profile()
    wizard = app.motion_wizard
    assert wizard is not None

    # «щипок»: чередуем «свёл» и «разжал» — как человек и делает
    t = 0.0
    while app.motion_wizard is not None and wizard.step.key == "pinch":
        value = 0.09 + 0.21 * (wizard.frames % 2)
        app._motion_features = lambda v=value: {"pinch": v, "smile": 0.0, "brow": 0.0,
                                                "mouth": None, "squat": None}
        t += 1 / 30
        app._tick_motion_profile(t)

    _run_step(app, smile=0.10)
    _run_step(app, brow=0.09)
    _run_step(app, mouth=0.80)
    _run_step(app, squat=0.60)
    if app.motion_wizard is not None:          # последний шаг мог ещё идти
        _run_step(app, squat=0.60)

    assert app.motion_wizard is None
    assert 0.18 <= app.cfg.hand.pinch_ratio <= 0.55
    assert app.cfg.face.smile_delta == pytest.approx(0.055, abs=0.02)
    assert app.cfg.face.brow_delta == pytest.approx(0.0495, abs=0.02)
    assert app.cfg.face.mouth_open_ratio == pytest.approx(0.56, abs=0.05)
    assert app.cfg.body.squat_down <= 0.80
    assert app.cfg.motion_profile["pinch_open"] > app.cfg.motion_profile["pinch_closed"]
    assert "пороги" in app._events_log[0]


def test_app_profile_cancel_and_skip():
    app = _app()
    app.start_motion_profile()
    app.skip_motion_step()
    assert app.motion_wizard is not None
    assert app.cancel_motion_profile()
    assert app.motion_wizard is None
    assert "отменён" in app._events_log[0]


def test_app_profile_cannot_start_during_gaze_calibration():
    app = _app()
    app.start_gaze_calibration()
    assert "калибровк" in app.start_motion_profile()
    assert app.motion_wizard is None


def test_hotkeys_n_and_space():
    app = _app()
    from airmouse.keys import aliases
    n_code = sorted(aliases("n"))[0]
    space = 32
    assert app.handle_hotkey(n_code) is True
    assert app.motion_wizard is not None
    before = app.motion_wizard.index
    assert app.handle_hotkey(space) is True
    assert app.motion_wizard.index == before + 1


