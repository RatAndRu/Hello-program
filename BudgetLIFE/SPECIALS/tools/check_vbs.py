#!/usr/bin/env python3
"""
check_vbs.py — статическая проверка VBS-скриптов репозитория.

VBScript «молчит» о половине ошибок до самого запуска (нет компилятора), а окно
ошибки появляется у пользователя, а не у разработчика. Этот скрипт ловит самые
частые причины отказа прямо из исходника:

  * непарные кавычки в логической строке (продолжения через « _» склеиваются);
  * Duplicate Dim в одной процедуре (в VBScript это ошибка компиляции);
  * незакрытые блоки: If/End If, For/Next, Do/Loop, While/Wend,
    Select Case/End Select, Sub|Function/End Sub|Function;
  * запуск `python.exe` вместо `pythonw.exe` (появится чёрное окно консоли);
  * жёсткие абсолютные пути (C:\\..., D:/...) — проект нельзя перенести;
  * отсутствие `Option Explicit` (опечатка в имени станет пустой переменной).

Это не полноценный парсер (его для VBScript не существует), но перечисленные
ошибки — ровно те, из-за которых скрипты в этом репозитории уже «не работали».

Запуск:
    python SPECIALS/tools/check_vbs.py            # весь репозиторий
    python SPECIALS/tools/check_vbs.py --root Трекер
    python SPECIALS/tools/check_vbs.py --json

Код возврата: 0 — замечаний нет, 1 — есть (только по «жёстким» ошибкам:
кавычки, Dim, блоки; стилевые советы не влияют на код возврата).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist", "logs"}

# Стилевые подсказки (не влияют на код возврата)
RE_PYTHON_EXE = re.compile(r'["\']python\.exe["\']', re.I)
# Списки типовых путей установки интерпретатора — это НЕ «жёсткий путь проекта»:
# проект от них не зависит (они нужны, чтобы вообще найти чем запускать).
RE_INTERPRETER_PATH = re.compile(r"(?:pythonw?|node|deno|bun)\.exe['\"]?\s*$", re.I)
RE_ABS_PATH = re.compile(r'(?<![\w])(?:[A-Za-z]:[\\/]|%SystemDrive%)')
RE_FUNC_START = re.compile(r"^\s*(?:Public |Private )?(?:Sub|Function)\s+(\w+)", re.I)
RE_FUNC_END = re.compile(r"^\s*End\s+(?:Sub|Function)\s*$", re.I)
RE_DIM = re.compile(r"^\s*Dim\s+(.+)$", re.I)
RE_BLOCK_OPEN = [
    ("If", re.compile(r"^\s*If\b.*\bThen\s*(?:'.*)?$", re.I), re.compile(r"^\s*End\s+If\b", re.I)),
    ("For", re.compile(r"^\s*For\b", re.I), re.compile(r"^\s*Next\b", re.I)),
    ("Do", re.compile(r"^\s*Do\b", re.I), re.compile(r"^\s*Loop\b", re.I)),
    ("While", re.compile(r"^\s*While\b", re.I), re.compile(r"^\s*Wend\b", re.I)),
    ("Select Case", re.compile(r"^\s*Select\s+Case\b", re.I), re.compile(r"^\s*End\s+Select\b", re.I)),
    ("With", re.compile(r"^\s*With\b", re.I), re.compile(r"^\s*End\s+With\b", re.I)),
]
# Однострочные If ... Then тоже считаются открытыми только если это не If ... Then <оператор>
RE_SINGLE_LINE_IF = re.compile(r"^\s*If\b.*\bThen\s+\S", re.I)
RE_COLON_JOIN = re.compile(r":\s*(?:If\b.*\bThen|For\b|Do\b|While\b)", re.I)


@dataclass
class Issue:
    path: str
    line: int
    kind: str          # error | hint
    message: str


@dataclass
class FileReport:
    path: str
    lines: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.kind == "error"]

    def to_dict(self) -> dict:
        return {"path": self.path, "lines": self.lines,
                "issues": [issue.__dict__ for issue in self.issues]}


def read_any_encoding(path: Path) -> str:
    """Читает .vbs в любой кодировке, какую понимает Windows Script Host.

    WSH понимает ANSI (системная кодовая страница) и UTF-16 с BOM. Файлы в
    UTF-8 (с BOM и без) редакторы и Git создают постоянно, поэтому распознаём
    все варианты: иначе проверка на такой файле выдаёт ложные ошибки.
    """
    raw = path.read_bytes()
    for bom, encoding in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
                          (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def logical_lines(text: str) -> list[tuple[int, str]]:
    """Склеивает продолжения « _» и возвращает (номер первой строки, текст)."""
    result: list[tuple[int, str]] = []
    buffer = ""
    start = 1
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not buffer:
            start = number
        stripped = line.rstrip()
        if stripped.endswith("_") and not stripped.endswith('"_'):
            buffer += stripped[:-1] + " "
            continue
        result.append((start, buffer + line))
        buffer = ""
    if buffer:
        result.append((start, buffer))
    return result


def check_file(path: Path, root: Path) -> FileReport:
    text = read_any_encoding(path)
    relative = str(path.relative_to(root))
    report = FileReport(path=relative, lines=len(text.splitlines()))
    lines = logical_lines(text)

    if not re.search(r"^\s*Option\s+Explicit", text, re.I | re.M):
        report.issues.append(Issue(relative, 1, "hint",
                                   "нет Option Explicit: опечатка в имени станет пустой переменной"))

    # Кавычки: в VBScript двойная кавычка внутри строки пишется как ""
    for number, line in lines:
        if line.count('"') % 2:
            report.issues.append(Issue(relative, number, "error",
                                       "непарная двойная кавычка в логической строке"))

    # Блоки
    stack: list[tuple[str, int]] = []
    procedure: str | None = None
    procedure_line = 0
    dims: dict[str, int] = {}
    for number, line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("'"):
            continue
        func = RE_FUNC_START.match(line)
        if func and not stripped.startswith("End"):
            if procedure:
                report.issues.append(Issue(relative, procedure_line, "error",
                                           f"процедура {procedure} не закрыта"))
            procedure, procedure_line = func.group(1), number
            dims = {}
        if RE_FUNC_END.match(line):
            procedure = None
        if procedure:
            dim = RE_DIM.match(line)
            if dim:
                for name in dim.group(1).split(","):
                    name = name.strip().split("(")[0].strip()
                    if not name:
                        continue
                    if name.lower() in dims:
                        report.issues.append(Issue(
                            relative, number, "error",
                            f"повторный Dim «{name}» в процедуре {procedure} "
                            f"(первый — строка {dims[name.lower()]})"))
                    else:
                        dims[name.lower()] = number

        for name, opener, closer in RE_BLOCK_OPEN:
            if closer.match(line):
                if stack and stack[-1][0] == name:
                    stack.pop()
                elif stack:
                    report.issues.append(Issue(
                        relative, number, "error",
                        f"«{closer.pattern}» закрывает не тот блок "
                        f"(открыт «{stack[-1][0]}» со строки {stack[-1][1]})"))
            elif opener.match(line):
                if name == "If" and (RE_SINGLE_LINE_IF.match(line) or RE_COLON_JOIN.search(line)):
                    continue                      # однострочный If
                stack.append((name, number))
    for name, line in stack:
        report.issues.append(Issue(relative, line, "error", f"блок «{name}» не закрыт"))
    if procedure:
        report.issues.append(Issue(relative, procedure_line, "error",
                                   f"процедура {procedure} не закрыта"))

    for number, line in lines:
        code = code_part(line)
        if RE_PYTHON_EXE.search(code) and "start_debug" not in path.name:
            report.issues.append(Issue(relative, number, "hint",
                                       "запускается python.exe — под pythonw появится окно консоли"))
        for match in RE_ABS_PATH.finditer(code):
            tail = code[match.start():match.start() + 90]
            token = tail.split('"', 1)[0] if '"' in tail else tail.split(",", 1)[0]
            if RE_INTERPRETER_PATH.search(token.strip()):
                continue          # список типовых путей установки Python — это нормально
            fragment = code[max(0, match.start() - 12):match.start() + 28].strip()
            report.issues.append(Issue(relative, number, "hint",
                                       f"жёсткий путь «{fragment}…» — проект не перенести"))
    return report


def code_part(line: str) -> str:
    """Часть строки до комментария (' вне кавычек); кавычки внутри строк — как ""."""
    result = []
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if in_string and index + 1 < len(line) and line[index + 1] == '"':
                result.append(char)
                index += 2
                continue
            in_string = not in_string
            result.append(char)
        elif char == "'" and not in_string:
            break
        else:
            result.append(char)
        index += 1
    return "".join(result)


def iter_vbs(root: Path):
    for path in sorted(root.rglob("*.vbs")):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка VBS-скриптов")
    parser.add_argument("--root", default=None, help="корень репозитория или папка")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    reports = [check_file(path, root) for path in iter_vbs(root)]
    hard_errors = sum(len(report.errors) for report in reports)

    if args.json:
        print(json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2))
        return 1 if hard_errors else 0

    print("=" * 78)
    print(" ПРОВЕРКА VBS — SPECIALS/tools/check_vbs.py")
    print(f" Папка: {root}; файлов: {len(reports)}")
    print("=" * 78)
    for report in reports:
        mark = "!! " if report.errors else ("~  " if report.issues else "ok ")
        print(f"\n{mark}{report.path}  ({report.lines} строк)")
        for issue in report.issues:
            prefix = "  ОШИБКА" if issue.kind == "error" else "  совет "
            print(f"{prefix} строка {issue.line}: {issue.message}")
    print("\n" + "=" * 78)
    print(f"ИТОГ: ошибок {hard_errors}; файлов с замечаниями "
          f"{sum(1 for r in reports if r.issues)}; всего файлов {len(reports)}")
    print("=" * 78)
    return 1 if hard_errors else 0


if __name__ == "__main__":
    sys.exit(main())
