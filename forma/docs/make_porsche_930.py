"""Сборка сценария Porsche 911 Turbo (930) по заводскому чертежу.

Зачем генератор, а не готовый текст: у лофта 24 сечения и по 18 точек в каждом,
и все они считаются из семи чисел чертежа. Если считать вручную, ошибку в
одной координате никто не найдёт; здесь числа выводятся из размеров, а сам
сценарий остаётся обычным текстом на языке ФОРМЫ (его можно править руками).

Чертёж (лист «Порше-911 Турбо», проекции сбоку, сверху, спереди и сзади):

    длина .............. 4291 мм
    ширина ............. 1775 мм
    высота ............. 1310 мм
    база ............... 2272 мм
    колея передняя ..... 1432 мм
    колея задняя ....... 1492 мм

Чего на чертеже нет и что принято допущением (это честно помечено в сценарии):
  * шины: 225/50 R16 спереди (ø632) и 245/45 R16 сзади (ø650) — размеров шин
    на листе нет, взяты штатные для 930 Turbo;
  * дорожный просвет 150 мм — на листе не указан;
  * форма кузова между проекциями восстановлена по трём видам (бок, сверху,
    спереди); это не обмер, а построение по силуэту.

Две цели сборки:

    python3 docs/make_porsche_930.py            → examples/porsche_930.forma
        884 числа в явном виде; читается везде, включая 0.58.

    python3 docs/make_porsche_930.py --params   → examples/porsche_930_params.forma
        те же сечения, но каждая координата — выражение от шести `param`
        (панель параметров и presets из 0.67) плюс точные проверки
        пересечений `collision` из 0.66. Нужна версия 0.66+.
"""
from __future__ import annotations

import sys
from pathlib import Path

# --------------------------------------------------------------------- числа
L = 4291.0          # длина
W = 1775.0          # ширина
H = 1310.0          # высота
WB = 2272.0         # база
TRACK_F = 1432.0    # колея передняя
TRACK_R = 1492.0    # колея задняя

CLEARANCE = 150.0   # дорожный просвет (допущение)
TIRE_F = 632.0      # ø шины спереди (225/50 R16)
TIRE_R = 650.0      # ø шины сзади  (245/45 R16)

X0, X1 = -L / 2, L / 2
AXLE_F, AXLE_R = -WB / 2, WB / 2

#: Режим вывода координат. False — числа, True — выражения от параметров.
PARAMS = "--params" in sys.argv


def hw(fraction: float) -> float:
    """Полуширина кузова по доле от максимума (1775/2)."""
    return W / 2 * fraction


#: Осевая линия кузова: x → (верх, низ, полуширина «по борту», полуширина верха).
#: Верх снят с вида сбоку, полуширина — с вида сверху, низ — с вида сбоку.
STATIONS: list[tuple[float, float, float, float, float]] = [
    (X0,          600.0, 330.0, 0.88, 0.90),   # носок бампера
    (X0 + 120,    660.0, 260.0, 0.92, 0.92),
    (X0 + 300,    712.0, 205.0, 0.94, 0.90),   # передний бампер
    (X0 + 560,    742.0, 175.0, 0.93, 0.88),   # капот у фар
    (X0 + 900,    760.0, 160.0, 0.95, 0.86),   # фары/крылья
    (X0 + 1250,   768.0, 152.0, 0.96, 0.86),
    (X0 + 1500,   790.0, 150.0, 0.97, 0.84),   # основание лобового стекла
    (X0 + 1680,   860.0, 150.0, 0.97, 0.80),
    (X0 + 1815,   985.0, 150.0, 0.98, 0.72),   # стойка лобового
    (X0 + 1930,   1120.0, 150.0, 0.98, 0.66),
    (X0 + 2020,   1230.0, 150.0, 0.985, 0.62),
    (X0 + 2085,   1290.0, 150.0, 0.99, 0.60),  # передняя кромка крыши
    (X0 + 2160,   H - 3, 150.0, 0.9986, 0.60),  # крыша (см. пояснение ниже)
    (X0 + 2350,   H - 3, 150.0, 0.9986, 0.60),
    (X0 + 2520,   H - 15, 150.0, 1.00, 0.62),   # задняя кромка крыши
    (X0 + 2700,   1215.0, 150.0, 1.00, 0.72),  # заднее стекло
    (X0 + 2900,   1105.0, 152.0, 1.00, 0.82),
    (X0 + 3100,   1030.0, 158.0, 1.00, 0.88),
    (X0 + 3300,   1010.0, 165.0, 1.00, 0.90),  # моторный отсек, задние крылья
    (X0 + 3550,   1005.0, 172.0, 1.00, 0.90),
    (X0 + 3800,   995.0, 185.0, 0.99, 0.90),
    (X0 + 4000,   960.0, 205.0, 0.97, 0.90),
    (X0 + 4140,   915.0, 240.0, 0.93, 0.90),   # задний бампер
    (X1,          860.0, 300.0, 0.88, 0.90),
]


def contour(zt: float, zb: float, w_frac: float, wt_frac: float) -> list[tuple[float, float]]:
    """Замкнутый контур поперечного сечения: низ → борт → верх → другой борт.

    Полуширина берётся по чертежу «вид сверху»; верх уже низа — это и даёт
    характерный для 911 наклон бортов к крыше.
    """
    w = hw(w_frac)
    wt = hw(wt_frac)
    h = zt - zb
    shoulder = zb + 0.52 * h
    right = [
        (0.0, zb),
        (0.46 * w, zb + 0.01 * h),
        (0.80 * w, zb + 0.07 * h),
        (0.96 * w, zb + 0.24 * h),
        (w, shoulder),
        (0.97 * w, zb + 0.74 * h),
        (max(wt, 0.62 * w), zb + 0.94 * h),
        (wt * 0.60, zt),
        (0.0, zt),
    ]
    left = [(-y, z) for y, z in reversed(right[1:-1])]
    return right + left


def fmt(value: float) -> str:
    """Число без лишних нулей: 1775, 887.5, 1310.25."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _scale(base: str, fraction: float) -> str:
    """Выражение «доля от размера»: L*0.5, -W/2*0.898, H*0.99771."""
    if abs(fraction) < 1e-9:
        return "0"
    body = f"{abs(fraction):.5f}"
    return f"{base}*{body}" if fraction > 0 else f"-{base}*{body}"


def cx(value: float) -> str:
    """Координата по длине: доля от L (или число)."""
    return _scale("L", value / L) if PARAMS else fmt(value)


def cwb(value: float) -> str:
    """Координата вдоль базы: доля от WB (оси колёс)."""
    return _scale("WB", value / WB) if PARAMS else fmt(value)


def cyw(value: float) -> str:
    """Координата по ширине кузова: доля от W/2."""
    return _scale("W/2", value / (W / 2)) if PARAMS else fmt(value)


def cykf(value: float) -> str:
    """Координата по передней колее: доля от KF/2."""
    return _scale("KF/2", value / (TRACK_F / 2)) if PARAMS else fmt(value)


def cykr(value: float) -> str:
    """Координата по задней колее: доля от KR/2."""
    return _scale("KR/2", value / (TRACK_R / 2)) if PARAMS else fmt(value)


def cz(value: float) -> str:
    """Координата по высоте: доля от H."""
    return _scale("H", value / H) if PARAMS else fmt(value)


def body_height(margin: float = 0.0) -> str:
    """Высота кузова над землёй = H − просвет (+ допуск). Просвет — допущение
    (150 мм), поэтому в проверке он стоит рядом с H и видно, откуда число."""
    if PARAMS:
        sign = "+" if margin > 0 else "-"
        tail = f"{sign}{abs(margin):.0f}" if margin else ""
        return f"H-{fmt(CLEARANCE)}{tail}"
    return fmt(H - CLEARANCE + margin)


def cz_from(zb: float, z: float) -> str:
    """Высота точки сечения.

    Низ кузова (просвет) — абсолютное число от земли, а не доля H: иначе
    ползунок «высота» уводил бы машину с пола. Верх и промежуточные точки
    считаются как доля оставшейся высоты: 150 + (H − 150) · k.
    """
    if not PARAMS:
        return fmt(z)
    if abs(z - zb) < 1e-6:
        return fmt(zb)
    frac = (z - zb) / (H - zb)
    return f"{fmt(zb)}+(H-{fmt(zb)})*{frac:.5f}"


def fmt_points(points: list[tuple[float, float]], zb: float) -> str:
    return "[" + ",".join(f"[{cyw(y)},{cz_from(zb, z)}]" for y, z in points) + "]"


PARAM_BLOCK = """# ---------------------------------------------- чертёж как параметры (0.66+)
# Шесть чисел листа объявлены параметрами: в приложении они становятся
# ползунками, а `preset` даёт готовые наборы. Все координаты ниже — выражения
# от этих шести чисел, поэтому сдвиг ползунка перестраивает кузов целиком,
# а проверки в конце пересчитывают допуски от тех же параметров.
param L=4291 min=3800 max=4800 step=1 label="Длина, мм" group="Чертёж"
param W=1775 min=1600 max=2000 step=1 label="Ширина, мм" group="Чертёж"
param H=1310 min=1150 max=1450 step=1 label="Высота, мм" group="Чертёж"
param WB=2272 min=2000 max=2600 step=1 label="База, мм" group="Чертёж"
param KF=1432 min=1300 max=1650 step=1 label="Колея передняя, мм" group="Чертёж"
param KR=1492 min=1350 max=1700 step=1 label="Колея задняя, мм" group="Чертёж"

# Наборы: сток — числа листа; «низкий» и «широкий» — две проверки того, что
# сценарий действительно параметрический, а не жёстко зашитый.
# Важно: объявление набора сразу его применяет, поэтому «сток» идёт последним
# и файл собирается ровно в заводских числах листа.
preset низкий H=1250
preset широкий W=1830 KR=1520
preset сток L=4291 W=1775 H=1310 WB=2272 KF=1432 KR=1492
"""

HEADER = """# Porsche 911 Turbo (930) по заводскому чертежу — тип 930, 3.3 л.
# Габариты взяты с листа: {L} x {W} x {H} мм, база {WB} мм,
# колея {KF} спереди и {KR} сзади. Ось X — вдоль машины
# (перед слева, -X), ось Y — поперёк, Z — вверх, пол на Z=0.
# Файл собран скриптом docs/make_porsche_930.py: сечения считаются из этих чисел.
# Чего на чертеже нет: размеров шин (взяты штатные {tire_f}/{tire_r} мм)
# и просвета ({clearance} мм) — они помечены как допущения.
{mode}"""

MODE_NOTE = """
# ВАРИАНТ ДЛЯ 0.66+: координаты записаны выражениями от параметров.
"""


def build_script() -> str:
    sections = [contour(zt, zb, w, wt) for _, zt, zb, w, wt in STATIONS]
    positions = [x for x, *_ in STATIONS]

    sections_block = "сечения = [\n" + "".join(
        f"  {fmt_points(s, station[2])},\n" for s, station in zip(sections, STATIONS)) + "]\n"
    # строка целиком: перенос ''' внутри f-строки съел бы перевод строки
    positions_line = ("positions=[" + ", ".join(cx(x) for x in positions) + "] axis=x")

    header = HEADER.format(L=fmt(L), W=fmt(W), H=fmt(H), WB=fmt(WB),
                           KF=fmt(TRACK_F), KR=fmt(TRACK_R),
                           tire_f=fmt(TIRE_F), tire_r=fmt(TIRE_R),
                           clearance=fmt(CLEARANCE),
                           mode=MODE_NOTE if PARAMS else "")

    script = header + (PARAM_BLOCK if PARAMS else "") + f"""
# ------------------------------------------------------------------ 1. кузов
# Двадцать четыре сечения сняты с трёх видов чертежа: верх — с вида сбоку,
# полуширина — с вида сверху. Лофт соединяет их и сглаживает по длине.
{sections_block}
# `кузов` — алиас команды loft, поэтому сама основа называется иначе:
# в языке имя объекта не должно совпадать с названием команды.
кузов_база = loft sections=сечения {positions_line} smooth=4 profile_smooth=2

# ------------------------------------------------------------- 2. остекление
# Приём со сборочного чертежа: сначала проём, потом стекло в проём.
# Объёмный «клин» из кузова — это стекло по обводу; проём вырезается таким же
# клином, но на 4 мм шире, поэтому по краю видна кромка (шов).
# Наклоны подобраны под обвод: лобовое ~40°, заднее ~25°, борт ~20°.
лоб_плита = box size=[1000,1400,240]
лоб_плита = rotate [лоб_плита] angle=-40 axis=y
лоб_плита = place [лоб_плита] at=[{cx(X0 + 1830)},0,{cz(1055)}] align=center
лоб_паз = box size=[1008,1404,244]
лоб_паз = rotate [лоб_паз] angle=-40 axis=y
лоб_паз = place [лоб_паз] at=[{cx(X0 + 1830)},0,{cz(1055)}] align=center

зад_плита = box size=[620,1330,200]
зад_плита = rotate [зад_плита] angle=25 axis=y
зад_плита = place [зад_плита] at=[{cx(X0 + 2760)},0,{cz(1165)}] align=center
зад_паз = box size=[628,1334,204]
зад_паз = rotate [зад_паз] angle=25 axis=y
зад_паз = place [зад_паз] at=[{cx(X0 + 2760)},0,{cz(1165)}] align=center

# Борт сужается к крыше (tumblehome): панель стекла наклонена на 20° и стоит
# вплотную к борту; проём шире стекла на 4 мм.
бок_плита_п = box size=[760,120,250]
бок_плита_п = rotate [бок_плита_п] angle=-20 axis=x
бок_плита_п = place [бок_плита_п] at=[{cx(X0 + 2180)},{cyw(-797)},{cz(1040)}] align=center
бок_паз_п = box size=[764,124,254]
бок_паз_п = rotate [бок_паз_п] angle=-20 axis=x
бок_паз_п = place [бок_паз_п] at=[{cx(X0 + 2180)},{cyw(-797)},{cz(1040)}] align=center
бок_плита_з = box size=[760,120,250]
бок_плита_з = rotate [бок_плита_з] angle=20 axis=x
бок_плита_з = place [бок_плита_з] at=[{cx(X0 + 2180)},{cyw(797)},{cz(1040)}] align=center
бок_паз_з = box size=[764,124,254]
бок_паз_з = rotate [бок_паз_з] angle=20 axis=x
бок_паз_з = place [бок_паз_з] at=[{cx(X0 + 2180)},{cyw(797)},{cz(1040)}] align=center

лобовое = intersect [кузов_база, лоб_плита]
заднее = intersect [кузов_база, зад_плита]
стекло_п = intersect [кузов_база, бок_плита_п]
стекло_з = intersect [кузов_база, бок_плита_з]
color лобовое #0f1620 metal=0.7 rough=0.06
color заднее #0f1620 metal=0.7 rough=0.06
color стекло_п #0f1620 metal=0.7 rough=0.06
color стекло_з #0f1620 metal=0.7 rough=0.06

# Проёмы: те же плиты, но на 4 мм шире — стекло утоплено в кузов, по краю
# остаётся кромка, как на разрезе кузова в чертеже.
кузов = difference [кузов_база, лоб_паз, зад_паз, бок_паз_п, бок_паз_з]
hide кузов_база

# --------------------------------------------------------- 3. колёсные арки
# Арка — цилиндр поперёк машины: он срезает только борт, не проходя кузов
# насквозь. Радиус = радиус шины + зазор.
арка_пп = cylinder radius={TIRE_F / 2 + 45:.0f} height=280 segments=72
арка_пп = rotate [арка_пп] angle=90 axis=x
арка_пп = place [арка_пп] at=[{cwb(AXLE_F)},{cykf(-(TRACK_F / 2 + 40))},{cz(TIRE_F / 2)}] align=center
кузов = difference [кузов, арка_пп]
арка_пз = cylinder radius={TIRE_F / 2 + 45:.0f} height=280 segments=72
арка_пз = rotate [арка_пз] angle=90 axis=x
арка_пз = place [арка_пз] at=[{cwb(AXLE_F)},{cykf(TRACK_F / 2 + 40)},{cz(TIRE_F / 2)}] align=center
кузов = difference [кузов, арка_пз]
арка_зп = cylinder radius={TIRE_R / 2 + 45:.0f} height=300 segments=72
арка_зп = rotate [арка_зп] angle=90 axis=x
арка_зп = place [арка_зп] at=[{cwb(AXLE_R)},{cykr(-(TRACK_R / 2 + 40))},{cz(TIRE_R / 2)}] align=center
кузов = difference [кузов, арка_зп]
арка_зз = cylinder radius={TIRE_R / 2 + 45:.0f} height=300 segments=72
арка_зз = rotate [арка_зз] angle=90 axis=x
арка_зз = place [арка_зз] at=[{cwb(AXLE_R)},{cykr(TRACK_R / 2 + 40)},{cz(TIRE_R / 2)}] align=center
кузов = difference [кузов, арка_зз]

# ------------------------------------------------ 4. «китовый хвост» и решётка
# Спойлер 930-го: плоская полка на моторном отсеке с двумя приподнятыми
# бортиками. Ставится по месту командой place, зазор отсчитывается от кузова.
полка = box size=[560,1210,34] round=14
полка = place [полка] at=[{cx(X0 + 3480)},0,{cz(1060)}] align=center
бортик_п = box size=[560,32,80] round=10
бортик_п = place [бортик_п] at=[{cx(X0 + 3480)},{cyw(-590)},{cz(1100)}] align=center
бортик_з = box size=[560,32,80] round=10
бортик_з = place [бортик_з] at=[{cx(X0 + 3480)},{cyw(590)},{cz(1100)}] align=center
стойка_п = cylinder radius=22 height=110 segments=24
стойка_п = place [стойка_п] at=[{cx(X0 + 3480)},{cyw(-600)},{cz(1000)}] align=center
стойка_з = cylinder radius=22 height=110 segments=24
стойка_з = place [стойка_з] at=[{cx(X0 + 3480)},{cyw(600)},{cz(1000)}] align=center
хвост = union [полка, бортик_п, бортик_з, стойка_п, стойка_з]
color хвост #14171c material=rubber

# Решётка моторного отсека: пятнадцать ламелей в ряд — та же геометрия, что
# в разрезе «Г—Г» на чертеже.
ламель = box size=[300,20,10] round=4
решётка = array [ламель] count=15 mode=linear offset=[0,88,0]
решётка = place [решётка] at=[{cx(X0 + 3630)},0,{cz(1012)}] align=center
color решётка #101317 metal=0.6 rough=0.35

# ------------------------------------------------------- 5. бамперы и оптика
бампер_п = cylinder radius=105 height=1470 segments=48
бампер_п = rotate [бампер_п] angle=90 axis=x
бампер_п = place [бампер_п] at=[{cx(X0 + 170)},0,{cz(345)}] align=center
бампер_з = cylinder radius=100 height=1520 segments=48
бампер_з = rotate [бампер_з] angle=90 axis=x
бампер_з = place [бампер_з] at=[{cx(X1 - 150)},0,{cz(380)}] align=center
color бампер_п #16181c material=rubber
color бампер_з #16181c material=rubber

# Фары 911-го стоят на крыльях и чуть выступают над капотом.
фара_п = sphere radius=118 segments=40
фара_п = scale [фара_п] factor=[0.62,1.0,1.0]
фара_п = place [фара_п] at=[{cx(X0 + 690)},{cyw(-560)},{cz(742)}] align=center
фара_з = sphere radius=118 segments=40
фара_з = scale [фара_з] factor=[0.62,1.0,1.0]
фара_з = place [фара_з] at=[{cx(X0 + 690)},{cyw(560)},{cz(742)}] align=center
color фара_п #f7f3e6 metal=0.4 rough=0.05
color фара_з #f7f3e6 metal=0.4 rough=0.05

фонарь = box size=[44,1290,120] round=18
фонарь = place [фонарь] at=[{cx(X1 - 22)},0,{cz(742)}] align=center
color фонарь #8c1210 metal=0.3 rough=0.25

# Надпись на задней панели: плоскость yz ставит буквы лицом в +X.
надпись = text text="PORSCHE" size=58 depth=6 weight=6 plane=yz at=[{cx(X1 - 6)},0,{cz(626)}]
color надпись #d8dde5 metal=0.8 rough=0.2

# Зеркала и дверные ручки — по одному на борт, второй борт зеркалом.
ножка_зеркала = cylinder radius=16 height=90 segments=20
ножка_зеркала = rotate [ножка_зеркала] angle=90 axis=y
ножка_зеркала = place [ножка_зеркала] at=[{cx(X0 + 1590)},{cyw(-800)},{cz(948)}] align=center
зеркало = box size=[120,96,84] round=26
зеркало = place [зеркало] at=[{cx(X0 + 1590)},{cyw(-832)},{cz(1000)}] align=center
зеркала = union [ножка_зеркала, зеркало]
зеркала = mirror [зеркала] plane=y keep=да
ручка = box size=[170,18,34] round=8
ручка = place [ручка] at=[{cx(X0 + 2450)},{cyw(-815)},{cz(830)}] align=center
ручки = mirror [ручка] plane=y keep=да
color зеркала #b8332f metal=0.45 rough=0.2
color ручки #d8dde5 metal=0.85 rough=0.16

# --------------------------------------------------------------- 6. колёса
# Ширина шины и вылет подобраны так, чтобы наружная плоскость колеса не
# выходила за габарит {fmt(W)} мм: {fmt(TRACK_F / 2 + 112.5)} и {fmt(TRACK_R / 2 + 122.5)} < {fmt(W / 2)}.
колесо_пп = wheel diameter={fmt(TIRE_F)} width=225 rim=30 spokes=5 hub=96 tire=46 segments=64 at=[{cwb(AXLE_F)},{cykf(-TRACK_F / 2)},0]
колесо_пз = wheel diameter={fmt(TIRE_F)} width=225 rim=30 spokes=5 hub=96 tire=46 segments=64 at=[{cwb(AXLE_F)},{cykf(TRACK_F / 2)},0]
колесо_зп = wheel diameter={fmt(TIRE_R)} width=245 rim=32 spokes=5 hub=100 tire=48 segments=64 at=[{cwb(AXLE_R)},{cykr(-TRACK_R / 2)},0]
колесо_зз = wheel diameter={fmt(TIRE_R)} width=245 rim=32 spokes=5 hub=100 tire=48 segments=64 at=[{cwb(AXLE_R)},{cykr(TRACK_R / 2)},0]
color колесо_пп #191b1f material=rubber
color колесо_пз #191b1f material=rubber
color колесо_зп #191b1f material=rubber
color колесо_зз #191b1f material=rubber
color кузов #d8b400 metal=0.5 rough=0.22
"""

    if PARAMS:
        script += """
# --------------------------------------- 7. точные пересечения (правило 0.66)
# `collision` считает объём пересечения `a ^ b`, а не габаритные коробки.
# Здесь проверяется зазор «колесо ↔ кузов»: арка вырезана радиусом шины +45 мм,
# и если ползунок сузит колею или увеличит шину, проверка упадёт первой.
check колесо_пп collision
check колесо_пз collision
check колесо_зп collision
check колесо_зз collision
"""

    verify = f"""
# ----------------------------------------------------------------- 8. проверки
# Числа проверок — прямо с чертежа: база, колея, габарит.
check колесо_пп center {cwb(AXLE_F)}..{cwb(AXLE_F)} {cykf(-TRACK_F / 2)}..{cykf(-TRACK_F / 2)} {fmt(TIRE_F / 2)}..{fmt(TIRE_F / 2)}
check колесо_пз center {cwb(AXLE_F)}..{cwb(AXLE_F)} {cykf(TRACK_F / 2)}..{cykf(TRACK_F / 2)} {fmt(TIRE_F / 2)}..{fmt(TIRE_F / 2)}
check колесо_зп center {cwb(AXLE_R)}..{cwb(AXLE_R)} {cykr(-TRACK_R / 2)}..{cykr(-TRACK_R / 2)} {fmt(TIRE_R / 2)}..{fmt(TIRE_R / 2)}
check колесо_зз center {cwb(AXLE_R)}..{cwb(AXLE_R)} {cykr(TRACK_R / 2)}..{cykr(TRACK_R / 2)} {fmt(TIRE_R / 2)}..{fmt(TIRE_R / 2)}
check кузов width {cx(L - 1)}..{cx(L + 1)}
# Высота кузова считается от его нижней точки: 1310 − 150 (просвет) = 1160.
# Полная высота 1310 получается вместе с колёсами — они и держат пол на Z=0.
check кузов height {body_height(-1)}..{body_height(3)}
check колесо_пп watertight
check колесо_зп parts 1
check надпись inside кузов
# Пересечения здесь — не ошибка, а конструкция: бамперы, фары и фонари
# посажены в кузов, стёкла утоплены в проёмы, спойлер стоит на кузове.
# Поэтому пары перечислены явно: отчёт `interference` покажет всё остальное.
interference tolerance=1 allow="хвост:решётка,решётка:хвост,кузов:бампер_*,бампер_*:кузов,кузов:фонарь,фонарь:кузов,фонарь:надпись,надпись:фонарь,кузов:фара_*,фара_*:кузов,кузов:лобовое,лобовое:кузов,кузов:заднее,заднее:кузов,кузов:стекло_*,стекло_*:кузов,кузов:решётка,решётка:кузов,кузов:надпись,надпись:кузов,кузов:хвост,хвост:кузов,кузов:зеркала,зеркала:кузов,кузов:ручки,ручки:кузов,кузов:колесо_*,колесо_*:кузов"
passport кузов
"""
    return script + verify


def main() -> None:
    name = "porsche_930_params.forma" if PARAMS else "porsche_930.forma"
    target = Path(__file__).resolve().parents[1] / "examples" / name
    script = build_script()
    target.write_text(script, encoding="utf-8")
    print(f"{target}: {len(script.splitlines())} строк, {len(script.encode())} байт")


if __name__ == "__main__":
    main()
