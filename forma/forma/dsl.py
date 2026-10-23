"""Парсер текстового языка ФОРМА.

Синтаксис — по одной команде на строку:

    имя_объекта = команда параметр=значение ...
    команда объект параметр=значение ...
    параметр = 95
    check объект правило 3..5

Значения: числа и выражения (2*pi, height/2), списки [1,2,3],
точки [(0,0),(10,0)] или [0,0 10,0], строки "в кавычках", диапазоны 3..5.
Комментарии — # до конца строки. Длинные строки можно переносить
внутри скобок или символом \\.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import DslError
from .geometry import as_points
from .model import Scene, Solid
from .values import (Range, bracket_balance, parse_number, parse_value,
                     split_top_level, strip_comment)

ASSIGN_RE = re.compile(r"^([^\W\d]\w*)\s*=\s*(?!=)(.*)$", re.UNICODE)
LET_RE = re.compile(r"^let\s+([^\W\d]\w*)\s*=\s*(.*)$", re.UNICODE | re.IGNORECASE)
IDENT_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)

PARAM_ALIASES = {
    "радиус": "radius", "радиус2": "r2", "радиус_2": "r2", "высота": "height",
    "размер": "size", "размеры": "size", "сегменты": "segments", "сегмент": "segments",
    "толщина": "thickness", "цвет": "color", "материал": "material",
    "точки": "points", "путь": "path", "профиль": "profile", "сечения": "sections",
    "количество": "count", "угол": "angle", "ось": "axis", "центр": "center",
    "смещение": "offset", "сглаживание": "smooth", "скругление": "round",
    "поворот": "angle", "сторона": "sides", "стороны": "sides",
    "глубина": "depth", "ширина": "width", "длина": "length", "масштаб": "factor",
    "шаг": "step", "плотность": "density", "металл": "metal",
    "шероховатость": "rough", "видимость": "visible", "режим": "mode",
    "свечение": "emissive", "светится": "emissive", "glow": "emissive",
    "яркость": "emissive_strength", "сила_света": "emissive_strength",
    "прозрачность": "transmission",
    "точность": "tolerance", "уровень": "level", "уровни": "levels",
    "положение": "at", "позиция": "at", "от": "from", "до": "to",
    "открыто": "open", "выражение": "expression", "границы": "bounds",
    "разрешение": "resolution", "сферы": "spheres", "капсулы": "capsules",
    "касание": "blend", "к": "k", "объединить": "merge",
    "сохранить": "keep", "плоскость": "plane", "слой": "layer",
    "текст": "text", "надпись_текст": "text", "буквы": "text",
    "точка_вращения": "pivot", "петля": "pivot", "обороты": "turns",
    "расстояние": "distance", "путь_качения": "distance",
    # крепёж и сборка
    "в": "into", "во_что": "into", "направление": "direction", "вектор": "direction",
    "утопить": "sink", "шлиц": "drive", "головка": "head", "остриё": "tip",
    "острие": "tip", "шейка": "neck", "полная": "full", "полный": "full",
    "кисть": "radius", "радиус_кисти": "radius", "точка": "point", "центр_входа": "point",
}

STYLE_KEYS = {"color", "metal", "rough", "density", "material", "visible",
              "emissive", "emissive_strength", "transmission"}


@dataclass
class Command:
    line: int
    text: str
    target: str | None
    verb: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    rest: str = ""

    def describe(self) -> str:
        head = f"{self.target} = " if self.target else ""
        return f"{head}{self.verb} ..."


def _logical_lines(text: str):
    """Склеивает физические строки в логические, сохраняя номер первой."""
    physical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(physical):
        start = i + 1
        raw = strip_comment(physical[i]).rstrip()
        buf = raw
        while True:
            stripped = buf.rstrip()
            cont = stripped.endswith("\\")
            if cont:
                buf = stripped[:-1] + " "
            depth = bracket_balance(buf)
            if (cont or depth > 0) and i + 1 < len(physical):
                i += 1
                buf += " " + strip_comment(physical[i]).strip()
                continue
            break
        if buf.strip():
            yield start, buf.strip()
        i += 1


def _split_kwarg(token: str) -> tuple[str | None, str]:
    depth = 0
    quote = ""
    i = 0
    while i < len(token):
        ch = token[i]
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
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0:
            key = token[:i].strip()
            if IDENT_RE.match(key):
                return key, token[i + 1:].strip()
            return None, token
        i += 1
    return None, token


def parse_script(text: str) -> list[Command]:
    commands: list[Command] = []
    for line_no, raw in _logical_lines(text or ""):
        m_let = LET_RE.match(raw)
        if m_let:
            commands.append(Command(line=line_no, text=raw, target=None, verb="let",
                                    kwargs={m_let.group(1): m_let.group(2).strip()}, rest=raw))
            continue
        target = None
        rest = raw
        m = ASSIGN_RE.match(raw)
        if m and not raw.lower().startswith("check "):
            target = m.group(1)
            rest = m.group(2).strip()
        tokens = split_top_level(rest)
        if not tokens:
            raise DslError("Пустая команда после знака «=».", line=line_no, command=raw)
        verb = tokens[0]
        args: list[str] = []
        kwargs: dict[str, str] = {}
        for tok in tokens[1:]:
            key, value = _split_kwarg(tok)
            if key is None:
                args.append(value)
            else:
                if key in kwargs:
                    raise DslError(f"Параметр «{key}» задан дважды.", line=line_no, command=raw)
                kwargs[key] = value
        if target and verb.startswith("="):
            verb = ""
        commands.append(Command(line=line_no, text=raw, target=target, verb=verb,
                                args=args, kwargs=kwargs, rest=rest))
    return commands


def command_value(cmd: Command, params: dict[str, float]) -> Any:
    """Для строк вида `height = 95` — значение параметра."""
    raw = (cmd.rest or "").strip()
    if not raw:
        raise DslError(f"Не задано значение параметра «{cmd.target}».", line=cmd.line,
                       command=cmd.text)
    value = parse_value(raw, params)
    if isinstance(value, Range):
        raise DslError("Параметр не может быть диапазоном.", line=cmd.line)
    if not isinstance(value, (int, float)):
        raise DslError(f"Параметр «{cmd.target}» должен быть числом, получено «{value}».",
                       line=cmd.line)
    return float(value)


class Args:
    """Ленивый доступ к аргументам команды с проверкой имён и типов."""

    def __init__(self, cmd: Command, scene: Scene, spec, positional_map: list[str] | str | None):
        self.cmd = cmd
        self.scene = scene
        self.spec = spec
        self.params = scene.params
        self.vars = scene.vars
        self.extra: list[str] = []
        self.kwargs: dict[str, str] = {}
        for key, raw in cmd.kwargs.items():
            k = PARAM_ALIASES.get(key.lower(), key)
            if k in self.kwargs:
                raise DslError(f"Параметр «{k}» задан дважды.", line=cmd.line, command=cmd.text)
            self.kwargs[k] = raw
        positionals = list(cmd.args)
        if positional_map == "*":
            self.extra = positionals
        elif isinstance(positional_map, list):
            if len(positionals) > len(positional_map):
                extra = positionals[len(positional_map)]
                raise DslError(
                    f"Лишний аргумент «{extra}».",
                    hint="Доступные позиционные аргументы: " + (", ".join(positional_map) or "нет"),
                    line=cmd.line, command=cmd.text)
            for idx, raw in enumerate(positionals):
                key = positional_map[idx]
                if key in self.kwargs:
                    raise DslError(f"Параметр «{key}» указан дважды.", line=cmd.line,
                                   command=cmd.text)
                self.kwargs[key] = raw
        self._validate()

    def _validate(self) -> None:
        allowed = set(self.spec.params) | STYLE_KEYS
        unknown = [k for k in self.kwargs if k not in allowed]
        if unknown:
            keys = ", ".join(self.spec.params) or "—"
            kw = unknown[0]
            import difflib
            close = difflib.get_close_matches(kw, list(allowed), n=2, cutoff=0.6)
            hint = ("Возможно: " + ", ".join(close) + ". ") if close else ""
            hint += f"Параметры команды {self.spec.name}: {keys}"
            raise DslError(f"Неизвестный параметр «{kw}» у команды «{self.spec.name}».",
                           hint=hint, line=self.cmd.line, command=self.cmd.text)

    # ------------------------------------------------------------------ #
    def has(self, key: str) -> bool:
        return key in self.kwargs

    def raw(self, key: str) -> str | None:
        return self.kwargs.get(key)

    def value(self, key: str, default: Any = None) -> Any:
        if key not in self.kwargs:
            return default
        return parse_value(self.kwargs[key], self.params, self.vars)

    def num(self, key: str, default: float | None = None, required: bool = False,
            minv: float | None = None, maxv: float | None = None) -> float | None:
        if key not in self.kwargs:
            if required:
                raise DslError(f"Не задан обязательный параметр «{key}».",
                               hint=self._params_hint(), line=self.cmd.line, command=self.cmd.text)
            return default
        raw = self.kwargs[key]
        v = parse_value(raw, self.params)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise DslError(f"Параметр «{key}» должен быть числом, получено «{raw}».",
                           line=self.cmd.line, command=self.cmd.text)
        v = float(v)
        if minv is not None and v < minv - 1e-9:
            raise DslError(f"Параметр «{key}» должен быть ≥ {minv:g} (сейчас {v:g}).",
                           line=self.cmd.line, command=self.cmd.text)
        if maxv is not None and v > maxv + 1e-9:
            raise DslError(f"Параметр «{key}» должен быть ≤ {maxv:g} (сейчас {v:g}).",
                           line=self.cmd.line, command=self.cmd.text)
        return v

    def int(self, key: str, default: int | None = None, required: bool = False,
            minv: int | None = None, maxv: int | None = None) -> int | None:
        v = self.num(key, None if default is None else float(default), required,
                     None if minv is None else float(minv), None if maxv is None else float(maxv))
        if v is None:
            return None
        if abs(v - round(v)) > 1e-6:
            raise DslError(f"Параметр «{key}» должен быть целым числом.", line=self.cmd.line,
                           command=self.cmd.text)
        return int(round(v))

    def boolean(self, key: str, default: bool = False) -> bool:
        if key not in self.kwargs:
            return default
        raw = self.kwargs[key].strip().lower()
        if raw in ("true", "1", "да", "yes", "on", "истина"):
            return True
        if raw in ("false", "0", "нет", "no", "off", "ложь"):
            return False
        raise DslError(f"Параметр «{key}» должен быть true/false.", line=self.cmd.line,
                       command=self.cmd.text)

    def text(self, key: str, default: str | None = None, choices: list[str] | None = None) -> str | None:
        if key not in self.kwargs:
            return default
        raw = self.kwargs[key].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        if choices and raw not in choices:
            raise DslError(f"Параметр «{key}» должен быть одним из: {', '.join(choices)}.",
                           line=self.cmd.line, command=self.cmd.text)
        return raw

    def vec(self, key: str, dims: int = 3, default: Any = None, required: bool = False,
            fill_scalar: bool = True) -> list[float] | None:
        if key not in self.kwargs:
            if required:
                raise DslError(f"Не задан обязательный параметр «{key}» ({dims} числа).",
                               hint=self._params_hint(), line=self.cmd.line, command=self.cmd.text)
            return list(default) if default is not None else None
        v = parse_value(self.kwargs[key], self.params, self.vars)
        if isinstance(v, bool):
            raise DslError(f"Параметр «{key}» не может быть логическим.", line=self.cmd.line)
        if isinstance(v, (int, float)):
            return [float(v)] * dims if fill_scalar else [float(v)]
        if isinstance(v, (list, tuple)):
            nums = []
            for item in v:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise DslError(f"Параметр «{key}»: все элементы должны быть числами.",
                                   line=self.cmd.line, command=self.cmd.text)
                nums.append(float(item))
            if len(nums) == 1 and fill_scalar:
                return nums * dims
            if len(nums) != dims:
                raise DslError(f"Параметр «{key}»: нужно {dims} чисел, получено {len(nums)}.",
                               line=self.cmd.line, command=self.cmd.text)
            return nums
        raise DslError(f"Параметр «{key}» должен быть числом или списком чисел.",
                       line=self.cmd.line, command=self.cmd.text)

    def points(self, key: str, dims: int = 2, required: bool = True,
               default: Any = None) -> Any:
        if key not in self.kwargs:
            if required:
                raise DslError(f"Не задан обязательный параметр «{key}».",
                               hint=self._params_hint(), line=self.cmd.line, command=self.cmd.text)
            return default
        value = parse_value(self.kwargs[key], self.params, self.vars)
        try:
            return as_points(value, dims, key)
        except DslError:
            raise
        except Exception as exc:
            raise DslError(f"Параметр «{key}»: {exc}", line=self.cmd.line,
                           command=self.cmd.text) from exc

    def solid(self, key: str, required: bool = True, default: Any = None) -> Solid | None:
        if key not in self.kwargs:
            if required:
                raise DslError(f"Не задан объект «{key}».", hint=self._params_hint(),
                               line=self.cmd.line, command=self.cmd.text)
            return default
        return self.scene.resolve(self.value(key), "объект")

    def solids(self) -> list[Solid]:
        raws: list[Any] = []
        for raw in self.extra:
            raws.append(parse_value(raw, self.params, self.vars) if isinstance(raw, str) else raw)
        if "objects" in self.kwargs:
            raws.append(parse_value(self.kwargs["objects"], self.params, self.vars))
        solids: list[Solid] = []
        for raw in raws:
            if isinstance(raw, (list, tuple)):
                items = list(raw)
            else:
                items = [raw]
            for item in items:
                if isinstance(item, bool) or item is None:
                    raise DslError(
                        "Ожидалось имя объекта, а получено «"
                        + ("да" if item else "нет") + "».",
                        hint="Проверьте аргумент: в квадратных скобках указывается имя "
                             "объекта, например fillet [деталь] radius=2.",
                        line=self.cmd.line, command=self.cmd.text)
                solids.append(self.scene.resolve(item, "объект"))
        # уникализируем по имени, сохраняя порядок
        seen = set()
        out = []
        for s in solids:
            if s.name not in seen:
                seen.add(s.name)
                out.append(s)
        if not out:
            raise DslError("Не указаны объекты.",
                           hint="Например: union [корпус, ручка] или union objects=[a,b]",
                           line=self.cmd.line, command=self.cmd.text)
        return out

    def style(self) -> dict:
        data = {}
        if "material" in self.kwargs:
            from .geometry import MATERIAL_PRESETS
            mat = self.text("material")
            key = (mat or "").strip().lower()
            if key not in MATERIAL_PRESETS:
                raise DslError(f"Неизвестный материал «{mat}».",
                               hint="Доступно: " + ", ".join(sorted(MATERIAL_PRESETS)),
                               line=self.cmd.line, command=self.cmd.text)
            data.update(MATERIAL_PRESETS[key])
        if "color" in self.kwargs:
            from .geometry import normalize_color
            data["color"] = normalize_color(self.text("color") or "")
        for key in ("metal", "rough", "density"):
            if key in self.kwargs:
                v = self.num(key)
                if key in ("metal", "rough") and not (0.0 <= v <= 1.0):
                    raise DslError(f"Параметр «{key}» должен быть от 0 до 1.",
                                   line=self.cmd.line, command=self.cmd.text)
                data[key] = v
        if "emissive" in self.kwargs:
            from .geometry import normalize_color
            raw = (self.text("emissive") or "").strip().lower()
            if raw in ("да", "yes", "true", "1", "вкл"):
                data["emissive"] = "#ffffff"
            elif raw in ("нет", "no", "false", "0", "выкл", ""):
                data["emissive"] = ""
            else:
                data["emissive"] = normalize_color(raw)
        if "emissive_strength" in self.kwargs:
            v = self.num("emissive_strength")
            if not (0.0 <= v <= 20.0):
                raise DslError("Яркость свечения должна быть от 0 до 20.",
                               line=self.cmd.line, command=self.cmd.text)
            data["emissive_strength"] = v
        if "transmission" in self.kwargs:
            v = self.num("transmission")
            if not (0.0 <= v <= 1.0):
                raise DslError("Прозрачность должна быть от 0 до 1.",
                               line=self.cmd.line, command=self.cmd.text)
            data["transmission"] = v
        if "visible" in self.kwargs:
            data["visible"] = self.boolean("visible", True)
        return data

    def _params_hint(self) -> str:
        spec = self.spec
        if not spec.params:
            return ""
        return "Параметры: " + ", ".join(spec.params)
