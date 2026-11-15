"""Две руки в кадре: главная управляет, вторая только отображается."""

import numpy as np

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.gestures import synthetic_hand
from airmouse.tracker import FrameResult

EMPTY = np.zeros((360, 640, 3), dtype=np.uint8)


class TwoHandTracker:
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


def make_app(script, **overrides):
    cfg = AppConfig()
    for key, value in overrides.items():
        parts = key.split(".")
        node = cfg
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app.tracker = TwoHandTracker(script)
    app._prepared = True
    return app


def _hand(center=(0.3, 0.55), scale=0.2):
    return synthetic_hand(center=center, scale=scale)


def test_primary_hand_stays_the_same():
    """Новая рука в кадре не должна отбирать управление у уже работающей."""
    left = _hand(center=(0.25, 0.55))
    right = _hand(center=(0.75, 0.55))
    app = make_app([[left], [left], [right, left], [left, right]])
    for i in range(4):
        app.process_frame(EMPTY, 100.0 + i * 0.03, i * 30)
        # главной всегда остаётся левая рука, в каком бы порядке их ни вернул движок
        assert app._hands[app._primary_index] is left


def test_second_hand_does_not_steal_pointer():
    """Курсор двигает только главная рука, даже если вторая ближе к центру."""
    left = _hand(center=(0.2, 0.6))
    right = _hand(center=(0.8, 0.4))
    app = make_app([[left]] * 3 + [[right, left]] * 6)
    now = 200.0
    for i in range(9):
        app.process_frame(EMPTY, now, int(now * 1000))
        now += 1 / 30.0
    assert len(app._hands) == 2
    assert app._hands[app._primary_index] is left


def test_ignore_mode_keeps_only_one_hand():
    left = _hand(center=(0.3, 0.55))
    second = _hand(center=(0.7, 0.55))
    app = make_app([[left, second]] * 2, **{"hand.second_hand": "ignore"})
    app.process_frame(EMPTY, 300.0, 0)
    assert len(app._hands) == 1


def test_face_events_suppressed_while_dragging(monkeypatch):
    """Пока тянем объект, улыбка не должна «отпускать» кнопку мыши."""
    app = make_app([[_hand()]] * 2)

    from airmouse.gestures import Event

    monkeypatch.setattr(
        app, "_handle_face",
        lambda face, now: [Event("smile_hold", label="улыбка")],
    )
    app.hand_fsm._dragging = True
    events = app.process_frame(EMPTY, 400.0, 0)
    assert all(e.kind != "smile_hold" for e in events)

    app.hand_fsm._dragging = False
    events = app.process_frame(EMPTY, 400.1, 30)
    assert any(e.kind == "smile_hold" for e in events)
