"""Моргание и подмигивание: время захвата, оба глаза, предел «зажмурился»."""

from airmouse.config import FaceConfig
from airmouse.face import FaceFSM, measure_face
from airmouse.synthetic import synthetic_face

FPS = 25.0
OPEN = 0.30
CLOSED = 0.08


def _run(ears, cfg: FaceConfig | None = None):
    """Прогнать последовательность EAR и вернуть список событий."""
    fsm = FaceFSM(cfg or FaceConfig())
    events = []
    t = 0.0
    for ear in ears:
        pair = (ear, ear) if isinstance(ear, (int, float)) else ear
        events += fsm.update(measure_face(synthetic_face(ear=pair)), t)
        t += 1.0 / FPS
    return fsm, events


def _kinds(events):
    return [e.kind for e in events]


# --------------------------------------------------------------------------- #
#  Время захвата
# --------------------------------------------------------------------------- #
def test_instant_eyelid_twitch_is_ignored():
    """Один кадр «закрыто» — это не моргание и не что-либо ещё."""
    _fsm, events = _run([OPEN] * 6 + [CLOSED] + [OPEN] * 5)
    assert _kinds(events) == []


def test_blink_needs_capture_time():
    cfg = FaceConfig()
    assert cfg.blink_min_s >= 0.08          # «чуть подождали»
    # 2 кадра при 25 к/с = 0.08 с — меньше времени захвата, одиночного моргания нет
    _fsm, events = _run([OPEN] * 6 + [CLOSED] * 2 + [OPEN] * 4)
    assert "eyes_closed_hold" not in _kinds(events)


def test_double_blink_needs_both_blinks_held():
    """Обычное двойное моргание работает (каждое дольше времени захвата)."""
    _fsm, events = _run([OPEN] * 6 + [CLOSED] * 4 + [OPEN] * 3
                        + [CLOSED] * 4 + [OPEN] * 6)
    assert _kinds(events) == ["double_blink"]


# --------------------------------------------------------------------------- #
#  Подмигивание и «оба глаза»
# --------------------------------------------------------------------------- #
def test_wink_works_when_other_eye_stays_open():
    _fsm, events = _run([OPEN] * 6 + [(CLOSED, OPEN)] * 8 + [OPEN] * 4)
    assert _kinds(events) == ["wink_left"]


def test_no_wink_when_both_eyes_close():
    """Оба глаза закрылись — это моргание, подмигивания быть не должно."""
    _fsm, events = _run([OPEN] * 6 + [(CLOSED, CLOSED)] * 4 + [OPEN] * 5)
    assert not any(kind.startswith("wink") for kind in _kinds(events))


def test_no_wink_when_other_eye_blinks_during():
    """Второй глаз моргнул посреди «подмигивания» — это уже не подмигивание."""
    ears = [OPEN] * 6
    ears += [(CLOSED, OPEN)] * 3
    ears += [(CLOSED, CLOSED)] * 2       # второй глаз закрылся на мгновение
    ears += [(CLOSED, OPEN)] * 3
    ears += [OPEN] * 4
    _fsm, events = _run(ears)
    assert not any(kind.startswith("wink") for kind in _kinds(events))


def test_wink_must_be_held():
    cfg = FaceConfig()
    short = int(cfg.wink_min_s * FPS) - 1
    _fsm, events = _run([OPEN] * 6 + [(CLOSED, OPEN)] * short + [OPEN] * 4)
    assert not any(kind.startswith("wink") for kind in _kinds(events))


# --------------------------------------------------------------------------- #
#  Слишком долго закрытые глаза
# --------------------------------------------------------------------------- #
def test_long_closure_reports_once_and_then_stops():
    frames = int(6 * FPS)
    fsm, events = _run([OPEN] * 6 + [CLOSED] * frames + [OPEN] * 6)
    kinds = _kinds(events)
    assert kinds == ["eyes_closed_hold"], kinds
    assert fsm.cfg.eyes_closed_cap_s < frames / FPS


def test_after_long_closure_wink_works_again():
    frames = int(5 * FPS)
    _fsm, events = _run([OPEN] * 6 + [CLOSED] * frames + [OPEN] * 6
                        + [(CLOSED, OPEN)] * 8 + [OPEN] * 4)
    assert _kinds(events) == ["eyes_closed_hold", "wink_left"]


def test_long_closure_does_not_become_double_blink():
    """Долгое закрытие не должно «доклеиваться» к следующему морганию."""
    frames = int(5 * FPS)
    _fsm, events = _run([OPEN] * 6 + [CLOSED] * frames + [OPEN] * 6
                        + [CLOSED] * 4 + [OPEN] * 6)
    kinds = _kinds(events)
    assert "double_blink" not in kinds
    assert kinds.count("eyes_closed_hold") == 1


# --------------------------------------------------------------------------- #
#  Ложные «руки»: фильтр детекции
# --------------------------------------------------------------------------- #
def _hand(score=1.0, scale=0.2):
    from airmouse.gestures import synthetic_hand

    hand = synthetic_hand(scale=scale)
    hand.score = score
    return hand


def test_low_confidence_hand_is_ignored():
    from airmouse.config import HandConfig
    from airmouse.gestures import HandGate

    gate = HandGate(HandConfig())
    assert gate.update([_hand(score=0.20)]) == []
    assert gate.update([_hand(score=0.90)])


def test_tiny_and_huge_hands_are_ignored():
    from airmouse.config import HandConfig
    from airmouse.gestures import HandGate

    cfg = HandConfig()
    gate = HandGate(cfg)
    assert gate.update([_hand(scale=0.005)]) == []      # крошечное пятно
    assert gate.update([_hand(scale=0.95)]) == []       # «рука» на пол-кадра
    assert gate.update([_hand(scale=0.20)])


def test_phantom_hand_never_reaches_cursor():
    """Кадр без руки: фантом с низкой уверенностью не двигает курсор."""
    import numpy as np

    from airmouse.app import AirMouseApp
    from airmouse.config import AppConfig
    from airmouse.tracker import FrameResult

    class Phantom:
        name = "fake"

        def process(self, frame, ts_ms):
            return FrameResult(hands=[_hand(score=0.15)], face=None, backend="fake")

        def close(self):
            pass

    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    app.tracker = Phantom()
    app._prepared = True
    empty = np.zeros((360, 640, 3), dtype=np.uint8)
    for i in range(10):
        app.process_frame(empty, 100.0 + i * 0.05, i * 50)
    assert app.backend.log == []
    assert app._hands == []


def test_hand_release_is_smoothed():
    from airmouse.config import HandConfig
    from airmouse.gestures import HandGate

    cfg = HandConfig()
    gate = HandGate(cfg)
    assert gate.update([_hand()])                       # рука появилась
    assert gate.update([])                              # один пропущенный кадр — терпим
    assert gate.update([]) == []                        # второй — уже честно отпустили


def test_confirm_frames_can_be_raised():
    from airmouse.config import HandConfig
    from airmouse.gestures import HandGate

    cfg = HandConfig()
    cfg.confirm_frames = 3
    gate = HandGate(cfg)
    assert gate.update([_hand()]) == []
    assert gate.update([_hand()]) == []
    assert gate.update([_hand()])
