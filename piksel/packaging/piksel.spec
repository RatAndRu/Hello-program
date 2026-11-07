# -*- mode: python ; coding: utf-8 -*-
"""Сборка ПИКСЕЛЬ в один exe — форк forma/packaging/forma.spec"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
datas=[]; binaries=[]; hiddenimports=[]
for pkg in ("clr_loader","pythonnet"):
    try:
        d,b,h=collect_all(pkg)
        datas+=d; binaries+=b; hiddenimports+=h
    except: pass
try: datas+=collect_data_files("webview")
except: pass
hiddenimports+=["webview","webview.platforms.winforms","webview.platforms.edgechromium","numpy","Pillow"]

datas+=[(str(ROOT/"web"),"web"),(str(ROOT/"examples"),"examples")]
icon_path=ROOT/"packaging"/"icon.ico"
version_file=ROOT/"packaging"/"version_info.txt"

a=Analysis(
    [str(ROOT/"packaging"/"entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[], excludes=["scipy","skimage","networkx","shapely","tkinter","PyQt5","PyQt6","PySide2","PySide6","wx","qtpy","OpenGL","IPython","pytest"],
    noarchive=False)
pyz=PYZ(a.pure, a.zipped_data)
exe=EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, name='Piksel.exe', console=False, icon=str(icon_path) if icon_path.exists() else None)
