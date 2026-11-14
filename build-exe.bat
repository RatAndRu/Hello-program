@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AirMouse — сборка EXE

if not exist ".venv\Scripts\python.exe" (
    echo Сначала запустите install.bat
    pause
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"

echo Ставлю PyInstaller ...
%PY% -m pip install --upgrade pyinstaller --quiet
if errorlevel 1 goto :err

echo Собираю AirMouse.exe (5-10 минут, ~300 МБ в dist\AirMouse) ...
%PY% -m PyInstaller --noconfirm --clean packaging\airmouse.spec
if errorlevel 1 goto :err

if exist "models\hand_landmarker.task" (
    if not exist "dist\AirMouse\models" mkdir "dist\AirMouse\models"
    copy /y "models\*.task" "dist\AirMouse\models\" >nul
    echo Модели скопированы рядом с EXE.
)

copy /y README.md "dist\AirMouse\" >nul
if exist "КАК-ЗАПУСТИТЬ.txt" copy /y "КАК-ЗАПУСТИТЬ.txt" "dist\AirMouse\" >nul

echo.
echo Готово: dist\AirMouse\AirMouse.exe
echo Папку dist\AirMouse можно целиком скопировать на другой компьютер.
pause
exit /b 0

:err
echo.
echo [ОШИБКА] Сборка не удалась.
pause
exit /b 1
