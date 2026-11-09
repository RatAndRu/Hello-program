"""Построение сцены по тексту сценария и подготовка результата для интерфейса."""

from __future__ import annotations

import hashlib
import re
import time
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__ as _FORMA_VERSION
from . import ops as _ops_pkg  # noqa: F401  (реестр команд)
from .checks import evaluate_checks
from .errors import DslError, FormaError, GeometryError
from .model import Scene
from .ops import OPS, help_list, lookup, suggest
from .dsl import Args, command_value, parse_script
from .library import (bind_module_values, clone_functions, evaluate_call_text,
                      expand_includes, parse_program, register_definitions)
from .provenance import record_execution, record as record_provenance
from .geometry import export_glb
from .face_visibility import roles_payload
from .metrics import analyze
from .values import numeric_issue, parse_value

# регистрируем команды
from . import ops_basic  # noqa: F401,E402
from . import ops_cavity  # noqa: F401,E402
from . import ops_contour  # noqa: F401,E402
from . import ops_curves  # noqa: F401,E402
from . import ops_shape  # noqa: F401,E402
from . import ops_scene  # noqa: F401,E402
from . import ops_sdf  # noqa: F401,E402
from . import ops_skeleton  # noqa: F401,E402
from . import ops_human  # noqa: F401,E402
from . import ops_studio  # noqa: F401,E402
from . import ops_io  # noqa: F401,E402
from . import ops_scad  # noqa: F401,E402
from . import ops_extra  # noqa: F401,E402
from . import ops_inspect  # noqa: F401,E402
from . import ops_face_roles  # noqa: F401,E402
from . import ops_text  # noqa: F401,E402
from . import ops_tech  # noqa: F401,E402
from . import ops_shapes  # noqa: F401,E402
from . import ops_form  # noqa: F401,E402
from . import ops_glyphs  # noqa: F401,E402
from . import ops_surface  # noqa: F401,E402
from . import ops_blade  # noqa: F401,E402
from . import ops_sheet  # noqa: F401,E402
from . import ops_figure  # noqa: F401,E402
from . import ops_hardware  # noqa: F401,E402
from . import ops_fittings  # noqa: F401,E402
from . import ops_containers  # noqa: F401,E402
from . import ops_kit  # noqa: F401,E402
from . import ops_assembly  # noqa: F401,E402
from . import ops_parts  # noqa: F401,E402
from . import ops_fill  # noqa: F401,E402
from . import ops_interior  # noqa: F401,E402
from . import ops_sculpt  # noqa: F401,E402
from . import ops_grid  # noqa: F401,E402
from . import ops_hair  # noqa: F401,E402
from . import ops_face  # noqa: F401,E402
from . import ops_fold  # noqa: F401,E402
from . import ops_origami  # noqa: F401,E402
from . import ops_chain  # noqa: F401,E402
from . import ops_graded  # noqa: F401,E402
from . import ops_mount  # noqa: F401,E402
from . import ops_attach  # noqa: F401,E402
from . import ops_vessel  # noqa: F401,E402
from . import ops_solids  # noqa: F401,E402
from . import ops_barrel  # noqa: F401,E402
from . import ops_mech  # noqa: F401,E402
from . import ops_ribbon  # noqa: F401,E402
from . import ops_structures  # noqa: F401,E402
from . import ops_orient  # noqa: F401,E402
from . import ops_eye  # noqa: F401,E402
from . import ops_web  # noqa: F401,E402
from . import ops_organic  # noqa: F401,E402
from . import ops_params  # noqa: F401,E402
from .ops_params import handle_special


# Команды, которые не меняют ни форму, ни видимость: в анимации сборки
# им делать нечего — пользователь смотрит детали, а не отчёт о проверках.
FRAME_SKIP_VERBS = {
    "check", "gap", "clearance", "probe", "passport", "note", "param", "help",
    "version", "save", "load", "light", "color", "scene", "comment", "info",
    "сетка", "interference", "пересечения", "коллизии", "collision_report",
    "faces", "полигоны", "грани", "разметка_граней", "разметка_полигонов",
    "preset", "пресет", "набор", "precision", "точность", "quality", "качество",
    "derive", "link", "связать", "связь", "зависимость",
    "__forma_definition", "module", "модуль", "function", "функция",
}

# Эти команды могут менять группу in-place, не увеличивая Scene.op_count.
# Если не сохранить такой шаг, сборка перескакивает через перемещение/поворот
# всей группы и показывает ложную паузу на прежней геометрии.
FRAME_IN_PLACE_VERBS = {"translate", "rotate", "scale"}


def _part_count(manifold) -> int:
    try:
        return 0 if manifold.is_empty() else len(manifold.decompose())
    except Exception:
        return 0


def _affected_names(scene: Scene, cmd) -> list[str]:
    """Имена деталей, к которым относится команда (включая членов группы).

    ``target`` у ``translate [группа]`` пуст, поэтому одного поля target
    недостаточно для подсветки кадра. Разбираем только первый позиционный
    аргумент и не делаем геометрических вычислений.
    """
    candidates: list[str] = []
    if cmd.target:
        candidates.append(str(cmd.target))
    if cmd.args:
        try:
            value = parse_value(cmd.args[0], scene.params, scene.vars)
            values = value if isinstance(value, (list, tuple)) else [value]
            candidates.extend(v.strip() for v in values if isinstance(v, str))
        except Exception:
            pass
    out: list[str] = []
    for name in candidates:
        names = scene.groups.get(name, [name])
        for member in names:
            if member in scene.objects and member not in out:
                out.append(member)
    return out


@dataclass
class Build:
    script: str = ""
    scene: Scene | None = None
    analysis: dict | None = None
    error: dict | None = None
    timings: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    script_hash: str = ""
    steps: list = field(default_factory=list)
    # Независимый от кадров сборки профиль: одна запись на каждую исполненную
    # DSL-команду, включая команду, завершившуюся ошибкой. В отличие от steps
    # сюда попадают также проверки, параметры и служебные операции.
    command_timings: list = field(default_factory=list)
    upto: int | None = None
    empty: bool = False
    overrides: dict = field(default_factory=dict)
    _glb: bytes | None = None
    _glb_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.scene is not None and self.error is None

    @property
    def variant_hash(self) -> str:
        # GLB зависит не только от текста и overrides, но и от geometry/exporter
        # версии. Иначе обновление программы оставляет прежний URL и старый
        # кэш может выглядеть как свежая сборка того же сценария.
        raw = (self.script + "\n" + repr(sorted(self.overrides.items()))
               + "\nengine=" + str(_FORMA_VERSION))
        return _hash(raw)

    def commands(self) -> list[dict]:
        """Команды исходного текста со строками и смещениями токенов.

        Считается по ``self.script``, а не по развёрнутому сценарию: правится
        всегда тот файл, который пользователь открыл. Команды из include в этот
        список не попадают — их строки в исходнике нет.
        """
        from .edit import commands_payload

        if not hasattr(self, "_commands_cache"):
            self._commands_cache = commands_payload(self.script)
        return self._commands_cache

    def command_presets(self) -> dict:
        """Пресеты формы для строк сценария: ``{строка: [{name, label, changes}]}``."""
        from .param_spec import presets_for

        out: dict[str, list] = {}
        for command in self.commands():
            items = presets_for(command.get("verb") or "", command.get("kwargs") or {})
            if items:
                out[str(command["line"])] = items
        return out

    def op_specs(self) -> dict:
        """Типы параметров для операций, которые реально есть в сценарии."""
        from .param_spec import payload as _spec_payload
        from .ops import lookup

        verbs: list[str] = []
        for command in self.commands():
            verb = (command.get("verb") or "").lower()
            if verb and verb not in verbs:
                verbs.append(verb)
        specs: dict[str, dict] = {}
        for verb in verbs:
            spec = lookup(verb)
            found = _spec_payload(verb, list(spec.params) if spec else None)
            if found:
                specs[verb] = found
        return specs

    def visible_solids(self):
        return self.scene.visible_solids() if self.scene else []

    def glb(self) -> bytes:
        if self._glb is None:
            if not self.ok:
                raise GeometryError("Модель не построена.")
            solids = self.visible_solids()
            if not solids:
                raise GeometryError("Нет видимых объектов для экспорта.")
            scene = self.scene
            self._glb = export_glb(solids,
                                   animation=scene.animation if scene else None,
                                   animations=list(scene.animations) if scene else None,
                                   keys=dict(scene.keys) if scene else None,
                                   groups=dict(scene.groups) if scene else None,
                                   metadata={
                                       "forma_variant": self.variant_hash,
                                       "forma_script": self.script_hash,
                                       **({key: scene.settings.get(key)
                                           for key in ("copyright", "license", "source")
                                           if scene and scene.settings.get(key)}),
                                   })
        return self._glb

    def objects_payload(self) -> list[dict]:
        out = []
        if not self.scene:
            return out
        for solid in self.scene.objects.values():
            st = solid.stats()
            out.append({
                "name": solid.name,
                "visible": solid.visible,
                "color": solid.color,
                "metal": solid.metal,
                "rough": solid.rough,
                "density": solid.density,
                "emissive": getattr(solid, "emissive", "") or "",
                "emissive_strength": getattr(solid, "emissive_strength", 1.0),
                "transmission": getattr(solid, "transmission", 0.0),
                "mirror": float(getattr(solid, "mirror", 0.0) or 0.0),
                "kind": solid.kind,
                "op": solid.op,
                "line": solid.line,
                "provenance": (getattr(solid, "meta", None) or {}).get("provenance"),
                "module": (getattr(solid, "meta", None) or {}).get("module"),
                "tris": st["tris"],
                "verts": st["verts"],
                "volume_cm3": round(st["volume"] / 1000.0, 3),
                "mass_g": round(st["volume"] / 1000.0 * solid.density, 2),
                "bbox": st["bbox"],
                "size": st["size"],
                # Матрица «мир ← деталь»: столбцы right/back/up. Нужна окну
                # для личных стрелок выделенного предмета, а не для новой панели.
                "axes": (getattr(solid, "meta", None) or {}).get("axes")
                        or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "genus": st["genus"],
                # Логические панели икосферы: ядро триангулирует квадраты и
                # соты, но исходная топология остаётся доступной отчёту и ИИ.
                "topology": (getattr(solid, "meta", None) or {}).get("topology"),
                "parts": _part_count(solid.manifold),
                "area_mm2": round(st["area"], 1),
                "tex": ({"kind": solid.tex.get("kind"), "label": solid.tex.get("label"),
                         "scale": solid.tex.get("scale"),
                         "relief": solid.tex.get("relief"),
                         "pattern": solid.tex.get("pattern"),
                         "color1": solid.tex.get("color1"),
                         "color2": solid.tex.get("color2")}
                        if getattr(solid, "tex", None) else None),
                "uv": getattr(solid, "uv", "cylinder"),
                "paint": list(getattr(solid, "paint", None) or []) or None,
                "brush": list(getattr(solid, "brush", None) or []) or None,
                "face_roles": roles_payload(solid),
            })
        return out

    def frames(self) -> list[dict]:
        """Кадры сборки: шаги сценария, после которых менялась видимая модель.

        Служебные команды (проверки, цвет, свет, параметры, заметки) форму не
        меняют — в кадры они не попадают, иначе анимация «стоит» на проверках.
        Команды hide/show/delete, наоборот, сохраняются: видимость — часть
        собираемой сцены, включая переход к полностью пустому кадру.
        """
        out = []
        prev = None
        prev_names: set[str] = set()
        for step in self.steps:
            raw_verb = (step.get("verb") or "").lower()
            spec = lookup(raw_verb)
            verb = spec.name if spec else raw_verb
            if verb in FRAME_SKIP_VERBS or raw_verb in FRAME_SKIP_VERBS:
                continue
            sig = (tuple(step.get("objects") or []), step.get("ops"))
            names = list(step.get("objects") or [])
            # In-place преобразование видимой детали принимаем даже при том же
            # op_count. Преобразование скрытой детали кадром не является:
            # иначе между видимыми шагами снова появляется ложная пауза.
            affected = set(step.get("affected") or [])
            in_place = verb in FRAME_IN_PLACE_VERBS and bool(affected.intersection(names))
            # Для остальных команд сравниваем только базовую сигнатуру. Иначе
            # специальная метка преобразования ошибочно делала animate кадром.
            # Пустой список тоже является состоянием сцены: hide/delete последнего
            # объекта должен получить кадр, иначе следующий show сливается со
            # старым кадром и зритель вообще не видит изменения видимости.
            changed = sig != prev
            if not changed and not in_place:
                continue
            if not names and prev is None and not in_place:
                # Не начинаем сборку с пустого служебного состояния. Пустой кадр
                # принимаем только после уже показанной геометрии (prev != None).
                continue
            prev = sig
            added = [n for n in names if n not in prev_names]
            removed = [n for n in prev_names if n not in names]
            prev_names = set(names)
            out.append({**step, "frame": len(out) + 1,
                        "added": added, "removed": removed})
        return out

    def payload(self, light: bool = False) -> dict:
        scene = self.scene
        frames = self.frames()
        plan = scene.animation_plan(len(frames)) if scene else {
            "clips": [], "duration": 0.0, "count": 0, "has": False,
            "kinds": [], "assembly": None}
        payload = {
            "ok": self.ok,
            "error": self.error,
            "script_hash": self.script_hash,
            "variant_hash": self.variant_hash,
            "overrides": dict(self.overrides),
            "objects": [] if light else self.objects_payload(),
            "params": dict(scene.params) if scene else {},
            "parameter_schema": scene.parameter_schema() if scene else [],
            "presets": {key: dict(value) for key, value in (scene.presets if scene else {}).items()},
            "provenance": list(getattr(scene, "provenance", []) or []) if scene else [],
            "contours": [item.to_dict() for item in scene.contours.values()] if scene else [],
            "analysis": self.analysis,
            "timings": self.timings,
            "cache": scene.op_cache.stats() if scene and getattr(scene, "op_cache", None) else {},
            "log": self.log,
            "settings": dict(scene.settings) if scene else {},
            "animation": scene.animation if scene else None,
            "animations": plan["clips"],
            "keys": plan.get("keys", []),
            "timeline": plan,
            "groups": {g: list(m) for g, m in (scene.groups if scene else {}).items()},
            "sections": _sections_payload(scene),
            "probes": list(getattr(scene, "probes", []) or []) if scene else [],
            "passports": list(getattr(scene, "passports", []) or []) if scene else [],
            "interferences": list(getattr(scene, "interferences", []) or []) if scene else [],
            "mates": list(getattr(scene, "mates", []) or []) if scene else [],
            "dimension_links": list(getattr(scene, "dimension_links", []) or []) if scene else [],
            "grid": getattr(scene, "grid", None) if scene else None,
            "steps": self.steps,
            "commands": self.commands(),
            "op_specs": self.op_specs(),
            "command_presets": self.command_presets(),
            "form_presets": {op: [dict(item) for item in items]
                             for op, items in (getattr(scene, "form_presets", {}) or {}).items()}
            if scene else {},
            "command_timings": self.command_timings,
            "frames": frames,
            "upto": self.upto,
            "empty": self.empty,
        }
        return payload


def _sections_payload(scene) -> list[dict]:
    """Сечения для интерфейса: контуры с ограничением числа точек."""
    if scene is None:
        return []
    try:
        import numpy as np

        from .cuts import polygons_payload
    except Exception:
        return []
    out = []
    for entry in getattr(scene, "sections", []) or []:
        out.append({
            "object": entry.get("object"),
            "plane": entry.get("plane"),
            "at": entry.get("at"),
            "layer": entry.get("layer"),
            "area": entry.get("area"),
            "outer": entry.get("outer"),
            "holes": entry.get("holes"),
            "bbox": entry.get("bbox"),
            "contours": polygons_payload(
                [{"points": np.asarray(c, dtype=float)}
                 for c in entry.get("contours") or []], max_points=200),
            "dxf": entry.get("dxf"),
            "svg": entry.get("svg"),
        })
    return out


def _hash(script: str) -> str:
    return hashlib.sha1(script.encode("utf-8")).hexdigest()[:12]


MEASURES = {
    "height": lambda bb, st: st["size"][2],
    "width": lambda bb, st: st["size"][0],
    "depth": lambda bb, st: st["size"][1],
    # длина — наибольший габарит: у лежащей доски это она сама, у стойки —
    # высота. Нужна, когда важно «в 1.5 раза длиннее», не думая об осях.
    "length": lambda bb, st: max(st["size"]),
    "длина": lambda bb, st: max(st["size"]),
    "volume": lambda bb, st: st["volume"] / 1000.0,
    "area": lambda bb, st: st["area"] / 100.0,  # см², как volume в см³
    "tris": None, "parts": None, "genus": None,
    "top": lambda bb, st: bb[5],
    "bottom": lambda bb, st: bb[2],
    "left": lambda bb, st: bb[0],
    "right": lambda bb, st: bb[3],
    "front": lambda bb, st: bb[1],
    "back": lambda bb, st: bb[4],
    "cx": lambda bb, st: (bb[0] + bb[3]) / 2,
    "cy": lambda bb, st: (bb[1] + bb[4]) / 2,
    "cz": lambda bb, st: (bb[2] + bb[5]) / 2,
    "высота_об": None, "ширина_об": None, "объём": None, "объем": None,
    "верх": None, "низ": None, "лево": None, "право": None,
    # центр массы: у тора и воронки центр габарита пустой, а центр массы — нет
    "mx": None, "my": None, "mz": None,
    "центр_масс": None, "центр_масс_x": None, "центр_масс_y": None,
    "центр_масс_z": None,
    # русские имена мерок: писать проще, чем вспоминать английские
    "ширина": None, "высота": None, "глубина": None, "толщина": None,
    "площадь": None, "треугольники": None, "части": None,
    "род": None, "отверстия": None,
}


def _measure(name: str, obj: str, scene: Scene) -> float:
    name = name.lower()
    aliases = {"высота_об": "height", "ширина_об": "width", "объём": "volume",
               "объем": "volume", "верх": "top", "низ": "bottom", "лево": "left",
               "право": "right", "ширина": "width", "высота": "height",
               "глубина": "depth", "толщина": "depth",
               "центр_масс_x": "mx", "центр_масс_y": "my", "центр_масс_z": "mz",
               "mass_x": "mx", "mass_y": "my", "mass_z": "mz",
               "площадь": "area", "треугольники": "tris", "части": "parts",
               "род": "genus", "отверстия": "genus"}
    name = aliases.get(name, name)
    target = (obj or "").strip().strip("\"'")
    if not target:
        raise DslError(f"Функции {name}() нужно имя объекта: {name}(кружка)",
                       line=scene.line, command=scene.command)
    if target in scene.contours:
        contour = scene.contours[target]
        measured = contour.measurements()
        if name in ("length", "длина"):
            return float(measured["length"])
        if name == "area":
            return float(measured["area"]) / 100.0
        raise DslError(f"Для Contour2D доступны length({target}) и area({target}).",
                       line=scene.line)
    solid = scene.resolve(target)
    if name == "tris":
        return float(solid.manifold.num_tri())
    if name == "parts":
        return float(len(solid.manifold.decompose()))
    if name == "genus":
        return float(solid.manifold.genus())
    if name in ("mx", "my", "mz"):
        from . import orient
        center = orient.mass_center(solid.manifold)
        return float(center["xyz".index(name[1])])
    fn = MEASURES.get(name)
    if fn is None:
        raise DslError(f"Неизвестная функция «{name}».", line=scene.line)
    stats = solid.stats()
    return float(fn(stats["bbox"], stats))


def _substitute_measures(raw: str, scene: Scene) -> str:
    """Подставляет height(кружка), top(крышка) … в числовое выражение."""
    if "(" not in raw:
        return raw
    pattern = re.compile(r"([A-Za-zА-Яа-яЁё_][\w]*)\s*\(\s*([^()]*?)\s*\)")
    out = raw
    for match in list(pattern.finditer(raw)):
        fn = match.group(1).lower()
        if fn not in MEASURES:
            continue
        value = _measure(fn, match.group(2), scene)
        out = out.replace(match.group(0), f"{value:.6f}", 1)
    return out


def _apply_measures(cmd, scene: Scene) -> None:
    """Подставляет меры вида top(кружка) во все параметры команды.

    Раньше это работало только в `let имя = …`. Поэтому понятная запись
    `at=[0, 0, top(кружка) + 2]` падала с «все элементы должны быть числами»,
    хотя язык умеет считать выражения. Теперь меры раскрываются до разбора
    параметров — в любом месте сценария.
    """
    for key, raw in list(cmd.kwargs.items()):
        if isinstance(raw, str) and "(" in raw:
            cmd.kwargs[key] = _substitute_measures(raw, scene)
    for i, raw in enumerate(cmd.args):
        if isinstance(raw, str) and "(" in raw:
            cmd.args[i] = _substitute_measures(raw, scene)


def _handle_let(scene: Scene, cmd) -> None:
    if cmd.kwargs:
        name, raw = next(iter(cmd.kwargs.items()))
    elif len(cmd.args) >= 2:
        name, raw = cmd.args[0], " ".join(cmd.args[1:])
    else:
        raise DslError("Формат: let имя = значение", line=cmd.line, command=cmd.text)
    if not name.isidentifier():
        raise DslError(f"Недопустимое имя параметра «{name}».", line=cmd.line, command=cmd.text)
    raw = _substitute_measures(raw, scene)
    parsed = parse_value(raw, scene.params, scene.vars, scene.functions)
    if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
        raise DslError(f"Параметр «{name}» должен быть числом, получено «{parsed}».",
                       line=cmd.line, command=cmd.text)
    default = float(parsed)
    overridden = name in getattr(scene, "overrides", {})
    value = float(scene.overrides[name]) if overridden else default
    scene.params[name] = value
    meta = scene.param_meta.setdefault(name, {"label": name, "default": default, "step": 0.1})
    meta.setdefault("default", default)
    scene.log("info", f"параметр {name} = {value:g}" + (" (морфинг)" if overridden else ""), cmd.line)


def _plain_solid(solid) -> bool:
    """Можно ли доверить кэшу только геометрию этой детали.

    Кэш возвращает сетку, а операция может оставить на объекте сведения о
    сборке (``meta``), покраску, мазки кисти, роли граней или разметку UV.
    Такие детали не кэшируются: повтор потерял бы не геометрию, а смысл.
    """
    for field in ("paint", "brush", "face_roles", "notes", "tex"):
        if getattr(solid, field, None):
            return False
    # axes и provenance вычисляются из строки сценария заново — их можно
    # потерять. Всё остальное в meta ставит сама операция (например «turn»
    # у повёрнутой лестницы) — такую деталь кэшировать нельзя.
    extra = set(getattr(solid, "meta", None) or {}) - {"axes", "provenance"}
    return not extra


def _handle_check(scene: Scene, cmd) -> None:
    if len(cmd.args) < 2:
        raise DslError("Формат проверки: check объект правило параметры",
                       hint="Например: check кружка height 90..110",
                       line=cmd.line, command=cmd.text)
    target, rule = cmd.args[0], cmd.args[1]
    if len(target) >= 2 and target[0] == target[-1] and target[0] in "\"'":
        target = target[1:-1]
    scene.checks.append({
        "target": target,
        "rule": rule,
        "args": cmd.args[2:],
        # именованные уточнения (x=, y=, z=, допуск=) — для проверки положения
        "kwargs": dict(cmd.kwargs or {}),
        "line": cmd.line,
        "text": cmd.text,
    })
    scene.log("info", f"проверка: {target} {rule}", cmd.line)


def _safe_value(value):
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return float(value)
    except Exception:
        return str(value)


def _invoke_module(scene: Scene, definition, cmd, positional, named) -> None:
    """Исполняет модуль в локальном Scene и переносит его обычные детали."""
    if scene.module_depth >= 32:
        raise DslError("Превышена глубина вызовов модулей (32); проверьте рекурсию.",
                       line=cmd.line, command=cmd.text)
    local_params, local_vars, values = bind_module_values(definition, positional, named, scene)
    child = Scene()
    child.base_dir = getattr(scene, "base_dir", None)
    child.settings = deepcopy(scene.settings)
    child.params = local_params
    child.vars = local_vars
    child.functions = clone_functions(scene.functions, child)
    child.modules = dict(scene.modules)
    child.definitions = dict(scene.definitions)
    child.overrides = dict(getattr(scene, "overrides", {}) or {})
    child.module_depth = scene.module_depth + 1
    child.vars["__forma_functions__"] = child.functions
    register_definitions(child, definition.definitions)
    try:
        for child_cmd in definition.commands:
            _execute(child, child_cmd)
    except FormaError as exc:
        suffix = f"модуль «{definition.name}», вызов на строке {cmd.line}"
        exc.hint = (str(exc.hint) + "; " if exc.hint else "") + suffix
        if exc.line is None:
            exc.line = cmd.line
        raise
    if not child.objects and not child.contours:
        raise DslError(f"Модуль «{definition.name}» не создал ни одного объекта.",
                       line=cmd.line, command=cmd.text)
    visible = child.visible_solids()
    base = (cmd.target or scene.unique_name(definition.name)).strip()
    if cmd.target and (base in scene.objects or base in scene.contours or base in scene.groups):
        raise DslError(f"Имя «{base}» уже занято.", line=cmd.line, command=cmd.text)
    root = visible[0] if len(visible) == 1 else None
    name_map: dict[str, str] = {}
    for solid in child.objects.values():
        candidate = base if solid is root else f"{base}__{solid.name}"
        if candidate in scene.objects or candidate in scene.contours or candidate in scene.groups:
            raise DslError(f"Модуль «{definition.name}»: имя «{candidate}» уже занято.",
                           line=cmd.line)
        name_map[solid.name] = candidate
    for contour_name in child.contours:
        candidate = f"{base}__{contour_name}"
        if candidate in scene.objects or candidate in scene.contours:
            raise DslError(f"Модуль «{definition.name}»: имя контура «{candidate}» уже занято.",
                           line=cmd.line)
        name_map[contour_name] = candidate
    # Переносим и скрытые исходники: они нужны picking/provenance так же, как
    # скрытые plate0/h1 в обычном сценарии. Это не геометрическое CAD-дерево.
    old_provenance = deepcopy(child.provenance)
    for old_name, new_name in name_map.items():
        solid = child.objects.get(old_name)
        if solid is None:
            continue
        solid.name = new_name
        solid.meta["module"] = definition.name
        solid.meta["module_args"] = _safe_value(values)
        passport = solid.meta.get("provenance")
        if passport:
            passport["parents"] = [name_map.get(p, p) for p in passport.get("parents", [])]
            passport["object"] = new_name
            passport["module"] = definition.name
        scene.add(solid)
    for old_name, contour in child.contours.items():
        contour.name = name_map[old_name]
        scene.contours[contour.name] = contour
    for group, members in child.groups.items():
        mapped = [name_map.get(member, member) for member in members if member in name_map]
        if mapped:
            group_name = f"{base}__{group}"
            scene.groups[group_name] = mapped
    if len(visible) > 1:
        scene.groups[base] = [name_map[solid.name] for solid in visible]
    for row in old_provenance:
        copied = dict(row)
        copied["object"] = name_map.get(row.get("object"), row.get("object"))
        copied["parents"] = [name_map.get(p, p) for p in row.get("parents", [])]
        copied["module"] = definition.name
        copied["call_line"] = cmd.line
        scene.provenance.append(copied)
    del scene.provenance[:-int(getattr(scene, "provenance_limit", 512))]
    # Вызов модуля виден отдельной строкой, но не заменяет паспорт последней
    # внутренней операции у одиночного результата.
    root_passport = deepcopy(root.meta.get("provenance")) if root is not None else None
    record_provenance(scene, base, "module", cmd.line, [], command=cmd.text,
                      extra={"module": definition.name, "arguments": _safe_value(values)})
    if root is not None and root_passport is not None:
        root.meta["provenance"] = root_passport
    scene.log("info", f"модуль {definition.name}: объектов {len(child.objects)}, "
              f"видимых {len(visible)}", cmd.line)


def _try_module(scene: Scene, cmd) -> bool:
    raw_verb = (cmd.verb or "").strip()
    name = ""
    positional: list = []
    named: dict = {}
    if "(" in raw_verb and raw_verb.endswith(")"):
        try:
            candidate, positional, named = evaluate_call_text(raw_verb, scene)
        except DslError:
            return False
        if candidate not in scene.modules:
            return False
        name = candidate
    elif raw_verb in scene.modules:
        name = raw_verb
        positional = [parse_value(raw, scene.params, scene.vars, scene.functions)
                      for raw in (cmd.args or [])]
        named = {key: parse_value(raw, scene.params, scene.vars, scene.functions)
                 for key, raw in (cmd.kwargs or {}).items()}
    if not name:
        return False
    _invoke_module(scene, scene.modules[name], cmd, positional, named)
    return True


def _execute(scene: Scene, cmd) -> None:
    scene.line = cmd.line
    scene.command = cmd.text
    verb_raw = cmd.verb or ""
    verb = verb_raw.lower()
    before_ids = {name: id(solid.manifold) for name, solid in scene.objects.items()}
    # меры (top, height, volume…) — до разбора параметров, в любой команде
    _apply_measures(cmd, scene)

    if verb == "__forma_definition":
        return
    if verb == "let":
        _handle_let(scene, cmd)
        return
    if handle_special(scene, cmd):
        return
    if _try_module(scene, cmd):
        return

    spec = lookup(verb)
    if spec is None and cmd.target:
        # Сначала читаем исходный default, затем применяем morph. Иначе reset
        # после overrides ошибочно считал текущее значение заводским default.
        raw = (cmd.rest or "").strip()
        raw = _substitute_measures(raw, scene)
        value = parse_value(raw, scene.params, scene.vars, scene.functions)
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if cmd.target in getattr(scene, "overrides", {}):
            default = float(value) if is_number else float(scene.overrides[cmd.target])
            value = float(scene.overrides[cmd.target])
            scene.params[cmd.target] = value
            meta = scene.param_meta.setdefault(
                cmd.target, {"label": cmd.target, "default": default, "step": 0.1})
            meta.setdefault("default", default)
            scene.log("info", f"параметр {cmd.target} = {value:g} (морфинг)", cmd.line)
            return
        # строка вида  height = 95  или  точки = [[0,0],[40,0]]  или  имя = "Кружка"
        parsed_ok = not (isinstance(value, str) and value == raw)
        if is_number:
            scene.params[cmd.target] = float(value)
            scene.param_meta.setdefault(cmd.target, {"label": cmd.target, "default": float(value), "step": 0.1})
            scene.log("info", f"параметр {cmd.target} = {value:g}", cmd.line)
            return
        if not parsed_ok:
            reason = numeric_issue(raw, scene.params, scene.functions)
            if reason:
                raise DslError(
                    f"Не удалось вычислить «{raw}»: {reason}.",
                    hint="Проверьте выражение: деление на ноль и корень из "
                         "отрицательного числа недопустимы.",
                    line=cmd.line, command=cmd.text)
        if parsed_ok:
            scene.vars[cmd.target] = value
            if isinstance(value, (list, tuple)):
                scene.log("info", f"набор {cmd.target}: {len(value)} элементов", cmd.line)
            else:
                scene.log("info", f"значение {cmd.target} = {value}", cmd.line)
            return
        suggestions = suggest(verb)
        hint = ("Возможно, вы имели в виду: " + ", ".join(suggestions)) if suggestions \
            else "Список команд — во вкладке «Справочник»."
        raise DslError(f"Неизвестная команда «{verb_raw}».", hint=hint,
                       line=cmd.line, command=cmd.text)

    if spec is None:
        suggestions = suggest(verb)
        hint = ("Возможно, вы имели в виду: " + ", ".join(suggestions)) if suggestions \
            else "Список команд — во вкладке «Справочник» или в README."
        raise DslError(f"Неизвестная команда «{verb_raw}».", hint=hint,
                       line=cmd.line, command=cmd.text)

    if spec.name == "check":
        _handle_check(scene, cmd)
        return

    args = Args(cmd, scene, spec, spec.positional)
    previous = scene.objects.get(cmd.target) if cmd.target else None
    scene.last_replaced = None
    # Кэш операций: ключ — слово, параметры как записаны, отпечаток параметров
    # сцены и точности. Команды, ссылающиеся на готовый объект, не кэшируются:
    # их результат зависит от входной геометрии (провенанс родителей).
    cache = getattr(scene, "op_cache", None)
    cache_key = None
    cached_manifold = None
    if cache is not None:
        from .cache import references_object, scene_digest

        # Позиционные аргументы тоже могут быть именами объектов
        # (difference [a, b]) — их обязательно проверять, иначе кэш вернёт
        # геометрию, посчитанную для другой входной фигуры.
        values = list(args.kwargs.values()) + list(args.extra or []) \
            + list(cmd.args or [])
        # Контуры и группы — тоже входная геометрия: extrude profile=э зависит
        # от допуска, с которым построен контур «э», а не от его имени.
        inputs = set(scene.objects) | set(scene.contours) | set(scene.groups)
        if not references_object(values, inputs):
            cache_key = cache.make_key(spec.name, args.kwargs, scene_digest(scene))
            cached_manifold = cache.get(cache_key)
    try:
        before_names = set(scene.objects)
        if cached_manifold is not None:
            # Регистрация — та же, что у операции: имя, цвет, ориентация.
            from .ops import make_solid

            result = make_solid(scene, cmd.target, cached_manifold, args)
            scene.log("debug", f"{spec.name}: геометрия из кэша", cmd.line)
        else:
            result = spec.fn(args, cmd.target)
            # Кэшируем только команды «одна фигура — один объект». Составные
            # операции (разъём, крепёж) создают ещё и подсборку, и повтор
            # только главной детали потерял бы остальные.
            added = set(scene.objects) - before_names
            if (cache_key is not None and result is not None and len(added) == 1
                    and getattr(result, "manifold", None) is not None
                    and _plain_solid(result)):
                cache.put(cache_key, getattr(result, "manifold", None))
    except FormaError as exc:
        if exc.line is None:
            exc.line = cmd.line
        if exc.command is None:
            exc.command = cmd.text
        raise
    from .contour import Contour2D
    if isinstance(result, Contour2D):
        contour_name = cmd.target or result.name
        if contour_name in scene.objects or contour_name in scene.contours:
            raise DslError(f"Имя контура «{contour_name}» уже занято.",
                           line=cmd.line, command=cmd.text)
        result.name = contour_name
        scene.contours[contour_name] = result
        scene.op_count += 1
        scene.log("info", f"Contour2D: {len(result.segments)} сегмента, "
                          f"допуск {result.tolerance:g} мм", cmd.line)
        return
    if result is not None and cmd.target and result.name != cmd.target:
        # страховка: переименование к целевому имени
        scene.remove(result.name)
        result.name = scene.unique_name(cmd.target)
        scene.add(result)
    if (previous is not None and cmd.target
            and scene.last_replaced is previous and previous.visible):
        # Новая деталь получила имя уже существующей — не затираем молча.
        raise DslError(
            f"Имя «{cmd.target}» уже занято другим объектом.",
            hint=f"Придумайте новое имя или удалите прежний объект: remove {cmd.target}",
            line=cmd.line, command=cmd.text)
    record_execution(scene, cmd, result, before_ids)
    scene.log("info", f"{spec.name}: готово", cmd.line)


def build(script: str, previous_analysis: dict | None = None,
          upto: int | None = None, analyze_model: bool = True,
          overrides: dict | None = None, base_dir: str | Path | None = None) -> Build:
    """Собирает сцену. ``upto`` — остановиться после N-й команды (кадр сборки).

    ``overrides`` подменяет числовые параметры сценария (R = 42) — так строится
    морфинг: одна и та же модель с разными значениями параметра.
    """
    started = time.perf_counter()
    script = script or ""
    result = Build(script=script, script_hash=_hash(script), upto=upto,
                   overrides=dict(overrides or {}))
    scene = Scene()
    from .cache import for_build

    scene.op_cache = for_build()
    scene.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None
    scene.overrides = dict(overrides or {})
    for key, value in (overrides or {}).items():
        try:
            scene.params[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    result.scene = scene
    t_parse = time.perf_counter()
    try:
        expanded = expand_includes(script, base_dir=base_dir)
        program = parse_program(expanded)
        commands = program.commands
        scene.definitions = program.definitions
        register_definitions(scene, program.definitions)
    except FormaError as exc:
        result.error = exc.to_dict()
        result.scene = None
        result.log = []
        result.timings = {
            "parse": round((time.perf_counter() - t_parse) * 1000, 1),
            "total": round((time.perf_counter() - started) * 1000, 1),
        }
        return result
    parse_time = time.perf_counter() - t_parse
    if not commands:
        # Пустой сценарий — это не ошибка, а чистая сцена: всё, что было
        # построено и применено, сбрасывается.
        result.empty = True
        result.analysis = empty_analysis()
        result.log = []
        result.timings = {"parse": round(parse_time * 1000, 1), "build": 0.0,
                          "total": round((time.perf_counter() - started) * 1000, 1)}
        return result

    build_start = time.perf_counter()
    limit = len(commands) if upto is None else max(0, min(int(upto), len(commands)))
    try:
        for index, cmd in enumerate(commands):
            if index >= limit:
                break
            command_started = time.perf_counter()
            spec = lookup(cmd.verb or "")
            status = "ok"
            try:
                _execute(scene, cmd)
            except Exception:
                status = "error"
                raise
            finally:
                result.command_timings.append({
                    "n": index + 1,
                    "line": cmd.line,
                    "verb": spec.name if spec else (cmd.verb or ""),
                    "raw_verb": cmd.verb or "",
                    "target": cmd.target or "",
                    "status": status,
                    "ms": round((time.perf_counter() - command_started) * 1000, 3),
                })
            try:
                names = [solid.name for solid in scene.visible_solids()]
            except Exception:
                names = []
            result.steps.append({"n": index + 1, "line": cmd.line, "text": cmd.text,
                                 "verb": (cmd.verb or "").lower(),
                                 "target": cmd.target or "",
                                 "affected": _affected_names(scene, cmd),
                                 "objects": names, "ops": scene.op_count})
        visible = scene.visible_solids()
        if not visible:
            if not scene.objects:
                if scene.contours and not scene.had_solids:
                    # Исходная сцена только из аналитических контуров валидна.
                    result.empty = True
                elif upto is not None or not analyze_model:
                    # Кадр до первого тела и служебная сцена без анализа —
                    # нормальный пустой предпросмотр (сетка, стиль, параметры).
                    result.empty = True
                else:
                    # Сохраняем прежний контракт: «удалить all» — ошибка сборки.
                    raise DslError("В сцене нет видимых объектов.")
            elif upto is not None:
                result.empty = True
            else:
                raise DslError("Все объекты скрыты — покажите нужный командой show.",
                               hint="Например: show корпус")
    except FormaError as exc:
        if exc.line is None:
            exc.line = scene.line
        result.error = exc.to_dict()
        result.log = scene.logs
        result.scene = None
        result.timings = {
            "parse": round(parse_time * 1000, 1),
            "build": round((time.perf_counter() - build_start) * 1000, 1),
            "total": round((time.perf_counter() - started) * 1000, 1),
        }
        return result
    except Exception as exc:  # внутренняя ошибка — не пугаем пользователя трассировкой
        result.error = {
            "message": f"Внутренняя ошибка построения: {exc}",
            "hint": "Проверьте параметры последней команды; если ошибка повторяется — сообщите разработчику.",
            "line": scene.line,
            "command": scene.command,
            "internal": True,
        }
        result.log = scene.logs
        result.log.append({"level": "error", "message": traceback.format_exc(), "line": scene.line})
        result.scene = None
        result.timings = {"total": round((time.perf_counter() - started) * 1000, 1)}
        return result

    build_time = time.perf_counter() - build_start
    if not analyze_model:
        result.log = scene.logs
        result.timings = {"parse": round(parse_time * 1000, 1),
                          "build": round(build_time * 1000, 1),
                          "total": round((time.perf_counter() - started) * 1000, 1)}
        return result
    if result.empty:
        result.analysis = empty_analysis()
        if scene.contours:
            result.analysis["text"] = (
                f"АНАЛИТИЧЕСКИЕ КОНТУРЫ: {len(scene.contours)}\n\n"
                "Твёрдых объектов пока нет. Используйте контур в extrude, lathe, loft или sweep.")
        result.log = scene.logs
        result.timings = {"parse": round(parse_time * 1000, 1),
                          "build": round(build_time * 1000, 1), "analysis": 0.0,
                          "total": round((time.perf_counter() - started) * 1000, 1)}
        return result
    analysis_start = time.perf_counter()
    try:
        analysis = analyze(scene, previous=previous_analysis)
    except Exception as exc:
        result.error = {
            "message": f"Модель построена, но анализ не удался: {exc}",
            "hint": "Попробуйте упростить модель или уменьшить число объектов.",
            "line": 0,
        }
        result.log = scene.logs
        result.scene = None
        result.timings = {
            "parse": round(parse_time * 1000, 1),
            "build": round(build_time * 1000, 1),
            "total": round((time.perf_counter() - started) * 1000, 1),
        }
        return result
    analysis_time = time.perf_counter() - analysis_start

    result.analysis = analysis
    result.log = scene.logs
    result.timings = {
        "parse": round(parse_time * 1000, 1),
        "build": round(build_time * 1000, 1),
        "analysis": round(analysis_time * 1000, 1),
        "total": round((time.perf_counter() - started) * 1000, 1),
    }
    return result


def empty_analysis() -> dict:
    """Отчёт для пустой сцены: нули вместо ошибки."""
    metrics = {"size": [0.0, 0.0, 0.0], "bbox": [0.0] * 6, "volume_cm3": 0.0,
               "mass_g": 0.0, "area_cm2": 0.0, "tris": 0, "verts": 0,
               "parts": 0, "genus": 0, "visible_count": 0, "total_count": 0,
               "density": 0.0, "wall": None, "flat_bottom_pct": 0.0,
               "overhang_pct": 0.0, "symmetry": {}}
    return {
        "metrics": metrics, "checks": [], "checks_passed": 0, "checks_total": 0,
        "warnings": [], "advice": [],
        "compare": None,
        "text": ("СЦЕНА ПУСТА\n\nВ сценарии нет ни одной команды.\n"
                 "Всё, что было построено, снято: объекты, цвета, текстуры, "
                 "проверки и анимации.\n\nНачните с команды, например:\n"
                 "  шар = sphere radius=50"),
    }


def commands_help() -> list[dict]:
    rows = help_list()
    # include/definitions обрабатываются до обычного op-dispatch, но должны
    # присутствовать в той же встроенной справке, а не только в docs.
    rows.extend([
        {"name": "include", "aliases": ["включить", "подключить"],
         "category": "Библиотеки Forma",
         "summary": "Подключает .forma/.f3d с защитой от циклов; .scad передаётся openscad.",
         "params": [{"name": "file", "desc": "путь к библиотеке относительно сценария"}],
         "example": "include file=\"lib/plates.forma\""},
        {"name": "function", "aliases": ["функция"], "category": "Библиотеки Forma",
         "summary": "Объявляет чистую числовую функцию с defaults и локальными аргументами.",
         "params": [{"name": "x, y=…", "desc": "позиционные и именованные аргументы"}],
         "example": "function plus(x, y=2) = x + y"},
        {"name": "module", "aliases": ["модуль"], "category": "Библиотеки Forma",
         "summary": "Объявляет переиспользуемый блок обычных команд Forma в локальном scope.",
         "params": [{"name": "width=…", "desc": "параметры и значения по умолчанию"}],
         "example": "module plate(width=40) {\n  body = box size=[width,20,3]\n}"},
    ])
    return rows


def selftest() -> dict:
    from .selftest import run_selftest
    return run_selftest()
