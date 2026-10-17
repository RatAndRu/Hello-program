#!/usr/bin/env python3
"""
check_deps.py — какие библиотеки нужны каждому проекту и что из них не установлено.

Зачем: в этом репозитории установка зависимостей — самая частая причина «а у меня
не работает»: модуль есть, но не в том Python; в requirements.txt проект забыли;
в коде импорт лежит в try/except, и его отсутствие надо отличать от обязательного.

Что делает:
  1. разбирает импорты всех .py-файлов проекта (через ast; при синтаксической
     ошибке — грубым regex, чтобы файл всё равно попал в отчёт);
  2. отделяет стандартную библиотеку, локальные модули проекта и импорты внутри
     try/except (необязательные);
  3. сравнивает найденное с requirements.txt и с установленным в текущем Python;
  4. печатает «чего не хватает», «что лишнее» и готовую команду pip install.

Запуск:
    python SPECIALS/tools/check_deps.py                 # все проекты
    python SPECIALS/tools/check_deps.py --root Cooker   # один проект
    python SPECIALS/tools/check_deps.py --json
    python SPECIALS/tools/check_deps.py --pip            # готовая команда установки

Код возврата: 0 — обязательные зависимости на месте, 1 — чего-то не хватает.
Зависимостей нет: сам скрипт работает на стандартной библиотеке.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Импорт (import PIL) → имя пакета для pip.
PIP_NAMES = {
    "pil": "pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "pypdf2": "PyPDF2",
    "win32com": "pywin32",
    "win32gui": "pywin32",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "pythoncom": "pywin32",
    "manga_ocr": "manga-ocr",
    "speech_recognition": "SpeechRecognition",
    "deep_translator": "deep-translator",
    "pynput": "pynput",
    "qrcode": "qrcode[pil]",   # не обязателен: без него работает appcore.qr
    "werkzeug": "flask",          # всегда приезжает вместе с flask
    "jinja2": "flask",
    "itsdangerous": "flask",
    "click": "flask",
    "blinker": "flask",
    "markupsafe": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "aiosqlite": "aiosqlite",
    "multipart": "python-multipart",
}

# Модули, которые «выглядят» внешними, но являются стандартной библиотекой
# (в старых версиях Python их может не быть в sys.stdlib_module_names).
EXTRA_STDLIB = {"__future__", "typing_extensions"}

LOCAL_SUFFIXES = (".py", ".pyw", ".pyd", ".so", ".dll")


@dataclass
class Imports:
    required: set[str] = field(default_factory=set)
    optional: set[str] = field(default_factory=set)


@dataclass
class ProjectReport:
    name: str
    path: str
    required: set[str] = field(default_factory=set)
    optional: set[str] = field(default_factory=set)
    declared: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)      # есть в коде, нет в requirements
    not_installed: set[str] = field(default_factory=set)
    undeclared_optional: set[str] = field(default_factory=set)
    unused: set[str] = field(default_factory=set)        # есть в requirements, нет в коде
    local: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "project": self.name,
            "path": self.path,
            "required": sorted(self.required),
            "optional": sorted(self.optional),
            "declared": sorted(self.declared),
            "missing_in_requirements": sorted(self.missing),
            "not_installed": sorted(self.not_installed),
            "optional_not_declared": sorted(self.undeclared_optional),
            "unused_in_requirements": sorted(self.unused),
        }


def stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()))
    names |= EXTRA_STDLIB
    return names


def module_base(name: str) -> str:
    return name.split(".")[0]


def collect_imports(path: Path) -> Imports:
    text = path.read_text(encoding="utf-8", errors="replace")
    result = Imports()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        for match in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", text, re.M):
            name = module_base(match.group(1))
            if name not in ("__future__",):
                result.required.add(name)
        return result

    def visit_body(body: list[ast.stmt], optional: bool) -> None:
        for node in body:
            target = result.optional if optional else result.required
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target.add(module_base(alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    target.add(module_base(node.module))
            elif isinstance(node, ast.Try):
                visit_body(node.body, True)          # импорт в try — необязательный
                for handler in node.handlers:
                    visit_body(handler.body, optional)
                visit_body(node.orelse, optional)
                visit_body(node.finalbody, optional)
            elif isinstance(node, (ast.If, ast.While, ast.For, ast.With)):
                visit_body(node.body, optional)
                visit_body(list(getattr(node, "orelse", [])), optional)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit_body(node.body, optional)
            else:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom, ast.Try)):
                        visit_body([child], optional)

    visit_body(tree.body, False)
    return result


def local_modules(project: Path) -> set[str]:
    names: set[str] = set()
    for item in project.iterdir():
        if item.is_file() and item.suffix == ".py":
            names.add(item.stem)
        elif item.is_dir() and item.name.isidentifier():
            if (item / "__init__.py").exists():
                names.add(item.name)
    return names


def parse_requirements(project: Path) -> set[str]:
    declared: set[str] = set()
    for req_file in sorted(project.rglob("requirements*.txt")):
        if any(part in ("node_modules", "__pycache__", ".venv", "venv", "build", "dist")
               for part in req_file.parts):
            continue
        for raw in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = re.split(r"[<>=!\[; ]", line, maxsplit=1)[0].strip().lower()
            if name:
                declared.add(name)
    return declared


def pip_name(module: str) -> str:
    """import PIL → pip-пакет pillow; незнакомые имена — как есть."""
    base = module_base(module).lower()
    return PIP_NAMES.get(base, base)


def pip_base(name: str) -> str:
    """Имя пакета без extras: qrcode[pil] → qrcode (для сравнения с requirements)."""
    return name.split("[", 1)[0].strip().lower()


def is_installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def project_dirs(root: Path) -> list[Path]:
    result = []
    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name in (".git", "SPECIALS", "node_modules", "__pycache__"):
            continue
        if any(item.rglob("*.py")):
            result.append(item)
    return result


def analyse_project(project: Path) -> ProjectReport:
    report = ProjectReport(name=project.name, path=str(project))
    report.local = local_modules(project)
    required: set[str] = set()
    optional: set[str] = set()
    for path in project.rglob("*.py"):
        if any(part in ("__pycache__", "node_modules", "build", "dist") for part in path.parts):
            continue
        found = collect_imports(path)
        required |= found.required
        optional |= found.optional
    skip = report.local | stdlib_names() | {"appcore", "shared", "config", "prompt_templates"}
    report.required = {m for m in required if m not in skip and not m.startswith("_")}
    report.optional = {m for m in optional if m not in skip and not m.startswith("_")} - report.required
    report.declared = parse_requirements(project)
    declared_pip = {pip_base(name) for name in report.declared}

    report.missing = {pip_name(m) for m in report.required
                      if pip_base(pip_name(m)) not in declared_pip}
    report.undeclared_optional = {pip_name(m) for m in report.optional
                                  if pip_base(pip_name(m)) not in declared_pip}
    used_pip = {pip_base(pip_name(m)) for m in report.required | report.optional}
    report.unused = {name for name in report.declared if pip_base(name) not in used_pip}
    report.not_installed = {pip_name(m) for m in report.required if not is_installed(m)}
    return report


def print_report(reports: list[ProjectReport]) -> tuple[int, int]:
    ok = projects_with_problems = 0
    for report in reports:
        print(f"\n■ {report.name}  ({report.path})")
        if report.required:
            print(f"  обязательные: {', '.join(sorted(report.required))}")
        if report.optional:
            print(f"  опциональные: {', '.join(sorted(report.optional))}")
        if report.declared:
            print(f"  в requirements: {', '.join(sorted(report.declared))}")
        report_has_problem = False
        if report.missing:
            report_has_problem = True
            if report.declared:
                print(f"  ! нет в requirements.txt: {', '.join(sorted(report.missing))}")
                print(f"    добавьте строки: {' '.join(sorted(report.missing))}")
            else:
                print(f"  ! файла requirements.txt нет — в коде используются: "
                      f"{', '.join(sorted(report.missing))}")
                print(f"    создайте requirements.txt со строками: {' '.join(sorted(report.missing))}")
        if report.not_installed:
            report_has_problem = True
            print(f"  ! не установлено в текущем Python: {', '.join(sorted(report.not_installed))}")
            print(f"    установить: pip install {' '.join(sorted(report.not_installed))}")
        if report.undeclared_optional:
            print(f"  ~ опциональные, не указанные в requirements: "
                  f"{', '.join(sorted(report.undeclared_optional))}")
        if report.unused:
            print(f"  ~ в requirements, но в коде не найдены: {', '.join(sorted(report.unused))}")
        if report_has_problem or report.undeclared_optional or report.unused:
            projects_with_problems += 1
        else:
            ok += 1
            print("  всё сходится")
    return ok, projects_with_problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Аудит зависимостей проектов")
    parser.add_argument("--root", default=None, help="корень репозитория или один проект")
    parser.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    parser.add_argument("--pip", action="store_true",
                        help="показать общую команду установки отсутствующего")
    args = parser.parse_args(argv)

    default_root = Path(__file__).resolve().parents[2]
    root = Path(args.root).resolve() if args.root else default_root
    if not root.exists():
        print(f"Папка не найдена: {root}")
        return 2
    projects = [root] if (root / "requirements.txt").exists() or list(root.glob("*.py")) \
        else project_dirs(root)
    reports = [analyse_project(project) for project in projects]

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
    else:
        print("=" * 78)
        print(" АУДИТ ЗАВИСИМОСТЕЙ — SPECIALS/tools/check_deps.py")
        print(f" Python: {sys.version.split()[0]} ({sys.executable})")
        print("=" * 78)
        ok, problems = print_report(reports)
        print("\n" + "=" * 78)
        print(f"ИТОГ: проектов {len(reports)}; без замечаний {ok}; с замечаниями {problems}")
        if args.pip:
            needed = sorted({name for r in reports for name in r.not_installed})
            if needed:
                print(f"Общая команда: python -m pip install {' '.join(needed)}")
        print("=" * 78)
    return 1 if any(r.missing or r.not_installed for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
