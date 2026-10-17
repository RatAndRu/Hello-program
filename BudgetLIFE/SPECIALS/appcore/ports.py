"""
ports.py — дисциплина портов: блоки, проверка свободы, опознание «своего» сервера.

ГЛАВНАЯ ИДЕЯ (лечит конфликты, найденные в репозитории)
------------------------------------------------------
1. У каждого проекта есть ЗАРЕЗЕРВИРОВАННЫЙ БЛОК из 10 портов (SPECIALS/ports.json).
   Приложение пробует основной порт, затем остальные порты СВОЕГО блока и
   никогда не заходит на чужой блок.
2. «Порт свободен» проверяется bind-ом на том же адресе, где будет слушать
   сервер (а не connect-ом на 127.0.0.1, как в Cooker/PlotMaker: чужой сервер на
   0.0.0.0 или на другом интерфейсе так можно не заметить).
3. Даже если порт занят — приложение спрашивает `/api/identity`. Если ответило
   НАШЕ приложение (совпал app_id), второй экземпляр не поднимается: он просто
   открывает окно уже работающего. Это приём LanguageYOI (`find_running_server`).
4. Выбранный порт пишется в `data/port.txt` (приём DnD's) — по нему трей,
   VBS-лаунчер и внешние инструменты узнают актуальный адрес.

Почему это важно: в репозитории порт 5000 занят сразу тремя приложениями
(swipe_review, shedevrum_bot, Телепульт), а динамические сканеры Cooker/PlotMaker
могут «уехать» на чужой порт. Подробный разбор — SPECIALS/docs/PORTS.md.
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import netutil, processes

# ── блоки по умолчанию (если ports.json недоступен) ─────────────────────────
# Копия SPECIALS/ports.json в виде кода: приложение не должно зависеть от файла.
DEFAULT_BLOCKS: dict[str, tuple[int, int]] = {
    # app_id            (основной порт, размер блока)
    "specials_demo":    (5120, 10),
    "swipe_review":     (5000, 10),
    "shedevrum_bot":    (5010, 10),
    "bridge":           (5020, 10),
    "cooker":           (5030, 10),
    "blind_pc":         (5040, 10),
    "tracker":          (5100, 10),
    "telepult":         (5110, 10),
    "languageyoi_dict": (5660, 20),
    "languageyoi_ocr":  (5680, 20),
    "plotmaker":        (5700, 20),
    "rpg_table":        (8000, 10),
    "shadow_game":      (8010, 10),
}

REGISTRY_FILENAME = "ports.json"
LOCK_PORT_RANGE = (18900, 18999)   # служебные порты-локи (DeployAgent: 18523)


@dataclass(frozen=True)
class PortBlock:
    app_id: str
    base: int
    size: int = 10
    note: str = ""

    @property
    def ports(self) -> list[int]:
        return list(range(self.base, self.base + self.size))


@dataclass
class PortChoice:
    """Результат выбора порта."""
    port: int
    host: str
    existing: bool = False              # на порту уже работает НАШ экземпляр
    identity: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return netutil.url_for(self.host, self.port)


# ── реестр блоков ───────────────────────────────────────────────────────────

def load_blocks(registry_path: str | Path | None = None) -> dict[str, tuple[int, int]]:
    """Читает блоки из SPECIALS/ports.json; при любой проблеме — встроенные."""
    blocks = dict(DEFAULT_BLOCKS)
    candidates: list[Path] = []
    if registry_path:
        candidates.append(Path(registry_path))
    # ищем ports.json рядом с пакетом appcore (в проекте — свой,
    # в репозитории — SPECIALS/ports.json)
    package_parent = Path(__file__).resolve().parent.parent
    candidates.append(package_parent / REGISTRY_FILENAME)
    candidates.append(package_parent / "SPECIALS" / REGISTRY_FILENAME)
    for parent in list(package_parent.parents)[:3]:     # …и выше по дереву
        candidates.append(parent / REGISTRY_FILENAME)
        candidates.append(parent / "SPECIALS" / REGISTRY_FILENAME)
    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            for item in raw.get("blocks", []):
                app_id = str(item.get("app_id", "")).strip()
                base = int(item.get("base", 0))
                size = int(item.get("size", 10))
                if app_id and 1 <= base <= 65535 and 1 <= size <= 200:
                    blocks[app_id] = (base, size)
            break
        except Exception:
            continue
    return blocks


def block_for(app_id: str, registry_path: str | Path | None = None) -> PortBlock:
    """Блок портов приложения. Незнакомый app_id получает блок 5200+ по хэшу.

    Хэш нужен, чтобы новый проект без регистрации всё равно получал
    СТАБИЛЬНЫЙ порт (одинаковый между запусками) и не пересекался с другими.
    """
    blocks = load_blocks(registry_path)
    if app_id in blocks:
        base, size = blocks[app_id]
        return PortBlock(app_id, base, size)
    # свободная зона 5200–5599, 40 блоков по 10
    import zlib
    slot = zlib.crc32(app_id.encode("utf-8")) % 40
    return PortBlock(app_id, 5200 + slot * 10, 10, note="авто-блок по хэшу app_id")


def candidates(app_id: str, *, prefer: int | None = None,
               registry_path: str | Path | None = None) -> list[int]:
    """Порядок проверки портов: основной → остальные из своего блока."""
    block = block_for(app_id, registry_path)
    primary = int(prefer) if prefer else block.base
    if primary not in block.ports:
        primary = block.base
    ordered = [primary] + [p for p in block.ports if p != primary]
    return ordered


# ── проверка свободы порта ──────────────────────────────────────────────────

def port_is_free(host: str, port: int, *, exclusive: bool = True) -> bool:
    """Проверка bind-ом: похоже на реальный запуск сервера.

    `exclusive=True` использует SO_EXCLUSIVEADDRUSE (Windows): если порт держит
    хоть кто-то, bind не пройдёт. С SO_REUSEADDR на Windows можно «сесть» поверх
    чужого сокета — именно поэтому порт-лок DeployAgent с SO_REUSEADDR может
    дать ложное «свободно».
    """
    family = socket.AF_INET6 if ":" in str(host) else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            if exclusive:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_host = host or "0.0.0.0"
        sock.bind((bind_host, int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def find_free_port(host: str, ports: Iterable[int], *, logger=None) -> int | None:
    """Первый свободный порт из списка (в пределах блока!)."""
    for port in ports:
        if port_is_free(host, port):
            return int(port)
        if logger:
            logger.debug("Порт %s занят, пробую следующий", port)
    return None


# ── опознание приложения на порту ───────────────────────────────────────────

API_IDENTITY = "/api/identity"


def identity_payload(app_id: str, app_name: str, version: str, port: int = 0,
                     extra: dict | None = None) -> dict:
    """Ответ /api/identity. По нему второй запуск понимает: «это я или чужой?»"""
    payload = {
        "app_id": app_id,
        "app": app_name,
        "version": version,
        "pid": os.getpid(),
        "port": int(port),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": os.environ.get("COMPUTERNAME") or socket.gethostname(),
    }
    if extra:
        payload.update(extra)
    return payload


def check_identity(host: str, port: int, app_id: str,
                   timeout: float = 1.5) -> dict | None:
    """Возвращает payload /api/identity, если на порту именно НАШ app_id."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    payload = netutil.http_get_json(
        netutil.url_for(probe_host, port, API_IDENTITY), timeout=timeout)
    if payload and str(payload.get("app_id")) == str(app_id):
        return payload
    return None


def find_running(app_id: str, host: str, ports: Iterable[int], *,
                 timeout: float = 0.8) -> PortChoice | None:
    """Ищет уже работающий экземпляр НАШЕГО приложения в своём блоке портов."""
    for port in ports:
        payload = check_identity(host, port, app_id, timeout=timeout)
        if payload:
            return PortChoice(port=int(port), host=host, existing=True, identity=payload)
    return None


def choose(app_id: str, host: str, *, prefer: int | None = None,
           reuse_running: bool = True, logger=None,
           registry_path: str | Path | None = None,
           port_file: str | Path | None = None) -> PortChoice | None:
    """Полный сценарий выбора порта.

    1) если приложение уже запущено в своём блоке — вернём его порт (existing=True);
    2) иначе ищем свободный порт в блоке (см. шаг 1);
    3) результат сразу пишем в data/port.txt для трея/ярлыков.
    """
    ports = candidates(app_id, prefer=prefer, registry_path=registry_path)
    if reuse_running:
        running = find_running(app_id, host, ports)
        if running:
            if logger:
                logger.info("Уже запущено: %s на порту %s (pid=%s) — переиспользую",
                            app_id, running.port, running.identity.get("pid"))
            write_port_file(port_file, running.port, app_id, running.identity.get("pid"))
            return running
    port = find_free_port(host, ports, logger=logger)
    if port is None:
        if logger:
            logger.error("В блоке %s нет свободных портов: %s", app_id, ports)
        return None
    write_port_file(port_file, port, app_id)
    return PortChoice(port=port, host=host)


# ── файл порта (для трея, лаунчера, ярлыков) ────────────────────────────────

def port_file_path(data_dir: str | Path | None) -> Path | None:
    return Path(data_dir) / "port.txt" if data_dir else None


def write_port_file(data_dir: str | Path | None, port: int, app_id: str,
                    pid: int | None = None) -> None:
    """Пишет data/port.txt в формате JSON + совместимость с «просто числом».

    DnD's читал из файла одно число (`int(f.read())`), поэтому формат такой:
    первая строка — ЧИСЛО (старые потребители работают), ниже — JSON-детали.
    """
    path = port_file_path(data_dir)
    if path is None:
        return
    try:
        from .jsonstore import atomic_write_text
        payload = {"port": int(port), "app_id": app_id, "pid": int(pid or os.getpid()),
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        atomic_write_text(path, f"{int(port)}\n{json.dumps(payload, ensure_ascii=False)}\n")
    except Exception:
        pass


def read_port_file(data_dir: str | Path | None) -> dict | None:
    """Читает data/port.txt. Понимает и «число», и JSON-формат."""
    path = port_file_path(data_dir)
    if path is None:
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0])
    except ValueError:
        return None
    info: dict[str, Any] = {"port": port}
    if len(lines) > 1:
        try:
            extra = json.loads(lines[1])
            if isinstance(extra, dict):
                info.update(extra)
        except json.JSONDecodeError:
            pass
    if not processes.pid_alive(int(info.get("pid") or 0)):
        info["stale"] = True
    return info


def wait_until_ready(app_id: str, host: str, ports: Iterable[int], *,
                     timeout: float = 15.0, logger=None,
                     data_dir: str | Path | None = None) -> int | None:
    """Ждёт, пока НАШ /api/identity ответит, и возвращает порт.

    Приём LanguageYOI (`wait_for_web_server`): браузер открывается только тогда,
    когда сервер реально поднялся, и на ПРАВИЛЬНОМ порту. Никаких «мёртвых» вкладок
    на 5678, когда сервер на 5681.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    ports = list(ports)
    while True:
        for port in ports:
            payload = check_identity(host, port, app_id, timeout=0.6)
            if payload:
                write_port_file(data_dir, port, app_id, payload.get("pid"))
                return int(port)
        if time.monotonic() >= deadline:
            if logger:
                logger.warning("Сервер %s не поднялся за %.1f с (порты %s)", app_id, timeout, ports)
            return None
        time.sleep(0.35)
