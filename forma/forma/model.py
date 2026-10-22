"""Модель сцены: объекты, параметры, проверки."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from .errors import DslError
from .geometry import solid_info

PALETTE = [
    "#c9d1e3", "#e8b07a", "#8fd6bd", "#e79aa8",
    "#b3a4e8", "#e6d27a", "#9cc7e8", "#d8dee9",
]


@dataclass
class Solid:
    """Именованный твёрдый объект сцены."""

    name: str
    manifold: Any
    color: str = "#c9d1e3"
    metal: float = 0.0
    rough: float = 0.5
    density: float = 1.24
    visible: bool = True
    kind: str = "solid"
    op: str = ""
    line: int = 0
    notes: list[str] = field(default_factory=list)
    tex: dict | None = None
    uv: str = "cylinder"
    _stats: dict | None = field(default=None, repr=False)

    def stats(self) -> dict:
        if self._stats is None:
            self._stats = solid_info(self.manifold)
        return self._stats

    @property
    def bbox(self) -> list[float]:
        return self.stats()["bbox"]

    @property
    def volume_cm3(self) -> float:
        return self.stats()["volume"] / 1000.0

    @property
    def mass_g(self) -> float:
        return self.volume_cm3 * self.density


DEFAULT_SETTINGS = {
    "bg": "#0b0e13", "env": "studio", "exposure": 1.05, "key": 2.5,
    "fill": 0.75, "rim": 0.5, "shadows": True, "grid": True, "ground": True,
}


class Scene:
    """Сцена скрипта. Хранит объекты по именам, параметры и проверки."""

    def __init__(self):
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.animation: dict | None = None
        self.objects: dict[str, Solid] = {}
        self.params: dict[str, float] = {}
        self.vars: dict[str, Any] = {}
        self.checks: list[dict] = []
        self.logs: list[dict] = []
        self.line = 0
        self.command = ""
        self.op_count = 0
        self.last_replaced: Solid | None = None
        self._auto_idx = 0
        self._color_idx = 0

    # ------------------------------------------------------------------ #
    def log(self, level: str, message: str, line: int | None = None) -> None:
        self.logs.append({"level": level, "message": message,
                          "line": self.line if line is None else line})

    def add(self, solid: Solid) -> Solid:
        self.last_replaced = self.objects.get(solid.name)
        if solid.name in self.objects:
            self.objects.pop(solid.name)
        self.objects[solid.name] = solid
        self.op_count += 1
        return solid

    def remove(self, name: str) -> None:
        self.objects.pop(name, None)

    def get(self, name: str) -> Solid | None:
        return self.objects.get(name)

    def resolve(self, value: Any, what: str = "объект") -> Solid:
        if isinstance(value, Solid):
            return value
        if isinstance(value, str):
            name = value.strip()
            if name in self.objects:
                return self.objects[name]
            names = [n for n in self.objects]
            close = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
            hint = None
            if close:
                hint = "Возможно, вы имели в виду: " + ", ".join(close)
            elif names:
                hint = "Сейчас в сцене: " + ", ".join(names[-12:])
            else:
                hint = "Сцена пока пуста — сначала создайте объект."
            raise DslError(f"Не найден {what} «{name}».", hint=hint)
        raise DslError(f"Ожидалось имя объекта, получено «{value}».")

    def consume(self, solid: Solid) -> None:
        """Прячет объект, вошедший в другой объект (как в дереве построения)."""
        if solid.name in self.objects:
            solid.visible = False
            solid.notes.append("использован в другой фигуре")

    def next_color(self) -> str:
        c = PALETTE[self._color_idx % len(PALETTE)]
        self._color_idx += 1
        return c

    def auto_name(self, base: str = "obj") -> str:
        self._auto_idx += 1
        name = f"{base}{self._auto_idx}"
        while name in self.objects:
            self._auto_idx += 1
            name = f"{base}{self._auto_idx}"
        return name

    def unique_name(self, base: str) -> str:
        if base not in self.objects:
            return base
        i = 2
        while f"{base}_{i}" in self.objects:
            i += 1
        return f"{base}_{i}"

    def visible_solids(self) -> list[Solid]:
        return [s for s in self.objects.values() if s.visible and not s.manifold.is_empty()]

    def all_solids(self) -> list[Solid]:
        return [s for s in self.objects.values() if not s.manifold.is_empty()]

    def summary(self) -> str:
        vis = self.visible_solids()
        return f"{len(vis)} видимых объектов из {len(self.objects)}"
