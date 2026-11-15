#!/usr/bin/env python3
"""Собирает ZIP-архив AirMouse для передачи на другой компьютер.

    python packaging/make_zip.py            -> release/AirMouse-<версия>.zip

В архив попадает только то, что нужно для работы: код, скрипты запуска,
документация и шаблоны. Локальные данные (config/, logs/, profiles/,
output/, скачанные модели) не включаются.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from airmouse import __version__  # noqa: E402

INCLUDE_FILES = [
    "README.md",
    "КАК-ЗАПУСТИТЬ.txt",
    "requirements.txt",
    "pyproject.toml",
    "run_airmouse.py",
    "run.bat",
    "run-background.bat",
    "install.bat",
    "build-exe.bat",
    "run.sh",
    "models/README.txt",
    "packaging/airmouse.spec",
    "packaging/airmouse_entry.py",
    "docs/airmouse-preview.png",
    "docs/overlay-body.png",
    "docs/overlay-body-waist.png",
    "docs/overlay-settings-body.png",
    "docs/overlay-settings-window.png",
    "docs/overlay-hand-predicted.png",
    "docs/overlay-face-mouth.png",
    "docs/overlay-face-hint.png",
    "docs/overlay-body-tpose.png",
    "docs/overlay-body-boxing.png",
    "docs/overlay-body-head-arms.png",
]
INCLUDE_DIRS = ["airmouse", "tests"]
SKIP_SUFFIXES = {".pyc", ".pyo", ".task", ".part", ".avi", ".mp4", ".gif", ".npz"}
CRLF_SUFFIXES = {".bat", ".cmd", ".txt"}


def iter_files():
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.exists():
            yield path
    for name in INCLUDE_DIRS:
        base = ROOT / name
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix in SKIP_SUFFIXES:
                continue
            yield path


def main() -> int:
    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"AirMouse-{__version__}.zip"
    prefix = f"AirMouse-{__version__}"
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in iter_files():
            rel = path.relative_to(ROOT)
            data = path.read_bytes()
            if path.suffix.lower() in CRLF_SUFFIXES or path.suffix.lower() in {".py", ".md"}:
                # Windows-дружественные переводы строк для скриптов и текстов
                text = data.decode("utf-8").replace("\r\n", "\n")
                if path.suffix.lower() in CRLF_SUFFIXES:
                    text = text.replace("\n", "\r\n")
                data = text.encode("utf-8")
            zf.writestr(f"{prefix}/{rel.as_posix()}", data)
            count += 1
    size = target.stat().st_size / 1024
    print(f"Готово: {target} ({count} файлов, {size:.0f} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
