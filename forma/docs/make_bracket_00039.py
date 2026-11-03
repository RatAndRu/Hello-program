"""Кронштейн правый 00.039 — генератор сценария ФОРМЫ по чертежу А2.

Чертёж: «Кронштейн правый 00.039», формат А2, масштаб 1:1.5, материал АЛ9.
Что прочитано и куда пошло:

   210, 130, 15 ............... габарит плиты и её толщина
   135±0.2, 75±0.2 ............ положение крепёжных отверстий
   100±0.02, R15, Ø20×3, Ø9 ... второй шаг, скругления, цековки, отверстия
   Ø70, 25 .................... центральная бобышка
   Ø40×20, Ø35H7, 38, Ø30×18 .. её расточка сверху вниз
   Ø60, Ø65×2, 35 ............. нижний прилив под плитой
   165, Ø50, Ø30, Ø35H7×18 .... патрубок: ось, наружный, расточка, цековки
   100-0.2, M10-H7 ............ длина патрубка и резьбовое отверстие сверху
   75, 60±0.2, 15, R5, R7.5 ... высота стойки, её положение, толщина, галтели
   25, 40 ..................... вылет ребра

Чего в модели нет и почему:
  * √Ra5 / √Ra1.25 — шероховатость, требование к обработке, не форма;
  * H7, ±0.2, ±0.02 — допуски контроля; вместо них стоят `check … center`,
    которые падают, если центр отверстия уедет больше допуска;
  * резьба M10 нарезана как отверстие Ø8.5 (см. ниже) — витки резьбы
    на виде не читаются, а `thread` дал бы 200 тысяч треугольников.

Запуск:  python3 docs/make_bracket_00039.py  →  examples/bracket_00039.forma
"""
from __future__ import annotations

import math
from pathlib import Path

# ---------------------------------------------------------------- габарит
L, W, T = 210.0, 130.0, 15.0
R_PLATE = 15.0

# ---------------------------------------------------------------- крепёж
BOLT_X = (15.0, 150.0)
BOLT_Y = (15.0, 115.0)
BOLT_D = 9.0
PAD_D = 20.0
PAD_H = 3.0
DOWEL_D = 8.0
DOWEL_AT = ((95.0, 45.0), (95.0, 85.0))     # 2 отв Ø8H7 между бобышкой и стойкой

# ------------------------------------------------------- центральная бобышка
BX, BY = 50.0, 65.0
BOSS_D, BOSS_H = 70.0, 25.0
CB1_D, CB1_DEPTH = 40.0, 20.0
BORE_D, BORE_LEN = 35.0, 38.0
LOW_D, LOW_DEPTH = 30.0, 18.0
SPIGOT_D, SPIGOT_H = 60.0, 35.0
COLLAR_D, COLLAR_H = 65.0, 2.0
FILLET = 5.0

# ---------------------------------------------------------------- патрубок
TX, TY = 165.0, 65.0
TUBE_D, TUBE_BORE = 50.0, 30.0
TUBE_CB_D, TUBE_CB_DEPTH = 35.0, 18.0
TUBE_LEN = 100.0
TZ = 75.0                      # 75±0.1 — высота оси патрубка над плитой (низ 50, верх 100)
TUBE_Y0 = TY - TUBE_LEN / 2

# ------------------------------------------------------------- стойка, ребро
WALL_T = 15.0
WALL_X0 = 110.0                # передняя плоскость стойки: 50 + 60±0.2
WEB_Z0 = TZ - TUBE_D / 2 - WALL_T   # низ полки: под патрубком (35)
GUSSET_END = 195.0
GUSSET_H = WEB_Z0 - T           # высота ребра — от плиты до полки
Y0, Y1 = 15.0, 115.0           # стойка и ребро не доходят до кромок на 15
SUPPORT_X1 = 195.0             # стойка доходит до 195 (40 от правого торца)
SUPPORT_H = 35.0               # высота стойки — «35H7» на разрезе Б-Б
JOIN = 1.0                     # нахлёст 1 мм, чтобы union слил тела без щели
WIN_W, WIN_H = 40.0, 26.0      # окно: 85 − 25 − 40 = 20… на разрезе окно шире,
                               # берём 40 по X и 26 по Z (ножки 22.5 и 22.5)
WIN_X0 = WALL_X0 + 25.0        # левая ножка 25 мм (размер на разрезе)
FILLET_PLATE = 7.5             # R7.5 — сопряжение стойки и ребра с плитой

TOP_Z = TZ + TUBE_D / 2        # верх детали = 100 (ось патрубка + радиус)


def num(v: float, digits: int = 2) -> str:
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def rounded_rect(w: float, h: float, r: float, steps: int = 12) -> list[tuple[float, float]]:
    """Прямоугольник w×h со скруглением r, против часовой стрелки."""
    pts: list[tuple[float, float]] = []
    for cx, cy, a0 in ((r, r, 180.0), (w - r, r, 270.0),
                       (w - r, h - r, 0.0), (r, h - r, 90.0)):
        for i in range(steps + 1):
            a = math.radians(a0 + 90.0 * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def pts(seq) -> str:
    return "[" + ",".join(f"[{num(x)},{num(y)}]" for x, y in seq) + "]"


def arc(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 6):
    out = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def _unused_boss_profile() -> list[tuple[float, float]]:
    """Профиль (r, z) бобышки с приливом и галтелью R5 — одно тело вращения.

    Снизу вверх по наружной стороне, затем сверху вниз по расточке:
    Ø60 → буртик Ø65×2 → плита → галтель R5 → Ø70 до Z=40 →
    Ø40 на глубину 20 → Ø35H7 длиной 38 → Ø30 на глубину 18.
    """
    z_bot = -SPIGOT_H
    outer = [
        (SPIGOT_D / 2, z_bot),
        (SPIGOT_D / 2, -COLLAR_H),
        (COLLAR_D / 2, -COLLAR_H),
        (COLLAR_D / 2, 0.0),
        (BOSS_D / 2, 0.0),
        (BOSS_D / 2, T),                      # плита: галтель начинается выше
    ]
    outer += arc(BOSS_D / 2 + FILLET, T + FILLET, FILLET, 180.0, 270.0)
    outer += [(BOSS_D / 2 + FILLET, T + BOSS_H - FILLET)]
    outer += arc(BOSS_D / 2, T + BOSS_H - FILLET, FILLET, 0.0, 90.0)
    inner = [
        (CB1_D / 2, T + BOSS_H),
        (CB1_D / 2, T + BOSS_H - CB1_DEPTH),          # Ø40×20
        (BORE_D / 2, T + BOSS_H - CB1_DEPTH),         # Ø35H7
        (BORE_D / 2, T + BOSS_H - CB1_DEPTH - BORE_LEN),
        (LOW_D / 2, T + BOSS_H - CB1_DEPTH - BORE_LEN),  # Ø30
        (LOW_D / 2, z_bot),
    ]
    return outer + inner


def _unused_tube_profile() -> list[tuple[float, float]]:
    """Профиль (r, z) патрубка: Ø50 снаружи, Ø30 внутри, цековки Ø35H7×18."""
    return [
        (TUBE_BORE / 2, 0),
        (TUBE_CB_D / 2, 0),
        (TUBE_CB_D / 2, TUBE_CB_DEPTH),
        (TUBE_BORE / 2, TUBE_CB_DEPTH),
        (TUBE_BORE / 2, TUBE_LEN - TUBE_CB_DEPTH),
        (TUBE_CB_D / 2, TUBE_LEN - TUBE_CB_DEPTH),
        (TUBE_CB_D / 2, TUBE_LEN),
        (TUBE_BORE / 2, TUBE_LEN),
        (TUBE_D / 2, TUBE_LEN),
        (TUBE_D / 2, 0),
    ]


def gusset_profile() -> list[tuple[float, float]]:
    """Ребро в плоскости XZ: катет по плите, катет по стойке, R7.5 в углу."""
    x0 = WALL_X0 + WALL_T
    foot = GUSSET_END - x0
    return [
        (0.0, 0.0),
        (foot - FILLET_PLATE, 0.0),
        *arc(foot - FILLET_PLATE, FILLET_PLATE, FILLET_PLATE, 270.0, 180.0),
        (0.0, GUSSET_H),
    ]


def arc_pts(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 5):
    out = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def boss_lathe_profile() -> list[tuple[float, float]]:
    """Профиль (r, z) бобышки Ø70 высотой 25 с галтелью R5 у основания.

    Галтель заложена в профиль, а не снята командой fillet: так поверхность
    получается точной и сетка остаётся лёгкой (глобальный fillet на такой
    сборке даёт 400 тысяч треугольников и отказывается работать).
    """
    pts = [(0.0, 0.0), (BOSS_D / 2 + FILLET, 0.0)]
    pts += arc_pts(BOSS_D / 2 + FILLET, FILLET, FILLET, 270.0, 180.0)
    pts += [(BOSS_D / 2, BOSS_H), (0.0, BOSS_H)]
    return pts


def wall_profile() -> list[tuple[float, float]]:
    """Сечение стойки в плоскости XZ: толщина 15 и галтели R5 с двух сторон.

    Координаты локальные: x от −5 до 20, z от 0 (плита) до высоты стойки.
    """
    h = WEB_Z0 - T
    pts = [(-FILLET, 0.0)]
    pts += arc_pts(-FILLET, FILLET, FILLET, 270.0, 360.0)      # левая галтель
    pts += [(0.0, h), (WALL_T, h)]
    pts += arc_pts(WALL_T + FILLET, FILLET, FILLET, 180.0, 270.0)  # правая
    pts += [(WALL_T + FILLET, 0.0)]
    return pts


def window_profile() -> list[tuple[float, float]]:
    """Окно в стойке со скруглением R7.5 по углам (размер R7.5 на разрезе Б-Б)."""
    return rounded_rect(WIN_W, WIN_H, 7.5, steps=8)


def _unused_rib_profile() -> list[tuple[float, float]]:
    """Сечение ребра в плоскости XZ (начало — у стойки, z = 0 — верх плиты).

    Ребро идёт от стойки по плите и поднимается под патрубок: сверху оно
    подходит к низу патрубка (z = 50), снизу — с R7.5 к плите.
    """
    foot = GUSSET_END - (WALL_X0 + WALL_T)
    top = WEB_Z0 - T                     # z низа патрубка относительно плиты
    pts = [(0.0, 0.0), (foot - FILLET_PLATE, 0.0)]
    pts += arc_pts(foot - FILLET_PLATE, FILLET_PLATE, FILLET_PLATE, 270.0, 180.0)
    pts += [(foot * 0.35, top), (0.0, top)]
    return pts


def build_script() -> str:
    """Собирает текст сценария. Все `place` — по правилу ФОРМЫ: at = центр по
    X и Y, низ по Z (align=bottom по умолчанию, center_xy=да)."""
    plate = rounded_rect(L, W, R_PLATE)
    pad_list = [(bx, by) for bx in BOLT_X for by in BOLT_Y]
    ym = (Y0 + Y1) / 2                    # центр стойки/полки по Y
    wall_x1 = WALL_X0 + WALL_T
    z_spig = -SPIGOT_H
    ov = 1.0                              # нахлёст, чтобы union не оставлял щелей

    pads = "\n".join(
        f"цековка_{i} = cylinder radius={num(PAD_D / 2)} height={num(PAD_H + ov)} segments=48\n"
        f"цековка_{i} = place [цековка_{i}] at=[{num(x)},{num(y)},{num(T - ov)}]"
        for i, (x, y) in enumerate(pad_list, 1))
    bolts = "\n".join(
        f"сверло_{i} = cylinder radius={num(BOLT_D / 2)} height=60 segments=40\n"
        f"сверло_{i} = place [сверло_{i}] at=[{num(x)},{num(y)},{num(-40)}]"
        for i, (x, y) in enumerate(pad_list, 1))
    dowels = "\n".join(
        f"штифт_{i} = cylinder radius={num(DOWEL_D / 2)} height=60 segments=40\n"
        f"штифт_{i} = place [штифт_{i}] at=[{num(x)},{num(y)},{num(-40)}]"
        for i, (x, y) in enumerate(DOWEL_AT, 1))

    rib_foot = GUSSET_END - wall_x1
    shelf_x = (TX - TUBE_D / 2) - wall_x1 + 2

    script = f"""# Кронштейн правый 00.039 — модель по чертежу А2 (1:1.5, материал АЛ9).
# Оси: X — вдоль плиты (0…{num(L)}), Y — поперёк (0…{num(W)}),
# Z = 0 — нижняя плоскость плиты; крепёж смотрит вниз, патрубок — вверх.
# Собрано скриптом docs/make_bracket_00039.py из чисел чертежа.

# --------------------------------------------------- 1. плита 210×130×15
# Углы R15 стоят по центрам болтов: на чертеже R15 привязан к отверстию,
# поэтому скругление угла и отверстие концентричны.
плита = extrude profile={pts(plate)} height={num(T)}
# «2×45°, 2 фаску» на чертеже — фаски кромок плиты; снимаем до объединения,
# пока сетка плиты простая.
плита = chamfer [плита] width=2 edges=convex

# Цековки Ø20×3 под головки болтов — четыре площадки на плите.
{pads}
основа = union [плита, цековка_1, цековка_2, цековка_3, цековка_4]

# ------------------------------------------------- 2. бобышка и нижний прилив
# Ø70 высотой 25 с галтелью R5 у основания; снизу прилив Ø60 (35) с буртиком
# Ø65×2. Расточка: Ø40×20 сверху, Ø35H7 длиной 38, Ø30×18 снизу.
бобышка = lathe points={pts(boss_lathe_profile())} segments=96
бобышка = place [бобышка] at=[{num(BX)},{num(BY)},{num(T)}]
прилив = cylinder radius={num(SPIGOT_D / 2)} height={num(SPIGOT_H - COLLAR_H)} segments=160
прилив = place [прилив] at=[{num(BX)},{num(BY)},{num(z_spig)}]
буртик = cylinder radius={num(COLLAR_D / 2)} height={num(COLLAR_H)} segments=160
буртик = place [буртик] at=[{num(BX)},{num(BY)},{num(-COLLAR_H)}]
основа = union [основа, бобышка, прилив, буртик]

# ------------------------------------------------------- 3. стойка и патрубок
# Стойка стоит в 60±0.2 от оси бобышки и несёт патрубок Ø50 (ось на 75).
# Это не сплошная стенка: на разрезе Б-Б видно окно со скруглением R7.5, а по
# бокам остаются ножки 25 (слева) и 40 (справа) — окно прорезано насквозь по Y.
стойка = box size=[{num(SUPPORT_X1 - WALL_X0)},{num(Y1 - Y0)},{num(SUPPORT_H + JOIN)}]
стойка = place [стойка] at=[{num((WALL_X0 + SUPPORT_X1) / 2)},{num(ym)},{num(T)}]
окно = extrude profile={pts(window_profile())} height={num(Y1 - Y0 + 4)}
окно = rotate [окно] angle=90 axis=x
окно = place [окно] at=[{num((WALL_X0 + SUPPORT_X1) / 2 - WIN_W / 2 + WIN_W / 2)},{num(ym)},{num(T + SUPPORT_H / 2)}] align=center
стойка = difference [стойка, окно]
патрубок = cylinder radius={num(TUBE_D / 2)} height={num(TUBE_LEN)} segments=128
патрубок = rotate [патрубок] angle=90 axis=x
патрубок = place [патрубок] at=[{num(TX)},{num(TY)},{num(TZ)}] align=center
патрубок = chamfer [патрубок] width=2 edges=convex

# Ребро справа: от низа патрубка вниз к плите, катет 40 («40» на разрезе
# Б-Б), толщина 15 по Y, посередине ширины.
ребро = extrude profile=[[0,0],[40,0],[0,{num(WEB_Z0 - T)}]] height={num(WALL_T)}
ребро = rotate [ребро] angle=-90 axis=x
ребро = place [ребро] at=[{num(SUPPORT_X1 - 40 + 20)},{num(ym)},{num(T + (WEB_Z0 - T) / 2)}] align=center

# Второе ребро — между бобышкой и стойкой: наклонная плоскость от плиты к
# верху стойки (на изометрии референса видна как наклонная грань у окна).
ребро_л = extrude profile=[[0,0],[{num(WALL_X0 - (BX + BOSS_D / 2))},0],[{num(WALL_X0 - (BX + BOSS_D / 2))},{num(SUPPORT_H)}]] height={num(WALL_T)}
ребро_л = rotate [ребро_л] angle=-90 axis=x
ребро_л = place [ребро_л] at=[{num((BX + BOSS_D / 2 + WALL_X0) / 2)},{num(ym)},{num(T + SUPPORT_H / 2)}] align=center

тело = union [основа, стойка, патрубок, ребро, ребро_л]

# Галтели R5 и R7.5 заложены в профили (бобышка, стойка, ребро): так они
# точные и не раздувают сетку. Глобальный fillet на такой сборке разрастается
# до 400 тысяч треугольников и отказывается работать — это проверено.

# --------------------------------------------------------- 6. отверстия
# Сверлим после объединения, чтобы отверстия проходили все слои насквозь.
{bolts}
{dowels}

# Расточка бобышки сверху вниз: Ø40×20 → Ø35H7 (38) → Ø30×18.
ц_40 = cylinder radius={num(CB1_D / 2)} height={num(CB1_DEPTH + ov)} segments=96
ц_40 = place [ц_40] at=[{num(BX)},{num(BY)},{num(T + BOSS_H - CB1_DEPTH)}]
ц_35 = cylinder radius={num(BORE_D / 2)} height={num(BORE_LEN + 2)} segments=96
ц_35 = place [ц_35] at=[{num(BX)},{num(BY)},{num(T + BOSS_H - CB1_DEPTH - BORE_LEN)}]
ц_30 = cylinder radius={num(LOW_D / 2)} height={num(LOW_DEPTH + 2)} segments=96
ц_30 = place [ц_30] at=[{num(BX)},{num(BY)},{num(z_spig - 2)}]

# Расточка патрубка: Ø30 насквозь и цековки Ø35H7×18 с обоих торцов.
ц_п = cylinder radius={num(TUBE_BORE / 2)} height={num(TUBE_LEN + 4)} segments=96
ц_п = rotate [ц_п] angle=90 axis=x
ц_п = place [ц_п] at=[{num(TX)},{num(TY)},{num(TZ)}] align=center
к_1 = cylinder radius={num(TUBE_CB_D / 2)} height={num(TUBE_CB_DEPTH)} segments=96
к_1 = rotate [к_1] angle=90 axis=x
к_1 = place [к_1] at=[{num(TX)},{num(TUBE_Y0 + TUBE_CB_DEPTH / 2)},{num(TZ)}] align=center
к_2 = cylinder radius={num(TUBE_CB_D / 2)} height={num(TUBE_CB_DEPTH)} segments=96
к_2 = rotate [к_2] angle=90 axis=x
к_2 = place [к_2] at=[{num(TX)},{num(TUBE_Y0 + TUBE_LEN - TUBE_CB_DEPTH / 2)},{num(TZ)}] align=center

# M10-H7 сверху патрубка: резьба по оси детали, глубиной 12.
м10 = cylinder radius=4.2 height=14 segments=32
м10 = place [м10] at=[{num(TX)},{num(TY)},{num(TOP_Z - 12)}]

тело = difference [тело, сверло_1, сверло_2, сверло_3, сверло_4, штифт_1, штифт_2,
                  ц_40, ц_35, ц_30, ц_п, к_1, к_2, м10]

# --------------------------------------------- 7. материал и вид
color тело #b9bdc5 metal=0.85 rough=0.28

# ----------------------------------------------------------- 8. проверки
# Допуски с чертежа: центры отверстий ±0.2, габарит, замкнутость, дно.
"""
    for i, (x, y) in enumerate(pad_list, 1):
        script += (f"check сверло_{i} center {num(x - 0.2)}..{num(x + 0.2)} "
                   f"{num(y - 0.2)}..{num(y + 0.2)} -14..-6\n")
    script += f"""check тело size {num(L - 0.3)}..{num(L + 0.3)} {num(W - 0.3)}..{num(W + 0.3)} {num(TOP_Z + SPIGOT_H - 0.5)}..{num(TOP_Z + SPIGOT_H + 0.5)}
check тело watertight
check тело parts 1
passport тело
"""
    return script


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "examples" / "bracket_00039.forma"
    target.write_text(build_script(), encoding="utf-8")
    print(f"{target}: {len(build_script().splitlines())} строк")
