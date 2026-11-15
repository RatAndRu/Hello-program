"""Всё, что настроено, должно пережить выход и повторный запуск.

Раньше файл настроек писала только кнопка в панели: включил «мышь глазами»
клавишей G, прошёл калибровку взгляда, закрыл приложение — и всё это пропало.
Здесь проверяем, что сохраняется весь конфиг: режимы, ползунки, калибровки.
"""

from pathlib import Path

import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig, load_config
from airmouse.gaze import CALIBRATION_TARGETS, GazeCalibration


def _app(tmp_path: Path, autosave: bool = True, **overrides) -> AirMouseApp:
    cfg = AppConfig()
    for dotted, value in overrides.items():
        section, _, name = dotted.partition(".")
        setattr(getattr(cfg, section), name, value)
    app = AirMouseApp(cfg, dry_run=True, show_window=False)
    app._prepared = True
    app.config_path = tmp_path / "config.json"
    app.autosave = autosave
    return app


def _calibrated() -> GazeCalibration:
    def gaze_for(sx: float, sy: float):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    calib = GazeCalibration(feature="head2")
    for sx, sy in CALIBRATION_TARGETS:
        calib.add(*gaze_for(sx, sy), sx, sy)
    assert calib.fit()
    return calib


# --------------------------------------------------------------------------- #
#  Выход и повторный запуск
# --------------------------------------------------------------------------- #
def test_hotkey_toggles_and_sliders_survive_restart(tmp_path: Path):
    app = _app(tmp_path)
    app.cfg.hand.pinch_ratio = 0.31            # ползунок
    app.cfg.pointer.max_step_px = 180
    app.cfg.body.enabled = True
    app.router.gaze_pointer = True             # клавиша G
    app.router.head_pointer = True             # клавиша H
    app._fullscreen = True                     # клавиша F
    app.gaze_calib = _calibrated()             # клавиша B

    app.shutdown()                             # человек просто закрыл программу

    cfg = load_config(tmp_path / "config.json")
    assert cfg.hand.pinch_ratio == pytest.approx(0.31)
    assert cfg.pointer.max_step_px == 180
    assert cfg.body.enabled is True
    assert cfg.gaze_pointer is True
    assert cfg.head_pointer is True
    assert cfg.fullscreen is True
    # калибровка взгляда не просто «есть флаг», а рабочая
    restored = GazeCalibration.from_dict(cfg.face.gaze_calibration)
    assert restored.ready and not restored.stale
    sx, sy = restored.apply((0.5 - 0.5) * 0.6, (0.5 - 0.5) * 0.3)
    assert sx == pytest.approx(0.5, abs=0.05) and sy == pytest.approx(0.5, abs=0.05)


def test_nothing_is_written_without_autosave(tmp_path: Path):
    app = _app(tmp_path, autosave=False)
    app.cfg.hand.pinch_ratio = 0.42
    app.shutdown()
    assert not (tmp_path / "config.json").exists()


def test_second_save_does_not_touch_the_file(tmp_path: Path):
    app = _app(tmp_path)
    app.cfg.hand.pinch_ratio = 0.27
    assert app.save_settings("тест") is not None
    # ничего не менялось — записывать второй раз нечего
    assert app.save_settings("тест") is None


def test_background_autosave_writes_after_a_change(tmp_path: Path):
    app = _app(tmp_path)
    app._maybe_autosave(10.0)                  # первый тик — запоминаем состояние
    app.cfg.face.gaze_deadzone = 0.09
    app._maybe_autosave(20.0)                  # через 5+ секунд — записали
    cfg = load_config(tmp_path / "config.json")
    assert cfg.face.gaze_deadzone == pytest.approx(0.09)


# --------------------------------------------------------------------------- #
#  Калибровка взгляда сохраняется сразу после мастера
# --------------------------------------------------------------------------- #
def test_finished_calibration_is_written_immediately(tmp_path: Path):
    app = _app(tmp_path)

    def gaze_for(sx: float, sy: float):
        return ((sx - 0.5) * 0.6, (sy - 0.5) * 0.3)

    pursuit = []
    t = 0.0
    for sx, sy in CALIBRATION_TARGETS:
        for _ in range(6):
            gx, gy = gaze_for(sx, sy)
            pursuit.append((t, gx, gy, sx, sy))
            t += 1.0 / 30.0
    app._calib = {"mode": "pursuit", "pursuit": pursuit, "head": [],
                  "phase": "pursuit", "samples": [], "points": []}
    app._finish_gaze_calibration()

    cfg = load_config(tmp_path / "config.json")
    assert cfg.face.gaze_absolute is True
    assert GazeCalibration.from_dict(cfg.face.gaze_calibration).ready
    assert app.gaze_calib.ready


def test_reset_calibration_is_written_too(tmp_path: Path):
    app = _app(tmp_path)
    app.gaze_calib = _calibrated()
    app.cfg.face.gaze_calibration = app.gaze_calib.to_dict()
    app.save_settings("до сброса")
    app.reset_gaze_calibration()
    cfg = load_config(tmp_path / "config.json")
    assert cfg.face.gaze_calibration == {}


# --------------------------------------------------------------------------- #
#  Панель настроек пишет в тот же файл, что и --config
# --------------------------------------------------------------------------- #
def test_settings_panel_uses_the_same_path(tmp_path: Path):
    path = tmp_path / "мой-конфиг.json"
    app = _app(tmp_path)
    app.config_path = path
    app.show_window = True
    assert app.toggle_settings() is True
    assert app.settings is not None
    assert app.settings.path == path
