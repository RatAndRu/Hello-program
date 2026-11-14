"""Захват кадров: отдельный поток, чтобы камера не тормозила распознавание."""

from __future__ import annotations

import platform
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import CameraConfig


def _resolve_backend(name: str) -> int:
    name = (name or "auto").lower()
    if name == "auto":
        if platform.system() == "Windows":
            return cv2.CAP_DSHOW  # быстрее открывается и стабильнее
        return cv2.CAP_ANY
    return {
        "dshow": cv2.CAP_DSHOW,
        "msmf": cv2.CAP_MSMF,
        "v4l2": cv2.CAP_V4L2,
        "any": cv2.CAP_ANY,
        "gstreamer": cv2.CAP_GSTREAMER,
    }.get(name, cv2.CAP_ANY)


class Camera:
    """Синхронная обёртка над cv2.VideoCapture (камера или видеофайл)."""

    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self.cap: Optional[cv2.VideoCapture] = None
        self.source_name = ""
        self.ended = False
        self.pos_ms = 0.0

    def open(self) -> None:
        if self.cfg.video_file:
            self.cap = cv2.VideoCapture(self.cfg.video_file)
            self.source_name = self.cfg.video_file
        else:
            self.cap = cv2.VideoCapture(self.cfg.index, _resolve_backend(self.cfg.backend))
            self.source_name = f"камера #{self.cfg.index}"
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
            try:  # меньшая задержка там, где поддерживается
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Не удалось открыть {self.source_name}. "
                "Проверьте, что камера не занята другим приложением "
                "и разрешения на камеру включены."
            )

    def read(self) -> Optional[np.ndarray]:
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            if self.cfg.video_file:
                self.ended = True
            return None
        if self.cfg.mirror and not self.cfg.video_file:
            frame = cv2.flip(frame, 1)
        if self.cfg.video_file:
            self.pos_ms = float(self.cap.get(cv2.CAP_PROP_POS_MSEC))
        return frame

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @property
    def resolution(self) -> Tuple[int, int]:
        if self.cap is None:
            return self.cfg.width, self.cfg.height
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.cfg.width
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.cfg.height
        return w, h


class ThreadedCamera:
    """Читает кадры в фоне и всегда отдаёт самый свежий (без накопления лага)."""

    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self.camera = Camera(cfg)
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._stamp = 0.0
        self._seq = 0
        self._running = False
        self._sync = False
        self._thread: Optional[threading.Thread] = None
        self.fps = 0.0
        self.errors = 0
        self._ended = False

    def start(self) -> "ThreadedCamera":
        self.camera.open()
        if self.cfg.video_file:
            # Видеофайл читаем синхронно: никаких потерянных кадров —
            # так проще отлаживать и повторять одну и ту же запись.
            self._sync = True
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        last = time.monotonic()
        while self._running:
            frame = self.camera.read()
            if frame is None:
                if self.camera.ended:
                    self._ended = True
                    break
                self.errors += 1
                time.sleep(0.02)
                if self.errors > 200:
                    break
                continue
            now = time.monotonic()
            dt = now - last
            last = now
            if dt > 0:
                self.fps = 0.85 * self.fps + 0.15 * (1.0 / dt) if self.fps else 1.0 / dt
            with self._lock:
                self._frame = frame
                self._stamp = now
                self._seq += 1
            time.sleep(max(0.0, (1.0 / max(self.cfg.fps, 1)) - dt))

    def read(self) -> Tuple[Optional[np.ndarray], float, int]:
        if self._sync:
            frame = self.camera.read()
            self._seq += 1
            # для видеофайла «время» — это время самого видео, а не настенных часов
            return frame, self.camera.pos_ms / 1000.0, self._seq
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            return frame, self._stamp, self._seq

    @property
    def ended(self) -> bool:
        """Закончился ли источник (для видеофайла — дочитан до конца)."""
        return self._ended or (self._sync and self.camera.ended)

    @property
    def alive(self) -> bool:
        if self._sync:
            return not self.camera.ended
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self.camera.release()
