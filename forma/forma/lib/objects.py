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
    if blade < 200:
        raise ValueError("Клинок короче 200 мм — это уже кинжал, а не меч.")
    grip, guard, pommel = float(grip), float(guard), float(pommel)
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
    if height < 1500:
        raise ValueError("Столб ниже 1500 мм — это садовый светильник, а не фонарь.")
    base_h = 140.0
    bracket_h = top_d * 0.8              # высота кронштейна
    bracket_top = height - 6.0           # верх кронштейна чуть ниже верха столба
    bracket_z = bracket_top - bracket_h
    pole_top = height - 10.0             # столб входит в кронштейн, торец внутри
    lantern_h = lantern * 1.35
    roof_h = lantern * 0.35
    fin_h = lantern * 0.2                # шпиль на крыше
    fin_z = height + roof_h * 0.6        # низ шпиля — внутри крыши
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
        f"крыша = box size=[{_num(lantern * 1.06)},{_num(lantern * 1.06)},{_num(roof_h)}] round=6 "
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
#  Вход для `forma lib`
# --------------------------------------------------------------------------- #

BUILDERS = {
    "sword": ("Меч одноручный", sword_script),
    "helmet": ("Шлем кастрюльный", helmet_script),
    "chair": ("Стул обеденный", chair_script),
    "lamp": ("Фонарный столб", lamp_script),
}


def build_script(kind: str, **options) -> str:
    """Собрать сценарий по имени и текстовым параметрам (для CLI)."""
    key = (kind or "").strip().lower()
    if key not in BUILDERS:
        raise ValueError(f"Неизвестный объект: {kind}. Есть: {', '.join(BUILDERS)}")
    builder = BUILDERS[key][1]
    clean = {}
    for name, value in options.items():
        name = name.strip().lower()
        if name == "slats":
            clean[name] = int(float(value))
        else:
            clean[name] = float(value)
    return builder(**clean)


def params_help() -> list[tuple[str, str]]:
    return [
        ("sword", "blade=750 width=50 thickness=5 grip=110 guard=190 pommel=50"),
        ("helmet", "head=580 dome=105 brim=70 wall=2.5"),
        ("chair", "seat_h=450 seat=440 back=420 leg=40 slats=3"),
        ("lamp", "height=4000 base_d=300 pole_d=120 top_d=60 arm=700 lantern=260"),
    ]
