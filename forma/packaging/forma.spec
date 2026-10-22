# -*- mode: python ; coding: utf-8 -*-
"""Сборка Форма 3D в один exe (Windows).

Вес EXE = то, что реально нужно приложению. Здесь сознательно не собираются:

* scikit-image и scipy (≈130 МБ распакованных) — поверхность извлекает свой
  мешер `forma/mesher.py` (surface nets на numpy);
* Pillow (≈22 МБ) — PNG пишет и читает свой кодек в `forma/geometry.py`;
* networkx, shapely, imageio, tifffile — приходят «в комплекте» с trimesh и
  scikit-image, приложению не нужны;
* платформы pywebview для gtk/qt/cocoa/android — на Windows работает
  WinForms + WebView2 (Edge).
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent          # .../forma
PKG = ROOT

datas = []
binaries = []
hiddenimports = []

# пакеты с бинарными модулями и данными
for package in ("manifold3d", "trimesh", "clr_loader", "pythonnet"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # пакет может отсутствовать на не-Windows
        print(f"skip {package}: {exc}")

# pywebview: только данные (js/lib) + платформы Windows
try:
    datas += collect_data_files("webview")
except Exception as exc:
    print(f"skip webview data: {exc}")
hiddenimports += ["webview", "webview.platforms.winforms", "webview.platforms.edgechromium"]

hiddenimports += [
    "forma.ops_basic", "forma.ops_curves", "forma.ops_shape", "forma.ops_scene",
    "forma.ops_sdf", "forma.render", "forma.webui", "forma.cli", "forma.checks",
    "forma.metrics", "forma.agent", "forma.geometry", "forma.values",
    "forma.mesher", "forma.sdf", "forma.anatomy", "forma.textures",
    "forma.blender", "forma.paths", "forma.ops_human", "forma.ops_studio",
    "forma.ops_io", "forma.ops_extra",
    "numpy", "manifold3d", "trimesh",
    "trimesh.exchange.gltf", "trimesh.exchange.stl", "trimesh.exchange.obj",
    "trimesh.exchange.ply", "trimesh.exchange.load",
    "trimesh.visual", "trimesh.visual.material",
]

# интерфейс и примеры кладём внутрь exe
datas += [(str(ROOT / "web"), "web"), (str(ROOT / "examples"), "examples")]
icon_png = ROOT / "packaging" / "icon_256.png"
if icon_png.exists():
    datas += [(str(icon_png), ".")]

icon_path = ROOT / "packaging" / "icon.ico"
version_file = ROOT / "packaging" / "version_info.txt"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(PKG)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # научный стек, который приложению больше не нужен
        "scipy", "skimage", "PIL", "Pillow", "imageio", "tifffile",
        "networkx", "shapely", "sympy", "numba", "llvmlite",
        "matplotlib", "pandas", "seaborn", "plotly", "bokeh",
        # GUI-тулкиты, кроме встроенного в Windows WebView2
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "qtpy", "pyglet",
        "OpenGL", "IPython", "jupyter", "notebook", "pytest", "nose",
        "setuptools", "pip", "wheel", "pydoc_data", "doctest",
        # платформы pywebview не для Windows
        "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
        "webview.platforms.android", "webview.platforms.mshtml",
    ],
    noarchive=False,
)


# Что можно выкинуть без риска: исходники, заголовки, отладочные символы и
# папки с тестами. ВАЖНО: сравниваем только окончания имён (а не «.c» внутри
# имени) — иначе под нож попадут собранные модули вида
# numpy/_core/_multiarray_umath.cp312-win_amd64.pyd.
_DROP_DIRS = ("/tests/", "/test/", "__pycache__/", "/include/")
_DROP_EXT = (".c", ".h", ".hpp", ".cpp", ".cc", ".pyx", ".pxd", ".pyi",
             ".lib", ".a", ".inc", ".def", ".exp", ".pdb", ".obj", ".o")


def _keep(entry):
    name = entry[0].replace("\\", "/").lower()
    if any(part in name for part in _DROP_DIRS):
        return False
    return not name.endswith(_DROP_EXT)


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Forma3D",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    console=os.environ.get("FORMA_CONSOLE") == "1",
    icon=str(icon_path) if icon_path.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)
