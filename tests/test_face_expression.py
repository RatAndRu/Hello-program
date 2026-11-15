"""Мимика в окне: открытый рот и удивление не перекрываются улыбкой."""

import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.config import FaceConfig
from airmouse.face import FaceFSM, FaceMetrics
from airmouse.overlay import OverlayState, render


def _app() -> AirMouseApp:
    cfg = AppConfig()
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    app._frame_size = (960, 540)
    return app


def _metrics(open_mouth: float, brow: float = 0.0) -> FaceMetrics:
    return FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=1.0,
                       mouth_open=open_mouth, corner_lift=0.0, brow_height=brow,
                       valid=True)


def _text(app, *, open_mouth=0.1, smile=0.0, sad=0.0, brow=0.0) -> str:
    app._metrics = _metrics(open_mouth, brow)
    app.face_fsm.smile_score = smile
    app.face_fsm.sad_score = sad
    app.face_fsm.brow_score = brow
    return app._expression_text()


# --------------------------------------------------------------------------- #
#  Открытый рот важнее улыбки и грусти
# --------------------------------------------------------------------------- #
def test_open_mouth_is_not_reported_as_a_smile():
    app = _app()
    # рот открыт, ширина губ «как у улыбки» — раньше выходило «улыбка 100%»
    assert _text(app, open_mouth=0.7, smile=0.5, sad=0.2) == "рот открыт"


def test_open_mouth_with_raised_brows_is_surprise():
    app = _app()
    assert _text(app, open_mouth=0.4, brow=0.2) == "удивление"


def test_smile_without_open_mouth_still_reads_as_smile():
    app = _app()
    text = _text(app, open_mouth=0.08, smile=0.2)
    assert text.startswith("улыбка")


def test_sadness_is_not_hidden_by_smile():
    app = _app()
    timeline = _text(app, open_mouth=0.05, smile=0.0, sad=0.1)
    assert timeline.startswith("грусть")


def test_slightly_open_mouth_states_are_distinct():
    app = _app()
    assert _text(app, open_mouth=0.35) == "рот приоткрыт"
    assert _text(app, open_mouth=0.05) == "нейтрально"


# --------------------------------------------------------------------------- #
#  Сам счётчик улыбки не верит ширине рта при открытой челюсти
# --------------------------------------------------------------------------- #
def test_wide_mouth_ignores_width_gain_in_smile_score():
    fsm = FaceFSM(FaceConfig())
    base = FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=1.0,
                       mouth_open=0.05, corner_lift=0.02, brow_height=0.0, valid=True)
    fsm.update(base, 0.0)                     # нейтраль зафиксирована

    wide = FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=3.0,
                       mouth_open=0.8, corner_lift=0.02, brow_height=0.0, valid=True)
    fsm.update(wide, 1.0)
    assert fsm.mouth_wide is True
    assert fsm.smile_score < 0.05, "открытая челюсть не должна выглядеть улыбкой"

    smile = FaceMetrics(ear_left=0.3, ear_right=0.3, mouth_width=3.0,
                        mouth_open=0.8, corner_lift=0.30, brow_height=0.0, valid=True)
    fsm.update(smile, 2.0)
    assert fsm.smile_score > 0.1, "уголки вверх при открытом рте — всё-таки улыбка"


# --------------------------------------------------------------------------- #
#  В окне видно и рот, и подсказку головы, и спорт
# --------------------------------------------------------------------------- #
def test_face_panel_has_a_mouth_bar():
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    closed = render(frame.copy(), OverlayState(face_seen=True, mouth_open=0.0))
    opened = render(frame.copy(), OverlayState(face_seen=True, mouth_open=0.5))
    # полоса рта — пятая в правой панели: x ≈ 710..806, y ≈ 150..159
    band = (slice(151, 159), slice(712, 804))
    assert opened[band].mean() > closed[band].mean() + 5


def test_face_hint_is_drawn_when_face_is_lost():
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    state = OverlayState(face_seen=False, face_hint=(0.3, 0.2, 0.5, 0.45),
                         face_hint_note="лицо не видно — показываю по телу")
    img = render(frame.copy(), state)
    assert int(img.sum()) > 0
    assert (img[..., 2] > img[..., 0]).any(), "рамка подсказки — синеватая"


def test_sport_line_fits_the_status_panel():
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    plain = render(frame.copy(), OverlayState(hand_seen=False))
    sport = render(frame.copy(), OverlayState(
        hand_seen=False,
        sport_text="спорт: сгибания рук 5 · T-поза · бокс: стойка · ударов 12"))
    assert int(sport.sum()) > int(plain.sum())
