"""Команды сцены: цвет, видимость, проверки."""

from __future__ import annotations

from .errors import DslError
from .geometry import normalize_color
from .ops import op


@op("color", aliases=("цвет", "покрасить", "материал", "paint"), category="Сцена и материал",
    summary="Задаёт цвет и материал объекта (или всех объектов).",
    example="color ручка #d8b98a material=wood",
    params={"target": "имя объекта или all",
            "color": "цвет #RRGGBB или название",
            "material": "ceramic, metal, steel, aluminum, gold, copper, plastic, wood, rubber, glass",
            "metal": "металличность 0..1", "rough": "шероховатость 0..1",
            "density": "плотность г/см³ (для оценки массы)"},
    positional=["target", "color"])
def color(a, name):
    target = (a.text("target") or "all").strip()
    style = a.style()
    if not style:
        raise DslError("Укажите цвет или материал.",
                       hint="Например: color корпус #e8e8e8 material=ceramic",
                       line=a.cmd.line, command=a.cmd.text)
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        [a.scene.resolve(target)]
    for solid in targets:
        for key, value in style.items():
            if key == "color":
                setattr(solid, key, normalize_color(value))
            else:
                setattr(solid, key, value)
    a.scene.log("info", f"Материал применён: {', '.join(s.name for s in targets)}", a.cmd.line)
    return None


@op("show", aliases=("показать", "видимый"), category="Сцена и материал",
    summary="Показывает объект (в том числе промежуточный).",
    example="show корпус", params={"target": "имя объекта или all"},
    positional=["target"])
def show(a, name):
    target = (a.text("target") or "").strip()
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        [a.scene.resolve(target)]
    for solid in targets:
        solid.visible = True
    return None


@op("hide", aliases=("скрыть", "спрятать"), category="Сцена и материал",
    summary="Скрывает объект.",
    example="hide корпус", params={"target": "имя объекта или all"},
    positional=["target"])
def hide(a, name):
    target = (a.text("target") or "").strip()
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        [a.scene.resolve(target)]
    for solid in targets:
        solid.visible = False
    return None


@op("check", aliases=("проверить", "проверка"), category="Проверка",
    summary="Задаёт проверку результата: размер, толщина стенок, герметичность, симметрия и т.д.",
    example="check кружка height 90..110",
    params={"object": "имя объекта",
            "rule": "watertight, genus, parts, size, height, width, depth, volume, mass, "
                    "wall, flat_bottom, overhang, symmetric, gap, inside, tris, inverted",
            "args": "параметры правила, например 90..110 или x"},
    positional="*")
def check(a, name):
    raise DslError("Внутренняя ошибка: проверка должна обрабатываться построителем.",
                   line=a.cmd.line)
