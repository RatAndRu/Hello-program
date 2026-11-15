"""Источники точек: MediaPipe (два API) или классическое CV.

Поддерживаются оба поколения MediaPipe:

* ``mediapipe<1.0`` — старый ``mp.solutions`` с встроенными моделями;
* ``mediapipe>=1.0`` — Tasks API (``vision.HandLandmarker`` /
  ``vision.FaceLandmarker``), которому нужны файлы ``*.task`` (скачиваются
  один раз в ``models/``).

Снаружи всё одинаково: ``tracker.process(frame_bgr, ts_ms) -> FrameResult``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol

import numpy as np

from .config import FaceConfig, HandConfig
from .landmarks import Face, Hand

log = logging.getLogger("airmouse")


@dataclass
class FrameResult:
    hands: List[Hand] = field(default_factory=list)
    face: Optional[Face] = None
    backend: str = ""

    @property
    def primary_hand(self) -> Optional[Hand]:
        return self.hands[0] if self.hands else None


class Tracker(Protocol):  # pragma: no cover - протокол
    name: str

    def process(self, frame_bgr: np.ndarray, ts_ms: int) -> FrameResult: ...
    def close(self) -> None: ...


def _to_hand(landmarks, handedness: str = "Right") -> Hand:
    pts = np.array([[lm.x, lm.y, getattr(lm, "z", 0.0)] for lm in landmarks], dtype=np.float32)
    return Hand(pts, handedness=handedness, score=1.0)


class MediaPipeTracker:
    """21 точка кисти + 468 точек лица из MediaPipe."""

    name = "mediapipe"
    fallback_reason = ""

    def __init__(
        self,
        hand_cfg: HandConfig,
        face_cfg: FaceConfig,
        model_dir: Path | str = "models",
        want_face: bool = True,
        progress=None,
    ) -> None:
        import mediapipe as mp

        self._mp = mp
        self.hand_cfg = hand_cfg
        self.face_cfg = face_cfg
        self.want_face = want_face and face_cfg.enabled
        self.api = "legacy" if hasattr(mp, "solutions") else "tasks"
        self._last_ts = 0
        if self.api == "legacy":
            self._init_legacy()
        else:
            self._init_tasks(model_dir, progress)

    # ------------------------------------------------------------------ #
    def _init_legacy(self) -> None:
        mp = self._mp
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=self.hand_cfg.max_hands,
            model_complexity=1,
            min_detection_confidence=self.hand_cfg.min_detection_confidence,
            min_tracking_confidence=self.hand_cfg.min_tracking_confidence,
        )
        self._face = None
        if self.want_face:
            self._face = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                # refine_landmarks=True → 478 точек: 468 лица + 10 радужки
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    def _init_tasks(self, model_dir: Path | str, progress) -> None:
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision
        from .models import ensure_model

        self._vision = vision
        hand_model = ensure_model(model_dir, "hand_landmarker", progress)
        self._hand_landmarker = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(hand_model)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=self.hand_cfg.max_hands,
                min_hand_detection_confidence=self.hand_cfg.min_detection_confidence,
                min_hand_presence_confidence=self.hand_cfg.min_tracking_confidence,
                min_tracking_confidence=self.hand_cfg.min_tracking_confidence,
            )
        )
        self._face_landmarker = None
        if self.want_face:
            face_model = ensure_model(model_dir, "face_landmarker", progress)
            self._face_landmarker = vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(face_model)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_faces=1,
                    output_face_blendshapes=False,
                )
            )

    # ------------------------------------------------------------------ #
    def _ts(self, ts_ms: int) -> int:
        # MediaPipe требует строго возрастающие метки времени.
        self._last_ts = max(int(ts_ms), self._last_ts + 1)
        return self._last_ts

    def process(self, frame_bgr: np.ndarray, ts_ms: int) -> FrameResult:
        rgb = frame_bgr[:, :, ::-1]
        ts = self._ts(ts_ms)

        if self.api == "legacy":
            return self._process_legacy(rgb)
        return self._process_tasks(rgb, ts)

    # ------------------------------------------------------------------ #
    def _process_legacy(self, rgb: np.ndarray) -> FrameResult:
        rgb = np.ascontiguousarray(rgb)
        res = FrameResult(backend="mediapipe/legacy")
        hands_res = self._hands.process(rgb)
        if hands_res.multi_hand_landmarks:
            for i, hlm in enumerate(hands_res.multi_hand_landmarks[: self.hand_cfg.max_hands]):
                label = "Right"
                try:
                    label = hands_res.multi_handedness[i].classification[0].label
                except Exception:
                    pass
                res.hands.append(_to_hand(hlm.landmark, label))
        if self._face is not None:
            face_res = self._face.process(rgb)
            if face_res.multi_face_landmarks:
                pts = np.array(
                    [[lm.x, lm.y, lm.z] for lm in face_res.multi_face_landmarks[0].landmark],
                    dtype=np.float32,
                )
                res.face = Face(pts)
        return res

    def _process_tasks(self, rgb: np.ndarray, ts: int) -> FrameResult:
        mp = self._mp
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = FrameResult(backend="mediapipe/tasks")
        hand_res = self._hand_landmarker.detect_for_video(image, ts)
        for i, lms in enumerate(hand_res.hand_landmarks or []):
            label = "Right"
            try:
                cats = hand_res.handedness[i]
                label = cats[0].category_name or cats[0].display_name or "Right"
            except Exception:
                pass
            res.hands.append(_to_hand(lms, label))
        if self._face_landmarker is not None:
            face_res = self._face_landmarker.detect_for_video(image, ts)
            if face_res.face_landmarks:
                pts = np.array(
                    [[lm.x, lm.y, lm.z] for lm in face_res.face_landmarks[0]], dtype=np.float32
                )
                res.face = Face(pts)
        return res

    def close(self) -> None:
        for name in ("_hands", "_face", "_hand_landmarker", "_face_landmarker"):
            obj = getattr(self, name, None)
            if obj is not None and hasattr(obj, "close"):
                try:
                    obj.close()
                except Exception:
                    pass


class NullTracker:
    """Заглушка: точек нет (например, режим без камеры)."""

    name = "none"
    fallback_reason = ""

    def process(self, frame_bgr: np.ndarray, ts_ms: int) -> FrameResult:
        return FrameResult(backend="none")

    def close(self) -> None:
        pass


def explain_mediapipe_failure(exc: BaseException, model_dir: Path | str) -> str:
    """Короткое объяснение, почему нейросеть не поднялась (показываем на экране)."""
    from .models import ModelError

    name = type(exc).__name__
    if isinstance(exc, ModelError):
        return ("нет файлов моделей рядом с программой — распакуйте архив "
                "AirMouse целиком в папку и запустите EXE оттуда")
    text = str(exc)
    if isinstance(exc, ImportError) or "DLL" in text or "libEGL" in text or "shared" in text.lower():
        return f"не загрузилась библиотека MediaPipe ({name}: {text[:110]})"
    if "No module named" in text:
        return f"нет пакета MediaPipe ({text[:110]})"
    return f"{name}: {text[:140]}"


def create_tracker(
    backend: str,
    hand_cfg: HandConfig,
    face_cfg: FaceConfig,
    model_dir: Path | str = "models",
    progress=None,
) -> Tracker:
    backend = (backend or "auto").lower()
    if backend in ("none", "off", "no"):
        return NullTracker()
    reason = ""
    if backend in ("auto", "mediapipe"):
        try:
            return MediaPipeTracker(hand_cfg, face_cfg, model_dir, progress=progress)
        except Exception as exc:
            if backend == "mediapipe":
                raise
            # auto: нейросеть не поднялась — работаем на классическом CV,
            # но запоминаем причину, чтобы показать её в окне и в журнале.
            reason = explain_mediapipe_failure(exc, model_dir)
            log.warning("MediaPipe недоступен: %s", reason)
            if progress:
                progress(f"Нейросеть MediaPipe недоступна ({reason}) — включён классический режим.")
    from .classical import ClassicalTracker

    tracker = ClassicalTracker(hand_cfg=hand_cfg)
    tracker.fallback_reason = reason or "включён вручную (--backend classical)"
    return tracker
