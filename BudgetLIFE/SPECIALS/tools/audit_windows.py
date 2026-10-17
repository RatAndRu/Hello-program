#!/usr/bin/env python3
"""
audit_windows.py — «что сейчас происходит на компьютере»: порты, процессы, автозапуск.

Зачем: приложения запускаются одновременно (трей + автозагрузка + ярлыки), и надо
быстро понять:
  * какой порт реально слушает каждое приложение и НЕ чужое ли оно;
  * нет ли двух экземпляров одного проекта и «зомби», держащих порт;
  * какие записи автозапуска остались от проектов (и нет ли дублей);
  * не устарел ли data/port.txt (порт есть, а приложения нет).

Запуск (Windows):
    python SPECIALS/tools/audit_windows.py
    python SPECIALS/tools/audit_windows.py --json
На Linux/macOS тоже запускается — покажет, что доступно, остальное пропустит.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

SPECIALS = Path(__file__).resolve().parents[1]
REPO = SPECIALS.parent
sys.path.insert(0, str(SPECIALS))

from appcore import autostart, ports, processes  # noqa: E402

WINDOWS = os.name == "nt"


# ── порты приложений ────────────────────────────────────────────────────────

def load_blocks() -> list[dict]:
    try:
        raw = json.loads((SPECIALS / "ports.json").read_text(encoding="utf-8"))
        blocks = raw.get("blocks", [])
        return sorted(blocks, key=lambda b: int(b.get("base", 0)))
    except Exception:
        return []


def probe_block(block: dict) -> dict:
    """Что на портах блока: свободно / наше приложение / чужой процесс."""
    app_id = str(block.get("app_id", ""))
    base = int(block.get("base", 0))
    size = int(block.get("size", 10))
    result = {"app_id": app_id, "name": block.get("name", app_id), "base": base,
              "ports": []}
    for port in range(base, base + size):
        entry: dict = {"port": port}
        identity = ports.check_identity("127.0.0.1", port, app_id, timeout=0.4)
        if identity:
            entry.update(state="наше", pid=identity.get("pid"), version=identity.get("version"))
        else:
            listeners = processes.port_owner_info(port)
            if listeners:
                entry.update(state="чужой", owners=[{"pid": pid, "cmd": cmd[:120]}
                                                    for pid, cmd in listeners])
            else:
                entry["state"] = "свободно"
        result["ports"].append(entry)
        if entry["state"] == "наше":
            break       # основной порт найден — остальные не интересны
    return result


# ── автозапуск ──────────────────────────────────────────────────────────────

def autostart_report(blocks: list[dict]) -> dict:
    entries = autostart.list_autostart_entries()
    known_names = {str(block.get("name", "")) for block in blocks}
    known_names |= {"DeployAgent", "RecipeBox", "BlindPC", "Tracker", "LanguageYOI",
                    "LanguageYOI_OCR", "Bridge", "SwipeReview", "ShedevrumBot", "Telepult"}
    ours = [(name, value) for name, value in entries
            if any(token.lower() in name.lower() or token.lower() in value.lower()
                   for token in known_names if token)]
    duplicates: list[str] = []
    seen: dict[str, str] = {}
    for name, value in ours:
        key = value.strip().lower()
        if key in seen:
            duplicates.append(f"{seen[key]} и {name} — одна и та же команда автозапуска")
        else:
            seen[key] = name
    return {"total_in_run": len(entries), "ours": ours, "duplicates": duplicates}


# ── data/port.txt по проектам ───────────────────────────────────────────────

def port_files_report() -> list[dict]:
    report = []
    for path in sorted(REPO.glob("*/data/port.txt")) + sorted(REPO.glob("*/*/data/port.txt")):
        info = ports.read_port_file(path.parent)
        if not info:
            continue
        report.append({"file": str(path.relative_to(REPO)), "port": info.get("port"),
                       "pid": info.get("pid"), "app_id": info.get("app_id"),
                       "stale": bool(info.get("stale")),
                       "alive": processes.pid_alive(int(info.get("pid") or 0))})
    return report


# ── вывод ───────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Аудит запущенных приложений (Windows)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    blocks = load_blocks()
    data = {
        "os": sys.platform,
        "blocks": [probe_block(block) for block in blocks],
        "autostart": autostart_report(blocks),
        "port_files": port_files_report(),
        "local_ip": None,
    }
    try:
        from appcore import netutil
        data["local_ip"] = netutil.local_ip()
    except Exception:
        pass

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print(" АУДИТ ЗАПУЩЕННЫХ ПРИЛОЖЕНИЙ")
    print(f" ОС: {sys.platform} | локальный IP: {data['local_ip']}")
    print("=" * 78)

    print("\nПОРТЫ ПО БЛОКАМ (SPECIALS/ports.json)")
    for block in data["blocks"]:
        ports = block["ports"]
        main = ports[0]                       # первый порт блока — основной
        state = main["state"]
        mark = {"наше": "  ✓ наше  ", "чужой": "  !! чужой", "свободно": "  · свободно"}[state]
        line = f"[{mark}] {block['base']:>5}-{block['base'] + len(ports) - 1:<5} " \
               f"{block['name']:<28} порт {main['port']:<5}"
        if state == "наше":
            line += f" pid={main.get('pid')} v{main.get('version')}"
        elif state == "чужой":
            owners = ", ".join(f"pid={o['pid']} {o['cmd'][:60]}" for o in main.get("owners", []))
            line += f" {owners}"
        elif len(ports) > 1:
            # свободны ли остальные порты блока (важно: диапазон может быть занят)
            taken = [entry for entry in ports[1:] if entry["state"] != "свободно"]
            if taken:
                line += " (в блоке занято: " + ", ".join(str(e["port"]) for e in taken) + ")"
        print(line)

    auto = data["autostart"]
    print(f"\nАВТОЗАПУСК (HKCU\\...\\Run): всего записей {auto['total_in_run']}")
    if not WINDOWS:
        print("  (реестр Windows недоступен — проверка только в Windows)")
    for name, value in auto["ours"]:
        print(f"  * {name} = {value[:100]}")
    for line in auto["duplicates"]:
        print(f"  ! дубль: {line}")
    if WINDOWS and not auto["ours"]:
        print("  (наших записей нет)")

    print("\ndata/port.txt (адрес, по которому приложение ждёт браузер)")
    if not data["port_files"]:
        print("  (файлов нет — приложения ещё не запускались по стандарту SPECIALS)")
    for item in data["port_files"]:
        state = "УСТАРЕЛ" if item["stale"] else "ок"
        print(f"  {item['file']:<44} порт {item['port']:<6} pid={item['pid']} [{state}]")

    print("\nРЕКОМЕНДАЦИИ")
    ours_states = [e["state"] for b in data["blocks"] for e in b["ports"]]
    if ours_states.count("чужой"):
        print("  * Есть порты, занятые чужими процессами: приложения из SPECIALS")
        print("    автоматически возьмут следующий порт своего блока (проверьте трей).")
    if auto["duplicates"]:
        print("  * В автозапуске есть дубли — отключите лишние (трей → «Автозапуск»).")
    if any(item["stale"] for item in data["port_files"]):
        print("  * Есть устаревшие data/port.txt: приложение закрылось, не удалив файл.")
        print("    В стандарте файл перезаписывается при старте, а pid проверяется по факту.")
    if not any(state == "наше" for state in ours_states):
        print("  * Ни одно приложение из реестра сейчас не запущено.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
