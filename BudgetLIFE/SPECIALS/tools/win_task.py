#!/usr/bin/env python3
"""
win_task.py — действия с приложениями как с задачами Windows.

audit_windows.py отвечает на вопрос «что сейчас происходит», а этот скрипт —
«сделай»: остановить, перезапустить, включить/выключить автозапуск, поставить
URI-протокол. Всё — по реестру SPECIALS/ports.json, и всё безопасно: чужой
процесс, занявший порт, НИКОГДА не убивается (только сообщение).

Команды:
    python SPECIALS/tools/win_task.py list                  # что запущено (по портам)
    python SPECIALS/tools/win_task.py port 5120             # кто держит конкретный порт
    python SPECIALS/tools/win_task.py kill specials_demo    # остановить своё приложение
    python SPECIALS/tools/win_task.py restart cooker        # остановить и запустить заново
    python SPECIALS/tools/win_task.py autostart specials_demo on|off [--name "…"]
    python SPECIALS/tools/win_task.py uri tracker on        # зарегистрировать myapp://
    python SPECIALS/tools/win_task.py uri tracker off
    python SPECIALS/tools/win_task.py --json list

Аргументом вместо app_id можно писать порт: `kill 5120`.
Зависимостей нет: работает на стандартной библиотеке, на Windows использует
реестр, на Linux/macOS — то, что доступно (psutil, если установлен).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SPECIALS = Path(__file__).resolve().parents[1]
REPO = SPECIALS.parent
sys.path.insert(0, str(SPECIALS))

from appcore import autostart, ports, processes  # noqa: E402

WINDOWS = os.name == "nt"


# ── реестр блоков и «свои» процессы ─────────────────────────────────────────

def load_blocks() -> list[dict]:
    try:
        raw = json.loads((SPECIALS / "ports.json").read_text(encoding="utf-8"))
        return raw.get("blocks", [])
    except Exception as exc:
        print(f"Не читается ports.json: {exc}")
        return []


def block_by_key(key: str) -> dict | None:
    """Находит блок по app_id или по номеру порта (входит в блок)."""
    for block in load_blocks():
        if block.get("app_id") == key:
            return block
        try:
            base, size = int(block.get("base", 0)), int(block.get("size", 0))
        except (TypeError, ValueError):
            continue
        if key.isdigit() and base <= int(key) < base + size:
            return block
    return None


def app_dir_of(block: dict) -> Path:
    current = str(block.get("current_file", "") or "")
    return (REPO / current).parent if current else REPO


def script_of(block: dict) -> str:
    current = str(block.get("current_file", "") or "")
    return Path(current).name if current else "app.py"


def markers_for(block: dict) -> list[str]:
    """Метки «своего» процесса: имя файла-скрипта и путь к папке проекта."""
    directory = app_dir_of(block)
    return [script_of(block), str(directory).lower(),
            str(directory).replace("\\", "/").lower()]


def process_cwd(pid: int) -> str:
    """Рабочая папка процесса: самый надёжный признак «наш ли это процесс»."""
    try:
        if not WINDOWS:
            return os.readlink(f"/proc/{pid}/cwd")
        import psutil  # noqa: PLC0415
        return psutil.Process(pid).cwd() or ""
    except Exception:
        return ""


def classify(pid: int, cmdline: str, block: dict) -> str:
    """«наше» | «чужое» — по рабочей папке, затем по командной строке."""
    directory = str(app_dir_of(block)).lower()
    cwd = process_cwd(pid)
    if cwd and (str(Path(cwd).resolve()).lower() == directory
                or directory.endswith(str(Path(cwd)).lower())):
        return "наше"
    low = (cmdline or "").lower()
    if directory and (directory in low.replace("\\", "/")
                      or str(app_dir_of(block)).lower() in low):
        return "наше"
    return "чужое"


def block_state(block: dict) -> dict:
    base, size = int(block.get("base", 0)), int(block.get("size", 0))
    state = {"app_id": block.get("app_id"), "name": block.get("name"),
             "base": base, "size": size, "listeners": [], "port_file": None}
    for port in range(base, base + size):
        for pid, cmdline in processes.port_owner_info(port):
            state["listeners"].append({"port": port, "pid": pid,
                                       "cmdline": (cmdline or "")[:200],
                                       "kind": classify(pid, cmdline, block)})
    port_file = ports.read_port_file(app_dir_of(block) / "data")
    if port_file:
        state["port_file"] = port_file
    return state


# ── вывод ───────────────────────────────────────────────────────────────────

def print_state(state: dict) -> None:
    listeners = state["listeners"]
    title = f"{state['name']} [{state['app_id']}] блок {state['base']}-" \
            f"{state['base'] + state['size'] - 1}"
    if not listeners:
        print(f"  —  {title}: не запущено")
    for item in listeners:
        sign = "✓" if item["kind"] == "наше" else "?"
        print(f"  {sign}  {title}: порт {item['port']}, pid {item['pid']} ({item['kind']})")
        if item["cmdline"]:
            print(f"        {item['cmdline']}")
    if state["port_file"]:
        info = state["port_file"]
        alive = info.get("port") in {i["port"] for i in listeners}
        print(f"        data/port.txt: порт {info.get('port')} "
              f"({'жив' if alive else 'УСТАРЕЛ'})")


def command_list(blocks: list[dict], as_json: bool) -> int:
    states = [block_state(block) for block in blocks]
    if as_json:
        print(json.dumps(states, ensure_ascii=False, indent=2))
        return 0
    print("=" * 78)
    print(" ЗАПУЩЕННЫЕ ПРИЛОЖЕНИЯ (по реестру SPECIALS/ports.json)")
    print("=" * 78)
    running = 0
    for state in states:
        if state["listeners"]:
            running += 1
            print_state(state)
        elif state["port_file"]:
            print_state(state)          # покажем устаревший port.txt
    print("-" * 78)
    print(f"Запущено: {running} из {len(states)}. Подробности: audit_windows.py")
    return 0


def command_port(port: int, as_json: bool) -> int:
    owners = processes.port_owner_info(port)
    payload = [{"pid": pid, "cmdline": cmdline} for pid, cmdline in owners]
    if as_json:
        print(json.dumps({"port": port, "owners": payload}, ensure_ascii=False, indent=2))
        return 0
    print(f"Порт {port}: " + ("свободен" if not owners else f"слушателей {len(owners)}"))
    for pid, cmdline in owners:
        print(f"  pid {pid}: {cmdline}")
    return 0


def command_kill(key: str, as_json: bool) -> int:
    block = block_by_key(key)
    if not block:
        print(f"Не знаю такое приложение: {key}. Список: win_task.py list")
        return 2
    base, size = int(block["base"]), int(block["size"])
    killed: list[dict] = []
    for port in range(base, base + size):
        for pid, cmdline in processes.port_owner_info(port):
            if classify(pid, cmdline, block) != "наше":
                print(f"  порт {port}: чужой процесс pid={pid} — НЕ трогаю "
                      f"({(cmdline or '')[:120]})")
                continue
            if processes.kill_pid(pid):
                killed.append({"port": port, "pid": pid})
                print(f"  порт {port}: остановлен pid={pid}")
            else:
                print(f"  порт {port}: не удалось остановить pid={pid}")
    if as_json:
        print(json.dumps(killed, ensure_ascii=False))
    if not killed:
        print(f"{block['name']}: не запущено (или порт занимает чужой процесс).")
    return 0


def command_restart(key: str, as_json: bool) -> int:
    block = block_by_key(key)
    if not block:
        print(f"Не знаю такое приложение: {key}.")
        return 2
    command_kill(key, as_json=False)
    start_vbs = app_dir_of(block) / "start.vbs"
    if not start_vbs.exists():
        print(f"Нет файла {start_vbs} — запустите вручную.")
        return 2
    if WINDOWS:
        os.startfile(str(start_vbs))  # noqa: S606 — VBS-лаунчер, как двойной клик
        print(f"Запущено: {start_vbs}")
    else:
        print(f"На этой ОС start.vbs не запускается. Запустите вручную: {start_vbs}")
    return 0


def command_autostart(key: str, mode: str, name: str | None, as_json: bool) -> int:
    block = block_by_key(key)
    if not block:
        print(f"Не знаю такое приложение: {key}.")
        return 2
    app_dir = app_dir_of(block)
    value_name = name or str(block.get("name") or block.get("app_id"))
    command = autostart.launcher_command(app_dir)
    if mode == "on":
        ok = autostart.set_autostart(value_name, command, True)
    else:
        ok = autostart.set_autostart(value_name, command, False)
    if ok:
        state = "включён" if mode == "on" else "выключен"
    elif not WINDOWS:
        state = "недоступен: это настройка Windows"
    else:
        state = "НЕ удалось (нет прав?)"
    print(f"Автозапуск «{value_name}»: {state}")
    print(f"  команда: {command}")
    if as_json:
        print(json.dumps({"name": value_name, "command": command, "enable": mode == "on",
                          "ok": ok}, ensure_ascii=False))
    return 0 if ok else 1


def command_uri(scheme: str, mode: str, key: str | None, as_json: bool) -> int:
    if mode == "on":
        if not key:
            print("Для регистрации укажите приложение: "
                  "win_task.py uri <схема> on <app_id|порт>")
            return 2
        block = block_by_key(key)
        if not block:
            print(f"Не знаю такое приложение: {key}.")
            return 2
        command = autostart.launcher_command(app_dir_of(block)) + ' "%1"'
        ok = autostart.register_uri_protocol(scheme, command,
                                             display_name=f"URL:{scheme}")
    else:
        ok = autostart.unregister_uri_protocol(scheme)
    if ok:
        state = "зарегистрирована" if mode == "on" else "удалена"
    elif not WINDOWS:
        state = "недоступно: это настройка Windows"
    else:
        state = "не удалось"
    print(f"URI-схема «{scheme}://»: {state}")
    if as_json:
        print(json.dumps({"scheme": scheme, "enable": mode == "on", "ok": ok},
                         ensure_ascii=False))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Действия с приложениями SPECIALS")
    parser.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="что запущено сейчас")
    p_port = sub.add_parser("port", help="кто держит порт")
    p_port.add_argument("port", type=int)
    p_kill = sub.add_parser("kill", help="остановить своё приложение")
    p_kill.add_argument("key", help="app_id или порт")
    p_restart = sub.add_parser("restart", help="остановить и запустить заново")
    p_restart.add_argument("key", help="app_id или порт")
    p_auto = sub.add_parser("autostart", help="включить/выключить автозапуск")
    p_auto.add_argument("key", help="app_id или порт")
    p_auto.add_argument("mode", choices=["on", "off"])
    p_auto.add_argument("--name", default=None, help="имя записи в реестре")
    p_uri = sub.add_parser("uri", help="URI-протокол (myapp://)")
    p_uri.add_argument("scheme")
    p_uri.add_argument("mode", choices=["on", "off"])
    p_uri.add_argument("key", nargs="?", default=None, help="app_id или порт (для on)")
    args = parser.parse_args(argv)

    if args.command in (None, "list"):
        return command_list(load_blocks(), args.json)
    if args.command == "port":
        return command_port(args.port, args.json)
    if args.command == "kill":
        return command_kill(args.key, args.json)
    if args.command == "restart":
        return command_restart(args.key, args.json)
    if args.command == "autostart":
        return command_autostart(args.key, args.mode, args.name, args.json)
    if args.command == "uri":
        return command_uri(args.scheme, args.mode, args.key, args.json)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
