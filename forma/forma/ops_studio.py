"""Сцена, свет, текстуры и анимация — то, что делает модель «живой».

Команды не меняют геометрию, а настраивают вид: фон, окружение, экспозицию,
силу источников света, процедурную текстуру на объекте и анимацию сцены.
Всё это сохраняется в GLB, поэтому открывается в Blender как есть.
"""

from __future__ import annotations

from .errors import DslError
from .geometry import normalize_color
from .ops import op
from .textures import KIND_NAMES, KINDS, texture_file

ENVIRONMENTS = {
    "студия": "studio", "studio": "studio",
    "солнце": "sun", "день": "sun", "sun": "sun", "day": "sun",
    "закат": "sunset", "sunset": "sunset", "тёплый": "sunset",
    "ночь": "night", "night": "night", "тёмный": "night",
    "мягкий": "soft", "soft": "soft", "нейтральный": "soft",
    "контражур": "back", "back": "back", "силуэт": "back",
    "серый": "grey", "grey": "grey", "gray": "grey", "белый": "white",
    "white": "white", "пусто": "void", "void": "void",
}
LIGHT_PRESETS = {
    "студия": {"env": "studio", "key": 2.5, "fill": 0.75, "rim": 0.5, "ambient": 0.55},
    "studio": {"env": "studio", "key": 2.5, "fill": 0.75, "rim": 0.5, "ambient": 0.55},
    "солнце": {"env": "sun", "key": 3.4, "fill": 0.35, "rim": 0.3, "ambient": 0.35},
    "sun": {"env": "sun", "key": 3.4, "fill": 0.35, "rim": 0.3, "ambient": 0.35},
    "ночь": {"env": "night", "key": 1.5, "fill": 0.5, "rim": 1.1, "ambient": 0.22},
    "night": {"env": "night", "key": 1.5, "fill": 0.5, "rim": 1.1, "ambient": 0.22},
    "мягкий": {"env": "soft", "key": 1.9, "fill": 1.05, "rim": 0.6, "ambient": 0.7},
    "soft": {"env": "soft", "key": 1.9, "fill": 1.05, "rim": 0.6, "ambient": 0.7},
    "контражур": {"env": "back", "key": 1.2, "fill": 0.4, "rim": 2.2, "ambient": 0.3},
    "back": {"env": "back", "key": 1.2, "fill": 0.4, "rim": 2.2, "ambient": 0.3},
    "портрет": {"env": "studio", "key": 2.2, "fill": 0.9, "rim": 0.8, "ambient": 0.6},
    "portrait": {"env": "studio", "key": 2.2, "fill": 0.9, "rim": 0.8, "ambient": 0.6},
}
ANIMATIONS = {
    "spin": "spin", "вращение": "spin", "поворот": "spin", "turntable": "spin",
    "formation": "formation", "сборка": "formation", "рост": "formation",
    "появление": "formation", "build": "formation",
    "explode": "explode", "разлёт": "explode", "разлет": "explode",
    "взрыв": "explode", "разнесение": "explode",
}


@op("scene", aliases=("сцена", "окружение", "фон", "view"), category="Сцена и материал",
    summary="Настраивает вид сцены: фон, окружение, экспозицию, тени и сетку.",
    example="scene bg=#0b0e13 env=studio exposure=1.05 shadows=да grid=да",
    params={"bg": "цвет фона #RRGGBB или название",
            "env": "студия, солнце, закат, ночь, мягкий, контражур, серый, белый",
            "exposure": "экспозиция (1.0 — нейтрально)",
            "shadows": "тени да/нет", "grid": "сетка да/нет",
            "ground": "показывать пол да/нет"})
def scene(a, name):
    s = a.scene.settings
    if a.has("bg"):
        s["bg"] = normalize_color(a.text("bg") or "")
    if a.has("env"):
        raw = (a.text("env") or "").strip().lower()
        if raw not in ENVIRONMENTS:
            raise DslError(f"Неизвестное окружение «{raw}».",
                           hint="Доступно: " + ", ".join(sorted(set(ENVIRONMENTS.values()))),
                           line=a.cmd.line, command=a.cmd.text)
        s["env"] = ENVIRONMENTS[raw]
    if a.has("exposure"):
        s["exposure"] = max(0.15, min(4.0, float(a.num("exposure") or 1.0)))
    for key in ("shadows", "grid", "ground"):
        if a.has(key):
            s[key] = a.boolean(key, True)
    a.scene.log("info", "вид сцены обновлён", a.cmd.line)
    return None


@op("light", aliases=("свет", "освещение", "lights"), category="Сцена и материал",
    summary="Ставит свет: пресеты студия/солнце/ночь/мягкий/контражур или свои силы источников.",
    example="light preset=студия strength=1.1",
    params={"preset": "студия, солнце, ночь, мягкий, контражур, портрет",
            "strength": "общая яркость (множитель)",
            "key": "сила основного света", "fill": "сила заполняющего",
            "rim": "сила контрового", "ambient": "сила рассеянного",
            "shadows": "тени да/нет", "env": "окружение для отражений"})
def light(a, name):
    s = a.scene.settings
    preset = (a.text("preset") or "студия").strip().lower()
    if preset not in LIGHT_PRESETS:
        raise DslError(f"Неизвестный пресет света «{preset}».",
                       hint="Доступно: студия, солнце, ночь, мягкий, контражур, портрет",
                       line=a.cmd.line, command=a.cmd.text)
    base = dict(LIGHT_PRESETS[preset])
    strength = float(a.num("strength", 1.0) or 1.0)
    for key in ("key", "fill", "rim", "ambient"):
        s[key] = base[key] * strength
    s["env"] = base["env"]
    if a.has("env"):
        raw = (a.text("env") or "").strip().lower()
        if raw in ENVIRONMENTS:
            s["env"] = ENVIRONMENTS[raw]
    if a.has("key"):
        s["key"] = float(a.num("key") or s["key"])
    if a.has("fill"):
        s["fill"] = float(a.num("fill") or s["fill"])
    if a.has("rim"):
        s["rim"] = float(a.num("rim") or s["rim"])
    if a.has("ambient"):
        s["ambient"] = float(a.num("ambient") or s.get("ambient", 0.55))
    if a.has("shadows"):
        s["shadows"] = a.boolean("shadows", True)
    a.scene.log("info", f"свет: {preset}", a.cmd.line)
    return None


@op("texture", aliases=("текстура", "материал-текстура", "tex"), category="Сцена и материал",
    summary="Накладывает процедурную текстуру: дерево, мрамор, металл, ткань, кожу, кирпич.",
    example="texture кружка kind=дерево scale=1.2",
    params={"target": "имя объекта или all",
            "kind": "дерево, мрамор, металл, ткань, кожа, клетка, шум, кирпич, керамика",
            "scale": "масштаб рисунка", "seed": "число или строка для вариации",
            "uv": "cylinder (вокруг), planar (плоско), box (по граням)",
            "size": "размер картинки в пикселях (512)"},
    positional=["target"])
def texture(a, name):
    target = (a.text("target") or "").strip()
    if not target:
        raise DslError("Укажите объект: texture кружка kind=дерево",
                       line=a.cmd.line, command=a.cmd.text)
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        [a.scene.resolve(target)]
    kind = (a.text("kind") or "дерево").strip().lower()
    if kind not in KINDS:
        raise DslError(f"Неизвестная текстура «{kind}».",
                       hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values())),
                       line=a.cmd.line, command=a.cmd.text)
    scale = float(a.num("scale", 1.0) or 1.0)
    seed = a.text("seed") or "1"
    uv = (a.text("uv") or "cylinder").strip().lower()
    if uv not in ("cylinder", "planar", "box"):
        raise DslError("Параметр uv: cylinder, planar или box.",
                       line=a.cmd.line, command=a.cmd.text)
    size = int(a.num("size", 512) or 512)
    info = texture_file(kind, scale=scale, seed=seed, size=size)
    for solid in targets:
        solid.tex = info
        solid.uv = uv
        if solid.color == "#c9d1e3":
            solid.color = "#ffffff"
    a.scene.log("info", f"текстура {KIND_NAMES.get(info['kind'], kind)}: "
                        f"{', '.join(s.name for s in targets)}", a.cmd.line)
    return None


@op("animate", aliases=("анимация", "движение", "animation"), category="Сцена и материал",
    summary="Задаёт анимацию: вращение, формирование из нуля или разлёт на части; "
            "сохраняется в GLB для Blender.",
    example="animate kind=spin axis=z seconds=6 loop=да",
    params={"kind": "spin (вращение), formation (сборка/рост), explode (разлёт)",
            "axis": "ось вращения x, y или z", "seconds": "длительность, с",
            "loop": "зациклить да/нет", "amount": "разлёт: расстояние в мм",
            "steps": "число ключей анимации"})
def animate(a, name):
    kind_raw = (a.text("kind") or "spin").strip().lower()
    if kind_raw not in ANIMATIONS:
        raise DslError(f"Неизвестная анимация «{kind_raw}».",
                       hint="Доступно: spin, formation, explode",
                       line=a.cmd.line, command=a.cmd.text)
    kind = ANIMATIONS[kind_raw]
    axis = (a.text("axis") or "z").strip().lower()
    if axis not in ("x", "y", "z"):
        raise DslError("Ось анимации: x, y или z.", line=a.cmd.line, command=a.cmd.text)
    seconds = float(a.num("seconds", 4.0) or 4.0)
    seconds = max(0.4, min(seconds, 600.0))
    spec = {"kind": kind, "axis": axis, "seconds": seconds,
            "loop": a.boolean("loop", True),
            "steps": int(a.num("steps", 48) or 48)}
    if a.has("amount"):
        spec["amount"] = float(a.num("amount") or 0.0)
    a.scene.animation = spec
    a.scene.log("info", f"анимация: {kind}, {seconds:g} с", a.cmd.line)
    return None
