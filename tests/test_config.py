"""Конфигурация: сохранение, чтение, точечное изменение."""

from __future__ import annotations

import json

import pytest

from airmouse.config import AppConfig, load_config, save_config, set_value


def test_roundtrip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = AppConfig()
    cfg.hand.pinch_ratio = 0.29
    cfg.pointer.active_box = (0.1, 0.2, 0.9, 0.8)
    cfg.lip.words["стоп"] = "toggle_pause"
    save_config(cfg, path)

    restored = load_config(path)
    assert restored.hand.pinch_ratio == pytest.approx(0.29)
    assert restored.pointer.active_box == pytest.approx((0.1, 0.2, 0.9, 0.8))
    assert restored.lip.words["стоп"] == "toggle_pause"


def test_missing_file_creates_default(tmp_path):
    path = tmp_path / "nested" / "cfg.json"
    cfg = load_config(path)
    assert path.exists()
    assert cfg.hand.enabled is True


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"hand": {"pinch_ratio": 0.4, "nonsense": 1}}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.hand.pinch_ratio == pytest.approx(0.4)


def test_broken_json_falls_back(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text("{ это не json", encoding="utf-8")
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)


def test_set_value():
    cfg = AppConfig()
    assert set_value(cfg, "hand.pinch_ratio", "0.45") == pytest.approx(0.45)
    assert set_value(cfg, "camera.index", "1") == 1
    assert set_value(cfg, "show_window", "false") is False
    assert set_value(cfg, "pointer.active_box", "0.1,0.2,0.9,0.8") == pytest.approx(
        (0.1, 0.2, 0.9, 0.8)
    )
    with pytest.raises(KeyError):
        set_value(cfg, "hand.нет_такого", "1")
