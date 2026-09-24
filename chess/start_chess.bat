@echo off
rem ==========================================================================
rem  start_chess.bat — резервный запуск шахмат (Windows).
rem  Нужен, если start.vbs по какой-то причине не сработал.
rem ==========================================================================
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 chess.py --console
) else (
  python chess.py --console
)

echo.
echo Партия окончена. Нажмите любую клавишу, чтобы закрыть окно...
pause >nul
