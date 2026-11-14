# -*- mode: python ; coding: utf-8 -*-
"""Сборка Windows-приложения AirMouse (PyInstaller).

Запуск:  build-exe.bat   или   pyinstaller --noconfirm packaging/airmouse.spec
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# MediaPipe тянет за собой бинарники, tflite-модули и data-файлы — только
# collect_all собирает это корректно.
for package in ("mediapipe", "pystray"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # пакет не установлен — не повод падать
        print(f"[spec] {package}: {exc}")

# Модели .task можно положить внутрь сборки (тогда они всегда под рукой),
# но по умолчанию не кладём: build-exe.bat копирует их рядом с EXE.
models_dir = os.path.abspath("models")
if os.path.isdir(models_dir) and "--with-models" in sys.argv:
    for name in os.listdir(models_dir):
        if name.endswith(".task"):
            datas.append((os.path.join(models_dir, name), "models"))

a = Analysis(
    ["packaging/airmouse_entry.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "tkinter", "tests"],
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AirMouse",
)
