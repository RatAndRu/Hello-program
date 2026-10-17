#!/usr/bin/env python3
"""
check_ports.py — аудит портов по всему репозиторию.

Зачем: приложения писались по отдельности, и один и тот же порт мог достаться
нескольким проектам (в этом репозитории так и есть: 5000 занят трижды,
8080 попадает в динамический диапазон DnD's, PlotMaker сканирует порты 5678+,
которые нужны LanguageYOI).

Скрипт читает код (.py, .vbs, .bat, .ps1, .js), вытаскивает «портовые» числа и
динамические диапазоны, сравнивает их между проектами и с реестром
SPECIALS/ports.json.

Запуск:
    python SPECIALS/tools/check_ports.py                 # по всему репозиторию
    python SPECIALS/tools/check_ports.py --json          # машиночитаемый отчёт
    python SPECIALS/tools/check_ports.py --root path

Код возврата: 0 — конфликтов нет, 1 — найдены пересечения.
Зависимостей нет: Python 3.8+.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

# ── шаблоны «портовых» объявлений ───────────────────────────────────────────
# Формат: (что это, шаблон, какие группы являются портами)
#   "single:N"  — группа N это порт;
#   "list:N"    — группа N это список портов через запятую;
#   "range:N,M" — динамический диапазон: группа N начало, M конец.
PATTERN_SPECS: list[tuple[str, re.Pattern, str]] = [
    # PORT = 5000, WEB_PORT: int = 5002, LOCK_PORT = 18523 (в т.ч. в строке через ";")
    ("константа",
     re.compile(r"\b((?:[A-Za-z0-9]+_)*(?:PORT|PORTS|port|ports)(?:_[A-Za-z0-9]+)*)\s*[:=]\s*(\d{2,5})\b"),
     "single:2"),
    # "port": 5000
    ("настройка", re.compile(r"['\"]port['\"]\s*[:=]\s*(\d{2,5})"), "single:1"),
    # app.run(..., port=5000) / app_flask.run(...) / uvicorn.run / make_server / serve(...)
    ("запуск сервера",
     re.compile(r"\b\w+\.run\s*\([^)]*?\bport\s*=\s*(\d{2,5})"),
     "single:1"),
    # find_free_port(start=8000, end=8100) — динамический диапазон целиком
    ("диапазон сканера",
     re.compile(r"\b(?:find|get|pick)_free_port\s*\(\s*(?:start|start_port)\s*=\s*(\d{3,5})"
                r"[^)]*?end\s*=\s*(\d{3,5})"),
     "range:1,2"),
    # find_free_port(start=8000) / get_free_port(start_port=5678) — только начало
    ("сканер портов",
     re.compile(r"\b(?:find|get|pick)_free_port\s*\(\s*(?:start|start_port)\s*=\s*(\d{3,5})"),
     "single:1"),
    # range(8000, 8100) внутри сканера портов
    ("диапазон (динамический)", re.compile(r"range\(\s*(\d{3,5})\s*,\s*(\d{3,5})\s*\)"),
     "range:1,2"),
    # DASHBOARD_PORTS = (5678, 5681, ...) / PANEL_PORTS = (5679, 5680)
    ("список портов",
     re.compile(r"^\s*\w*PORTS\s*[:=]\s*\(([\d,\s]+)\)", re.MULTILINE),
     "list:1"),
    # python -m http.server 8080
    ("http.server", re.compile(r"-m\s+http\.server\s+(\d{3,5})"), "single:1"),
    # const API = 'http://localhost:5002' / http://127.0.0.1:5100
    ("адрес в коде", re.compile(r"(?:localhost|127\.0\.0\.1):(\d{3,5})"), "single:1"),
]

# Числа, которые «портовым» шаблонам попадаются, но портами не являются:
# коды состояния HTTP, размеры буферов и т.п. 5000 — настоящий порт, его не трогаем.
FALSE_POSITIVES = {0, 1, 100, 200, 500, 800, 1000, 1024, 2048, 3000, 4096}

SCAN_SUFFIXES = {".py", ".vbs", ".bat", ".ps1", ".js"}
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist",
                "_backup", "logs"}
SKIP_FILE_MARKERS = ("check_ports.py", "ports.json", "package-lock.json")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    port: int
    raw: str
    port_end: int | None = None      # для динамических диапазонов

    def __str__(self) -> str:
        span = f"{self.port}-{self.port_end}" if self.port_end else f"{self.port}"
        return f"{self.path}:{self.line}  {span:>12}  ({self.kind}) {self.raw}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    conflicts: dict[int, list[Finding]] = field(default_factory=dict)
    overlaps: list[str] = field(default_factory=list)
    unbounded: list[Finding] = field(default_factory=list)
    registry_conflicts: list[str] = field(default_factory=list)
    scanned_files: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "findings": [f.__dict__ for f in self.findings],
            "conflicts": {str(port): [f.__dict__ for f in items]
                          for port, items in self.conflicts.items()},
            "overlaps": list(self.overlaps),
            "unbounded": [f.__dict__ for f in self.unbounded],
            "registry_conflicts": list(self.registry_conflicts),
        }


# ── чтение файлов ───────────────────────────────────────────────────────────

def python_code_lines(text: str) -> list[str]:
    """Возвращает строки, из которых удалены комментарии и текст docstring.

    Важно именно УДАЛИТЬ куски, а не пропускать строки целиком: `PORT = 5000  #
    комментарий` — обычная строка кода с пояснением, и порт в ней настоящий.
    """
    lines = [line.expandtabs(4) for line in text.splitlines()]

    def blank_piece(line_index: int, start_col: int, end_col: int | None) -> None:
        if not (0 <= line_index < len(lines)):
            return
        line = lines[line_index]
        if end_col is None:
            end_col = len(line)
        if start_col >= len(line):
            return
        lines[line_index] = line[:start_col] + " " * (min(end_col, len(line)) - start_col) + \
            line[min(end_col, len(line)):]

    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                blank_piece(token.start[0] - 1, token.start[1], token.end[1])
    except Exception:
        pass

    try:
        tree = ast.parse(text)
    except Exception:
        return lines
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                start = body[0].lineno
                end = getattr(body[0], "end_lineno", start) or start
                for line_index in range(start - 1, min(end, len(lines))):
                    lines[line_index] = " " * len(lines[line_index])
    return lines


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if any(marker in path.name for marker in SKIP_FILE_MARKERS):
            continue
        yield path


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    relative = str(path.relative_to(root))
    lines = python_code_lines(text) if path.suffix == ".py" else text.splitlines()

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for kind, pattern, spec in PATTERN_SPECS:
            match = pattern.search(line)
            if not match:
                continue
            mode, _, groups = spec.partition(":")
            try:
                if mode == "range":
                    # В spec записаны НОМЕРА ГРУПП, а сами числа берём из совпадения
                    group_a, group_b = (int(part) for part in groups.split(","))
                    first, second = int(match.group(group_a)), int(match.group(group_b))
                    start_port, end_port = sorted((first, second))
                    if 100 <= start_port <= 65535 and end_port > start_port:
                        findings.append(Finding(relative, number, kind, start_port,
                                                stripped[:110], port_end=end_port))
                else:
                    raw_value = match.group(int(groups))
                    values = ([int(part) for part in re.findall(r"\d+", raw_value)]
                              if mode == "list" else [int(raw_value)])
                    for value in values:
                        if 100 <= value <= 65535 and value not in FALSE_POSITIVES:
                            findings.append(Finding(relative, number, kind, value, stripped[:110]))
            except (ValueError, IndexError):
                pass
    # Убираем дубликаты: одну и ту же строку могут поймать разные шаблоны
    unique: dict[tuple[str, int, int, int | None], Finding] = {}
    for item in findings:
        unique[(item.path, item.line, item.port, item.port_end)] = item
    return list(unique.values())


def load_registry(specials_dir: Path) -> dict:
    try:
        return json.loads((specials_dir / "ports.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def block_of(registry: dict, file_path: str) -> dict | None:
    for block in registry.get("blocks", []):
        current = str(block.get("current_file", ""))
        if current and current in file_path:
            return block
    return None


def project_of(path: str) -> str:
    return path.split("/")[0]


# ── анализ ──────────────────────────────────────────────────────────────────

def analyse(root: Path) -> Report:
    report = Report()
    for path in iter_files(root):
        report.scanned_files += 1
        found = scan_file(path, root)
        # Если в строке найден и диапазон, и его начало — оставляем только диапазон.
        spans = {(f.path, f.line) for f in found if f.port_end}
        report.findings.extend(f for f in found
                               if f.port_end or (f.path, f.line) not in spans)

    by_port: dict[int, list[Finding]] = {}
    for finding in report.findings:
        by_port.setdefault(finding.port, []).append(finding)

    # Конфликт 1: один порт в файлах разных проектов
    for port, items in sorted(by_port.items()):
        projects = {project_of(item.path) for item in items}
        if len(projects) > 1:
            report.conflicts[port] = items

    # Отдельно: сканер без верхней границы (get_free_port(start=5001) и т.п.)
    # Теоретически может занять ЛЮБОЙ порт выше старта — так делать нельзя.
    for finding in report.findings:
        if finding.kind != "сканер портов":
            continue
        # Если в строке нет верхней границы (end=, max_attempts=) — сканер
        # теоретически может занять любой свободный порт, включая чужие.
        if not re.search(r"\bend\s*=|\bmax_attempts\s*=", finding.raw):
            report.unbounded.append(finding)

    # Конфликт 2: динамический диапазон одного проекта накрывает порт другого
    for finding in report.findings:
        if not finding.port_end:
            continue
        owner = project_of(finding.path)
        for port, items in sorted(by_port.items()):
            if not (finding.port < port <= finding.port_end):
                continue
            strangers = sorted({project_of(item.path) for item in items
                                if project_of(item.path) != owner and not item.port_end})
            if strangers:
                report.overlaps.append(
                    f"{finding.path}:{finding.line}: динамический диапазон "
                    f"{finding.port}-{finding.port_end} может занять порт {port} "
                    f"(проект: {', '.join(strangers)})")

    specials_dir = root / "SPECIALS" if (root / "SPECIALS").exists() else root
    registry = load_registry(specials_dir)
    for port, items in report.conflicts.items():
        owner = "нет записи в ports.json"
        for item in items:
            block = block_of(registry, item.path)
            if block:
                owner = block.get("app_id", "нет записи в ports.json")
                break
        projects = ", ".join(sorted({project_of(i.path) for i in items}))
        report.registry_conflicts.append(
            f"порт {port}: занят {len(items)} раз (проекты: {projects}); "
            f"владелец по ports.json — {owner}")
    return report


# ── вывод ───────────────────────────────────────────────────────────────────

def print_report(report: Report, root: Path) -> None:
    width = 82
    print("=" * width)
    print(" АУДИТ ПОРТОВ — SPECIALS/tools/check_ports.py")
    print(f" Репозиторий: {root}")
    print(f" Просмотрено файлов: {report.scanned_files}; найдено объявлений: {len(report.findings)}")
    print("=" * width)

    by_port: dict[int, list[Finding]] = {}
    for item in report.findings:
        by_port.setdefault(item.port, []).append(item)
    for port, items in sorted(by_port.items()):
        projects = sorted({project_of(item.path) for item in items})
        marker = "!! КОНФЛИКТ" if port in report.conflicts else "      ок    "
        print(f"\n[{marker}] порт {port} — {len(items)} упом. ({', '.join(projects)})")
        for item in items[:5]:
            print(f"      {item}")
        if len(items) > 5:
            print(f"      … ещё {len(items) - 5}")

    print("\n" + "-" * width)
    if report.unbounded:
        print(f"НЕОГРАНИЧЕННЫЕ СКАНЕРЫ ПОРТОВ (могут занять чужой порт): {len(report.unbounded)}")
        for item in report.unbounded:
            print(f"  ! {item}")
        print()
    if report.overlaps:
        print(f"РИСК ПЕРЕКРЫТИЯ ДИНАМИЧЕСКИХ ДИАПАЗОНОВ: {len(report.overlaps)}")
        for line in report.overlaps:
            print(f"  ~ {line}")
        print()
    if report.conflicts:
        print(f"НАЙДЕНО КОНФЛИКТОВ: {len(report.conflicts)}")
        for line in report.registry_conflicts:
            print(f"  * {line}")
        print()
        print("Что делать (золотой стандарт SPECIALS):")
        print("  1. каждому проекту — свой блок из SPECIALS/ports.json (10 портов);")
        print("  2. порт выбирать через appcore.ports.choose (свой блок + /api/identity);")
        print("  3. динамические сканеры заменить блоком: Cooker 5001+ → 5030-5039,")
        print("     PlotMaker 5678+ → 5700-5719, DnD's 8000-8100 → 8000-8009.")
        print("  Подробности: SPECIALS/docs/PORTS.md")
    else:
        print("Конфликтов портов не найдено: каждый порт принадлежит одному проекту.")
    print("-" * width)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Аудит портов в репозитории проектов")
    parser.add_argument("--root", default=None,
                        help="корень репозитория (по умолчанию — два уровня вверх от скрипта)")
    parser.add_argument("--json", action="store_true", help="отчёт в JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    report = analyse(root)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_report(report, root)
    return 1 if (report.conflicts or report.overlaps or report.unbounded) else 0


if __name__ == "__main__":
    sys.exit(main())
