@echo off
rem ==========================================================================
rem  start_netdoctor.bat - RESERVE launcher for NET DOCTOR (English on purpose)
rem --------------------------------------------------------------------------
rem  The MAIN way to start is start_netdoctor.vbs - double-click that file.
rem  This .bat is a fallback (for example, if .vbs is blocked by policy).
rem
rem  It is written in PURE ASCII with CRLF line endings on purpose:
rem    * no Cyrillic  -> the cmd.exe codepage cannot mangle the text;
rem    * no chcp call -> changing the codepage in the middle of a .bat makes
rem      cmd.exe re-read the file at a wrong offset and execute FRAGMENTS of
rem      lines (that is where errors like "'on' is not recognized as an
rem      internal or external command" came from);
rem    * CRLF only    -> cmd.exe never sees lone LF line endings.
rem  The program itself switches the console to UTF-8 (see setup_console in
rem  net_doctor.py), so Russian output is fine without any chcp here.
rem
rem  Usage (same keys as net_doctor.py):
rem      start_netdoctor.bat --check-port 5000 --phone 192.168.0.61
rem      start_netdoctor.bat --fix
rem ==========================================================================

setlocal
title NET DOCTOR - local network server access diagnostics
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

if not defined PY goto nopython
if not exist "net_doctor.py" goto nofile

echo Running: %PY% net_doctor.py %*
echo.
call %PY% net_doctor.py %*
set "RC=%ERRORLEVEL%"

echo.
echo ---------------------------------------------------------------------------
if "%RC%"=="1" (
  echo NET DOCTOR stopped with an internal error ^(exit code 1^).
) else (
  echo NET DOCTOR finished. Report: netdoctor_report.txt
)
echo Press any key to close this window...
pause >nul
exit /b %RC%

:nopython
echo.
echo Python was not found on this computer.
echo.
echo 1^) Install Python 3: https://www.python.org/downloads/
echo 2^) Tick "Add python.exe to PATH" during setup
echo 3^) Run start_netdoctor.vbs ^(the main launcher^) again
echo.
pause >nul
exit /b 1

:nofile
echo.
echo net_doctor.py was not found next to this file.
echo Download the whole netdiagn folder from the repository.
echo.
pause >nul
exit /b 1
