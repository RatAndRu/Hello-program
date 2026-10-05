@echo off
rem ==========================================================================
rem  start_netdoctor.bat — запуск NET DOCTOR на Windows (двойной клик).
rem --------------------------------------------------------------------------
rem  Что делает:
rem    1. включает UTF-8, чтобы русские буквы и рамки выводились ровно;
rem    2. ищет Python (py / python / python3);
rem    3. запускает net_doctor.py.
rem
rem  Можно передать любые ключи, например:
rem      start_netdoctor.bat --check-port 5000 --phone 192.168.0.61
rem      start_netdoctor.bat --fix
rem      start_netdoctor.bat --no-server
rem ==========================================================================
chcp 65001 >nul
title NET DOCTOR — почему телефон не видит мой Python-сервер
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  where python3 >nul 2>nul
  if not errorlevel 1 set "PY=python3"
)

if not defined PY (
  echo.
  echo Python не найден на этом компьютере.
  echo.
  echo 1^) Скачайте Python 3 с сайта https://www.python.org/downloads/
  echo 2^) При установке поставьте галочку "Add python.exe to PATH"
  echo 3^) Запустите этот файл снова.
  echo.
  pause >nul
  exit /b 1
)

echo Запускаю: %PY% net_doctor.py %*
echo.
%PY% net_doctor.py %*

echo.
echo ---------------------------------------------------------------------------
echo NET DOCTOR завершил работу. Отчёт лежит рядом: netdoctor_report.txt
echo Нажмите любую клавишу, чтобы закрыть окно...
pause >nul
