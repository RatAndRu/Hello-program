"""Типы повторяющихся параметров: одна таблица вместо двух тысяч объявлений.

В реестре 2505 параметров, но имён среди них — около четырёхсот, и большинство
повторяются: ``radius``, ``height``, ``wall``, ``at``. Держать тип у каждой
операции отдельно бессмысленно: ``radius`` остаётся радиусом и у болта, и у
вала. Поэтому здесь объявлены **имена**, а ``param_spec`` подставляет их тем
операциям, у которых имя встречается.

Таблица заполнена по факту: типы выведены из того, как параметр реально
записан в примерах реестра и в ``examples/*.forma`` (см. ``docs/revision.md``),
и только там, где значение устойчиво одного вида. Спорные имена — ``size``
(бывает и ``size=20``, и ``size=[20,10,4]``), ``points``, ``sections``,
``factor`` — здесь намеренно отсутствуют: для них остаётся свободный ввод, а
не догадка. Явное объявление в ``SPECS`` всегда важнее этой таблицы.

Типы — те же, что понимает интерфейс: ``num``, ``int``, ``vec``, ``flag``,
``str``. Свободный ввод остаётся только у ``str``.
"""

from __future__ import annotations

# name → {"type": ..., "label": ..., "unit": ..., "min"/"max"/"step"/"size"}
TYPES: dict[str, dict] = {
    # --- положение и размеры ------------------------------------------------
    "at": {"type": "vec", "size": 3, "label": "положение [X, Y, Z]", "unit": "мм",
           "step": 0.1},
    "pos": {"type": "vec", "size": 3, "label": "точка [X, Y, Z]", "unit": "мм"},
    "point": {"type": "vec", "size": 3, "label": "точка [X, Y, Z]", "unit": "мм"},
    "center": {"type": "flag", "label": "по центру"},
    "offset": {"type": "vec", "size": 3, "label": "смещение [dx, dy, dz]", "unit": "мм"},
    "pivot": {"type": "vec", "size": 3, "label": "центр поворота [X, Y, Z]", "unit": "мм"},
    "top_size": {"type": "vec", "size": 2, "label": "верхняя плоскость [X, Y]", "unit": "мм"},
    "top_offset": {"type": "vec", "size": 2, "label": "сдвиг верха [dx, dy]", "unit": "мм"},
    "root": {"type": "vec", "size": 2, "label": "корень [X, Y]", "unit": "мм"},
    "radius": {"type": "num", "label": "радиус", "unit": "мм", "min": 0.0, "step": 0.5},
    "diameter": {"type": "num", "label": "диаметр", "unit": "мм", "min": 0.0, "step": 0.5},
    "height": {"type": "num", "label": "высота", "unit": "мм", "step": 0.5},
    "width": {"type": "num", "label": "ширина", "unit": "мм", "step": 0.5},
    "length": {"type": "num", "label": "длина", "unit": "мм", "step": 0.5},
    "depth": {"type": "num", "label": "глубина", "unit": "мм", "step": 0.5},
    "thickness": {"type": "num", "label": "толщина", "unit": "мм", "min": 0.0, "step": 0.2},
    "thick": {"type": "num", "label": "толщина", "unit": "мм", "min": 0.0, "step": 0.2},
    "wall": {"type": "num", "label": "стенка", "unit": "мм", "min": 0.0, "step": 0.2},
    "d": {"type": "num", "label": "диаметр", "unit": "мм", "min": 0.0, "step": 0.5},
    "dz": {"type": "num", "label": "шаг по Z", "unit": "мм", "step": 0.5},
    "dy": {"type": "num", "label": "шаг по Y", "unit": "мм", "step": 0.5},
    "inner": {"type": "num", "label": "внутренний размер", "unit": "мм", "min": 0.0},
    "outer": {"type": "num", "label": "наружный размер", "unit": "мм", "min": 0.0},
    "rim": {"type": "num", "label": "обод", "unit": "мм", "min": 0.0},
    "hub": {"type": "num", "label": "ступица", "unit": "мм", "min": 0.0},
    "tire": {"type": "num", "label": "шина", "unit": "мм", "min": 0.0},
    "bore": {"type": "num", "label": "отверстие", "unit": "мм", "min": 0.0},
    "major": {"type": "num", "label": "большой радиус", "unit": "мм", "min": 0.0},
    "minor": {"type": "num", "label": "малый радиус", "unit": "мм", "min": 0.0},
    "gap": {"type": "num", "label": "зазор", "unit": "мм", "min": 0.0, "step": 0.1},
    "inset": {"type": "num", "label": "заглубление", "unit": "мм", "step": 0.2},
    "flange": {"type": "num", "label": "фланец", "unit": "мм", "min": 0.0},
    "base_d": {"type": "num", "label": "диаметр основания", "unit": "мм", "min": 0.0},
    "base_h": {"type": "num", "label": "высота основания", "unit": "мм", "min": 0.0},
    "head_d": {"type": "num", "label": "диаметр головки", "unit": "мм", "min": 0.0},
    "knob_d": {"type": "num", "label": "диаметр ручки", "unit": "мм", "min": 0.0},
    "chord": {"type": "num", "label": "хорда", "unit": "мм", "min": 0.0},
    "track": {"type": "num", "label": "дорожка", "unit": "мм", "min": 0.0},
    "pitch": {"type": "num", "label": "шаг", "unit": "мм", "step": 0.1},
    "step": {"type": "num", "label": "шаг", "unit": "мм", "step": 0.1},
    "rise": {"type": "num", "label": "подъём", "unit": "мм"},
    "inset_depth": {"type": "num", "label": "глубина посадки", "unit": "мм"},
    # --- форма и поворот ----------------------------------------------------
    "angle": {"type": "num", "label": "угол", "unit": "°", "step": 1.0},
    "base_angle": {"type": "num", "label": "угол в основании", "unit": "°", "step": 1.0},
    "tilt": {"type": "num", "label": "наклон", "unit": "°", "step": 1.0},
    "taper": {"type": "num", "label": "сужение", "unit": "", "min": 0.0, "step": 0.05},
    "twist": {"type": "num", "label": "закрутка", "unit": "°", "step": 1.0},
    "bend": {"type": "num", "label": "изгиб", "unit": "мм"},
    "curl": {"type": "num", "label": "завиток", "unit": "", "step": 0.05},
    "camber": {"type": "num", "label": "выпуклость", "unit": "мм"},
    "sag": {"type": "num", "label": "провис", "unit": "мм"},
    "wave": {"type": "num", "label": "волна", "unit": "мм"},
    "amp": {"type": "num", "label": "амплитуда", "unit": "мм"},
    "curve": {"type": "num", "label": "кривизна", "unit": "", "step": 0.05},
    "openness": {"type": "num", "label": "раскрытие", "unit": "", "step": 0.05},
    "soft": {"type": "num", "label": "мягкость", "unit": "", "step": 0.05},
    "fillet": {"type": "num", "label": "скругление", "unit": "мм", "min": 0.0, "step": 0.2},
    "bevel": {"type": "num", "label": "фаска", "unit": "мм", "min": 0.0, "step": 0.2},
    "round": {"type": "num", "label": "скругление рёбер", "unit": "мм", "min": 0.0,
              "step": 0.2},
    "round_caps": {"type": "num", "label": "скругление торцов", "unit": "мм", "min": 0.0},
    "smooth": {"type": "num", "label": "сглаживание", "unit": "", "min": 0.0, "step": 1.0},
    "detail": {"type": "num", "label": "детализация", "unit": "", "min": 0.0, "step": 1.0},
    "resolution": {"type": "num", "label": "разрешение", "unit": "мм", "min": 0.05,
                   "step": 0.05},
    "tolerance": {"type": "num", "label": "допуск", "unit": "мм", "min": 0.0, "step": 0.01},
    "segments": {"type": "int", "label": "сегментов", "min": 3.0},
    "sides": {"type": "int", "label": "сторон", "min": 3.0},
    "rows": {"type": "int", "label": "рядов", "min": 1.0},
    "cols": {"type": "int", "label": "столбцов", "min": 1.0},
    "count": {"type": "int", "label": "количество", "min": 1.0},
    "parts": {"type": "int", "label": "частей", "min": 1.0},
    "teeth": {"type": "int", "label": "зубьев", "min": 3.0},
    "spokes": {"type": "int", "label": "спиц", "min": 2.0},
    "turns": {"type": "num", "label": "витков", "unit": "", "min": 0.5, "step": 0.5},
    "steps": {"type": "int", "label": "ступеней", "min": 1.0},
    "links": {"type": "int", "label": "звеньев", "min": 1.0},
    "holes": {"type": "int", "label": "отверстий", "min": 0.0},
    "legs": {"type": "int", "label": "ног", "min": 0.0},
    "levels": {"type": "int", "label": "уровней", "min": 1.0},
    "folds": {"type": "int", "label": "сгибов", "min": 1.0},
    "bars": {"type": "int", "label": "перекладин", "min": 0.0},
    "radials": {"type": "int", "label": "радиальных нитей", "min": 1.0},
    "rings": {"type": "num", "label": "колец", "unit": "", "min": 0.0, "step": 1.0},
    "divisions": {"type": "int", "label": "делений", "min": 1.0},
    "per_row": {"type": "int", "label": "в ряду", "min": 1.0},
    "minor_segments": {"type": "int", "label": "сегментов кольца", "min": 3.0},
    "sockets": {"type": "int", "label": "розеток", "min": 1.0},
    "seed": {"type": "int", "label": "зерно случайности", "min": 0.0},
    "wire": {"type": "num", "label": "толщина провода", "unit": "мм", "min": 0.0,
             "step": 0.1},
    "hole": {"type": "num", "label": "отверстие", "unit": "мм", "min": 0.0},
    "frame": {"type": "num", "label": "окантовка", "unit": "мм", "min": 0.0},
    "bar": {"type": "num", "label": "перекладина", "unit": "мм", "min": 0.0},
    "module": {"type": "num", "label": "модуль", "unit": "мм", "min": 0.01, "step": 0.1},
    "tooth": {"type": "num", "label": "зуб", "unit": "мм", "min": 0.0},
    "arm": {"type": "num", "label": "плечо", "unit": "мм", "min": 0.0},
    "leg": {"type": "num", "label": "нога", "unit": "мм", "min": 0.0},
    "cell": {"type": "num", "label": "ячейка", "unit": "мм", "min": 0.0},
    "distance": {"type": "num", "label": "расстояние", "unit": "мм", "min": 0.0},
    "grooves": {"type": "num", "label": "канавок", "unit": "", "min": 0.0},
    "groove_depth": {"type": "num", "label": "глубина канавки", "unit": "мм", "min": 0.0},
    "cavity_depth": {"type": "num", "label": "глубина полости", "unit": "мм", "min": 0.0},
    "line": {"type": "num", "label": "линия", "unit": "мм"},
    "volume": {"type": "flag", "label": "объёмный"},
    "open": {"type": "flag", "label": "открытый"},
    "lock": {"type": "flag", "label": "зафиксировать"},
    "safe": {"type": "flag", "label": "безопасный режим"},
    "thread": {"type": "flag", "label": "резьба"},
    "screws": {"type": "flag", "label": "с крепежом"},
    "elastic": {"type": "flag", "label": "упругая деформация"},
    "axes": {"type": "flag", "label": "показывать оси"},
    "poly": {"type": "flag", "label": "полигональный"},
    "shadows": {"type": "flag", "label": "тени"},
    "ground": {"type": "flag", "label": "пол"},
    # --- материал и вид -----------------------------------------------------
    "color": {"type": "str", "label": "цвет #rrggbb"},
    "emissive": {"type": "str", "label": "свечение #rrggbb"},
    "bg": {"type": "str", "label": "фон #rrggbb"},
    "emissive_strength": {"type": "num", "label": "яркость свечения", "unit": "",
                          "min": 0.0, "step": 0.1},
    "metal": {"type": "num", "label": "металл", "unit": "", "min": 0.0, "max": 1.0,
              "step": 0.05},
    "rough": {"type": "num", "label": "шероховатость", "unit": "", "min": 0.0,
              "max": 1.0, "step": 0.05},
    "transmission": {"type": "num", "label": "прозрачность", "unit": "", "min": 0.0,
                     "max": 1.0, "step": 0.05},
    "strength": {"type": "num", "label": "сила", "unit": "", "min": 0.0, "step": 0.1},
    "exposure": {"type": "num", "label": "экспозиция", "unit": "", "min": 0.0, "step": 0.1},
    "bloom": {"type": "num", "label": "свечение кадра", "unit": "", "min": 0.0, "step": 0.05},
    "seconds": {"type": "num", "label": "секунды", "unit": "с", "min": 0.0, "step": 0.1},
    "density": {"type": "num", "label": "плотность", "unit": "", "min": 0.0, "step": 0.05},
    # --- словари (остаются свободным вводом осознанно) ----------------------
    "material": {"type": "str", "label": "материал"},
    "align": {"type": "str", "label": "выравнивание"},
    "axis": {"type": "str", "label": "ось"},
    "plane": {"type": "str", "label": "плоскость"},
    "path": {"type": "str", "label": "путь"},
    "file": {"type": "str", "label": "файл"},
    "unit": {"type": "str", "label": "единицы"},
    "node": {"type": "str", "label": "узел"},
    "scene": {"type": "str", "label": "сцена"},
    "mode": {"type": "str", "label": "режим"},
    "kind": {"type": "str", "label": "вид"},
    "shape": {"type": "str", "label": "форма"},
    "form": {"type": "str", "label": "форма"},
    "pattern": {"type": "str", "label": "узор"},
    "preset": {"type": "str", "label": "пресет"},
    "label": {"type": "str", "label": "подпись"},
    "text": {"type": "str", "label": "текст"},
    "expression": {"type": "str", "label": "формула"},
    "on": {"type": "str", "label": "на"},
    "as": {"type": "str", "label": "как"},
    "env": {"type": "str", "label": "окружение"},
    "style": {"type": "str", "label": "стиль"},
    "surface": {"type": "str", "label": "поверхность"},
    "section": {"type": "str", "label": "сечение"},
    "sequence": {"type": "str", "label": "последовательность"},
    "state": {"type": "str", "label": "состояние"},
    "type": {"type": "str", "label": "тип"},
    "layout": {"type": "str", "label": "раскладка"},
    "uv": {"type": "str", "label": "UV-развёртка"},
    "edges": {"type": "str", "label": "рёбра"},
    "side": {"type": "str", "label": "сторона"},
    "around": {"type": "str", "label": "вокруг"},
    "drive": {"type": "str", "label": "привод"},
    "object": {"type": "str", "label": "объект"},
    "paths": {"type": "str", "label": "пути"},
    "profile": {"type": "str", "label": "профиль"},
    "outline": {"type": "str", "label": "контур"},
    "spheres": {"type": "str", "label": "сферы"},
    "hole_shape": {"type": "str", "label": "форма отверстия"},
    "edge": {"type": "num", "label": "толщина кромки", "unit": "мм", "min": 0.0, "step": 0.1},
    "edge_band": {"type": "num", "label": "ширина перехода кромки", "unit": "мм",
                  "min": 0.0, "step": 0.1},
    "spread": {"type": "num", "label": "разброс", "unit": "мм", "min": 0.0, "step": 0.5},
    "tail": {"type": "num", "label": "длина хвоста", "unit": "мм", "min": 0.0, "step": 0.5},
    "ribs": {"type": "int", "label": "число рёбер", "unit": "", "min": 0},
    "solid": {"type": "flag", "label": "объёмный вариант"},
    "min": {"type": "num", "label": "минимум", "unit": "", "step": 0.5},
    "max": {"type": "num", "label": "максимум", "unit": "", "step": 0.5},
}


# Хвост имени говорит о смысле параметра: ``head_height`` — высота, ``eye_d`` —
# диаметр, ``plate_color`` — цвет. Правила применяются только к составным
# именам (с подчёркиванием) и только к однозначным окончаниям.
SUFFIXES: tuple[tuple[str, dict], ...] = (
    ("_diameter", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.5, "word": "диаметр"}),
    ("_radius", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.5, "word": "радиус"}),
    ("_height", {"type": "num", "unit": "мм", "step": 0.5, "word": "высота"}),
    ("_width", {"type": "num", "unit": "мм", "step": 0.5, "word": "ширина"}),
    ("_depth", {"type": "num", "unit": "мм", "step": 0.5, "word": "глубина"}),
    ("_length", {"type": "num", "unit": "мм", "step": 0.5, "word": "длина"}),
    ("_thickness", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "толщина"}),
    ("_wall", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "стенка"}),
    ("_angle", {"type": "num", "unit": "°", "step": 1.0, "word": "угол"}),
    ("_gap", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "зазор"}),
    ("_pitch", {"type": "num", "unit": "мм", "min": 0.05, "step": 0.05, "word": "шаг"}),
    ("_step", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "шаг"}),
    ("_offset", {"type": "num", "unit": "мм", "step": 0.1, "word": "смещение"}),
    ("_inset", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "отступ"}),
    ("_margin", {"type": "num", "unit": "мм", "step": 0.5, "word": "припуск"}),
    ("_spacing", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.5, "word": "расстояние"}),
    ("_overlap", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.1, "word": "перекрытие"}),
    ("_count", {"type": "int", "unit": "", "min": 0, "word": "количество"}),
    ("_segments", {"type": "int", "unit": "", "min": 3, "word": "сегментов"}),
    ("_d", {"type": "num", "unit": "мм", "min": 0.0, "step": 0.5, "word": "диаметр"}),
    ("_color", {"type": "str", "word": "цвет"}),
    ("_material", {"type": "str", "word": "материал"}),
)


def _suffix_spec(name: str) -> dict | None:
    for suffix, entry in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            prefix = name[: -len(suffix)].replace("_", " ")
            found = {key: value for key, value in entry.items() if key != "word"}
            found["label"] = f"{entry['word']} ({prefix})"
            return found
    return None


def generic_spec(name: str) -> dict | None:
    """Описание параметра по имени — без привязки к операции.

    Сначала точное имя из ``TYPES``, затем правило по окончанию имени.
    """
    key = str(name or "").strip().lower()
    entry = TYPES.get(key)
    if entry:
        return dict(entry)
    return _suffix_spec(key)
