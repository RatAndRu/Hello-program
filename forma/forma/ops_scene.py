"""Команды сцены: цвет, видимость, проверки."""

from __future__ import annotations

from .errors import DslError
from .geometry import normalize_color
from .ops import op


@op("color", aliases=("цвет", "материал"), category="Сцена и материал",
    summary="Задаёт цвет и материал объекта (или всех объектов).",
    example='ручка = cylinder radius=6 height=50\ncolor ручка #d8b98a material=wood',
    params={"target": "имя объекта или all",
            "color": "цвет #RRGGBB или название",
            "material": "ceramic, metal, steel, aluminum, gold, copper, plastic, wood, rubber, glass",
            "metal": "металличность 0..1", "rough": "шероховатость 0..1",
            "density": "плотность г/см³ (для оценки массы)",
            "emissive": "цвет свечения (#rrggbb) — для LED, неона, ламп",
            "emissive_strength": "яркость свечения 0…20 (1)",
            "transmission": "прозрачность стекла 0…1 (0)"},
    positional=["target", "color"])
def color(a, name):
    target = (a.text("target") or "all").strip()
    style = a.style()
    if not style:
        raise DslError("Укажите цвет или материал.",
                       hint="Например: color корпус #e8e8e8 material=ceramic",
                       line=a.cmd.line, command=a.cmd.text)
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        a.scene.expand(target)
    for solid in targets:
        for key, value in style.items():
            if key == "color":
                setattr(solid, key, normalize_color(value))
            else:
                setattr(solid, key, value)
    a.scene.log("info", f"Материал применён: {', '.join(s.name for s in targets)}", a.cmd.line)
    return None


@op("paint", aliases=("краска", "пятно", "раскрасить", "покрасить_часть"), category="Сцена и материал",
    summary="Красит часть предмета: верх, низ, бок, полосу по высоте, радиусу или область. "
            "Не нужно перечислять полигоны — регион задаётся словами и числами.",
    example='кружка = cylinder radius=40 height=95\n'
            'paint кружка #2f6fb0 side=верх\n'
            'paint кружка #ffffff height=40..70\n'
            'paint кружка #d94f3d radius=0..18',
    params={"target": "имя объекта",
            "color": "цвет #RRGGBB или название",
            "side": "верх, низ, перед, зад, лево, право — по направлению граней",
            "box": "область [x0,y0,z0,x1,y1,z1] в мм",
            "height": "полоса по высоте: height=40..70",
            "radius": "кольцо вокруг оси Z: 0..18",
            "clear": "да — снять всю покраску с предмета"},
    positional=["target", "color"])
def paint(a, name):
    """Регионная покраска: одна команда вместо перечисления граней."""
    target = (a.text("target") or "").strip()
    if not target:
        raise DslError("Укажите объект: paint кружка #c0402a side=верх",
                       line=a.cmd.line, command=a.cmd.text)
    solid = a.scene.resolve(target)
    if (a.text("clear") or "").lower() in ("да", "yes", "1", "true"):
        solid.paint = []
        a.scene.log("info", f"Покраска снята: {solid.name}", a.cmd.line)
        return None
    color_value = normalize_color(a.text("color") or "")
    if not color_value or color_value == "#c9d1e3":
        raise DslError("Укажите цвет для покраски.",
                       hint="Например: paint кружка #c0402a height 60..90",
                       line=a.cmd.line, command=a.cmd.text)
    spec: dict = {"color": color_value}
    side = (a.text("side") or "").strip().lower()
    if side:
        spec["side"] = side
    box = a.value("box")
    if isinstance(box, (list, tuple)) and len(box) == 6:
        spec["box"] = [float(b) for b in box]
    for key in ("height", "radius"):
        value = a.value(key)
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            spec[key] = [float(value), float(value)]
        elif hasattr(value, "lo"):
            lo = getattr(value, "lo", None)
            hi = getattr(value, "hi", None)
            spec[key] = [float(lo if lo is not None else float("-inf")),
                         float(hi if hi is not None else float("inf"))]
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            spec[key] = [float(value[0]), float(value[1])]
    if len(spec) == 1:
        # без условия это просто цвет всего предмета
        solid.paint = []
        solid.color = color_value
        a.scene.log("info", f"Цвет предмета: {solid.name}", a.cmd.line)
        return None
    solid.paint = list(solid.paint or []) + [spec]
    a.scene.log("info", f"Покрашено: {solid.name} — {', '.join(k for k in spec if k != 'color')}",
                a.cmd.line)
    return None


@op("show", aliases=("показать", "видимый"), category="Сцена и материал",
    summary="Показывает объект (в том числе промежуточный).",
    example='корпус = box size=[60,60,60]\nshow корпус', params={"target": "имя объекта или all"},
    positional=["target"])
def show(a, name):
    target = (a.text("target") or "").strip()
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        a.scene.expand(target)
    for solid in targets:
        solid.visible = True
    return None


@op("hide", aliases=("скрыть", "спрятать"), category="Сцена и материал",
    summary="Скрывает объект.",
    example='корпус = box size=[60,60,60]\nплита = box size=[100,100,10]\nhide корпус', params={"target": "имя объекта или all"},
    positional=["target"])
def hide(a, name):
    target = (a.text("target") or "").strip()
    targets = list(a.scene.objects.values()) if target in ("all", "*", "все") else \
        a.scene.expand(target)
    for solid in targets:
        solid.visible = False
    return None


@op("delete", aliases=("удалить", "стереть", "remove", "убрать"), category="Сцена и материал",
    summary="Удаляет объект из сцены: он исчезает из списка, модели, рендера и экспорта. "
            "Строки сценария самого объекта остаются — их можно вернуть откатом.",
    example='ручка = cylinder radius=6 height=50\nкорпус = box size=[60,60,60]\nудалить ручка',
    params={"target": "имя объекта или all"},
    positional=["target"])
def delete_object(a, name):
    target = (a.text("target") or "").strip()
    if not target:
        raise DslError("Укажите, что удалить: удалить ручка",
                       line=a.cmd.line, command=a.cmd.text)
    if target in ("all", "*", "все", "всё"):
        targets = list(a.scene.objects.values())
    else:
        targets = a.scene.expand(target)
    removed = []
    for solid in targets:
        if solid.name in a.scene.objects:
            a.scene.remove(solid.name)
            removed.append(solid.name)
    if not removed:
        raise DslError(f"Объект «{target}» уже удалён.", line=a.cmd.line)
    a.scene.groups.pop(target, None)
    a.scene.log("info", "удалено: " + ", ".join(removed), a.cmd.line)
    return None


@op("group", aliases=("группа", "сборка_объектов", "assembly_group", "группировать"),
    category="Сцена и материал",
    summary="Собирает готовые объекты в группу для анимации: группа целиком едет или "
            "поворачивается, а детали внутри могут двигаться и крутиться сами.",
    example='фасад_л = box size=[100,20,300]\nручка_левая = cylinder radius=5 height=60 at=[0,-10,150]\nдверь = group [фасад_л, ручка_левая]\nanimate дверь turn angle=100 axis=z pivot=[-481, 216, 0] seconds=2',
    params={"objects": "объекты через запятую: [a, b, c]",
            "name": "имя группы (берётся из «имя = group …»)"},
    positional=["objects"])
def group(a, name):
    members = a.solids()
    if not members:
        raise DslError("Группа пустая: перечислите объекты в квадратных скобках.",
                       hint="Например: дверь = group [фасад_л, ручка_левая]",
                       line=a.cmd.line, command=a.cmd.text)
    gname = (name or "").strip()
    if not gname:
        raise DslError("Укажите имя группы: дверь = group [фасад_л, ручка_левая]",
                       line=a.cmd.line, command=a.cmd.text)
    if gname in a.scene.objects:
        raise DslError(f"Имя «{gname}» уже занято объектом.",
                       hint="Назовите группу иначе, например «дверь_сборка».",
                       line=a.cmd.line, command=a.cmd.text)
    names = [s.name for s in members]
    used = {}
    for other, items in a.scene.groups.items():
        if other == gname:
            continue
        for n in items:
            if n in names:
                used[n] = other
    if used:
        first = next(iter(used))
        raise DslError(f"Объект «{first}» уже входит в группу «{used[first]}».",
                       hint="Один объект может быть только в одной группе: "
                            "уберите его из прежней или назовите новую иначе.",
                       line=a.cmd.line, command=a.cmd.text)
    a.scene.groups[gname] = names
    a.scene.log("info", f"группа «{gname}»: " + ", ".join(names), a.cmd.line)
    return None


@op("check", aliases=("проверить", "проверка"), category="Проверка",
    summary="Задаёт проверку результата: размер, толщина стенок, герметичность, симметрия и т.д.",
    example='кружка = cylinder radius=40 height=95\ncheck кружка height 90..110\ncheck кружка watertight',
    params={"object": "имя объекта",
            "rule": "watertight, genus, parts, size, height, width, depth, volume, mass, "
                    "wall, wall_min, flat_bottom, overhang, symmetric, gap, inside, tris, "
                    "sharp_edge, tri_quality, deviation",
            "args": "параметры правила, например 90..110 или x"},
    positional="*")
def check(a, name):
    raise DslError("Внутренняя ошибка: проверка должна обрабатываться построителем.",
                   line=a.cmd.line)


# --------------------------------------------------------------------------- #
#  Кисть и ластик: свободная роспись по поверхности
# --------------------------------------------------------------------------- #
def _stroke(a, erase: bool = False):
    """Общий разбор мазка для кисти и ластика."""
    target = (a.text("target") or "").strip()
    if not target:
        raise DslError("Укажите предмет: кисть кружка #c0402a point=[0,40,60]",
                       line=a.cmd.line, command=a.cmd.text)
    solid = a.scene.resolve(target)
    if (a.text("clear") or "").lower() in ("да", "yes", "1", "true"):
        had = len(solid.brush or [])
        solid.brush = []
        a.scene.log("info", f"Роспись снята: {solid.name} ({had} мазков)", a.cmd.line)
        return None
    radius = float(a.num("radius", 4.0, minv=0.05) or 4.0)
    path = []
    if a.has("path"):
        raw = a.points("path", 3)
        path = [[float(v) for v in p] for p in raw]
    if a.has("point"):
        point = a.vec("point", 3, required=True)
        if not path:
            path.append([float(v) for v in point])
        else:
            path.insert(0, [float(v) for v in point])
    if not path:
        raise DslError("Где рисовать? Укажите point=[x,y,z] или path=[[x,y,z], …]",
                       hint="Например: кисть кружка #2f6fb0 radius=6 point=[0,40,60]",
                       line=a.cmd.line, command=a.cmd.text)
    spec: dict = {"radius": round(radius, 3),
                  "path": [[round(v, 2) for v in p] for p in path]}
    if erase:
        spec["erase"] = True
    else:
        color = normalize_color(a.text("color") or "")
        if not color:
            raise DslError("Укажите цвет мазка.",
                           hint="Например: кисть кружка #2f6fb0 radius=6 point=[0,40,60]",
                           line=a.cmd.line, command=a.cmd.text)
        spec["color"] = color
    solid.brush = list(solid.brush or []) + [spec]
    a.scene.log("info", ("ластик: " if erase else "мазок: ") + solid.name, a.cmd.line)
    return solid


@op("кисть", aliases=("мазок", "brush", "рисовать", "кисточка"), category="Сцена и материал",
    summary="Рисует по поверхности предмета свободным мазком: шар краски заданного "
            "радиуса проходит по точкам path. Мазки ложатся и в PNG, и в GLB, "
            "хранятся в сценарии отдельно от материала — их можно стереть ластиком.",
    example="кружка = cylinder radius=40 height=95\n"
            "кисть кружка #2f6fb0 radius=6 point=[0,40,60]\n"
            "кисть кружка #ffd166 radius=4 path=[[0,40,30],[0,40,50],[0,40,70]]",
    params={"target": "имя предмета", "color": "цвет мазка #RRGGBB или название",
            "radius": "радиус кисти в мм (4)",
            "point": "одна точка касания [x,y,z]",
            "path": "цепочка точек [[x,y,z], …] — сплошной мазок",
            "clear": "да — снять все мазки с предмета"},
    positional=["target", "color"])
def brush(a, name):
    return _stroke(a, erase=False)


@op("ластик", aliases=("стёрка", "стерка", "eraser", "erase_brush", "ластик_кисти"),
    category="Сцена и материал",
    summary="Стирает нарисованное кистью, но не материал и не регионы paint. "
            "Работает как кисть наоборот: в месте мазка возвращается цвет основания.",
    example="кружка = cylinder radius=40 height=95\n"
            "кисть кружка #2f6fb0 radius=6 point=[0,40,60]\n"
            "ластик кружка radius=8 point=[0,40,60]",
    params={"target": "имя предмета", "radius": "радиус ластика в мм (6)",
            "point": "точка [x,y,z]", "path": "цепочка точек [[x,y,z], …]",
            "clear": "да — стереть все мазки сразу"},
    positional=["target"])
def eraser(a, name):
    return _stroke(a, erase=True)
