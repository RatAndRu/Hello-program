"""Взгляд без «диагоналей»: модель по осям, задержка зрачка учитывается."""

import numpy as np
import pytest

from airmouse.gaze import (
    PURSUIT_DURATION_S,
    GazeCalibration,
    lag_compensate,
    pursuit_metrics,
    pursuit_point,
)


def gaze_for(sx: float, sy: float):
    """Честный зрачок: горизонталь экрана — только от u, вертикаль — только от v."""
    return (-0.30 + 0.60 * sx, -0.18 + 0.36 * sy)


def _noisy_pursuit(seed: int = 5, n: int = 400, noise: float = 0.012):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        t = i * PURSUIT_DURATION_S / n
        sx, sy = pursuit_point(t)
        gx, gy = gaze_for(sx, sy)
        rows.append((t, gx + rng.normal(0, noise), gy + rng.normal(0, noise), sx, sy))
    return rows


def test_noisy_pursuit_picks_axis_model():
    calib = GazeCalibration(points=[(u, v, sx, sy) for (_t, u, v, sx, sy) in _noisy_pursuit()])
    assert calib.fit()
    assert calib.model == "axis"
    H = calib.matrix
    # перекрёстных членов нет: x экрана не зависит от вертикали зрачка и наоборот
    assert H[0, 1] == 0.0 and H[1, 0] == 0.0 and H[2, 0] == 0.0 and H[2, 1] == 0.0


def test_horizontal_look_moves_cursor_only_horizontally():
    """Главная жалоба: смотришь вправо — курсор едет вправо-вниз. Больше нет."""
    calib = GazeCalibration(points=[(u, v, sx, sy) for (_t, u, v, sx, sy) in _noisy_pursuit()])
    assert calib.fit()
    left = calib.apply(*gaze_for(0.1, 0.5))
    right = calib.apply(*gaze_for(0.9, 0.5))
    assert right[0] - left[0] > 0.6
    assert abs(right[1] - left[1]) < 0.03
    up = calib.apply(*gaze_for(0.5, 0.1))
    down = calib.apply(*gaze_for(0.5, 0.9))
    assert down[1] - up[1] > 0.6
    assert abs(down[0] - up[0]) < 0.03


def test_axis_model_round_trips_through_config():
    calib = GazeCalibration(points=[(u, v, sx, sy) for (_t, u, v, sx, sy) in _noisy_pursuit()])
    calib.fit()
    restored = GazeCalibration.from_dict(calib.to_dict())
    assert restored.model == "axis" and restored.ready
    assert "по осям" in restored.quality_text()


def test_lag_compensation_pairs_pupil_with_earlier_dot():
    rows = _noisy_pursuit(noise=0.0)
    lag = 4
    delayed = [(t, *gaze_for(*rows[max(0, i - lag)][3:5]), sx, sy)
               for i, (t, _u, _v, sx, sy) in enumerate(rows)]
    naive = GazeCalibration(points=[(u, v, sx, sy) for (_t, u, v, sx, sy) in delayed])
    naive.fit()
    fixed = GazeCalibration(points=lag_compensate(delayed, lag))
    fixed.fit()
    assert fixed.error()[1] < naive.error()[1] * 0.5
    # задержка, которую намерил pursuit_metrics, совпадает с заложенной
    dt = PURSUIT_DURATION_S / len(rows)
    assert pursuit_metrics(delayed)["latency_ms"] == pytest.approx(lag * dt * 1000, rel=0.3)


def test_lag_compensation_without_lag_is_identity():
    rows = _noisy_pursuit(n=50)
    assert lag_compensate(rows, 0) == [(u, v, sx, sy) for (_t, u, v, sx, sy) in rows]
    # слишком мало кадров для сдвига — тоже без изменений
    assert len(lag_compensate(rows[:10], 4)) == 10
