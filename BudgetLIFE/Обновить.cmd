@echo off
title BudgetLIFE - update
cd /d "%~dp0"

echo.
echo   BudgetLIFE ^| update
echo   ---------------------
echo   (Node.js is needed only to REBUILD the app.
echo    Normal launch via start.vbs works without it.)
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo   [!] Node.js not found. Install Node.js 20+ from https://nodejs.org
  echo       and run this file again.
  goto :end
)

if not exist "node_modules" (
  echo   [1/3] Installing dependencies...
  call npm install --no-audit --no-fund
) else (
  echo   [1/3] Dependencies OK.
)

echo   [2/3] Building application...
call npm run build
if errorlevel 1 (
  echo.
  echo   [!] Build failed. See errors above.
  goto :end
)

echo   [3/3] Done.
echo   Now run start.vbs or the desktop shortcut.

:end
echo.
pause
