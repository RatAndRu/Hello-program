"""
singleton.py — один экземпляр приложения (и корректный перезапуск).

Три уровня защиты (каждый лечит свою беду):
  1. ИМЕНОВАННЫЙ МЬЮТЕКС (LanguageYOI: CreateMutexW/OpenMutexW) — мгновенно
     отвечает, «уже запущено?», даже если сервер ещё поднимается.
  2. ПОРТ-ЛОК (DeployAgent: bind на локальный порт) — защищает от гонки, когда
     мьютекс занят, а процесс уже умирает; DeployAgent делает ПОВТОРЫ (retries):
     при перезапуске старый процесс ещё держит сокет несколько сотен мс, и без
     повторов новый процесс молча выходил, а старый уже умер.
  3. HTTP-идентификация (appcore.ports.check_identity) — главный уровень: порт
     мог унаследоваться или занять чужой программой.

Внимание к SO_EXCLUSIVEADDRUSE: на Windows SO_REUSEADDR позволяет bind поверх
чужого сокета, из-за чего лок-порт может ошибочно «получиться». appcore.ports
использует исключительный режим.

`relaunch_app()` — перезапуск через start.vbs: новый процесс стартует «чистым»,
как будто пользователь дважды кликнул ярлык (именно так делают DeployAgent и
BLIND_PC в hot-reload).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0
_MUTEX_MARK = "Local\\appcore_"

_held: dict[str, int] = {}      # name → handle мьютекса (держать до выхода!)
_lock_socket: socket.socket | None = None
_lock_guard = threading.Lock()


# ── 1. мьютекс ──────────────────────────────────────────────────────────────

def _mutex_name(name: str) -> str:
    return _MUTEX_MARK + str(name)


def acquire_mutex(name: str) -> bool:
    """Пытается стать единственным владельцем мьютекса. True — мы первые.

    Локальный префикс `Local\\` = «в пределах сеанса пользователя» (как в
    LanguageYOI). Для служб нужен `Global\\`, но это уже не наш случай.
    """
    if not WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, ctypes.c_wchar_p(_mutex_name(name)))
        if not handle:
            return True  # не смогли — не мешаем работать
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        with _lock_guard:
            _held[name] = handle
        return True
    except Exception:
        return True


def mutex_held_by_other(name: str) -> bool:
    """Занят ли мьютекс (например, приложение уже запускается)."""
    if not WINDOWS:
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenMutexW(0x00100000, False, ctypes.c_wchar_p(_mutex_name(name)))
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def release_mutex(name: str) -> None:
    with _lock_guard:
        handle = _held.pop(name, None)
    if handle and WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def single_instance(name: str) -> bool:
    """Короткая проверка «уже запущено?» без лок-порта."""
    return not mutex_held_by_other(name)


# ── 2. порт-лок ─────────────────────────────────────────────────────────────

def acquire_lock_port(port: int, *, host: str = "127.0.0.1", retries: int = 10,
                      delay: float = 0.4, logger=None) -> bool:
    """Занимает служебный порт-лок с повторами (опыт DeployAgent).

    Сокет НЕ закрывается до выхода процесса — иначе лок ничего не значит.
    """
    global _lock_socket
    release_lock_port()
    with _lock_guard:
        for attempt in range(max(1, retries)):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if WINDOWS:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, int(port)))
                sock.listen(1)
                _lock_socket = sock
                if attempt and logger:
                    logger.info("Порт-лок %s захвачен с %d-й попытки", port, attempt + 1)
                return True
            except OSError:
                try:
                    sock.close()
                except OSError:
                    pass
                time.sleep(delay)
        if logger:
            logger.warning("Порт-лок %s занят другим экземпляром — выход", port)
        return False


def release_lock_port() -> None:
    global _lock_socket
    with _lock_guard:
        if _lock_socket is not None:
            try:
                _lock_socket.close()
            except OSError:
                pass
            _lock_socket = None


def lock_port_for(app_id: str, span: int = 1, base: int = 18900) -> int:
    """Стабильный служебный порт-лок для app_id (диапазон 18900–18999)."""
    import zlib
    if span < 1:
        span = 1
    return base + (zlib.crc32(str(app_id).encode("utf-8")) % max(1, 100 // span)) * span


# ── 3. перезапуск и выход ───────────────────────────────────────────────────

def relaunch_app(app_dir: str | Path, vbs_name: str = "start.vbs", *,
                 delay: float = 0.4, logger=None) -> bool:
    """Перезапускает приложение через VBS-лаунчер (как двойной клик).

    Порядок важен (урок DeployAgent._do_restart):
      1. освобождаем порт-лок и мьютекс,
      2. запускаем новый процесс,
      3. только потом выходим сами.
    """
    app_dir = Path(app_dir)
    vbs = app_dir / vbs_name
    release_lock_port()
    time.sleep(max(0.0, delay))
    try:
        if vbs.exists() and WINDOWS:
            subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(app_dir),
                             creationflags=CREATE_NO_WINDOW)
        else:
            # фолбэк: запускаем тем же интерпретатором (полезно для отладки)
            entry = app_dir / "app.py"
            subprocess.Popen([sys.executable, str(entry)], cwd=str(app_dir),
                             creationflags=CREATE_NO_WINDOW)
        if logger:
            logger.info("Запущен новый процесс, старый завершается")
        return True
    except Exception as exc:
        if logger:
            logger.error("Не удалось перезапустить приложение: %s", exc)
        return False


def exit_process(code: int = 0) -> None:
    """Жёсткий выход: снимает лок и не даёт «фоновым потокам» держать процесс.

    os._exit нужен, потому что flask/pystray/pynput-потоки не всегда завершаются
    по флагам; иначе получается «зомби в диспетчере задач», который держит порт.
    """
    release_lock_port()
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        import logging
        logging.shutdown()
    except Exception:
        pass
    os._exit(code)
