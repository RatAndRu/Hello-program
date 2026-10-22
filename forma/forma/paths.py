"""Пути данных приложения: всё лежит рядом с exe, без папок User/AppData.

Правило простое и предсказуемое:

* запущен собранный EXE — данные лежат в той же папке, где Forma3D.exe:
  ``projects``, ``exports``, ``renders``, ``prompts``, ``textures``, ``imports``;
* запуск из исходников — та же схема, только рядом с корнем проекта
  (``forma/forma-data``), чтобы не мусорить в домашней папке;
* переменная ``FORMA_DATA`` переопределяет корень (нужно тестам и переносу).

Старые папки ``%APPDATA%\\Forma3D`` и ``~/.forma3d`` больше не используются:
``migrate_legacy()`` один раз переносит из них файлы и удаляет пустые папки.
Готовые файлы по-прежнему копируются в «Загрузки» — этого просил пользователь.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SUBDIRS = ("projects", "exports", "renders", "prompts", "textures", "imports")
LEGACY_DIRNAME = "Forma3D"


def is_frozen() -> bool:
    """Приложение собрано PyInstaller (запущено как .exe)?"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Папка приложения: рядом с exe (или корень исходников при разработке)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # форма/форма/paths.py → форма/paths.py → корень пакета forma
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Корень данных: папка приложения, если писать в неё можно."""
    custom = os.environ.get("FORMA_DATA")
    if custom:
        return Path(custom).expanduser().resolve()
    # при разработке — подпапка forma-data, чтобы не мусорить файлами проекта
    base = app_dir() if is_frozen() else app_dir() / "forma-data"
    if _writable(base):
        return base
    # exe лежит в защищённой папке (Program Files) — берём рабочую папку,
    # но не домашнюю: пользователь просил никаких User/AppData.
    cwd = Path.cwd().resolve()
    if _writable(cwd):
        return cwd
    import tempfile

    return Path(tempfile.gettempdir()) / "Forma3D"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".forma_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def ensure_dirs(root: Path | None = None) -> Path:
    """Создаёт рабочие папки рядом с exe и возвращает корень данных."""
    path = Path(root) if root is not None else data_root()
    for sub in SUBDIRS:
        try:
            (path / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return path


def user_data_dir() -> Path:
    """Корень данных приложения (рядом с exe): projects/exports/renders/…"""
    return ensure_dirs()


def subdir(name: str) -> Path:
    """Путь к рабочей подпапке (создаётся по требованию)."""
    path = user_data_dir() / name
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def legacy_dirs() -> list[Path]:
    """Старые места хранения данных, от которых нужно избавиться."""
    out: list[Path] = []
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            out.append(Path(base) / LEGACY_DIRNAME)
    out.append(Path.home() / ".forma3d")
    # случай, когда exe раньше лежал в подпапке Forma3D рядом с данными
    out.append(app_dir() / LEGACY_DIRNAME)
    seen: set[Path] = set()
    result = []
    for item in out:
        try:
            key = item.resolve()
        except OSError:
            key = item
        if key in seen:
            continue
        seen.add(key)
        if item.exists() and item.is_dir():
            result.append(item)
    return result


def migrate_legacy(root: Path | None = None, legacy: list[Path] | None = None) -> dict:
    """Переносит данные из старых папок и удаляет их. Ничего не теряет.

    Файлы переносятся только если в новом месте такого имени ещё нет;
    совпадающие по имени файлы остаются в старой папке, а она не удаляется,
    чтобы пользователь точно ничего не потерял.
    """
    if os.environ.get("FORMA_DATA"):
        return {"moved": 0, "left": [], "removed": []}
    target = ensure_dirs(root)
    moved = 0
    left: list[str] = []
    removed: list[str] = []
    for legacy in (legacy_dirs() if legacy is None else legacy):
        try:
            legacy_res = legacy.resolve()
        except OSError:
            legacy_res = legacy
        if not legacy.is_dir() or legacy_res == target.resolve():
            continue
        problems = False
        for item in sorted(legacy.rglob("*")):
            if item.is_dir():
                continue
            rel = item.relative_to(legacy)
            dest = target / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    problems = True
                    left.append(str(item))
                    continue
                shutil.move(str(item), str(dest))
                moved += 1
            except OSError:
                problems = True
                left.append(str(item))
        if problems:
            continue
        # удаляем только опустевшие папки — файлы пользователя не трогаем
        try:
            for sub in sorted((p for p in legacy.rglob("*") if p.is_dir()),
                              key=lambda p: len(p.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    problems = True
            legacy.rmdir()
            if not problems:
                removed.append(str(legacy))
        except OSError:
            continue
    return {"moved": moved, "left": left, "removed": removed}


def downloads_dir() -> Path:
    """Папка «Загрузки» пользователя — сюда копируются готовые файлы.

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
            return subdir("exports")
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
    return subdir("exports")


def safe_name(name: str, fallback: str = "file") -> str:
    keep = "".join(c for c in (name or "") if c.isalnum() or c in "-_.() ")
    keep = keep.strip().replace(" ", "_")
    return keep or fallback


def describe() -> dict:
    """Краткая карта папок — для справки и диагностики."""
    root = user_data_dir()
    return {
        "root": str(root),
        "portable": not os.environ.get("FORMA_DATA"),
        "frozen": is_frozen(),
        **{name: str(root / name) for name in SUBDIRS},
        "downloads": str(downloads_dir()),
        "legacy": [str(p) for p in legacy_dirs()],
    }
