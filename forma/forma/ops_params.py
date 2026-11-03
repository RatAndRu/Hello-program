"""Параметры, presets и глобальная точность — команды без отдельного движка."""
from __future__ import annotations

import math
from typing import Any

from .errors import DslError
from .ops import op
from .values import parse_value

_SPECIAL = {"param", "parameter", "параметр", "preset", "пресет", "набор",
            "precision", "точность", "quality", "качество"}
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


def handle_special(scene, cmd) -> bool:
    """Выполняет команду с произвольными именами параметров до Args allowlist."""
    verb = (cmd.verb or "").lower()
    if verb not in _SPECIAL:
        return False
    if verb in {"param", "parameter", "параметр"}:
        _param(scene, cmd)
    elif verb in {"preset", "пресет", "набор"}:
        _preset(scene, cmd)
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
