# Shadow Morse AR - локальный сервер с иконкой в трее
# Требует: pip install pystray pillow
# Запуск: pythonw tray_server.py  или start_tray_server.vbs

import os
import sys
import socket
import threading
import subprocess
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = 8080
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def kill_previous_python_http_servers_on_port(port=PORT):
    """Закрывает только старые python -m http.server на указанном порту.
    Не трогает все Python-процессы подряд.
    Windows-only, на других ОС ничего не делает.
    """
    if os.name != "nt":
        return
    ps = rf'''
$port = {port}
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {{
    $pidNum = $c.OwningProcess
    if ($pidNum -eq $PID) {{ continue }}
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pidNum" -ErrorAction SilentlyContinue
    if ($null -ne $p) {{
        $cmd = [string]$p.CommandLine
        $name = [string]$p.Name
        if (($name -match 'python|py\.exe') -and ($cmd -match 'http\.server') -and ($cmd -match '{port}')) {{
            try {{ Invoke-CimMethod -InputObject $p -MethodName Terminate | Out-Null }} catch {{}}
        }}
    }}
}}
'''
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def log_message(self, fmt, *args):
        # Не спамим консоль/лог.
        pass


def start_http_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def make_icon_image():
    from PIL import Image, ImageDraw
    size = 64
    im = Image.new("RGBA", (size, size), (5, 7, 17, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 8, 56, 56), fill=(22, 28, 58, 255), outline=(120, 220, 255, 255), width=2)
    d.ellipse((22, 24, 29, 30), fill=(255, 230, 120, 255))
    d.ellipse((35, 24, 42, 30), fill=(255, 230, 120, 255))
    d.arc((20, 27, 44, 49), 20, 160, fill=(135, 235, 255, 255), width=2)
    d.ellipse((45, 12, 53, 20), fill=(255, 70, 85, 255))
    return im


def main():
    kill_previous_python_http_servers_on_port(PORT)

    try:
        server = start_http_server()
    except OSError as e:
        # Если порт занят не старым http.server, показываем ошибку.
        print(f"Не удалось запустить сервер на порту {PORT}: {e}")
        input("Нажми Enter для выхода...")
        return

    local_url = f"http://localhost:{PORT}"
    lan_url = f"http://{get_lan_ip()}:{PORT}"

    try:
        import pystray
        from pystray import MenuItem as item
    except Exception:
        print("Сервер запущен, но pystray не установлен, поэтому трея нет.")
        print(f"Локально: {local_url}")
        print(f"По Wi-Fi: {lan_url}")
        print("Установи зависимости: pip install pystray pillow")
        print("Для остановки нажми Ctrl+C.")
        try:
            while True:
                threading.Event().wait(3600)
        except KeyboardInterrupt:
            server.shutdown()
        return

    def open_local(icon=None, menu_item=None):
        webbrowser.open(local_url)

    def open_lan(icon=None, menu_item=None):
        webbrowser.open(lan_url)

    def exit_app(icon=None, menu_item=None):
        try:
            server.shutdown()
            server.server_close()
        finally:
            if icon:
                icon.stop()

    menu = pystray.Menu(
        item("Открыть на этом ПК", open_local),
        item(f"Открыть Wi‑Fi: {lan_url}", open_lan),
        item("Выход / остановить сервер", exit_app),
    )
    icon = pystray.Icon("Shadow Morse AR", make_icon_image(), "Shadow Morse AR server", menu)
    webbrowser.open(local_url)
    icon.run()


if __name__ == "__main__":
    main()
