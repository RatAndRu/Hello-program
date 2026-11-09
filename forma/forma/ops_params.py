"""Параметры, presets и глобальная точность — команды без отдельного движка."""
from __future__ import annotations

import math
from typing import Any

from .errors import DslError
from .ops import op
from .values import parse_value

_SPECIAL = {"form_preset", "пресет_формы", "shape_preset", "пресет_фигуры",
            "param", "parameter", "параметр", "preset", "пресет", "набор",
            "precision", "точность", "quality", "качество",
            "derive", "link", "связать", "связь", "зависимость"}
_META = {"name", "default", "value", "min", "max", "step", "label", "group", "unit",
         "description", "choices", "мин", "макс", "шаг", "имя", "название"}


def _value(scene, raw):
    return parse_value(raw, scene.params, scene.vars, scene.functions)


def _number(scene, raw, what: str) -> float:
    value = _value(scene, raw) if isinstance(raw, str) else raw
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DslError(f"{what} должно быть числом, получено «{value}».")
    return float(value)


def _param(scene, cmd) -> None:
    args = list(cmd.args or [])
    kwargs = dict(cmd.kwargs or {})
    name = str(kwargs.get("name") or kwargs.get("имя") or "").strip()
    if not name and args:
        name = str(args.pop(0)).strip().strip("\"'")
    if not name:
        # Короткая форма: param height=20 min=5 …
        for key in kwargs:
            if key not in _META:
                name = key
                kwargs["default"] = kwargs.pop(key)
                break
    if not name:
        raise DslError("param: укажите имя, например param height=95 min=20 max=200.",
                       line=cmd.line, command=cmd.text)
    if args:
        raise DslError(f"param: лишний аргумент «{args[0]}».", line=cmd.line)
    meta = dict(scene.param_meta.get(name) or {})
    current = scene.params.get(name)
    default_raw = kwargs.get("default", kwargs.get("value"))
    if default_raw is not None:
        value = _number(scene, default_raw, f"Параметр {name}")
    elif current is not None:
        value = float(current)
    else:
        raise DslError(f"param {name}: нужен default=… или ранее заданное значение.",
                       line=cmd.line)
    for key, aliases in (("min", ("min", "мин")), ("max", ("max", "макс")),
                         ("step", ("step", "шаг"))):
        raw = next((kwargs[item] for item in aliases if item in kwargs), None)
        if raw is not None:
            meta[key] = _number(scene, raw, f"{name}.{key}")
    for key in ("label", "group", "unit", "description"):
        if key in kwargs:
            text_value = _value(scene, kwargs[key])
            meta[key] = str(text_value)
    if "choices" in kwargs:
        choices_value = _value(scene, kwargs["choices"])
        meta["choices"] = list(choices_value) if isinstance(choices_value, (list, tuple)) else [choices_value]
    meta.setdefault("label", name)
    if default_raw is not None or "default" not in meta:
        meta["default"] = float(value)
    if "min" in meta and "max" in meta and meta["min"] > meta["max"]:
        raise DslError(f"param {name}: min больше max.", line=cmd.line)
    if "min" in meta and value < meta["min"] - 1e-9:
        raise DslError(f"param {name}: значение {value:g} меньше min={meta['min']:g}.", line=cmd.line)
    if "max" in meta and value > meta["max"] + 1e-9:
        raise DslError(f"param {name}: значение {value:g} больше max={meta['max']:g}.", line=cmd.line)
    effective = float(getattr(scene, "overrides", {}).get(name, value))
    if "min" in meta and effective < meta["min"] - 1e-9:
        raise DslError(f"param {name}: override {effective:g} меньше min={meta['min']:g}.", line=cmd.line)
    if "max" in meta and effective > meta["max"] + 1e-9:
        raise DslError(f"param {name}: override {effective:g} больше max={meta['max']:g}.", line=cmd.line)
    scene.params[name] = effective
    scene.param_meta[name] = meta
    scene.log("info", f"параметр {name} = {value:g}; доступен в панели и presets", cmd.line)


def _derive(scene, cmd) -> None:
    """Связывает размер с выражением и пересчитывает его на каждом rebuild.

    Короткая форма ``column_h = derive base_h * 1.25`` намеренно похожа на
    обычное присваивание, но не принимает override самого результата: панель
    отправляет все значения сразу, и старое значение зависимого параметра не
    должно побеждать новое значение его источника.
    """
    kwargs = dict(cmd.kwargs or {})
    args = list(cmd.args or [])
    name = str(cmd.target or kwargs.pop("name", "") or kwargs.pop("target", "")
               or kwargs.pop("имя", "") or "").strip()
    if not name and args:
        name = str(args.pop(0)).strip().strip("\"'")
    raw = kwargs.pop("expr", kwargs.pop("expression", kwargs.pop("from", kwargs.pop("source", None))))
    if raw is None and args:
        raw = " ".join(str(item) for item in args)
    if raw is None:
        raw = kwargs.pop("value", None)
    if not name or not name.isidentifier():
        raise DslError("derive: укажите имя зависимого размера, например "
                       "column_h = derive base_h * 1.25.", line=cmd.line, command=cmd.text)
    if raw is None or not str(raw).strip():
        raise DslError(f"derive {name}: нужно выражение, например base_h * 1.25.",
                       line=cmd.line, command=cmd.text)
    expression = str(raw).strip()
    if expression.startswith("="):
        expression = expression[1:].strip()
    if kwargs:
        unknown = next(iter(kwargs))
        raise DslError(f"derive {name}: неизвестный параметр «{unknown}».", line=cmd.line)
    try:
        value = parse_value(expression, scene.params, scene.vars, scene.functions)
    except Exception as exc:
        raise DslError(f"derive {name}: не удалось вычислить «{expression}»: {exc}",
                       line=cmd.line, command=cmd.text) from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DslError(f"derive {name}: выражение должно давать конечное число, получено «{value}».",
                       line=cmd.line, command=cmd.text)

    # Для reset сохраняем заводское значение, а не вариант с override источника.
    default_params = dict(scene.params)
    for key in getattr(scene, "overrides", {}) or {}:
        meta = scene.param_meta.get(key) or {}
        if "default" in meta:
            default_params[key] = meta["default"]
    try:
        default = parse_value(expression, default_params, scene.vars, scene.functions)
        default = float(default) if isinstance(default, (int, float)) and not isinstance(default, bool) else float(value)
        if not math.isfinite(default):
            default = float(value)
    except Exception:
        default = float(value)
    meta = dict(scene.param_meta.get(name) or {})
    meta.update({"label": meta.get("label", name), "default": default,
                 "derived": True, "read_only": True, "expression": expression})
    scene.params[name] = float(value)
    scene.param_meta[name] = meta
    record = {"name": name, "expression": expression, "value": float(value),
              "default": default, "line": int(cmd.line)}
    scene.dimension_links.append(record)
    scene.log("info", f"связанный размер {name} = {float(value):g} ({expression})", cmd.line)


def _preset(scene, cmd) -> None:
    kwargs = dict(cmd.kwargs or {})
    args = list(cmd.args or [])
    name = str(kwargs.pop("name", "") or kwargs.pop("имя", "") or "").strip().strip("\"'")
    if not name and args:
        name = str(args.pop(0)).strip().strip("\"'")
    delete = kwargs.pop("delete", None)
    if delete is not None:
        key = str(_value(scene, delete)).strip()
        if key not in scene.presets:
            raise DslError(f"Preset «{key}» не найден.", line=cmd.line)
        del scene.presets[key]
        scene.log("info", f"preset {key}: удалён", cmd.line)
        return
    save = kwargs.pop("save", None)
    apply = kwargs.pop("apply", None)
    if save is not None:
        name = str(_value(scene, save)).strip() or name
        values = {key: float(value) for key, value in scene.params.items()
                  if isinstance(value, (int, float)) and not isinstance(value, bool)}
        if not name:
            raise DslError("preset save: укажите имя.", line=cmd.line)
        scene.presets[name] = values
        scene.log("info", f"preset {name}: сохранено значений {len(values)}", cmd.line)
        return
    if apply is not None:
        name = str(_value(scene, apply)).strip() or name
    values: dict[str, float] = {}
    for key, raw in kwargs.items():
        if key in _META:
            continue
        values[key] = _number(scene, raw, f"preset.{key}")
    if not name:
        raise DslError("preset: укажите имя, например preset tall height=120.", line=cmd.line)
    if values:
        # Декларация — только вариант для панели. Иначе несколько presets
        # подряд неявно применялись бы все, а последняя молча побеждала.
        scene.presets[name] = dict(values)
        scene.log("info", f"preset {name}: объявлен набор ({len(values)} значений)", cmd.line)
        if apply is None:
            return
    elif name not in scene.presets:
        raise DslError(f"Preset «{name}» не найден и не содержит значений.", line=cmd.line)
    selected = scene.presets[name]
    for key, value in selected.items():
        scene.params[key] = float(getattr(scene, "overrides", {}).get(key, value))
        if key in scene.param_meta:
            # Текущее значение меняется, default preset не затирает.
            scene.param_meta[key].setdefault("label", key)
    scene.log("info", f"preset {name}: применены параметры "
              + ", ".join(f"{key}={value:g}" for key, value in selected.items()), cmd.line)


def _precision(scene, cmd) -> None:
    kwargs = dict(cmd.kwargs or {})
    args = list(cmd.args or [])
    mode = str(kwargs.get("mode") or (args[0] if args else "") or "").strip().lower()
    if mode in {"default", "old", "legacy", "старая", "обычная", "совместимость"}:
        mode = "legacy"
    elif mode in {"high", "fine", "точная", "высокая"}:
        mode = "fine"
    elif mode in {"ultra", "максимальная"}:
        mode = "ultra"
    elif mode in {"draft", "черновая", "быстрая"}:
        mode = "draft"
    factors = {"legacy": 1.0, "fine": 1.5, "ultra": 2.0, "draft": 0.75}
    if mode and mode not in factors:
        # precision 1.75 — короткая форма пользовательского множителя.
        try:
            factor = float(mode)
            mode = "custom"
        except ValueError as exc:
            raise DslError("precision: mode=legacy|draft|fine|ultra или factor=число.",
                           line=cmd.line) from exc
    else:
        factor = factors.get(mode, 1.0)
    if "factor" in kwargs:
        factor = _number(scene, kwargs["factor"], "precision.factor")
        mode = "custom"
    if not math.isfinite(factor) or factor <= 0 or factor > 16:
        raise DslError("precision.factor должен быть конечным числом в диапазоне 0…16.", line=cmd.line)
    settings = dict(scene.settings.get("precision") or {})
    settings.update({"mode": mode or settings.get("mode", "legacy"), "factor": float(factor)})
    if "tolerance" in kwargs:
        tolerance = _number(scene, kwargs["tolerance"], "precision.tolerance")
        if tolerance <= 0:
            raise DslError("precision.tolerance должен быть больше нуля.", line=cmd.line)
        settings["tolerance"] = tolerance
    scene.settings["precision"] = settings
    scene.log("info", f"глобальная точность: {settings['mode']}, множитель {factor:g}; "
              "явные detail/segments сохранены", cmd.line)


def _form_preset(scene, cmd) -> None:
    """Объявляет пресет формы: ``пресет_формы "плита" box size=[200,100,12]``.

    Пресет живёт в сценарии и никуда не копируется: панель читает объявление и
    применяет его к строке объекта обычной правкой ``set_params``. Значения
    хранятся как написаны (в тексте), чтобы выражение ``R/2`` не превращалось в
    число на этапе объявления.
    """
    from .values import split_top_level

    tokens = split_top_level(cmd.rest or "")
    words = [token for token in tokens[1:]]
    if len(words) < 2:
        raise DslError("Формат: пресет_формы \"имя\" операция key=значение …",
                       line=cmd.line, command=cmd.text)
    name = str(words[0]).strip().strip("\"'")
    op = str(words[1]).strip().lower()
    from .ops import lookup

    spec = lookup(op)
    if spec is None:
        raise DslError(f"Пресет формы: неизвестная операция «{words[1]}».", line=cmd.line,
                       command=cmd.text)
    changes: dict[str, str] = {}
    for token in words[2:]:
        key, _, raw = token.partition("=")
        key = key.strip()
        if not key or not raw.strip():
            raise DslError(f"Пресет формы: ожидалось key=значение, получено «{token}».",
                           line=cmd.line, command=cmd.text)
        if key not in spec.params:
            raise DslError(f"У {spec.name} нет параметра «{key}».", line=cmd.line,
                           command=cmd.text)
        changes[key] = raw.strip()
    if not changes:
        raise DslError("Пресет формы: не задано ни одного значения.", line=cmd.line,
                       command=cmd.text)
    items = scene.form_presets.setdefault(spec.name, [])
    items[:] = [item for item in items if item.get("name") != name]
    items.append({"name": name, "op": spec.name, "changes": changes,
                  "line": cmd.line, "user": True})
    scene.log("info", f"пресет формы «{name}» для {spec.name}: "
              + ", ".join(f"{key}={value}" for key, value in changes.items()), cmd.line)


def handle_special(scene, cmd) -> bool:
    """Выполняет команду с произвольными именами параметров до Args allowlist."""
    verb = (cmd.verb or "").lower()
    if verb not in _SPECIAL:
        return False
    if verb in {"param", "parameter", "параметр"}:
        _param(scene, cmd)
    elif verb in {"preset", "пресет", "набор"}:
        _preset(scene, cmd)
    elif verb in {"form_preset", "пресет_формы", "shape_preset", "пресет_фигуры"}:
        _form_preset(scene, cmd)
    elif verb in {"derive", "link", "связать", "связь", "зависимость"}:
        _derive(scene, cmd)
    else:
        _precision(scene, cmd)
    return True


# Записи в справочнике; исполнение перехватывается выше, поэтому произвольные
# height=/width= в preset не отбрасываются общим Args allowlist.
@op("param", aliases=("parameter", "параметр"), category="Сцена и материал",
    summary="Объявляет параметр панели: default, min, max, step, label, group.",
    example="param height=95 min=20 max=200 step=1 label=\"Высота\"",
    params={"default": "начальное значение", "min": "минимум", "max": "максимум",
            "step": "шаг", "label": "подпись"}, positional="*")
def param_command(a, name):  # pragma: no cover - dispatch выполняет handle_special
    return None


@op("derive", aliases=("link", "связать", "связь", "зависимость"), category="Сцена и материал",
    summary="Связывает размер с выражением; зависимое значение пересчитывается при rebuild.",
    example="base_h = 68\ncolumn_h = derive base_h * 1.25\n"
            "column_top = derive base_h + column_h",
    params={"expr": "выражение от других размеров или height(деталь)",
            "from": "синоним expr"}, positional="*")
def derive_command(a, name):  # pragma: no cover - dispatch выполняет handle_special
    return None


@op("form_preset", aliases=("пресет_формы", "shape_preset", "пресет_фигуры"),
    category="Сцена и материал",
    summary="Объявляет пресет формы для операции: значения её параметров. "
            "Применяется к строке объекта одной правкой, в геометрию не входит.",
    example='пресет_формы "плита" box size=[200,100,12]\n'
            'пресет_формы "стакан" cylinder wall=3 cavity=верх',
    params={"имя": "название пресета в кавычках",
            "операция": "box, cylinder, sphere …",
            "key=значение": "значения параметров этой операции"},
    positional="*")
def form_preset_command(a, name):  # pragma: no cover - dispatch выполняет handle_special
    return None


@op("preset", aliases=("пресет", "набор"), category="Сцена и материал",
    summary="Объявляет набор значений; preset имя или apply явно выбирает его.",
    example="preset tall height=140 width=60\npreset tall",
    params={"name": "имя набора", "save": "сохранить текущие", "apply": "применить"},
    positional="*")
def preset_command(a, name):  # pragma: no cover
    return None


@op("precision", aliases=("точность", "quality", "качество"), category="Сцена и материал",
    summary="Глобальная детализация opt-in; legacy сохраняет старое поведение.",
    example="precision mode=fine\nprecision mode=legacy",
    params={"mode": "legacy, draft, fine, ultra", "factor": "пользовательский множитель",
            "tolerance": "допуск по умолчанию, мм"}, positional="*")
def precision_command(a, name):  # pragma: no cover
    return None
