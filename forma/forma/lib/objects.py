"""Параметрические объекты, собранные «по референсу»: меч, шлем, стул, фонарь.

Зачем это здесь. Готовые CC0-модели (Quaternius, Kenney, Poly Haven, Smithsonian)
— это меши: их нельзя переразмерить. Но их **пропорции и размеры** — обычные
числа, а числа переносятся: мы строим ту же вещь своими примитивами и получаем
то, что можно менять параметром.

Откуда взяты числа (и что именно проверяемо):

* **меч** — типология Оукшотта для одноручного меча (X–XIV): клинок 700–800 мм,
  ширина у пяты 45–60 мм, толщина 4–5 мм, гарда 180–200 мм, рукоять 100–120 мм,
  общая длина 900–1000 мм, масса 1.0–1.4 кг. Масса считается по стали 7.85 г/см³.
  Референсы-меши: Quaternius «LowPoly Medieval Weapons» (22 модели, CC0),
  Quaternius «Ultimate RPG Items» (Sword, Claymore, Dagger — CC0).
* **шлем** — кастрюльный шлем (kettle hat): тулья по обхвату головы 560–600 мм,
  поля 60–80 мм. Для сверки габарита: Smithsonian CC0, «French Adrian Helmet» —
  159 × 210 × 286 мм (высота × ширина × глубина).
  Референсы: Smithsonian 3D (CC0), Quaternius «Knight Character» (CC0).
* **стул** — обеденный стул: высота сиденья 450 мм, сиденье 430–450 мм,
  верх спинки 850–900 мм от пола (бытовые стандарты мебели, ГОСТ 13025 / EN 1729
  дают те же величины с допусками).
  Референсы: Kenney «Furniture Kit» (140 моделей, CC0: Chair, Chair Rounded,
  Desk Chair, Bench), Poly Haven (Side Table 01, Chair — CC0).
* **фонарный столб** — свободностоящий: высота 3500–4500 мм, цоколь Ø280–320,
  столб кверху сужается с Ø120 до Ø60, вылет кронштейна 600–800 мм.
  Референс с реальным масштабом: Poly Haven «Street Lamp 02» — 1.7 м,
  39 × 81 × 168 см, 20k трис (CC0, настенный вариант).

Все объекты — наши примитивы (`loft`, `hemisphere`, `cylinder`, `box`, `array`),
поэтому каждый размер — параметр. `forma lib` собирает их по имени.
"""

from __future__ import annotations

import math
from typing import Sequence


# --------------------------------------------------------------------------- #
#  Помощники
# --------------------------------------------------------------------------- #

def _num(value: float) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _range(value: float, tol: float) -> str:
    return f"{_num(value - tol)}..{_num(value + tol)}"


def _blade_section(width: float, thickness: float) -> list[tuple[float, float]]:
    """Сечение клинка: линза с шестью вершинами (два дола по толщине)."""
    w, t = width / 2, thickness / 2
    return [(w, 0.0), (w * 0.5, t), (-w * 0.5, t), (-w, 0.0), (-w * 0.5, -t), (w * 0.5, -t)]


def _section(points: Sequence[tuple[float, float]]) -> str:
    return "[" + ",".join(f"[{_num(x)},{_num(y)}]" for x, y in points) + "]"


# --------------------------------------------------------------------------- #
#  1. Меч
# --------------------------------------------------------------------------- #

def sword_script(blade: float = 750.0, width: float = 50.0, thickness: float = 5.0,
                 grip: float = 110.0, guard: float = 190.0, pommel: float = 50.0,
                 comment: str | None = None) -> str:
    """Одноручный меч: клинок с сужением, гарда, рукоять, навершие.

    ``blade`` — длина клинка от гарды до острия, мм. Остальные размеры тоже в мм.
    """
    blade = float(blade)
    if not 200 <= blade <= 1100:
        raise ValueError("Длина клинка меча — от 200 до 1100 мм "
                         "(короче — кинжал, длиннее — двуручник другого профиля).")
    grip, guard, pommel = float(grip), float(guard), float(pommel)
    for name, value, low, high in (("ширина клинка", float(width), 20, 80),
                                   ("толщина клинка", float(thickness), 2, 12),
                                   ("рукоять", grip, 70, 260),
                                   ("гарда", guard, 60, 350),
                                   ("навершие", pommel, 20, 90)):
        if not low <= value <= high:
            raise ValueError(f"{name[0].upper()}{name[1:]} вне {low}…{high} мм: {value:g}.")
    guard_h = 12.0                       # толщина гарды
    z_guard = grip                       # гарда стоит на рукояти
    z_blade = z_guard + guard_h          # пята клинка
    w, t = float(width), float(thickness)

    sections = [
        (0.0, w, t),                     # пята
        (blade * 0.35, w * 0.96, t * 0.9),
        (blade * 0.75, w * 0.82, t * 0.7),
        (blade * 0.95, w * 0.55, t * 0.45),
        (blade, w * 0.06, t * 0.2),      # острие
    ]
    body = "[" + ",\n    ".join(_section(_blade_section(sw, st)) for _, sw, st in sections) + "]"
    positions = "[" + ",".join(_num(z_blade + z) for z, *_ in sections) + "]"
    total = z_blade + blade
    height_total = total + pommel * 0.35

    lines = [
        comment or f"# Меч: клинок {_num(blade)} мм, общая длина {_num(height_total)} мм.",
        "# Пропорции — типология Оукшотта X–XIV: масса 1.0–1.4 кг при стали 7.85 г/см³.",
        "",
        "# 1. Клинок: линза в сечении, сужение к острию (loft по пяти сечениям).",
        f"клинок = loft sections={body} positions={positions} axis=z smooth=1",
        "",
        "# 2. Гарда: брусок со скруглением, перпендикулярно клинку.",
        # `at` у box — центр по X/Y и низ по Z (проверено bbox).
        f"гарда = box size=[{_num(guard)},{_num(guard * 0.11)},{_num(guard_h)}] round=5 "
        f"at=[0,0,{_num(z_guard)}]",
        "",
        "# 3. Рукоять: цилиндр с сужением к навершию.",
        f"рукоять = cylinder radius={_num(w * 0.21)} height={_num(grip)} "
        f"r2={_num(w * 0.19)} segments=24 at=[0,0,0]",
        "",
        "# 4. Навершие: эллипсоид, половина уходит под рукоять.",
        # У `ellipsoid` x/y/z — полуоси, а `at.z` — низ: полуоси в два раза меньше.
        f"навершие = ellipsoid x={_num(pommel / 2)} y={_num(pommel * 0.39)} "
        f"z={_num(pommel * 0.35)} segments=32 at=[0,0,{_num(-pommel * 0.35)}]",
        "",
        "меч = union [клинок, гарда, рукоять, навершие]",
        # Навершие уходит ниже нуля — поднимаем меч, чтобы он стоял на полу.
        "меч = place [меч] at=[0,0,0]",
        "",
        "# Проверки: общая длина и герметичность.",
        f"check меч height {_range(height_total, 0.6)}",
        "check меч watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  2. Шлем
# --------------------------------------------------------------------------- #

def helmet_script(head: float = 580.0, dome: float = 105.0, brim: float = 70.0,
                  wall: float = 2.5, brim_thickness: float = 5.0, height_k: float = 0.78,
                  comment: str | None = None) -> str:
    """Кастрюльный шлем: неглубокая тулья вращения и кольцевые поля.

    ``head`` — обхват головы, мм (радиус тульи считается из него, но не меньше
    ``dome``). ``height_k`` — во сколько раз тулья ниже своего радиуса: у
    кастрюльного шлема это 0.7–0.9, у полусферы было бы 1.0.
    """
    head, brim, wall = float(head), float(brim), float(wall)
    if not 480 <= head <= 660:
        raise ValueError("Обхват головы вне 480…660 мм — это не человек.")
    if not 10 <= brim <= 200:
        raise ValueError("Поля шлема — от 10 до 200 мм.")
    if not 1 <= wall <= 8:
        raise ValueError("Стенка шлема — от 1 до 8 мм.")
    radius = max(float(dome), head / (2 * math.pi) + 6.0)
    thick = float(brim_thickness)
    hh = radius * float(height_k)
    inner = radius - wall
    slope = 8.0                          # насколько поля опускаются к краю
    width = 2 * (radius + brim)
    height = hh + slope + thick

    def outer(scale: float, shift: float, top: float = 1.0) -> str:
        """Профиль тульи: у кастрюльного шлема купол крутой у кромки и плоский сверху."""
        return (f"[[0,{_num(shift)}],[{_num(radius * scale)},{_num(shift)}],"
                f"[{_num(radius * scale * 0.94)},{_num(shift + hh * 0.35 * top)}],"
                f"[{_num(radius * scale * 0.62)},{_num(shift + hh * 0.78 * top)}],"
                f"[{_num(radius * scale * 0.30)},{_num(shift + hh * 0.97 * top)}],"
                f"[0,{_num(shift + hh * top)}]]")

    lines = [
        comment or (f"# Шлем: обхват {_num(head)} мм, тулья R{_num(radius)}×{_num(hh)} мм, "
                    f"поля {_num(brim)} мм."),
        "# Сверка габарита: Smithsonian CC0 «French Adrian Helmet» — 159 × 210 × 286 мм.",
        "",
        "# 1. Тулья: тело вращения (не полусфера — у шлема она ниже радиуса).",
        f"тулья_тело = lathe points={outer(1.0, 0.0)} segments=64",
        f"тулья_полость = lathe points={outer(inner / radius, -1.0, 0.88)} segments=64",
        "тулья = difference [тулья_тело, тулья_полость]",
        "",
        "# 2. Поля: кольцо вращения (профиль не касается оси).",
        "# Порядок точек — против часовой стрелки в плоскости (r, z): иначе пусто.",
        f"поля = lathe points=[[{_num(radius - 2)},{_num(-thick)}],"
        f"[{_num(radius + brim)},{_num(-slope - thick)}],"
        f"[{_num(radius + brim)},{_num(-slope)}],[{_num(radius - 2)},{_num(0)}]] segments=64",
        "",
        "шлем = union [тулья, поля]",
        # Поля наклонены вниз — ставим шлем на пол, а не «в пол».
        "шлем = place [шлем] at=[0,0,0]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check шлем size {_range(width, 1.0)} {_range(width, 1.0)} {_range(height, 0.6)}",
        "check шлем watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  3. Стул
# --------------------------------------------------------------------------- #

def chair_script(seat_h: float = 450.0, seat: float = 440.0, seat_t: float = 25.0,
                 back: float = 420.0, leg: float = 40.0, slats: int = 3,
                 comment: str | None = None) -> str:
    """Обеденный стул: четыре ножки, сиденье, две стойки и перекладины спинки."""
    seat_h, seat, seat_t = float(seat_h), float(seat), float(seat_t)
    back, leg = float(back), float(leg)
    if not 350 <= seat_h <= 560:
        raise ValueError("Высота сиденья вне 350…560 мм.")
    if not 300 <= seat <= 600:
        raise ValueError("Сиденье вне 300…600 мм.")
    if not 250 <= back <= 600:
        raise ValueError("Спинка вне 250…600 мм над сиденьем.")
    if not 25 <= leg <= 80:
        raise ValueError("Ножка вне 25…80 мм.")
    slats = max(1, int(slats))
    top = seat_h + back
    # Ножки стоят под кромкой сиденья: центр ножки — на `seat/2 - leg/2` от оси.
    half = seat / 2 - leg / 2
    spread = 2 * half

    lines = [
        comment or f"# Стул: сиденье {_num(seat)}×{_num(seat)} на {_num(seat_h)} мм, спинка до {_num(top)} мм.",
        "# Величины — бытовые нормы мебели: сиденье 430–450 мм, верх спинки 850–900 мм.",
        "",
        "# 1. Ножки: четыре бруска, сетка 2×2 нашим `array`.",
        f"ножка = box size=[{_num(leg)},{_num(leg)},{_num(seat_h - seat_t)}] round=3 "
        f"at=[{_num(-half)},{_num(-half)},0]",
        f"ножки = array [ножка] mode=grid counts=[2,2,1] "
        f"spacing=[{_num(spread)},{_num(spread)},0]",
        "",
        "# 2. Сиденье.",
        f"сиденье = box size=[{_num(seat)},{_num(seat)},{_num(seat_t)}] round=8 "
        f"at=[0,0,{_num(seat_h - seat_t)}]",
        "",
        "# 3. Спинка: две стойки по краям сиденья.",
        # `place` не сдвигает, а переносит в точку, поэтому высоту задаём сразу.
        # Высоту задаём сразу: `place` не сдвигает, а переносит объект в точку.
        f"стойка = box size=[{_num(leg)},{_num(leg)},{_num(back)}] round=3 "
        f"at=[{_num(-half)},{_num(half - leg / 2)},{_num(seat_h)}]",
        f"стойки = array [стойка] mode=grid counts=[2,1,1] spacing=[{_num(spread)},0,0]",
        "",
        f"# 4. Перекладины спинки: {slats} шт., распределены по высоте.",
    ]
    slat_h = 28.0
    step = (back - leg) / (slats + 1)
    for i in range(slats):
        z = seat_h + leg + step * (i + 1) - slat_h / 2
        lines.append(f"планка_{i + 1} = box size=[{_num(seat - 2 * leg)},{_num(16)},{_num(slat_h)}] "
                     f"at=[0,{_num(half)},{_num(z)}]")
    planks = ", ".join(f"планка_{i + 1}" for i in range(slats))
    lines += [
        "",
        f"стул = union [ножки, сиденье, стойки, {planks}]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check стул size {_range(seat, 0.6)} {_range(seat, 0.6)} {_range(top, 0.6)}",
        "check стул watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  4. Фонарный столб
# --------------------------------------------------------------------------- #

def lamp_script(height: float = 4000.0, base_d: float = 300.0, pole_d: float = 120.0,
                top_d: float = 60.0, arm: float = 700.0, lantern: float = 260.0,
                comment: str | None = None) -> str:
    """Фонарный столб: цоколь, сужающийся столб, кронштейн и фонарь."""
    height, base_d = float(height), float(base_d)
    pole_d, top_d = float(pole_d), float(top_d)
    arm, lantern = float(arm), float(lantern)
    if not 1500 <= height <= 12000:
        raise ValueError("Высота столба вне 1500…12000 мм.")
    if not 50 <= pole_d <= 400 or not 20 <= top_d <= 300:
        raise ValueError("Диаметр столба 50…400 мм, верха — 20…300 мм.")
    if not 150 <= base_d <= 800:
        raise ValueError("Цоколь вне 150…800 мм.")
    if not 200 <= arm <= 2500:
        raise ValueError("Вылет кронштейна вне 200…2500 мм.")
    if not 80 <= lantern <= 800:
        raise ValueError("Фонарь вне 80…800 мм.")
    base_h = 140.0
    bracket_h = top_d * 0.8              # высота кронштейна
    bracket_top = height - 6.0           # верх кронштейна чуть ниже верха столба
    bracket_z = bracket_top - bracket_h
    pole_top = height - 10.0             # столб входит в кронштейн, торец внутри
    lantern_h = lantern * 1.35
    roof_h = lantern * 0.5
    fin_h = lantern * 0.2                # шпиль на крыше
    fin_z = height + roof_h * 0.75       # низ шпиля — внутри крыши
    width = base_d

    lines = [
        comment or f"# Фонарный столб: высота {_num(height)} мм, вылет {_num(arm)} мм.",
        "# Ориентир по реальному масштабу: Poly Haven Street Lamp 02 — 1.7 м, 39×81×168 см (CC0).",
        "",
        "# 1. Цоколь и столб с сужением.",
        f"цоколь = cylinder radius={_num(base_d / 2)} height={_num(base_h)} "
        f"r2={_num(base_d * 0.4)} segments=48 at=[0,0,0]",
        f"столб = cylinder radius={_num(pole_d / 2)} height={_num(pole_top - base_h)} "
        f"r2={_num(top_d / 2)} segments=48 at=[0,0,{_num(base_h)}]",
        "",
        "# 2. Кронштейн: брусок вдоль X и подкос.",
        # Подкос начинается от оси столба, иначе он висит в воздухе: у
        # сужающегося столба радиус на этой высоте меньше смещения.
        f"кронштейн = box size=[{_num(arm)},{_num(top_d)},{_num(bracket_h)}] round=8 "
        f"at=[{_num(arm / 2)},0,{_num(bracket_z)}]",
        f"подкос = box size=[{_num(arm * 0.5)},{_num(top_d * 0.5)},{_num(top_d * 0.5)}] round=6 "
        f"at=[{_num(arm * 0.25)},0,{_num(bracket_z - arm * 0.2)}]",
        "",
        "# 3. Фонарь на конце кронштейна: корпус, крыша, шпиль.",
        f"фонарь = box size=[{_num(lantern)},{_num(lantern)},{_num(lantern_h)}] round=10 "
        f"at=[{_num(arm - lantern / 2)},0,{_num(height - lantern_h)}]",
        # Крыша — усечённая пирамидка со скруглением: у конуса вершина на оси
        # даёт полюс с веером игл, у `box top_size` его нет.
        f"крыша = box size=[{_num(lantern * 1.3)},{_num(lantern * 1.3)},{_num(roof_h)}] round=6 "
        f"top_size=[{_num(lantern * 0.1)},{_num(lantern * 0.1)}] "
        f"at=[{_num(arm - lantern / 2)},0,{_num(height - 1)}]",
        f"шпиль = cylinder radius={_num(lantern * 0.05)} height={_num(fin_h)} segments=24 "
        f"at=[{_num(arm - lantern / 2)},0,{_num(fin_z)}]",
        "",
        "фонарь_столб = union [цоколь, столб, кронштейн, подкос, фонарь, крыша, шпиль]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check фонарь_столб height {_range(fin_z + fin_h, 2.0)}",
        "check фонарь_столб watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  5. Кинжал
# --------------------------------------------------------------------------- #

def _diamond(width: float, thickness: float) -> list[tuple[float, float]]:
    """Ромб в сечении — так выглядит гранёный клинок кинжала."""
    w, t = width / 2, thickness / 2
    return [(w, 0.0), (0.0, t), (-w, 0.0), (0.0, -t)]


def dagger_script(blade: float = 280.0, width: float = 32.0, thickness: float = 7.0,
                  grip: float = 95.0, guard: float = 64.0, pommel: float = 46.0,
                  comment: str | None = None) -> str:
    """Кинжал-рондель: гранёный клинок, дисковая гарда, диск навершия.

    Пропорции — рондель/мизерикорд XIV–XV вв.: клинок 250–320 мм, ширина 28–36 мм,
    толщина 6–8 мм, рукоять 85–110 мм, гарда-диск 55–70 мм, навершие 40–55 мм.
    Референсы: Quaternius `S_Dagger`, `S_Dagger_2` (CC0), типология Оукшотта.
    """
    blade, width, thickness = float(blade), float(width), float(thickness)
    grip, guard, pommel = float(grip), float(guard), float(pommel)
    if blade < 120:
        raise ValueError("Клинок короче 120 мм — это уже не кинжал.")
    if width < thickness * 2:
        raise ValueError("Ширина клинка должна быть хотя бы вдвое больше толщины.")
    guard_t, pommel_h = 8.0, 14.0
    z_guard = grip
    z_blade = z_guard + guard_t
    total = z_blade + blade + pommel_h

    sections = [
        (0.0, width, thickness),
        (blade * 0.45, width * 0.95, thickness * 0.85),
        (blade * 0.80, width * 0.72, thickness * 0.6),
        (blade, width * 0.05, thickness * 0.25),
    ]
    body = "[" + ",\n    ".join(_section(_diamond(w, t)) for _, w, t in sections) + "]"
    positions = "[" + ",".join(_num(z_blade + z) for z, *_ in sections) + "]"

    lines = [
        comment or f"# Кинжал: клинок {_num(blade)} мм, общая длина {_num(total)} мм.",
        "# Пропорции — рондель/мизерикорд XIV–XV вв.: клинок 250–320, рукоять 85–110 мм.",
        "",
        "# 1. Клинок: ромб в сечении, четыре доли, сужение к острию.",
        f"клинок = loft sections={body} positions={positions} axis=z smooth=1",
        "",
        "# 2. Гарда-диск (рондель) и навершие-диск.",
        f"гарда = cylinder radius={_num(guard / 2)} height={_num(guard_t)} segments=48 "
        f"at=[0,0,{_num(z_guard)}]",
        f"навершие = cylinder radius={_num(pommel / 2)} height={_num(pommel_h)} segments=48 "
        f"at=[0,0,{_num(-pommel_h)}]",
        "",
        "# 3. Рукоять между дисками.",
        f"рукоять = cylinder radius={_num(width * 0.30)} height={_num(grip)} "
        f"r2={_num(width * 0.26)} segments=24 at=[0,0,0]",
        "",
        "кинжал = union [клинок, гарда, рукоять, навершие]",
        "# Навершие уходит под ноль — ставим кинжал на пол.",
        "кинжал = place [кинжал] at=[0,0,0]",
        "",
        "# Проверки: общая длина и герметичность.",
        f"check кинжал height {_range(total, 0.6)}",
        "check кинжал watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  6. Топор
# --------------------------------------------------------------------------- #

def _rounded_rect(width: float, depth: float, radius: float, seg: int = 5) -> list[tuple[float, float]]:
    """Контур скруглённого прямоугольника против часовой стрелки."""
    r = max(0.2, min(float(radius), width / 2 - 0.2, depth / 2 - 0.2))
    hw, hd = width / 2 - r, depth / 2 - r
    pts: list[tuple[float, float]] = []
    for cx, cy, a0 in ((hw, hd, 0.0), (-hw, hd, 90.0), (-hw, -hd, 180.0), (hw, -hd, 270.0)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def axe_script(haft: float = 700.0, blade: float = 140.0, thickness: float = 26.0,
               edge: float = 4.0, socket_h: float = 130.0, haft_w: float = 32.0,
               haft_d: float = 26.0, comment: str | None = None) -> str:
    """Бородатый топор: рукоять-брусок, проушина-труба, клин с бородой.

    Пропорции — бытовой/боевой топор X–XIV вв.: рукоять 600–800 мм, вылет лезвия
    120–170 мм, толщина у проушины 22–30 мм, к лезвию 3–5 мм, борода на 60–120 мм
    ниже проушины. Референсы: Quaternius `S_Axe`, `S_AxeDouble` (CC0).
    """
    haft, blade = float(haft), float(blade)
    thickness, edge = float(thickness), float(edge)
    socket_h, haft_w, haft_d = float(socket_h), float(haft_w), float(haft_d)
    if haft < 300:
        raise ValueError("Рукоять короче 300 мм — это уже топорик-потес, а не топор.")
    if not 0.1 * thickness < edge < thickness * 0.6:
        raise ValueError("Толщина лезвия должна быть от 10 % до 60 % толщины обуха.")

    socket_d = max(44.0, thickness * 1.85)
    eye_x0 = -socket_d / 2
    eye_x1 = socket_d / 2 + 6.0
    top = socket_h * 0.65
    # Силуэт клина в плоскости (x, z): обух слева, борода свисает справа-снизу.
    contour = [
        (eye_x1, top),
        (eye_x1 + 0.89 * blade, 0.71 * top),
        (eye_x1 + blade, -0.24 * top),
        (eye_x1 + 0.64 * blade, -1.24 * top),
        (eye_x1 + 0.18 * blade, -1.0 * top),
        (eye_x1, -0.53 * top),
        (eye_x0, -0.53 * top),
        (eye_x0, top),
    ]
    # Спуски: два косых среза с половины толщины до половины толщины лезвия.
    half0, half1 = thickness / 2, edge / 2
    k = (half0 - half1) / blade
    reach = eye_x1 + blade + 40.0
    top_cut = [(eye_x1, 0.0), (reach, -half0 + (half0 - k * (reach - eye_x1))),
               (reach, 90.0), (eye_x1, 90.0)]
    bot_cut = [(eye_x1, -2 * half0), (reach, -half0 - (half0 - k * (reach - eye_x1))),
               (reach, -90.0), (eye_x1, -90.0)]

    haft_top = haft * 1.06
    head_z = haft - 90.0                     # центр головы по высоте
    bore = max(haft_w, haft_d) / 2 + 1.5
    head_h = (top + 1.24 * top)
    lines = [
        comment or f"# Топор: рукоять {_num(haft)} мм, вылет лезвия {_num(blade)} мм.",
        "# Пропорции — топор X–XIV вв.: рукоять 600–800 мм, спуски от 26 к 4 мм.",
        "",
        "# 1. Клин: силуэт выдавливаем и ставим вертикально, спуски — двумя срезами.",
        f"клин = extrude profile={_section(contour)} height={_num(thickness)}",
        "клин = rotate [клин] angle=90 axis=x",
        f"срез_верх = extrude profile={_section(top_cut)} height=400",
        "срез_верх = translate [срез_верх] offset=[0,0,-200]",
        f"срез_низ = extrude profile={_section(bot_cut)} height=400",
        "срез_низ = translate [срез_низ] offset=[0,0,-200]",
        "клин = difference [клин, срез_верх, срез_низ]",
        "",
        "# 2. Проушина: труба, в неё проходит рукоять. Торец спрятан внутри клина.",
        f"проушина = cylinder radius={_num(socket_d / 2)} height={_num(socket_h - 6)} "
        f"segments=40 at=[0,0,{_num(-socket_h * 0.53)}]",
        f"отверстие = cylinder radius={_num(bore)} height={_num(socket_h + 10)} "
        f"segments=40 at=[0,0,{_num(-socket_h * 0.53 - 5)}]",
        "проушина = difference [проушина, отверстие]",
        "",
        "# 3. Голова целиком — на высоту рукояти.",
        "голова = union [клин, проушина]",
        f"голова = translate [голова] offset=[0,0,{_num(head_z)}]",
        "",
        "# 4. Рукоять: брусок со скруглением, сужается кверху. У цилиндра торец —",
        "# веер треугольников (полюс), у выдавливания — обычная триангуляция.",
        f"рукоять = extrude profile={_section(_rounded_rect(haft_w, haft_d, haft_w * 0.25))} "
        f"height={_num(haft_top)} scale_top=0.86",
        "",
        "топор = union [голова, рукоять]",
        "",
        "# Проверки: высота и герметичность.",
        f"check топор height {_range(haft_top, 0.6)}",
        "check топор watertight",
    ]
    _ = head_h  # высота головы нужна только для справки в докстринге
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  7. Щит
# --------------------------------------------------------------------------- #

def _heater_outline(width: float, height: float, n: int = 12) -> list[tuple[float, float]]:
    """Контур щита-утюга: прямой верх, скруглённые боки, низ сведён в точку."""
    half = width / 2
    right: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        x = half * math.cos(t * math.pi / 2) ** 0.55
        z = height * (1.0 - t)
        right.append((x, z))
    right[0] = (half, height)              # верхний угол — прямой, без среза
    pts = [(-half, height)]
    pts.extend(right)                      # правый бок вниз до острия (0, 0)
    pts.extend([(-x, z) for x, z in reversed(right[1:-1])])
    return pts


def shield_script(height: float = 700.0, width: float = 520.0, thickness: float = 22.0,
                  curve: float = 0.07, boss: float = 120.0, straps: int = 1,
                  comment: str | None = None) -> str:
    """Щит-утюг (heater): силуэт, скос кромки, умбон и ремни с тыла.

    Пропорции — щит XIII–XV вв.: высота 600–800 мм, ширина 450–600 мм,
    толщина 18–25 мм, умбон Ø100–150 мм. Референсы: Quaternius `S_ShieldHeater`,
    `S_ShieldHeater_2` (CC0), Kenney `Shield`.
    """
    height, width = float(height), float(width)
    thickness, curve = float(thickness), float(curve)
    boss, straps = float(boss), int(straps)
    if height < 300:
        raise ValueError("Щит ниже 300 мм — это баклер, для него другая форма.")
    if not 0.0 <= curve < 0.3:
        raise ValueError("Скос кромки — доля от 0 до 0.3.")
    outline = _heater_outline(width, height)
    depth = thickness + (boss / 2 if boss > 0 else 0.0) + (12.0 if straps else 0.0)
    # Три сечения по глубине: задняя плоскость, середина, лицевая с косом.
    scales = [1.0, 1.0, 1.0 - curve]
    positions = [0.0, thickness * 0.55, thickness]
    sections = [[(x * s, z * s) for x, z in outline] for s in scales]
    body = "[" + ",\n    ".join(_section(s) for s in sections) + "]"

    lines = [
        comment or f"# Щит: {_num(width)} × {_num(height)} мм, толщина {_num(thickness)} мм.",
        "# Пропорции — щит-утюг XIII–XV вв.: 600–800 мм в высоту, умбон Ø100–150 мм.",
        "",
        "# 1. Корпус: три сечения по глубине, лицевое чуть меньше — скос кромки.",
        f"корпус = loft sections={body} positions=[{','.join(_num(v) for v in positions)}] "
        "axis=y caps=1",
        "",
        "# 2. Умбон: полусфера на лицевой стороне (ось полусферы повёрнута на +Y).",
    ]
    if boss > 0:
        lines += [
            f"умбон = hemisphere radius={_num(boss / 2)} segments=48",
            "умбон = rotate [умбон] angle=-90 axis=x",
            f"умбон = translate [умбон] offset=[0,{_num(thickness)},0]",
            f"умбон = translate [умбон] offset=[0,0,{_num(height * 0.62)}]",
        ]
    straps_names = ["корпус"]
    if boss > 0:
        straps_names.append("умбон")
    if straps:
        lines += [
            "",
            "# 3. Ремни с тыла и рукоять между ними.",
            f"ремень = box size=[{_num(width * 0.09)},{_num(10)},{_num(height * 0.42)}] round=3 "
            f"at=[{_num(width * 0.22)},{-5},{_num(height * 0.3)}]",
            f"ремни = array [ремень] mode=grid counts=[2,1,1] spacing=[{_num(-width * 0.44)},0,0]",
            f"рукоять = box size=[{_num(width * 0.38)},{_num(12)},{_num(30)}] round=4 "
            f"at=[0,{-6},{_num(height * 0.45)}]",
        ]
        straps_names += ["ремни", "рукоять"]
    target = "щит"
    if len(straps_names) > 1:
        lines += ["", f"щит = union [{', '.join(straps_names)}]"]
    else:
        target = "корпус"          # щит без умбона и ремней — это сам корпус
    lines += [
        f"{target} = place [{target}] at=[0,0,0]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check {target} size {_range(width, 1.0)} {_range(depth, 3.0)} {_range(height, 1.0)}",
        f"check {target} watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  8. Стол
# --------------------------------------------------------------------------- #

def table_script(length: float = 1200.0, width: float = 700.0, height: float = 750.0,
                 top_t: float = 32.0, leg: float = 60.0, apron: float = 90.0,
                 stretcher: float = 0.0, comment: str | None = None) -> str:
    """Обеденный стол: столешница, четыре ножки, царги, необязательная проножка.

    Нормы: высота 720–760 мм, столешница 25–40 мм, ножка 50–70 мм,
    царга 80–100 мм, вылет столешницы за ножки 20–40 мм.
    Референсы: Kenney Furniture Kit `Table`, `Desk` (CC0), Quaternius `S_Table`.
    """
    length, width = float(length), float(width)
    height, top_t = float(height), float(top_t)
    leg, apron, stretcher = float(leg), float(apron), float(stretcher)
    if min(length, width) < 400:
        raise ValueError("Стол меньше 400 мм по стороне — это уже табурет.")
    if not 300 < height < 1200:
        raise ValueError("Высота стола вне 300…1200 мм.")
    under = height - top_t
    half_len = length / 2 - leg / 2 - 6
    half_wid = width / 2 - leg / 2 - 6
    inner_len = length - 2 * leg - 24
    inner_wid = width - 2 * leg - 24

    lines = [
        comment or f"# Стол: {_num(length)} × {_num(width)} × {_num(height)} мм.",
        "# Нормы мебели: высота 720–760 мм, столешница 25–40 мм, ножка 50–70 мм.",
        "",
        "# 1. Ножки: сетка 2×2 нашим `array`.",
        f"ножка = box size=[{_num(leg)},{_num(leg)},{_num(under)}] round=3 "
        f"at=[{_num(-half_len)},{_num(-half_wid)},0]",
        f"ножки = array [ножка] mode=grid counts=[2,2,1] "
        f"spacing=[{_num(2 * half_len)},{_num(2 * half_wid)},0]",
        "",
        "# 2. Столешница.",
        f"столешница = box size=[{_num(length)},{_num(width)},{_num(top_t)}] round=6 "
        f"at=[0,0,{_num(under)}]",
        "",
        "# 3. Царги: две по длине, две по ширине, под столешницей.",
        f"царга_длинная = box size=[{_num(inner_len)},{_num(22)},{_num(apron)}] "
        f"at=[0,{_num(half_wid)},{_num(under - apron)}]",
        f"царги_длинные = array [царга_длинная] mode=grid counts=[1,2,1] "
        f"spacing=[0,{_num(-2 * half_wid)},0]",
        f"царга_короткая = box size=[{_num(22)},{_num(inner_wid)},{_num(apron)}] "
        f"at=[{_num(half_len)},{0},{_num(under - apron)}]",
        f"царги_короткие = array [царга_короткая] mode=grid counts=[2,1,1] "
        f"spacing=[{_num(-2 * half_len)},0,0]",
    ]
    parts = ["ножки", "столешница", "царги_длинные", "царги_короткие"]
    if stretcher > 0:
        z = float(stretcher)
        if not 60 < z < under - apron:
            raise ValueError("Проножка должна быть между 60 мм и низом царги.")
        lines += [
            "",
            f"# 4. Проножка на высоте {_num(z)} мм.",
            # проножек две, по боковым царгам: одна по центру ни до ножек не достаёт
            f"проножка = box size=[{_num(2 * half_len)},{_num(28)},{_num(24)}] "
            f"at=[0,{_num(half_wid)},{_num(z)}]",
            f"проножки = array [проножка] mode=grid counts=[1,2,1] "
            f"spacing=[0,{_num(-2 * half_wid)},0]",
        ]
        parts.append("проножки")
    lines += [
        "",
        f"стол = union [{', '.join(parts)}]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check стол size {_range(length, 0.6)} {_range(width, 0.6)} {_range(height, 0.6)}",
        "check стол watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  9. Колонна
# --------------------------------------------------------------------------- #

def column_script(height: float = 3000.0, diameter: float = 300.0, taper: float = 0.14,
                  base_h: float = 190.0, capital_h: float = 210.0, flutes: int = 0,
                  comment: str | None = None) -> str:
    """Классическая колонна: плита, база, ствол с энтазисом, эхин и абака.

    Пропорции — античный ордер: высота 8–10 диаметров, сужение ствола 12–16 %,
    база 1/6–1/8 высоты, капитель 1/14–1/12. Каннелюры — вычитанием цилиндров,
    поставленных по кругу (`array mode=radial`).
    Референсы: Kenney Building Kit `Column`, `Column Thin` (CC0),
    Quaternius `S_ColumnRound1…3` (CC0).
    """
    height, diameter = float(height), float(diameter)
    taper, base_h, capital_h = float(taper), float(base_h), float(capital_h)
    flutes = max(0, int(flutes))
    if height < 500:
        raise ValueError("Колонна ниже 500 мм — это балясина.")
    if not 0.0 <= taper < 0.4:
        raise ValueError("Сужение ствола — доля от 0 до 0.4.")
    if base_h + capital_h > height * 0.5:
        raise ValueError("База и капитель вместе не могут занимать больше половины.")

    r = diameter / 2
    shaft_h = height - base_h - capital_h
    plinth_h = base_h * 0.33
    moulding_h = base_h - plinth_h
    echinus_h = capital_h * 0.55
    abacus_h = capital_h - echinus_h

    def shaft_r(z: float) -> float:
        """Энтазис: лёгкое расширение в нижней трети, как у дорических колонн."""
        t = z / shaft_h
        return r * (1.0 - taper * t) * (1.0 + 0.02 * math.sin(math.pi * t))

    shaft_pts = [(0.0, 0.0), (shaft_r(0.0), 0.0)]
    steps = 10
    for i in range(1, steps + 1):
        z = shaft_h * i / steps
        shaft_pts.append((shaft_r(z), z))
    shaft_pts.append((0.0, shaft_h))

    # Профиль базы на 1 мм ниже и на 1 мм выше своего места: иначе она только
    # касается плиты и ствола плоскостями, и колонна распадается на части.
    moulding = [(0.0, -1.0), (r * 1.34, -1.0), (r * 1.34, moulding_h * 0.22),
                (r * 1.30, moulding_h * 0.40),      # торус
                (r * 1.20, moulding_h * 0.52),
                (r * 1.08, moulding_h * 0.60),      # выкружка
                (r * 1.10, moulding_h * 0.74),
                (r * 1.05, moulding_h * 0.92),
                (r * 1.04, moulding_h + 1.0), (0.0, moulding_h + 1.0)]
    # эхин на 1 мм выше нужного и ниже на 1 мм — иначе он только касается абаки
    # плоскостью и колонна распадается на две части
    eh = echinus_h + 1.0
    echinus = [(0.0, -1.0), (shaft_r(shaft_h) * 1.02, -1.0),
               (shaft_r(shaft_h) * 1.04, eh * 0.18),
               (shaft_r(shaft_h) * 1.14, eh * 0.45),
               (r * 1.20, eh * 0.78), (r * 1.28, eh), (0.0, eh)]

    lines = [
        comment or f"# Колонна: высота {_num(height)} мм, ствол Ø{_num(diameter)} мм.",
        "# Пропорции античного ордера: 8–10 диаметров в высоту, сужение 12–16 %.",
        "",
        "# 1. Плита и профилированная база.",
        f"плита = box size=[{_num(diameter * 1.36)},{_num(diameter * 1.36)},{_num(plinth_h)}] "
        "at=[0,0,0]",
        f"база = lathe points={_section(moulding)} segments=64",
        f"база = translate [база] offset=[0,0,{_num(plinth_h)}]",
        "",
        "# 2. Ствол с энтазисом — профиль вращения по десяти высотам.",
        f"ствол = lathe points={_section(shaft_pts)} segments=64",
        f"ствол = translate [ствол] offset=[0,0,{_num(base_h)}]",
        "",
        "# 3. Капитель: эхин и абака.",
        f"эхин = lathe points={_section(echinus)} segments=64",
        f"эхин = translate [эхин] offset=[0,0,{_num(base_h + shaft_h)}]",
        f"абака = box size=[{_num(diameter * 1.34)},{_num(diameter * 1.34)},{_num(abacus_h)}] "
        f"at=[0,0,{_num(height - abacus_h)}]",
        "",
        "колонна = union [плита, база, ствол, эхин, абака]",
    ]
    if flutes:
        flute_r = min(r * 0.09, diameter * 0.045)
        lines += [
            "",
            f"# 4. Каннелюры: {flutes} полукруглых борозд, вычтенных по кругу.",
            f"борозда = cylinder radius={_num(flute_r)} height={_num(shaft_h)} segments=16 "
            f"at=[{_num(r)},0,0]",
            f"борозды = array [борозда] count={flutes} mode=radial radius=0 around=z",
            f"борозды = translate [борозды] offset=[0,0,{_num(base_h + 8)}]",
            "колонна = difference [колонна, борозды]",
        ]
    lines += [
        "",
        "колонна = place [колонна] at=[0,0,0]",
        "",
        "# Проверки: габарит и герметичность.",
        f"check колонна size {_range(diameter * 1.36, 1.0)} {_range(diameter * 1.36, 1.0)} "
        f"{_range(height, 0.8)}",
        "check колонна watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  Вход для `forma lib`
# --------------------------------------------------------------------------- #

BUILDERS = {
    "sword": ("Меч одноручный", sword_script),
    "dagger": ("Кинжал-рондель", dagger_script),
    "axe": ("Топор бородатый", axe_script),
    "shield": ("Щит-утюг", shield_script),
    "helmet": ("Шлем кастрюльный", helmet_script),
    "chair": ("Стул обеденный", chair_script),
    "table": ("Стол обеденный", table_script),
    "lamp": ("Фонарный столб", lamp_script),
    "column": ("Колонна классическая", column_script),
}


#: параметры, которые считаются целыми (штуки, а не миллиметры)
INT_PARAMS = {"slats", "flutes", "straps"}


def build_script(kind: str, **options) -> str:
    """Собрать сценарий по имени и текстовым параметрам (для CLI)."""
    key = (kind or "").strip().lower()
    if key not in BUILDERS:
        raise ValueError(f"Неизвестный объект: {kind}. Есть: {', '.join(BUILDERS)}")
    builder = BUILDERS[key][1]
    clean = {}
    for name, value in options.items():
        name = name.strip().lower()
        if name in INT_PARAMS:
            clean[name] = int(float(value))
        else:
            clean[name] = float(value)
    return builder(**clean)


#: текстовка параметров по имени объекта (её показывает `forma lib`)
PARAMS: dict[str, str] = {}


def params_help() -> list[tuple[str, str]]:
    return [
        ("sword", "blade=750 width=50 thickness=5 grip=110 guard=190 pommel=50"),
        ("dagger", "blade=280 width=32 thickness=7 grip=95 guard=64 pommel=46"),
        ("axe", "haft=700 blade=140 thickness=26 edge=4 socket_h=130 haft_w=32 haft_d=26"),
        ("shield", "height=700 width=520 thickness=22 curve=0.07 boss=120 straps=1"),
        ("table", "length=1200 width=700 height=750 top_t=32 leg=60 apron=90 stretcher=0"),
        ("column", "height=3000 diameter=300 taper=0.14 base_h=190 capital_h=210 flutes=0"),
        ("helmet", "head=580 dome=105 brim=70 wall=2.5"),
        ("chair", "seat_h=450 seat=440 back=420 leg=40 slats=3"),
        ("lamp", "height=4000 base_d=300 pole_d=120 top_d=60 arm=700 lantern=260"),
    ]


PARAMS.update(dict(params_help()))
