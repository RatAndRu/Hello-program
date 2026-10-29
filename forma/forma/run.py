"""Построение сцены по тексту сценария и подготовка результата для интерфейса."""

from __future__ import annotations

import hashlib
import re
import time
import traceback
from dataclasses import dataclass, field

from . import ops as _ops_pkg  # noqa: F401  (реестр команд)
from .checks import evaluate_checks
from .errors import DslError, FormaError, GeometryError
from .model import Scene
from .ops import OPS, help_list, lookup, suggest
from .dsl import Args, command_value, parse_script
from .geometry import export_glb
from .metrics import analyze
from .values import numeric_issue, parse_value

# регистрируем команды
from . import ops_basic  # noqa: F401,E402
from . import ops_cavity  # noqa: F401,E402
from . import ops_curves  # noqa: F401,E402
from . import ops_shape  # noqa: F401,E402
from . import ops_scene  # noqa: F401,E402
from . import ops_sdf  # noqa: F401,E402
from . import ops_skeleton  # noqa: F401,E402
from . import ops_human  # noqa: F401,E402
from . import ops_studio  # noqa: F401,E402
from . import ops_io  # noqa: F401,E402
from . import ops_extra  # noqa: F401,E402
from . import ops_inspect  # noqa: F401,E402
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


# Команды, которые не меняют ни форму, ни видимость: в анимации сборки
# им делать нечего — пользователь смотрит детали, а не отчёт о проверках.
FRAME_SKIP_VERBS = {
    "check", "gap", "clearance", "probe", "passport", "note", "param", "help",
    "version", "save", "load", "light", "color", "scene", "comment", "info",
    "сетка", "interference", "пересечения", "коллизии", "collision_report",
}


def _part_count(manifold) -> int:
    try:
        return 0 if manifold.is_empty() else len(manifold.decompose())
    except Exception:
        return 0


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
    upto: int | None = None
    empty: bool = False
    _glb: bytes | None = None
    _glb_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.scene is not None and self.error is None

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
                                   metadata={key: scene.settings.get(key)
                                             for key in ("copyright", "license", "source")
                                             if scene and scene.settings.get(key)})
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
            })
        return out

    def frames(self) -> list[dict]:
        """Кадры сборки: шаги сценария, после которых менялась видимая модель.

        Служебные команды (проверки, цвет, свет, параметры, заметки) форму не
        меняют — в кадры они не попадают, иначе анимация «стоит» на проверках.
        """
        out = []
        prev = None
        prev_names: set[str] = set()
        for step in self.steps:
            if (step.get("verb") or "").lower() in FRAME_SKIP_VERBS:
                continue
            sig = (tuple(step.get("objects") or []), step.get("ops"))
            if not step.get("objects") or sig == prev:
                continue
            prev = sig
            names = list(step.get("objects") or [])
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
            "objects": [] if light else self.objects_payload(),
            "params": dict(scene.params) if scene else {},
            "analysis": self.analysis,
            "timings": self.timings,
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
            "grid": getattr(scene, "grid", None) if scene else None,
            "steps": self.steps,
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
}


def _measure(name: str, obj: str, scene: Scene) -> float:
    name = name.lower()
    aliases = {"высота_об": "height", "ширина_об": "width", "объём": "volume",
               "объем": "volume", "верх": "top", "низ": "bottom", "лево": "left",
               "право": "right", "ширина": "width", "высота": "height",
               "глубина": "depth", "толщина": "depth",
               "центр_масс_x": "mx", "центр_масс_y": "my", "центр_масс_z": "mz",
               "mass_x": "mx", "mass_y": "my", "mass_z": "mz"}
    name = aliases.get(name, name)
    target = (obj or "").strip().strip("\"'")
    if not target:
        raise DslError(f"Функции {name}() нужно имя объекта: {name}(кружка)",
                       line=scene.line, command=scene.command)
    solid = scene.resolve(target)
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
    if name in getattr(scene, "overrides", {}):
        value = float(scene.overrides[name])
        scene.params[name] = value
        scene.log("info", f"параметр {name} = {value:g} (морфинг)", cmd.line)
        return
    raw = _substitute_measures(raw, scene)
    value = parse_value(raw, scene.params)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DslError(f"Параметр «{name}» должен быть числом, получено «{value}».",
                       line=cmd.line, command=cmd.text)
    scene.params[name] = float(value)
    scene.log("info", f"параметр {name} = {value:g}", cmd.line)


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


def _execute(scene: Scene, cmd) -> None:
    scene.line = cmd.line
    scene.command = cmd.text
    verb_raw = cmd.verb or ""
    verb = verb_raw.lower()
    # меры (top, height, volume…) — до разбора параметров, в любой команде
    _apply_measures(cmd, scene)

    if verb == "let":
        _handle_let(scene, cmd)
        return

    spec = lookup(verb)
    if spec is None and cmd.target:
        # морфинг: значение параметра подменяется при сборке кадра
        if cmd.target in getattr(scene, "overrides", {}):
            value = float(scene.overrides[cmd.target])
            scene.params[cmd.target] = value
            scene.log("info", f"параметр {cmd.target} = {value:g} (морфинг)", cmd.line)
            return
        # строка вида  height = 95  или  точки = [[0,0],[40,0]]  или  имя = "Кружка"
        raw = (cmd.rest or "").strip()
        raw = _substitute_measures(raw, scene)
        value = parse_value(raw, scene.params, scene.vars)
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        parsed_ok = not (isinstance(value, str) and value == raw)
        if is_number:
            scene.params[cmd.target] = float(value)
            scene.log("info", f"параметр {cmd.target} = {value:g}", cmd.line)
            return
        if not parsed_ok:
            reason = numeric_issue(raw, scene.params)
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
    try:
        result = spec.fn(args, cmd.target)
    except FormaError as exc:
        if exc.line is None:
            exc.line = cmd.line
        if exc.command is None:
            exc.command = cmd.text
        raise
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
    scene.log("info", f"{spec.name}: готово", cmd.line)


def build(script: str, previous_analysis: dict | None = None,
          upto: int | None = None, analyze_model: bool = True,
          overrides: dict | None = None) -> Build:
    """Собирает сцену. ``upto`` — остановиться после N-й команды (кадр сборки).

    ``overrides`` подменяет числовые параметры сценария (R = 42) — так строится
    морфинг: одна и та же модель с разными значениями параметра.
    """
    started = time.perf_counter()
    script = script or ""
    result = Build(script=script, script_hash=_hash(script), upto=upto)
    scene = Scene()
    scene.overrides = dict(overrides or {})
    for key, value in (overrides or {}).items():
        try:
            scene.params[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    result.scene = scene
    t_parse = time.perf_counter()
    try:
        commands = parse_script(script)
    except FormaError as exc:
        result.error = exc.to_dict()
        result.scene = None
        result.log = []
        result.timings = {"parse": time.perf_counter() - t_parse}
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
            _execute(scene, cmd)
            try:
                names = [solid.name for solid in scene.visible_solids()]
            except Exception:
                names = []
            result.steps.append({"n": index + 1, "line": cmd.line, "text": cmd.text,
                                 "verb": (cmd.verb or "").lower(),
                                 "target": cmd.target or "",
                                 "objects": names, "ops": scene.op_count})
        visible = scene.visible_solids()
        if not visible:
            if not scene.objects:
                # все объекты удалены — честная пустая сцена
                result.empty = True
            elif upto is not None:
                # кадр сборки до первого объекта — это нормально, покажем пустую сцену
                result.empty = True
            elif scene.objects:
                raise DslError("Все объекты скрыты — покажите нужный командой show.",
                               hint="Например: show корпус")
            else:
                raise DslError("В сцене нет видимых объектов.")
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
    return help_list()


def selftest() -> dict:
    from .selftest import run_selftest
    return run_selftest()
