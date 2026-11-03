"""Собственные библиотеки Forma: include, функции и параметрические модули.

Это небольшой слой поверх line-based DSL, а не второй интерпретатор OpenSCAD.
Модули исполняются в дочернем Scene с локальными параметрами и возвращают в
родительскую сцену обычные Solid/Contour2D. Поэтому все существующие операции,
проверки, морфинг и экспорт продолжают работать без отдельного CAD-дерева.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dsl import Command, parse_script
from .errors import DslError
from .values import parse_value, split_top_level, strip_comment

_IDENT = r"[^\W\d]\w*"
_DEF_RE = re.compile(rf"^\s*(module|модуль|function|функция)\s+({_IDENT})", re.IGNORECASE | re.UNICODE)
_INCLUDE_RE = re.compile(r"^\s*(?:include|включить|подключить)\s+(.+?)\s*$", re.IGNORECASE | re.UNICODE)
_RESERVED_VARS = "__forma_functions__"
_MAX_INCLUDE_DEPTH = 64
_MAX_FUNCTION_DEPTH = 64


def _curly_delta(text: str) -> int:
    """Число открытых фигурных скобок вне строк и комментариев."""
    text = strip_comment(text)
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth


def _brace_span(text: str) -> tuple[int, int]:
    """Позиции первой «{» и соответствующей ей «}»."""
    start = -1
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch == "#":
            # Комментарий до перевода строки; #rrggbb здесь не является
            # осмысленным телом модуля, но не мешает цветам в строках.
            end = text.find("\n", i)
            if end < 0:
                break
            i = end + 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "{":
            if depth == 0 and start < 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return start, i
            if depth < 0:
                break
        i += 1
    raise DslError("Не закрыт блок модуля: не хватает «}».")


def _parse_params(raw: str, line: int) -> list[tuple[str, str | None]]:
    if not raw.strip():
        return []
    parts = [item.strip() for item in split_top_level(raw, ",") if item.strip()]
    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for part in parts:
        if "=" in part:
            name, default = part.split("=", 1)
            name, default = name.strip(), default.strip()
            if not default:
                raise DslError(f"Пустое значение по умолчанию у параметра «{name}».", line=line)
        else:
            name, default = part.strip(), None
        if not re.fullmatch(_IDENT, name, re.UNICODE):
            raise DslError(f"Некорректное имя параметра «{name}».", line=line)
        if name in seen:
            raise DslError(f"Параметр «{name}» объявлен дважды.", line=line)
        seen.add(name)
        result.append((name, default))
    return result


def _parse_header(text: str, kind: str, line: int) -> tuple[str, list[tuple[str, str | None]]]:
    match = re.match(rf"^\s*(?:module|модуль|function|функция)\s+({_IDENT})\s*",
                     text, re.IGNORECASE | re.UNICODE)
    if not match:
        raise DslError("Ожидалось объявление module/function.", line=line)
    name = match.group(1)
    rest = text[match.end():].strip()
    params_raw = ""
    if rest.startswith("("):
        # Заголовок не содержит тела; последняя скобка — закрывающая список
        # параметров, включая вложенные списки в значениях по умолчанию.
        close = rest.rfind(")")
        if close < 0 or rest[close + 1:].strip():
            raise DslError(f"Не закрыт список параметров «{name}».", line=line)
        params_raw = rest[1:close]
    elif rest:
        raise DslError(f"Неожиданный текст в объявлении «{name}».", line=line)
    return name, _parse_params(params_raw, line)


@dataclass
class Definition:
    kind: str                         # function | module
    name: str
    params: list[tuple[str, str | None]]
    line: int
    expression: str = ""
    body: str = ""
    body_line: int = 1
    source: str = ""
    commands: list[Command] = field(default_factory=list)
    definitions: dict[str, "Definition"] = field(default_factory=dict)


@dataclass
class Program:
    commands: list[Command]
    definitions: dict[str, Definition]


def _split_definition_equals(text: str) -> tuple[str, str]:
    """Делит ``header = body`` только по «=» вне скобок и кавычек."""
    depth = 0
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == "\\":
                continue
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "=" and depth == 0:
            return text[:index], text[index + 1:]
    raise DslError("Объявление должно содержать «=» вне списка параметров.")


def parse_program(text: str) -> Program:
    """Разбирает обычный DSL и вынимает объявления библиотек.

    Объявления заменяются маркерами, поэтому физические номера строк остального
    сценария не сдвигаются. Тело модуля разбирается тем же ``parse_script``;
    никакого второго набора геометрических команд не появляется.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sanitized = list(lines)
    definitions: dict[str, Definition] = {}
    markers: dict[str, Definition] = {}
    i = 0
    while i < len(lines):
        clean = strip_comment(lines[i])
        match = _DEF_RE.match(clean)
        if not match:
            i += 1
            continue
        keyword = match.group(1).lower()
        kind = "module" if keyword in {"module", "модуль"} else "function"
        start = i
        first = clean.strip()
        # Определяем, есть ли блочное тело, по первой строке. Для function
        # разрешено только выражение — это намеренная защита от скрытых побочных
        # эффектов в арифметике.
        header_and_tail = first[match.start():]
        open_brace = header_and_tail.find("{")
        is_block = kind == "module" and open_brace >= 0
        end = i
        block = first
        if is_block:
            balance = _curly_delta(first)
            while balance > 0 and end + 1 < len(lines):
                end += 1
                block += "\n" + lines[end]
                balance += _curly_delta(lines[end])
            if balance != 0:
                raise DslError(f"Не закрыт блок модуля, начало на строке {start + 1}.",
                               line=start + 1)
            left, right = _brace_span(block)
            header = block[:left].strip()
            body = block[left + 1:right]
            if block[right + 1:].strip():
                raise DslError("После закрывающей «}» модуля нужна новая строка.",
                               line=start + 1)
            body_line = start + 1 + block[:left + 1].count("\n")
            if body.startswith("\n"):
                body_line += 1
            name, params = _parse_header(header, kind, start + 1)
            definition = Definition(kind=kind, name=name, params=params, line=start + 1,
                                    body=body, body_line=body_line)
        else:
            # function f(x)=... и короткий module m(...)=команда
            if "=" not in first:
                raise DslError(
                    f"Объявление «{match.group(2)}» должно содержать «=» или блок «{{…}}».",
                    line=start + 1)
            header, expression = _split_definition_equals(first)
            name, params = _parse_header(header, kind, start + 1)
            expression = expression.strip()
            if not expression:
                raise DslError(f"Пустое тело «{name}».", line=start + 1)
            definition = Definition(kind=kind, name=name, params=params, line=start + 1,
                                    expression=expression if kind == "function" else "",
                                    body="" if kind == "function" else expression,
                                    body_line=start + 1)
        marker = f"__forma_definition_{len(markers)}"
        definition.source = marker
        definitions[marker] = definition
        markers[marker] = definition
        sanitized[start] = marker
        for j in range(start + 1, end + 1):
            sanitized[j] = ""
        i = end + 1
    if not markers:
        return Program(parse_script(text), {})
    commands = parse_script("\n".join(sanitized))
    replaced: list[Command] = []
    for cmd in commands:
        definition = markers.get(cmd.verb or "")
        if definition is None:
            replaced.append(cmd)
        else:
            replaced.append(Command(line=definition.line, text=lines[definition.line - 1].strip(),
                                    target=None, verb="__forma_definition",
                                    kwargs={"id": definition.source}, rest=""))
    return Program(replaced, definitions)


def expand_includes(script: str, base_dir: str | Path | None = None,
                    _stack: list[Path] | None = None, _depth: int = 0) -> str:
    """Текстовально подключает .forma/.f3d библиотеки с защитой от циклов.

    ``.scad`` сюда намеренно не принимается: его исполняет настоящий headless
    OpenSCAD runner, а не Forma parser. Это различие видно в сообщении ошибки.
    """
    if _depth > _MAX_INCLUDE_DEPTH:
        raise DslError("Слишком глубокая цепочка include (больше 64 файлов).")
    root = Path(base_dir or Path.cwd()).expanduser().resolve()
    stack = list(_stack or [])
    out: list[str] = []
    for line_no, line in enumerate((script or "").replace("\r\n", "\n").split("\n"), start=1):
        match = _INCLUDE_RE.match(strip_comment(line))
        if not match:
            out.append(line)
            continue
        raw = match.group(1).strip()
        raw = re.sub(r"^file\s*=\s*", "", raw, flags=re.IGNORECASE).strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1].strip()
        raw = raw.strip("\"'")
        if not raw:
            raise DslError("include: не указан файл.", line=line_no)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if path.suffix.lower() == ".scad":
            raise DslError(
                "include предназначен для библиотек Forma, а не для .scad.",
                hint="Для произвольного SCAD/BOSL2 используйте команду openscad — Forma вызовет "
                     "настоящий OpenSCAD в фоне.", line=line_no)
        if path in stack:
            chain = " → ".join(str(item) for item in stack + [path])
            raise DslError("Обнаружен циклический include.", hint=chain, line=line_no)
        if not path.is_file():
            raise DslError(f"Библиотека не найдена: {raw}",
                           hint=f"Искали: {path}", line=line_no)
        try:
            included = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DslError(f"Не удалось прочитать библиотеку «{raw}»: {exc}", line=line_no) from exc
        out.append(expand_includes(included, path.parent, stack + [path], _depth + 1))
    return "\n".join(out)


class UserFunction:
    """Чистая числовая функция с лексическими глобальными и локальными аргументами."""

    def __init__(self, definition: Definition, scene):
        self.definition = definition
        self.scene = scene

    def clone_for(self, scene):
        return UserFunction(self.definition, scene)

    def __call__(self, *args, **kwargs) -> float:
        definition = self.definition
        params = definition.params
        if len(args) > len(params):
            raise ValueError(f"{definition.name}: лишние позиционные аргументы")
        local_params = {key: value for key, value in self.scene.params.items()
                        if isinstance(value, (int, float)) and not isinstance(value, bool)}
        local_vars = dict(self.scene.vars)
        local_vars[_RESERVED_VARS] = self.scene.functions
        supplied: dict[str, Any] = {}
        for index, value in enumerate(args):
            supplied[params[index][0]] = value
        for key, value in kwargs.items():
            if key not in {item[0] for item in params}:
                raise ValueError(f"{definition.name}: неизвестный аргумент «{key}»")
            if key in supplied:
                raise ValueError(f"{definition.name}: аргумент «{key}» задан дважды")
            supplied[key] = value
        for key, default in params:
            if key in supplied:
                value = supplied[key]
            elif default is not None:
                value = parse_value(default, local_params, local_vars, self.scene.functions)
            else:
                raise ValueError(f"{definition.name}: не задан аргумент «{key}»")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                local_params[key] = float(value)
            else:
                local_vars[key] = value
        depth = int(getattr(self.scene, "_function_depth", 0))
        if depth >= _MAX_FUNCTION_DEPTH:
            raise ValueError(f"{definition.name}: превышена глубина рекурсии (64)")
        self.scene._function_depth = depth + 1
        try:
            value = parse_value(definition.expression, local_params, local_vars, self.scene.functions)
        finally:
            self.scene._function_depth = depth
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{definition.name}: функция должна возвращать число")
        return float(value)


def register_definitions(scene, definitions: dict[str, Definition]) -> None:
    """Регистрирует определения и заранее проверяет тела модулей."""
    for definition in definitions.values():
        if definition.kind == "function":
            if definition.name in scene.functions:
                raise DslError(f"Функция «{definition.name}» объявлена дважды.", line=definition.line)
            scene.functions[definition.name] = UserFunction(definition, scene)
        else:
            if definition.name in scene.modules:
                raise DslError(f"Модуль «{definition.name}» объявлен дважды.", line=definition.line)
            if not definition.commands:
                program = parse_program(definition.body)
                offset = definition.body_line - 1
                for command in program.commands:
                    command.line += offset
                for nested in program.definitions.values():
                    nested.line += offset
                definition.commands = program.commands
                definition.definitions = program.definitions
            scene.modules[definition.name] = definition
    scene.vars[_RESERVED_VARS] = scene.functions


def clone_functions(functions: dict[str, Any], scene) -> dict[str, Any]:
    return {name: (value.clone_for(scene) if hasattr(value, "clone_for") else value)
            for name, value in functions.items()}


def bind_module_values(definition: Definition, positional: list[Any], named: dict[str, Any],
                       scene) -> tuple[dict[str, float], dict[str, Any], dict[str, Any]]:
    """Проверяет аргументы модуля и создаёт его локальный scope."""
    params = definition.params
    if len(positional) > len(params):
        raise DslError(f"Модуль «{definition.name}»: лишние позиционные аргументы.",
                       hint="Допустимые параметры: " + ", ".join(k for k, _ in params))
    known = {key for key, _ in params}
    unknown = [key for key in named if key not in known]
    if unknown:
        raise DslError(f"Модуль «{definition.name}»: неизвестный параметр «{unknown[0]}».",
                       hint="Параметры: " + (", ".join(known) or "нет"))
    local_params = dict(scene.params)
    local_vars = dict(scene.vars)
    local_vars[_RESERVED_VARS] = scene.functions
    values: dict[str, Any] = {}
    for index, value in enumerate(positional):
        values[params[index][0]] = value
    for key, value in named.items():
        if key in values:
            raise DslError(f"Модуль «{definition.name}»: параметр «{key}» задан дважды.")
        values[key] = value
    for key, default in params:
        if key not in values:
            if key in getattr(scene, "overrides", {}):
                values[key] = scene.overrides[key]
            elif default is not None:
                values[key] = parse_value(default, local_params, local_vars, scene.functions)
            else:
                raise DslError(f"Модуль «{definition.name}»: не задан параметр «{key}».")
        value = values[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            local_params[key] = float(value)
        else:
            local_vars[key] = value
    return local_params, local_vars, values


def evaluate_call_text(text: str, scene) -> tuple[str, list[Any], dict[str, Any]]:
    """Разбирает ``name(1, width=20)`` для вызова модуля."""
    match = re.match(rf"^\s*({_IDENT})\s*\((.*)\)\s*$", text or "", re.DOTALL | re.UNICODE)
    if not match:
        raise DslError(f"Некорректный вызов модуля «{text}».")
    name, inner = match.group(1), match.group(2).strip()
    positional_raw: list[str] = []
    named_raw: dict[str, str] = {}
    if inner:
        for part in [item.strip() for item in split_top_level(inner, ",") if item.strip()]:
            if "=" in part:
                key, raw = part.split("=", 1)
                key = key.strip()
                if not re.fullmatch(_IDENT, key, re.UNICODE):
                    raise DslError(f"Некорректный именованный аргумент «{key}».")
                if key in named_raw:
                    raise DslError(f"Аргумент «{key}» задан дважды.")
                named_raw[key] = raw.strip()
            else:
                if named_raw:
                    raise DslError("Позиционный аргумент после именованного.")
                positional_raw.append(part)
    positional = [parse_value(raw, scene.params, scene.vars, scene.functions) for raw in positional_raw]
    named = {key: parse_value(raw, scene.params, scene.vars, scene.functions)
             for key, raw in named_raw.items()}
    return name, positional, named
