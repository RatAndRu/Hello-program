"""
netutil.py — сеть и адреса: локальный IP, HTTP-проверки, QR для телефона.

Взято из BLIND_PC (get_local_ip + QR), DnD's (QR страницы игрока),
swipe_review (QR в SVG без бинарных зависимостей).

Важный принцип: приложение НИКОГДА не падает из-за отсутствия сети.
Локальный сервер работает и без интернета — все функции ниже возвращают
значение по умолчанию вместо исключения.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Any

DEFAULT_TIMEOUT = 2.0
_UA = "appcore/1.0 (+local-pwa)"


# ── адреса ──────────────────────────────────────────────────────────────────

def local_ip() -> str:
    """IP в локальной сети (для адреса с телефона). 127.0.0.1, если сети нет.

    Трюк с UDP-сокетом: пакет никуда не отправляется, но ОС выбирает
    исходящий интерфейс — так мы узнаём адрес Wi-Fi/Ethernet без интернета.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def is_loopback(host: str) -> bool:
    return str(host).strip().lower() in {"127.0.0.1", "localhost", "::1"}


def url_for(host: str, port: int, path: str = "/") -> str:
    """Собирает URL, корректно склеивая слэши (path может быть "" или "/x").

    Адрес прослушивания 0.0.0.0 — это «все интерфейсы», а не адрес для браузера,
    поэтому в ссылке показываем localhost (иначе пользователь видит 0.0.0.0:5120).
    """
    if not str(path).startswith("/"):
        path = "/" + str(path or "")
    host = str(host or "")
    shown = "localhost" if is_loopback(host) or host in ("0.0.0.0", "::", "") else host
    return f"http://{shown}:{int(port)}{path}"


def lan_url(port: int, path: str = "/", host: str | None = None) -> str:
    return url_for(host or local_ip(), port, path)


# ── HTTP ────────────────────────────────────────────────────────────────────

def http_get_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """GET → dict. None при любой ошибке (таймаут, 404, мусор в ответе)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            payload = json.loads(resp.read(65536).decode("utf-8", "replace"))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def http_ok(url: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Отвечает ли сервер хоть как-то (для «браузер откроем, когда уже живой»)."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except urllib.error.HTTPError as exc:
        # 4xx — сервер ЖИВ, просто маршрут другой. 5xx — тоже живой процесс.
        return exc.code < 600
    except Exception:
        return False


def wait_http(url: str, timeout: float = 15.0, interval: float = 0.3) -> bool:
    """Ждёт, пока URL начнёт отвечать. Нужно, чтобы не открыть «мёртвую» вкладку."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if http_ok(url, timeout=min(1.5, max(0.3, timeout))):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


# ── QR-код ──────────────────────────────────────────────────────────────────

def has_qr() -> bool:
    """QR доступен всегда: пакет qrcode или встроенный appcore.qr."""
    return True


def qr_png_bytes(url: str, box_size: int = 10, border: int = 2) -> bytes | None:
    """PNG с QR-кодом. Сначала пробуем пакет qrcode, потом — свой кодировщик.

    Пакет ``qrcode`` удобнее (умеет сжимать числа/латиницу), но он опционален.
    Если его нет, работает ``appcore.qr``: чистый Python + zlib, без Pillow.
    Так QR появляется всегда — раньше без пакета приходил отказ 501.
    """
    try:
        import io
        import qrcode
        img = qrcode.make(url, box_size=box_size, border=border)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass
    try:                                        # свой кодировщик: без зависимостей
        from . import qr as _qr
        return _qr.png_bytes(url, ecc="M", box=box_size, border=border)
    except Exception:
        return None


def qr_svg_text(url: str, box_size: int = 10, border: int = 2) -> str | None:
    """QR как SVG-текст (без Pillow). Пакет qrcode, иначе — свой кодировщик."""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage,
                          box_size=box_size, border=border)
        import io
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        pass
    try:
        from . import qr as _qr
        return _qr.svg(url, ecc="M", box=box_size, border=border)
    except Exception:
        return None


def save_qr(url: str, path, *, prefer_png: bool = True) -> str | None:
    """Сохраняет QR рядом с приложением и возвращает путь (или None)."""
    from pathlib import Path
    path = Path(path)
    if prefer_png:
        data = qr_png_bytes(url)
        if data:
            path = path.with_suffix(".png")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return str(path)
            except OSError:
                pass
    svg = qr_svg_text(url)
    if svg:
        path = path.with_suffix(".svg")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding="utf-8")
            return str(path)
        except OSError:
            pass
    return None


# ── прочее ──────────────────────────────────────────────────────────────────

def open_url(url: str) -> bool:
    """Открывает браузер, не роняя приложение (в т.ч. под pythonw)."""
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def copy_to_clipboard(text: str) -> bool:
    """Копирует в буфер обмена: pyperclip → PowerShell/ clip → tkinter."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    try:
        import subprocess
        proc = subprocess.run(["clip"], input=str(text), text=True, shell=True,
                              capture_output=True, timeout=5)
        if proc.returncode == 0:
            return True
    except Exception:
        pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def fetch_dict(url: str, payload: dict, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """POST JSON → dict|None (для внутренних вызовов API из трея)."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(65536).decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {"ok": True}
    except Exception:
        return None


def payload_summary(payload: Any) -> str:
    """Короткое человекочитаемое представление JSON (для меню трея/логов)."""
    if not isinstance(payload, dict):
        return str(payload)[:120]
    return ", ".join(f"{k}={v}" for k, v in list(payload.items())[:6])
