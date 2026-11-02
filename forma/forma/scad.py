"""Экспорт сцены ФОРМЫ в OpenSCAD (`.scad`) — мост между двумя языками.

Зачем: OpenSCAD — де-факто «SVG для 3D». У него огромная экосистема готовых
библиотек (BOSL2, dotSCAD, MCAD), редактор и Customizer с ползунками. Наша
сила в другом — метрики, проверки, профили печати. Вместо «или/или» отдаём
деталь в мир OpenSCAD, не теряя своего ядра.

Два режима, и они намеренно разные:

* ``mode="solid"`` (по умолчанию) — геометрия переносится **как есть**:
  каждый видимый объект становится `polyhedron(points, faces)`. Работает для
  любой из 227 команд, объём и число треугольников совпадают с ядром до
  последнего знака. Файл нечитаемый, зато всегда верный.
* ``mode="script"`` — сценарий переводится **по командам**: `box` → `cube`,
  `cylinder` → `cylinder`, `difference` → `difference()`, `translate` →
  `translate()`. Получается параметрический `.scad`, который человек может
  править руками и подключать к своим библиотекам. Что не перевелось —
  подменяется `polyhedron` этого объекта, и в файле остаётся комментарий.

Позиции берутся не из догадок, а из ядра: каждая примитивная команда
строится отдельно, и её центр габарита переносится в `translate([...])`.
Поэтому «где стоит деталь» в двух системах совпадает.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .dsl import parse_script
from .geometry import manifold_mesh

__all__ = ["scad_solid", "scad_script", "export_scad"]

#: команды, которые переводятся в родные операторы OpenSCAD
_PRIMS = {
    "box": "cube", "cube": "cube",
    "cylinder": "cylinder", "sphere": "sphere", "cone": "cone",
    "prism": "prism", "pyramid": "pyramid", "sheet": "sheet",
    "torus": "torus", "washer": "washer",
    "столб": "cylinder", "шар": "sphere", "конус": "cone",
    "плита": "cube", "труба": "cylinder", "шайба": "washer",
}
_BOOL = {"union": "union", "difference": "difference", "intersect": "intersection",
         "объединить": "union", "вычесть": "difference", "пересечение": "intersection"}
_XFORM = {"translate": "translate", "move": "translate", "сдвиг": "translate",
          "rotate": "rotate", "поворот": "rotate", "повернуть": "rotate",
          "mirror": "mirror", "зеркало": "mirror", "отразить": "mirror",
          "scale": "scale", "масштаб": "scale"}


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _vec(values) -> str:
    return "[" + ", ".join(_fmt(float(v)) for v in values) + "]"


#: OpenSCAD 2021.01 не принимает кириллицу в идентификаторах, поэтому имена
#: транслитерируем: «плита» → `plita`. Читаемость важнее точности.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _clean_name(name: str, index: int) -> str:
    """Безопасный идентификатор OpenSCAD: транслит, цифры, подчёркивания."""
    out = []
    for ch in str(name):
        low = ch.lower()
        if low in _TRANSLIT:
            piece = _TRANSLIT[low]
            out.append(piece.capitalize() if ch.isupper() and piece else piece)
        elif ch.isascii() and (ch.isalnum() or ch == "_"):
            out.append(ch)
        else:
            out.append("_")
    ascii_name = "".join(out).strip("_") or f"obj{index}"
    if ascii_name[0].isdigit():
        ascii_name = f"obj_{ascii_name}"
    return ascii_name


def _polyhedron(manifold, name: str, comment: str) -> str:
    verts, faces = manifold_mesh(manifold)
    if len(verts) == 0 or len(faces) == 0:
        return f"// {comment}: пустое тело, пропущено\n"
    points = ",\n    ".join(_vec(v) for v in verts)
    tris = ", ".join(f"[{int(a)}, {int(b)}, {int(c)}]" for a, b, c in faces)
    return (
        f"// {comment}\n"
        f"module {name}() {{\n"
        f"  polyhedron(\n"
        f"    points = [\n    {points}\n    ],\n"
        f"    faces = [{tris}],\n"
        f"    convexity = 10\n"
        f"  );\n"
        f"}}\n"
    )


def scad_solid(result) -> str:
    """Геометрия «как есть»: polyhedron на каждый видимый объект."""
    if not result.ok or result.scene is None:
        raise ValueError("сцену не удалось построить — экспортировать нечего")
    lines = [
        "// ФОРМА 3D → OpenSCAD, режим solid: геометрия перенесена без упрощений",
        "// объём, число треугольников и положение совпадают с ядром ФОРМЫ",
        "$fn = 64;",
        "",
    ]
    calls: list[str] = []
    for index, solid in enumerate(result.scene.visible_solids()):
        volume = abs(float(solid.manifold.volume())) / 1000.0
        tris = solid.manifold.num_tri()
        module = _clean_name(solid.name, index)
        lines.append(_polyhedron(solid.manifold, module,
                                 f"{solid.name}: {tris} треугольников, {volume:.3f} см³"))
        calls.append(f"{module}();   // {solid.name}")
    lines.append("")
    lines.extend(calls)
    return "\n".join(lines) + "\n"


def _primitive_code(kind: str, cmd) -> str | None:
    """Операторы OpenSCAD для примитива без учёта положения (центр в 0)."""
    get = cmd.kwargs.get
    if kind == "cube":
        size = get("size")
        if not size:
            return None
        values = [float(v) for v in str(size).strip("[]").split(",")]
        if len(values) != 3:
            return None
        return f"cube({_vec(values)}, center = true);"
    if kind in ("cylinder", "cone", "prism", "pyramid"):
        radius = _num(get("radius") or get("r"))
        height = _num(get("height") or get("h"))
        if radius is None or height is None:
            return None
        sides = _num(get("sides"), 0)
        if kind == "cone" and "r2" not in cmd.kwargs:
            return (f"cylinder(h = {_fmt(height)}, r1 = {_fmt(radius)}, r2 = 0, "
                    f"center = true);")
        if kind in ("prism", "pyramid") and sides and sides >= 3:
            r2 = 0 if kind == "pyramid" else radius
            return (f"cylinder(h = {_fmt(height)}, r1 = {_fmt(radius)}, "
                    f"r2 = {_fmt(r2)}, $fn = {int(sides)}, center = true);")
        return f"cylinder(h = {_fmt(height)}, r = {_fmt(radius)}, center = true);"
    if kind == "sphere":
        radius = _num(get("radius") or get("r"))
        return f"sphere(r = {_fmt(radius)});" if radius else None
    if kind == "sheet":
        w = _num(get("width"))
        length = _num(get("length"))
        thickness = _num(get("thickness"), 1.0)
        if None in (w, length, thickness):
            return None
        return f"cube({_vec([w, length, thickness])}, center = true);"
    if kind == "torus":
        outer = _num(get("outer"))
        inner = _num(get("inner"))
        if None in (outer, inner):
            return None
        big = (outer + inner) / 2.0
        small = abs(outer - inner) / 2.0
        return (f"rotate_extrude($fn = 96) translate([{_fmt(big)}, 0, 0]) "
                f"circle(r = {_fmt(small)}, $fn = 64);")
    if kind == "washer":
        outer = _num(get("outer"))
        inner = _num(get("inner"))
        thickness = _num(get("thickness"), 3.0)
        if None in (outer, inner, thickness):
            return None
        return (f"difference() {{ cylinder(h = {_fmt(thickness)}, d = {_fmt(outer)}, "
                f"center = true); cylinder(h = {_fmt(thickness + 2)}, d = {_fmt(inner)}, "
                f"center = true); }}")
    return None


def _bbox_center(text: str) -> list[float] | None:
    """Центр габарита примитива — по ядру, а не по догадке о смысле `at`."""
    from .run import build

    single = build(text, analyze_model=False)
    if not single.ok or single.scene is None:
        return None
    solids = single.scene.visible_solids()
    if not solids:
        return None
    bb = solids[-1].manifold.bounding_box()
    return [float((bb[i] + bb[i + 3]) / 2.0) for i in range(3)]


def scad_script(result, source: str) -> str:
    """Перевод по командам: параметрический `.scad`, который можно править."""
    if not result.ok or result.scene is None:
        raise ValueError("сцену не удалось построить — экспортировать нечего")

    modules: list[str] = []
    names: dict[str, str] = {}
    unsupported: list[str] = []
    counter = 0

    def fallback(name: str, reason: str) -> None:
        solid = result.scene.objects.get(name)
        unsupported.append(f"{name}: {reason}")
        if solid is None:
            return
        module = names.get(name) or _clean_name(name, counter)
        names[name] = module
        modules.append(_polyhedron(solid.manifold, module,
                                   f"{name}: {reason}; перенесено как polyhedron"))

    for cmd in parse_script(source):
        verb = (cmd.verb or "").strip()
        if not verb or verb in ("check", "проверка", "let", "профиль", "profile"):
            continue
        target = cmd.target or f"auto{counter}"
        counter += 1
        module = names.get(target) or _clean_name(target, counter)
        names[target] = module

        if verb in _BOOL:
            operands = [a for a in cmd.args if a not in ("[", "]")]
            children = []
            for raw in operands:
                for token in str(raw).replace("[", " ").replace("]", " ").split():
                    children.append(names.get(token))
            if not children or any(child is None for child in children):
                fallback(target, f"операция {verb}: не все операнды переведены")
                continue
            body = "\n".join(f"    {child}();" for child in children)
            modules.append(f"// {target} = {verb}\nmodule {module}() {{\n"
                           f"  {_BOOL[verb]}() {{\n{body}\n  }}\n}}\n")
            continue

        if verb in _XFORM:
            operand = None
            for raw in cmd.args:
                for token in str(raw).replace("[", " ").replace("]", " ").split():
                    operand = names.get(token) or operand
            if operand is None:
                fallback(target, f"преобразование {verb} без переведённого операнда")
                continue
            if verb in ("translate", "move", "сдвиг"):
                offset = [(_num(cmd.kwargs.get(axis), 0.0) or 0.0) for axis in ("x", "y", "z")]
                if cmd.kwargs.get("offset"):
                    offset = [float(v) for v in str(cmd.kwargs["offset"]).strip("[]").split(",")]
                code = f"translate({_vec(offset)}) {operand}();"
            elif verb in ("rotate", "поворот", "повернуть"):
                angle = _num(cmd.kwargs.get("angle"), 0.0) or 0.0
                axis = str(cmd.kwargs.get("axis", "z")).lower()
                vector = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get(axis, [0, 0, 1])
                code = f"rotate(a = {_fmt(angle)}, v = {_vec(vector)}) {operand}();"
            elif verb in ("mirror", "зеркало", "отразить"):
                plane = str(cmd.kwargs.get("plane", "x")).lower()
                vector = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get(plane, [1, 0, 0])
                code = f"mirror({_vec(vector)}) {operand}();"
            else:
                factor = _num(cmd.kwargs.get("factor") or cmd.kwargs.get("scale"), 1.0) or 1.0
                code = f"scale({_vec([factor, factor, factor])}) {operand}();"
            modules.append(f"// {target} = {verb}\nmodule {module}() {{ {code} }}\n")
            continue

        kind = _PRIMS.get(verb)
        code = _primitive_code(kind, cmd) if kind else None
        if code is None:
            fallback(target, f"команда «{verb}» пока не переводится")
            continue
        center = _bbox_center(cmd.text)
        if center is None:
            fallback(target, "не удалось определить положение")
            continue
        modules.append(f"// {cmd.text}\nmodule {module}() {{\n"
                       f"  translate({_vec(center)}) {code}\n}}\n")

    visible = [s.name for s in result.scene.visible_solids()]
    for name in visible:
        if name not in names:
            fallback(name, "объект создан командой без перевода")

    head = [
        "// ФОРМА 3D → OpenSCAD, режим script: параметрическая запись",
        "// правьте числа и модули; непереведённые команды заменены polyhedron",
        "$fn = 64;",
        "",
    ]
    body = "\n".join(modules)
    tail = "\n".join(f"{names[name]}();   // {name}" for name in visible if name in names)
    note = ""
    if unsupported:
        note = ("\n// НЕ ПЕРЕВЕДЕНО (эти объекты перенесены как polyhedron):\n"
                + "\n".join(f"//   {u}" for u in unsupported) + "\n")
    return "\n".join(head) + body + "\n" + tail + "\n" + note


def export_scad(result, path, mode: str = "solid", source: str | None = None) -> dict:
    """Пишет `.scad` и возвращает короткий отчёт: режим, объекты, байты."""
    text = scad_solid(result) if mode == "solid" else scad_script(result, source or "")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "path": str(path),
        "mode": mode,
        "objects": len(result.scene.visible_solids()) if result.scene else 0,
        "bytes": path.stat().st_size,
        "has_polyhedron": "polyhedron(" in text,
        "lines": text.count("\n"),
    }
