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

from . import gridfinity

#: имя → (человеческое название, функция-генератор, источник и лицензия)
LIBRARIES: Dict[str, dict] = {
    "gridfinity": {
        "title": "Gridfinity — ящики и плиты 42 мм",
        "build": gridfinity.build_script,
        "source": "gridfinity/gridfinity (MIT) + kennetek/gridfinity-rebuilt-openscad (MIT)",
        "note": "размеры взяты из референса, геометрия пересчитана нашими loft/array",
    },
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
