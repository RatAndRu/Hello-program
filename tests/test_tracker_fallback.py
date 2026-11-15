"""Откат на классический движок должен быть объяснён, а не молчаливым."""

import pytest

from airmouse import tracker as tracker_module
from airmouse.config import FaceConfig, HandConfig
from airmouse.tracker import explain_mediapipe_failure


def test_auto_falls_back_with_reason(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("нет библиотеки")

    monkeypatch.setattr(tracker_module, "MediaPipeTracker", boom)
    tracker = tracker_module.create_tracker("auto", HandConfig(), FaceConfig(), "models")
    assert tracker.name == "classical"
    assert "нет библиотеки" in tracker.fallback_reason


def test_explicit_mediapipe_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("нет библиотеки")

    monkeypatch.setattr(tracker_module, "MediaPipeTracker", boom)
    with pytest.raises(RuntimeError):
        tracker_module.create_tracker("mediapipe", HandConfig(), FaceConfig(), "models")


def test_missing_models_message_is_actionable():
    from airmouse.models import ModelError

    text = explain_mediapipe_failure(ModelError("не удалось скачать"), "models")
    assert "модел" in text.lower()


def test_explicit_classical_has_no_fallback_reason_noise():
    tracker = tracker_module.create_tracker("classical", HandConfig(), FaceConfig())
    assert tracker.name == "classical"
