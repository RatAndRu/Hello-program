"""Построение сцены по тексту сценария и подготовка результата для интерфейса."""

from __future__ import annotations

import hashlib
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
from . import ops_curves  # noqa: F401,E402
from . import ops_shape  # noqa: F401,E402
from . import ops_scene  # noqa: F401,E402
from . import ops_sdf  # noqa: F401,E402
from . import ops_human  # noqa: F401,E402
from . import ops_studio  # noqa: F401,E402
from . import ops_io  # noqa: F401,E402
from . import ops_extra  # noqa: F401,E402


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
                                   animations=list(scene.animations) if scene else None)
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
                "kind": solid.kind,
                "op": solid.op,
                "line": solid.line,
                "tris": st["tris"],
                "verts": st["verts"],
                "volume_cm3": round(st["volume"] / 1000.0, 3),
                "mass_g": round(st["volume"] / 1000.0 * solid.density, 2),
                "bbox": st["bbox"],
                "size": st["size"],
                "genus": st["genus"],
                "tex": ({"kind": solid.tex.get("kind"), "label": solid.tex.get("label"),
                         "scale": solid.tex.get("scale"),
                         "relief": solid.tex.get("relief"),
                         "pattern": solid.tex.get("pattern"),
                         "color1": solid.tex.get("color1"),
                         "color2": solid.tex.get("color2")}
                        if getattr(solid, "tex", None) else None),
                "uv": getattr(solid, "uv", "cylinder"),
            })
        return out

    def frames(self) -> list[dict]:
        """Кадры сборки: шаги сценария, после которых менялась видимая модель."""
        out = []
        prev = None
        for step in self.steps:
            sig = (tuple(step.get("objects") or []), step.get("ops"))
            if not step.get("objects") or sig == prev:
                continue
            prev = sig
            out.append({**step, "frame": len(out) + 1})
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
            "timeline": plan,
            "steps": self.steps,
            "frames": frames,
            "upto": self.upto,
            "empty": self.empty,
        }
        return payload


def _hash(script: str) -> str:
    return hashlib.sha1(script.encode("utf-8")).hexdigest()[:12]


def _handle_let(scene: Scene, cmd) -> None:
    if cmd.kwargs:
        name, raw = next(iter(cmd.kwargs.items()))
    elif len(cmd.args) >= 2:
        name, raw = cmd.args[0], " ".join(cmd.args[1:])
    else:
        raise DslError("Формат: let имя = значение", line=cmd.line, command=cmd.text)
    if not name.isidentifier():
        raise DslError(f"Недопустимое имя параметра «{name}».", line=cmd.line, command=cmd.text)
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
        "line": cmd.line,
        "text": cmd.text,
    })
    scene.log("info", f"проверка: {target} {rule}", cmd.line)


def _execute(scene: Scene, cmd) -> None:
    scene.line = cmd.line
    scene.command = cmd.text
    verb_raw = cmd.verb or ""
    verb = verb_raw.lower()

    if verb == "let":
        _handle_let(scene, cmd)
        return

    spec = lookup(verb)
    if spec is None and cmd.target:
        # строка вида  height = 95  или  точки = [[0,0],[40,0]]  или  имя = "Кружка"
        raw = (cmd.rest or "").strip()
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
          upto: int | None = None, analyze_model: bool = True) -> Build:
    """Собирает сцену. ``upto`` — остановиться после N-й команды (кадр сборки)."""
    started = time.perf_counter()
    script = script or ""
    result = Build(script=script, script_hash=_hash(script), upto=upto)
    scene = Scene()
    result.scene = scene
    t_parse = time.perf_counter()
    try:
        commands = parse_script(script)
        if not commands:
            raise DslError("Сценарий пуст. Начните с команды, например: шар = sphere radius=50")
    except FormaError as exc:
        result.error = exc.to_dict()
        result.scene = None
        result.log = []
        result.timings = {"parse": time.perf_counter() - t_parse}
        return result
    parse_time = time.perf_counter() - t_parse

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
            if upto is not None:
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


def commands_help() -> list[dict]:
    return help_list()


def selftest() -> dict:
    from .selftest import run_selftest
    return run_selftest()
