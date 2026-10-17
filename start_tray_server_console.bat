@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tray_server.py
pause
