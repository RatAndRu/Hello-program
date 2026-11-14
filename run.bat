@echo off
rem AirMouse: запуск управления (окно предпросмотра)
cd /d "%~dp0"
python run_airmouse.py %*
if errorlevel 1 pause
