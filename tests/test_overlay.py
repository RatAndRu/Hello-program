"""Окно предпросмотра: AR-отрисовка и русские подписи не должны падать."""

import numpy as np

from airmouse import text as T
from airmouse.landmarks import Face, Hand
from airmouse.overlay import OverlayState, render

import pytest


def _hand() -> Hand:
    """Правая рука, ладонью к камере, пальцы вверх (21 точка)."""
    pts = np.array([
        (0.50, 0.94), (0.38, 0.86), (0.30, 0.78), (0.25, 0.72), (0.205, 0.655),
        (0.425, 0.665), (0.405, 0.545), (0.395, 0.475), (0.39, 0.415),
        (0.50, 0.645), (0.50, 0.515), (0.50, 0.44), (0.50, 0.365),
        (0.575, 0.66), (0.60, 0.535), (0.61, 0.465), (0.615, 0.405),
        (0.655, 0.69), (0.695, 0.60), (0.715, 0.545), (0.73, 0.49),
    ], dtype=np.float32)
    return Hand(pts, handedness="Right")


def _face() -> Face:
    """Простейшая «сетка» из 468 точек: важен не смысл, а отрисовка."""
    rng = np.random.default_rng(7)
    pts = rng.uniform(0.2, 0.6, size=(468, 3)).astype(np.float32)
    # глаза и губы ставим геометрически осмысленно, чтобы линии не вырождались
    pts[33], pts[133] = (0.28, 0.42, 0.0), (0.38, 0.42, 0.0)
    pts[362], pts[263] = (0.46, 0.42, 0.0), (0.56, 0.42, 0.0)
    return Face(pts)


def _frame() -> np.ndarray:
    return np.full((540, 960, 3), 60, dtype=np.uint8)


def test_render_hand_and_face():
    out = render(
        _frame(),
        OverlayState(fps=25.0, backend="ИИ MediaPipe (нейросеть)", pose="щипок",
                     hand_seen=True, face_seen=True, expression="улыбка 60%",
                     version="0.2.0"),
        hands=[_hand()], face=_face(),
    )
    assert out.shape == (540, 960, 3)
    assert out.any()


def test_render_paused_help_and_classical():
    for state in (
        OverlayState(paused=True, backend="классический CV (без ИИ)"),
        OverlayState(show_help=True),
        OverlayState(actions_on=False, dry_run=True,
                     backend_note="MediaPipe недоступен: нет моделей"),
    ):
        out = render(_frame(), state, hands=[_hand()])
        assert out.shape == (540, 960, 3)


def test_render_tiny_frame_does_not_crash():
    """Окно может быть совсем маленьким — подписи обязаны помещаться."""
    out = render(np.zeros((120, 160, 3), dtype=np.uint8), OverlayState(show_help=True))
    assert out.shape == (120, 160, 3)


def test_text_cyrillic_available_or_translit(monkeypatch):
    """Без TrueType-шрифта текст рисуется транслитом, но не падает."""
    assert T.measure("привет", 14)[0] > 0
    img = np.zeros((40, 200, 3), dtype=np.uint8)
    T.draw(img, "привет", (4, 4), 18)
    assert img.any()

    monkeypatch.setattr(T, "_font", lambda size: None)
    assert T.translit("Привет") == "Privet"
    img2 = np.zeros((40, 200, 3), dtype=np.uint8)
    T.draw(img2, "проверка", (4, 4), 16)
    assert img2.any()
