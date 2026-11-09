"""Кэш операций: одна и та же деталь не строится дважды.

Ключ — операция, её параметры (как записаны), точность сцены и значения
параметров сценария. Если операция ссылается на готовый объект, она не
кэшируется: у такой команды результат зависит от входной геометрии, а её
провенанс меняется вместе с родителями.

Кэшируется **геометрия** (``manifold``), а не ``Solid``: цвет, материал и
заметки принадлежат конкретной строке сценария, поэтому на каждый вызов
создаётся новый объект. Иначе покраска одной детали меняла бы все, что
построены из того же кэша.
"""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict

DEFAULT_LIMIT = 512


def enabled() -> bool:
    value = (os.environ.get("FORMA_CACHE") or "").strip().lower()
    return value not in {"0", "off", "false", "no", "нет", "выкл"}


def scene_digest(scene) -> str:
    """Отпечаток того, что влияет на геометрию помимо текста команды."""
    params = sorted((str(key), round(float(value), 6))
                    for key, value in (getattr(scene, "params", {}) or {}).items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool))
    precision = (getattr(scene, "settings", {}) or {}).get("precision") or {}
    settings = sorted((str(key), repr(value)) for key, value in precision.items())
    raw = repr((params, settings))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def references_object(values, objects) -> bool:
    """Ссылается ли команда на готовый объект сцены.

    Достаточно консервативной проверки: имя объекта встречается как отдельное
    слово в значении параметра — значит результат зависит от входной сетки.
    """
    names = set(objects or ())
    if not names:
        return False
    for raw in values:
        text = str(raw)
        if text.strip() in names:
            return True
        for name in names:
            if name and name in text:
                return True
    return False


class OpCache:
    """LRU-кэш геометрии по ключу команды."""

    def __init__(self, limit: int = DEFAULT_LIMIT):
        self.limit = max(4, int(limit))
        self.items: OrderedDict[tuple, object] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.disabled = not enabled()

    def make_key(self, verb: str, kwargs: dict, digest: str) -> tuple:
        pairs = tuple(sorted((str(key), str(value)) for key, value in (kwargs or {}).items()))
        return (str(verb).lower(), pairs, digest)

    def get(self, key):
        if self.disabled:
            return None
        if key in self.items:
            self.items.move_to_end(key)
            self.hits += 1
            return self.items[key]
        self.misses += 1
        return None

    def put(self, key, manifold) -> None:
        if self.disabled or manifold is None:
            return
        self.items[key] = manifold
        self.items.move_to_end(key)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)

    def clear(self) -> None:
        self.items.clear()

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses,
                "size": len(self.items), "limit": self.limit,
                "enabled": not self.disabled}
