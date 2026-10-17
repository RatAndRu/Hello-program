#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BudgetLIFE — иконка в системном трее (необязательная надстройка).

Приложение остаётся полностью рабочим и без этого файла: `start.vbs` поднимает
скрытый сервер и открывает отдельное окно браузера. Но если на компьютере есть
Python, этот скрипт даёт «настоящее» поведение десктопной программы:

    • иконка в трее с меню (Открыть, Копировать адрес, QR-код, Папка данных,
      Автозапуск, Перезапустить, Выход);
    • сам поднимает сервер (`node server.js`), если тот не запущен;
    • надзиратель: если сервер упал — поднимает заново (appcore.watchdog);
    • имя процесса в диспетчере задач (AppUserModelID, appcore.windowing).

Всё вспомогательное берётся из эталона SPECIALS/appcore — порты, трей,
автозапуск, логи и QR не изобретаются заново:

    python tools/tray.py            # обычный запуск (сервер + трей)
    python tools/tray.py --no-tray  # только сервер, без иконки
    python tools/tray.py --stop     # остановить сервер этого проекта

Требования: Python 3.10+, Node.js 20+; для иконки —
    python -m pip install -r tools/requirements.txt   (pystray, pillow, psutil)
Без pystray приложение продолжает работать и пишет в лог, что установить.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SPECIALS = BASE / "SPECIALS"

APP_ID = "budgetlife"
APP_NAME = "BudgetLIFE"
APP_VERSION = "1.0.0"
APP_LETTER = "B"
HOST = "127.0.0.1"
REGISTRY = BASE / "ports.json"
SERVER_FILE = BASE / "server.js"

# appcore — библиотека эталона; если папка SPECIALS рядом, используем её
if SPECIALS.exists():
    sys.path.insert(0, str(SPECIALS))

try:
    from appcore import autostart, netutil, paths, ports, tray as tray_lib, watchdog
    from appcore.logutil import setup as setup_logging
except Exception as exc:  # pragma: no cover — эталон не рядом или не установлен
    sys.stderr.write(
        f"Не найден appcore (папка SPECIALS): {exc}\n"
        "Положите SPECIALS рядом с проектом или запускайте приложение через start.vbs.\n"
    )
    raise

APP_PATHS = paths.AppPaths.for_dir(BASE).ensure()
logger = setup_logging(APP_NAME, APP_PATHS.log_file("log.txt"), console_also=False)

SERVER_PROCESS: subprocess.Popen | None = None
STATE = {"port": 0, "url": ""}


# ─────────────────────────────── управление сервером ────────────────────────
def _hidden_kwargs() -> dict:
    """Скрыть окно консоли дочернего node.exe (для Windows)."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def candidate_ports() -> list[int]:
    return ports.candidates(APP_ID, registry_path=REGISTRY)


def server_is_up(port: int) -> bool:
    return ports.check_identity(HOST, port, APP_ID, timeout=1.0) is not None


def start_server() -> int:
    """Поднимает `node server.js`; возвращает фактический порт (0 — не вышло)."""
    global SERVER_PROCESS
    if not SERVER_FILE.exists():
        logger.error("Не найден server.js: %s", SERVER_FILE)
        return 0
    node = shutil.which("node") or "node"
    cmd = [node, str(SERVER_FILE), f"--host={HOST}"]
    try:
        SERVER_PROCESS = subprocess.Popen(
            cmd, cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_hidden_kwargs(),
        )
    except FileNotFoundError:
        logger.error("Не найден node.exe — установите Node.js 20+ с nodejs.org")
        return 0
    except Exception as exc:
        logger.error("Не удалось запустить сервер: %s", exc)
        return 0

    port = ports.wait_until_ready(
        APP_ID, HOST, candidate_ports(), timeout=45.0, logger=logger,
        data_dir=APP_PATHS.data,
    )
    if not port:
        logger.error("Сервер не ответил по /api/identity ни на одном порту блока")
        return 0
    logger.info("Сервер поднят: pid=%s порт=%s", SERVER_PROCESS.pid, port)
    return port


def ensure_server() -> int:
    """Уже запущен — переиспользуем; нет — поднимаем сами."""
    running = ports.find_running(APP_ID, HOST, candidate_ports())
    if running:
        logger.info("Сервер уже работает на порту %s (pid=%s)",
                    running.port, running.identity.get("pid"))
        STATE["port"] = running.port
        STATE["url"] = f"http://{HOST}:{running.port}/"
        return running.port
    port = start_server()
    STATE["port"] = port
    STATE["url"] = f"http://{HOST}:{port}/" if port else ""
    return port


def stop_server() -> None:
    """Останавливаем только то, что запустили сами (чужие процессы не трогаем)."""
    global SERVER_PROCESS
    if SERVER_PROCESS and SERVER_PROCESS.poll() is None:
        logger.info("Останавливаю сервер pid=%s", SERVER_PROCESS.pid)
        SERVER_PROCESS.terminate()
        try:
            SERVER_PROCESS.wait(timeout=8)
        except Exception:
            SERVER_PROCESS.kill()
    SERVER_PROCESS = None


def restart_server() -> None:
    stop_server()
    time.sleep(1.0)
    if not ensure_server():
        logger.error("Перезапуск не удался")


# ───────────────────────────────── пункты меню ──────────────────────────────
def open_app() -> None:
    url = STATE.get("url") or "http://127.0.0.1:5130/"
    try:
        from appcore import windowing
        windowing.focus_or_open(url, [APP_NAME])
    except Exception:
        import webbrowser
        webbrowser.open(url)


def show_qr() -> None:
    url = STATE.get("url")
    if not url:
        logger.warning("QR: сервер не запущен")
        return
    data = netutil.qr_png_bytes(url)
    if not data:
        logger.warning("QR не удалось построить")
        return
    path = APP_PATHS.data_file("qr.png")
    path.write_bytes(data)
    logger.info("QR сохранён: %s", path)
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]  # Windows
    except Exception:
        logger.info("Откройте файл вручную: %s", path)


def open_data_folder() -> None:
    folder = APP_PATHS.data
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(folder))  # type: ignore[attr-defined]  # Windows
    except Exception:
        logger.info("Папка данных: %s", folder)


def toggle_autostart() -> bool:
    """Галочка «Автозапуск» в меню трея (HKCU\\...\\Run → start.vbs)."""
    command = autostart.launcher_command(BASE, "start.vbs")
    enabled = autostart.set_autostart(
        APP_NAME, command, not autostart.is_autostart_enabled(APP_NAME), logger=logger)
    logger.info("Автозапуск: %s", "включён" if enabled else "выключен")
    return enabled


def on_quit() -> None:
    """Порядок выхода по стандарту: сервер → иконка → выход без «зомби»."""
    logger.info("Выход из трея")
    stop_server()
    logging_shutdown()
    os._exit(0)


def logging_shutdown() -> None:
    try:
        import logging
        logging.shutdown()
    except Exception:
        pass


def build_items() -> list:
    items = [
        tray_lib.TrayItem.title(f"{APP_NAME} {APP_VERSION}"),
        tray_lib.open_url_item("Открыть", STATE.get("url") or "http://127.0.0.1:5130/",
                               hints=[APP_NAME], default=True),
        tray_lib.TrayItem("Копировать адрес",
                          lambda: netutil.copy_to_clipboard(STATE.get("url", ""))),
        tray_lib.TrayItem("QR-код с адресом", show_qr),
        tray_lib.TrayItem("Открыть папку данных", open_data_folder),
        tray_lib.TrayItem.separator_item(),
        tray_lib.TrayItem("Автозапуск", toggle_autostart,
                          checked=lambda: autostart.is_autostart_enabled(APP_NAME)),
        tray_lib.TrayItem("Перезапустить", restart_server),
        tray_lib.TrayItem.separator_item(),
        tray_lib.TrayItem("Выход", on_quit),
    ]
    return items


# ────────────────────────────────────main ───────────────────────────────────
class NodeHandle:
    """Маленькая «нить» для надзирателя: жива, пока жив процесс сервера."""

    def is_alive(self) -> bool:
        if SERVER_PROCESS is not None:
            return SERVER_PROCESS.poll() is None
        return bool(STATE.get("port")) and server_is_up(int(STATE["port"]))


def main() -> int:
    args = sys.argv[1:]
    if "--stop" in args:
        stop_server()
        return 0

    logger.info("=== %s %s (трей) ===", APP_NAME, APP_VERSION)
    logger.info("Папка: %s", BASE)
    logger.info("Блок портов: %s", candidate_ports())

    try:
        from appcore import windowing
        windowing.set_app_user_model_id(f"RatAndRu.{APP_NAME}.{APP_ID}")
    except Exception as exc:
        logger.debug("AppUserModelID не задан: %s", exc)

    port = ensure_server()
    if not port:
        logger.error("Приложение без сервера работать не может — выход")
        return 1
    logger.info("Адрес: %s", STATE["url"])

    # Надзиратель: если сервер «упал» — поднимаем заново (приём DnD's)
    watchdog.ThreadWatchdog(
        thread=NodeHandle(),
        health_url=netutil.url_for(HOST, port, "/api/health"),
        on_down=lambda reason: (logger.warning("Сервер недоступен (%s) — перезапуск", reason),
                                threading.Thread(target=restart_server, daemon=True).start()),
        interval=30.0, failures=2, startup_grace=20.0, logger=logger,
    ).start()

    if "--no-tray" in args:
        logger.info("Режим --no-tray: сервер работает, ждём Ctrl+C")
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            on_quit()
        return 0

    app = tray_lib.TrayApp(
        tray_lib.TrayConfig(app_id=APP_ID, title=f"{APP_NAME} {APP_VERSION}",
                            tooltip_url=STATE["url"], icon_letter=APP_LETTER,
                            background=(16, 185, 129), items=build_items()),
        logger=logger, on_quit=on_quit,
    )

    if not app.available:
        logger.warning("Трей недоступен: %s", app.unavailable_reason())
        logger.warning("Подсказка: %s", tray_lib.install_hint(app.unavailable_reason()))
        # Без иконки всё равно обслуживаем приложение: просто держим сервер
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            on_quit()
        return 0

    app.notify(f"{APP_NAME} запущен: {STATE['url']}", APP_NAME)
    app.run(blocking=True)      # главный поток занят иконкой
    return 0


if __name__ == "__main__":
    sys.exit(main())
