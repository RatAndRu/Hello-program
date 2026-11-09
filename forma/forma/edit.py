"""Правка сценария ``.forma`` по смещениям разбора.

Источник истины Формы — текст сценария. Поэтому панель параметров не хранит
своих значений: она просит поправить одну строку, а всё остальное (пересборка,
проверки, провенанс) идёт обычным путём. Здесь нет ни одного регулярного
выражения: границы токенов приходят из :mod:`forma.dsl`, где уже учтены
кавычки, вложенные скобки и переносы строк.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import Command, PARAM_ALIASES, parse_script
from .errors import FormaError
from .ops import lookup


# --------------------------------------------------------------------------
# Литералы
# --------------------------------------------------------------------------

def _is_number(raw: str) -> bool:
    text = raw.strip()
    if not text:
        return False
    if text[0] in "+-":
        text = text[1:]
    if not text:
        return False
    dot = text.count(".")
    if dot > 1:
        return False
    return text.replace(".", "", 1).isdigit()


def literal_value(raw: str) -> bool:
    """``True``, если значение не зависит от параметров сценария.

    Связанные значения (``round=R/2``) нельзя молча перезаписывать: это разрыв
    связи, о котором пользователь должен узнать.
    """
    text = (raw or "").strip()
    if not text:
        return False
    if text[0] in "\"'":
        return text[-1:] == text[0] and len(text) > 1
    if text.lower() in {"true", "false", "да", "нет"}:
        return True
    if text[0] in "[(" and text[-1:] in "])":
        inner = text[1:-1]
        parts = [p for p in inner.replace(";", ",").split(",")]
        return all(_is_number(p) or p.strip().lower() in {"true", "false"} or
                   (p.strip()[:1] in "\"'" and p.strip()[-1:] == p.strip()[:1])
                   for p in parts)
    return _is_number(text)


# --------------------------------------------------------------------------
# Поиск строки и её границ
# --------------------------------------------------------------------------

def _physical_lines(text: str) -> list[int]:
    """Начала физических строк."""
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _line_bounds(text: str, line: int) -> tuple[int, int]:
    starts = _physical_lines(text)
    if line < 1 or line > len(starts):
        raise FormaError(f"Строки {line} нет в сценарии.")
    begin = starts[line - 1]
    end = starts[line] - 1 if line < len(starts) else len(text)
    return begin, end


def _code_end(text: str, line: int) -> int:
    """Конец кода в физической строке — до комментария и пробелов."""
    begin, end = _line_bounds(text, line)
    chunk = text[begin:end]
    quote = ""
    cut = len(chunk)
    index = 0
    while index < len(chunk):
        ch = chunk[index]
        if quote:
            if ch == "\\":
                index += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            cut = index
            break
        index += 1
    body = chunk[:cut].rstrip()
    return begin + len(body)


def _definition_lines(text: str) -> set[int]:
    """Строки, занятые объявлениями ``module``/``def`` — их править нельзя."""
    from .library import parse_program

    try:
        program = parse_program(text)
    except Exception:  # noqa: BLE001 — сценарий может быть ещё не дописан
        return set()
    lines: set[int] = set()
    for definition in program.definitions.values():
        width = definition.body.count("\n") + 1
        for offset in range(width + 1):
            lines.add(definition.line + offset)
    return lines


@dataclass
class Edits:
    """Набор замен: (начало, конец, текст) в абсолютных смещениях."""

    script: str
    changes: list[tuple[int, int, str]] = field(default_factory=list)

    def replace(self, begin: int, end: int, text: str) -> None:
        self.changes.append((begin, end, text))

    def insert(self, at: int, text: str) -> None:
        self.changes.append((at, at, text))

    def apply(self, warnings: list[str]) -> str:
        ordered = sorted(self.changes, key=lambda item: item[0])
        for (_pb, prev_e, _), (b, _e, _t) in zip(ordered, ordered[1:]):
            if prev_e > b:
                raise FormaError("Правки пересекаются: измените параметры по одному.")
        out = self.script
        for begin, end, text in sorted(ordered, key=lambda item: item[0], reverse=True):
            out = out[:begin] + text + out[end:]
        if not out.endswith("\n") and self.script.endswith("\n"):
            out += "\n"
        return out


# --------------------------------------------------------------------------
# Поиск команды
# --------------------------------------------------------------------------

def find_command(commands: list[Command], line: int, target: str | None = None,
                 verb: str | None = None) -> Command:
    candidates = [c for c in commands if c.line == line]
    if target:
        exact = [c for c in candidates if c.target == target]
        if exact:
            candidates = exact
        else:
            other = [c for c in candidates if c.target is None]
            if other:
                candidates = other
    if verb:
        lowered = verb.lower()
        matched = [c for c in candidates if c.verb.lower() == lowered]
        if matched:
            candidates = matched
    if not candidates:
        raise FormaError(f"На строке {line} нет команды, которую можно править.")
    return candidates[0]


def canonical_key(cmd: Command, key: str) -> str:
    """Приводит имя параметра к тому, как оно записано в строке."""
    spec = lookup(cmd.verb)
    local = dict(getattr(spec, "param_aliases", {}) or {})
    want = PARAM_ALIASES.get(key.lower()) or local.get(key.lower()) or key
    for existing in cmd.spans.get("kwargs", {}):
        resolved = local.get(existing.lower()) or PARAM_ALIASES.get(existing.lower()) or existing
        if resolved == want:
            return existing
    return key


# --------------------------------------------------------------------------
# Операции
# --------------------------------------------------------------------------

def _guard(text: str, line: int) -> None:
    if line in _definition_lines(text):
        raise FormaError("Строка внутри объявления module/def — её правит автор "
                         "сценария, а не панель параметров.")


def _set_param(text: str, edit: dict, warnings: list[str]) -> tuple[str, dict]:
    line = int(edit.get("line") or 0)
    _guard(text, line)
    commands = parse_script(text)
    cmd = find_command(commands, line, edit.get("target"), edit.get("verb"))
    key = str(edit.get("param") or edit.get("key") or "").strip()
    if not key:
        raise FormaError("Не указан параметр для правки.")
    value = edit.get("value")
    if value is None:
        raise FormaError("Не указано значение параметра.")
    raw_value = value if isinstance(value, str) else _format_value(value)
    source_key = canonical_key(cmd, key)
    spans = cmd.spans.get("kwargs", {})
    changes = Edits(text)
    previous = cmd.kwargs.get(source_key)
    if previous is not None and not literal_value(previous) and not edit.get("break_link"):
        return text, {
            "ok": False,
            "reason": "linked",
            "line": line,
            "param": source_key,
            "value": previous,
            "message": ("Значение связано с параметром сценария. Правка разорвёт "
                        "связь — подтвердите её отдельно."),
        }
    if source_key in spans:
        begin, end = spans[source_key]["value"]
        changes.replace(begin, end, raw_value)
        action = "replace"
    else:
        # Дописывать надо в конец команды: у команды с переносом строки хвост
        # первой физической строки — обратный слэш, и «вставка перед ним»
        # склеила бы параметр с продолжением.
        point = _code_end(text, _last_line_of(cmd, text))
        changes.insert(point, f" {source_key}={raw_value}")
        action = "append"
        if cmd.line != _last_line_of(cmd, text):
            warnings.append("Команда занимает несколько строк: параметр дописан "
                            "в последнюю строку команды.")
    return changes.apply(warnings), {
        "ok": True, "action": action, "line": line, "param": source_key,
        "value": raw_value, "previous": previous,
        "spans": spans.get(source_key),
    }


def _last_line_of(cmd: Command, text: str) -> int:
    end = cmd.spans.get("line", [0, 0])[1]
    return text.count("\n", 0, end) + 1


def _unset_param(text: str, edit: dict, warnings: list[str]) -> tuple[str, dict]:
    line = int(edit.get("line") or 0)
    _guard(text, line)
    cmd = find_command(parse_script(text), line, edit.get("target"), edit.get("verb"))
    key = str(edit.get("param") or edit.get("key") or "").strip()
    source_key = canonical_key(cmd, key)
    spans = cmd.spans.get("kwargs", {})
    if source_key not in spans:
        raise FormaError(f"Параметра «{key}» в строке {line} нет.")
    begin, end = spans[source_key]["whole"]
    while begin > 0 and text[begin - 1] in " \t":
        begin -= 1
    changes = Edits(text)
    changes.replace(begin, end, "")
    return changes.apply(warnings), {
        "ok": True, "action": "unset", "line": line, "param": source_key,
        "previous": cmd.kwargs.get(source_key),
    }


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        items = ", ".join(_format_value(item) for item in value)
        return f"[{items}]"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _toggle_line(text: str, edit: dict) -> tuple[str, dict]:
    """Временно выключает команду, не удаляя её.

    Выключенная команда — это строка, начинающаяся с ``#``. Такой способ
    выбран специально: он виден в тексте, не требует второго хранилища
    состояний и переживает перезапуск. Обратное включение снимает ровно один
    маркер ``# ``, поэтому комментарий автора не теряется.
    """
    line = int(edit.get("line") or 0)
    _guard(text, line)
    enabled = edit.get("enabled")
    begin, end = _line_bounds(text, line)
    chunk = text[begin:end]
    stripped = chunk.lstrip()
    indent = chunk[:len(chunk) - len(stripped)]
    disabled = stripped.startswith("#")
    want = (not disabled) if enabled is None else not bool(enabled)
    if want == disabled:
        return text, {"ok": True, "action": "set_enabled", "line": line,
                      "enabled": not disabled, "changed": False}
    if want:
        new_chunk = indent + "# " + stripped
    else:
        body = stripped[1:]
        if body.startswith(" "):
            body = body[1:]
        new_chunk = indent + body
    changes = Edits(text)
    changes.replace(begin, end, new_chunk)
    return changes.apply([]), {"ok": True, "action": "set_enabled", "line": line,
                               "enabled": not want, "changed": True}


def _insert_line(text: str, after: int, line_text: str) -> str:
    lines = text.split("\n")
    lines.insert(after, line_text)
    return "\n".join(lines)


def _is_commented(text: str, line: int) -> bool:
    begin, end = _line_bounds(text, line)
    return text[begin:end].lstrip().startswith("#")


def _delete_line(text: str, edit: dict) -> str:
    line = int(edit.get("line") or 0)
    _guard(text, line)
    if _is_commented(text, line):
        lines = text.split("\n")
        del lines[line - 1]
        return "\n".join(lines)
    cmd = find_command(parse_script(text), line, edit.get("target"), edit.get("verb"))
    last = _last_line_of(cmd, text)
    lines = text.split("\n")
    del lines[line - 1:last]
    out = "\n".join(lines)
    return out


def _move_line(text: str, edit: dict) -> str:
    line = int(edit.get("line") or 0)
    to = int(edit.get("to") or edit.get("after") or 0)
    _guard(text, line)
    _guard(text, to)
    if _is_commented(text, line):
        lines = text.split("\n")
        block = [lines.pop(line - 1)]
        index = max(0, min(to, len(lines)))
        lines[index:index] = block
        return "\n".join(lines)
    cmd = find_command(parse_script(text), line, edit.get("target"), edit.get("verb"))
    last = _last_line_of(cmd, text)
    lines = text.split("\n")
    block = lines[line - 1:last]
    rest = lines[:line - 1] + lines[last:]
    index = to if to <= line else to - (last - line + 1)
    index = max(0, min(index, len(rest)))
    rest[index:index] = block
    return "\n".join(rest)


def edit_source(script: str, edit: dict | None = None) -> dict:
    """Правит текст сценария и возвращает новый текст.

    ``edit`` — описание правки: ``{"action": "set_param", "line": 12,
    "param": "h", "value": 40}``. Ничего, кроме текста, не меняется: ни
    провенанс, ни кэши — пересборка идёт отдельным шагом.
    """
    text = (script or "").replace("\r\n", "\n").replace("\r", "\n")
    payload = dict(edit or {})
    action = str(payload.get("action") or "set_param").lower()
    warnings: list[str] = []
    if action in {"set_param", "set_at"}:
        if action == "set_at":
            payload["param"] = "at"
        new_text, info = _set_param(text, payload, warnings)
    elif action == "unset_param":
        new_text, info = _unset_param(text, payload, warnings)
    elif action == "set_params":
        values = payload.get("values") or payload.get("params") or {}
        if not isinstance(values, dict) or not values:
            raise FormaError("Правка set_params ждёт словарь значений.")
        current = text
        applied = []
        for key, value in values.items():
            current, info = _set_param(current, {**payload, "param": key, "value": value}, warnings)
            if not info.get("ok", True):
                raise FormaError(info.get("message") or f"Параметр «{key}» не изменён.")
            applied.append(info)
        new_text, info = current, {"ok": True, "action": "set_params", "applied": applied}
    elif action == "add_command":
        line_text = str(payload.get("text") or "").strip()
        if not line_text:
            raise FormaError("Нечего вставлять: пустая строка команды.")
        if "\n" in line_text:
            raise FormaError("Команда должна быть одной строкой.")
        after = payload.get("after_line")
        if after is None:
            after = len(text.split("\n"))
        new_text = _insert_line(text, int(after), line_text)
        info = {"ok": True, "action": "add_command", "after_line": int(after),
                "text": line_text}
    elif action in {"set_enabled", "toggle_command"}:
        new_text, info = _toggle_line(text, payload)
    elif action == "delete_line":
        new_text = _delete_line(text, payload)
        info = {"ok": True, "action": "delete_line", "line": payload.get("line")}
    elif action == "move_line":
        new_text = _move_line(text, payload)
        info = {"ok": True, "action": "move_line", "line": payload.get("line"),
                "to": payload.get("to")}
    else:
        raise FormaError(f"Неизвестная правка «{action}».")
    if new_text is None:
        return {"ok": False, "script": text, **info}
    if new_text == text:
        warnings.append("Текст не изменился: значение уже такое.")
    return {
        "ok": bool(info.get("ok", True)),
        "script": new_text,
        "changed": new_text != text,
        "edit": info,
        "warnings": warnings,
        "line_count": len(new_text.split("\n")),
    }


def commands_payload(script: str, *, editable: bool = True) -> list[dict]:
    """Список команд сценария с номерами строк и смещениями.

    Нужен интерфейсу: панель объекта показывает, какую именно строку она
    изменит, а проверки — что правка не задела объявления.
    """
    text = (script or "").replace("\r\n", "\n").replace("\r", "\n")
    blocked = _definition_lines(text) if editable else set()
    out: list[dict] = []
    try:
        commands = parse_script(text)
    except FormaError:
        return out
    for cmd in commands:
        spans = cmd.spans or {}
        out.append({
            "line": cmd.line,
            "last_line": _last_line_of(cmd, text),
            "target": cmd.target,
            "verb": cmd.verb,
            "args": list(cmd.args),
            "kwargs": dict(cmd.kwargs),
            "text": cmd.text,
            "spans": spans,
            "enabled": True,
            "editable": cmd.line not in blocked,
            "in_definition": cmd.line in blocked,
        })
    # Выключенная команда — закомментированная строка. Панель должна её видеть,
    # иначе выключить шаг можно, а включить обратно — нет.
    for index, physical in enumerate(text.split("\n"), start=1):
        stripped = physical.strip()
        if not stripped.startswith("#"):
            continue
        body = stripped[1:].strip()
        if not body or body.startswith("#"):
            continue
        try:
            parsed = parse_script(body)
        except FormaError:
            continue
        if len(parsed) != 1 or "\n" in body:
            continue
        cmd = parsed[0]
        if not cmd.verb:
            continue
        out.append({
            "line": index,
            "last_line": index,
            "target": cmd.target,
            "verb": cmd.verb,
            "args": list(cmd.args),
            "kwargs": dict(cmd.kwargs),
            "text": body,
            "spans": {},
            "enabled": False,
            "editable": index not in blocked,
            "in_definition": index in blocked,
        })
    out.sort(key=lambda item: item["line"])
    return out
