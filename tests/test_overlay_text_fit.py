"""Длинная строка в окне не должна выезжать за панель и налезать на соседнюю."""

import numpy as np

from airmouse.overlay import OverlayState, render
from airmouse.synthetic import synthetic_face
from airmouse import text as T


def _canvas() -> np.ndarray:
    return np.zeros((540, 960, 3), dtype=np.uint8)


def test_fit_truncates_to_width():
    line = "взгляд: вниз · мышь глазами ВКЛ (телепорт) · ошибка 1.1% · дрожание 0.6%"
    fitted = T.fit(line, 12, 200)
    assert fitted != line and fitted.endswith("…")
    assert T.measure(fitted, 12)[0] <= 200


def test_fit_keeps_short_line_untouched():
    assert T.fit("взгляд: вниз", 12, 200) == "взгляд: вниз"


def test_long_gaze_line_stays_on_screen():
    """Длинная строка про взгляд не уходит за правый край окна."""
    from airmouse.overlay import ACCENT

    st = OverlayState(face_seen=True, hand_seen=True, fps=29.6,
                      gaze_pointer=True,
                      gaze_text="взгляд: вниз · мышь глазами ВКЛ (телепорт) · "
                                "ошибка 1.1% · дрожание 0.6% · голова +12°/+3°")
    img = render(_canvas(), st, hands=[], face=synthetic_face())
    colour = np.array(ACCENT)
    mask = (np.abs(img.astype(int) - colour).sum(axis=2) < 40)
    ys, xs = np.nonzero(mask)
    assert xs.size, "строка про взгляд вообще не нарисована"
    assert xs.max() <= img.shape[1] - 3, f"строка вылезла за край: {xs.max()}"

    # короткая строка рисуется целиком — без «…»
    st.gaze_text = "взгляд: вниз"
    short = render(_canvas(), st, hands=[], face=synthetic_face())
    assert short.shape == img.shape
