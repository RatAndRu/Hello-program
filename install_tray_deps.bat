@echo off
chcp 65001 >nul
echo Установка зависимостей для трея: pystray pillow
echo.
py -m pip install pystray pillow
if errorlevel 1 (
  echo.
  echo Не получилось через py. Пробую python...
  python -m pip install pystray pillow
)
echo.
echo Готово. Если ошибок нет, можно запускать start_tray_server.vbs
pause
