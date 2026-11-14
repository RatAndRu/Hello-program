@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title AirMouse — установка

echo ============================================
echo  AirMouse: установка
echo  Нужен Python 3.10-3.12 и веб-камера
echo ============================================
echo.

set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY (py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11")
if not defined PY (py -3.10 -c "import sys" >nul 2>nul && set "PY=py -3.10")
if not defined PY (python -c "import sys" >nul 2>nul && set "PY=python")

if not defined PY (
    echo [ОШИБКА] Python не найден.
    echo Установите Python 3.12: https://www.python.org/downloads/windows/
    echo При установке отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Использую: !PY!
!PY! -c "import sys; print('  версия Python:', sys.version.split()[0])"
!PY! -c "import sys; sys.exit(0 if sys.version_info[:2] < (3,13) else 1)"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Python 3.13+ пока не поддерживается MediaPipe.
    echo Поставьте Python 3.12 и запустите install.bat снова.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение .venv ...
    !PY! -m venv .venv
    if errorlevel 1 goto :err
)

set "PY=.venv\Scripts\python.exe"
echo Обновляю pip ...
%PY% -m pip install --upgrade pip --quiet
echo Ставлю зависимости (2-5 минут, качается ~150 МБ) ...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :err

echo.
echo Проверяю окружение и камеру ...
%PY% -m airmouse doctor

echo.
echo ============================================
echo  Готово!
echo    run.bat             — запуск с окном
echo    run-background.bat  — работа в фоне (трей)
echo    build-exe.bat       — собрать AirMouse.exe
echo ============================================
pause
exit /b 0

:err
echo.
echo [ОШИБКА] Установка не завершена, читайте сообщения выше.
echo Полезное: %PY% -m pip install -r requirements.txt
pause
exit /b 1
