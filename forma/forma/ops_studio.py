"""Сцена, свет, текстуры и анимация — то, что делает модель «живой».

Команды не меняют геометрию, а настраивают вид: фон, окружение, экспозицию,
силу источников света, процедурную текстуру на объекте и анимацию сцены.
Всё это сохраняется в GLB, поэтому открывается в Blender как есть.
"""

from __future__ import annotations

import math

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
    "move": "move", "перенос": "move", "перемещение": "move", "сдвиг": "move",
    "shift": "move", "движение": "move",
    "scale": "scale", "размер": "scale", "масштаб": "scale", "рост_размер": "scale",
    "turn": "turn", "доворот": "turn", "наклон": "turn", "tilt": "turn",
    "rotation": "turn",
    "wait": "wait", "пауза": "wait", "ожидание": "wait", "задержка": "wait",
    "morph": "morph", "морф": "morph", "морфинг": "morph",
    "изменение": "morph", "форма": "morph", "shape": "morph",
    "roll": "roll", "качение": "roll", "катить": "roll", "rolling": "roll",
    "jump": "jump", "прыжок": "jump", "прыгать": "jump", "подскок": "jump",
    "fall": "fall", "падение": "fall", "падать": "fall", "упасть": "fall",
    "fan": "fan", "вентилятор": "fan", "турбина": "fan", "пропеллер": "fan",
    "открыть": "turn", "закрыть": "turn", "open": "turn", "close": "turn",
}

KIND_NAMES_ANIM = {"spin": "вращение", "formation": "формирование",
                   "explode": "разлёт", "assembly": "сборка по шагам",
                   "move": "перемещение", "scale": "масштаб", "turn": "доворот",
                   "wait": "пауза", "morph": "изменение формы",
                   "roll": "качение", "jump": "прыжок", "fall": "падение",
                   "fan": "вращение вентилятора"}


@op("scene", aliases=("сцена", "окружение", "фон", "view"), category="Сцена и материал",
    summary="Настраивает вид сцены: фон, окружение, экспозицию, тени, сетку, "
            "оси, полигонаж и силу свечения. Всё это сохраняется в проекте.",
    example='к = box size=[40,40,40]\nscene bg=#0b0e13 env=studio exposure=1.05 '
            'shadows=да grid=да axes=да poly=нет bloom=0.55',
    params={"bg": "цвет фона #RRGGBB или название",
            "env": "студия, солнце, закат, ночь, мягкий, контражур, серый, белый",
            "exposure": "экспозиция (1.0 — нейтрально)",
            "shadows": "тени да/нет", "grid": "сетка да/нет",
            "ground": "показывать пол да/нет",
            "axes": "оси координат да/нет",
            "poly": "полигонаж (каркас) да/нет",
            "bloom": "сила свечения светодиодов 0…3 (0 — выключено)"})
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
    for key in ("shadows", "grid", "ground", "axes", "poly"):
        if a.has(key):
            s[key] = a.boolean(key, True)
    if a.has("bloom"):
        s["bloom"] = max(0.0, min(3.0, float(a.num("bloom") or 0.0)))
    a.scene.log("info", "вид сцены обновлён", a.cmd.line)
    return None


@op("light", aliases=("свет", "освещение", "lights"), category="Сцена и материал",
    summary="Ставит свет: пресеты студия/солнце/ночь/мягкий/контражур или свои силы источников.",
    example='к = box size=[40,40,40]\nlight preset=студия strength=1.1',
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


@op("anime", aliases=("аниме", "манга", "стиль", "контур", "контуры", "обводка", "toon"),
    category="Сцена и материал",
    summary="Аниме/манга-подача: настоящие контуры по форме (силуэт, изломы, стыки "
            "деталей), ступени тона и растр. Работает и в окне, и в PNG-снимках, "
            "и в GLB. mode=аниме — цвет с чёрным контуром; манга — чёрно-белое с "
            "растром; комикс — толстый контур и точки в тенях; линия — только "
            "контуры на бумаге; выкл — обычный вид. line — толщина линии в пикселях, "
            "crease — угол, начиная с которого рисуется внутренний контур (рёбра, "
            "складки, фаски), seams — отдельная линия на стыке деталей.",
    example='ваза = lathe points=[[0,0],[26,0],[40,30],[30,62],[16,90],[0,92]]\n'
            'шар = sphere radius=30 at=[70,0,30]\n'
            'anime mode=аниме line=1.8 crease=32\n'
            'обводка = anime mode=манга line=2.2 tone=0.8 paper=#ffffff',
    params={"mode": "аниме, манга, комикс, линия или выкл — «аниме»",
            "line": "толщина контура, px (1.6)",
            "color": "цвет линий (#101018)",
            "inner": "внутренние контуры: рёбра и складки (да)",
            "crease": "угол излома для внутреннего контура, градусы (32)",
            "depth": "порог перепада глубины 0.0005…0.6 (0.035)",
            "seams": "контур на стыке отдельных деталей (да)",
            "toon": "ступеней тона 0…8 (3)",
            "tone": "сила растра 0…1 (манга 0.75)",
            "paper": "цвет бумаги (#f4f6fa) или сцена — фон сцены",
            "shade": "затенять поверхность да/нет (да; нет — только контур)",
            "off": "да — выключить стиль"},
    positional=[])
def anime(a, name):
    from .anime import style_from_args
    style = style_from_args(a)
    a.scene.settings["anime"] = style
    mode = style["mode"]
    if mode == "выкл":
        a.scene.log("info", "аниме-стиль выключен", a.cmd.line)
    else:
        a.scene.log("info", f"стиль «{mode}»: контур {style['line']:g} px, "
                            f"излом {style['crease']:g}°, тонов {style['toon']}",
                    a.cmd.line)
    return None


@op("texture", aliases=("текстура", "материал-текстура", "tex"), category="Сцена и материал",
    summary="Накладывает процедурную текстуру: дерево, мрамор, металл, ткань, кожу, кирпич.",
    example='кружка = cylinder radius=40 height=95\ntexture кружка kind=дерево scale=1.2',
    params={"target": "имя объекта или all",
            "kind": "дерево, мрамор, металл, ткань, кожа, клетка, шум, кирпич, "
                    "керамика или своя",
            "scale": "масштаб рисунка", "seed": "число или строка для вариации",
            "uv": "auto (бесшовно по граням), atlas (атлас: каждая грань — свой остров), "
                  "cylinder (вокруг), planar (плоско), box",
            "size": "размер картинки в пикселях (512)",
            "pattern": "для своей текстуры: полосы, клетка, волны, градиент, "
                       "шум, камень, точки, сетка",
            "color1": "для своей текстуры: первый цвет (#rrggbb или название)",
            "color2": "для своей текстуры: второй цвет",
            "relief": "для своей текстуры: рельеф 0…1 (0 — гладкая, 0.5 — заметный)"},
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
    explicit_uv = a.has("uv")
    uv = (a.text("uv") or "").strip().lower()
    if uv in ("авто", "грани", "triplanar"):
        uv = "auto"
    if uv in ("атлас", "атласная", "atlas", "развёртка"):
        uv = "atlas"
    if uv and uv not in ("auto", "atlas", "cylinder", "planar", "box"):
        raise DslError("Параметр uv: auto (бесшовно), atlas (атлас), cylinder, "
                       "planar или box.",
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
            scale=scale, seed=seed, size=size,
            relief=float(a.num("relief", 0.0, minv=0.0, maxv=1.0) or 0.0))
    else:
        if kind not in KINDS:
            raise DslError(f"Неизвестная текстура «{kind}».",
                           hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values()))
                                + ", а также своя",
                           line=a.cmd.line, command=a.cmd.text)
        info = texture_file(kind, scale=scale, seed=seed, size=size)
    # 0.22: если uv не задан руками — развёртку выбирает материал:
    # металлу, ткани и коже — атлас, дереву, мрамору и кирпичу — auto.
    if not explicit_uv:
        from .textures import preferred_uv, uv_reason
        pattern = info.get("pattern") if info.get("kind") == "custom" else None
        uv = preferred_uv(info.get("kind"), pattern)
        reason = uv_reason(info.get("kind"), pattern)
    else:
        reason = ""
    for solid in targets:
        solid.tex = info
        solid.uv = uv
        if solid.color == "#c9d1e3":
            solid.color = "#ffffff"
    a.scene.log("info", f"текстура {info.get('label') or KIND_NAMES.get(info['kind'], kind)}: "
                        f"{', '.join(s.name for s in targets)}"
                        + (f"; развёртка: {reason}" if reason else ""), a.cmd.line)
    return None


@op("animate", aliases=("анимация", "движение", "animation"), category="Сцена и материал",
    summary="Добавляет клип анимации: вращение, формирование, разлёт, перемещение, "
            "масштаб, доворот, пауза, сборка по шагам или изменение формы. "
            "Клипы одного track идут друг за другом, разные track — параллельно.",
    example='к = box size=[40,40,40]\nanimate kind=spin axis=z seconds=6 track=1\nanimate kind=move dz=40 seconds=2 track=1\nanimate kind=scale to=1.4 seconds=2 track=1',
    positional="*",
    params={"kind": "spin, formation, explode, move, scale, turn, wait, assembly, morph, roll, "
                    "jump, fall, fan",
            "axis": "ось: x, y, z (можно -x, -y, -z); z — вверх",
            "seconds": "длительность клипа, с", "duration": "то же, что seconds",
            "start": "с какой секунды начинать (иначе — за предыдущим клипом дорожки)",
            "loop": "зациклить да/нет", "amount": "разлёт: расстояние в мм",
            "steps": "число ключей анимации", "fps": "кадров в секунду",
            "hold": "сборка: секунд на один шаг сценария",
            "track": "дорожка 1…8: клипы одной дорожки идут подряд, разных — параллельно",
            "object": "объект для move/scale (иначе — вся модель)",
            "dx": "move: смещение по X, мм", "dy": "move: смещение по Y, мм",
            "dz": "move: смещение по Z, мм", "to": "move: куда переместить центр [x,y,z]; "
            "scale: во сколько раз увеличить (2 = вдвое)",
            "from": "scale/morph: начальное значение", "angle": "turn: угол поворота, градусы",
            "param": "morph: имя параметра сценария (R, H, …)",
            "samples": "morph: сколько кадров геометрии построить (12)",
            "pivot": "точка вращения [x,y,z]: дверная петля, ось колеса и т.п.",
            "turns": "spin: сколько полных оборотов (1)",
            "distance": "roll: путь качения, мм", "radius": "roll: радиус колеса, мм",
            "height": "jump/fall: высота прыжка или падения, мм",
            "elastic": "jump/fall: упругое сжатие да/нет",
            "rpm": "fan: оборотов в минуту (900)",
            "scene_name": "сцена-вариант: имя заготовки (дверь, ящик, …)",
            "scene": "то же, что scene_name"})
def animate(a, name):
    # Порядок слов свободный: animate дверь turn angle=…, animate turn object=дверь
    words = [str(w).strip() for w in a.extra if str(w).strip()]
    kind_raw = (a.text("kind") or "").strip().lower()
    if not kind_raw:
        for w in list(words):
            if w.lower() in ANIMATIONS:
                kind_raw = w.lower()
                words.remove(w)
                break
    if not kind_raw:
        kind_raw = "spin"
    object_raw = (a.text("object") or "").strip()
    if not object_raw:
        for w in list(words):
            if w in a.scene.groups or w in a.scene.objects:
                object_raw = w
                words.remove(w)
                break
    if words:
        raise DslError(f"Лишний аргумент «{words[0]}» у команды animate.",
                       hint="Пишите: animate [объект] [вид] параметры — например "
                            "animate дверь turn angle=100 axis=z pivot=[-481,216,0]",
                       line=a.cmd.line, command=a.cmd.text)
    if kind_raw not in ANIMATIONS:
        raise DslError(f"Неизвестная анимация «{kind_raw}».",
                       hint="Доступно: spin (вращение), formation (рост), explode (разлёт), "
                            "move (перемещение), scale (масштаб), turn (доворот), "
                            "wait (пауза), assembly (сборка по шагам), morph (изменение формы)",
                       line=a.cmd.line, command=a.cmd.text)
    kind = ANIMATIONS[kind_raw]
    axis_raw = (a.text("axis") or "z").strip().lower().replace(" ", "")
    sign = 1.0
    if axis_raw.startswith("-"):
        sign, axis_raw = -1.0, axis_raw[1:]
    elif axis_raw.startswith("+"):
        axis_raw = axis_raw[1:]
    elif axis_raw.endswith("-"):
        sign, axis_raw = -1.0, axis_raw[:-1]
    elif axis_raw.endswith("+"):
        axis_raw = axis_raw[:-1]
    if axis_raw not in ("x", "y", "z"):
        raise DslError(f"Ось анимации «{a.text('axis')}» не понята.",
                       hint="Ось задаётся буквой: x, y или z. Z — вверх (высота модели), "
                            "X — влево/вправо, Y — глубина. Знак: axis=-z крутит в другую сторону.",
                       line=a.cmd.line, command=a.cmd.text)
    track = int(a.num("track", 1) or 1)
    if track < 1 or track > 8:
        raise DslError(f"Дорожка {track} вне диапазона 1…8.",
                       hint="Клипы на одной дорожке идут друг за другом, на разных — "
                            "одновременно. Всего дорожек восемь.",
                       line=a.cmd.line, command=a.cmd.text)
    default_seconds = {"spin": 6.0, "formation": 4.0, "explode": 3.0, "assembly": 0.8,
                       "move": 2.0, "scale": 2.0, "turn": 2.0, "wait": 1.0,
                       "morph": 3.0, "roll": 2.0, "jump": 1.2, "fall": 1.4,
                       "fan": 3.0}[kind]
    seconds = float(a.num("seconds", a.num("duration", default_seconds)) or default_seconds)
    seconds = max(0.2, min(seconds, 600.0))
    start_at = None
    for key in ("start", "at"):
        if a.has(key):
            start_at = float(a.num(key) or 0.0)
            start_at = max(0.0, min(start_at, 3600.0))
            break
    fps = int(a.num("fps", 24) or 24)
    fps = max(1, min(fps, 60))
    steps = int(a.num("steps", 48) or 48)
    scene_name = (a.text("scene_name") or a.text("scene") or "").strip()
    if scene_name.lower() in ("все", "все сцены", "all", "*", "любая"):
        scene_name = ""   # общий клип: виден в любой анимации
    if scene_name:
        # любая названная анимация регистрируется сама: отдельно объявлять
        # её командой «анимация …» не обязательно (но можно — так список
        # анимаций остаётся упорядоченным и видным до первого клипа)
        scene_name = scene_name.replace(" ", "_")
        a.scene.add_named_animation(scene_name)
    spec = {"kind": kind, "seconds": seconds, "fps": fps,
            "loop": a.boolean("loop", True),
            "steps": max(2, min(steps, 600)),
            "axis": axis_raw, "axis_sign": sign, "start": start_at,
            "track": track, "line": a.cmd.line, "text": a.cmd.text}
    if scene_name:
        spec["scene"] = scene_name

    target = None
    target_solids = []
    if object_raw:
        raw = object_raw
        if raw in a.scene.groups:
            # группа: двигается целиком, детали внутри могут двигаться сами
            spec["object"] = raw
            spec["target_kind"] = "group"
            target_solids = a.scene.expand(raw)
        else:
            target = a.scene.resolve(raw)
            spec["object"] = target.name
            target_solids = [target]

    if a.has("pivot"):
        if not target and not target_solids:
            raise DslError("pivot задаёт точку вращения объекта — укажите object=…",
                           hint="Например: animate фасад_л turn angle=100 axis=z "
                                "pivot=[-481,216,0]",
                           line=a.cmd.line, command=a.cmd.text)
        pivot = a.vec("pivot", 3, required=True)
        spec["pivot"] = [float(v) for v in pivot]

    if kind == "assembly":
        spec["hold"] = max(0.1, min(float(a.num("hold", seconds) or seconds), 30.0))
        spec["seconds"] = spec["hold"]
    elif kind in ("explode",):
        if a.has("amount"):
            spec["amount"] = float(a.num("amount") or 0.0)
    elif kind == "move":
        if a.has("to"):
            to = a.vec("to", 3, required=True)
            if target_solids:
                boxes = [s.manifold.bounding_box() for s in target_solids]
                lo = [min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes)]
                hi = [max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes)]
                cur = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
            else:
                visible = a.scene.visible_solids()
                if not visible:
                    raise DslError("Нечего перемещать: в сцене нет видимых объектов.",
                                   line=a.cmd.line, command=a.cmd.text)
                boxes = [s.manifold.bounding_box() for s in visible]
                lo = [min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes)]
                hi = [max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes)]
                cur = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
            spec["delta"] = [float(to[i] - cur[i]) for i in range(3)]
        else:
            spec["delta"] = [float(a.num("dx", 0.0) or 0.0),
                             float(a.num("dy", 0.0) or 0.0),
                             float(a.num("dz", 0.0) or 0.0)]
        if not any(abs(v) > 1e-9 for v in spec["delta"]):
            raise DslError("Куда перемещать? Укажите dx/dy/dz или to=[x,y,z].",
                           hint="Например: animate kind=move dz=40 seconds=2",
                           line=a.cmd.line, command=a.cmd.text)
    elif kind == "scale":
        spec["from"] = float(a.num("from", 1.0) or 1.0)
        spec["to"] = float(a.num("to", 1.5) or 1.5)
        if abs(spec["to"] - spec["from"]) < 1e-9:
            raise DslError("Масштаб не меняется: from и to равны.",
                           line=a.cmd.line, command=a.cmd.text)
    elif kind == "turn":
        spec["angle"] = float(a.num("angle", 90.0) or 90.0) * sign
    elif kind == "spin":
        spec["turns"] = float(a.num("turns", 1.0) or 1.0)
    elif kind == "roll":
        distance = float(a.num("distance", 0.0) or 0.0)
        radius = float(a.num("radius", 0.0) or 0.0)
        if abs(distance) < 1e-9:
            raise DslError("roll: укажите distance= — на сколько миллиметров катится колесо.",
                           hint="Например: animate колесо roll distance=250 radius=15 axis=x",
                           line=a.cmd.line, command=a.cmd.text)
        if radius <= 1e-9:
            raise DslError("roll: укажите radius= — радиус колеса в мм.",
                           hint="Например: animate колесо roll distance=250 radius=15 axis=x",
                           line=a.cmd.line, command=a.cmd.text)
        # угол качения = путь / радиус; знак задаётся осью (axis=-x)
        spec["radians"] = (distance / radius) * sign
        spec["distance"] = distance
        spec["radius"] = radius
    elif kind in ("jump", "fall"):
        default_h = 60.0 if kind == "jump" else 200.0
        spec["height"] = max(0.5, float(a.num("height", default_h) or default_h))
        spec["elastic"] = a.boolean("elastic", True)
    elif kind == "fan":
        rpm = float(a.num("rpm", 900.0) or 900.0)
        rpm = max(1.0, min(rpm, 20000.0))
        spec["rpm"] = rpm
        spec["turns"] = rpm * seconds / 60.0
        spec["loop"] = a.boolean("loop", True)
    elif kind == "morph":
        param = (a.text("param") or "").strip()
        if not param:
            raise DslError("morph меняет геометрию через параметр сценария.",
                           hint="Сначала объявите параметр: R = 42, затем "
                                "animate kind=morph param=R from=35 to=50 seconds=3",
                           line=a.cmd.line, command=a.cmd.text)
        if param not in a.scene.params:
            raise DslError(f"Параметр «{param}» не найден в сценарии.",
                           hint="Параметры объявляются строкой «имя = число» до команды animate.",
                           line=a.cmd.line, command=a.cmd.text)
        if not a.has("from") or not a.has("to"):
            raise DslError("morph: нужны from= и to= (начальное и конечное значение).",
                           line=a.cmd.line, command=a.cmd.text)
        spec["param"] = param
        spec["from"] = float(a.num("from") or 0.0)
        spec["to"] = float(a.num("to") or 0.0)
        spec["samples"] = max(2, min(int(a.num("samples", round(seconds * 4)) or 12), 60))

    a.scene.add_animation(spec)
    label = KIND_NAMES_ANIM.get(kind, kind)
    extra = ""
    if kind == "move":
        extra = f", Δ=({spec['delta'][0]:g}, {spec['delta'][1]:g}, {spec['delta'][2]:g}) мм"
    elif kind == "scale":
        extra = f", ×{spec['from']:g}→×{spec['to']:g}"
    elif kind == "turn":
        extra = f", {spec['angle']:g}° вокруг {axis_raw}"
    elif kind == "spin":
        extra = f", {spec.get('turns', 1):g} об. вокруг {axis_raw}"
    elif kind == "roll":
        extra = f", {spec['distance']:g} мм, R{spec['radius']:g} → " \
                f"{math.degrees(spec['radians']):.0f}°"
    elif kind == "jump":
        extra = f", высота {spec['height']:g} мм" + (", упруго" if spec["elastic"] else "")
    elif kind == "fall":
        extra = f", падение {spec['height']:g} мм" + (", упруго" if spec["elastic"] else "")
    elif kind == "fan":
        extra = f", {spec['rpm']:g} об/мин"
    elif kind == "morph":
        extra = f", {spec['param']} {spec['from']:g}→{spec['to']:g}"
    a.scene.log("info", f"анимация: {label}, {seconds:g} с, дорожка {track}{extra}",
                a.cmd.line)
    return None


@op("заготовка", aliases=("анимации", "сцена_анимации", "сюжет", "storyboard"),
    category="Сцена и материал",
    summary="Объявляет заготовку анимации — их у сцены может быть сколько угодно. "
            "Клипы привязываются к ней через scene=имя: «открывание двери» и «выезд "
            "ящика» становятся независимыми анимациями, а не одной кучей на общей "
            "шкале. Заготовку без клипов тоже видно в списке.",
    example='дверь = box size=[40,2,60] at=[0,-1,0]\n''ящик = box size=[40,2,60] at=[60,-1,0]\n''заготовка names=[открыть_дверь, выезд_ящика]\n'
            'animate дверь turn angle=-100 axis=z pivot=[-486,-212,0] seconds=2 scene=открыть_дверь\n'
            'animate ящик move dy=-250 seconds=2 scene=выезд_ящика',
    params={"name": "имя анимации (без пробелов; можно в кавычках)",
            "names": "несколько имён сразу [открыть_дверь, выезд_ящика]"},
    positional="*")
def animation(a, name):
    names: list[str] = []
    if a.has("names"):
        value = a.value("names")
        names = [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
    raw = (a.text("name") or "").strip()
    if raw:
        names.extend(part for part in raw.strip("[]").split(",") if part.strip())
    names.extend(str(w) for w in a.extra)
    clean = []
    for item in names:
        item = str(item).strip().strip('"\'').replace(" ", "_").strip(",;")
        if not item or item in clean:
            continue
        a.scene.add_named_animation(item)
        clean.append(item)
    if not clean:
        raise DslError("Укажите имя анимации: анимация открыть_дверь",
                       hint="Клипы привязываются к ней через scene=открыть_дверь",
                       line=a.cmd.line, command=a.cmd.text)
    a.scene.log("info", "анимация сцены: " + ", ".join(clean), a.cmd.line)
    return None


@op("keyframe", aliases=("key", "ключ", "кадр", "ключ_кадр", "keys"), category="Сцена и материал",
    summary="Ключевой кадр объекта: смещение, поворот и масштаб в заданный момент. "
            "Строк keyframe может быть несколько — между ними плавная интерполяция.",
    example='ручка = box size=[20,20,20]\nkeyframe ручка at=0 pos=[0, 0, 0]\nkeyframe ручка at=2 pos=[0, 0, 30]',
    positional=["object"],
    params={"object": "имя объекта", "at": "время ключа, с",
            "pos": "смещение [dx, dy, dz] в мм", "rot": "поворот [rx, ry, rz] в градусах",
            "scale": "масштаб (1 — как построено)"})
def keyframe(a, name):
    target = a.text("object") or name
    if not target:
        raise DslError("Укажите объект: keyframe ручка at=0 pos=[0,0,20]",
                       line=a.cmd.line, command=a.cmd.text)
    solid = a.scene.resolve(target)
    at = float(a.num("at", 0.0) or 0.0)
    at = max(0.0, min(at, 3600.0))
    pos = a.vec("pos", 3) if a.has("pos") else None
    rot = a.vec("rot", 3) if a.has("rot") else None
    scale = float(a.num("scale")) if a.has("scale") else None
    if pos is None and rot is None and scale is None:
        raise DslError("Ключ пустой: укажите pos, rot или scale.",
                       hint="Например: keyframe ручка at=1 pos=[0,0,20] rot=[0,0,45]",
                       line=a.cmd.line, command=a.cmd.text)
    spec = {"t": at, "line": a.cmd.line, "text": a.cmd.text}
    if pos is not None:
        spec["pos"] = [float(v) for v in pos]
    if rot is not None:
        spec["rot"] = [float(v) for v in rot]
    if scale is not None:
        spec["scale"] = float(scale)
    a.scene.add_key(solid.name, spec)
    a.scene.log("info", f"ключ: {solid.name} @ {at:g} с", a.cmd.line)
    return None


