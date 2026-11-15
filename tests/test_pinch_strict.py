"""Щипок — только двумя пальцами: кулак и «ОК» не должны кликать.

Плюс послабление порогов для второй руки в режиме «две руки».
"""

import numpy as np

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, HandConfig
from airmouse.gestures import (
    HandFSM,
    Pose,
    analyze_hand,
    classify_pose,
    pinch_is_real,
    recognize_pose,
    synthetic_hand,
)
from airmouse.settings_ui import TOGGLES
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)


# --------------------------------------------------------------------------- #
#  «Это не щипок»: кулак и «ОК»
# --------------------------------------------------------------------------- #
def _fist():
    return synthetic_hand(
        curl={k: 1.0 for k in ("index", "middle", "ring", "pinky", "thumb")},
        pinch_index=True,
    )


def _ok():
    return synthetic_hand(pinch_index=True,
                          curl={"index": 0.7, "middle": 0.0, "ring": 0.0, "pinky": 0.0})


def _run(fsm, hand, frames, t=0.0, dt=0.033):
    events, out = [], []
    for _ in range(frames):
        events += fsm.update(hand, t)
        t += dt
    out += events
    return out, t


def test_fist_pose_is_fist_not_pinch():
    hand = _fist()
    assert recognize_pose(hand, HandConfig()) is Pose.FIST
    f = analyze_hand(hand, "index")
    assert not pinch_is_real(f, HandConfig()), "кулак не должен считаться щипком"


def test_fist_does_not_click():
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    events, _ = _run(fsm, _fist(), 20)
    kinds = [e.kind for e in events]
    assert "pinch_release" not in kinds
    assert not [e for e in events if e.label == "щипок начат"]


def test_ok_sign_pose_is_ok_not_pinch():
    hand = _ok()
    assert recognize_pose(hand, HandConfig()) is Pose.OK
    f = analyze_hand(hand, "index")
    assert not pinch_is_real(f, HandConfig()), "«ОК» не должен считаться щипком"


def test_ok_sign_does_not_click():
    cfg = HandConfig()
    fsm = HandFSM(cfg)
    events, _ = _run(fsm, _ok(), 20)
    kinds = [e.kind for e in events]
    assert "pinch_release" not in kinds
    assert "ok_sign" in kinds, "«ОК» должен срабатывать как своя команда"


def test_pinch_needs_straight_index():
    """Полусогнутый указательный (как в «ОК») — ещё не щипок."""
    cfg = HandConfig()
    for curl in (0.45, 0.6, 0.75):
        hand = synthetic_hand(pinch_index=True, curl={"index": curl})
        f = analyze_hand(hand, "index")
        assert f.pinch < cfg.pinch_ratio, curl
        assert not pinch_is_real(f, cfg), f"curl={curl} не должен быть щипком"


def test_pinch_requires_thumb_away_from_palm():
    cfg = HandConfig()
    hand = synthetic_hand(pinch_index=True)
    f = analyze_hand(hand, "index")
    f.thumb_tip_out = 0.1          # большой палец прижат к ладони
    assert not pinch_is_real(f, cfg)


# --------------------------------------------------------------------------- #
#  Настоящий щипок и его отмена
# --------------------------------------------------------------------------- #
def test_real_pinch_clicks_once():
    fsm = HandFSM(HandConfig())
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events, t = _run(fsm, opened, 4)
    events += _run(fsm, pinched, 6, t)[0]
    events += _run(fsm, opened, 4, t + 0.2)[0]
    assert len([e for e in events if e.kind == "pinch_release"]) == 1


def test_pinch_cancelled_when_hand_turns_into_fist():
    """Начали щипок, сжали кулак — это не клик, а отмена."""
    fsm = HandFSM(HandConfig())
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events, t = _run(fsm, opened, 4)
    started = _run(fsm, pinched, 6, t)[0]
    events += started
    assert [e for e in started if e.label == "щипок начат"], "щипок должен начаться"
    events += _run(fsm, _fist(), 6, t + 0.2)[0]
    events += _run(fsm, opened, 4, t + 0.4)[0]
    assert [e for e in events if e.kind == "pinch_release"] == []
    assert not fsm.pinching


def test_pinch_cancelled_when_hand_shows_ok():
    fsm = HandFSM(HandConfig())
    opened = synthetic_hand()
    pinched = synthetic_hand(pinch_index=True)
    events, t = _run(fsm, opened, 4)
    events += _run(fsm, pinched, 6, t)[0]
    events += _run(fsm, _ok(), 6, t + 0.2)[0]
    events += _run(fsm, opened, 4, t + 0.4)[0]
    assert [e for e in events if e.kind == "pinch_release"] == []


# --------------------------------------------------------------------------- #
#  Две руки: жесты проще
# --------------------------------------------------------------------------- #
def _late_pinch_cfg():
    """Порог такой, что синтетический щипок проходит только с послаблением."""
    cfg = HandConfig()
    cfg.pinch_ratio = 0.010
    cfg.pinch_release_ratio = 0.020
    return cfg


def test_relax_properties_soften_thresholds():
    cfg = HandConfig()
    strict = HandFSM(cfg)
    easy = HandFSM(cfg, relax=1.0)
    assert easy.pinch_on > strict.pinch_on
    assert easy.pinch_off > strict.pinch_off
    assert easy.pinch_min_s < strict.pinch_min_s
    assert easy.stable_frames < strict.stable_frames


def test_relax_brings_pinch_closer_to_reach():
    """Один и тот же щипок: строгая рука не ловит, вторая в «две руки» — ловит."""
    cfg = _late_pinch_cfg()
    hand = synthetic_hand(pinch_index=True)
    strict = HandFSM(cfg)
    easy = HandFSM(cfg, relax=1.0)
    assert not pinch_is_real(analyze_hand(hand, "index"), cfg, 0.0)
    assert pinch_is_real(analyze_hand(hand, "index"), cfg, 1.0)

    opened = synthetic_hand()
    frames = [(opened, 4), (hand, 6), (opened, 4)]
    clicks = {}
    for name, fsm in (("strict", strict), ("easy", easy)):
        events, t = [], 0.0
        for h, n in frames:
            chunk, t = _run(fsm, h, n, t)
            events += chunk
        clicks[name] = len([e for e in events if e.kind == "pinch_release"])
    assert clicks["strict"] == 0
    assert clicks["easy"] == 1


def test_relax_keeps_fist_and_ok_safe():
    """Послабление не возвращает ложный щипок на кулаке и «ОК»."""
    cfg = _late_pinch_cfg()
    easy = HandFSM(cfg, relax=1.0)
    for hand in (_fist(), _ok()):
        events, _ = _run(easy, hand, 20)
        assert [e for e in events if e.kind == "pinch_release"] == []


# --------------------------------------------------------------------------- #
#  Приложение: режим рук -> послабление
# --------------------------------------------------------------------------- #
class ScriptedTracker:
    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.index = 0

    def process(self, frame, ts_ms):
        hands = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return FrameResult(hands=list(hands), face=None, backend="fake")

    def close(self):
        pass


def _app(script, **overrides):
    cfg = AppConfig()
    for key, value in overrides.items():
        node = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = ScriptedTracker(script)
    app._prepared = True
    return app


def test_two_hand_modes_are_simpler_by_default():
    app = _app([[synthetic_hand()]], **{"hand.roles": "split"})
    assert app._click_relax() == 1.0
    app.process_frame(EMPTY, 100.0, 0)
    assert app.click_fsm.relax == 1.0
    assert app.hand_fsm.relax == 1.0  # первая рука тоже в «двух руках»


def test_single_hand_stays_strict():
    app = _app([[synthetic_hand()]], **{"hand.roles": "single"})
    assert app._click_relax() == 0.0
    assert app._two_hand_relax() == 0.0
    app.process_frame(EMPTY, 100.0, 0)
    assert app.hand_fsm.relax == 0.0
    assert app.click_fsm.relax == 0.0


def test_simple_two_hand_can_be_switched_off():
    app = _app([[synthetic_hand()]],
               **{"hand.roles": "split", "hand.simple_two_hand": False})
    assert app._two_hand_relax() == 0.0
    app.process_frame(EMPTY, 100.0, 0)
    assert app.click_fsm.relax == 0.0


def test_relax_follows_mode_switch_at_runtime():
    app = _app([[synthetic_hand()]])
    app.process_frame(EMPTY, 100.0, 0)
    assert app.hand_fsm.relax == 0.0
    app.cfg.hand.roles = "split"
    app.process_frame(EMPTY, 100.1, 33)
    assert app._two_hand_relax() == 1.0
    assert app.click_fsm.relax == 1.0


def test_zoom_mode_is_half_relaxed():
    app = _app([[synthetic_hand()]], **{"hand.two_hand": "zoom"})
    assert app._two_hand_relax() == 0.5


def test_second_hand_click_works_in_two_hand_mode():
    """В режиме двух рук щипок второй рукой всё так же даёт клик."""
    cfg_pinch = {"pinch_ratio": 0.010, "pinch_release_ratio": 0.020}
    pointer = synthetic_hand(center=(0.30, 0.55), scale=0.26)
    click_open = synthetic_hand(center=(0.70, 0.55), scale=0.17)
    click_pinch = synthetic_hand(center=(0.70, 0.55), scale=0.17, pinch_index=True)
    script = [[pointer, click_open]] * 4 + [[pointer, click_pinch]] * 6
    script += [[pointer, click_open]] * 4
    app = _app(script, **{"hand.roles": "split",
                          "hand.pinch_ratio": cfg_pinch["pinch_ratio"],
                          "hand.pinch_release_ratio": cfg_pinch["pinch_release_ratio"]})
    clicks = []
    for i in range(len(script)):
        app.process_frame(EMPTY, 100.0 + i * 0.033, i * 33)
        clicks += [e for e in app.backend.log if e.startswith("click")]
        app.backend.log.clear()
    assert clicks, "вторая рука должна кликнуть"


def test_simple_two_hand_has_toggle():
    assert any(t.key == "mode.simple_two_hand" for t in TOGGLES)


# --------------------------------------------------------------------------- #
#  Пороги и классификация
# --------------------------------------------------------------------------- #
def test_strict_pinch_pose_requires_real_pinch():
    cfg = HandConfig()
    hand = synthetic_hand(pinch_index=True)
    f = analyze_hand(hand, "index")
    assert pinch_is_real(f, cfg)
    assert classify_pose(f, cfg) is Pose.PINCH


def test_ok_hand_classifies_as_ok_even_with_relax():
    cfg = HandConfig()
    hand = _ok()
    f = analyze_hand(hand, "index")
    assert classify_pose(f, cfg, relax=1.0) is Pose.OK


def test_new_knobs_survive_save_and_load(tmp_path):
    from airmouse.config import load_config, save_config

    cfg = AppConfig()
    cfg.hand.simple_two_hand = False
    cfg.hand.pinch_min_index_ext = 0.7
    path = save_config(cfg, tmp_path / "airmouse.json")
    back = load_config(path)
    assert back.hand.simple_two_hand is False
    assert abs(back.hand.pinch_min_index_ext - 0.7) < 1e-9
