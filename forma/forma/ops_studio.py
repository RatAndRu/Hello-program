"""Сцена, свет, текстуры и анимация — то, что делает модель «живой».

Команды не меняют геометрию, а настраивают вид: фон, окружение, экспозицию,
силу источников света, процедурную текстуру на объекте и анимацию сцены.
Всё это сохраняется в GLB, поэтому открывается в Blender как есть.
"""

from __future__ import annotations

from .errors import DslError
from .geometry import normalize_color
from .ops import op
from .textures import (KIND_NAMES, KINDS, PATTERN_NAMES, PATTERNS,
                       custom_texture_file, texture_file)

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
    "formation": "formation", "рост": "formation", "формирование": "formation",
    "появление": "formation", "growth": "formation",
    "explode": "explode", "разлёт": "explode", "разлет": "explode",
    "взрыв": "explode", "разнесение": "explode",
    "assembly": "assembly", "сборка": "assembly", "шаги": "assembly",
    "пошагово": "assembly", "steps": "assembly", "по_шагам": "assembly",
}

KIND_NAMES_ANIM = {"spin": "вращение", "formation": "формирование",
                   "explode": "разлёт", "assembly": "сборка по шагам"}


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
            "kind": "дерево, мрамор, металл, ткань, кожа, клетка, шум, кирпич, "
                    "керамика или своя",
            "scale": "масштаб рисунка", "seed": "число или строка для вариации",
            "uv": "cylinder (вокруг), planar (плоско), box (по граням)",
            "size": "размер картинки в пикселях (512)",
            "pattern": "для своей текстуры: полосы, клетка, волны, градиент, "
                       "шум, камень, точки, сетка",
            "color1": "для своей текстуры: первый цвет (#rrggbb или название)",
            "color2": "для своей текстуры: второй цвет"},
    positional=["target"])
def texture(a, name):
    target = (a.text("target") or "").strip()
    if not target:
        raise DslError("Укажите объект: texture кружка kind=дерево",
                       line=a.cmd.line, command=a.cmd.text)
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        [a.scene.resolve(target)]
    kind = (a.text("kind") or "дерево").strip().lower()
    scale = float(a.num("scale", 1.0) or 1.0)
    seed = a.text("seed") or "1"
    uv = (a.text("uv") or "cylinder").strip().lower()
    if uv not in ("cylinder", "planar", "box"):
        raise DslError("Параметр uv: cylinder, planar или box.",
                       line=a.cmd.line, command=a.cmd.text)
    size = int(a.num("size", 512) or 512)
    if kind in ("своя", "своё", "свое", "custom", "мой"):
        pattern = (a.text("pattern") or "полосы").strip().lower()
        if pattern not in PATTERNS:
            raise DslError(f"Неизвестный узор «{pattern}».",
                           hint="Доступно: " + ", ".join(sorted(PATTERN_NAMES.values())),
                           line=a.cmd.line, command=a.cmd.text)
        info = custom_texture_file(
            pattern=pattern,
            color1=(a.text("color1") or "#3a6ea5"),
            color2=(a.text("color2") or "#e8dfcf"),
            scale=scale, seed=seed, size=size)
    else:
        if kind not in KINDS:
            raise DslError(f"Неизвестная текстура «{kind}».",
                           hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values()))
                                + ", а также своя",
                           line=a.cmd.line, command=a.cmd.text)
        info = texture_file(kind, scale=scale, seed=seed, size=size)
    for solid in targets:
        solid.tex = info
        solid.uv = uv
        if solid.color == "#c9d1e3":
            solid.color = "#ffffff"
    a.scene.log("info", f"текстура {info.get('label') or KIND_NAMES.get(info['kind'], kind)}: "
                        f"{', '.join(s.name for s in targets)}", a.cmd.line)
    return None


@op("animate", aliases=("анимация", "движение", "animation"), category="Сцена и материал",
    summary="Добавляет клип анимации: вращение, формирование, разлёт или сборка по шагам "
            "сценария. Строк animate может быть несколько — клипы идут друг за другом.",
    example="animate kind=spin axis=z seconds=6 loop=да",
    positional=["kind"],
    params={"kind": "spin, formation, explode или assembly (сборка по шагам)",
            "axis": "ось вращения x, y или z", "seconds": "длительность клипа, с",
            "start": "с какой секунды начинать (иначе — сразу за предыдущим клипом)",
            "loop": "зациклить да/нет", "amount": "разлёт: расстояние в мм",
            "steps": "число ключей анимации", "fps": "кадров в секунду для покадрового просмотра",
            "hold": "сборка: секунд на один шаг сценария"})
def animate(a, name):
    kind_raw = (a.text("kind") or "spin").strip().lower()
    if kind_raw not in ANIMATIONS:
        raise DslError(f"Неизвестная анимация «{kind_raw}».",
                       hint="Доступно: spin (вращение), formation (формирование), "
                            "explode (разлёт), assembly (сборка по шагам)",
                       line=a.cmd.line, command=a.cmd.text)
    kind = ANIMATIONS[kind_raw]
    axis = (a.text("axis") or "z").strip().lower()
    if axis not in ("x", "y", "z"):
        raise DslError("Ось анимации: x, y или z.", line=a.cmd.line, command=a.cmd.text)
    default_seconds = {"spin": 6.0, "formation": 4.0, "explode": 3.0, "assembly": 0.8}[kind]
    seconds = float(a.num("seconds", default_seconds) or default_seconds)
    seconds = max(0.2, min(seconds, 600.0))
    start_at = None
    for key in ("start", "at", "from"):
        if a.has(key):
            start_at = float(a.num(key) or 0.0)
            start_at = max(0.0, min(start_at, 3600.0))
            break
    fps = int(a.num("fps", 24) or 24)
    fps = max(1, min(fps, 60))
    steps = int(a.num("steps", 48) or 48)
    spec = {"kind": kind, "seconds": seconds, "fps": fps,
            "loop": a.boolean("loop", True),
            "steps": max(2, min(steps, 600)),
            "axis": axis, "start": start_at,
            "line": a.cmd.line, "text": a.cmd.text}
    if kind == "assembly":
        spec["hold"] = max(0.1, min(float(a.num("hold", seconds) or seconds), 30.0))
        spec["seconds"] = spec["hold"]
    if a.has("amount"):
        spec["amount"] = float(a.num("amount") or 0.0)
    a.scene.add_animation(spec)
    if kind == "assembly":
        a.scene.log("info", f"анимация сборки: {spec['hold']:g} с на шаг сценария", a.cmd.line)
    else:
        a.scene.log("info", f"анимация: {KIND_NAMES_ANIM.get(kind, kind)}, {seconds:g} с",
                    a.cmd.line)
    return None
