"""Библиотеки-шаблоны ФОРМЫ: чужие процедурные наборы, переписанные своими средствами.

Зачем отдельная папка. Готовые модели из интернета (GLB/STL/OBJ) — это скульптура:
её можно только уменьшить или починить. А библиотеки-генераторы (Gridfinity,
BOSL2 и подобные) — это формулы с размерами; их переносят как текст, и тогда
объект становится таким же параметрическим, как наши примитивы.

Два способа переноса, оба лежат здесь:

* `.f3d`-файлы (папка ``fastener``) — таблица размеров + фигуры, подключается
  строкой ``включить файл=…``. Работает без Python, правится в блокноте.
* Python-генераторы (``gridfinity``) — когда фигура требует расчёта (скруглённые
  контуры сечений, лофт), генерируется обычный сценарий ФОРМЫ. Сценарий остаётся
  читаемым и правится руками.

Реестр ``LIBRARIES`` нужен команде ``forma lib``: она показывает, что есть, и
собирает сценарий по параметрам.
"""

from __future__ import annotations

from typing import Callable, Dict

from . import gridfinity, objects


def _reference_builder(kind: str):
    """Генератор по имени объекта: `forma lib sword` и т.д."""
    def build(**options) -> str:
        return objects.build_script(kind, **options)
    return build


#: имя → (человеческое название, функция-генератор, источник и лицензия)
LIBRARIES: Dict[str, dict] = {
    "gridfinity": {
        "title": "Gridfinity — ящики и плиты 42 мм",
        "build": gridfinity.build_script,
        "source": "gridfinity/gridfinity (MIT) + kennetek/gridfinity-rebuilt-openscad (MIT)",
        "note": "размеры взяты из референса, геометрия пересчитана нашими loft/array",
    },
}

# Объекты «по референсу»: каждый — отдельная библиотека, чтобы параметры не
# путались. Пропорции взяты из CC0-наборов, геометрия — наша.
_REFERENCE_NOTES = {
    "sword": ("Меч одноручный (клинок, гарда, рукоять, навершие)",
              "типология Оукшотта X–XIV; меши-референсы Quaternius (CC0)"),
    "helmet": ("Шлем кастрюльный (тулья, поля)",
               "габарит сверен со Smithsonian CC0 «French Adrian Helmet»"),
    "chair": ("Стул обеденный (ножки, сиденье, спинка)",
              "нормы мебели; референсы Kenney Furniture Kit (CC0)"),
    "lamp": ("Фонарный столб (цоколь, столб, кронштейн, фонарь)",
             "масштаб сверен с Poly Haven Street Lamp 02 (CC0)"),
    "dagger": ("Кинжал-рондель (клинок-ромб, дисковая гарда)",
               "типология ронделя XIV–XV вв.; Quaternius S_Dagger (CC0)"),
    "axe": ("Топор бородатый (рукоять, проушина, клин со спусками)",
            "пропорции X–XIV вв.; Quaternius S_Axe, S_AxeDouble (CC0)"),
    "shield": ("Щит-утюг (корпус, умбон, ремни)",
               "щит XIII–XV вв.; Quaternius S_ShieldHeater (CC0)"),
    "table": ("Стол обеденный (столешница, ножки, царги)",
              "нормы мебели; Kenney Furniture Kit Table (CC0)"),
    "column": ("Колонна классическая (плита, база, ствол, капитель)",
               "античный ордер; Kenney Column, Quaternius S_ColumnRound (CC0)"),
}
for _kind, (_title, _source) in _REFERENCE_NOTES.items():
    LIBRARIES[_kind] = {
        "title": _title,
        "build": _reference_builder(_kind),
        "source": _source,
        "note": "наши примитивы; каждый размер — параметр",
    }


def names() -> list[str]:
    return sorted(LIBRARIES)


def get(name: str) -> dict:
    key = (name or "").strip().lower()
    if key not in LIBRARIES:
        raise KeyError(name)
    return LIBRARIES[key]


def builder(name: str) -> Callable[..., str]:
    return LIBRARIES[name.strip().lower()]["build"]
