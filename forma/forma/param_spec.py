"""Типы параметров операций: из чего строится управляющий элемент.

Панель Формы не должна показывать «свободное поле ввода» там, где у параметра
есть диапазон, единица или набор допустимых слов. Здесь для каждой операции
объявлено, **чем** параметр управляется и **как** он может быть не задан.

Объявление — не проверка значений: проверки живут в ``Args`` и остаются
единственным источником ошибок сборки. Здесь только форма управления и способ
вернуть «авто» (параметр не задан), чтобы интерфейс не выдумывал это сам.
"""

from __future__ import annotations

from typing import Any

# Режимы «авто»:
#   omitted  — параметра нет в строке, значение выбирает операция;
#   sentinel — параметр задан особым числом (например 0 = «по детализации»);
#   enum     — авто является одним из вариантов списка.
AUTO_OMITTED = "omitted"
AUTO_SENTINEL = "sentinel"
AUTO_ENUM = "enum"


def num(label: str, *, default: Any = None, minv: float | None = None,
        maxv: float | None = None, step: float | None = None, unit: str = "мм",
        auto: str | None = None, hint: str = "", required: bool = False,
        hidden: bool = False, sentinel: Any = None,
        sentinel_label: str = "") -> dict:
    return {"type": "num", "label": label, "default": default, "min": minv,
            "max": maxv, "step": step, "unit": unit, "auto": auto, "auto_hint": hint,
            "required": required, "hidden": hidden, "sentinel_value": sentinel,
            "sentinel_label": sentinel_label}


def integer(label: str, **kwargs) -> dict:
    kwargs.setdefault("step", 1)
    kwargs.setdefault("unit", "")
    spec = num(label, **kwargs)
    spec["type"] = "int"
    return spec


def vec(label: str, size: int = 3, *, default: Any = None, unit: str = "мм",
        minv: float | None = None, maxv: float | None = None,
        auto: str | None = None, hint: str = "", required: bool = False) -> dict:
    return {"type": "vec", "label": label, "size": size, "default": default,
            "unit": unit, "min": minv, "max": maxv, "auto": auto,
            "auto_hint": hint, "required": required}


def flag(label: str, *, default: bool = False, **kwargs) -> dict:
    return {"type": "flag", "label": label, "default": default, **kwargs}


def enum(label: str, items: list[str], *, default: str | None = None,
         labels: dict[str, str] | None = None, auto: str | None = None,
         hint: str = "") -> dict:
    return {"type": "enum", "label": label,
            "items": [{"value": item, "label": (labels or {}).get(item, item)}
                      for item in items],
            "default": default, "auto": auto, "auto_hint": hint}


def string(label: str, *, default: str | None = None, **kwargs) -> dict:
    """Единственный свободный ввод: имена, материалы, пути, точечные списки."""
    return {"type": "str", "label": label, "default": default, "free": True, **kwargs}


TOP = {"верх": "верх", "низ": "низ"}

SPECS: dict[str, dict[str, dict]] = {
    "box": {
        "size": vec("габарит [X, Y, Z]", 3, required=True, minv=0.01),
        "top_size": vec("верхняя плоскость [X, Y]", 2,
                        auto=AUTO_OMITTED, hint="как у основания"),
        "top_offset": vec("сдвиг верхней плоскости [dx, dy]", 2, default=[0, 0]),
        "base_angle": num("угол в основании, °", default=90.0, minv=1.0, maxv=179.0,
                          step=1.0, unit="°"),
        "wall": num("толщина стенки (0 — сплошной)", default=0.0, minv=0.0, step=0.5),
        "cavity": enum("открытая сторона полости", ["верх", "низ"], default="верх"),
        "cavity_depth": num("глубина полости", default=None, minv=0.1,
                            auto=AUTO_OMITTED, hint="до дна не тоньше стенки"),
        "round": num("скругление рёбер", default=0.0, minv=0.0, step=0.5),
        "expand": num("расширение половины", default=0.0, minv=0.0, step=0.5),
        "expand_side": enum("расширяемая половина", ["верх", "низ"], default="верх"),
        "expand_joint": enum("посадка половин", ["посадка", "стык"], default="посадка",
                             labels={"посадка": "колпачок с поясом",
                                     "стык": "без нахлёста"}),
        "expand_seat": num("заход пояса", auto=AUTO_OMITTED,
                           hint="12 % полувысоты", minv=0.0),
        "expand_smooth": num("плавность перехода 0…1", default=0.0, minv=0.0,
                             maxv=1.0, step=0.05, unit=""),
        "detail": integer("детализация скругления 0…5", minv=0, maxv=5, unit=""),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по Z", default=False),
    },
    "cylinder": {
        "radius": num("радиус снизу", required=True, minv=0.01),
        "height": num("высота", required=True, minv=0.01),
        "r2": num("радиус сверху", auto=AUTO_OMITTED, hint="равен нижнему",
                  minv=0.0),
        "top_scale": vec("множители верха [sx, sy]", 2, default=[1, 1], unit=""),
        "top_offset": vec("сдвиг верха [dx, dy]", 2, default=[0, 0]),
        "segments": integer("сегментов", minv=8, maxv=1024,
                            auto=AUTO_OMITTED, hint="по детализации"),
        "detail": integer("детализация 0…5", minv=0, maxv=5, unit=""),
        "wall": num("толщина стенки (0 — сплошной)", default=0.0, minv=0.0, step=0.5),
        "cavity": enum("открытая сторона полости", ["верх", "низ"], default="верх"),
        "cavity_depth": num("глубина полости", auto=AUTO_OMITTED,
                            hint="на всю высоту минус дно"),
        "round": num("скругление кромок", default=0.0, minv=0.0, step=0.5),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по Z", default=False),
    },
    "cone": {
        "radius": num("радиус основания", required=True, minv=0.01),
        "height": num("высота", required=True, minv=0.01),
        "form": enum("профиль", ["прямой", "парабола", "холмик"], default="прямой"),
        "segments": integer("сегментов", minv=8, maxv=1024,
                            auto=AUTO_OMITTED, hint="по радиусу"),
        "wall": num("толщина стенки (0 — сплошной)", default=0.0, minv=0.0, step=0.5),
        "cavity_depth": num("глубина полости", auto=AUTO_OMITTED,
                            hint="высота минус стенка"),
        "smooth": integer("сглаживание 0…4", minv=0, maxv=4, unit=""),
        "detail": integer("детализация 0…5", minv=0, maxv=5, unit=""),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по Z", default=False),
    },
    "sphere": {
        "radius": num("радиус", required=True, minv=0.01),
        "slice": num("срез сверху, доля радиуса", default=0.0, minv=0.0, maxv=1.0,
                     step=0.05, unit=""),
        "cut": num("срез сверху", auto=AUTO_OMITTED, hint="срез не задан",
                   minv=0.0),
        "round": num("скругление кромки среза", default=0.0, minv=0.0, step=0.5),
        "detail": integer("детализация 0…5", minv=0, maxv=5, unit=""),
        "segments": integer("сегментов", minv=8, maxv=512,
                            auto=AUTO_OMITTED, hint="по детализации"),
        "expand": num("расширение половины", default=0.0, minv=0.0, maxv=2.0,
                      step=0.05, unit=""),
        "expand_side": enum("расширяемая половина", ["верх", "низ"], default="верх"),
        "expand_smooth": num("плавность перехода 0…1", default=0.0, minv=0.0,
                             maxv=1.0, step=0.05, unit=""),
        "expand_joint": enum("посадка половин", ["посадка", "стык"],
                             default="посадка"),
        "expand_seat": num("заход пояса", auto=AUTO_OMITTED,
                           hint="12 % полувысоты", minv=0.0),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
    },
    "prism": {
        "sides": integer("сторон", default=6, minv=3, maxv=256),
        "radius": num("радиус основания", required=True, minv=0.01),
        "height": num("высота", required=True, minv=0.01),
        "r2": num("радиус верха", auto=AUTO_OMITTED, hint="равен нижнему", minv=0.0),
        "twist": num("закрутка верха, °", default=0.0, unit="°"),
        "top_scale": vec("множители верха [sx, sy]", 2, default=[1, 1], unit=""),
        "top_offset": vec("сдвиг верха [dx, dy]", 2, default=[0, 0]),
        "base_angle": num("угол в основании, °", default=90.0, minv=15.0, maxv=165.0,
                          step=1.0, unit="°"),
        "smooth": integer("скругление рёбер 0…4", minv=0, maxv=4, unit=""),
        "wall": num("толщина стенки (0 — сплошной)", default=0.0, minv=0.0, step=0.5),
        "cavity": enum("открытая сторона полости", ["верх", "низ"], default="верх"),
        "cavity_depth": num("глубина полости", auto=AUTO_OMITTED,
                            hint="до дна не тоньше стенки"),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по Z", default=False),
    },
    "pyramid": {
        "sides": integer("сторон", default=4, minv=3, maxv=128),
        "radius": num("радиус основания", required=True, minv=0.01),
        "height": num("высота", required=True, minv=0.01),
        "tip": vec("смещение вершины [dx, dy]", 2,
                   auto=AUTO_OMITTED, hint="вершина над центром"),
        "tip_at": enum("где вершина", ["center", "corner", "side"],
                       default="center",
                       labels={"center": "по центру", "corner": "над углом",
                               "side": "над стороной"}),
        "tip_index": integer("номер угла/стороны", default=0, minv=0, maxv=127),
        "base_angle": num("угол параллелограмма, °", default=90.0, minv=15.0,
                          maxv=165.0, step=1.0, unit="°"),
        "smooth": integer("скругление рёбер 0…4", minv=0, maxv=4, unit=""),
        "wall": num("толщина стенки (0 — сплошной)", default=0.0, minv=0.0, step=0.5),
        "cavity_depth": num("глубина полости", auto=AUTO_OMITTED,
                            hint="высота минус стенка"),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по Z", default=False),
    },
    "torus": {
        "outer": num("наружный радиус", auto=AUTO_OMITTED, hint="из major и minor",
                     minv=0.2),
        "inner": num("радиус отверстия", auto=AUTO_OMITTED, hint="из major и minor",
                     minv=0.0),
        "thickness": num("толщина по радиусу", auto=AUTO_OMITTED,
                         hint="2 · minor", minv=0.02),
        "major": num("радиус кольца", auto=AUTO_OMITTED, hint="из outer и inner",
                     minv=0.1),
        "minor": num("радиус трубки", auto=AUTO_OMITTED, hint="из thickness",
                     minv=0.01),
        "segments": integer("сегментов кольца", minv=12, maxv=512,
                            auto=AUTO_OMITTED, hint="по детализации"),
        "minor_segments": integer("сегментов трубки", minv=8, maxv=128,
                                  auto=AUTO_OMITTED, hint="по детализации"),
        "detail": integer("детализация 0…5", minv=0, maxv=5, unit=""),
        "at": vec("центр [x, y, z]", 3, default=[0, 0, 0]),
    },
    "washer": {
        "outer": num("наружный диаметр/радиус", default=40.0, minv=1.0),
        "inner": num("внутренний радиус", default=16.0, minv=0.2),
        "thickness": num("толщина", default=4.0, minv=0.2),
        "chamfer": num("фаска", default=0.5, minv=0.0, step=0.1),
        "segments": integer("сегментов", minv=32, maxv=256,
                            auto=AUTO_OMITTED, hint="96"),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по высоте", default=False),
    },
    "gear": {
        "teeth": integer("зубьев", default=20, minv=6, maxv=200),
        "module": num("модуль", default=2.0, minv=0.05, step=0.1),
        "thickness": num("толщина", default=8.0, minv=0.2),
        "bore": num("отверстие ступицы (0 — нет)", default=0.0, minv=0.0),
        "hub": num("высота ступицы (0 — нет)", default=0.0, minv=0.0),
        "hub_height": num("выступ ступицы", auto=AUTO_OMITTED,
                          hint="0.6 толщины", minv=0.0),
        "hub_below": num("ступица снизу", default=0.0, minv=0.0),
        "hub_round": num("скругление ступицы", default=0.4, minv=0.0, step=0.1),
        "web": num("толщина диска", auto=AUTO_OMITTED, hint="равна толщине",
                   minv=0.4),
        "spokes": integer("спиц (0 — диск)", default=0, minv=0, maxv=12),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по высоте", default=False),
    },
    "icosphere": {
        "radius": num("радиус", required=True, minv=0.01),
        "divisions": integer("подразбиений 0…5", default=2, minv=0, maxv=5),
        "mode": enum("разбиение", ["triangle", "quad", "pentagon", "honeycomb"],
                     default="triangle",
                     labels={"triangle": "треугольники", "quad": "квадраты",
                             "pentagon": "пятиугольники", "honeycomb": "сота"}),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
    },
    "shaft": {
        "length": num("длина", default=100.0, minv=1.0),
        "diameter": num("диаметр", default=20.0, minv=0.5),
        "chamfer": num("фаска торца", default=1.0, minv=0.0, step=0.1),
        "bore": num("осевое отверстие (0 — нет)", default=0.0, minv=0.0),
        "flange": num("толщина фланца (0 — нет)", default=0.0, minv=0.0),
        "flange_d": num("диаметр фланца", auto=AUTO_OMITTED,
                        hint="2 · диаметр вала", minv=1.0),
        "flange_at": num("положение фланца", auto=AUTO_OMITTED,
                         hint="по центру", minv=0.0),
        "flange_round": num("скругление фланца", default=0.5, minv=0.0, step=0.1),
        "axis": enum("ось", ["x", "y", "z"], default="z"),
        "steps": string("ступени [[длина, диаметр], …]",
                        hint="вместо одного диаметра"),
        "segments": integer("сегментов", minv=8, maxv=512,
                            auto=AUTO_OMITTED, hint="64"),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по высоте", default=False),
    },
    "pipe": {
        "diameter": num("наружный диаметр", default=32.0, minv=1.0),
        "wall": num("толщина стенки", default=2.0, minv=0.2, step=0.1),
        "length": num("длина", default=200.0, minv=1.0, maxv=100000.0),
        "angle": num("угол сгиба, °", default=0.0, minv=-180.0, maxv=180.0,
                     step=1.0, unit="°"),
        "radius": num("радиус сгиба", default=80.0, minv=0.5, maxv=100000.0),
        "joint": enum("сгиб", ["плавный", "острый"], default="плавный"),
        "path": string("путь [[x, y, z], …]",
                       hint="старый режим; отключает простой сгиб"),
        "hole": flag("полая труба", default=True),
        "sides": integer("сегментов по кругу", minv=6, maxv=128,
                         auto=AUTO_OMITTED, hint="24"),
        "at": vec("положение [x, y, z]", 3, default=[0, 0, 0]),
        "center": flag("центрировать по высоте", default=False),
    },
}


def spec_for(op: str) -> dict[str, dict]:
    """Спецификация параметров операции (пустая — если ещё не объявлена)."""
    return SPECS.get(str(op or "").lower(), {})


def control_kind(spec: dict) -> str:
    """Тип управляющего элемента: num/int/vec/flag/enum/str."""
    return str(spec.get("type") or "str")


def is_free(spec: dict) -> bool:
    """Свободный ввод допустим только для ``type: "str"``."""
    return control_kind(spec) == "str"


def reset_value(spec: dict, default: Any = None) -> Any:
    """Значение «сбросить к заводскому»: None означает «параметр убрать»."""
    if default is not None:
        return default
    return spec.get("default")


def auto_mode(spec: dict) -> str | None:
    return spec.get("auto")


def payload(op: str) -> dict:
    """Готовый словарь для интерфейса: типы, диапазоны, режимы «авто»."""
    specs = spec_for(op)
    return {key: dict(value) for key, value in specs.items()}
