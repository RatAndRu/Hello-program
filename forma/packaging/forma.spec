# -*- mode: python ; coding: utf-8 -*-
"""Сборка Форма 3D в один exe (Windows)."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent          # .../forma
PKG = ROOT

datas = []
binaries = []
hiddenimports = []

for package in ("manifold3d", "trimesh", "webview", "clr_loader", "pythonnet",
                "skimage", "PIL"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # пакет может отсутствовать на не-Windows
        print(f"skip {package}: {exc}")

hiddenimports += collect_submodules("webview")
hiddenimports += [
    "forma.ops_basic", "forma.ops_curves", "forma.ops_shape", "forma.ops_scene",
    "forma.ops_sdf", "forma.render", "forma.webui", "forma.cli", "forma.checks",
    "forma.metrics", "forma.agent", "forma.geometry", "forma.values",
    "numpy", "manifold3d", "trimesh", "trimesh.exchange.gltf",
    "trimesh.visual", "trimesh.visual.material", "shapely", "networkx",
    "forma.sdf", "forma.anatomy", "forma.textures", "forma.blender", "forma.paths",
    "forma.ops_human", "forma.ops_studio", "forma.ops_io",
    "skimage", "skimage.measure", "skimage.measure._marching_cubes_lewiner",
    "skimage.measure._marching_cubes_lewiner_luts",
    "scipy", "scipy.ndimage", "scipy.sparse", "scipy.spatial",
    "PIL", "PIL.Image", "PIL.ImageFile", "PIL.PngImagePlugin",
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
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6", "pandas",
              "IPython", "pytest", "setuptools"],
    noarchive=False,
)
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)
