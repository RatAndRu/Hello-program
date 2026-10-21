"""Пути данных приложения (проекты, экспорт, текстуры, импорт)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    """Папка данных: %APPDATA%\\Forma3D или ~/.forma3d (настраивается FORMA_DATA)."""
    custom = os.environ.get("FORMA_DATA")
    if custom:
        path = Path(custom).expanduser()
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / "Forma3D"
    else:
        path = Path.home() / ".forma3d"
    for sub in ("projects", "exports", "renders", "prompts", "textures", "imports"):
        try:
            (path / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return path


def safe_name(name: str, fallback: str = "file") -> str:
    keep = "".join(c for c in (name or "") if c.isalnum() or c in "-_.() " )
    keep = keep.strip().replace(" ", "_")
    return keep or fallback
