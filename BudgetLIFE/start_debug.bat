@echo off
rem ============================================================================
rem  start_debug.bat - zagruzka S KONSOLYU (po standartu SPECIALS)
rem
rem  Obychnyy zapusk: start.vbs (bez konsoli).
rem  Zdes: vidny vse oshibki i logi, okno ne ischezaet.
rem
rem  Ispolzovanie:
rem     start_debug.bat          - server na PowerShell (ne nuzhen Node.js)
rem     start_debug.bat node     - server na Node.js (esli on ustanovlen)
rem     start_debug.bat dev      - rezhim razrabotki Vite (nuzhen Node.js)
rem ============================================================================
cd /d "%~dp0"
title BudgetLIFE - debug

echo [1/2] Checking PowerShell...
where powershell >nul 2>nul
if errorlevel 1 (
    echo.
    echo PowerShell NOT FOUND. This Windows is too old or broken.
    pause
    exit /b 1
)

echo [2/2] Starting server (Ctrl+C to stop)...
echo ---------------------------------------------------------------
if /i "%1"=="dev" (
    npm run dev
) else if /i "%1"=="node" (
    node server.js
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File server.ps1
)
set EXITCODE=%ERRORLEVEL%
echo ---------------------------------------------------------------
echo Server finished. Exit code: %EXITCODE%
echo Logs: logs\server.log  and  logs\launch.log
pause
exit /b %EXITCODE%
