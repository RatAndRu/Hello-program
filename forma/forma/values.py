"""Разбор значений в сценарии: числа, выражения, списки, диапазоны, цвета."""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from typing import Any

from .errors import DslError

_MATH_NAMES = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "abs": abs, "min": min, "max": max, "round": round,
    "floor": math.floor, "ceil": math.ceil, "pow": pow,
    "radians": math.radians, "degrees": math.degrees, "log": math.log, "exp": math.exp,
    "hypot": math.hypot, "copysign": math.copysign,
}

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.FloorDiv, ast.UAdd, ast.USub,
)


class Range:
    """Диапазон для проверок: 3..5, ..5, 3.., 3.5."""

    __slots__ = ("lo", "hi")

    def __init__(self, lo: float | None = None, hi: float | None = None):
        self.lo = lo
        self.hi = hi

    def contains(self, value: float, tol: float = 1e-9) -> bool:
        if value is None or not math.isfinite(value):
            return False
        if self.lo is not None and value < self.lo - tol:
            return False
        if self.hi is not None and value > self.hi + tol:
            return False
        return True

    def is_exact(self) -> bool:
        return self.lo is not None and self.hi is not None and abs(self.lo - self.hi) < 1e-9

    def __str__(self) -> str:
        if self.lo is None and self.hi is None:
            return "любое"
        if self.lo is not None and self.hi is not None and abs(self.lo - self.hi) < 1e-9:
            return fmt(self.lo)
        return f"{'' if self.lo is None else fmt(self.lo)}..{'' if self.hi is None else fmt(self.hi)}"

    def describe(self) -> str:
        if self.lo is None and self.hi is None:
            return "любое значение"
        if self.lo is not None and self.hi is not None and abs(self.lo - self.hi) < 1e-9:
            return f"= {fmt(self.lo)}"
        if self.lo is None:
            return f"≤ {fmt(self.hi)}"
        if self.hi is None:
            return f"≥ {fmt(self.lo)}"
        return f"от {fmt(self.lo)} до {fmt(self.hi)}"


def fmt(value: float | int | None, digits: int = 2) -> str:
    """Красивый формат числа для отчётов."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if not isinstance(value, (int, float)):
        return str(value)
    if not math.isfinite(float(value)):
        return "—"
    v = float(value)
    if abs(v) >= 1000:
        s = f"{v:,.0f}".replace(",", " ")
        return s
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s.replace("-", "−")


def split_top_level(text: str, separators: str = " \t") -> list[str]:
    """Делит строку по разделителям, не заглядывая внутрь скобок и кавычек."""
    out: list[str] = []
    depth = 0
    quote = ""
    buf: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch in separators and depth == 0:
            if buf:
                out.append("".join(buf))
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append("".join(buf))
    return out


def split_items(text: str) -> list[str]:
    """Делит содержимое списка по запятым верхнего уровня.

    Если запятых нет вообще — по пробелам (например [1 2 3]).
    Выражения вида `радиус + 5` остаются одним элементом.
    """
    if split_top_level(text, ","):
        return [p.strip() for p in split_top_level(text, ",") if p.strip()]
    return [p for p in split_top_level(text, " \t") if p.strip()]


def bracket_balance(text: str) -> int:
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
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        i += 1
    return depth


_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?![0-9a-zA-Zа-яА-Я_])")


def strip_comment(line: str) -> str:
    """Удаляет #-комментарий, но не трогает цвета вида #ff0000."""
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            m = _HEX_COLOR_RE.match(line, i)
            if m and (i == 0 or line[i - 1] in " \t=,[("):
                return line
            if i == 0 or line[i - 1] in " \t":
                return line[:i]
        i += 1
    return line


def _eval_node(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("только числа")
    if isinstance(node, ast.Name):
        if node.id in names:
            return float(names[node.id])
        raise ValueError(f"неизвестное имя «{node.id}»")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left, names)
        right = _eval_node(node.right, names)
        try:
            return float(_BIN_OPS[type(node.op)](left, right))
        except ZeroDivisionError as exc:
            raise ValueError("деление на ноль") from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_eval_node(node.operand, names)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = names.get(node.func.id)
        if fn is None or node.func.id not in _MATH_NAMES:
            raise ValueError(f"неизвестная функция «{node.func.id}»")
        args = [_eval_node(a, names) for a in node.args]
        try:
            return float(fn(*args))
        except Exception as exc:
            raise ValueError(str(exc)) from exc
    raise ValueError("недопустимое выражение")


def parse_number(text: str, params: dict[str, float]) -> float | None:
    """Пытается вычислить числовое выражение. Возвращает None, если это не число."""
    raw = text.strip()
    if not raw:
        return None
    try:
        tree = ast.parse(raw, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return None
    names = dict(_MATH_NAMES)
    names.update({k: v for k, v in params.items() if isinstance(v, (int, float))})
    try:
        value = _eval_node(tree, names)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        body = raw[1:-1]
        return body.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return raw


def parse_value(raw: str, params: dict[str, float], variables: dict | None = None) -> Any:
    """Разбирает одно значение сценария."""
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return ""
    if (text[0] in "\"'" and text[-1] == text[0] and len(text) >= 2):
        return _unquote(text)
    low = text.lower()
    if low in ("true", "да", "yes", "on", "истина"):
        return True
    if low in ("false", "нет", "no", "off", "ложь"):
        return False
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [parse_value(part, params, variables) for part in split_items(inner)]
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if not inner:
            return ()
        return tuple(parse_value(part, params, variables) for part in split_items(inner))
    if ".." in text and not text.startswith("."):
        parts = re.split(r"\.\.+", text, maxsplit=1)
        if len(parts) == 2:
            lo = parse_number(parts[0], params) if parts[0].strip() else None
            hi = parse_number(parts[1], params) if parts[1].strip() else None
            if (lo is not None or hi is not None) and not (parts[0].strip() and lo is None) \
                    and not (parts[1].strip() and hi is None):
                return Range(lo, hi)
    if text.startswith(".."):
        tail = text[2:].strip()
        hi = parse_number(tail, params) if tail else None
        if hi is not None:
            return Range(None, hi)
    num = parse_number(text, params)
    if num is not None:
        return num
    if variables and text in variables:
        return variables[text]
    return _unquote(text)


def parse_range(raw: str, params: dict[str, float]) -> Range:
    value = parse_value(raw, params)
    if isinstance(value, Range):
        return value
    if isinstance(value, (int, float)):
        return Range(float(value), float(value))
    raise DslError(f"Ожидался диапазон вида 3..5 или число, получено «{raw}».")


def require_number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DslError(f"{what}: ожидалось число, получено «{value}».")
    return float(value)
