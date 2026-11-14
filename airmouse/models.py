"""Модели MediaPipe Tasks API: скачивание .task-файлов.

MediaPipe >= 1.0 больше не содержит встроенных моделей (в версиях 0.10.x
они лежали внутри пакета). Поэтому при первом запуске модель скачивается
один раз в папку ``models/`` — дальше всё работает офлайн.

Если сети нет, а на компьютере стоит mediapipe 0.10.x — используется
встроенная модель, скачивать ничего не нужно.
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Callable, Optional

MODEL_URLS = {
    "hand_landmarker": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
    "face_landmarker": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
}
MODEL_SIZES = {"hand_landmarker": 7_800_000, "face_landmarker": 3_700_000}


class ModelError(RuntimeError):
    pass


def model_path(model_dir: Path | str, name: str) -> Path:
    return Path(model_dir) / f"{name}.task"


def ensure_model(
    model_dir: Path | str,
    name: str,
    progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """Возвращает путь к модели, скачивая её при необходимости."""
    if name not in MODEL_URLS:
        raise ModelError(f"неизвестная модель: {name}")
    path = model_path(model_dir, name)
    if path.exists() and path.stat().st_size > 100_000:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    url = MODEL_URLS[name]
    if progress:
        progress(f"Скачиваю модель {name} (~{MODEL_SIZES.get(name, 0) // 1_000_000} МБ): {url}")
    tmp = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:  # сеть, прокси, 403 и т.п.
        if tmp.exists():
            tmp.unlink()
        raise ModelError(
            f"Не удалось скачать модель {name}: {exc}\n"
            "Варианты: 1) подключить интернет и повторить; 2) скачать файл "
            f"вручную по ссылке {url} и положить в {path}; 3) установить "
            "mediapipe 0.10.x — там модели встроены."
        ) from exc
    tmp.replace(path)
    if progress:
        progress(f"Готово: {path} ({path.stat().st_size / 1e6:.1f} МБ)")
    return path


def download_all(model_dir: Path | str, progress: Optional[Callable[[str], None]] = None) -> dict:
    return {name: ensure_model(model_dir, name, progress) for name in MODEL_URLS}
