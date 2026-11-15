# -*- mode: python ; coding: utf-8 -*-
"""Сборка Windows-приложения AirMouse (PyInstaller).

Запуск:  build-exe.bat   или   pyinstaller --noconfirm packaging/airmouse.spec
"""
import os
import sys

sys.setrecursionlimit(20000)  # mediapipe/hooks иногда уходят в глубокую рекурсию

from PyInstaller.utils.hooks import collect_all

# Пути в .spec считаются от каталога самого spec-файла, поэтому все пути
# к проекту строим явно от корня репозитория.
try:
    SPEC_DIR = os.path.abspath(SPECPATH)          # подставляет PyInstaller
except NameError:                                 # pragma: no cover
    SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SPEC_DIR)

datas, binaries, hiddenimports = [], [], []

# MediaPipe тянет за собой бинарники, tflite-модули и data-файлы — только
# collect_all собирает это корректно.
for package in ("mediapipe", "pystray", "cv2"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # пакет не установлен — не повод падать
        print(f"[spec] {package}: {exc}")

# Чистка мусора: тесты, стабы и байткод занимают десятки мегабайт и не нужны
# работающему приложению.
def _is_junk(dest: str) -> bool:
    low = dest.replace("\\", "/").lower()
    if "/test/" in low or low.startswith("test/") or "/tests/" in low:
        return True
    if "/__pycache__/" in low or "/.dist-info/" in low:
        return True
    return low.endswith((".pyi", ".pxd", ".pyx", ".c", ".h", ".hpp", ".chm"))


_cut = 0
for _list in (datas, binaries):
    keep = [item for item in _list if not _is_junk(item[0])]
    _cut += len(_list) - len(keep)
    _list[:] = keep
print(f"[spec] отброшено лишних файлов: {_cut}")

# Модели .task можно положить внутрь сборки (тогда они всегда под рукой),
# но по умолчанию не кладём: build-exe.bat копирует их рядом с EXE.
models_dir = os.path.join(ROOT, "models")
if os.path.isdir(models_dir) and "--with-models" in sys.argv:
    for name in os.listdir(models_dir):
        if name.endswith(".task"):
            datas.append((os.path.join(models_dir, name), "models"))

a = Analysis(
    [os.path.join(SPEC_DIR, "airmouse_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",   # mediapipe тянет его только для drawing_utils
        "scipy",
        "pandas",
        "tkinter",
        "tests",
        "IPython",
        "PyQt5",
        "PySide2",
        "PySide6",
        "pytest",
        "pydoc_data",
        "lib2to3",
        "doctest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AirMouse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # окна консоли нет; об ошибках сообщает MessageBox
    disable_windowed_traceback=False,
    icon=None,
)

# Вторая сборка — с консолью: если оконная версия почему-то не стартует,
# AirMouse-debug.exe покажет traceback вместо тихого закрытия.
exe_debug = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AirMouse-debug",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    exe_debug,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AirMouse",
)
