@echo off
rem AirMouse: работа в фоне, иконка в системном трее (консоль не нужна)
cd /d "%~dp0"
start "" pythonw run_airmouse.py --no-window --tray
