#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================================
 NET DOCTOR  —  «почему телефон не видит мой Python-сервер?»   (одним файлом, без библиотек)
==========================================================================================

Задача инструмента: не гадать, а по шагам показать, ГДЕ именно рвётся цепочка

    [твой Python-сервер] -> [ноутбук: адрес + брандмауэр] -> [Wi-Fi/роутер] -> [телефон]

Что делает:

  1. Проверяет сам процесс:  порт свободен, сокет слушает 0.0.0.0, ответ идёт
     и на 127.0.0.1, и на «публичный» 192.168.x.x адрес ноутбука.
  2. Читает конфигурацию Windows, которая чаще всего всё и ломает:
       * профиль сети (Public блокирует входящие, Private — нет);
       * брандмауэр: включён ли, есть ли правило для python.exe, не включено ли
         «блокировать все входящие»;
       * лишние виртуальные адаптеры: Cloudflare WARP, Hyper-V, WSL, VPN, TAP;
       * таблицу маршрутов и метрики интерфейсов;
       * системный прокси WinINET/WinHTTP (WARP любит ставить 127.0.0.1:40000);
       * антивирусы сторонних фирм, свои сетевые фильтры;
       * файл hosts, DNS, список «соседей» в сети (ARP) и текущий SSID Wi-Fi.
  3. Поднимает тестовый веб-сервер на 0.0.0.0:<порт> и ЖДЁТ запрос с телефона.
     Как только телефон откроет страницу — это видно и в консоли, и на странице.
  4. Печатает понятный вердикт: «дело в брандмауэре», «дело в WARP»,
     «телефон в другой сети», «сервер слушает только 127.0.0.1» и т.п.
  5. Готовит файл-починку: netdoctor_fix.ps1 (добавить правило брандмауэра,
     переключить профиль сети на Private) и netdoctor_undo.ps1 (всё вернуть).
  6. Пишет отчёт netdoctor_report.txt — его можно показать/переслать целиком.

Запуск:

    python net_doctor.py                      # проверки + тестовый сервер + вердикт
    python net_doctor.py --port 5000          # проверить/послушать другой порт
    python net_doctor.py --check-port 5000    # что происходит с ВАШИМ сервером на 5000
    python net_doctor.py --phone 192.168.0.61 # проверить связь именно с телефоном
    python net_doctor.py --no-server          # только проверки, без тестового сервера
    python net_doctor.py --fix                # создать netdoctor_fix.ps1 (и предложить запустить)
    python net_doctor.py --selftest           # самотест инструмента (для CI)
    python net_doctor.py --help               # все ключи

Требуется только Python 3.8+ и стандартная библиотека. Никаких pip install.
Windows-специфичные проверки включаются сами; на Linux/macOS базовые проверки тоже работают.

Автор-код: для репозитория Hello-program / New program.
==========================================================================================
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import http.server
import inspect
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "1.1.0"
DEFAULT_PORT = 8770          # порт тестового сервера (специально не 5000/8000/8080)
IS_WINDOWS = (os.name == "nt")

# Служебные имена правил брандмауэра, которые создаёт инструмент.
FW_RULE_PREFIX = "netdoctor: разрешить LAN"
FW_RULE_TAG = "netdoctor-lan-dev"


# =========================================================================================
#  1. ЦВЕТА, СИМВОЛЫ И ПЕЧАТЬ
# =========================================================================================

class _ColorMeta(type):
    """Неизвестное имя цвета не должно ронять инструмент — вернём пустую строку."""

    def __getattr__(cls, name: str) -> str:
        return ""


class C(metaclass=_ColorMeta):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GREY = "\033[90m"


_COLOR = False


def setup_console() -> None:
    """
    Готовит консоль и потоки вывода.

    Зачем: раньше кодовая страница переключалась командой `chcp 65001` в .bat-файле.
    На Windows это опасно: если .bat сохранён с юниксовыми переводами строк (LF),
    cmd.exe после смены кодовой страницы теряет позицию чтения файла и начинает
    выполнять ОБРЫВКИ строк как команды ("'on' is not recognized...",
    "'тайте' is not recognized..."). Поэтому chcp убран, а всё, что нужно, делаем здесь:
      * Windows: кодовая страница вывода -> UTF-8 (для дочерних утилит и перенаправленного
        вывода), заголовок окна -> «NET DOCTOR»;
      * везде: переводим stdout/stderr в UTF-8, если поток это позволяет
        (безопасно: ошибки кодирования заменяются, а не роняют программу).
    """
    if IS_WINDOWS:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleTitleW("NET DOCTOR — диагностика доступа к серверам")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _enable_vt_on_windows() -> None:
    """Включает поддержку ANSI-цветов в классической консоли Windows."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VT
    except Exception:
        pass


def enable_colors(force: Optional[bool] = None) -> bool:
    global _COLOR
    if force is False or os.environ.get("NO_COLOR"):
        _COLOR = False
        return False
    if force is True:
        _COLOR = True
        return True
    if not hasattr(sys.stdout, "isatty"):
        return False
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    if IS_WINDOWS:
        _enable_vt_on_windows()
    _COLOR = True
    return True


def col(text: str, *codes: str) -> str:
    if not _COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET


def _can_print(ch: str) -> bool:
    """Сможет ли текущая консоль напечатать этот символ."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        ch.encode(enc)
        return True
    except Exception:
        return False


def _sym(unicode_sym: str, ascii_sym: str) -> str:
    return unicode_sym if _can_print(unicode_sym) else ascii_sym


SYM = {
    "ok": _sym("✔", "OK"),
    "warn": _sym("!", "!"),
    "bad": _sym("✖", "X"),
    "info": _sym("•", "-"),
    "skip": _sym("·", "."),
    "arrow": _sym("→", "->"),
    "phone": _sym("📱", "[phone]"),
}

STATUS_LABEL = {
    "ok": "ОК",
    "warn": "ВНИМАНИЕ",
    "bad": "ПРОБЛЕМА",
    "info": "инфо",
    "skip": "пропущено",
}

STATUS_COLOR = {
    "ok": C.GREEN,
    "warn": C.YELLOW,
    "bad": C.RED,
    "info": C.CYAN,
    "skip": C.GREY,
}


def hr(char: str = "─", width: int = 86) -> str:
    """Горизонтальная линия (в старых консолях ─ недоступна — берём -)."""
    ch = char if _can_print(char) else "-"
    return col(ch * width, C.GREY)


def say(text: str = "") -> None:
    print(text)


def title(text: str) -> None:
    print()
    print(col("═" * 86, C.BLUE))
    print(col("  " + text, C.BOLD, C.WHITE))
    print(col("═" * 86, C.BLUE))


def step(num: str, text: str) -> None:
    print()
    print(col(f"[{num}] ", C.BOLD, C.MAGENTA) + col(text, C.BOLD))


def good(text: str) -> None:
    print("  " + col(f"{SYM['ok']} ", C.GREEN) + text)


def warn(text: str) -> None:
    print("  " + col(f"{SYM['warn']} ", C.YELLOW) + text)


def bad(text: str) -> None:
    print("  " + col(f"{SYM['bad']} ", C.RED) + text)


def info(text: str) -> None:
    print("  " + col(f"{SYM['info']} ", C.CYAN) + text)


# =========================================================================================
#  2. ЗАПУСК ВНЕШНИХ КОМАНД
# =========================================================================================

def decode_bytes(data: bytes) -> str:
    """Аккуратно декодирует вывод команд Windows (cp866 / cp1251 / utf-8)."""
    if not data:
        return ""
    for enc in ("utf-8", "cp866", "cp1251", "cp437"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def run(cmd: Sequence[str], timeout: float = 60.0,
        cwd: Optional[str] = None) -> Tuple[Optional[int], str, str]:
    """Запускает команду. Возвращает (код возврата или None, stdout, stderr)."""
    kwargs: Dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW — не мигаем окном
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=cwd,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return None, "", f"команда не ответила за {timeout:.0f} с"
    except (OSError, ValueError) as exc:
        return None, "", str(exc)
    return proc.returncode, decode_bytes(proc.stdout), decode_bytes(proc.stderr)


def cmd_text(cmd: Sequence[str], timeout: float = 30.0) -> str:
    """stdout команды одной строкой (или '' если не получилось)."""
    rc, out, err = run(cmd, timeout=timeout)
    return (out or err or "").strip()


# =========================================================================================
#  3. POWERSHELL: СБОР КОНФИГУРАЦИИ WINDOWS
# =========================================================================================

def which_powershell() -> Optional[str]:
    if not IS_WINDOWS:
        return None
    for exe in ("powershell.exe", "pwsh.exe"):
        path = shutil.which(exe)
        if path:
            return path
    # На случай, если PATH «поехал», но Windows на месте.
    for path in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                     r"System32\WindowsPowerShell\v1.0\powershell.exe"),
    ):
        if os.path.isfile(path):
            return path
    return None


_PS_HEADER = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$script:ND_OUT = [ordered]@{}
function AddSec {
    param([string]$name, [scriptblock]$sb)
    $sec = [ordered]@{ ok = $true; error = $null; data = $null }
    try {
        $val = & $sb
        $sec.data = $val
    } catch {
        $sec.ok = $false
        $sec.error = "$($_.Exception.Message)"
    }
    $script:ND_OUT[$name] = $sec
}
"""


def extract_json(text: str) -> Any:
    """Достаёт JSON из вывода команды, даже если вокруг есть мусор/предупреждения."""
    if not text:
        return None
    s = text.lstrip("\ufeff \t\r\n")
    try:
        return json.loads(s)
    except Exception:
        pass
    # Ищем первый { ... последний } и пробуем ещё раз.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        end = s.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except Exception:
                continue
    return None


def ps_collect(sections: Sequence[Tuple[str, str]], timeout: float = 150.0) -> Dict[str, Any]:
    """
    Выполняет набор PowerShell-«секций» и возвращает словарь
        {имя_секции: {"ok": bool, "error": str|None, "data": ...}}

    Секции пишутся на PowerShell и должны возвращать данные (объект/массив).
    Результат складывается в JSON-файл (обходим проблемы с кодировкой консоли).
    """
    ps = which_powershell()
    if not ps:
        return {}

    tmpdir = tempfile.mkdtemp(prefix="netdoctor_")
    script_path = os.path.join(tmpdir, "collect.ps1")
    json_path = os.path.join(tmpdir, "collect.json")

    parts = [_PS_HEADER]
    for name, body in sections:
        safe_name = name.replace("'", "''")
        parts.append("AddSec '%s' {\n%s\n}\n" % (safe_name, body))
    parts.append(
        "$json = $script:ND_OUT | ConvertTo-Json -Depth 8 -Compress\n"
        "if ($null -eq $json) { $json = '{}' }\n"
        "[System.IO.File]::WriteAllText('%s', $json, (New-Object System.Text.UTF8Encoding($false)))\n"
        % json_path.replace("'", "''")
    )

    try:
        with open(script_path, "w", encoding="utf-8-sig") as fh:
            fh.write("\n".join(parts))
        cmd = [ps, "-NoProfile", "-NonInteractive"]
        if IS_WINDOWS:
            cmd += ["-ExecutionPolicy", "Bypass"]
        cmd += ["-File", script_path]
        run(cmd, timeout=timeout)
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8-sig") as fh:
                data = extract_json(fh.read())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {}


def ps_balance_check(script: str) -> Optional[str]:
    """
    Проверяет, что в PowerShell-скрипте сбалансированы {} [] () и кавычки.

    Полноценного парсера PowerShell в стандартной библиотеке нет, но такая проверка
    ловит самые частые опечатки — потерянную скобку или незакрытую кавычку в
    многострочной конструкции. Возвращает текст проблемы или None, если всё хорошо.
    (Here-strings @" ... "@ не поддерживаются — в этом файле они не используются.)
    """
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: List[Tuple[str, int]] = []
    in_single = in_double = in_block_comment = False
    i, line, n = 0, 1, len(script)
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
            i += 1
            continue
        if in_block_comment:
            if ch == "#" and nxt == ">":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'":
                if nxt == "'":            # '' — экранированная кавычка
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == "`":                 # ` — escape-символ PowerShell
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "#":
            while i < n and script[i] != "\n":
                i += 1
            continue
        if ch == "<" and nxt == "#":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch in "([{":
            stack.append((ch, line))
            i += 1
            continue
        if ch in ")]}":
            if not stack or stack[-1][0] != pairs[ch]:
                return f"лишняя «{ch}» в строке {line}"
            stack.pop()
            i += 1
            continue
        i += 1
    if stack:
        ch, ln = stack[-1]
        return f"не закрыта «{ch}», открытая в строке {ln}"
    if in_single:
        return "не закрыта одинарная кавычка"
    if in_double:
        return "не закрыта двойная кавычка"
    if in_block_comment:
        return "не закрыт блочный комментарий <# #>"
    return None


def ps_one(script: str, timeout: float = 90.0) -> Optional[str]:
    """Небольшой одиночный PowerShell-скрипт -> текст (без JSON-обёртки)."""
    ps = which_powershell()
    if not ps:
        return None
    tmpdir = tempfile.mkdtemp(prefix="netdoctor_")
    path = os.path.join(tmpdir, "one.ps1")
    try:
        with open(path, "w", encoding="utf-8-sig") as fh:
            fh.write("$ErrorActionPreference='SilentlyContinue'\n"
                     "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}\n"
                     + script)
        cmd = [ps, "-NoProfile", "-NonInteractive"]
        if IS_WINDOWS:
            cmd += ["-ExecutionPolicy", "Bypass"]
        cmd += ["-File", path]
        rc, out, err = run(cmd, timeout=timeout)
        return (out or "").strip() or None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def is_admin() -> bool:
    """Запущен ли процесс с правами администратора."""
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


# =========================================================================================
#  4. МОДЕЛЬ РЕЗУЛЬТАТОВ
# =========================================================================================

@dataclass
class Check:
    key: str
    title: str
    status: str = "info"          # ok | warn | bad | info | skip
    detail: str = ""
    hint: str = ""                # что делать
    fix_ps: List[str] = field(default_factory=list)   # команды PowerShell для починки

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
        }


class Diag:
    """Собирает проверки и «факты» о сети; из них потом строится вердикт."""

    def __init__(self) -> None:
        self.checks: List[Check] = []
        self.facts: Dict[str, Any] = {}
        self.hits: List[Dict[str, Any]] = []
        self.started = _dt.datetime.now()
        self._lock = threading.Lock()

    def add(self, key: str, ttl: str, status: str, detail: str = "",
            hint: str = "", fix_ps: Optional[Sequence[str]] = None) -> Check:
        chk = Check(key=key, title=ttl, status=status, detail=detail, hint=hint,
                    fix_ps=list(fix_ps or []))
        with self._lock:
            self.checks.append(chk)
        return chk

    def get(self, key: str) -> Optional[Check]:
        for chk in self.checks:
            if chk.key == key:
                return chk
        return None

    def worst(self) -> str:
        order = ["bad", "warn", "ok", "info", "skip"]
        for st in order:
            if any(c.status == st for c in self.checks):
                return st
        return "info"

    def count(self, status: str) -> int:
        return sum(1 for c in self.checks if c.status == status)

    def add_hit(self, ip: str, path: str, ua: str, port: int, scheme: str = "http",
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        # «Своих» вычисляем по всем известным адресам ноутбука...
        known = list(self.facts.get("local_ips") or []) + list(self.facts.get("ips") or [])
        local = is_local_ip(ip, known)
        # ...а запросы самого netdoctor (проверки 127.0.0.1 и LAN-адресов) — никогда не «гость».
        ua_l = (ua or "").strip().lower()
        if ua_l.startswith("netdoctor/"):
            local = True
        hit = {
            "time": _dt.datetime.now().strftime("%H:%M:%S"),
            "ip": ip,
            "port": port,
            "path": path,
            "ua": ua,
            "local": local,
            "via_proxy": bool(headers and (headers.get("Via") or headers.get("X-Forwarded-For"))),
            "forwarded": (headers or {}).get("X-Forwarded-For", ""),
        }
        with self._lock:
            self.hits.append(hit)
        return hit

    def external_hits(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [h for h in self.hits if not h["local"]]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "started": self.started.isoformat(timespec="seconds"),
            "facts": self.facts,
            "checks": [c.as_dict() for c in self.checks],
            "hits": list(self.hits),
        }

    # ---- печать одной проверки в консоль -------------------------------------------
    def show(self, key: str) -> None:
        chk = self.get(key)
        if not chk:
            return
        mark = col(SYM[chk.status], STATUS_COLOR[chk.status], C.BOLD)
        line = f"  {mark} {chk.title}"
        if chk.detail:
            line += col("  " + chk.detail, C.GREY)
        print(line)
        if chk.hint:
            print(col("      ", C.GREY) + col(f"{SYM['arrow']} {chk.hint}",
                                             STATUS_COLOR.get(chk.status, C.CYAN)))

    def show_all(self) -> None:
        for chk in list(self.checks):
            self.show(chk.key)


# =========================================================================================
#  5. СЕТЕВЫЕ ФАКТЫ: АДРЕСА, ИНТЕРФЕЙСЫ, ПРОФИЛИ, БРАНДМАУЭР
# =========================================================================================

LAN_KEYWORDS = [
    # (что ищем в описании/имени адаптера, что это значит, насколько «мешает» 1..3)
    ("cloudflare", "Cloudflare WARP", 3),
    ("warp", "Cloudflare WARP", 3),
    ("wireguard", "WireGuard VPN", 3),
    ("openvpn", "OpenVPN", 3),
    ("proton", "ProtonVPN", 3),
    ("nordlynx", "NordVPN", 3),
    ("nord", "NordVPN", 3),
    ("surfshark", "Surfshark", 3),
    ("expressvpn", "ExpressVPN", 3),
    ("windscribe", "Windscribe", 3),
    ("kaspersky", "Kaspersky VPN", 3),
    ("avast", "Avast SecureLine", 3),
    ("avg", "AVG VPN", 3),
    ("mullvad", "Mullvad", 3),
    ("tunnelbear", "TunnelBear", 3),
    ("cisco", "Cisco VPN", 3),
    ("anyconnect", "Cisco AnyConnect", 3),
    ("globalprotect", "Palo Alto GlobalProtect", 3),
    ("fortinet", "Fortinet VPN", 3),
    ("forticlient", "FortiClient", 3),
    ("zscaler", "Zscaler", 3),
    ("checkpoint", "Check Point VPN", 3),
    ("sonicwall", "SonicWall", 3),
    ("softether", "SoftEther VPN", 3),
    ("tap-windows", "OpenVPN TAP", 2),
    ("tap-", "TAP-адаптер", 2),
    ("wintun", "Wintun-туннель", 2),
    ("vethernet", "Hyper-V / WSL виртуальная сеть", 2),
    ("hyper-v", "Hyper-V виртуальная сеть", 2),
    ("default switch", "Hyper-V Default Switch", 2),
    ("docker", "Docker виртуальная сеть", 2),
    ("virtualbox", "VirtualBox Host-Only", 2),
    ("vmware", "VMware виртуальная сеть", 2),
    ("loopback", "Loopback-адаптер", 1),
    ("wi-fi", "Wi-Fi", 0),
    ("wifi", "Wi-Fi", 0),
    ("wireless", "Wi-Fi", 0),
    ("ethernet", "Ethernet", 0),
    ("realtek", "Ethernet", 0),
    ("intel(r)", "сетевой адаптер", 0),
    ("bluetooth", "Bluetooth PAN", 1),
    # Точка доступа Windows (мобильный хот-спот) живёт на Wi-Fi Direct адаптере
    # с адресом 192.168.137.x — для телефона в обычной Wi-Fi сети он бесполезен.
    ("wi-fi direct", "точка доступа Windows (мобильный хот-спот)", 2),
    ("wifi direct", "точка доступа Windows (мобильный хот-спот)", 2),
]

# Подсеть, которую Windows ICS (общий доступ/мобильный хот-спот) использует по
# умолчанию: 192.168.137.0/24. Адреса оттуда телефон в обычной сети не найдёт.
ICS_SUBNET = ipaddress.ip_network("192.168.137.0/24")

# Статусы служб Windows (ServiceControllerStatus), чтобы в отчёте не было «4» и «1».
SERVICE_STATUS = {
    1: "Stopped/остановлена", 2: "StartPending/запускается",
    3: "StopPending/останавливается", 4: "Running/работает",
    5: "ContinuePending/продолжается", 6: "PausePending/пауза", 7: "Paused/на паузе",
}


def service_status_word(value: Any) -> str:
    """Числовой статус службы -> понятная строка (в отчёте были «4», «1»)."""
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        return str(value)
    return SERVICE_STATUS.get(num, str(value))


def is_ics_ip(ip: str) -> bool:
    """Адрес из подсети общего доступа Windows (мобильный хот-спот/ICS)."""
    try:
        return ipaddress.ip_address(ip) in ICS_SUBNET
    except ValueError:
        return False


def describe_raw_request(raw: bytes) -> str:
    """
    Описывает «сырой» запрос, который не удалось разобрать как HTTP.

    Зачем: если открыть адрес как https://, браузер пришлёт TLS-приветствие
    (ClientHello). Обычный HTTP-сервер отвечает ошибкой 400 и НЕ попадает в журнал
    запросов — и кажется, что «телефон не достучался», хотя пакеты дошли.
    """
    if not raw:
        return "подключение без данных"
    head = raw[:8]
    if head.startswith(b"\x16\x03"):
        return "TLS ClientHello — открывали https://, а сервер ждёт http://"
    if head.startswith((b"GET ", b"POST", b"HEAD", b"PUT ", b"OPTI")):
        return "HTTP-запрос с ошибкой формата (битые заголовки/строка запроса)"
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
    return f"не HTTP (первые байты: {head.hex()}, как текст: {printable!r})"


def classify_adapter(*names: str) -> Tuple[str, int]:
    """Определяет тип адаптера и «мешательность» (0 — обычный, 3 — VPN/WARP)."""
    hay = " ".join(n for n in names if n).lower()
    best_kind, best_risk = "сетевой адаптер", 1
    for needle, kind, risk in LAN_KEYWORDS:
        if needle in hay:
            if risk >= best_risk or best_kind == "сетевой адаптер":
                best_kind, best_risk = kind, risk
            if risk == 3:
                break
    return best_kind, best_risk


def is_local_ip(ip: str, local_ips: Iterable[str]) -> bool:
    if not ip:
        return True
    if ip.startswith("127.") or ip in ("::1", "localhost"):
        return True
    if ip.startswith("169.254."):
        # APIPA-адрес: с точки зрения ноутбука он «свой», но для телефона — нет.
        return ip in set(local_ips or [])
    return ip in set(local_ips or [])


def is_apipa(ip: str) -> bool:
    return ip.startswith("169.254.")


def subnet_of(ip: str, prefix: int) -> Optional[ipaddress.IPv4Network]:
    try:
        net = ipaddress.ip_network(f"{ip}/{int(prefix)}", strict=False)
        return net  # type: ignore[return-value]
    except Exception:
        return None


def in_same_subnet(ip_a: str, ip_b: str, prefix: int = 24) -> Optional[bool]:
    """Лежат ли два адреса в одной подсети (по указанной длине префикса)."""
    try:
        a = ipaddress.ip_address(ip_a)
        b = ipaddress.ip_address(ip_b)
    except ValueError:
        return None
    if a.version != 4 or b.version != 4:
        return None
    net = subnet_of(str(a), prefix)
    if net is None:
        return None
    return b in net


def primary_local_ip() -> Optional[str]:
    """Адрес, с которого ноутбук выходит «наружу» — обычно это и есть нужный IP."""
    for probe in (("8.8.8.8", 53), ("1.1.1.1", 53), ("192.168.0.1", 80)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0.6)
            s.connect(probe)
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            continue
        finally:
            try:
                s.close()
            except Exception:
                pass
    return None


def all_local_ips() -> List[str]:
    """Все IPv4-адреса машины (без 127.*)."""
    ips: List[str] = []
    # 1) Через имя хоста.
    try:
        host = socket.gethostname()
        for item in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    # 2) Через UDP-трюк (даёт основной адрес).
    ip = primary_local_ip()
    if ip and ip not in ips:
        ips.insert(0, ip)

    # 3) Windows: полный список из PowerShell (учитывает все адаптеры).
    facts = NET_FACTS
    for row in facts.get("ipaddresses", []) or []:
        candidate = str(row.get("IPAddress") or "").strip()
        if candidate and not candidate.startswith("127.") and candidate not in ips:
            ips.append(candidate)
    return ips


def rank_local_ips(diag_or_facts: Any) -> List[Dict[str, Any]]:
    """
    Сортирует адреса ноутбука по «пригодности для телефона».

    Почему это важно: на ноутбуке легко оказывается 5–7 адресов (Wi-Fi, точка доступа
    Windows 192.168.137.1, VMware, Bluetooth, APIPA). Первый из них может не иметь
    никакого отношения к вашей Wi-Fi сети — на реальном запуске QR-код и подсказка
    показали 192.168.137.1 (мобильный хот-спот), и телефон туда не попал.

    Порядок (score меньше — лучше):
      0 — адрес на интерфейсе с маршрутом по умолчанию (это ваша сеть);
      1 — другой адрес из той же подсети, что и основной;
      2 — служебные адреса (точка доступа Windows, VMware, Bluetooth);
      3 — APIPA 169.254.* (роутер не выдал адрес).
    """
    facts = (diag_or_facts.facts if isinstance(diag_or_facts, Diag) else diag_or_facts) or {}
    rows = [r for r in (facts.get("ipaddresses") or []) if isinstance(r, dict)]
    adapters: Dict[str, Dict[str, Any]] = {}
    for a in (facts.get("adapters") or []):
        if isinstance(a, dict):
            adapters[str(a.get("Name") or "")] = a

    defaults = [r for r in (facts.get("default_routes") or []) if isinstance(r, dict)]
    default_alias = str(defaults[0].get("InterfaceAlias") or "") if defaults else ""
    primary = str(facts.get("primary_ip") or "")
    primary_net = subnet_of(primary, 24) if primary else None

    result: List[Dict[str, Any]] = []
    for row in rows:
        ip = str(row.get("IPAddress") or "").strip()
        if not ip or ip.startswith("127."):
            continue
        alias = str(row.get("InterfaceAlias") or "")
        adapter = adapters.get(alias, {})
        desc = str(adapter.get("InterfaceDescription") or "")
        kind, risk = classify_adapter(alias, desc)
        if "wi-fi direct" in (alias + " " + desc).lower() or is_ics_ip(ip):
            kind, risk = "точка доступа Windows (мобильный хот-спот)", 2
        try:
            state_ok = int(row.get("AddressState")) == 4 if row.get("AddressState") is not None else True
        except (TypeError, ValueError):
            state_ok = True

        if is_apipa(ip):
            score, reason = 3, "адрес-заглушка 169.254.* (DHCP не сработал)"
        elif alias and alias == default_alias:
            score, reason = 0, "ваша основная сеть (через неё идёт интернет)"
        else:
            try:
                in_primary = (primary_net is not None and
                              ipaddress.ip_address(ip) in primary_net)
            except ValueError:
                in_primary = False
            if in_primary:
                score, reason = 1, "та же подсеть, что и основная сеть"
            elif not defaults and risk < 2:
                score, reason = 1, "обычный адрес ноутбука (данных о маршрутах нет)"
            elif risk >= 2:
                score, reason = 2, f"служебный адаптер: {kind}"
            else:
                score, reason = 2, f"другой интерфейс: {kind}"

        if not state_ok:
            score += 1
            reason += "; адрес не в состоянии Preferred"
        result.append({"ip": ip, "alias": alias, "kind": kind, "score": score,
                       "reason": reason, "apipa": is_apipa(ip), "ics": is_ics_ip(ip)})

    result.sort(key=lambda r: (r["score"], r["ip"]))
    return result


def recommended_ips(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Адреса, которые имеет смысл показывать телефону (без APIPA и служебных)."""
    ranking = rank_local_ips(facts)
    best = [r for r in ranking
            if r["score"] <= 1 and not r["apipa"] and not r["ics"]]
    if best:
        return best
    # Данных мало или всё служебное: лучше честно ничего не советовать
    # (раньше здесь возвращался APIPA-адрес, и телефон получал заведомо мёртвую ссылку).
    return [r for r in ranking if not r["apipa"] and not r["ics"] and r["score"] <= 2]


# «Мировые» факты о сети, собранные один раз (просто кэш, чтобы не спрашивать Windows повторно).
NET_FACTS: Dict[str, Any] = {}


# =========================================================================================
#  6. СБОР КОНФИГУРАЦИИ WINDOWS (PowerShell-секции)
# =========================================================================================

PS_SECTIONS_FAST: List[Tuple[str, str]] = [
    ("os", r"""
[ordered]@{
  version   = [Environment]::OSVersion.VersionString
  psversion = "$($PSVersionTable.PSVersion)"
  admin     = ([Security.Principal.WindowsPrincipal] `
                [Security.Principal.WindowsIdentity]::GetCurrent()
              ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  computer  = $env:COMPUTERNAME
  user      = $env:USERNAME
}
"""),
    ("adapters", r"""
Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, MacAddress,
    LinkSpeed, ifIndex, InterfaceOperationalStatus | Sort-Object ifIndex
"""),
    ("ipaddresses", r"""
Get-NetIPAddress -AddressFamily IPv4 |
  Select-Object IPAddress, PrefixLength, InterfaceAlias, InterfaceIndex,
    AddressState, PrefixOrigin, SuffixOrigin, SkipAsSource |
  Sort-Object InterfaceIndex
"""),
    ("ipv6", r"""
Get-NetIPAddress -AddressFamily IPv6 |
  Where-Object { $_.IPAddress -notlike 'fe80*' -and $_.IPAddress -ne '::1' } |
  Select-Object IPAddress, PrefixLength, InterfaceAlias, InterfaceIndex |
  Sort-Object InterfaceIndex
"""),
    ("profiles", r"""
Get-NetConnectionProfile | Select-Object InterfaceAlias, Name,
  @{n='Category';e={[int]$_.NetworkCategory}},
  @{n='CategoryText';e={"$($_.NetworkCategory)"}},
  @{n='IPv4';e={"$($_.IPv4Connectivity)"}},
  @{n='IPv6';e={"$($_.IPv6Connectivity)"}}
"""),
    ("ifaces", r"""
Get-NetIPInterface -AddressFamily IPv4 |
  Select-Object InterfaceAlias, InterfaceIndex, InterfaceMetric, ConnectionState,
    Dhcp, NlMtu, @{n='Forwarding';e={"$($_.Forwarding)"}} |
  Sort-Object InterfaceIndex
"""),
    ("routes", r"""
Get-NetRoute -AddressFamily IPv4 |
  Select-Object DestinationPrefix, NextHop, InterfaceAlias, InterfaceIndex,
    RouteMetric, @{n='Protocol';e={"$($_.Protocol)"}},
    @{n='Store';e={"$($_.PolicyStore)"}} |
  Sort-Object InterfaceIndex, DestinationPrefix
"""),
    ("listeners", r"""
$procs = @{}
Get-Process | ForEach-Object { $procs[[int]$_.Id] = [ordered]@{
    name = $_.ProcessName; path = "$($_.Path)" } }
$rows = @()
Get-NetTCPConnection -State Listen | ForEach-Object {
    $pid2 = [int]$_.OwningProcess
    $p = $procs[$pid2]
    $rows += [ordered]@{
        address = "$($_.LocalAddress)"; port = [int]$_.LocalPort; pid = $pid2
        name = $(if ($p) { $p.name } else { '' })
        path = $(if ($p) { $p.path } else { '' })
        v6 = ($_.LocalAddress -like '*:*')
    }
}
$rows
"""),
    ("python_procs", r"""
Get-CimInstance Win32_Process -Filter "Name LIKE '%python%' OR Name LIKE '%py.exe%'" |
  Select-Object ProcessId, Name, ExecutablePath, CommandLine
"""),
    ("py_versions", r"""
$out = @()
try { $out = @(& py -0p 2>$null) } catch {}
if ($out.Count -eq 0) { try { $out = @(& py --list-paths 2>$null) } catch {} }
if ($out.Count -eq 0) { $out = @('py launcher не найден — список версий недоступен') }
$out
"""),
    ("vpn_procs", r"""
Get-Process | Where-Object {
    $_.ProcessName -match 'warp|cloudflare|wireguard|openvpn|proton|nord|surfshark|expressvpn|windscribe|mullvad|tunnelbear|anyconnect|globalprotect|forticlient|zscaler|v2ray|xray|sing-box|nekoray|clash|hiddify|shadowsocks|outline|amnezia|softether|tapctl'
} | Select-Object ProcessName, Id, Path
"""),
    ("vpn_services", r"""
Get-Service | Where-Object {
    $_.Name -match 'warp|cloudflare|wireguard|openvpn|proton|nord|surfshark|expressvpn|windscribe|mullvad|tunnelbear|anyconnect|globalprotect|forticlient|zscaler|v2ray|xray|sing-box|nekoray|clash|hiddify|shadowsocks|outline|amnezia|softether|tap|tun'
} | Select-Object Name, DisplayName, Status, StartType
"""),
    ("av_products", r"""
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct |
  Select-Object displayName, pathToSignedProductExe, productState
"""),
    ("av_services", r"""
Get-Service | Where-Object {
    $_.Name -match 'avp|kav|ekrn|avast|avg|mbam|drweb|sophos|eset|bitdefender|kaspersky|norton|mcafee|trendmicro|comodo|360|huorong|adguard'
} | Select-Object Name, DisplayName, Status
"""),
    ("neighbors", r"""
Get-NetNeighbor -AddressFamily IPv4 |
  Where-Object { $_.State -ne 'Permanent' } |
  Select-Object IPAddress, LinkLayerAddress, @{n='State';e={"$($_.State)"}}, InterfaceAlias
"""),
    ("dns", r"""
Get-DnsClientServerAddress -AddressFamily IPv4 |
  Select-Object InterfaceAlias, InterfaceIndex, ServerAddresses
"""),
    ("warp_hidden", r"""
Get-NetAdapter -IncludeHidden | Where-Object {
    $_.Name -match 'warp|wireguard|cloudflare' -or
    $_.InterfaceDescription -match 'warp|wireguard|cloudflare'
} | Select-Object Name, InterfaceDescription, Status, AdminStatus
"""),
    ("ics_service", r"""
Get-Service SharedAccess, icssvc -ErrorAction SilentlyContinue |
  Select-Object Name, DisplayName, Status, StartType
"""),
    ("warp_cli", r"""
$candidates = @(
  "$env:ProgramFiles\Cloudflare\Cloudflare WARP\warp-cli.exe",
  "$env:LOCALAPPDATA\Programs\Cloudflare\Cloudflare WARP\warp-cli.exe"
)
$exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($exe) {
    $out = & $exe --no-ansi status 2>&1 | Out-String
    [ordered]@{ exe = $exe; output = $out.Trim() }
} else {
    [ordered]@{ exe = ""; output = "warp-cli.exe не найден" }
}
"""),
    ("metered", r"""
$c = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\NetworkList\DefaultMediaCost'
if ($c) { [ordered]@{ wifi = $c.WiFi; ethernet = $c.Ethernet; mobile = $c.Mobile } }
"""),
]

PS_SECTIONS_FIREWALL: List[Tuple[str, str]] = [
    ("firewall", r"""
Get-NetFirewallProfile | Select-Object Name,
  @{n='Enabled';e={[int]$_.Enabled}},
  @{n='DefaultInbound';e={[int]$_.DefaultInboundAction}},
  @{n='DefaultOutbound';e={[int]$_.DefaultOutboundAction}},
  @{n='AllowInboundRules';e={[int]$_.AllowInboundRules}},
  @{n='AllowLocalRules';e={[int]$_.AllowLocalFirewallRules}},
  @{n='AllowUnicastResponse';e={[int]$_.AllowUnicastResponseToMulticast}},
  @{n='NotifyOnListen';e={[int]$_.NotifyOnListen}},
  @{n='LogBlocked';e={[int]$_.LogBlocked}},
  @{n='LogFile';e={$_.LogFileName}}
"""),
    ("fw_python_rules", r"""
Get-NetFirewallApplicationFilter | Where-Object {
    $_.Program -and ($_.Program -match 'python|py\.exe')
} | ForEach-Object {
    $flt = $_
    Get-NetFirewallRule -Name $flt.InstanceID -ErrorAction SilentlyContinue |
      ForEach-Object {
        $r = $_
        $af = $r | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
        $pf = $r | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
        [pscustomobject]@{
          Program       = $flt.Program
          DisplayName   = $r.DisplayName
          Enabled       = "$($r.Enabled)"
          Direction     = "$($r.Direction)"
          Action        = "$($r.Action)"
          Profile       = "$($r.Profile)"
          RemoteAddress = (@($af.RemoteAddress) -join ', ')
          LocalPort     = (@($pf.LocalPort) -join ', ')
          Protocol      = "$($pf.Protocol)"
          Name          = "$($r.Name)"
        }
      }
}
"""),
    ("fw_netdoctor_rules", r"""
Get-NetFirewallRule -DisplayName 'netdoctor*' |
  Select-Object DisplayName, Enabled, @{n='Direction';e={"$($_.Direction)"}},
    @{n='Action';e={"$($_.Action)"}}, @{n='Profile';e={"$($_.Profile)"}}
"""),
]


def collect_windows_facts(diag: Diag, verbose: bool = True) -> None:
    """Читает конфигурацию Windows и складывает её в diag.facts."""
    facts: Dict[str, Any] = {}

    fast = ps_collect(PS_SECTIONS_FAST, timeout=120.0)
    facts["ps_fast_raw"] = fast
    if not fast:
        diag.add("ps_collect", "Чтение конфигурации Windows", "warn",
                 "PowerShell не ответил — глубокая диагностика недоступна",
                 "Проверьте, что PowerShell запускается: "
                 'powershell -NoProfile -Command "$PSVersionTable"')

    def sec(name: str) -> Any:
        block = fast.get(name) or {}
        data = block.get("data")
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        return data

    for key in ("os", "adapters", "ipaddresses", "ipv6", "profiles", "ifaces",
                "routes", "listeners", "python_procs", "vpn_procs", "vpn_services",
                "av_products", "av_services", "neighbors", "dns", "metered",
                "warp_hidden", "ics_service", "warp_cli", "py_versions"):
        facts[key] = sec(key)

    fw = ps_collect(PS_SECTIONS_FIREWALL, timeout=180.0)
    facts["ps_fw_raw"] = fw
    for key in ("firewall", "fw_python_rules", "fw_netdoctor_rules"):
        block = fw.get(key) or {}
        data = block.get("data")
        facts[key] = ([] if data is None
                      else ([data] if isinstance(data, dict) else data))

    # ---- то, что снимаем обычными командами -------------------------------------
    facts["wlan"] = cmd_text(["netsh", "wlan", "show", "interfaces"], timeout=25)
    facts["wlan_ssid"] = parse_netsh_ssid(facts["wlan"])
    facts["winhttp_proxy"] = cmd_text(["netsh", "winhttp", "show", "proxy"], timeout=25)
    facts["inet_proxy"] = read_inet_proxy()
    facts["hosts"] = read_hosts_file()
    facts["warp"] = detect_warp()
    facts["hostname"] = socket.gethostname()
    NET_FACTS.clear()
    NET_FACTS.update(facts)
    facts["ips"] = all_local_ips()
    facts["primary_ip"] = primary_local_ip()
    facts["gateway_hint"] = guess_gateway(facts.get("routes") or [])

    diag.facts.update(facts)
    NET_FACTS.clear()
    NET_FACTS.update(facts)


def collect_posix_facts(diag: Diag) -> None:
    """Минимальный набор фактов для Linux/macOS (чтобы можно было тестировать и там)."""
    facts: Dict[str, Any] = {"os": [{"version": platform.platform(), "admin": is_admin(),
                                     "computer": socket.gethostname(),
                                     "user": os.environ.get("USER", "")}]}
    facts["ipaddresses"] = parse_ip_addr_output()
    facts["routes"] = parse_ip_route_output()
    facts["adapters"] = [{"Name": a.get("InterfaceAlias", "?"),
                          "InterfaceDescription": a.get("InterfaceAlias", "?"),
                          "Status": "Up"} for a in facts["ipaddresses"]]
    facts["profiles"] = []
    facts["firewall"] = []
    facts["listeners"] = parse_ss_output()
    facts["neighbors"] = parse_ip_neigh_output()
    facts["hostname"] = socket.gethostname()
    NET_FACTS.clear()
    NET_FACTS.update(facts)          # чтобы all_local_ips() увидел все интерфейсы
    facts["ips"] = all_local_ips()
    facts["primary_ip"] = primary_local_ip()
    facts["hosts"] = read_hosts_file()
    diag.facts.update(facts)
    NET_FACTS.clear()
    NET_FACTS.update(facts)


def parse_ip_addr_output() -> List[Dict[str, Any]]:
    """Разбор `ip -o -4 addr show` -> строки, похожие на вывод Windows."""
    rows: List[Dict[str, Any]] = []
    rc, out, err = run(["ip", "-o", "-4", "addr", "show"], timeout=10)
    if rc != 0:
        rc, out, err = run(["ifconfig"], timeout=10)
        if rc != 0:
            return rows
    for line in out.splitlines():
        m = re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m:
            rows.append({"InterfaceAlias": m.group(1), "IPAddress": m.group(2),
                         "PrefixLength": int(m.group(3)), "AddressState": "Preferred",
                         "InterfaceIndex": 0})
    return rows


def parse_ip_route_output() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rc, out, err = run(["ip", "-4", "route", "show"], timeout=10)
    if rc != 0:
        return rows
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        rows.append({"DestinationPrefix": parts[0], "NextHop": parts[1] if "via" in parts else "",
                     "InterfaceAlias": parts[-1], "RouteMetric": 0})
    return rows


def parse_ss_output() -> List[Dict[str, Any]]:
    """Список слушающих сокетов через `ss -lntp` (или netstat)."""
    rows: List[Dict[str, Any]] = []
    rc, out, err = run(["ss", "-lntp"], timeout=10)
    if rc != 0:
        rc, out, err = run(["netstat", "-lntp"], timeout=10)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].lower() in ("state", "netid", "протокол"):
            continue
        local = parts[3] if parts[0].lower() != "tcp" else parts[4]
        if ":" not in local:
            continue
        addr, _, port_txt = local.rpartition(":")
        try:
            port = int(port_txt)
        except ValueError:
            continue
        pid = 0
        m = re.search(r"pid=(\d+)", line)
        if m:
            pid = int(m.group(1))
        m = re.search(r'\("([^"]+)"', line)
        rows.append({"address": addr.strip("[]"), "port": port, "pid": pid,
                     "name": m.group(1) if m else "", "path": "",
                     "v6": ":" in addr})
    return rows


def parse_ip_neigh_output() -> List[Dict[str, Any]]:
    """Соседи по сети (ARP) на Linux: `ip neigh`."""
    rows: List[Dict[str, Any]] = []
    rc, out, err = run(["ip", "-4", "neigh"], timeout=10)
    if rc != 0:
        return rows
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        row = {"IPAddress": parts[0], "LinkLayerAddress": "", "State": "",
               "InterfaceAlias": parts[-1] if len(parts) > 2 else ""}
        for i, token in enumerate(parts):
            if token == "lladdr" and i + 1 < len(parts):
                row["LinkLayerAddress"] = parts[i + 1]
        if "REACHABLE" in line:
            row["State"] = "Reachable"
        elif "STALE" in line:
            row["State"] = "Stale"
        elif "INCOMPLETE" in line:
            row["State"] = "Incomplete"
        elif "FAILED" in line:
            row["State"] = "Unreachable"
        rows.append(row)
    return rows


def parse_netsh_ssid(text: str) -> Dict[str, str]:
    """
    Вытаскивает SSID/сигнал из `netsh wlan show interfaces`.
    Вывод локализован, но метки всегда содержат латинские SSID / State / Signal,
    поэтому разбираем максимально терпимо.
    """
    result: Dict[str, str] = {}
    if not text:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label_l, value = label.strip().lower(), value.strip()
        if not value:
            continue
        if "ssid" in label_l and "bssid" not in label_l:
            result.setdefault("ssid", value)
        elif "bssid" in label_l:
            result["bssid"] = value
        elif "signal" in label_l or "сигнал" in label_l:
            result["signal"] = value
        elif ("radio" in label_l or "радио" in label_l
              or "band" in label_l or "диапазон" in label_l):
            result.setdefault("band", value)
        elif "state" in label_l or "состояние" in label_l:
            result["state"] = value
        elif "channel" in label_l or "канал" in label_l:
            result["channel"] = value
    return result


def read_inet_proxy() -> Dict[str, Any]:
    """Системный прокси пользователя (WinINET). Именно его использует браузер."""
    if not IS_WINDOWS:
        return {}
    ps = which_powershell()
    if not ps:
        return {}
    out = ps_one(r"""
$p = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
[ordered]@{
  enabled     = $p.ProxyEnable
  server      = "$($p.ProxyServer)"
  override    = "$($p.ProxyOverride)"
  autoconfig  = "$($p.AutoConfigURL)"
  autodetect  = $p.AutoDetect
} | ConvertTo-Json -Compress
""", timeout=45)
    data = extract_json(out or "")
    return data if isinstance(data, dict) else {}


def read_hosts_file() -> List[str]:
    """Нестандартные записи в файле hosts (без комментариев)."""
    paths = []
    if IS_WINDOWS:
        paths.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                  r"System32\drivers\etc\hosts"))
    paths += ["/etc/hosts"]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = [ln.strip() for ln in fh]
            active = [ln for ln in lines if ln and not ln.startswith("#")]
            return active
        except OSError:
            continue
    return []


def detect_warp() -> Dict[str, Any]:
    """
    Ищет следы Cloudflare WARP / 1.1.1.1:
    адаптеры, службы, процессы, конфиг и логи в ProgramData, DNS 127.0.0.1.
    """
    info: Dict[str, Any] = {"found": [], "paths": {}, "dns_localhost": False}
    paths = [
        r"C:\ProgramData\Cloudflare\Cloudflare WARP\conf.json",
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                     "Cloudflare", "Cloudflare WARP", "conf.json"),
    ]
    for path in paths:
        if os.path.isfile(path):
            info["paths"][path] = True
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    info["conf"] = fh.read()[:4000]
            except OSError:
                pass
    # Каталог с логами тоже говорит о том, что WARP стоял/стоит.
    for extra in ("Cloudflare WARP.exe", "warp-svc.exe"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidate = os.path.join(base, "Cloudflare", "Cloudflare WARP", extra)
            if os.path.isfile(candidate):
                info["found"].append(candidate)
    return info


def guess_gateway(routes: Sequence[Dict[str, Any]]) -> str:
    """Шлюз по умолчанию с лучшей (наименьшей) метрикой."""
    best, best_metric = "", 10 ** 9
    for row in routes or []:
        if str(row.get("DestinationPrefix")) != "0.0.0.0/0":
            continue
        try:
            metric = int(row.get("RouteMetric") or 0)
        except (TypeError, ValueError):
            metric = 0
        if metric < best_metric:
            best, best_metric = str(row.get("NextHop") or ""), metric
    return best


# =========================================================================================
#  7. ПРОВЕРКИ (СТАДИИ)
# =========================================================================================

def check_env(diag: Diag) -> None:
    os_rows = diag.facts.get("os") or [{}]
    os_info = os_rows[0] if isinstance(os_rows[0], dict) else {}
    diag.facts["admin"] = bool(os_info.get("admin")) or is_admin()
    diag.facts["os_version"] = os_info.get("version") or platform.platform()
    diag.add("env_os", "Система и права",
             "ok" if diag.facts["admin"] else "warn",
             f"{diag.facts['os_version']} · Python {platform.python_version()} · "
             f"{'администратор' if diag.facts['admin'] else 'обычный пользователь'}",
             "" if diag.facts["admin"] else
             "Для починки брандмауэра понадобятся права администратора — "
             "запустите от имени администратора или воспользуйтесь netdoctor_fix.ps1 "
             "(он сам попросит права).")


def check_adapters(diag: Diag) -> None:
    """Разбор адаптеров: ищем VPN/WARP/Hyper-V, которые могут ломать доступ из LAN."""
    adapters = diag.facts.get("adapters") or []
    diag.facts["adapter_kinds"] = {}
    suspicious: List[str] = []
    for row in adapters:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "")
        desc = str(row.get("InterfaceDescription") or "")
        kind, risk = classify_adapter(name, desc)
        diag.facts["adapter_kinds"][name or desc] = {"kind": kind, "risk": risk,
                                                     "status": row.get("Status")}
        if risk >= 2 and str(row.get("Status") or "").lower().startswith("up"):
            suspicious.append(f"{name} ({kind})")

    if suspicious:
        diag.add("adapters_vpn", "Виртуальные адаптеры сети", "warn",
                 "работают: " + ", ".join(suspicious),
                 "Туннель/VPN/виртуальная сеть в состоянии Up. Такие адаптеры перехватывают "
                 "входящие ответы: телефон стучится, а ответ уходит «в туннель». "
                 "Отключите WARP/VPN и повторите тест — это самый быстрый способ проверить.")
    else:
        diag.add("adapters_vpn", "Виртуальные адаптеры сети", "ok",
                 "мешающих VPN/WARP-адаптеров в состоянии Up нет")


def check_profiles(diag: Diag) -> None:
    """Профиль сети: Public = входящие блокируются по умолчанию."""
    profiles = [p for p in (diag.facts.get("profiles") or []) if isinstance(p, dict)]
    public = [p for p in profiles if int(p.get("Category") or 0) == 0]
    diag.facts["profile_public"] = [str(p.get("InterfaceAlias")) for p in public]

    if not profiles:
        diag.add("net_profile", "Профиль сети Windows", "skip",
                 "не удалось прочитать (нет Get-NetConnectionProfile)")
        return

    parts = []
    for p in profiles:
        cat = int(p.get("Category") or 0)
        label = {0: "Public (общедоступная)", 1: "Private (частная)",
                 2: "DomainAuthenticated"}.get(cat, str(p.get("CategoryText")))
        parts.append(f"{p.get('InterfaceAlias')}: {label}")
    detail = " · ".join(parts)

    if public:
        names = ", ".join(str(p.get("InterfaceAlias")) for p in public)
        diag.add("net_profile", "Профиль сети Windows", "warn", detail,
                 f"Сеть «{names}» считается общедоступной: Windows режет входящие "
                 "подключения, если нет отдельного разрешения. После отпуска/отеля это "
                 "случается чаще всего. Починка: переключить профиль на Private.",
                 fix_ps=[f"Set-NetConnectionProfile -InterfaceAlias '{names}' "
                         "-NetworkCategory Private"])
    else:
        diag.add("net_profile", "Профиль сети Windows", "ok", detail)


FIREWALL_ACTION = {0: "NotConfigured (по факту = блокировать, нужны разрешающие правила)",
                   1: "Allow (разрешать)", 2: "Block (блокировать)"}
FIREWALL_ENABLED = {0: "False", 1: "True"}


def check_firewall(diag: Diag) -> None:
    """Брандмауэр: включён, что с входящими, есть ли разрешение для python.exe."""
    rows = [r for r in (diag.facts.get("firewall") or []) if isinstance(r, dict)]
    if not rows:
        diag.add("firewall_state", "Брандмауэр Windows", "skip",
                 "не удалось прочитать (нет Get-NetFirewallProfile)")
        return

    blocking_profiles: List[str] = []
    all_blocked_profiles: List[str] = []
    summary = []
    for r in rows:
        name = str(r.get("Name"))
        enabled = r.get("Enabled")
        allow_rules = r.get("AllowInboundRules")
        default_in = r.get("DefaultInbound")
        is_enabled = str(enabled) in ("1", "True")
        state = "включён" if is_enabled else "выключен"
        default_txt = FIREWALL_ACTION.get(int(default_in or 0), str(default_in))
        summary.append(f"{name}: {state}, входящие по умолчанию — {default_txt}")
        if is_enabled and str(allow_rules) in ("0", "False"):
            all_blocked_profiles.append(name)
        elif is_enabled and str(default_in) in ("2",):   # Action.Block == 2
            blocking_profiles.append(name)

    diag.facts["firewall_all_inbound_blocked"] = all_blocked_profiles
    diag.facts["firewall_default_block"] = blocking_profiles
    detail = " · ".join(summary)

    if all_blocked_profiles:
        diag.add("firewall_state", "Брандмауэр Windows", "bad", detail,
                 "Включён режим «блокировать все входящие подключения» для профиля "
                 f"{', '.join(all_blocked_profiles)} — в этом режиме не помогают даже "
                 "правила-разрешения. Нужно снять галочку «Блокировать все входящие "
                 "подключения» в свойствах брандмауэра (или в оснастке wf.msc).")
    elif blocking_profiles:
        diag.add("firewall_state", "Брандмауэр Windows", "warn", detail,
                 "Входящие по умолчанию запрещены. Значит должен существовать явный "
                 "разрешающий правило для python.exe на нужном профиле сети — "
                 "проверьте строку ниже и при необходимости создайте правило.")
    else:
        diag.add("firewall_state", "Брандмауэр Windows", "ok", detail)

    # ---- правила для python.exe ---------------------------------------------------
    rules = [r for r in (diag.facts.get("fw_python_rules") or []) if isinstance(r, dict)]
    allow_in = []
    for r in rules:
        action = str(r.get("Action") or "")
        direction = str(r.get("Direction") or "")
        if direction.lower().startswith("in") and action.lower().startswith("allow"):
            if str(r.get("Enabled")) in ("1", "True"):
                allow_in.append(r)
    diag.facts["fw_python_allow_in"] = allow_in

    # Важно: правило может быть разрешающим, но ограниченным другим адресом
    # (например, подсетью мобильного хот-спота 192.168.137.0/24). Тогда внешне
    # «16 разрешающих правил», а из вашей Wi-Fi сети доступ закрыт.
    primary = str(diag.facts.get("primary_ip") or "")
    prefix = 24
    for row in (diag.facts.get("ipaddresses") or []):
        if isinstance(row, dict) and str(row.get("IPAddress")) == primary:
            try:
                prefix = int(row.get("PrefixLength") or 24)
            except (TypeError, ValueError):
                prefix = 24
    primary_net = subnet_of(primary, prefix) if primary else None

    def rule_covers_primary(r: Dict[str, Any]) -> bool:
        remote = str(r.get("RemoteAddress") or "").strip().lower()
        if not remote or "any" in remote or "localsubnet" in remote:
            return True
        if primary_net is None:
            return True
        for token in re.split(r"[,\s]+", remote):
            token = token.strip()
            if not token:
                continue
            try:
                if "/" in token:
                    if ipaddress.ip_network(token, strict=False).overlaps(primary_net):
                        return True
                elif ipaddress.ip_address(token) in primary_net:
                    return True
            except ValueError:
                # ключевые слова Windows: LocalSubnet, DNS, DefaultGateway, DHCP, WSL ...
                if token in ("localsubnet", "wlan", "wireless"):
                    return True
                continue
        return False

    covering = [r for r in allow_in if rule_covers_primary(r)]
    not_covering = [r for r in allow_in if rules and not rule_covers_primary(r)]
    diag.facts["fw_python_covering"] = [
        {"DisplayName": r.get("DisplayName"), "RemoteAddress": r.get("RemoteAddress"),
         "LocalPort": r.get("LocalPort"), "Profile": r.get("Profile")}
        for r in covering
    ]
    diag.facts["fw_python_scoped_other"] = [
        {"DisplayName": r.get("DisplayName"), "RemoteAddress": r.get("RemoteAddress"),
         "LocalPort": r.get("LocalPort"), "Profile": r.get("Profile")}
        for r in not_covering
    ]
    if primary and covering == [] and allow_in:
        diag.add("firewall_python_scope", "Покрытие вашей подсети правилами", "bad",
                 f"разрешающих правил: {len(allow_in)}, из них покрывают "
                 f"{primary}/{prefix}: 0 · примеры чужих подсетей: "
                 + ", ".join(str(r.get("RemoteAddress")) or "?"
                             for r in not_covering[:3]),
                 "Правила для python.exe есть, но ни одно не разрешает подключения "
                 f"из вашей сети ({primary}/{prefix}). Так бывает, если правило создавалось "
                 "в другой сети (например, в подсети мобильного хот-спота 192.168.137.0/24). "
                 "Быстрая починка: python net_doctor.py --fix — он создаёт правило с "
                 "RemoteAddress LocalSubnet, которое покрывает любую домашнюю сеть.")
    elif covering:
        diag.add("firewall_python_scope", "Покрытие вашей подсети правилами", "ok",
                 f"покрывают {primary}/{prefix}: {len(covering)} правил(о)")

    if allow_in:
        names = {str(r.get("Program") or "") for r in allow_in}
        profiles = {str(r.get("Profile") or "") for r in allow_in}
        diag.add("firewall_python", "Разрешение для python.exe", "ok",
                 f"правил: {len(allow_in)} · профили: {', '.join(sorted(profiles)) or '?'} · "
                 f"{', '.join(sorted(n for n in names if n))[:120]}")
    else:
        diag.add("firewall_python", "Разрешение для python.exe", "warn",
                 "разрешающих входящих правил для python.exe не найдено",
                 "Когда Python-сервер впервые слушает порт, Windows спрашивает "
                 "«Разрешить доступ?». Если когда-то нажать «Отмена» (или правило было "
                 "только для профиля Private, а сеть стала Public) — входящие молча "
                 "режутся. Быстрая починка: net_doctor.py --fix (правило для локальной "
                 "подсети на нужный порт).")


def check_routes(diag: Diag) -> None:
    """Маршруты и метрики: несколько «шлюзов по умолчанию» = риск перепутанных ответов."""
    routes = [r for r in (diag.facts.get("routes") or []) if isinstance(r, dict)]
    ifaces = [r for r in (diag.facts.get("ifaces") or []) if isinstance(r, dict)]
    defaults = [r for r in routes if str(r.get("DestinationPrefix")) == "0.0.0.0/0"]
    diag.facts["default_routes"] = defaults

    metrics: Dict[str, int] = {}
    for row in ifaces:
        try:
            metrics[str(row.get("InterfaceAlias"))] = int(row.get("InterfaceMetric") or 0)
        except (TypeError, ValueError):
            pass
    diag.facts["interface_metrics"] = metrics

    if not defaults:
        diag.add("routes", "Маршруты по умолчанию", "warn",
                 "шлюза по умолчанию не видно",
                 "Без маршрута по умолчанию ноутбук может быть отрезан от части сети.")
        return

    shown = []
    for r in defaults:
        alias = str(r.get("InterfaceAlias"))
        shown.append(f"{alias} → {r.get('NextHop')} (метрика "
                     f"{r.get('RouteMetric')}, интерфейс {metrics.get(alias, '?')})")

    if len(defaults) == 1:
        diag.add("routes", "Маршруты по умолчанию", "ok", shown[0])
    else:
        diag.add("routes", "Маршруты по умолчанию", "warn",
                 f"{len(defaults)} штук: " + " · ".join(shown),
                 "Несколько выходов в интернет (Wi-Fi + VPN/WARP/Hyper-V). Само по себе "
                 "не смертельно, но ответ подключившемуся телефону может уйти «не в ту "
                 "дверь». Отключите лишние адаптеры и повторите тест.")


def check_proxy(diag: Diag) -> None:
    """Системный прокси: WARP-прокси 127.0.0.1:40000 умеет ломать локальные адреса."""
    inet = diag.facts.get("inet_proxy") or {}
    winhttp = diag.facts.get("winhttp_proxy") or ""
    enabled = bool(inet.get("enabled"))
    server = str(inet.get("server") or "")
    override = str(inet.get("override") or "")

    problems = []
    if enabled and server:
        # Если 192.168.x.x не в списке исключений — браузер пошлёт его в прокси.
        override_l = override.lower()
        lan_included = "192.168" in override_l or "<local>" in override_l or "10." in override_l
        problems.append(f"прокси включён: {server}"
                        + ("" if lan_included else "; локальные адреса (192.168.*) "
                           "НЕ в исключениях"))
    if "127.0.0.1" in winhttp or "40000" in winhttp:
        problems.append("WinHTTP-прокси указывает на локальный порт (это типично для WARP)")

    diag.facts["proxy_enabled"] = bool(enabled and server)

    if problems:
        diag.add("proxy", "Системный прокси", "warn", " | ".join(problems),
                 "Прокси может перехватывать обращения браузера к 192.168.x.x. "
                 "Проверьте: Параметры → Сеть и Интернет → Прокси (должно быть выключено, "
                 "если вы не используете прокси осознанно). WARP-прокси живёт на "
                 "127.0.0.1:40000 — если он остался после удаления WARP, браузер будет "
                 "«глючить» только у ноутбука.")
    else:
        diag.add("proxy", "Системный прокси", "ok", "не мешает (прокси выключен)")


def check_warp(diag: Diag) -> None:
    """
    Cloudflare WARP: отдельно туннель и отдельно «фоновые» следы.

    Тонкость, на которой инструмент ошибался раньше: служба CloudflareWARP всегда
    работает в фоне, даже когда туннель отключён. Наличие службы и процессов —
    это НЕ признак активного VPN. Туннель подключён, только если есть его виртуальный
    адаптер (WireGuard/WARP) в состоянии Up, warp-cli сообщает Connected,
    или DNS/маршруты уведены на локальный адрес WARP.
    """
    facts = diag.facts
    tunnel: List[str] = []
    background: List[str] = []

    for row in (facts.get("warp_hidden") or []):
        if not isinstance(row, dict):
            continue
        status = str(row.get("Status") or "").lower()
        admin = str(row.get("AdminStatus") or "").lower()
        line = f"адаптер «{row.get('Name')}» ({row.get('InterfaceDescription')}) — {row.get('Status')}"
        if status.startswith("up"):
            tunnel.append(line)
        elif admin.startswith("up") or status:
            background.append(line)

    for row in (facts.get("adapters") or []):
        if not isinstance(row, dict):
            continue
        kind, risk = classify_adapter(str(row.get("Name") or ""),
                                      str(row.get("InterfaceDescription") or ""))
        if risk >= 3 and str(row.get("Status") or "").lower().startswith("up"):
            tunnel.append(f"адаптер «{row.get('Name')}» ({kind}) — Up")

    for row in (facts.get("routes") or []):
        if isinstance(row, dict) and re.search(r"warp|wireguard|cloudflare",
                                               str(row.get("InterfaceAlias") or ""), re.I):
            tunnel.append(f"маршрут через «{row.get('InterfaceAlias')}»")

    for row in (facts.get("dns") or []):
        if isinstance(row, dict):
            servers = row.get("ServerAddresses") or []
            if isinstance(servers, str):
                servers = [servers]
            if any(str(x).startswith("127.") for x in servers):
                tunnel.append(f"DNS 127.0.0.1 на «{row.get('InterfaceAlias')}» "
                              "(локальный DoH-прокси WARP)")

    cli = facts.get("warp_cli")
    cli_output = ""
    if isinstance(cli, list) and cli and isinstance(cli[0], dict):
        cli_output = str(cli[0].get("output") or "")
    elif isinstance(cli, dict):
        cli_output = str(cli.get("output") or "")
    cli_low = cli_output.lower()
    if cli_output and re.search(r"connected|подключ", cli_low) and not re.search(
            r"disconnected|not connected|отключ", cli_low):
        tunnel.append(f"warp-cli: {cli_output.splitlines()[0][:120]}")
    elif cli_output:
        first = cli_output.splitlines()[0][:120] if cli_output.splitlines() else cli_output[:120]
        background.append(f"warp-cli: {first}")

    for row in (facts.get("vpn_services") or []):
        if isinstance(row, dict) and re.search(r"warp|cloudflare", str(row.get("Name") or ""), re.I):
            background.append(f"служба {row.get('Name')} — "
                              f"{service_status_word(row.get('Status'))}")

    for row in (facts.get("vpn_procs") or []):
        if isinstance(row, dict) and re.search(r"warp|cloudflare",
                                               str(row.get("ProcessName") or ""), re.I):
            background.append(f"процесс {row.get('ProcessName')} (PID {row.get('Id')})")

    warp = facts.get("warp") or {}
    if warp.get("found") or warp.get("conf"):
        background.append("файлы/конфиг Cloudflare WARP на диске")

    facts["warp_tunnel_active"] = bool(tunnel)
    facts["warp_traces"] = list(dict.fromkeys(tunnel))
    facts["warp_background"] = list(dict.fromkeys(background))

    if tunnel:
        diag.add("warp", "Cloudflare WARP / VPN", "bad",
                 "; ".join(dict.fromkeys(tunnel)),
                 "Похоже, туннель WARP/VPN ПОДКЛЮЧЁН: есть его адаптер/маршрут/DNS. "
                 "В таком режиме входящие подключения из локальной сети часто не доходят. "
                 "Выйдите из WARP (трей → Disconnect/Quit), а лучше временно остановите "
                 "службу и повторите тест с телефоном.",
                 fix_ps=[
                     "Get-Service | Where-Object { $_.Name -match 'warp|cloudflare' } | "
                     "Select-Object Name,Status,StartType",
                     "# временная остановка для проверки (нужны права администратора):",
                     "Stop-Service -Name 'CloudflareWARP' -Force -ErrorAction SilentlyContinue",
                 ])
    elif background:
        diag.add("warp", "Cloudflare WARP / VPN", "info",
                 "; ".join(dict.fromkeys(background)),
                 "WARP установлен, его служба и процессы работают в фоне — это НОРМАЛЬНО "
                 "даже при отключённом туннеле, и само по себе входящие не блокирует. "
                 "Признаков подключённого туннеля нет (нет адаптера WARP в состоянии Up, "
                 "нет маршрута/DNS WARP). Если позже окажется, что блокировка осталась, "
                 "проверьте ещё так: остановите службу CloudflareWARP на 1 минуту "
                 "(нужны права администратора) и повторите тест с телефона.")
    else:
        diag.add("warp", "Cloudflare WARP / VPN", "ok",
                 "следов WARP/VPN не найдено")


def check_av(diag: Diag) -> None:
    """Сторонние антивирусы/фаерволы — частая причина «локально работает, снаружи нет»."""
    products = [p for p in (diag.facts.get("av_products") or []) if isinstance(p, dict)]
    services = [s for s in (diag.facts.get("av_services") or []) if isinstance(s, dict)]
    # Без дублей: SecurityCenter2 на реальных машинах отдаёт один и тот же
    # антивирус по 2–3 раза (в отчёте было «ESET Security, ESET Security, ESET Security»).
    names = []
    for p in products:
        name = str(p.get("displayName") or "").strip()
        if name and name not in names:
            names.append(name)
    third_party = [n for n in names if not re.search(r"windows defender|microsoft", n, re.I)]
    skip_re = r"windefend|wscsvc|securityhealth|mdm|sense"
    svc_names = sorted({str(s.get("Name")) for s in services
                        if not re.search(skip_re, str(s.get("Name")), re.I)})
    parts = []
    if names:
        parts.append("антивирусы: " + ", ".join(names))
    if svc_names:
        parts.append("службы: " + ", ".join(svc_names[:10]))

    facts = diag.facts
    facts["av_third_party"] = third_party

    # ESET (ekrn/ekrnEpfw) и Malwarebytes (MBAM*) держат СВОЙ сетевой фильтр,
    # который режет входящие раньше брандмауэра Windows и не виден в wf.msc.
    eset = bool([n for n in third_party if "eset" in n.lower()]) or         any(x.lower() in ("ekrn", "ekrnepfw", "eset") for x in svc_names) or         any("eset" in n.lower() for n in svc_names)
    mbytes = any("mbam" in n.lower() for n in svc_names)
    facts["av_firewall_strong"] = "ESET" if eset else (
        "Malwarebytes" if mbytes else "")

    if eset:
        diag.add("av", "Сторонняя защита (ESET)", "warn", " · ".join(parts),
                 "У ESET (службы ekrn/ekrnEpfw) СВОЙ сетевой экран, независимый от "
                 "брандмауэра Windows: правила Windows могут быть идеальными, а ESET "
                 "всё равно не пустит телефон. Проверка за 2 минуты: ESET → «Настройки» "
                 "→ «Защита сети» (Firewall) → временно выключить фильтрацию трафика, "
                 "проверить с телефона, включить обратно. Если дело в нём — добавьте "
                 "разрешение для python.exe/pythonw.exe и переведите свою Wi-Fi сеть в "
                 "зону «Домашняя/Доверенная» (в ESET есть свои зоны сетей).")
    elif third_party or svc_names:
        diag.add("av", "Сторонняя защита", "warn", " · ".join(parts),
                 "Встроенный фильтр антивируса/фаервола может резать входящие раньше, чем "
                 "брандмауэр Windows. Отключите в нём «сетевой экран» на 2 минуты и "
                 "повторите тест — если телефон сразу достучится, виноват он.")
    else:
        diag.add("av", "Сторонняя защита", "ok",
                 "только защита Windows" if not parts else " · ".join(parts))


def check_hosts(diag: Diag) -> None:
    lines = diag.facts.get("hosts") or []
    interesting = [ln for ln in lines if not re.match(r"^\s*#", ln)]
    if not interesting:
        diag.add("hosts", "Файл hosts", "ok", "лишних записей нет")
        return

    blockers = sum(1 for ln in interesting
                   if ln.startswith("0.0.0.0") or ln.startswith("127.0.0.1")
                   or ln.startswith("::1"))
    local = [ip for ip in (diag.facts.get("ips") or []) if ip]
    mentions = [ln for ln in interesting if any(ip in ln for ip in local)]
    detail = f"непустых строк: {len(interesting)} · блокировок (0.0.0.0/127.0.0.1): {blockers}"
    if mentions:
        detail += f" · упоминаний ваших адресов: {len(mentions)}"
    diag.facts["hosts_mentions"] = mentions[:20]
    diag.facts["hosts_lines"] = len(interesting)

    if mentions:
        diag.add("hosts", "Файл hosts", "warn", detail,
                 "В hosts есть строки с вашими локальными адресами — они могут направлять "
                 "трафик мимо нужного сервера: " + "; ".join(mentions[:3]))
    elif len(interesting) > 50:
        diag.add("hosts", "Файл hosts", "info", detail,
                 f"Похоже на список блокировки рекламы/телеметрии ({blockers} записей на "
                 "0.0.0.0/127.0.0.1). Для локальной сети это не помеха, но если что-то "
                 "странное — временно переименуйте файл и перезагрузитесь.")
    else:
        diag.add("hosts", "Файл hosts", "info", detail,
                 "Записи в hosts могут направлять домены мимо нужного адреса.")


def check_neighbors(diag: Diag, phone: Optional[str]) -> None:
    """Соседи по сети (ARP): кто вообще виден ноутбуку в локальной сети."""
    neighbors = [n for n in (diag.facts.get("neighbors") or []) if isinstance(n, dict)]
    diag.facts["neighbors_clean"] = [
        {"ip": n.get("IPAddress"), "mac": n.get("LinkLayerAddress"),
         "state": n.get("State"), "iface": n.get("InterfaceAlias")}
        for n in neighbors
    ]
    count = len(neighbors)
    diag.add("neighbors", "Соседи в локальной сети", "info" if count else "warn",
             f"видно устройств: {count}",
             "" if count else "Ноутбук никого не видит в LAN — проверьте, что Wi-Fi "
                              "подключён и это домашняя сеть, а не «гостевая»/отельная.")

    if not phone:
        return
    match = None
    for n in neighbors:
        if str(n.get("IPAddress")) == phone:
            match = n
            break
    if match:
        state = str(match.get("State") or "")
        if state.lower() in ("unreachable", "incomplete"):
            diag.add("neighbor_phone", "Телефон в таблице ARP", "bad",
                     f"{phone}: состояние {state}",
                     "Обмен на канальном уровне не идёт: телефон и ноутбук, скорее всего, "
                     "в РАЗНЫХ сетях (гостевая сеть / другой диапазон / точка доступа "
                     "с изоляцией клиентов) либо телефон спит. Сверьте на телефоне: "
                     "Настройки → Wi-Fi → ваша сеть → IP-адрес.")
        else:
            diag.add("neighbor_phone", "Телефон в таблице ARP", "ok",
                     f"{phone}: MAC {match.get('LinkLayerAddress')} ({state})",
                     "")
    else:
        diag.add("neighbor_phone", "Телефон в таблице ARP", "warn",
                 f"{phone} в таблице не найден",
                 "Либо адрес телефона введён неточно, либо ноутбук с ним не общался. "
                 "Пинг/ARP-проверка ниже уточнит.")


def check_ics(diag: Diag) -> None:
    """
    Точка доступа Windows (мобильный хот-спот) и её адрес 192.168.137.1.

    Это не «поломка», но именно из-за неё на ноутбуке появляется лишний адрес,
    который так удобно принять за «свой»: на реальном запуске QR-код вёл на
    192.168.137.1, куда телефон в обычной Wi-Fi сети попасть не может.
    """
    facts = diag.facts
    ranking = rank_local_ips(facts)
    hotspot = [r for r in ranking if r.get("ics")]
    shared = [s for s in (facts.get("ics_service") or []) if isinstance(s, dict)
              and str(s.get("Name") or "").lower() in ("sharedaccess", "icssvc")]
    running = [s for s in shared if str(s.get("Status")) in ("4", "Running")]
    wifi_direct = [a for a in (facts.get("adapters") or []) if isinstance(a, dict)
                   and "wi-fi direct" in str(a.get("InterfaceDescription") or "").lower()
                   and str(a.get("Status") or "").lower().startswith("up")]

    facts["ics_detected"] = bool(hotspot or running or wifi_direct)
    if not facts["ics_detected"]:
        diag.add("ics", "Точка доступа Windows (мобильный хот-спот)", "ok", "не обнаружена")
        return

    parts = []
    if wifi_direct:
        parts.append("адаптер «" + str(wifi_direct[0].get("Name")) + "» (Wi-Fi Direct) включён")
    if hotspot:
        parts.append("адрес " + ", ".join(r["ip"] for r in hotspot) + " в подсети точки доступа")
    if shared:
        parts.append("служба SharedAccess: " + service_status_word(shared[0].get("Status")))
    diag.add("ics", "Точка доступа Windows (мобильный хот-спот)", "warn",
             " · ".join(parts),
             "У ноутбука есть своя точка доступа (мобильный хот-спот) с адресом "
             "192.168.137.1 — это НЕ ваша домашняя Wi-Fi сеть, телефон в неё не попадёт, "
             "если он подключён к роутеру. Если хот-спот вам не нужен, выключите его: "
             "Параметры → Сеть и Интернет → Мобильный хот-спот → Выкл. Это уберёт лишний "
             "виртуальный адаптер и путаницу с адресами.")


def firewall_log_path() -> Optional[str]:
    """Путь к журналу брандмауэра Windows (если он вообще создан)."""
    base = os.environ.get("SystemRoot", r"C:\Windows")
    path = os.path.join(base, "System32", "LogFiles", "Firewall", "pfirewall.log")
    return path


FWLOG_ENABLE_HINT = (
    "Точный тест «доходят ли пакеты»: включите журнал блокировок брандмауэра "
    "(в консоли от имени администратора):\n"
    "      netsh advfirewall set allprofiles logging droppedconnections enable\n"
    "      netsh advfirewall set allprofiles logging maxfilesize 16384\n"
    "    затем повторите запуск NET DOCTOR и попробуйте зайти с телефона. "
    "Если в журнале появятся строки с адресом телефона — пакеты ДОХОДЯТ до ноутбука, "
    "и блокирует их сам ноутбук (фаервол/антивирус). Если журнал пуст — пакеты не "
    "доходят (роутер, гостевая сеть, VPN на телефоне)."
)


def read_firewall_log(tail_lines: int = 400) -> List[str]:
    """Последние строки журнала брандмауэра (пусто, если файла/прав нет)."""
    path = firewall_log_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        try:
            with open(path, "r", encoding="cp1251", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return []
    return [ln.rstrip("\n") for ln in lines[-tail_lines:]]


def check_firewall_log(diag: Diag, phone: Optional[str]) -> None:
    """Смотрим журнал блокировок: есть ли там пакеты от телефона."""
    if not IS_WINDOWS:
        return
    lines = read_firewall_log()
    if not lines:
        diag.add("firewall_log", "Журнал блокировок брандмауэра", "info",
                 "журнал пуст или ещё не включён",
                 FWLOG_ENABLE_HINT)
        return

    local = [ip for ip in (diag.facts.get("ips") or []) if ip and not is_apipa(ip)]
    blocked = [ln for ln in lines if " DROP " in ln.upper()]
    interesting = [ln for ln in blocked
                   if (phone and phone in ln) or any(ip in ln for ip in local)]
    diag.facts["fwlog_drops"] = interesting[-10:]
    if interesting:
        diag.add("firewall_log", "Журнал блокировок брандмауэра", "bad",
                 f"строк DROP: {len(blocked)}, с адресом телефона/ноутбука: {len(interesting)}",
                 "Пакеты ДОХОДЯТ до ноутбука, но брандмауэр их блокирует — вот доказательство "
                 "(последние строки): " + " | ".join(interesting[-3:]))
    else:
        diag.add("firewall_log", "Журнал блокировок брандмауэра", "info",
                 f"строк DROP: {len(blocked)}, с адресами телефона/ноутбука нет",
                 "Если телефон в момент проверки точно пытался подключиться, а строк нет — "
                 "пакеты до ноутбука не доходят: проблема на роутере (гостевая сеть, "
                 "изоляция клиентов) или на телефоне (VPN). " + FWLOG_ENABLE_HINT)


def check_python_procs(diag: Diag) -> None:
    procs = [p for p in (diag.facts.get("python_procs") or []) if isinstance(p, dict)]
    diag.facts["python_procs_clean"] = [
        {"pid": p.get("ProcessId"), "name": p.get("Name"),
         "cmd": (str(p.get("CommandLine") or "").strip())[:220]} for p in procs
    ]
    if procs:
        diag.add("py_procs", "Запущенные Python-процессы", "info",
                 f"найдено: {len(procs)} (это могут быть ваши сервера)")
    else:
        diag.add("py_procs", "Запущенные Python-процессы", "skip",
                 "не найдено (может быть, сервер ещё не запущен)")


def check_listeners(diag: Diag, watch_port: Optional[int] = None) -> None:
    """Кто и на каком адресе слушает порты: 0.0.0.0 (видно всем) или 127.0.0.1 (только себе)."""
    listeners = [l for l in (diag.facts.get("listeners") or []) if isinstance(l, dict)]
    diag.facts["listeners_clean"] = listeners
    py_listeners = [l for l in listeners
                    if str(l.get("name") or "").lower().startswith("python")]
    shown = []
    for l in py_listeners[:6]:
        shown.append(f"{l.get('address')}:{l.get('port')} (PID {l.get('pid')}, {l.get('name')})")

    only_loopback = []
    for l in py_listeners:
        addr = str(l.get("address") or "")
        if addr in ("127.0.0.1", "::1"):
            only_loopback.append(str(l.get("port")))

    detail = f"Python-серверов слушает: {len(py_listeners)}"
    if shown:
        detail += " · " + "; ".join(shown)

    if only_loopback:
        diag.add("listeners_loopback", "Адрес прослушивания", "bad", detail,
                 "Часть серверов слушает только 127.0.0.1 (порты "
                 f"{', '.join(only_loopback)}) — их видит только сам ноутбук. Это ровно то, "
                 "как выглядят ваши симптомы: «на ПК открывается, на телефоне нет». "
                 "В приложении должно быть host='0.0.0.0' (или у Flask "
                 "app.run(host='0.0.0.0', port=...)).",
                 fix_ps=[])
    elif py_listeners:
        diag.add("listeners_loopback", "Адрес прослушивания", "ok", detail)
    else:
        diag.add("listeners_loopback", "Адрес прослушивания", "info", detail)

    if watch_port:
        found = [l for l in listeners if int(l.get("port") or 0) == int(watch_port)]
        if not found:
            diag.add("watch_port", f"Порт {watch_port}", "warn",
                     "никто не слушает этот порт",
                     "Ваш сервер на этом порту сейчас не запущен (или уже закрылся).")
        else:
            addrs = {str(l.get("address")) for l in found}
            names = {str(l.get("name")) for l in found}
            if addrs & {"0.0.0.0", "::", "::0"}:
                diag.add("watch_port", f"Порт {watch_port}", "ok",
                         f"слушает {', '.join(sorted(addrs))} · процесс: {', '.join(sorted(names))}")
            else:
                diag.add("watch_port", f"Порт {watch_port}", "bad",
                         f"слушает только {', '.join(sorted(addrs))} · процесс: {', '.join(sorted(names))}",
                         "Сервер привязан не ко всем интерфейсам. Нужен 0.0.0.0 — "
                         "иначе телефон физически не сможет подключиться.")


def norm_exe_path(path: str) -> str:
    """Приводит путь к .exe к сравнимому виду: регистр, слэши, кавычки, .. и т.п."""
    text = str(path or "").strip().strip('"').strip("'").strip()
    if not text:
        return ""
    text = text.replace("/", "\\")
    return os.path.normpath(text).lower()


def rule_covers_exe(program: Any, exe_path: str) -> bool:
    """Покрывает ли одно правило (поле Program) указанный исполняемый файл."""
    prog = norm_exe_path(str(program or ""))
    if not prog or prog in ("any", "*", "любая программа"):
        return True          # правило «для всех программ»
    exe = norm_exe_path(exe_path)
    if not exe:
        return False
    if "\\" not in prog:
        return os.path.basename(exe) == prog      # правило задано именем файла
    return prog == exe


def check_python_paths(diag: Diag) -> None:
    """
    Сопоставляет РЕАЛЬНЫЕ пути python-процессов, слушающих порты, с путями в
    разрешающих правилах брандмауэра.

    Зачем: «16 разрешающих правил для python.exe» ничего не гарантируют, если они
    указывают на C:\...\Python312-32\python.exe, а порт слушает совсем другой
    интерпретатор (например, ...\pythoncore-3.14-64\pythonw.exe). Брандмауэр Windows
    разрешает входящие по конкретному файлу, поэтому такие правила «не про этот» python.
    """
    listeners = [l for l in (diag.facts.get("listeners") or []) if isinstance(l, dict)]
    procs: Dict[int, Dict[str, Any]] = {}
    for item in (diag.facts.get("python_procs") or []):
        if isinstance(item, dict):
            try:
                procs[int(item.get("ProcessId"))] = item
            except (TypeError, ValueError):
                continue
    py_listeners = [
        l for l in listeners
        if str(l.get("name") or "").lower().startswith("python")
        or str(l.get("path") or "").lower().endswith(("python.exe", "pythonw.exe"))
    ]
    rules = [r for r in (diag.facts.get("fw_python_allow_in") or []) if isinstance(r, dict)]

    rows: List[Dict[str, Any]] = []
    for l in py_listeners:
        try:
            pid = int(l.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        path = str(l.get("path") or "")
        if not path and pid and procs.get(pid):
            path = str(procs[pid].get("ExecutablePath") or "")
        covered = (any(rule_covers_exe(r.get("Program"), path) for r in rules)
                   if path else False)
        rows.append({"pid": pid, "port": l.get("port"), "name": str(l.get("name") or ""),
                     "address": str(l.get("address") or ""), "path": path,
                     "covered": covered})
    diag.facts["py_listener_paths"] = rows

    if not rows:
        diag.add("python_paths", "Python-процессы и правила брандмауэра", "info",
                 "слушающих python-процессов не найдено")
        return

    shown = []
    for r in rows[:5]:
        mark = "правило есть" if r["covered"] else "правила нет"
        shown.append(f"{r['address']}:{r['port']} (PID {r['pid']}) — {mark}: "
                     f"{r['path'] or 'путь не определён'}")
    detail = " · ".join(shown)

    if not any(r["path"] for r in rows):
        diag.add("python_paths", "Python-процессы и правила брандмауэра", "info", detail,
                 "Пути процессов не удалось прочитать (это проверка Windows).")
        return

    uncovered = [r for r in rows if r["path"] and not r["covered"]]
    rule_paths = sorted({str(r.get("Program")) for r in rules if r.get("Program")})

    if uncovered and rules:
        diag.add("python_paths", "Python-процессы и правила брандмауэра", "bad", detail,
                 "Разрешающие правила есть, но ни одно не покрывает именно тот файл, "
                 "который слушает порты. Windows разрешает входящие по конкретному пути "
                 "к .exe — «чужое» правило не спасает. Правила созданы для: "
                 + ("; ".join(rule_paths[:4]) or "?")
                 + ". Починка: python net_doctor.py --fix — он добавит правило для "
                 "обнаруженных интерпретаторов (или добавьте путь вручную в wf.msc).")
    elif uncovered:
        diag.add("python_paths", "Python-процессы и правила брандмауэра", "warn", detail,
                 "Разрешающих входящих правил для python нет вовсе — Windows может резать "
                 "входящие. Запустите --fix (или нажмите «Разрешить доступ», когда Windows "
                 "спросит при первом запуске сервера).")
    else:
        diag.add("python_paths", "Python-процессы и правила брандмауэра", "ok", detail,
                 "Все слушающие python-процессы покрыты разрешающими правилами.")


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def launcher_problems(path: str) -> List[str]:
    """
    Проверяет файл-лаунчер (.bat/.cmd/.vbs) на «гигиену» Windows.

    Из-за нарушения этих правил cmd.exe однажды уже выполнил обрывки строк
    (ошибки вида «'on' is not recognized as an internal or external command»),
    поэтому теперь они проверяются автоматически:
      * только CRLF — одиночные LF заставляют cmd.exe путать смещения в файле;
      * .bat/.cmd — только ASCII, без BOM и без вызова chcp (смена кодовой
        страницы внутри файла ломает его чтение);
      * .vbs — BOM UTF-8 (иначе WSH прочитает кириллицу как мусор) и парные
        кавычки в каждой строке кода.
    Возвращает список проблем; пустой список — файл в порядке.
    """
    problems: List[str] = []
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return [f"не удалось прочитать: {exc}"]

    ext = os.path.splitext(path)[1].lower()
    lone_lf = raw.count(b"\n") - raw.count(b"\r\n")
    if lone_lf:
        problems.append(f"одиночных переводов строк LF: {lone_lf} (нужны только CRLF)")
    has_bom = raw[:3] == b"\xef\xbb\xbf"

    if ext in (".bat", ".cmd"):
        bad_bytes = sum(1 for b in raw if b >= 128)
        if bad_bytes:
            problems.append(f"не-ASCII байтов: {bad_bytes} (cmd.exe прочитает их "
                            "в чужой кодировке)")
        if has_bom:
            problems.append("BOM в .bat (cmd.exe может включить его в первую команду)")
        for num, line in enumerate(raw.decode("ascii", "replace").splitlines(), 1):
            stripped = line.strip().lower()
            if stripped.startswith("chcp"):
                problems.append(f"строка {num}: вызов chcp внутри .bat — "
                                "именно он вызывает выполнение обрывков строк")
    elif ext == ".vbs":
        if not has_bom:
            problems.append("нет BOM UTF-8 (WSH может прочитать кириллицу как мусор)")
        text = raw.decode("utf-8-sig", "replace")
        if "net_doctor.py" not in text:
            problems.append("в файле нет ссылки на net_doctor.py")
        for num, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("'"):
                continue
            if line.split("'")[0].count('"') % 2:
                problems.append(f"строка {num}: непарное число кавычек")
    return problems


def http_probe(url: str, timeout: float = 3.0) -> Tuple[bool, str]:
    """
    Простой GET БЕЗ системного прокси (иначе WARP-прокси 127.0.0.1:40000
    перехватил бы даже проверку локальных адресов). Возвращает (успех, описание).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"netdoctor/{VERSION}"})
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read(200).decode("utf-8", "replace")
            return True, f"HTTP {resp.status}, ответ: {body.strip()[:60]!r}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code} (сервер ответил)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def check_bind(diag: Diag, port: int) -> bool:
    """Может ли наш процесс слушать 0.0.0.0:<port>."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        s.listen(5)
        ok = True
        detail = f"порт {port} свободен, сокет 0.0.0.0:{port} создан"
        hint = ("Если Windows прямо сейчас покажет окно «Разрешить доступ к сети?» — "
                "нажмите «Разрешить доступ». Это то самое окно, отказ в котором ломает "
                "входящие подключения.")
        status = "ok"
    except PermissionError:
        ok = False
        detail = f"нет прав слушать порт {port}"
        hint = ("Порты < 1024 требуют прав администратора. Возьмите порт 5000+ "
                "или запустите от администратора.")
        status = "bad"
    except OSError as exc:
        ok = False
        detail = f"не удалось занять порт {port}: {exc}"
        hint = ("Порт уже занят другим процессом. Посмотрите, кто это: "
                f"net_doctor.py --check-port {port}")
        status = "bad"
    finally:
        try:
            s.close()
        except OSError:
            pass
    diag.add("bind", f"Свободен ли порт {port}", status, detail, hint)
    return ok


def check_local_reach(diag: Diag, port: int, ips: Sequence[str]) -> None:
    """Отвечает ли тестовый сервер на 127.0.0.1 и на LAN-адреса (с самих себя)."""
    ok, detail = http_probe(f"http://127.0.0.1:{port}/api/ping")
    diag.add("local_http", "Ответ по 127.0.0.1", "ok" if ok else "bad", detail,
             "" if ok else "Даже локально сервер не отвечает — проблема в самом Python/порту.")

    lan_ok_any = False
    details = []
    probed = 0
    apipa_only = 0
    for ip in ips:
        if is_apipa(ip):
            apipa_only += 1
            details.append(f"{ip}: это APIPA-адрес (169.254.*) — роутер не выдал IP")
            continue
        ok, detail = http_probe(f"http://{ip}:{port}/api/ping")
        probed += 1
        lan_ok_any = lan_ok_any or ok
        details.append(f"{ip}: {'отвечает' if ok else detail}")

    detail = " · ".join(details) or "нет ни одного не-loopback адреса"

    if probed == 0 and apipa_only:
        diag.add("lan_http", "Ответ по LAN-адресу ноутбука", "warn", detail,
                 "Адрес вида 169.254.* означает, что DHCP не сработал: ноутбук НЕ получил "
                 "адрес от роутера, и телефон в такой сети его не найдёт. Лечение: "
                 "переподключиться к Wi-Fi (забыть сеть и подключиться заново) или "
                 "проверить роутер.")
        return
    if probed == 0:
        diag.add("lan_http", "Ответ по LAN-адресу ноутбука", "warn", detail,
                 "Похоже, Wi-Fi/Ethernet не подключены или адрес не получен.")
        return

    diag.add("lan_http", "Ответ по LAN-адресу ноутбука", "ok" if lan_ok_any else "bad",
             detail,
             "" if lan_ok_any else
             "Сервер не отвечает даже самому ноутбуку по его сетевому адресу.")


def check_ssid(diag: Diag) -> None:
    wlan = diag.facts.get("wlan_ssid") or {}
    ssid = wlan.get("ssid")
    if not ssid:
        diag.add("ssid", "Wi-Fi (текущая сеть)", "skip",
                 "нет данных (netsh wlan недоступен или это кабель)")
        return
    extra = []
    if wlan.get("band"):
        extra.append(f"диапазон {wlan['band']}")
    if wlan.get("channel"):
        extra.append(f"канал {wlan['channel']}")
    if wlan.get("signal"):
        extra.append(f"сигнал {wlan['signal']}")
    diag.facts["ssid"] = ssid
    diag.add("ssid", "Wi-Fi (текущая сеть)", "info",
             f"{ssid}" + (" · " + ", ".join(extra) if extra else ""),
             "Проверьте, что телефон подключён ИМЕННО к этой сети (а не к гостевой/"
             "соседской/мобильному интернету).")


def check_phone(diag: Diag, phone: Optional[str]) -> None:
    """Если пользователь указал адрес телефона — проверяем связь в обе стороны."""
    if not phone:
        return
    ips = diag.facts.get("ips") or []
    prefix = 24
    same = None
    for ip in ips:
        for row in (diag.facts.get("ipaddresses") or []):
            if isinstance(row, dict) and str(row.get("IPAddress")) == ip:
                try:
                    prefix = int(row.get("PrefixLength") or 24)
                except (TypeError, ValueError):
                    prefix = 24
        same = in_same_subnet(phone, ip, prefix)
        if same:
            break

    if same is None:
        diag.add("phone_subnet", "Телефон в одной подсети", "warn",
                 "не удалось сравнить адреса")
    elif same:
        diag.add("phone_subnet", "Телефон в одной подсети", "ok",
                 f"{phone} и {ips[0] if ips else '?'} — одна сеть /{prefix}")
    else:
        diag.add("phone_subnet", "Телефон в одной подсети", "bad",
                 f"{phone} не входит в сеть ноутбука (/{prefix})",
                 "Адреса из разных сетей — обмен напрямую невозможен. Проверьте, что "
                 "телефон в той же Wi-Fi сети (и не в «гостевой»). Для справки: у телефона "
                 "адрес смотрится в Настройки → Wi-Fi → ваша сеть → IP.")

    # Пинг телефона (ICMP). Телефоны часто его игнорируют — это нормально.
    if IS_WINDOWS:
        rc, out, err = run(["ping", "-n", "2", "-w", "1200", phone], timeout=25)
    else:
        rc, out, err = run(["ping", "-c", "2", "-W", "2", phone], timeout=25)
    answered = bool(rc == 0)
    if answered:
        diag.add("phone_ping", "Пинг телефона", "ok", f"{phone} отвечает на ping")
    else:
        diag.add("phone_ping", "Пинг телефона", "info",
                 f"{phone} на ping не ответил (для телефонов это обычное дело)",
                 "Не делайте вывод по пингу. Смотрите на строку «Телефон в таблице ARP» "
                 "и на сам факт запроса в тестовый сервер.")

    diag.facts["phone"] = phone


# =========================================================================================
#  8. ВЕРДИКТ
# =========================================================================================

def build_verdict(diag: Diag, port: int, external_hit: bool,
                  raw_external_hit: bool = False) -> Dict[str, Any]:
    """
    Возвращает {"status": "ok|warn|bad", "headline": str, "steps": [str, ...],
                "probability": [(причина, «очки»), ...]}
    Логика: телефон достучался -> канал в порядке. Нет -> выбираем самую вероятную
    причину по совокупности фактов.
    """
    facts = diag.facts
    reasons: List[Tuple[str, int]] = []

    fw_all_blocked = facts.get("firewall_all_inbound_blocked") or []
    profile_public = facts.get("profile_public") or []
    fw_python_allow = facts.get("fw_python_allow_in") or []
    warp_traces = facts.get("warp_traces") or []
    defaults = facts.get("default_routes") or []
    apipa = [ip for ip in (facts.get("ips") or []) if is_apipa(ip)]
    real_ips = [ip for ip in (facts.get("ips") or [])
                if not is_apipa(ip) and not is_ics_ip(ip)]
    fw_scope = diag.get("firewall_python_scope")
    fw_log = diag.get("firewall_log")
    ics_chk = diag.get("ics")
    py_paths_chk = diag.get("python_paths")
    loopback_only = diag.get("listeners_loopback")
    sp = diag.get("watch_port")
    phone_sub = diag.get("phone_subnet")
    arp_bad = diag.get("neighbor_phone")

    # --- причины в порядке «веса» -------------------------------------------------
    if diag.get("bind") and diag.get("bind").status == "bad":
        reasons.append(("Порт занят или нет прав его слушать", 90))
    if sp and sp.status == "bad":
        reasons.append(("Ваш сервер слушает только 127.0.0.1 вместо 0.0.0.0", 95))
    if loopback_only and loopback_only.status == "bad":
        reasons.append(("Один из Python-серверов привязан только к 127.0.0.1", 70))
    if fw_all_blocked:
        reasons.append((f"Брандмауэр: включено «блокировать все входящие» "
                        f"({', '.join(fw_all_blocked)})", 85))
    if profile_public and not fw_python_allow:
        reasons.append((f"Сеть помечена как «Общедоступная» ({', '.join(profile_public)}), "
                        "а разрешения для python.exe нет", 80))
    if warp_traces:
        reasons.append(("Подключён туннель Cloudflare WARP/VPN — входящие из LAN "
                        "не доходят", 75))
    if fw_log is not None and fw_log.status == "bad":
        reasons.append(("В журнале брандмауэра есть блокировки с адресом телефона: "
                        "пакеты доходят, блокирует ноутбук", 82))
    if py_paths_chk is not None and py_paths_chk.status == "bad":
        reasons.append(("Разрешающие правила брандмауэра не покрывают именно тот python, "
                        "который слушает порты (правила созданы для другого интерпретатора)",
                        76))
    if fw_scope is not None and fw_scope.status == "bad":
        reasons.append(("Разрешающие правила для python.exe не покрывают вашу подсеть "
                        "(например, ограничены подсетью хот-спота)", 78))
    if facts.get("av_firewall_strong") == "ESET":
        reasons.append(("Свой сетевой экран ESET (ekrnEpfw) режет входящие независимо "
                        "от брандмауэра Windows", 70))
    if facts.get("hosts_mentions"):
        reasons.append(("В файле hosts есть записи с вашими локальными адресами", 25))
    if (ics_chk is not None and ics_chk.status == "warn") or facts.get("ics_detected"):
        reasons.append(("Включена точка доступа Windows (мобильный хот-спот): адрес "
                        "192.168.137.1 — это НЕ ваша Wi-Fi сеть, легко перепутать", 20))
    if phone_sub and phone_sub.status == "bad":
        reasons.append(("Телефон в другой подсети/сети (гостевая сеть, другой роутер)", 88))
    if arp_bad and arp_bad.status == "bad":
        reasons.append(("На канальном уровне телефон недостижим (ARP incomplete) — "
                        "изоляция клиентов на роутере/другая сеть", 84))
    if len(defaults) > 1:
        reasons.append(("Несколько маршрутов по умолчанию (VPN/Hyper-V) — ответы уходят "
                        "не в ту дверь", 40))
    # APIPA-адреса на служебных адаптерах (VMware/Bluetooth/Wi-Fi Direct) — это шум,
    # а не поломка: на реальном запуске четыре таких адреса дали ложные 60 %.
    if apipa and not real_ips:
        reasons.append((f"Адрес вида 169.254.* ({', '.join(apipa)}) — DHCP не сработал, "
                        "телефон такой ноутбук не найдёт", 60))
    if (facts.get("av_third_party") and facts.get("av_firewall_strong") != "ESET"):
        reasons.append(("Сторонний антивирус/фаервол фильтрует входящие", 45))
    if facts.get("proxy_enabled"):
        reasons.append(("Включён системный прокси — браузеру ноутбука может мешать, "
                        "на телефон не влияет", 15))
    if not facts.get("ips"):
        reasons.append(("У ноутбука нет ни одного LAN-адреса (нет сети)", 80))

    reasons.sort(key=lambda item: item[1], reverse=True)

    steps: List[str] = []
    if raw_external_hit:
        return {"status": "warn",
                "headline": "Пакеты от телефона ДОШЛИ, но это не HTTP-запрос "
                            "(похоже, открывали https://). Сеть работает — дело в адресе.",
                "steps": [
                    "Откройте адрес ровно как http://<IP>:<порт>/ — со схемой http.",
                    "В Chrome/Edge на телефоне отключите «Всегда использовать защищённые "
                    "подключения» (HTTPS-First), если он включён.",
                    "Самое надёжное — наведите камеру телефона на QR-код: в нём уже зашит "
                    "правильный http-адрес.",
                    "После этого проверьте своё приложение на 5000/5001 том же способом.",
                ]}
    if external_hit:
        verdict = {"status": "ok",
                   "headline": f"Телефон достучался до тестового сервера на порту {port} — "
                               "канал «телефон → ноутбук» РАБОТАЕТ.",
                   "steps": [
                       "Значит сеть, брандмауэр и адреса в порядке.",
                       "Теперь проверьте свое приложение: python net_doctor.py --check-port 5000 "
                       "(вместо 5000 — ваш порт).",
                       "Убедитесь, что в приложении указан host='0.0.0.0', и что порт не занят "
                       "другим процессом.",
                       "Если приложение всё равно не видно с телефона — сравните: работает ли "
                       "оно по 127.0.0.1 на ноутбуке (значит, дело в привязке адреса).",
                   ]}
        return verdict

    if not reasons:
        reasons.append(("Явных проблем в конфигурации не найдено", 10))

    headline = "Телефон за время проверки НЕ достучался. Наиболее вероятные причины:"
    if reasons[0][1] >= 80:
        headline = f"Телефон не достучался. Главный подозреваемый: {reasons[0][0].lower()}."

    shown_ip = ""
    for r in recommended_ips(facts):
        shown_ip = r["ip"]
        break
    if not shown_ip:
        for r in rank_local_ips(facts):
            if not r["apipa"] and not r["ics"]:
                shown_ip = r["ip"]
                break
    av_note = ""
    if facts.get("av_firewall_strong") == "ESET":
        av_note = " (у вас это ESET)"
    elif facts.get("av_third_party"):
        av_note = " (у вас: " + ", ".join(facts["av_third_party"][:3]) + ")"
    closed = facts.get("closed_port")
    steps = [
        "1. Самая частая причина при «всё настроено» — сетевой экран стороннего антивируса"
        + av_note + ": выключите его фильтрацию на 2 минуты и сразу проверьте с телефона.",
        "2. На телефоне: выключите любые VPN (в том числе 1.1.1.1/WARP), отключите мобильный "
        "интернет и откройте ровно http://" + (shown_ip or "<IP ноутбука>") +
        f":{port}/ (со схемой http, не https).",
        "3. Контрольный тест закрытого порта: откройте с телефона "
        + (f"http://{shown_ip or '<IP>'}:{closed}/" if closed else "адрес закрытого порта") +
        " — «отказано в подключении» значит пакеты доходят (блокирует ноутбук), "
        "«время ожидания» — пакеты не доходят (роутер или VPN на телефоне).",
        "4. Проверьте роутер: «гостевая сеть» и «изоляция клиентов» (AP isolation) должны "
        "быть выключены; телефон — в той же сети, что и ноутбук.",
        "5. Починка на ноутбуке: python net_doctor.py --fix (правило брандмауэра только для "
        "локальной подсети + профиль сети Private).",
        "6. Точное доказательство «кто виноват»: включите журнал блокировок брандмауэра "
        "(команды есть в отчёте netdoctor_report.txt) и посмотрите, появился ли в нём адрес "
        "телефона.",
    ]
    if py_paths_chk is not None and py_paths_chk.status == "bad":
        worst = next((r for r in (facts.get("py_listener_paths") or []) if r.get("path")), None)
        if worst:
            steps.append("7. Правило брандмауэра нужно ровно для этого файла: "
                         f"{worst['path']} — сейчас правила ссылаются на другой python "
                         "(проверьте в отчёте раздел «PYTHON: кто слушает»).")
    return {"status": "bad", "headline": headline, "steps": steps,
            "reasons": reasons}


def print_verdict(diag: Diag, verdict: Dict[str, Any]) -> None:
    title("ВЕРДИКТ")
    status = verdict["status"]
    color = {"ok": C.GREEN, "warn": C.YELLOW, "bad": C.RED}.get(status, C.CYAN)
    print(col(verdict["headline"], color, C.BOLD))
    reasons_list = (verdict.get("reasons") or [])[:8]
    lonely = len(reasons_list) == 1 and reasons_list[0][1] <= 10
    for reason, score in reasons_list:
        if lonely:
            print("   " + col(reason, C.GREY))
            continue
        bar = "#" * max(1, min(20, score // 5))
        print("   " + col(f"{score:>3}%", color, C.BOLD) + " " +
              col(bar, C.GREY) + "  " + reason)
    if verdict.get("steps"):
        print()
        for line in verdict["steps"]:
            print("  " + line)


# =========================================================================================
#  9. ФАЙЛ-ПОЧИНКА (PowerShell) И ОТЧЁТ
# =========================================================================================

def unique_ports(ports: Sequence[int]) -> List[int]:
    """Убирает повторы портов, сохраняя порядок появления."""
    seen, out = set(), []
    for p in ports:
        try:
            p = int(p)
        except (TypeError, ValueError):
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def build_fix_ps(port: int, extra_ports: Sequence[int], iface: Optional[str],
                 allow_program: bool, py_paths: Sequence[str] = ()) -> str:
    ports = unique_ports([port] + list(extra_ports))
    ports_txt = ", ".join(str(p) for p in ports)
    profile_cmd = ""
    if iface:
        profile_cmd = (
            "# 1) Сеть, через которую подключён ноутбук, помечаем как «частную».\n"
            "#    В общедоступной сети Windows по умолчанию режет входящие.\n"
            f"try {{ Set-NetConnectionProfile -InterfaceAlias '{iface}' "
            "-NetworkCategory Private -ErrorAction Stop; "
            f"Write-Host \"OK: профиль '{iface}' -> Private\" }} "
            "catch { Write-Host \"Не удалось переключить профиль: $($_.Exception.Message)\" }\n"
        )
    else:
        profile_cmd = (
            "# 1) Профиль сети: посмотрите сами и при необходимости переключите на Private\n"
            "Get-NetConnectionProfile | Format-Table InterfaceAlias, Name, NetworkCategory\n"
            "# Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private\n"
        )

    program_rule = ""
    if allow_program:
        program_rule = (
            "\n# 3) Дополнительно: разрешить именно python.exe (все порты, только локальная сеть)\n"
            "$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source\n"
            "if (-not $py) { $py = (Get-Process python -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty Path) }\n"
            "if (-not $py) { $py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }\n"
            "if ($py) {\n"
            "  Remove-NetFirewallRule -DisplayName 'netdoctor: python.exe (LAN)' -ErrorAction SilentlyContinue\n"
            "  New-NetFirewallRule -DisplayName 'netdoctor: python.exe (LAN)' "
            "-Direction Inbound -Action Allow -Program $py -Profile Any "
            "-RemoteAddress LocalSubnet -Protocol TCP | Out-Null\n"
            "  Write-Host \"OK: разрешён python.exe по адресу $py\"\n"
            "} else { Write-Host 'python.exe не найден в PATH — пропускаю' }\n"
        )

    listener_rules = ""
    listen_paths = [str(x) for x in (py_paths or []) if str(x).strip()]
    if listen_paths:
        quoted = ",\n  ".join("'" + x.replace("'", "''") + "'" for x in listen_paths)
        listener_rules = (
            "\n# 4) Разрешить именно те интерпретаторы, которые СЛУШАЮТ ПОРТЫ сейчас.\n"
            "#    Windows разрешает входящие по конкретному файлу: правило для другого\n"
            "#    python.exe (например, из старой версии) не помогает.\n"
            "$listenExes = @(\n  " + quoted + "\n)\n"
            "foreach ($exe in $listenExes) {\n"
            "  if (-not (Test-Path $exe)) { Write-Host \"пропуск (нет файла): $exe\"; continue }\n"
            "  $ruleName = \"netdoctor: python слушает $exe (LAN)\"\n"
            "  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue\n"
            "  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `\n"
            "      -Program $exe -Profile Any -RemoteAddress LocalSubnet -Protocol TCP | Out-Null\n"
            "  Write-Host \"OK: разрешён $exe\"\n"
            "}\n"
        )

    return f"""# =============================================================================
#  netdoctor_fix.ps1 — починка доступа к Python-серверам из локальной сети
# -----------------------------------------------------------------------------
#  Что делает (и что НЕ делает):
#    1. переводит сетевой профиль в Private (общедоступный профиль режет входящие);
#    2. добавляет разрешающее правило брандмауэра ТОЛЬКО для локальной подсети
#       (RemoteAddress LocalSubnet) на порты: {ports_txt};
#       Из интернета доступ НЕ открывается.
#    3. (необязательно) разрешает python.exe целиком для локальной подсети.
#
#  Запуск: правый клик по файлу -> «Выполнить с помощью PowerShell»
#          либо в консоли администратора:
#              powershell -NoProfile -ExecutionPolicy Bypass -File netdoctor_fix.ps1
#
#  Откат: netdoctor_undo.ps1 (удаляет все правила netdoctor*)
# =============================================================================

$ErrorActionPreference = 'Continue'
try {{ [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 }} catch {{}}

if (-not ([Security.Principal.WindowsPrincipal]`
          [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    Write-Host 'Нужны права администратора. Перезапускаю с запросом UAC...' -ForegroundColor Yellow
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $argLine
    exit
}}

Write-Host '=== NETDOCTOR: починка доступа из локальной сети ===' -ForegroundColor Cyan

{profile_cmd}
# 2) Разрешить входящие на нужные порты — только из локальной подсети.
$ruleName = 'netdoctor: разрешить LAN (TCP {ports_txt})'
Remove-NetFirewallRule -DisplayName 'netdoctor: разрешить LAN (TCP *' -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName $ruleName `
    -Description 'Создано net_doctor.py: доступ к локальным серверам для устройств своей сети' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort {ports_txt.replace(', ', ',')} `
    -Profile Any -RemoteAddress LocalSubnet | Out-Null
Write-Host "OK: правило брандмауэра добавлено: $ruleName" -ForegroundColor Green
{program_rule}{listener_rules}
# --- проверка -----------------------------------------------------------------
Write-Host ''
Write-Host '--- Проверка ---' -ForegroundColor Cyan
Get-NetConnectionProfile | Format-Table InterfaceAlias, NetworkCategory -AutoSize
Get-NetFirewallRule -DisplayName 'netdoctor*' |
    Format-Table DisplayName, Enabled, Direction, Action, Profile -AutoSize
Write-Host ''
Write-Host 'Готово. Теперь откройте с телефона адрес тестового сервера:' -ForegroundColor Green
Write-Host "   http://<IP-ноутбука>:{port}/" -ForegroundColor White
Write-Host 'Откат изменений: netdoctor_undo.ps1' -ForegroundColor Gray
"""


def build_undo_ps() -> str:
    return r"""# =============================================================================
#  netdoctor_undo.ps1 — откат изменений netdoctor_fix.ps1
#  Удаляет ВСЕ правила брандмауэра, созданные этим инструментом (netdoctor*).
#  Профиль сети обратно на Public НЕ переключает (это может быть вредно).
# =============================================================================
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal]`
          [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Нужны права администратора. Перезапускаю с запросом UAC...' -ForegroundColor Yellow
    $a = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $a
    exit
}
$rules = Get-NetFirewallRule -DisplayName 'netdoctor*' -ErrorAction SilentlyContinue
if ($rules) {
    $rules | Remove-NetFirewallRule
    Write-Host "Удалено правил: $($rules.Count)" -ForegroundColor Green
} else {
    Write-Host 'Правил netdoctor* не найдено — нечего удалять.' -ForegroundColor Gray
}
"""


def build_report_text(diag: Diag, verdict: Dict[str, Any], port: int,
                      extra: Optional[Dict[str, Any]] = None) -> str:
    lines: List[str] = []
    lines.append("=" * 90)
    lines.append(f" NET DOCTOR {VERSION} — отчёт о диагностике")
    lines.append(f" Время: {diag.started.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f" Тестовый порт: {port}")
    lines.append("=" * 90)
    lines.append("")
    lines.append("--- ЧТО МОЖНО ЗАПИСАТЬ В КОНСОЛЬ ---")
    for chk in diag.checks:
        lines.append(f"[{STATUS_LABEL.get(chk.status, chk.status):>9}] {chk.title}: {chk.detail}")
        if chk.hint:
            lines.append(f"            подсказка: {chk.hint}")
    lines.append("")
    lines.append("--- ФАКТЫ О СЕТИ ---")
    for key in ("hostname", "os_version", "ips", "primary_ip", "profile_public",
                "firewall_all_inbound_blocked", "ssid", "interface_metrics",
                "default_routes", "proxy_enabled", "warp_traces", "warp_tunnel_active",
                "warp_background", "av_third_party", "av_firewall_strong",
                "ics_detected", "closed_port", "hosts_mentions", "arp_diff", "phone"):
        if key in diag.facts:
            lines.append(f"{key}: {json.dumps(diag.facts.get(key), ensure_ascii=False)[:600]}")
    lines.append("")
    lines.append("--- АДАПТЕРЫ ---")
    for row in (diag.facts.get("adapters") or []):
        lines.append(json.dumps(row, ensure_ascii=False))
    lines.append("")
    lines.append("--- АДРЕСА ---")
    for row in (diag.facts.get("ipaddresses") or []):
        lines.append(json.dumps(row, ensure_ascii=False))
    lines.append("")
    lines.append("--- СЛУШАЮЩИЕ ПОРТЫ (python) ---")
    for row in (diag.facts.get("listeners_clean") or []):
        if str(row.get("name", "")).lower().startswith("python"):
            lines.append(json.dumps(row, ensure_ascii=False, default=str))
    lines.append("")
    lines.append("--- ПОЧЕМУ ТАКОЙ АДРЕС РЕКОМЕНДОВАН ТЕЛЕФОНУ ---")
    for row in (diag.facts.get("ip_ranking") or []):
        lines.append(json.dumps(row, ensure_ascii=False))
    lines.append("")
    lines.append("--- ПРАВИЛА БРАНДМАУЭРА ДЛЯ PYTHON (адреса и порты) ---")
    for row in (diag.facts.get("fw_python_allow_in") or []):
        lines.append(json.dumps({k: row.get(k) for k in
                                 ("Program", "DisplayName", "Profile", "RemoteAddress",
                                  "LocalPort", "Protocol")}, ensure_ascii=False))
    if not (diag.facts.get("fw_python_allow_in") or []):
        lines.append("(разрешающих входящих правил не найдено)")
    lines.append("")
    lines.append("--- PYTHON: КТО СЛУШАЕТ ПОРТЫ И ПОКРЫТ ЛИ ПРАВИЛАМИ ---")
    for row in (diag.facts.get("py_listener_paths") or []):
        lines.append(
            f"порт {row.get('port')} · PID {row.get('pid')} · {row.get('name')} → "
            f"{row.get('path') or 'путь не определён'} · "
            + ("покрыт разрешающим правилом" if row.get("covered")
               else "НЕ покрыт ни одним разрешающим правилом"))
    if not (diag.facts.get("py_listener_paths") or []):
        lines.append("(слушающих python-процессов не найдено)")
    lines.append("Установленные версии Python (py -0p):")
    for line in (diag.facts.get("py_versions") or [])[:40]:
        lines.append("    " + str(line).strip())
    lines.append("Полные пути из правил брандмауэра (Program):")
    for r in (diag.facts.get("fw_python_allow_in") or []):
        lines.append("    " + str(r.get("Program") or "(любая программа)"))
    lines.append("")
    lines.append("--- ЖУРНАЛ БЛОКИРОВОК БРАНДМАУЭРА ---")
    for line in (diag.facts.get("fwlog_drops") or []):
        lines.append(line)
    if not (diag.facts.get("fwlog_drops") or []):
        lines.append("(строк с адресами телефона/ноутбука нет)")
    lines.append("")
    lines.append("Если журнал нужно включить (консоль администратора):")
    lines.append("    netsh advfirewall set allprofiles logging droppedconnections enable")
    lines.append("    netsh advfirewall set allprofiles logging maxfilesize 16384")
    lines.append("")
    lines.append("--- СОСЕДИ (ARP) ---")
    for row in (diag.facts.get("neighbors_clean") or []):
        lines.append(json.dumps(row, ensure_ascii=False, default=str))
    lines.append("")
    lines.append("--- ЗАПРОСЫ К ТЕСТОВОМУ СЕРВЕРУ ---")
    for hit in diag.hits:
        lines.append(json.dumps(hit, ensure_ascii=False))
    if not diag.hits:
        lines.append("(запросов не было)")
    lines.append("")
    lines.append("--- ВЕРДИКТ ---")
    lines.append(verdict["headline"])
    for reason, score in (verdict.get("reasons") or []):
        lines.append(f"  {score:>3}%  {reason}")
    for msg in verdict.get("steps") or []:
        lines.append(f"  {msg}")
    if extra:
        lines.append("")
        lines.append("--- ДОПОЛНИТЕЛЬНО ---")
        for k, v in extra.items():
            lines.append(f"{k}: {v}")
    lines.append("")
    return "\n".join(lines)


# =========================================================================================
#  10. ТЕСТОВЫЙ HTTP-СЕРВЕР (слушает 0.0.0.0 и показывает каждый запрос)
# =========================================================================================

PAGE_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NET DOCTOR — тестовый сервер :$PORT$</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 18px; background: #0f1420; color: #e8eef8;
         font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .sub { color: #8fa2c0; font-size: 14px; margin-bottom: 16px; }
  .card { background: #171e2e; border: 1px solid #26314a; border-radius: 14px;
          padding: 14px 16px; margin: 12px 0; }
  .banner { border-radius: 14px; padding: 16px; margin: 14px 0; font-weight: 600;
            font-size: 18px; text-align: center; }
  .ok { background: #10361f; border: 1px solid #1c6b39; color: #7bf5a8; }
  .warn { background: #3a2e10; border: 1px solid #7a6116; color: #ffe08a; }
  .row { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0;
         border-bottom: 1px dashed #26314a; }
  .row:last-child { border-bottom: 0; }
  .k { color: #8fa2c0; }
  .v { text-align: right; word-break: break-all; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 7px 6px; border-bottom: 1px solid #26314a;
           word-break: break-all; }
  th { color: #8fa2c0; font-weight: 500; }
  code { background: #0b1020; padding: 2px 6px; border-radius: 6px; color: #9fe8ff; }
  a { color: #7cc7ff; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px;
          font-size: 12px; background: #26314a; color: #cfe1ff; }
  .pill.ext { background: #1c6b39; color: #b6ffd0; }
  .pill.loc { background: #4a3a16; color: #ffe08a; }
  ol { padding-left: 22px; }
  li { margin: 5px 0; }
</style>
</head>
<body>
  <h1>🩺 NET DOCTOR</h1>
  <div class="sub">Тестовый сервер на порту <b>$PORT$</b>. Он слушает 0.0.0.0 — то есть все
    сетевые интерфейсы ноутбука.</div>

  <div id="banner" class="banner warn">Проверяю, откуда вы открыли страницу…</div>

  <div class="card">
    <div class="row"><span class="k">Адрес страницы (как видит вас сервер)</span>
      <span class="v"><code id="host"></code></span></div>
    <div class="row"><span class="k">LAN-адреса ноутбука</span>
      <span class="v" id="ips">…</span></div>
    <div class="row"><span class="k">Запросов всего</span><span class="v" id="cnt">0</span></div>
  </div>

  <div class="card">
    <h3 style="margin-top:0">Онлайн-журнал запросов</h3>
    <table>
      <thead><tr><th>Время</th><th>Кто</th><th>Откуда</th><th>Путь</th></tr></thead>
      <tbody id="hits"><tr><td colspan="4" style="color:#8fa2c0">пока пусто</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <h3 style="margin-top:0">Что делать дальше</h3>
    <ol>
      <li>Если вы видите эту страницу <b>с телефона</b> — канал «телефон → ноутбук»
          полностью работает. Проблема была в самом приложении (чаще всего
          <code>host='127.0.0.1'</code> вместо <code>'0.0.0.0'</code>).</li>
      <li>Проверьте свой настоящий сервер:
          <code>python net_doctor.py --check-port 5000</code> (подставьте свой порт).</li>
      <li>Проверка «жив ли сервер прямо сейчас»:
          <a id="pinglink" href="/api/ping"><code>/api/ping</code></a>.</li>
      <li>Страница обновляется сама каждые 2 секунды.</li>
    </ol>
  </div>

<script>
async function tick() {
  try {
    const r = await fetch('/api/status', {cache: 'no-store'});
    const s = await r.json();
    document.getElementById('host').textContent = location.host;
    document.getElementById('ips').textContent = (s.ips || []).join(', ') || 'нет';
    document.getElementById('cnt').textContent = (s.hits || []).length;
    const body = document.getElementById('hits');
    body.innerHTML = '';
    if (!s.hits || !s.hits.length) {
      body.innerHTML = '<tr><td colspan="4" style="color:#8fa2c0">пока пусто</td></tr>';
    }
    (s.hits || []).slice().reverse().forEach(h => {
      const tr = document.createElement('tr');
      const cls = h.local ? 'loc' : 'ext';
      const label = h.local ? 'локально' : 'другое устройство';
      tr.innerHTML = '<td>' + h.time + '</td>' +
        '<td>' + h.ip +
        (h.via_proxy ? ' <span class="pill">через прокси?</span>' : '') + '</td>' +
        '<td><span class="pill ' + cls + '">' + label + '</span></td>' +
        '<td>' + h.path + '</td>';
      body.appendChild(tr);
    });
    const hostname = location.hostname;
    const isLocal = (s.ips || []).includes(hostname) ||
                    hostname === '127.0.0.1' || hostname === 'localhost';
    const b = document.getElementById('banner');
    if (isLocal) {
      b.className = 'banner warn';
      b.innerHTML = 'Страница открыта НА САМОМ НОУТБУКЕ. Теперь откройте этот адрес на телефоне: ' +
                    '<br><code>http://' + ((s.ips && s.ips[0]) || hostname) + ':' + $PORT$ + '/</code>';
    } else {
      b.className = 'banner ok';
      b.innerHTML = '📱 ЗАПРОС ПРИШЁЛ С ДРУГОГО УСТРОЙСТВА (' + hostname + ')! Канал работает.';
    }
  } catch (e) { /* сервер мог закрыться */ }
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


class _TestServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(diag: Diag, port: int, started: float,
                 on_hit: Optional[Callable[[Dict[str, Any]], None]] = None):
    """Создаёт обработчик, который запоминает каждый запрос и отдаёт страницу."""

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "netdoctor/" + VERSION
        sys_version = ""

        def log_message(self, *args: Any) -> None:   # печатаем сами
            pass

        def parse_request(self) -> bool:   # noqa: N802
            """
            Ловим «сырые» запросы: TLS-приветствие (открытие https://) и вообще всё,
            что не разбирается как HTTP.

            Зачем: обычный HTTP-сервер в этом случае отвечает ошибкой 400 и НЕ попадает
            в журнал. Из-за этого казалось, что «телефон не достучался», хотя пакеты
            доходили до ноутбука — на реальном запуске это была одна из слепых зон.
            """
            ok = super().parse_request()
            if not ok:
                try:
                    raw = getattr(self, "raw_requestline", b"") or b""
                    self._record_raw(raw)
                except Exception:
                    pass
            return ok

        def _record_raw(self, raw: bytes) -> None:
            """Пишем в журнал подключение, которое не удалось разобрать как HTTP."""
            note = describe_raw_request(raw)
            hit = diag.add_hit(self.client_address[0], "<не HTTP>", "(сырые данные)",
                               port, headers={})
            hit["raw"] = True
            hit["note"] = note
            if on_hit:
                try:
                    on_hit(hit)
                except Exception:
                    pass

        # ---- утилиты ---------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str, head_only: bool = False) -> None:
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                if not head_only:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _record(self) -> Dict[str, Any]:
            ua = ""
            try:
                ua = self.headers.get("User-Agent", "") if self.headers else ""
            except Exception:
                pass
            headers = {}
            try:
                headers = {k: v for k, v in (self.headers.items() if self.headers else [])}
            except Exception:
                pass
            return diag.add_hit(self.client_address[0], self.path, ua, port,
                                headers=headers)

        # ---- маршруты --------------------------------------------------------
        def do_GET(self) -> None:      # noqa: N802 (имя задано стандартом)
            self._handle(head_only=False)

        def do_HEAD(self) -> None:     # noqa: N802
            self._handle(head_only=True)

        def do_POST(self) -> None:     # noqa: N802
            self._handle(head_only=False)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._record()
            self._send(204, b"", "text/plain")

        def _handle(self, head_only: bool) -> None:
            hit = self._record()
            if on_hit:
                try:
                    on_hit(hit)
                except Exception:
                    pass
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html", "/test"):
                body = PAGE_HTML.replace("$PORT$", str(port)).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8", head_only)
            elif path == "/api/ping":
                body = json.dumps({"pong": True, "port": port, "time":
                                   _dt.datetime.now().isoformat(timespec="seconds")},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8", head_only)
            elif path == "/api/status":
                payload = {
                    "version": VERSION,
                    "port": port,
                    "uptime_sec": round(time.time() - started, 1),
                    "hostname": diag.facts.get("hostname"),
                    "ips": diag.facts.get("ips") or [],
                    "hits": list(diag.hits),
                }
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8", head_only)
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon", head_only)
            else:
                body = ("<html><meta charset='utf-8'><body style='background:#0f1420;"
                        "color:#e8eef8;font:16px system-ui;padding:24px'>"
                        f"<h2>NET DOCTOR: путь <code>{_html.escape(path)}</code> не найден</h2>"
                        "<p>Сервер жив и отвечает — но такой страницы у него нет.</p>"
                        "<p>Это тоже полезный результат: значит запрос ДОШЁЛ до ноутбука.</p>"
                        "<p><a style='color:#7cc7ff' href='/'>На главную</a></p></body></html>"
                        ).encode("utf-8")
                self._send(404, body, "text/html; charset=utf-8", head_only)

        # ---- чтобы «Context-Broken» клиенты не сыпали трейсбеками -------------
        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            except (ConnectionResetError, BrokenPipeError, TimeoutError):
                self.close_connection = True

    return Handler


def precheck_port_free(port: int) -> Optional[str]:
    """Проверяет, что порт реально свободен (без SO_REUSEADDR-фокусов Windows)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if IS_WINDOWS:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except (AttributeError, OSError):
            pass
    try:
        s.bind(("0.0.0.0", port))
        return None
    except OSError as exc:
        return str(exc)
    finally:
        try:
            s.close()
        except OSError:
            pass


def start_test_server(diag: Diag, port: int,
                      log: Callable[[str], None]) -> Optional[_TestServer]:
    err = precheck_port_free(port)
    if err:
        diag.add("server_start", f"Тестовый сервер на {port}", "bad",
                 f"порт занят: {err}",
                 f"Выберите другой порт: python net_doctor.py --port {port + 1}")
        return None
    handler = make_handler(diag, port, time.time(),
                           on_hit=lambda hit: log(_fmt_hit(hit)))
    try:
        srv = _TestServer(("0.0.0.0", port), handler)
    except OSError as exc:
        diag.add("server_start", f"Тестовый сервер на {port}", "bad", str(exc))
        return None
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3},
                              daemon=True, name="netdoctor-http")
    thread.start()
    diag.add("server_start", f"Тестовый сервер на {port}", "ok",
             f"поднят на 0.0.0.0:{port}")
    try:
        diag.facts.setdefault("listeners_clean", []).append(
            {"address": "0.0.0.0", "port": port, "pid": os.getpid(),
             "name": "python (netdoctor)", "path": "", "v6": False})
    except Exception:
        pass
    return srv


def qr_lines(text: str) -> Optional[List[str]]:
    """
    Строит QR-код для текста и возвращает готовые строки для печати.
    Требуется библиотека qrcode (необязательная, ставится как pip install qrcode).
    Если её нет — возвращает None, и мы просто печатаем адрес текстом.
    """
    try:
        import qrcode  # type: ignore
    except Exception:
        return None
    try:
        qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = [[bool(v) for v in row] for row in qr.get_matrix()]
    except Exception:
        return None
    if not matrix:
        return None
    if not (_can_print("█") and _can_print("▀") and _can_print("▄")):
        return None
    lines: List[str] = []
    for y in range(0, len(matrix), 2):
        top = matrix[y]
        bottom = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(top)
        row = ""
        for x in range(len(top)):
            t, b = top[x], bottom[x]
            row += "█" if (t and b) else ("▀" if t else ("▄" if b else " "))
        lines.append(row)
    return lines


def print_qr(url: str, legend: str = "") -> bool:
    lines = qr_lines(url)
    if not lines:
        return False
    pad = max(0, (len(lines[0]) - 4) // 2)
    for line in lines:
        print("    " + col(line, C.WHITE))
    if legend:
        print("    " + col(" " * pad + legend, C.GREY))
    return True


def _fmt_hit(hit: Dict[str, Any]) -> str:
    kind = "локально" if hit["local"] else "ДРУГОЕ УСТРОЙСТВО"
    if hit.get("raw"):
        return (col(SYM["phone"] + " ", C.MAGENTA) +
                col(f"попытка {hit['time']} от {hit['ip']}", C.BOLD) +
                col(f" [{kind}] запрос не распознан: {hit.get('note', '')}", C.YELLOW))
    return (col(SYM["phone"] + " ", C.MAGENTA) +
            col(f"запрос {hit['time']} от {hit['ip']}", C.BOLD) +
            col(f" [{kind}] {hit['path']} · {hit['ua'][:70]}", C.GREY))


# =========================================================================================
#  11. ЭТАПЫ И ИХ ИТОГ (та самая «где рвётся цепочка»)
# =========================================================================================

def stage_rows(diag: Diag, external_hit: bool) -> List[Tuple[str, str, str]]:
    """Возвращает [(этап, статус, пояснение)] — сжатая картина всей цепочки."""
    facts = diag.facts
    rows: List[Tuple[str, str, str]] = []

    ips = facts.get("ips") or []
    rows.append(("1. Сеть ноутбука (получены адреса)", "ok" if ips else "bad",
                 ", ".join(ips) or "нет ни одного адреса"))

    check = diag.get("net_profile")
    st = check.status if check else "skip"
    rows.append(("2. Профиль сети (Public/Private)", st,
                 diag.get("net_profile").detail if check else "нет данных"))

    check = diag.get("firewall_state")
    st = check.status if check else "skip"
    rows.append(("3. Брандмауэр (входящие)", st, check.detail if check else "нет данных"))

    check = diag.get("firewall_python")
    st = check.status if check else "skip"
    rows.append(("4. Разрешение для python.exe", st, check.detail if check else "нет данных"))

    check = diag.get("bind")
    st = check.status if check else "skip"
    rows.append((f"5. Порт свободен и слушается", st, check.detail if check else "нет данных"))

    check = diag.get("local_http")
    st = check.status if check else "skip"
    rows.append(("6. Ответ по 127.0.0.1", st, check.detail if check else "нет данных"))

    check = diag.get("lan_http")
    st = check.status if check else "skip"
    rows.append(("7. Ответ по 192.168.x.x (с ноутбука)", st,
                 check.detail if check else "нет данных"))

    ext_hits = diag.external_hits()
    if external_hit:
        who = ", ".join(sorted({h["ip"] for h in ext_hits}))
        rows.append(("8. Запрос С ДРУГОГО УСТРОЙСТВА", "ok", f"пришёл от {who}"))
    else:
        rows.append(("8. Запрос С ДРУГОГО УСТРОЙСТВА", "bad",
                     "не пришёл — проблема на этом участке"))
    return rows


def print_stages(diag: Diag, external_hit: bool) -> None:
    title("ЦЕПОЧКА: ГДЕ ПРОВАЛ")
    for name, status, detail in stage_rows(diag, external_hit):
        mark = col(SYM[status], STATUS_COLOR[status], C.BOLD)
        print(f"  {mark}  {name:<42}" + col(detail[:100], C.GREY))


# =========================================================================================
#  12. ОСНОВНОЙ ХОД
# =========================================================================================

def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="net_doctor.py",
        description="NET DOCTOR — пошаговая диагностика доступа к Python-серверам "
                    "из локальной сети (телефон не видит http://192.168.x.x:порт).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Коды возврата: 0 — проблем не найдено (или телефон достучался),\n"
               "               2 — найдены проблемы, 1 — внутренняя ошибка, 130 — прервано.\n\n"
               "Примеры:\n"
               "  python net_doctor.py\n"
               "  python net_doctor.py --check-port 5000 --phone 192.168.0.61\n"
               "  python net_doctor.py --port 8770 --wait 180\n"
               "  python net_doctor.py --no-server --fix\n")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"порт тестового сервера (по умолчанию {DEFAULT_PORT})")
    p.add_argument("--extra-port", type=int, action="append", default=[],
                   help="дополнительный порт для правила брандмауэра (можно несколько раз)")
    p.add_argument("--check-port", type=int, default=None,
                   help="дополнительно проверить ВАШ порт: кто слушает и где")
    p.add_argument("--phone", default=None,
                   help="IP-адрес телефона (для проверок подсети и ping)")
    p.add_argument("--wait", type=float, default=120.0,
                   help="сколько секунд ждать запрос с телефона (по умолчанию 120)")
    p.add_argument("--no-server", action="store_true",
                   help="не поднимать тестовый сервер")
    p.add_argument("--open", action="store_true",
                   help="открыть страницу тестового сервера в браузере ноутбука")
    p.add_argument("--fix", action="store_true",
                   help="создать netdoctor_fix.ps1 / netdoctor_undo.ps1")
    p.add_argument("--apply-fix", action="store_true",
                   help="создать и сразу запустить fix-скрипт (будет запрос UAC)")
    p.add_argument("--program-rule", action="store_true",
                   help="в fix-скрипт добавить разрешение для python.exe целиком (LAN)")
    p.add_argument("--iface", default=None,
                   help="имя сетевого интерфейса для перевода в Private "
                        "(по умолчанию — определяется сам)")
    p.add_argument("--report", default=None,
                   help="куда сохранить отчёт (по умолчанию netdoctor_report.txt)")
    p.add_argument("--fixdir", default=None,
                   help="куда сохранить ps1-файлы (по умолчанию текущая папка)")
    p.add_argument("--no-qr", action="store_true",
                   help="не печатать QR-код (если мешает или нет библиотеки qrcode)")
    p.add_argument("--no-color", action="store_true", help="без цветов")
    p.add_argument("--color", action="store_true", help="форсировать цвета")
    p.add_argument("--selftest", action="store_true", help="прогнать самотесты инструмента")
    p.add_argument("--version", action="version", version=f"netdoctor {VERSION}")
    return p.parse_args(list(argv) if argv is not None else None)


def detect_primary_interface(diag: Diag) -> Optional[str]:
    """Интерфейс, которому принадлежит «основной» LAN-адрес."""
    primary = diag.facts.get("primary_ip")
    for row in (diag.facts.get("ipaddresses") or []):
        if isinstance(row, dict) and str(row.get("IPAddress")) == primary:
            return str(row.get("InterfaceAlias") or "") or None
    # запасной вариант: интерфейс из профиля (Wi-Fi/Ethernet)
    for row in (diag.facts.get("profiles") or []):
        if isinstance(row, dict) and row.get("InterfaceAlias"):
            return str(row.get("InterfaceAlias"))
    return None


def collect_facts(diag: Diag) -> None:
    if IS_WINDOWS:
        collect_windows_facts(diag)
    else:
        collect_posix_facts(diag)
        diag.add("windows_only", "Windows-специфичные проверки", "skip",
                 "эта ОС не Windows — часть проверок недоступна",
                 "Инструмент рассчитан на Windows; на этой системе показываем "
                 "только общую часть.")


def run_checks_without_server(diag: Diag, args: argparse.Namespace) -> None:
    # check_env здесь НЕ вызываем: он уже вызван в run_diagnostics, иначе проверка
    # «Система и права» попадала в отчёт дважды.
    check_adapters(diag)
    check_profiles(diag)
    check_firewall(diag)
    check_routes(diag)
    check_proxy(diag)
    check_warp(diag)
    check_av(diag)
    check_hosts(diag)
    check_neighbors(diag, args.phone)
    check_phone(diag, args.phone)
    check_ssid(diag)
    check_ics(diag)
    check_python_procs(diag)
    check_listeners(diag, watch_port=args.check_port)
    check_python_paths(diag)
    check_firewall_log(diag, args.phone)


def wait_for_phone(diag: Diag, seconds: float, port: int,
                   no_qr: bool = False) -> Dict[str, Any]:
    """
    Ждёт запрос «извне» и рассказывает, что именно показать на телефоне.

    Возвращает словарь:
      {"external_hit": bool, "raw_hit": bool, "closed_port": int|None,
       "arp_diff": {"new": {...}, "changed": {...}}}
    """
    result: Dict[str, Any] = {"external_hit": False, "raw_hit": False,
                              "closed_port": None, "arp_diff": {}}
    if seconds <= 0:
        return result

    facts = diag.facts
    ranked = rank_local_ips(facts)
    primary_rows = [r for r in ranked
                    if r["score"] <= 1 and not r["apipa"] and not r["ics"]]
    other_rows = [r for r in ranked if r not in primary_rows]
    top_ip = primary_rows[0]["ip"] if primary_rows else (facts.get("primary_ip") or "")
    closed_port = pick_closed_port(port)
    result["closed_port"] = closed_port
    facts["closed_port"] = closed_port
    facts["ip_ranking"] = ranked

    print()
    print(col("=" * 86, C.BLUE))
    print(col("  ТЕПЕРЬ ВОЗЬМИТЕ ТЕЛЕФОН (он должен быть в ТОЙ ЖЕ Wi-Fi сети):", C.BOLD))
    for r in primary_rows:
        print(f"    {SYM['arrow']}  " + col(f"http://{r['ip']}:{port}/", C.BOLD, C.GREEN)
              + col(f"   — {r['reason']}", C.GREY))
    if other_rows:
        print(col("  Эти адреса телефону НЕ подойдут (служебные адаптеры/заглушки):", C.GREY))
        for r in other_rows[:6]:
            print(col(f"    · http://{r['ip']}:{port}/ — {r['reason']}", C.GREY))
    print(col("  Памятка: открывайте адрес ровно с http:// (не https); VPN и мобильный", C.YELLOW))
    print(col("  интернет на телефоне на время проверки выключены; SSID — тот же.", C.YELLOW))
    if closed_port and top_ip:
        print()
        print(col(f"  КОНТРОЛЬНЫЙ ТЕСТ (закрытый порт): http://{top_ip}:{closed_port}/", C.CYAN, C.BOLD))
        print(col("    «Отказано в подключении» = пакеты ДОХОДЯТ до ноутбука (значит блокирует "
                  "сам ноутбук: фаервол/антивирус).", C.GREY))
        print(col("    «Время ожидания истекло» = пакеты, скорее всего, НЕ доходят "
                  "(роутер/гостевая сеть/VPN на телефоне).", C.GREY))
    print(col("  Если Windows спросит «Разрешить доступ к сети?» — нажмите «Разрешить доступ».",
              C.YELLOW))
    if not no_qr and top_ip:
        print()
        if print_qr(f"http://{top_ip}:{port}/", "наведите камеру телефона"):
            print(col("  (QR-код ведёт на правильный адрес: " + top_ip + ")", C.GREY))
    print(col("=" * 86, C.BLUE))

    arp_before = arp_snapshot()
    deadline = time.time() + seconds
    printed = 0
    last_beat = time.time()
    hit_local = False
    while time.time() < deadline:
        time.sleep(0.35)
        hits = list(diag.hits)
        while printed < len(hits):
            hit = hits[printed]
            printed += 1
            if hit["local"]:
                hit_local = True
        external = diag.external_hits()
        if external:
            raw_external = [h for h in external if h.get("raw")]
            if raw_external:
                print()
                bad("С ТЕЛЕФОНА ПРИШЛИ ПАКЕТЫ, но запрос не похож на обычный HTTP:")
                for h in raw_external[:3]:
                    print(col(f"    от {h['ip']}: {h.get('note', '')}", C.YELLOW))
                info("Значит сеть «телефон ↔ ноутбук» РАБОТАЕТ. Откройте адрес ровно как "
                     "http://" + (top_ip or "<IP>") + f":{port}/ — без https — "
                     "или просто наведите камеру на QR-код.")
                result["external_hit"] = True
                result["raw_hit"] = True
            else:
                print()
                good("ЗАПРОС ДОШЁЛ С ДРУГОГО УСТРОЙСТВА — канал «телефон → ноутбук» РАБОТАЕТ!")
                result["external_hit"] = True
            break
        if time.time() - last_beat >= 15:
            last_beat = time.time()
            left = max(0.0, deadline - time.time())
            tail = ""
            if hit_local:
                tail = col("  (локальные заходы были — сервер точно отвечает)", C.GREY)
            print(col(f"    … жду запроса с телефона, осталось {left:.0f} с{tail}", C.GREY))

    arp_after = arp_snapshot()
    arp_diff = diff_arp(arp_before, arp_after)
    result["arp_diff"] = arp_diff
    diag.facts["arp_diff"] = arp_diff

    if arp_diff.get("new") or arp_diff.get("changed"):
        print()
        info("В таблице соседей произошли изменения (значит, обмен пакетами с кем-то шёл):")
        for ip, state in list(arp_diff.get("new", {}).items())[:5]:
            print(col(f"    появился {ip}: {state} — возможно, это ваш телефон", C.CYAN))
        for ip, (was, now) in list(arp_diff.get("changed", {}).items())[:5]:
            print(col(f"    {ip}: было {was}, стало {now}", C.GREY))

    if not result["external_hit"]:
        print()
        warn(f"Запросов с телефона не было за {seconds:.0f} с.")
        if hit_local:
            info("Зато были локальные заходы — сам сервер и порт работают.")
        if arp_diff.get("new"):
            info("Но появились новые соседи в ARP — пакеты от телефона, скорее всего, "
                 "доходят до ноутбука, а соединение блокируется уже на нём "
                 "(фаервол Windows/антивирус).")
    return result


# =========================================================================================
def write_fix_files(args: argparse.Namespace, diag: Diag) -> List[str]:
    outdir = args.fixdir or os.getcwd()
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        outdir = os.getcwd()
    iface = args.iface or detect_primary_interface(diag)
    extra = list(args.extra_port or [])
    if args.check_port:
        extra.append(args.check_port)
    extra += [5000, 8000]
    extra = unique_ports(extra)
    fix_path = os.path.join(outdir, "netdoctor_fix.ps1")
    undo_path = os.path.join(outdir, "netdoctor_undo.ps1")
    with open(fix_path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        py_paths = [str(r.get("path")) for r in (diag.facts.get("py_listener_paths") or [])
                    if r.get("path")]
        fh.write(build_fix_ps(args.port, extra, iface, args.program_rule, py_paths=py_paths))
    with open(undo_path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(build_undo_ps())
    return [fix_path, undo_path]


def apply_fix(fix_path: str) -> None:
    ps = which_powershell()
    if not ps:
        bad("PowerShell не найден — запустите netdoctor_fix.ps1 вручную.")
        return
    info("Запускаю fix-скрипт (сейчас Windows попросит права администратора)…")
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", fix_path]
    rc, out, err = run(cmd, timeout=300)
    if out:
        print(out)
    if err.strip():
        print(col(err.strip()[:2000], C.GREY))
    if rc == 0:
        good("Скрипт выполнен. Если в выводе выше есть 'OK' — правило добавлено.")
    else:
        warn(f"Скрипт завершился с кодом {rc} (часто это отказ в UAC или уже "
             "запущенный экземпляр).")


def save_report(text: str, path: Optional[str]) -> str:
    target = path or os.path.join(os.getcwd(), "netdoctor_report.txt")
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        warn(f"не удалось сохранить отчёт в {target}: {exc}")
        target = os.path.join(tempfile.gettempdir(), "netdoctor_report.txt")
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            return ""
    return target


class _UI:
    """Очень маленькая прослойка языка: пока только ru, но строки собраны в одном месте."""

    def __init__(self) -> None:
        self.lang = "ru"


_ui = _UI()


def run_diagnostics(args: argparse.Namespace) -> int:
    diag = Diag()

    title(f"NET DOCTOR {VERSION} — почему телефон не видит мой Python-сервер")
    print(col("  Ничего не меняем без вашего согласия. Единственное, что создаётся —\n"
              "  файл-починка netdoctor_fix.ps1 в текущей папке (только с ключом --fix).",
              C.GREY))
    print(col(f"  Система: {platform.platform()} · Python {platform.python_version()} · "
              f"старт {diag.started.strftime('%H:%M:%S')}", C.GREY))

    # ---- 1/6 окружение -----------------------------------------------------------
    step("1/6", "Собираю конфигурацию сети и Windows…")
    collect_facts(diag)
    check_env(diag)
    diag.show("env_os")
    if not diag.facts.get("ips"):
        bad("У ноутбука нет ни одного сетевого адреса — проверьте Wi-Fi/кабель. "
            "Дальше смотреть мало смысла, но продолжу.")

    # ---- 2/6 проверки без сервера -------------------------------------------------
    step("2/6", "Проверяю сеть, профиль, брандмауэр, VPN, прокси…")
    run_checks_without_server(diag, args)
    for key in ("ps_collect", "adapters_vpn", "net_profile", "firewall_state",
                "firewall_python", "firewall_python_scope", "routes", "proxy", "warp",
                "av", "hosts", "ics", "neighbors", "neighbor_phone", "phone_subnet",
                "phone_ping", "ssid", "py_procs", "listeners_loopback", "python_paths",
                "watch_port", "firewall_log"):
        if diag.get(key):
            diag.show(key)

    # ---- 3/6 тестовый сервер ------------------------------------------------------
    external_hit = False
    raw_external_hit = False
    server: Optional[_TestServer] = None
    arp_before_server = arp_snapshot()
    log = lambda line: print(line)  # noqa: E731

    if args.no_server:
        step("3/6", "Тестовый сервер отключён (--no-server) — ждать запрос с телефона не буду.")
    else:
        step("3/6", f"Проверяю порт {args.port} и поднимаю тестовый сервер…")
        # Сначала выбираем реально свободный порт (конфликт — частая причина «не работает»).
        if precheck_port_free(args.port) is not None:
            for alt in range(args.port + 1, args.port + 12):
                if precheck_port_free(alt) is None:
                    info(f"порт {args.port} занят — беру свободный {alt}")
                    args.port = alt
                    break
        check_bind(diag, args.port)      # проверяем ДО запуска, иначе «занят» — мы сами
        diag.show("bind")
        server = start_test_server(diag, args.port, log)
        diag.show("server_start")

        if server is not None:
            # ---- 4/6 локальные проверки ------------------------------------------
            step("4/6", "Проверяю ответ сервера: 127.0.0.1 и все LAN-адреса…")
            check_local_reach(diag, args.port, diag.facts.get("ips") or [])
            diag.show("local_http")
            diag.show("lan_http")
            rec = recommended_ips(diag.facts)
            if rec:
                info("Адрес для телефона: " + col(f"http://{rec[0]['ip']}:{args.port}/",
                                                  C.BOLD, C.GREEN)
                     + col(f"  ({rec[0]['reason']})", C.GREY))
                diag.add("recommended_ip", "Рекомендованный адрес для телефона", "info",
                         f"http://{rec[0]['ip']}:{args.port}/ — {rec[0]['reason']}")
                diag.show("recommended_ip")
            if args.open:
                url = f"http://127.0.0.1:{args.port}/"
                info(f"открываю в браузере ноутбука: {url}")
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        else:
            step("4/6", "Сервер не запустился — локальные проверки пропущены.")

    # ---- 5/6 ждём телефон ---------------------------------------------------------
    if server is not None:
        step("5/6", "Жду запрос с телефона…")
        wait_result = wait_for_phone(diag, args.wait, args.port, no_qr=args.no_qr)
        external_hit = bool(wait_result.get("external_hit"))
        raw_external_hit = bool(wait_result.get("raw_hit"))
    else:
        step("5/6", "Ожидание телефона пропущено (нет тестового сервера).")

    # ---- 5b/6: журнал брандмауэра — читаем ЗАНОВО, уже после попыток с телефона -----
    if IS_WINDOWS and (external_hit or not args.no_server):
        before = list(diag.checks)
        diag.checks = [c for c in diag.checks if c.key not in ("firewall_log", "arp_after")]
        check_firewall_log(diag, args.phone)
        after = [c for c in diag.checks if c.key == "firewall_log"
                 and c not in before]
        if after:
            print()
            info("Журнал брандмауэра — перечитан после попыток с телефона:")
            diag.show("firewall_log")
        changed = diff_arp(arp_before_server, arp_snapshot())
        if changed.get("new"):
            diag.facts["arp_after_server"] = changed
            info("С момента старта в сети появились новые устройства: "
                 + ", ".join(f"{ip} ({st})" for ip, st in list(changed["new"].items())[:5]))

    # ---- 6/6 вердикт --------------------------------------------------------------
    step("6/6", "Собираю вердикт и отчёт…")
    verdict = build_verdict(diag, args.port, external_hit,
                            raw_external_hit=raw_external_hit)
    print_stages(diag, external_hit)
    print_verdict(diag, verdict)

    extra: Dict[str, Any] = {}
    report = build_report_text(diag, verdict, args.port, extra)
    path = save_report(report, args.report)
    if path:
        good(f"Отчёт сохранён: {path}")

    if args.fix or args.apply_fix:
        files = write_fix_files(args, diag)
        print()
        for f in files:
            print("  " + col(f, C.BOLD))
        info("Запуск (правый клик → «Выполнить с помощью PowerShell»), лучше от имени "
             "администратора:")
        print(col(f'     powershell -NoProfile -ExecutionPolicy Bypass -File "{files[0]}"',
                  C.GREY))
        info("Откат всех изменений — " + os.path.basename(files[1]))
        if args.apply_fix and IS_WINDOWS:
            if sys.stdin.isatty():
                try:
                    answer = input("Запустить fix сейчас (Windows спросит права)? [y/N] ")
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer.strip().lower().startswith(("y", "д")):
                    apply_fix(files[0])
            else:
                apply_fix(files[0])

    if server is not None:
        print()
        info("Тестовый сервер продолжает работать, пока открыто это окно. "
             "Ctrl+C — остановить.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print()
            info("Останавливаю тестовый сервер.")
        finally:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

    if external_hit:
        return 0
    return 2 if verdict["status"] == "bad" else 0


# =========================================================================================
#  13. САМОТЕСТЫ (для CI: python net_doctor.py --selftest)
# =========================================================================================

NETSH_SAMPLE = """Управление беспроводными сетями

    Состояние интерфейса "Беспроводная сеть":

    Имя                   : Беспроводная сеть
    Описание              : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                  : 11111111-2222-3333-4444-555555555555
    Физический адрес      : aa:bb:cc:dd:ee:ff
    Состояние             : подключено
    SSID                  : HomeNet-5G
    BSSID                 : 11:22:33:44:55:66
    Тип сети              : Инфраструктура
    Тип радио             : 802.11ax
    Проверка подлинности  : WPA2-Personal
    Шифр                  : CCMP
    Подключение по каналу : 5
    Сигнал                : 92%
"""


def run_selftest() -> int:
    print(col(f"NET DOCTOR {VERSION} — SELF TEST", C.BOLD))
    failures: List[str] = []
    passed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  {col(SYM['ok'], C.GREEN)} {name}")
        else:
            failures.append(name)
            print(f"  {col(SYM['bad'], C.RED)} {name}" + (f" — {detail}" if detail else ""))

    # --- 1. Кодировки и JSON ------------------------------------------------------
    raw = "Привет, мир".encode("cp866")
    check("decode_bytes: cp866", decode_bytes(raw) == "Привет, мир")
    check("decode_bytes: utf-8", decode_bytes("Тест".encode("utf-8")) == "Тест")
    check("extract_json: чистый", extract_json('{"a": 1}') == {"a": 1})
    check("extract_json: с мусором",
          extract_json('WARNING: blabla\n{"a": [1,2]}\n') == {"a": [1, 2]})

    # --- 2. Классификация адаптеров ----------------------------------------------
    check("adapter: WARP -> риск 3",
          classify_adapter("CloudflareWARP", "Cloudflare WARP Tunnel")[1] == 3)
    check("adapter: Wi-Fi -> риск 0",
          classify_adapter("Wi-Fi", "Intel(R) Wi-Fi 6 AX201")[1] == 0)
    check("adapter: Hyper-V -> риск 2",
          classify_adapter("vEthernet (Default Switch)", "Hyper-V Virtual Ethernet")[1] == 2)

    # --- 3. Подсети ---------------------------------------------------------------
    check("subnet: одна сеть", in_same_subnet("192.168.0.61", "192.168.0.60", 24) is True)
    check("subnet: разные сети", in_same_subnet("192.168.1.61", "192.168.0.60", 24) is False)
    check("subnet: мусор -> None", in_same_subnet("не-ip", "192.168.0.60", 24) is None)
    check("apipa: распознан", is_apipa("169.254.10.20") is True)
    check("is_local_ip: loopback", is_local_ip("127.0.0.1", []) is True)
    check("is_local_ip: свой адрес", is_local_ip("192.168.0.60", ["192.168.0.60"]) is True)
    check("is_local_ip: чужой", is_local_ip("192.168.0.61", ["192.168.0.60"]) is False)

    # --- 4. netsh ----------------------------------------------------------------
    ssid = parse_netsh_ssid(NETSH_SAMPLE)
    check("netsh: SSID", ssid.get("ssid") == "HomeNet-5G", str(ssid))
    check("netsh: сигнал", ssid.get("signal") == "92%", str(ssid))
    check("netsh: состояние", ssid.get("state") == "подключено", str(ssid))

    # --- 4b. PowerShell: баланс скобок и кавычек ---------------------------------
    ps_problems = []
    for name, body in list(PS_SECTIONS_FAST) + list(PS_SECTIONS_FIREWALL):
        err = ps_balance_check(body)
        if err:
            ps_problems.append(f"{name}: {err}")
    for label, text in (("fix", build_fix_ps(8770, [5000], "Wi-Fi", True)),
                        ("fix без интерфейса", build_fix_ps(8770, [5000, 8000], None, False)),
                        ("undo", build_undo_ps()),
                        ("header", _PS_HEADER)):
        err = ps_balance_check(text)
        if err:
            ps_problems.append(f"{label}: {err}")
    check("PowerShell: скобки/кавычки сбалансированы во всех сниппетах",
          not ps_problems, "; ".join(ps_problems))
    check("PowerShell: нет присваивания автоматической переменной $args",
          "$args =" not in build_fix_ps(8770, [5000], "Wi-Fi", True))
    check("PowerShell: порты без повторов",
          build_fix_ps(8770, [5000, 5000, 8000], "Wi-Fi", True).count("5000,8000") == 1)

    # --- 5. fix-скрипты -----------------------------------------------------------
    fix = build_fix_ps(8770, [5000, 8000], "Wi-Fi", True)
    check("fix: порты перечислены", "8770, 5000, 8000" in fix)
    check("fix: LocalSubnet", "LocalSubnet" in fix)
    check("fix: Private", "NetworkCategory Private" in fix)
    check("fix: проверка админа", "IsUserAnAdmin" not in fix and "Administrator" in fix)
    check("fix: правило python.exe", "netdoctor: python.exe (LAN)" in fix)
    undo = build_undo_ps()
    check("undo: удаляет netdoctor*", "Remove-NetFirewallRule" in undo)

    # --- 6. Вердикт ---------------------------------------------------------------
    d = Diag()
    d.facts.update({
        "ips": ["192.168.0.60"], "primary_ip": "192.168.0.60",
        "firewall_all_inbound_blocked": [], "profile_public": ["Wi-Fi"],
        "fw_python_allow_in": [], "warp_traces": ["адаптер «CloudflareWARP» (Cloudflare WARP) — Up"],
        "default_routes": [{"DestinationPrefix": "0.0.0.0/0", "InterfaceAlias": "Wi-Fi"}],
        "av_third_party": [], "proxy_enabled": False,
    })
    d.add("net_profile", "Профиль", "warn", "", fix_ps=["Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private"])
    verdict = build_verdict(d, 8770, external_hit=False)
    check("вердикт: найдены причины", len(verdict.get("reasons") or []) >= 2)
    check("вердикт: Public в топе", any("Общедоступ" in r for r, _ in verdict["reasons"]))
    check("вердикт: WARP упомянут", any("WARP" in r for r, _ in verdict["reasons"]))
    check("вердикт: откат статуса при успехе",
          build_verdict(d, 8770, external_hit=True)["status"] == "ok")

    # --- 7. Живой сервер ---------------------------------------------------------
    srv_diag = Diag()
    srv_diag.facts["ips"] = ["127.0.0.1", "192.168.0.60"]
    srv_diag.facts["hostname"] = "test-host"
    tmp_port = free_port()
    handler = make_handler(srv_diag, tmp_port, time.time())
    try:
        srv = _TestServer(("127.0.0.1", tmp_port), handler)
    except OSError as exc:
        check("сервер: запуск", False, str(exc))
        srv = None
    if srv is not None:
        th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2},
                              daemon=True)
        th.start()
        try:
            ok_ping, detail_ping = http_probe(f"http://127.0.0.1:{tmp_port}/api/ping")
            check("сервер: /api/ping отвечает", ok_ping, detail_ping)
            ok_page, detail_page = http_probe(f"http://127.0.0.1:{tmp_port}/")
            check("сервер: главная страница", ok_page, detail_page)
            ok_404, _ = http_probe(f"http://127.0.0.1:{tmp_port}/no-such-page")
            check("сервер: незнакомый путь -> HTTP-ошибка", ok_404)
            status = fetch_url_text(f"http://127.0.0.1:{tmp_port}/api/status")
            data = extract_json(status) or {}
            check("сервер: /api/status — JSON", isinstance(data, dict) and "hits" in data)
            check("сервер: запросы записаны", len(srv_diag.hits) >= 3, str(len(srv_diag.hits)))
            check("сервер: все запросы помечены локальными",
                  all(h["local"] for h in srv_diag.hits))
            ext = [h for h in srv_diag.hits if not h["local"]]
            check("сервер: пометка «извне» работает", ext == [])
        finally:
            srv.shutdown()
            srv.server_close()

    # --- 8. Порты -----------------------------------------------------------------
    check("precheck_port_free: свободный порт -> None", precheck_port_free(free_port()) is None)
    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        busy.bind(("0.0.0.0", 0))
        busy.listen(1)
        busy_port = busy.getsockname()[1]
        err = precheck_port_free(busy_port)
        check("precheck_port_free: занятый порт -> ошибка", bool(err), str(err))
    finally:
        busy.close()

    # --- 9. Этапы -----------------------------------------------------------------
    d2 = Diag()
    d2.facts.update({"ips": ["192.168.0.60"]})
    d2.add("net_profile", "Профиль", "warn")
    d2.add("firewall_state", "Брандмауэр", "ok")
    d2.add("firewall_python", "Правило", "warn")
    d2.add("bind", "Порт", "ok")
    d2.add("local_http", "127.0.0.1", "ok")
    d2.add("lan_http", "LAN", "bad")
    rows = stage_rows(d2, external_hit=False)
    check("этапы: 8 строк", len(rows) == 8, str(len(rows)))
    check("этапы: последний этап = провал", rows[-1][1] == "bad")
    check("этапы: порядок пронумерован", rows[0][0].startswith("1."))

    # --- 11. Защита от ложного «телефон достучался» ------------------------------
    d3 = Diag()
    d3.facts["ips"] = ["192.168.0.60"]
    h_self = d3.add_hit("192.168.0.60", "/api/ping", f"netdoctor/{VERSION}", 8770)
    h_like_self = d3.add_hit("127.0.0.1", "/api/ping", "curl/8.0", 8770)
    h_phone = d3.add_hit("192.168.0.61", "/", "Mozilla/5.0 (iPhone)", 8770)
    check("свой зонд с LAN-адреса не считается 'гостем'", h_self["local"] is True)
    check("заход с 127.0.0.1 не считается 'гостем'", h_like_self["local"] is True)
    check("запрос с телефона считается 'гостем'", h_phone["local"] is False)
    check("внешних запросов ровно один", len(d3.external_hits()) == 1,
          str([h["ip"] for h in d3.external_hits()]))

    # --- 10. QR-код (только если установлена необязательная библиотека qrcode) -----
    qr = qr_lines("http://192.168.0.60:8770/")
    if qr is None:
        print(f"  {col(SYM['skip'], C.GREY)} QR-код: библиотека qrcode не установлена "
              "(необязательно; инструмент работает и без неё)")
    else:
        check("QR: строки одинаковой ширины",
              len(set(len(x) for x in qr)) == 1 and len(qr) >= 10, str(len(qr)))
        check("QR: тихая зона слева/справа",
              all(x[0] == " " and x[-1] == " " for x in qr))

    # --- 12. РЕГРЕССИЯ на реальном логе -------------------------------------------
    # Этот набор повторяет факты с настоящего запуска на ноутбуке (LAPTOP-ANDRU):
    # там инструмент ошибочно рекомендовал 192.168.137.1 (мобильный хот-спот),
    # считал 169.254.* на служебных адаптерах причиной «DHCP сломался» на 60 %
    # и называл фоновую службу WARP активным туннелем.
    real_facts = {
        "ipaddresses": [
            {"IPAddress": "192.168.137.1", "InterfaceAlias": "Подключение по локальной сети* 2",
             "AddressState": 4, "PrefixLength": 24},
            {"IPAddress": "169.254.47.125", "InterfaceAlias": "VMware Network Adapter VMnet1",
             "AddressState": 4, "PrefixLength": 16},
            {"IPAddress": "169.254.187.104", "InterfaceAlias": "Сетевое подключение Bluetooth",
             "AddressState": 1, "PrefixLength": 16},
            {"IPAddress": "192.168.0.60", "InterfaceAlias": "Беспроводная сеть",
             "AddressState": 4, "PrefixLength": 24},
            {"IPAddress": "169.254.197.107", "InterfaceAlias": "VMware Network Adapter VMnet8",
             "AddressState": 4, "PrefixLength": 16},
            {"IPAddress": "169.254.191.189", "InterfaceAlias": "Подключение по локальной сети* 1",
             "AddressState": 1, "PrefixLength": 16},
        ],
        "adapters": [
            {"Name": "Беспроводная сеть",
             "InterfaceDescription": "Realtek 8822CE Wireless LAN 802.11ac PCI-E NIC",
             "Status": "Up"},
            {"Name": "Подключение по локальной сети* 2",
             "InterfaceDescription": "Microsoft Wi-Fi Direct Virtual Adapter #2", "Status": "Up"},
            {"Name": "VMware Network Adapter VMnet1",
             "InterfaceDescription": "VMware Virtual Ethernet Adapter for VMnet1", "Status": "Up"},
            {"Name": "VMware Network Adapter VMnet8",
             "InterfaceDescription": "VMware Virtual Ethernet Adapter for VMnet8", "Status": "Up"},
        ],
        "default_routes": [{"DestinationPrefix": "0.0.0.0/0", "NextHop": "192.168.0.1",
                            "InterfaceAlias": "Беспроводная сеть", "InterfaceIndex": 3,
                            "RouteMetric": 0}],
        "primary_ip": "192.168.0.60",
        "ips": ["192.168.137.1", "169.254.197.107", "169.254.47.125", "192.168.0.60",
                "169.254.187.104", "169.254.191.189"],
    }
    ranking = rank_local_ips(real_facts)
    check("рейтинг адресов: первым идёт адрес основной сети",
          bool(ranking) and ranking[0]["ip"] == "192.168.0.60",
          str([r["ip"] for r in ranking]))
    check("рейтинг адресов: 192.168.137.1 помечен как точка доступа",
          any(r["ip"] == "192.168.137.1" and r["ics"] for r in ranking))
    check("рейтинг адресов: телефону рекомендуем только 192.168.0.60",
          [r["ip"] for r in recommended_ips(real_facts)] == ["192.168.0.60"],
          str([r["ip"] for r in recommended_ips(real_facts)]))
    check("рейтинг адресов: APIPA-адреса в самом конце",
          ranking[-1]["apipa"] is True)

    d4 = Diag()
    d4.facts.update(real_facts)
    d4.facts.update({"firewall_all_inbound_blocked": [], "profile_public": [],
                     "fw_python_allow_in": [{"Program": "python.exe"}],
                     "warp_traces": [], "av_third_party": ["ESET Security"],
                     "av_firewall_strong": "ESET", "ics_detected": True})
    verdict = build_verdict(d4, 8770, external_hit=False)
    reasons_text = " | ".join(r for r, _ in (verdict.get("reasons") or []))
    check("вердикт: APIPA-шум больше не главная причина",
          "169.254" not in (reasons_text.split("|")[0] if reasons_text else ""),
          reasons_text)
    check("вердикт: сетевой экран ESET назван причиной", "ESET" in reasons_text, reasons_text)
    check("вердикт: упомянута точка доступа/137.1",
          ("хот-спот" in reasons_text) or ("192.168.137" in reasons_text), reasons_text)

    d5 = Diag()
    d5.facts.update({"vpn_services": [{"Name": "CloudflareWARP", "Status": 4},
                                      {"Name": "CloudflareWARPUpdater", "Status": 4}],
                     "vpn_procs": [{"ProcessName": "warp-svc", "Id": 8196}],
                     "warp": {"found": True}, "warp_hidden": [], "routes": [], "dns": [],
                     "adapters": []})
    check_warp(d5)
    warp_check = d5.get("warp")
    check("WARP: фоновая служба не выдаётся за активный туннель",
          warp_check is not None and warp_check.status in ("info", "ok"),
          warp_check.status if warp_check else "нет проверки")
    check("WARP: туннель признан НЕ активным",
          d5.facts.get("warp_tunnel_active") is False)
    check("WARP: статус службы расшифрован по-человечески",
          "работает" in (warp_check.detail if warp_check else ""),
          warp_check.detail if warp_check else "")

    v_raw = build_verdict(d4, 8770, external_hit=True, raw_external_hit=True)
    check("вердикт: https-попытка с телефона объясняется как «сеть работает»",
          v_raw["status"] == "warn" and "https" in v_raw["headline"], v_raw["headline"])

    diff = diff_arp({"192.168.0.1": "Reachable (aa)"},
                    {"192.168.0.1": "Reachable (aa)", "192.168.0.27": "Stale (bb)"})
    check("diff_arp: новый сосед (возможный телефон) найден", "192.168.0.27" in diff["new"])
    closed = pick_closed_port(8799)
    check("pick_closed_port: выбранный порт действительно закрыт",
          closed is not None and precheck_port_free(closed) is None, str(closed))
    check("дубль проверки «Система и права» устранён",
          "check_env(diag)" not in inspect.getsource(run_checks_without_server))

    # wait_for_phone целиком: без этого теста однажды проскочила ошибка
    # «'list' object is not callable» — список адресов перекрыл функцию печати.
    d6 = Diag()
    d6.facts.update(real_facts)
    d6.facts["local_ips"] = list(d6.facts["ips"])
    import threading as _th

    def _fake_phone() -> None:
        time.sleep(0.4)
        d6.add_hit("192.168.0.27", "/", "Mozilla/5.0 (Linux; Android 14)", 8770, {})

    _t = _th.Thread(target=_fake_phone, daemon=True)
    _t.start()
    _wr = wait_for_phone(d6, 5, 8770, no_qr=True)
    _t.join(timeout=2)
    check("wait_for_phone: внешний запрос поймали, рекомендован адрес Wi-Fi, функция не упала",
          _wr.get("external_hit") is True and _wr.get("raw_hit") is False)
    check("wait_for_phone: подсказан именно 192.168.0.60",
          "192.168.0.60" in (d6.facts.get("ip_ranking") and
                             str([r["ip"] for r in d6.facts["ip_ranking"] if r["score"] == 0])),
          str(d6.facts.get("ip_ranking")))
    check("рекомендация для телефона никогда не содержит APIPA",
          all(not r["apipa"] for r in recommended_ips(d6.facts)))

    # --- Пути python и правила брандмауэра (важно при нескольких версиях Python) ---
    check("пути .exe сравниваются без учёта регистра и слэшей",
          norm_exe_path(r"C:\Py\python.exe") == norm_exe_path("c:/py/PYTHON.EXE"))
    check("правило для всех программ покрывает любой exe",
          rule_covers_exe("Any", r"C:\x\pythonw.exe") is True)
    check("правило для одного python не покрывает другой",
          rule_covers_exe(r"C:\Users\u\AppData\Local\Programs\Python\Python312-32\python.exe",
                          r"C:\Users\u\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")
          is False)

    d7 = Diag()
    d7.facts.update({
        "listeners": [{"address": "0.0.0.0", "port": 5000, "pid": 42776, "name": "pythonw",
                       "path": r"C:\Users\u\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"}],
        "python_procs": [],
        "fw_python_allow_in": [
            {"Program": r"C:\Users\u\AppData\Local\Programs\Python\Python312-32\python.exe",
             "DisplayName": "Python 3.12", "RemoteAddress": "LocalSubnet"}],
    })
    check_python_paths(d7)
    pp_bad = d7.get("python_paths")
    check("«правила для другого python» — это проблема, а не «правило есть»",
          pp_bad is not None and pp_bad.status == "bad",
          pp_bad.status if pp_bad else "нет")

    d8 = Diag()
    d8.facts.update({
        "listeners": [{"address": "0.0.0.0", "port": 5000, "pid": 42776, "name": "pythonw",
                       "path": r"C:\Users\u\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"}],
        "python_procs": [],
        "fw_python_allow_in": [
            {"Program": r"C:\Users\u\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe",
             "DisplayName": "pythonw", "RemoteAddress": "LocalSubnet"}],
    })
    check_python_paths(d8)
    pp_ok = d8.get("python_paths")
    check("совпадающий путь — правило действительно покрывает процесс",
          pp_ok is not None and pp_ok.status == "ok",
          pp_ok.status if pp_ok else "нет")
    check("отчёт по путям попадает в факты",
          d8.facts.get("py_listener_paths") and d8.facts["py_listener_paths"][0]["covered"] is True)

    fix_txt = build_fix_ps(8770, [], "Wi-Fi", False,
                           py_paths=[r"C:\Users\u\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"])
    check("--fix добавляет правило для реально слушающего интерпретатора",
          "pythoncore-3.14-64" in fix_txt and "listenExes" in fix_txt)

    # --- 12. Гигиена лаунчеров Windows --------------------------------------------
    here = os.path.dirname(os.path.abspath(__file__))
    launchers = ("start_netdoctor.vbs", "start_netdoctor.bat")
    checked_launchers = 0
    for name in launchers:
        path = os.path.join(here, name)
        if not os.path.isfile(path):
            print("  " + col(SYM["skip"], C.GREY) +
                  f" лаунчер {name}: файла рядом нет — пропущено")
            continue
        checked_launchers += 1
        problems = launcher_problems(path)
        check(f"лаунчер {name}: гигиена (CRLF/кодировка/без chcp)",
              not problems, "; ".join(problems))

    # сама проверка тоже должна ловить плохой файл
    with tempfile.TemporaryDirectory() as tmp:
        bad_bat = os.path.join(tmp, "bad.bat")
        with open(bad_bat, "wb") as fh:
            fh.write("chcp 65001\n".encode("utf-8"))       # LF + chcp + BOM-less
        bad_problems = launcher_problems(bad_bat)
        check("проверка лаунчеров ловит плохой .bat", len(bad_problems) >= 2,
              "; ".join(bad_problems))

        good_vbs = os.path.join(tmp, "good.vbs")
        with open(good_vbs, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" +
                     "cmd = Chr(34) & \"net_doctor.py\"\r\n".encode("utf-8"))
        check("проверка лаунчеров принимает хороший .vbs",
              launcher_problems(good_vbs) == [],
              "; ".join(launcher_problems(good_vbs)))

    if checked_launchers == 0:
        print("  " + col(SYM["skip"], C.GREY) +
              " лаунчеры не найдены рядом с net_doctor.py — проверка пропущена")

    # --- итог ---------------------------------------------------------------------
    print()
    if failures:
        bad(f"ПРОВАЛЕНО: {len(failures)} из {len(failures) + passed}: "
            + ", ".join(failures))
        return 1
    good(f"ВСЁ ХОРОШО: пройдено {passed} проверок из {passed}.")
    return 0


def pick_closed_port(port: int) -> Optional[int]:
    """Порт рядом с нашим, где точно никто не слушает (для контрольного теста)."""
    for candidate in range(port + 11, port + 60):
        if precheck_port_free(candidate) is None:
            return candidate
    return None


def arp_snapshot() -> Dict[str, str]:
    """Снимок соседей (ARP): ip -> "состояние (MAC)". Пусто, если не удалось."""
    result: Dict[str, str] = {}
    if IS_WINDOWS:
        out = ps_one(
            "Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.State -ne 'Permanent' } | "
            "Select-Object IPAddress, LinkLayerAddress, @{n='St';e={\"$($_.State)\"}} | "
            "ConvertTo-Json -Compress", timeout=45)
        data = extract_json(out or "")
        if isinstance(data, dict):
            data = [data]
        for row in (data or []):
            if isinstance(row, dict) and row.get("IPAddress"):
                result[str(row["IPAddress"])] = (f"{row.get('St') or '?'} "
                                                 f"({row.get('LinkLayerAddress') or '?'})")
        return result
    for row in parse_ip_neigh_output():
        result[str(row.get("IPAddress"))] = (f"{row.get('State')} "
                                            f"({row.get('LinkLayerAddress') or '?'})")
    return result


def diff_arp(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Any]:
    """Что изменилось в таблице соседей (появились ли новые устройства)."""
    new = {ip: st for ip, st in after.items() if ip not in before}
    changed = {ip: (before[ip], after[ip]) for ip in after
               if ip in before and before[ip] != after[ip]}
    return {"new": new, "changed": changed}


def free_port() -> int:
    """Свободный порт от системы."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def fetch_url_text(url: str, timeout: float = 3.0) -> str:
    try:
        req = urllib.request.Request(url)
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return ""


# =========================================================================================
#  14. ТОЧКА ВХОДА
# =========================================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    setup_console()
    args = parse_args(argv)
    if args.selftest:
        enable_colors(force=True if args.color else (False if args.no_color else None))
        return run_selftest()

    enable_colors(force=True if args.color else (False if args.no_color else None))
    try:
        return run_diagnostics(args)
    except KeyboardInterrupt:
        print()
        info("Прервано пользователем.")
        return 130
    except Exception as exc:                        # noqa: BLE001 — инструмент, не библиотека
        print()
        bad(f"Внутренняя ошибка инструмента: {type(exc).__name__}: {exc}")
        print(col("Соберите отчёт и покажите его разработчику: "
                  "python net_doctor.py --report netdoctor_error.txt", C.GREY))
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
