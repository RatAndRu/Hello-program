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
    # Оболочка: и список точек, и список тел задаются текстом — отдельных
    # контролов для списков в панели нет, но подпись и подсказка нужны.
    "hull": {
        "objects": string("детали через запятую", hint="например [a, b, c]"),
        "points": string("точки [[x, y, z], …]", hint="облако точек для оболочки"),
    },
    # Проверка материала в точке: три координаты — это числа, а не текст.
    "probe": {
        "x": num("координата X", default=0.0),
        "y": num("координата Y", default=0.0),
        "z": num("координата Z", default=0.0),
    },
}


def generic_entry(name: str) -> dict | None:
    """Тип параметра по его имени: общая таблица ``param_types``.

    Имя повторяется у десятков операций (``radius``, ``wall``, ``at``), поэтому
    тип объявлен один раз. Возвращает готовое описание управления или None,
    если имя спорное — тогда параметр остаётся свободным вводом.
    """
    from .param_types import generic_spec

    entry = generic_spec(name)
    if not entry:
        return None
    kind = entry.pop("type")
    label = entry.get("label") or name
    if kind == "num":
        return num(label, minv=entry.get("min"), maxv=entry.get("max"),
                   step=entry.get("step"), unit=entry.get("unit", "мм"))
    if kind == "int":
        return integer(label, minv=entry.get("min"), maxv=entry.get("max"),
                       unit=entry.get("unit", ""))
    if kind == "vec":
        return vec(label, int(entry.get("size") or 3), unit=entry.get("unit", "мм"),
                   minv=entry.get("min"), maxv=entry.get("max"))
    if kind == "flag":
        return flag(label)
    return string(label)


def spec_for(op: str, params: list[str] | None = None) -> dict[str, dict]:
    """Спецификация параметров операции.

    Без ``params`` — только явные объявления ``SPECS``. С именами параметров —
    ещё и общие типы из ``param_types``: явное объявление всегда важнее общего.
    """
    base = SPECS.get(str(op or "").lower(), {})
    if not params:
        return base
    merged: dict[str, dict] = {}
    for name in params:
        if name in base:
            merged[name] = base[name]
            continue
        generic = generic_entry(name)
        if generic:
            merged[name] = generic
    for key, value in base.items():
        merged.setdefault(key, value)
    return merged


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


def presets_payload(op: str, kwargs: dict | None = None) -> list[dict]:
    """Пресеты формы вместе со значениями, которые они запишут."""
    return presets_for(op, kwargs)


def payload(op: str, params: list[str] | None = None) -> dict:
    """Готовый словарь для интерфейса: типы, диапазоны, режимы «авто»."""
    specs = spec_for(op, params)
    return {key: dict(value) for key, value in specs.items()}


# --------------------------------------------------------------------------
# Пресеты формы
# --------------------------------------------------------------------------
#
# Пресет меняет **пропорции и режим**, а не абсолютный размер: «плита» — это
# та же деталь, сплющенная по Z, а не «плита 200×100×6». Так пресет осмыслен
# для любой модели и остаётся одной правкой строки.

def _num(raw, fallback: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _vec(raw, size: int, fallback=None):
    """Вектор из значения строки: ``[100, 80, 60]`` или уже список."""
    values = raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        values = [part.strip() for part in text.split(",")] if text else []
    if isinstance(values, (list, tuple)) and len(values) >= size:
        try:
            return [float(v) for v in values[:size]]
        except (TypeError, ValueError):
            return list(fallback or [0.0] * size)
    return list(fallback or [0.0] * size)


def _preset(name: str, label: str, changes: dict) -> dict:
    clean = {key: value for key, value in changes.items() if value is not None}
    return {"name": name, "label": label, "changes": clean}


def presets_for(op: str, kwargs: dict | None = None) -> list[dict]:
    """Пресеты формы для операции с учётом текущих значений строки."""
    values = {key: v for key, v in (kwargs or {}).items()}
    op = str(op or "").lower()
    out: list[dict] = []
    if op == "box":
        size = _vec(values.get("size"), 3, [100, 80, 60])
        x, y, z = size
        side = min(x, y, z)
        out.append(_preset("куб", "куб", {"size": [side, side, side]}))
        out.append(_preset("плита", "плита", {"size": [x, y, max(1.0, min(x, y) / 8.0)]}))
        out.append(_preset("брусок", "брусок", {"size": [x, y, z], "base_angle": 90,
                                                "top_size": [x, y]}))
        out.append(_preset("ромб", "ромб", {"size": [x, y, z], "base_angle": 60,
                                            "top_size": [x, y]}))
    elif op == "cylinder":
        radius = _num(values.get("radius"), 40.0)
        height = _num(values.get("height"), 80.0)
        wall = max(0.8, min(radius * 0.08, height * 0.08))
        out.append(_preset("цилиндр", "цилиндр", {"r2": radius, "wall": 0}))
        out.append(_preset("конус", "конус", {"r2": 0}))
        out.append(_preset("стакан", "стакан", {"wall": wall, "cavity": "верх",
                                                "cavity_depth": height - wall}))
        out.append(_preset("колпак", "колпак", {"wall": wall, "cavity": "низ",
                                                "cavity_depth": height * 0.85}))
    elif op == "sphere":
        radius = _num(values.get("radius"), 40.0)
        out.append(_preset("шар", "шар", {"slice": 0}))
        out.append(_preset("полусфера", "полусфера", {"slice": 1}))
        # slice и cut взаимоисключающие: пресет задаёт только один из них,
        # а второй, если он был в строке, убирается отдельной правкой.
        out.append(_preset("срез", "срез", {"cut": round(radius * 0.3, 3)}))
    elif op == "cone":
        radius = _num(values.get("radius"), 40.0)
        height = _num(values.get("height"), 60.0)
        out.append(_preset("прямой", "прямой", {"form": "прямой"}))
        out.append(_preset("горка", "горка", {"form": "парабола"}))
        out.append(_preset("холм", "холм", {"form": "холмик", "smooth": 1}))
        out.append(_preset("купол", "купол", {"form": "холмик", "wall": max(
            0.8, min(radius * 0.06, height * 0.06))}))
    elif op == "prism":
        out.append(_preset("гайка", "гайка", {"sides": 6, "base_angle": 90}))
        out.append(_preset("квадрат", "квадрат", {"sides": 4, "base_angle": 90}))
        out.append(_preset("ромб", "ромб", {"sides": 4, "base_angle": 60}))
        out.append(_preset("пластина", "пластина", {"sides": 6, "base_angle": 90}))
    elif op == "torus":
        major = _num(values.get("major"), 30.0)
        if "outer" in values or "inner" in values:
            major = max(0.1, (_num(values.get("outer"), 40.0)
                              + _num(values.get("inner"), 24.0)) / 2.0)
        out.append(_preset("кольцо", "кольцо", {"minor": max(0.5, major * 0.18)}))
        out.append(_preset("тонкое", "тонкое кольцо", {"minor": max(0.3, major * 0.08)}))
        out.append(_preset("толстое", "толстое кольцо", {"minor": max(1.0, major * 0.35)}))
    elif op == "gear":
        thickness = _num(values.get("thickness"), 8.0)
        out.append(_preset("диск", "диск", {"spokes": 0}))
        out.append(_preset("спицы", "спицы", {"spokes": 5, "web": max(0.4, thickness * 0.5)}))
        out.append(_preset("ступица", "со ступицей", {"hub": max(1.0, thickness * 1.5)}))
    elif op == "icosphere":
        out.append(_preset("сфера", "треугольники", {"mode": "triangle"}))
        out.append(_preset("сота", "сота", {"mode": "honeycomb"}))
    elif op == "pipe":
        out.append(_preset("прямая", "прямая", {"angle": 0}))
        out.append(_preset("колено", "колено 90°", {"angle": 90}))
        out.append(_preset("отвод", "отвод 45°", {"angle": 45}))
    elif op == "shaft":
        diameter = _num(values.get("diameter"), 20.0)
        out.append(_preset("вал", "гладкий вал", {"chamfer": max(0.2, diameter * 0.05)}))
        out.append(_preset("фланец", "с фланцем", {"flange": max(1.0, diameter * 0.4)}))
    return out
