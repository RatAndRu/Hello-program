"""
processes.py — работа с процессами: кто занял порт, жив ли pid, сколько памяти.

Взято из Трекера (tasklist/netstat, kill_process_on_port), SHADOW GAME
(аккуратное убийство только «своих» python -m http.server через PowerShell +
Win32_Process.CommandLine), DeployAgent (memory-guard для перезапуска).

ГЛАВНОЕ ПРАВИЛО БЕЗОПАСНОСТИ
---------------------------
Никогда не убивать процесс только потому, что он занял порт. Сначала проверить
командную строку: это должен быть НАШ app.py (или наш http.server). Иначе
однажды будет убит чужой сервер или, хуже, системный процесс.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterable

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0


# ── низкоуровневые запуски без мигания консоли ──────────────────────────────

def run_hidden(args, timeout: float = 10.0, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run без окна консоли (под pythonw окно недопустимо)."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", timeout)
    if WINDOWS:
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    try:
        return subprocess.run(args, **kwargs)
    except Exception as exc:  # таймаут/отсутствие утилиты
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr=str(exc))


# ── pid ─────────────────────────────────────────────────────────────────────

def pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким pid (без прав на его завершение)."""
    if not pid or pid <= 0:
        return False
    try:
        if WINDOWS:
            out = run_hidden(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"]).stdout or ""
            return str(int(pid)) in out
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def memory_mb(pid: int | None = None) -> float | None:
    """Память процесса в МБ: psutil → tasklist. None, если узнать не удалось."""
    pid = int(pid or os.getpid())
    try:
        import psutil
        return psutil.Process(pid).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    if WINDOWS:
        out = run_hidden(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]).stdout or ""
        match = re.search(r'"([\d\s\u00a0]+)\s*[KК]?"', out)
        if match:
            try:
                return float(match.group(1).replace(" ", "").replace("\u00a0", "")) / 1024.0
            except ValueError:
                return None
    return None


def command_line(pid: int) -> str:
    """Командная строка процесса — по ней мы понимаем, «наш» это процесс или чужой."""
    pid = int(pid)
    try:
        import psutil
        return " ".join(psutil.Process(pid).cmdline())
    except Exception:
        pass
    if WINDOWS:
        script = (f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
                  f".CommandLine")
        out = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-Command", script]).stdout or ""
        return out.strip()
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


# ── порты ───────────────────────────────────────────────────────────────────

def pids_listening_on(port: int) -> list[int]:
    """PID процессов, слушающих порт. Пусто, если порт свободен."""
    port = int(port)
    pids: set[int] = set()
    if WINDOWS:
        out = run_hidden(["netstat", "-ano", "-p", "TCP"]).stdout or ""
        for line in out.splitlines():
            parts = line.split()
            # TCP    0.0.0.0:5100    0.0.0.0:0    LISTENING    12345
            if len(parts) >= 5 and parts[0].upper().startswith("TCP") and parts[3].upper() == "LISTENING":
                if parts[1].rsplit(":", 1)[-1] == str(port):
                    try:
                        pids.add(int(parts[4]))
                    except ValueError:
                        pass
    else:
        try:
            import psutil
            for conn in psutil.net_connections(kind="tcp"):
                if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port and conn.pid:
                    pids.add(int(conn.pid))
        except Exception:
            pids |= _pids_from_procfs(port)
            if not pids:
                out = run_hidden(["sh", "-c", f"lsof -ti tcp:{port} -sTCP:LISTEN"]).stdout or ""
                for token in out.split():
                    if token.isdigit():
                        pids.add(int(token))
    pids.discard(os.getpid())
    return sorted(pids)


def _pids_from_procfs(port: int) -> set[int]:
    """Linux/macOS без psutil: слушающие сокеты из /proc/net/tcp{6}.

    Приём взят из аудита портов: сравниваем inode сокета с целями символических
    ссылок /proc/<pid>/fd/*. Внешние утилиты (lsof, ss) не нужны — стандартная
    библиотека. На не-Linux вернёт пустое множество, и сработает запасной путь.
    """
    import glob
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="ascii", errors="replace") as handle:
                lines = handle.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3].upper() != "0A":   # 0A = LISTEN
                continue
            try:
                if int(parts[1].rsplit(":", 1)[1], 16) == port:
                    inodes.add(parts[9])
            except (ValueError, IndexError):
                continue
    if not inodes:
        return set()
    found: set[int] = set()
    for fd_path in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            target = os.readlink(fd_path)
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in inodes:
            try:
                found.add(int(fd_path.split("/")[2]))
            except (ValueError, IndexError):
                continue
    return found


def port_owner_info(port: int) -> list[tuple[int, str]]:
    """[(pid, командная строка)] для всех слушателей порта."""
    return [(pid, command_line(pid)) for pid in pids_listening_on(port)]


def kill_pid(pid: int, *, force: bool = True) -> bool:
    """Завершает процесс. False — если не удалось (не бросает исключение)."""
    pid = int(pid)
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if WINDOWS:
            args = ["taskkill", "/PID", str(pid)] + (["/F"] if force else [])
            return run_hidden(args).returncode == 0
        os.kill(pid, 9 if force else 15)
        return True
    except Exception:
        return False


def kill_stale_listener(port: int, must_match: Iterable[str] = (), *, logger=None,
                        grace: float = 1.0) -> list[int]:
    """Завершает старый сервер на порту, ТОЛЬКО если его командная строка «наша».

    must_match — список подстрок, хотя бы одна должна встречаться в командной строке
    (обычно: путь к app.py и/или имя файла-скрипта). Такой подход взят из
    `stop_ar_servers.vbs` проекта SHADOW GAME: он убивает только
    `python -m http.server 8080`, а не все Python-процессы подряд.

    Возвращает список убитых pid.
    """
    import time
    markers = [str(m).lower() for m in must_match if str(m)]
    killed: list[int] = []
    for pid, cmdline in port_owner_info(port):
        low = (cmdline or "").lower()
        if not markers:
            if logger:
                logger.warning("Порт %s занят pid=%s, но список «своих» меток пуст — не трогаю: %s",
                               port, pid, low[:160])
            continue
        if not any(marker in low for marker in markers):
            if logger:
                logger.warning("Порт %s занят ЧУЖИМ процессом pid=%s (%s) — не убиваю",
                               port, pid, low[:160])
            continue
        if logger:
            logger.info("Освобождаю порт %s: завершаю старый экземпляр pid=%s", port, pid)
        if kill_pid(pid):
            killed.append(pid)
    if killed:
        time.sleep(grace)   # дать ОС закрыть сокет, иначе новый bind сразу упадёт
    return killed


def self_command_markers(*extra: str) -> list[str]:
    """Метки «своего» процесса для kill_stale_listener: путь к скрипту и его имя."""
    markers: list[str] = []
    if sys.argv and sys.argv[0]:
        try:
            markers.append(os.path.abspath(sys.argv[0]).lower())
            markers.append(os.path.basename(sys.argv[0]).lower())
        except Exception:
            pass
    markers.extend(str(x).lower() for x in extra if x)
    return list(dict.fromkeys(markers))
