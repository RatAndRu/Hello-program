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
    # Свечение: цвет ("" — не светится) и яркость. Светодиод, неон, лампа.
    emissive: str = ""
    emissive_strength: float = 1.0
    # Степень зеркальности 0…1 — свойство материала любого предмета.
    # 0 — обычная поверхность, промежуточные значения усиливают отражение
    # среды, 1 — полное зеркало (для плоских деталей доступен planar-проход).
    # Это явная настройка, а не догадка по металлу и шероховатости.
    mirror: float = 0.0
    # Прозрачность стекла: 0 — плотное тело, 1 — чистое стекло.
    transmission: float = 0.0
    visible: bool = True
    kind: str = "solid"
    op: str = ""
    line: int = 0
    notes: list[str] = field(default_factory=list)
    tex: dict | None = None
    # Покраска частей предмета: [{"color": "#rrggbb", "side": "верх", "box": [...],
    # "height": [a, b], "radius": [a, b]}]. Регион определяется по центру
    # треугольника, поэтому нейросети не нужно перечислять полигоны.
    paint: list[dict] = field(default_factory=list)
    # Свободная роспись кистью: мазки задаются точками в координатах сцены.
    # [{"color": "#rrggbb", "radius": 5, "path": [[x,y,z], …], "erase": False}]
    # Ластик — тот же мазок с "erase": True: он возвращает цвет основания,
    # но не трогает регионы `paint` и материал предмета.
    brush: list[dict] = field(default_factory=list)
    # Служебные сведения о детали (например, у самореза — тип головки и её высота),
    # чтобы сборка «ввернуть» ставила крепёж правильно, а не по габариту.
    meta: dict = field(default_factory=dict)
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
    # аниме/манга-подача: пусто — обычный реалистичный вид
    "anime": {},
}


class Scene:
    """Сцена скрипта. Хранит объекты по именам, параметры и проверки."""

    def __init__(self):
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.animation: dict | None = None
        self.animations: list[dict] = []
        # именованные анимации сцены: «открыть дверь», «выезд ящика», …
        # их может быть сколько угодно; клипы ссылаются на них через scene=
        self.named_animations: list[str] = []
        # ключевые кадры по объектам: {имя: [{t, pos, rot, scale, line}, ...]}
        self.keys: dict[str, list[dict]] = {}
        self.objects: dict[str, Solid] = {}
        # группы объектов: двигаются и вращаются целиком, детали внутри — сами
        self.groups: dict[str, list[str]] = {}
        self.params: dict[str, float] = {}
        self.vars: dict[str, Any] = {}
        self.checks: list[dict] = []
        # пакетные отчёты точных пересечений, выполненные по требованию
        self.interferences: list[dict] = []
        # кубическая сетка-бюджет: какие кубы модель имеет право занимать
        self.grid: dict | None = None
        # сечения, пробы материала и паспорта деталей
        self.sections: list[dict] = []
        self.probes: list[dict] = []
        self.passports: list[dict] = []
        # сопряжения: деталь ставится отношением (плоскость, ось, паз, петля…)
        self.mates: list[dict] = []
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
        self.groups.pop(name, None)
        for members in self.groups.values():
            while name in members:
                members.remove(name)

    def expand(self, value: Any, what: str = "объект") -> list[Solid]:
        """Объект или группа → список объектов."""
        if isinstance(value, str) and value.strip() in self.groups:
            return [self.objects[n] for n in self.groups[value.strip()] if n in self.objects]
        return [self.resolve(value, what)]

    def expand_name(self, name: str) -> list[Solid]:
        return self.expand(name)

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

    def add_named_animation(self, name: str) -> str:
        """Объявляет анимацию сцены (без клипов — просто имя в списке)."""
        name = (name or "").strip()
        if name and name not in self.named_animations:
            self.named_animations.append(name)
        return name

    def add_animation(self, spec: dict) -> dict:
        """Добавляет клип анимации. Клипы с одинаковым track идут друг за другом,
        с разным — параллельно."""
        self.animations.append(spec)
        self.animation = spec
        return spec

    def add_key(self, name: str, spec: dict) -> dict:
        """Ключевой кадр объекта: смещение, поворот и масштаб в момент времени."""
        self.keys.setdefault(name, []).append(spec)
        self.keys[name].sort(key=lambda k: float(k.get("t") or 0.0))
        return spec

    def animation_plan(self, step_count: int = 0) -> dict:
        """Склеивает клипы в тайм-лайн. Клипы одного объекта на одной дорожке идут
        друг за другом, разные объекты и разные дорожки — параллельно;
        ``start`` задаёт время вручную.

        Анимация сборки длится ``hold`` секунд на шаг сценария, морфинг —
        ``seconds``. Ключевые кадры объектов живут на своей дорожке.
        """
        clips: list[dict] = []
        scene_names: list[str] = list(self.named_animations)
        # дорожка + объект: у каждого объекта своя очередь клипов, поэтому
        # движение шкафа и качение его колёсиков идут одновременно
        cursors: dict[tuple[int, str], float] = {}
        for raw in self.animations:
            spec = dict(raw)
            kind = str(spec.get("kind") or "spin").lower()
            track = int(spec.get("track") or 1)
            if kind == "assembly":
                hold = float(spec.get("hold") or 0.8)
                length = max(0.4, hold * max(1, step_count))
            elif kind == "morph":
                length = float(spec.get("seconds") or 3.0)
                samples = int(spec.get("samples") or 12)
                spec["samples"] = max(2, min(samples, 60))
            else:
                length = float(spec.get("seconds") or 4.0)
            start = spec.get("start")
            key = (track, str(spec.get("object") or ""))
            if start is None:
                start = cursors.get(key, 0.0)
            start = max(0.0, float(start))
            scene_name = str(spec.get("scene") or "").strip()
            spec["scene"] = scene_name
            if scene_name and scene_name not in scene_names:
                scene_names.append(scene_name)
            spec["track"] = track
            spec["start"] = round(start, 3)
            spec["length"] = round(length, 3)
            spec["end"] = round(start + length, 3)
            clips.append(spec)
            cursors[key] = max(cursors.get(key, 0.0), start + length)

        keys: list[dict] = []
        for name, items in self.keys.items():
            for item in sorted(items, key=lambda k: float(k.get("t") or 0.0)):
                keys.append({**item, "object": name})
        keys.sort(key=lambda k: float(k.get("t") or 0.0))

        total = max([c["end"] for c in clips]
                    + [float(k.get("t") or 0.0) for k in keys], default=0.0)
        tracks = sorted({c["track"] for c in clips}) if clips else []
        scene_durations = {}
        for name in scene_names:
            scene_durations[name] = round(max(
                (c["end"] for c in clips if c["scene"] == name), default=0.0), 3)
        return {
            "clips": clips,
            "scenes": scene_names,
            "scene_durations": scene_durations,
            "duration": round(total, 3),
            "count": len(clips),
            "has": bool(clips or keys),
            "kinds": [c["kind"] for c in clips],
            "assembly": next((c for c in clips if c["kind"] == "assembly"), None),
            "track_count": len(tracks),
            "tracks": tracks,
            "keys": keys,
            "key_count": len(keys),
            "groups": {g: list(m) for g, m in self.groups.items()},
        }

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
