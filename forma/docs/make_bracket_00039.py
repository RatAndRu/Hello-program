"""Кронштейн правый 00.039 — генератор сценария ФОРМЫ по чертежу А2.

РАУНД 14. ЧТО БЫЛО НЕ ТАК В РАУНДЕ 13 (и что сделано иначе)

  * Опору я рисовал коробкой с двумя вертикальными ножками по краям Y и
    маленьким окном 55x20. На листе (изометрия + разрез Б-Б) опора — это
    СТЕНКА толщиной 100 по Y, у которой:
      - левая грань — скос 45° от плиты вверх (на разрезе это и есть та
        «диагональ», которую я в раунде 13 принял за косынку внутри окна);
      - окно — ТРАПЕЦИЯ: низ шире верха, левая кромка идёт по тому же 45°,
        низ на плите, верх на 20 мм выше; R5 слева внизу, R7.5 в остальных
        углах;
      - сверху полка 15 мм, патрубок лежит на ней и сливается галтелью R5;
      - справа — большой скос от низа патрубка к плите (40 мм по X).
  * Косынки внутри окна нет: разрез Б-Б на Y=65 идёт посередине окна и
    показывает там пустоту. «Косынка» раунда 13 — моя выдумка.
  * Патрубок я ставил вдоль Y поперёк плиты. Разрез Б-Б — это разрез
    плоскостью XZ (линия разреза на виде сверху горизонтальная), и патрубок
    на нём вскрыт ВДОЛЬ оси => ось патрубка идёт вдоль X.
  * Юбка бобышки была конусом с изломом; сделана вогнутой галтелью R8.
  * Цековки Ø20x3 — углубления в плите (раньше приподнятые площадки).

РАЗМЕРЫ С ЛИСТА

   210 x 130 x 15 ............. плита, углы R15, фаска 2x45°
   165 / 100 .................. шаг крепёжных отверстий (22.5/187.5, 15/115)
   4 отв. Ø9, Ø20x3 ........... болты и цековки под головки
   2 отв. Ø8H7 ................ штифты
   Ø70 / 25 ................... бобышка над плитой (юбка R5 — по разрезу Б-Б)
   Ø40x20, Ø35H7x38, Ø30x18 ... расточка бобышки сверху вниз
   Ø60 / 35, Ø65x2 ............ прилив и буртик под плитой
   Ø50, 100 ................... патрубок: наружный Ø и длина
   135 / 75 ................... ось патрубка от левого и правого торца плиты
   75±0.1 ..................... высота оси патрубка над низом плиты
   Ø30, 2 отв. Ø35H7x18 ....... расточка патрубка и цековки с торцов
   M10-H7 ..................... резьба сверху патрубка (сверлим Ø8.4)
   100 ........................ ширина опоры по Y
   15 ......................... полка над окном, материал справа от окна
   R5, R7.5 ................... углы окна, галтель седла под патрубком
   45° ........................ скосы опоры слева и справа (выведено по разрезу)

Запуск:  python3 docs/make_bracket_00039.py  ->  examples/bracket_00039.forma
"""
from __future__ import annotations

import math
from pathlib import Path

# ---------------------------------------------------------------- плита
L, W, T = 210.0, 130.0, 15.0
R_PLATE = 15.0
EDGE = 2.0

# ---------------------------------------------------------------- крепёж
BOLT_X = (15.0, 150.0)
BOLT_Y = (15.0, 115.0)
BOLT_D = 9.0
PAD_D, PAD_H = 20.0, 3.0
DOWEL_D = 8.0
DOWEL_AT = ((90.0, 45.0), (90.0, 85.0))   # 15 + 75 по X, 40 по Y (см. документ)

# ---------------------------------------------------------------- бобышка
BX, BY = 45.0, 65.0
BOSS_D, BOSS_H = 70.0, 25.0
SKIRT = 5.0                    # R5 у основания бобышки — как на разрезе Б-Б;
                               # больше (R8) давало «фаску», выходящую за край
CB1_D, CB1_DEPTH = 40.0, 20.0
BORE_D, BORE_LEN = 35.0, 38.0
LOW_D, LOW_DEPTH = 30.0, 18.0
SPIGOT_D, SPIGOT_H = 60.0, 35.0
COLLAR_D, COLLAR_H = 65.0, 2.0

# ---------------------------------------------------------------- патрубок
TUBE_D, TUBE_BORE = 50.0, 30.0
TUBE_CB_D, TUBE_CB_DEPTH = 35.0, 18.0
TUBE_LEN = 100.0
TZ = 75.0                      # ось патрубка над низом плиты (75±0.1)
TX0 = 85.0                     # левый торец патрубка
TX1 = TX0 + TUBE_LEN           # 185
TCX = (TX0 + TX1) / 2          # 135 — ось по X
TY = 65.0
SADDLE = 5.0                   # R5 — галтель седла под патрубком

# ---------------------------------------------------------------- опора
SUP_Y0, SUP_Y1 = 15.0, 115.0    # 100 по Y. На листе толщина стенки не
                               # проставлена; 100 взято по разрезу Б-Б.
                               # Стенку уже ~95 мм ядро не пропускает: её
                               # боковые плоскости касаются патрубка и CSG
                               # даёт вырожденные грани (см. документ, §5).
SHELF_Z = TZ - TUBE_D / 2 + 2.0  # полка входит в патрубок на 2 мм: при точном
                                 # касании CSG даёт вырожденный стык и дыры в сетке
SUP_L_X0, SUP_L_X1 = 88.0, 124.0   # левый скос 45°: от плиты к полке
SUP_R_X1, SUP_R_X0 = 182.0, 152.0  # правый скос: от патрубка к плите (30);
                                   # торцы стенки утоплены под патрубок на 3 мм
WIN_Z1 = 37.0                  # верх окна: над ним 15 мм до низа патрубка
WIN_X0, WIN_X1 = 96.0, 142.0   # низ окна 46 мм
WIN_SLANT_X1 = 118.0           # верх левой кромки окна (тот же 45°)
WIN_R_BL, WIN_R = 5.0, 7.5

TOP_Z = TZ + TUBE_D / 2        # 100
BOTTOM_Z = -SPIGOT_H           # -35


def num(v: float, digits: int = 2) -> str:
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def pts(seq) -> str:
    return "[" + ",".join(f"[{num(x)},{num(y)}]" for x, y in seq) + "]"


def arc(cx, cy, r, a0, a1, steps=8):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
            for i in range(steps + 1)]


def rounded_rect(w, h, r, steps=10):
    out = []
    for cx, cy, a0 in ((r, r, 180.0), (w - r, r, 270.0),
                       (w - r, h - r, 0.0), (r, h - r, 90.0)):
        out += arc(cx, cy, r, a0, a0 + 90.0, steps)
    return out


def fillet_poly(points, radii, steps=8):
    """Замкнутый контур по точкам с круговыми скруглениями вершин.

    Точки касания откладываются вдоль сторон на r/tan(θ/2), центр дуги —
    по внутренней нормали, дуга берётся короткая. Так скругление всегда
    «срезает» угол и не вылезает наружу при любом направлении обхода.
    """
    n = len(points)
    area = sum(points[i][0] * points[(i + 1) % n][1]
               - points[(i + 1) % n][0] * points[i][1] for i in range(n))
    sgn = 1.0 if area > 0 else -1.0     # +1 — обход против часовой
    out = []
    for i, (p, r) in enumerate(zip(points, radii)):
        pp = points[i - 1]
        pn = points[(i + 1) % n]
        if r <= 0:
            out.append(p)
            continue
        u = (pp[0] - p[0], pp[1] - p[1])   # к предыдущей вершине
        v = (pn[0] - p[0], pn[1] - p[1])   # к следующей
        lu, lv = math.hypot(*u), math.hypot(*v)
        u = (u[0] / lu, u[1] / lu)
        v = (v[0] / lv, v[1] / lv)
        cosang = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
        theta = math.acos(cosang)                  # внутренний угол
        d = r / math.tan(theta / 2.0)
        t1 = (p[0] + u[0] * d, p[1] + u[1] * d)
        t2 = (p[0] + v[0] * d, p[1] + v[1] * d)
        n1 = (u[1] * sgn, -u[0] * sgn)             # внутренняя нормаль
        c = (t1[0] + n1[0] * r, t1[1] + n1[1] * r)
        a0 = math.degrees(math.atan2(t1[1] - c[1], t1[0] - c[0]))
        a1 = math.degrees(math.atan2(t2[1] - c[1], t2[0] - c[0]))
        da = (a1 - a0 + 540.0) % 360.0 - 180.0     # короткая дуга
        out += arc(c[0], c[1], r, a0, a0 + da, steps)
    return out


def boss_profile():
    """Тело вращения бобышки: юбка R8 вогнутой дугой, цилиндр Ø70, верх 25."""
    r0 = BOSS_D / 2
    r_sk = r0 + SKIRT
    prof = [(0.0, 0.0), (r_sk, 0.0)]
    # вогнутая галтель от плиты (r_sk, 0) к цилиндру (r0, SKIRT)
    prof += arc(r0 + SKIRT, SKIRT, SKIRT, 270.0, 180.0)
    prof += [(r0, BOSS_H), (0.0, BOSS_H)]
    return prof


def build_script() -> str:
    plate = rounded_rect(L, W, R_PLATE)
    bolts = [(x, y) for x in BOLT_X for y in BOLT_Y]
    ymid = (SUP_Y0 + SUP_Y1) / 2
    sup_w = SUP_Y1 - SUP_Y0

    # стенка входит в плиту на 3 мм: точный контакт по плоскости CSG не
    # сливает, и деталь распадается на две части (parts 2)
    sup_z0 = T - 3.0
    support = [(SUP_L_X0, sup_z0), (SUP_L_X1, SHELF_Z),
               (SUP_R_X1, SHELF_Z), (SUP_R_X0, sup_z0)]
    window = fillet_poly([(WIN_X0, T), (WIN_SLANT_X1, WIN_Z1),
                          (WIN_X1, WIN_Z1), (WIN_X1, T)],
                         [WIN_R_BL, WIN_R, WIN_R, WIN_R])

    pads = "\n".join(
        f"цековка_{i} = cylinder radius={num(PAD_D / 2)} height=30 segments=64\n"
        f"цековка_{i} = place [цековка_{i}] at=[{num(x)},{num(y)},{num(T - PAD_H)}]"
        for i, (x, y) in enumerate(bolts, 1))
    drills = "\n".join(
        f"сверло_{i} = cylinder radius={num(BOLT_D / 2)} height=80 segments=48\n"
        f"сверло_{i} = place [сверло_{i}] at=[{num(x)},{num(y)},-50]"
        for i, (x, y) in enumerate(bolts, 1))
    dowels = "\n".join(
        f"штифт_{i} = cylinder radius={num(DOWEL_D / 2)} height=80 segments=48\n"
        f"штифт_{i} = place [штифт_{i}] at=[{num(x)},{num(y)},-50]"
        for i, (x, y) in enumerate(DOWEL_AT, 1))

    script = f"""# Кронштейн правый 00.039 — модель по чертежу А2 (1:1.5, материал АЛ9).
# Оси: X — вдоль плиты (0…{num(L)}), Y — поперёк (0…{num(W)}), Z = 0 — низ плиты.
# Собрано скриптом docs/make_bracket_00039.py из чисел чертежа.

# --------------------------------------------------- 1. плита 210×130×15
# Углы R15, фаска 2×45° по верхней кромке.
плита = extrude profile={pts(plate)} height={num(T)}
плита = chamfer [плита] width={num(EDGE)} edges=convex

# Ø20×3 — ЦЕКОВКИ под головки: углубления в плите (не площадки).
{pads}

# -------------------------------------------------- 2. бобышка и прилив
# Ø70 высотой 25, снизу вогнутая юбка R5; расточка Ø40×20 сверху,
# Ø35H7 длиной 38, Ø30×18 снизу. Под плитой прилив Ø60 с буртиком Ø65×2.
бобышка = lathe points={pts(boss_profile())} segments=128
бобышка = place [бобышка] at=[{num(BX)},{num(BY)},{num(T)}]
прилив = cylinder radius={num(SPIGOT_D / 2)} height={num(SPIGOT_H - COLLAR_H)} segments=128
прилив = place [прилив] at=[{num(BX)},{num(BY)},{num(BOTTOM_Z)}]
буртик = cylinder radius={num(COLLAR_D / 2)} height={num(COLLAR_H)} segments=128
буртик = place [буртик] at=[{num(BX)},{num(BY)},{num(-COLLAR_H)}]

# ------------------------------------------------------- 3. опора-стенка
# Разрез Б-Б: левая грань — скос 45° от плиты (X {num(SUP_L_X0)}) к полке
# (X {num(SUP_L_X1)}, Z {num(SHELF_Z)}), справа — скос 40 мм от низа патрубка
# к плите. Толщина стенки по Y — 100. Стенка и патрубок сливаются галтелью R5,
# поэтому скосы и седло считаются ДО вырезания окна.
опора = extrude profile={pts(support)} height={num(sup_w)}
опора = rotate [опора] angle=90 axis=x
опора = place [опора] at=[{num((SUP_L_X0 + SUP_R_X1) / 2)},{num((SUP_Y0 + SUP_Y1) / 2)},{num((T + SHELF_Z) / 2)}] align=center

# ----------------------------------------------------------- 4. патрубок
# Ø50 длиной 100 вдоль X (ось на Z {num(TZ)} = 75±0.1 над низом плиты).
# Фаски 2×45° заложены в профиль: `chamfer` по торцу цилиндра оставлял в
# сетке 3 граничных ребра (проверено экспортом STL — файл не проходил).
патрубок = lathe points={pts([(0.0, 0.0), (TUBE_D / 2 - EDGE, 0.0), (TUBE_D / 2, EDGE),
                              (TUBE_D / 2, TUBE_LEN - EDGE), (TUBE_D / 2 - EDGE, TUBE_LEN),
                              (0.0, TUBE_LEN)])} segments=128
патрубок = rotate [патрубок] angle=90 axis=y
патрубок = place [патрубок] at=[{num(TCX)},{num(TY)},{num(TZ)}] align=center

узел = union [опора, патрубок]
узел = fillet [узел] radius={num(SADDLE)} edges=concave segments=10

# Окно вырезается ПОСЛЕ галтели: иначе R5 зализал бы его кромки.
окно = extrude profile={pts(window)} height={num(sup_w + 8)}
окно = rotate [окно] angle=90 axis=x
окно = place [окно] at=[{num((WIN_X0 + WIN_X1) / 2)},{num((SUP_Y0 + SUP_Y1) / 2)},{num((T + WIN_Z1) / 2)}] align=center
узел = difference [узел, окно]

тело = union [плита, бобышка, прилив, буртик, узел]

# --------------------------------------------------------- 5. отверстия
# В плите — крепёж и штифты.
{drills}
{dowels}
ц_40 = cylinder radius={num(CB1_D / 2)} height={num(CB1_DEPTH + 1)} segments=96
ц_40 = place [ц_40] at=[{num(BX)},{num(BY)},{num(T + BOSS_H - CB1_DEPTH)}]
ц_35 = cylinder radius={num(BORE_D / 2)} height={num(BORE_LEN + 4)} segments=96
ц_35 = place [ц_35] at=[{num(BX)},{num(BY)},{num(T + BOSS_H - CB1_DEPTH - BORE_LEN)}]
ц_30 = cylinder radius={num(LOW_D / 2)} height={num(LOW_DEPTH + 4)} segments=96
ц_30 = place [ц_30] at=[{num(BX)},{num(BY)},{num(BOTTOM_Z)}]
# В патрубке — Ø30 насквозь и цековки Ø35H7×18 с обоих торцов.
ц_п = cylinder radius={num(TUBE_BORE / 2)} height={num(TUBE_LEN + 6)} segments=96
ц_п = rotate [ц_п] angle=90 axis=y
ц_п = place [ц_п] at=[{num(TCX)},{num(TY)},{num(TZ)}] align=center
к_1 = cylinder radius={num(TUBE_CB_D / 2)} height={num(TUBE_CB_DEPTH)} segments=96
к_1 = rotate [к_1] angle=90 axis=y
к_1 = place [к_1] at=[{num(TX0 + TUBE_CB_DEPTH / 2)},{num(TY)},{num(TZ)}] align=center
к_2 = cylinder radius={num(TUBE_CB_D / 2)} height={num(TUBE_CB_DEPTH)} segments=96
к_2 = rotate [к_2] angle=90 axis=y
к_2 = place [к_2] at=[{num(TX1 - TUBE_CB_DEPTH / 2)},{num(TY)},{num(TZ)}] align=center
# M10-H7 — радиальное отверстие сверху патрубка, по его середине.
м10 = cylinder radius=4.2 height=26 segments=32
м10 = place [м10] at=[{num(TCX)},{num(TY)},{num(TOP_Z - 26)}]

тело = difference [тело, сверло_1, сверло_2, сверло_3, сверло_4, штифт_1, штифт_2,
                  цековка_1, цековка_2, цековка_3, цековка_4,
                  ц_40, ц_35, ц_30, ц_п, к_1, к_2, м10]
color тело #c9ccd2 metal=0.9 rough=0.22

# ----------------------------------------------------------- 6. проверки
"""
    for i, (x, y) in enumerate(bolts, 1):
        script += (f"check сверло_{i} center {num(x - 0.2)}..{num(x + 0.2)} "
                   f"{num(y - 0.2)}..{num(y + 0.2)} -14..-6\n")
    script += f"""check тело size {num(L - 0.3)}..{num(L + 0.3)} {num(W - 0.3)}..{num(W + 0.3)} {num(TOP_Z - BOTTOM_Z - 0.5)}..{num(TOP_Z - BOTTOM_Z + 0.5)}
check тело watertight
check тело parts 1
passport тело
"""
    return script


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "examples" / "bracket_00039.forma"
    text = build_script()
    target.write_text(text, encoding="utf-8")
    print(f"{target}: {len(text.splitlines())} строк")
