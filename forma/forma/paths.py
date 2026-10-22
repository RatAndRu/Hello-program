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


def downloads_dir() -> Path:
    """Папка «Загрузки» пользователя — сюда сохраняются готовые файлы.

    Windows умеет переименовать папку (например, «Загрузки»), поэтому сначала
    спрашиваем систему о настоящем пути, а если не вышло — пробуем обычные имена.
    """
    custom = os.environ.get("FORMA_DOWNLOADS")
    if custom:
        path = Path(custom).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            return user_data_dir() / "exports"
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            guid = _GUID(0x374DE290, 0x123F, 0x4565,
                         (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                candidates.append(Path(out.value))
                ctypes.windll.ole32.CoTaskMemFree(out)
        except Exception:
            pass
    home = Path.home()
    candidates += [home / "Downloads", home / "Загрузки", home / "Завантаження",
                   home / "Documents" / "Downloads"]
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            if os.access(cand, os.W_OK):
                return cand
        except OSError:
            continue
    return user_data_dir() / "exports"


def safe_name(name: str, fallback: str = "file") -> str:
    keep = "".join(c for c in (name or "") if c.isalnum() or c in "-_.() " )
    keep = keep.strip().replace(" ", "_")
    return keep or fallback
