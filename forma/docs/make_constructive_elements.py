"""Каталог конструктивных элементов: сцена + лист.

Сцена `examples/constructive_elements_01.forma` собирается из САМЫХ ПРОСТЫХ
примитивов (цилиндр, коробка, конус, призма, тор) и булевых операций —
каждый термин показан отдельной деталью на своей клетке поля.

Запуск:  PYTHONPATH=. python docs/make_constructive_elements.py
Результат: examples/constructive_elements_01.forma, docs/elements/*.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forma.render import _prepare, _render_view, _to_bytes, write_png  # noqa: E402
from forma.run import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "elements"
SCENE = ROOT / "examples" / "constructive_elements_01.forma"

PX, PY = 220.0, 210.0          # шаг клеток
COLS, ROWS = 6, 6


# ---------------------------------------------------------------------------
# 30 элементов: (код, термин, определение, строки DSL с {x} {y} {z})
# ---------------------------------------------------------------------------
ELEMENTS = [
    # ---------------------------------------------------------- тела вращения
    ("э01", "ФАСКА",
     "Срезанная под углом кромка. Снимает заусенец, даёт заход резцу и ключу.",
     ["э01 = cylinder radius=32 height=46 at=[{x},{y},0]",
      "э01 = chamfer [э01] width=7 edges=convex"]),
    ("э02", "ГАЛТЕЛЬ",
     "Плавный переход по радиусу в месте ступени: снимает концентратор напряжений.",
     ["г2а = cylinder radius=40 height=18 at=[{x},{y},0]",
      "г2б = cylinder radius=22 height=42 at=[{x},{y},18]",
      "э02 = union [г2а, г2б]",
      "э02 = fillet [э02] radius=11 edges=concave segments=18"]),
    ("э03", "БУРТИК",
     "Кольцевое утолщение вала: упор для подшипника, фиксация от осевого сдвига.",
     ["г3а = cylinder radius=18 height=84 at=[{x},{y},0]",
      "г3б = cylinder radius=36 height=16 at=[{x},{y},34]",
      "э03 = union [г3а, г3б]",
      "э03 = chamfer [э03] width=2.2 edges=convex"]),
    ("э04", "ЗАПЛЕЧИК",
     "Ступень вала: её торец служит упором для насаженной детали.",
     ["г4а = cylinder radius=36 height=28 at=[{x},{y},0]",
      "г4б = cylinder radius=19 height=46 at=[{x},{y},28]",
      "э04 = union [г4а, г4б]"]),
    ("э05", "ПРОТОЧКА",
     "Кольцевая канавка на валу: выход резьбонарезного и шлифовального круга.",
     ["г5а = cylinder radius=30 height=78 at=[{x},{y},0]",
      "г5б = cylinder radius=33 height=10 at=[{x},{y},49]",
      "г5в = cylinder radius=21 height=10 at=[{x},{y},49]",
      "г5кан = difference [г5б, г5в]",
      "э05 = difference [г5а, г5кан]"]),
    ("э06", "ВЫТОЧКА",
     "Канавка внутри отверстия: выход внутреннего резца, снятие фаски в глубине.",
     ["г6а = cylinder radius=38 height=66 at=[{x},{y},0]",
      "г6б = cylinder radius=24 height=66 at=[{x},{y},0]",
      "г6тр = difference [г6а, г6б]",
      "г6в = cylinder radius=31 height=11 at=[{x},{y},37]",
      "г6г = cylinder radius=24 height=9 at=[{x},{y},38]",
      "г6выт = difference [г6в, г6г]",
      "э06 = difference [г6тр, г6выт]"]),
    # ------------------------------------------------------- концы и сечения
    ("э07", "ЛЫСКА",
     "Плоский срез на цилиндре под ключ. Линия пересечения — линия среза.",
     ["г7а = cylinder radius=34 height=68 at=[{x},{y},0]",
      "г7рез = box size=[96,40,74] center=true at=[{x},{y},34]",
      "г7рез = translate [г7рез] offset=[0,-44,0]",
      "э07 = difference [г7а, г7рез]"]),
    ("э08", "ШПОНОЧНЫЙ ПАЗ",
     "Паз под шпонку передаёт момент. Дно — по фрезе, конец — полукруглый.",
     ["г8а = cylinder radius=34 height=72 at=[{x},{y},0]",
      "г8б = box size=[20,24,52] center=true at=[{x},{y},30]",
      "г8б = translate [г8б] offset=[0,-38,0]",
      "г8в = cylinder radius=10 height=26",
      "г8в = rotate [г8в] angle=90 axis=x",
      "г8в = translate [г8в] offset=[{x},{y},56]",
      "г8в = translate [г8в] offset=[0,-38,0]",
      "г8рез = union [г8б, г8в]",
      "э08 = difference [г8а, г8рез]"]),
    ("э09", "ШЛИЦ (ПРОРЕЗЬ)",
     "Узкий паз на головке под отвёртку; его глубина около трети головки.",
     ["г9а = cylinder radius=32 height=20 at=[{x},{y},0]",
      "г9б = cylinder radius=14 height=34 at=[{x},{y},0]",
      "г9тело = union [г9а, г9б]",
      "г9рез = box size=[70,8,10] center=true at=[{x},{y},20]",
      "э09 = difference [г9тело, г9рез]"]),
    ("э10", "ШЛИЦЫ",
     "Продольные зубья на валу или в ступице: момент передаётся по всему контуру.",
     ["г10а = cylinder radius=28 height=80 at=[{x},{y},0]",
      "{teeth}",
      "э10 = union [г10а, {tooth_names}]"]),
    ("э11", "КВАДРАТ",
     "Четырёхгранный конец вала под ключ: четыре среза на цилиндре.",
     ["г11а = cylinder radius=34 height=26 at=[{x},{y},0]",
      "г11б = cylinder radius=26 height=38 at=[{x},{y},26]",
      "г11к = box size=[37.8,37.8,40] center=true at=[{x},{y},45]",
      "г11кв = intersect [г11б, г11к]",
      "э11 = union [г11а, г11кв]"]),
    ("э12", "ЦЕНТРОВОЕ ОТВ.",
     "База для центровки при токарной обработке: конус 60° и цилиндр.",
     ["г12а = cylinder radius=34 height=44 at=[{x},{y},0]",
      "г12б = cone radius=14 height=12",
      "г12б = rotate [г12б] angle=180 axis=x",
      "г12б = translate [г12б] offset=[{x},{y},44]",
      "г12в = cylinder radius=5 height=26 at=[{x},{y},8]",
      "г12рез = union [г12б, г12в]",
      "э12 = difference [г12а, г12рез]"]),
    # ---------------------------------------------------------------- дырки
    ("э13", "СКВОЗНОЕ ОТВ.",
     "Отверстие проходит деталь насквозь; кромки притуплены фаской.",
     ["г13а = box size=[76,76,30] center=true at=[{x},{y},15] round=4",
      "г13б = cylinder radius=15 height=44 at=[{x},{y},-7]",
      "э13 = difference [г13а, г13б]",
      "э13 = chamfer [э13] width=2 edges=convex"]),
    ("э14", "ГНЕЗДО (ГЛУХОЕ)",
     "Отверстие на заданную глубину; дно — по форме сверла, 118°.",
     ["г14а = box size=[76,76,30] center=true at=[{x},{y},15] round=4",
      "г14б = cylinder radius=17 height=20 at=[{x},{y},12]",
      "г14в = cone radius=10 height=9",
      "г14в = rotate [г14в] angle=180 axis=x",
      "г14в = translate [г14в] offset=[{x},{y},12]",
      "г14рез = union [г14б, г14в]",
      "э14 = difference [г14а, г14рез]"]),
    ("э15", "РЕЗЬБОВОЕ ГНЕЗДО",
     "Глухое отверстие с внутренней резьбой под винт; вход — с фаской.",
     ["г15а = box size=[76,76,34] center=true at=[{x},{y},17] round=4",
      "г15р = cylinder radius=9.05 height=24",
      "г15т = thread diameter=18 length=24 pitch=2.5 depth=1.2 internal=true",
      "г15рез = difference [г15р, г15т]",
      "г15рез = translate [г15рез] offset=[{x},{y},8]",
      "г15ф = cylinder radius=10 height=4 at=[{x},{y},30]",
      "э15 = difference [г15а, г15рез, г15ф]"]),
    ("э16", "ОКНО",
     "Прямоугольное отверстие в стенке: литое или фрезерованное насквозь.",
     ["г16а = box size=[96,16,74] center=true at=[{x},{y},37]",
      "г16б = box size=[38,26,32] center=true at=[{x},{y},40] round=3",
      "э16 = difference [г16а, г16б]"]),
    ("э17", "ФАСКА НА ГАЙКЕ",
     "Снятые кромки шестигранника: заход ключа и отсутствие заусенцев.",
     ["г17а = prism sides=6 radius=27 height=20 at=[{x},{y},0]",
      "г17б = cylinder radius=9 height=28 at=[{x},{y},-2]",
      "г17о = cylinder radius=40 height=5 at=[{x},{y},16]",
      "г17к = cone radius=27 height=15.6 at=[{x},{y},16]",
      "г17рез = difference [г17о, г17к]",
      "э17 = difference [г17а, г17б, г17рез]"]),
    ("э18", "НАКАТКА",
     "Мелкое рифление на поверхности: надёжный хват рукой и отделка.",
     ["г18а = cylinder radius=32 height=58 at=[{x},{y},0]",
      "э18 = knurl [г18а] count=32 depth=1.6 width=1.1"]),
    # ------------------------------------------------------ литые и крепёж
    ("э19", "БОБЫШКА",
     "Низкий цилиндрический прилив под крепёж: опорная площадка под болт.",
     ["г19а = box size=[84,84,14] center=true at=[{x},{y},7] round=3",
      "г19б = cylinder radius=24 height=24 at=[{x},{y},0]",
      "г19т = union [г19а, г19б]",
      "г19в = cylinder radius=8.5 height=30 at=[{x},{y},4]",
      "э19 = difference [г19т, г19в]"]),
    ("э20", "ПРИЛИВ",
     "Местное утолщение отливки: подвод металла и усиление под нагрузку.",
     ["г20а = box size=[84,84,14] center=true at=[{x},{y},7] round=3",
      "г20б = cylinder radius=24 height=80",
      "г20б = rotate [г20б] angle=90 axis=x",
      "г20б = translate [г20б] offset=[{x},{y},14]",
      "г20т = union [г20а, г20б]",
      "э20 = fillet [г20т] radius=4 edges=concave segments=10"]),
    ("э21", "РЕБРО ЖЁСТКОСТИ",
     "Треугольная стенка: поднимает жёсткость при минимальной массе.",
     ["г21а = box size=[92,60,10] center=true at=[{x},{y},5]",
      "г21к = contour2d start=[0,0] segments=[[\"line\",[54,0]],[\"line\",[0,54]],"
      "[\"line\",[0,0]]] closed=да",
      "г21б = extrude profile=г21к height=14",
      "г21б = rotate [г21б] angle=90 axis=x",
      "г21б = rotate [г21б] angle=90 axis=z",
      "г21б = translate [г21б] offset=[-7,-27,10]",
      "г21б = translate [г21б] offset=[{x},{y},0]",
      "э21 = union [г21а, г21б]"]),
    ("э22", "ЛАПКА",
     "Выступающая опора с отверстием под болт — крепление к основанию.",
     ["г22а = box size=[30,80,22] center=true at=[{x},{y},11] round=2",
      "г22б = cylinder radius=30 height=26 at=[{x},{y},0]",
      "г22т = union [г22б, г22а]",
      "г22в = cylinder radius=7.5 height=40 at=[{x},{y},0]",
      "г22в = translate [г22в] offset=[0,30,0]",
      "э22 = difference [г22т, г22в]"]),
    ("э23", "УШКО",
     "Прилив с отверстием под палец или ось — шарнирное соединение.",
     ["г23б = box size=[26,18,34] center=true at=[{x},{y},18]",
      "г23а = cylinder radius=22 height=18",
      "г23а = rotate [г23а] angle=90 axis=x",
      "г23а = translate [г23а] offset=[{x},{y},34]",
      "г23т = union [г23б, г23а]",
      "г23в = cylinder radius=9 height=30",
      "г23в = rotate [г23в] angle=90 axis=x",
      "г23в = translate [г23в] offset=[{x},{y},34]",
      "э23 = difference [г23т, г23в]"]),
    ("э24", "ФЛАНЕЦ",
     "Диск с отверстиями под болты: центрирует и уплотняет стык.",
     ["г24а = cylinder radius=46 height=12 at=[{x},{y},0]",
      "г24б = cylinder radius=22 height=22 at=[{x},{y},0]",
      "г24т = union [г24а, г24б]",
      "г24в = cylinder radius=13 height=40 at=[{x},{y},-4]",
      "{holes}",
      "э24 = difference [г24т, г24в, {hole_names}]"]),
    # ---------------------------------------------------- колесо и механика
    ("э25", "ОБОД",
     "Наружное кольцо колеса или шкива: по нему катится или бежит ремень.",
     ["г25а = cylinder radius=48 height=18 at=[{x},{y},0]",
      "г25б = cylinder radius=35 height=18 at=[{x},{y},0]",
      "э25 = difference [г25а, г25б]",
      "э25 = chamfer [э25] width=2 edges=convex"]),
    ("э26", "СПИЦА",
     "Стержень от ступицы к ободу; работает на растяжение и сжатие.",
     ["г26а = cylinder radius=7 height=100",
      "г26а = rotate [г26а] angle=90 axis=y",
      "г26а = translate [г26а] offset=[{x},{y},34]",
      "г26б = cylinder radius=12 height=12",
      "г26б = rotate [г26б] angle=90 axis=y",
      "г26б = translate [г26б] offset=[{x},{y},34]",
      "г26б = translate [г26б] offset=[-44,0,0]",
      "г26в = cylinder radius=12 height=12",
      "г26в = rotate [г26в] angle=90 axis=y",
      "г26в = translate [г26в] offset=[{x},{y},34]",
      "г26в = translate [г26в] offset=[44,0,0]",
      "э26 = union [г26а, г26б, г26в]"]),
    ("э27", "СТУПИЦА",
     "Центральная часть колеса: садится на вал и несёт спицы.",
     ["г27а = cylinder radius=26 height=36 at=[{x},{y},0]",
      "г27б = cylinder radius=31 height=10 at=[{x},{y},26]",
      "г27т = union [г27а, г27б]",
      "г27в = cylinder radius=12 height=50 at=[{x},{y},-4]",
      "э27 = difference [г27т, г27в]"]),
    ("э28", "ВТУЛКА",
     "Гильза с осевым отверстием: подшипник скольжения, проставка, распорка.",
     ["г28а = cylinder radius=30 height=54 at=[{x},{y},0]",
      "г28б = cylinder radius=20 height=54 at=[{x},{y},0]",
      "э28 = difference [г28а, г28б]",
      "э28 = chamfer [э28] width=2 edges=convex"]),
    ("э29", "РЕЗЬБА",
     "Винтовая канавка на стержне: шаг, профиль витка и направление захода.",
     ["э29 = thread diameter=36 length=64 pitch=3.5 depth=1.6"]),
    ("э30", "ШИП",
     "Небольшой выступ-цапфа, входящий в гнездо ответной детали.",
     ["г30а = box size=[64,64,16] center=true at=[{x},{y},8] round=3",
      "г30б = cylinder radius=13 height=40 at=[{x},{y},0]",
      "г30в = cone radius=9 height=12 at=[{x},{y},40]",
      "г30т = union [г30а, г30б, г30в]",
      "э30 = chamfer [г30т] width=1.5 edges=convex"]),
    ("э31", "ТОРЕЦ",
     "Торцевая плоскость, перпендикулярная оси: база установки и отсчёта размеров.",
     ["г31а = box size=[58,58,84] center=true at=[{x},{y},42]",
      "э31 = chamfer [г31а] width=3 edges=convex"]),
    ("э32", "ГРАНЬ · РЕБРО · ВЕРШИНА",
     "Плоская грань, линия пересечения двух граней и точка стыка трёх рёбер.",
     ["э32 = prism sides=6 radius=30 height=64 at=[{x},{y},0]",
      "э32 = chamfer [э32] width=1.2 edges=convex"]),
    ("э33", "КРИВАЯ ПОВЕРХНОСТЬ",
     "Поверхность вращения или литейная поверхность — не плоскость, задаётся профилем.",
     ["э33 = sphere radius=34 at=[{x},{y},0]",
      "э33 = fillet [э33] radius=1 edges=concave segments=8"]),
    ("э34", "ПОДШИПНИК",
     "Наружное и внутреннее кольца и тела качения между ними: момент не передаёт, держит вал.",
     ["г34а = cylinder radius=45 height=20 at=[{x},{y},0]",
      "г34б = cylinder radius=35 height=20 at=[{x},{y},0]",
      "г34н = difference [г34а, г34б]",
      "г34в = cylinder radius=25 height=20 at=[{x},{y},0]",
      "г34г = cylinder radius=15 height=20 at=[{x},{y},0]",
      "г34вн = difference [г34в, г34г]",
      "{balls}",
      "э34 = union [г34н, г34вн, {ball_names}]"]),
    ("э35", "СТОЙКА",
     "Вертикальная опора: держит ось или корпус на заданной высоте.",
     ["г35а = box size=[78,56,14] center=true at=[{x},{y},7] round=2",
      "г35б = box size=[26,50,86] center=true at=[{x},{y},50] round=2",
      "г35в = box size=[44,50,12] center=true at=[{x},{y},92] round=2",
      "э35 = union [г35а, г35б, г35в]"]),
    ("э36", "ОСНОВАНИЕ",
     "Опорная плита с крепёжными отверстиями и приливом под стойку или корпус.",
     ["г36а = box size=[112,92,16] center=true at=[{x},{y},8] round=3",
      "г36б = cylinder radius=26 height=14 at=[{x},{y},0]",
      "г36т = union [г36а, г36б]",
      "{bolts}",
      "э36 = difference [г36т, {bolt_names}]"]),
]


# на сцене подпись должна влезать в клетку — длинные термины сокращаются,
# полное название остаётся на листе
SHORT = {"э32": "ГРАНЬ · РЕБРО", "э33": "КРИВАЯ ПОВЕРХН."}


def cell_xy(row: int, col: int) -> tuple[float, float]:
    """Центр клетки: строки идут от задней к передней (−Y), столбцы слева направо."""
    return (col - (COLS - 1) / 2.0) * PX, -row * PY


def build_scene() -> str:
    lines = [
        "# Конструктивные элементы деталей машин — каталог из 30 терминов.",
        "# Каждый элемент собран из простейших примитивов (cylinder, box, cone,",
        "# prism, sphere, tri_prism, thread) и булевых операций union/difference/",
        "# intersect; где термин требует скругления или фаски — chamfer/fillet.",
        "# Подписи — объёмные надписи (text) перед каждой клеткой: +X вправо,",
        "# −Y на зрителя, +Z вверх. Шаг клетки 220 × 210 мм.",
        "",
        "precision mode=fine tolerance=0.15",
        "scene bg=#eef0f2 shadows=да ground=да",
        "light preset=студия strength=1.05",
        "",
    ]
    for i, (code, term, _def, tpl) in enumerate(ELEMENTS):
        row, col = divmod(i, COLS)
        x, y = cell_xy(row, col)
        lines.append(f"# ---------------------------------------------------------------- {term} --")
        holes, hole_names = [], []
        for k in range(6):
            ang = math.radians(k * 60)
            nm = f"г{code[1:]}отв{k}"
            hole_names.append(nm)
            holes.append(f"{nm} = cylinder radius=6 height=20")
            holes.append(f"{nm} = translate [{nm}] offset="
                         f"[{x + 34 * math.cos(ang):.1f},{y + 34 * math.sin(ang):.1f},4]")
        balls, ball_names = [], []
        for k in range(8):
            ang = math.radians(k * 45)
            nm = f"г{code[1:]}ш{k}"
            ball_names.append(nm)
            balls.append(f"{nm} = sphere radius=9")
            balls.append(f"{nm} = translate [{nm}] offset="
                         f"[{x + 30 * math.cos(ang):.1f},{y + 30 * math.sin(ang):.1f},10]")
        bolts, bolt_names = [], []
        for k, (bx, by) in enumerate([(-42, -32), (42, -32), (-42, 32), (42, 32)]):
            nm = f"г{code[1:]}б{k}"
            bolt_names.append(nm)
            bolts.append(f"{nm} = cylinder radius=6 height=26")
            bolts.append(f"{nm} = translate [{nm}] offset=[{x + bx:.1f},{y + by:.1f},-5]")
        teeth, names = [], []
        for k in range(8):
            nm = f"г{code[1:]}зуб{k}"
            names.append(nm)
            teeth.append(f"{nm} = box size=[11,26,74] center=true")
            teeth.append(f"{nm} = translate [{nm}] offset=[0,30,40]")
            teeth.append(f"{nm} = rotate [{nm}] angle={k * 45} axis=z")
            teeth.append(f"{nm} = translate [{nm}] offset=[{x:.1f},{y:.1f},0]")
        for t in tpl:
            if t == "{teeth}":
                lines.extend(teeth)
                continue
            if t == "{holes}":
                lines.extend(holes)
                continue
            if t == "{balls}":
                lines.extend(balls)
                continue
            if t == "{bolts}":
                lines.extend(bolts)
                continue
            lines.append(t.format(x=f"{x:.1f}", y=f"{y:.1f}",
                                  tooth_names=", ".join(names),
                                  hole_names=", ".join(hole_names),
                                  ball_names=", ".join(ball_names),
                                  bolt_names=", ".join(bolt_names)))
        lines.append(f"color {code} #b9c6d2 material=metal rough=0.45")
        label = SHORT.get(code, term)
        lsize = max(10.0, min(15.0, 196.0 / (len(label) * 0.66)))
        lines.append(
            f'подпись_{code[1:]} = text "{label}" size={lsize:.1f} depth=1.4 align=center '
            f'at=[{x:.1f},{y - 84:.1f},0]')
        lines.append(f"color подпись_{code[1:]} #22303c material=plastic rough=0.6")
        lines.append("")
    return "\n".join(lines) + "\n"


LINE_STYLE = {
    "mode": "линия", "line": 1.5, "color": "#141a26", "paper": "#ffffff",
    "inner": True, "crease": 32, "depth": 0.035, "seams": True,
    "toon": 3, "tone": 0.0, "hatch": 0.0, "lines": "все",
}

FONTS = Path("/usr/share/fonts/truetype/dejavu")
F_TITLE = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 44)
F_SUB = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 20)
F_TERM = ImageFont.truetype(str(FONTS / "DejaVuSans-Bold.ttf"), 24)
F_DEF = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), 15)
F_REC = ImageFont.truetype(str(FONTS / "DejaVuSansMono.ttf"), 14)

INK = (24, 28, 36)
SOFT = (118, 124, 136)
PAPER = (255, 255, 255)


def recipe(tpl) -> str:
    """Короткая запись того, из чего собран элемент: примитивы и операции."""
    order = ["cylinder", "box", "cone", "sphere", "prism", "tri_prism", "thread",
             "knurl", "union", "difference", "intersect", "fillet", "chamfer",
             "rotate", "translate", "array"]
    used = set()
    for t in tpl:
        if t == "{teeth}":
            used.update({"box", "rotate"})
            continue
        if "=" not in t:
            continue
        body = t.split("=", 1)[1].strip()
        verb = body.split()[0] if body else ""
        used.add(verb)
    return " · ".join(v for v in order if v in used)


def wrap(dr, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if dr.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main() -> int:
    SCENE.write_text(build_scene(), encoding="utf-8")
    print("сцена:", SCENE, len(SCENE.read_text(encoding="utf-8")), "символов")
    r = build(SCENE.read_text(encoding="utf-8"))
    print("сборка:", r.ok, r.error if not r.ok else "")
    if not r.ok:
        return 1
    acts = {k: v for k, v in r.scene.objects.items() if v.visible}
    OUT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------- вся сцена одной изометрией
    meshes = _prepare(list(acts.values()), r.scene.groups)
    lo = np.array([1e18] * 3)
    hi = -lo.copy()
    for o in acts.values():
        bb = np.array(o.bbox, dtype=float)
        lo = np.minimum(lo, bb[:3])
        hi = np.maximum(hi, bb[3:])
    img, _ = _render_view(meshes, (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2,
                          "iso", 1100, 2, [*map(float, lo), *map(float, hi)],
                          grid=False, shadow=True, bg=None, style=LINE_STYLE)
    write_png(OUT / "elements_scene.png", _to_bytes(img))
    print("сцена отрендерена")

    # ------------------------------------------------------ лист-каталог 6 × 5
    tile = 320
    cell_w, cell_h = 452, 506
    pad_x, pad_y = 64, 148
    W = pad_x * 2 + cell_w * COLS
    H = pad_y + 104 + cell_h * ROWS + 70
    sheet = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(sheet)
    dr.text((pad_x, 40), "КОНСТРУКТИВНЫЕ ЭЛЕМЕНТЫ ДЕТАЛЕЙ МАШИН", font=F_TITLE, fill=INK)
    dr.text((pad_x, 98),
            "36 терминов · каждый собран из простейших примитивов и булевых операций · "
            "изометрия, масштаб условный",
            font=F_SUB, fill=SOFT)

    for i, (code, term, definition, tpl) in enumerate(ELEMENTS):
        row, col = divmod(i, COLS)
        cx = pad_x + col * cell_w
        cy = pad_y + 104 + row * cell_h
        part = acts.get(code)
        if part is None:
            dr.text((cx + 10, cy + 100), f"{code}: нет объекта", font=F_DEF, fill=(200, 0, 0))
            continue
        bb = np.array(part.bbox, dtype=float)
        lo_p, hi_p = bb[:3], bb[3:]
        center = (lo_p + hi_p) / 2
        rad = float(np.linalg.norm(hi_p - lo_p)) / 2 * 1.04
        m = _prepare([part], r.scene.groups)
        sub, _ = _render_view(m, center, max(rad, 12.0), "iso", tile, 2,
                              [*map(float, lo_p), *map(float, hi_p)],
                              grid=False, shadow=True, bg=None, style=LINE_STYLE)
        img_i = Image.fromarray(_to_bytes(sub))
        px, py = cx + (cell_w - tile) // 2, cy
        sheet.paste(img_i, (px, py))
        dr.rectangle([px, py, px + tile, py + tile], outline=(222, 226, 232), width=1)
        # подпись
        ty = py + tile + 16
        dr.text((cx + 8, ty), f"{i + 1:02d} · {term}", font=F_TERM, fill=INK)
        yy = ty + 36
        for ln in wrap(dr, definition, F_DEF, cell_w - 22)[:3]:
            dr.text((cx + 8, yy), ln, font=F_DEF, fill=(70, 76, 88))
            yy += 20
        dr.text((cx + 8, ty + 36 + 3 * 20 + 8), recipe(tpl), font=F_REC, fill=(148, 106, 58))

    dr.line([(pad_x, H - 46), (W - pad_x, H - 46)], fill=INK, width=2)
    dr.text((pad_x, H - 38),
            "Сцена: forma/examples/constructive_elements_01.forma · подписи на сцене — "
            "объёмные надписи text · сборка каталога: docs/make_constructive_elements.py",
            font=F_SUB, fill=SOFT)
    write_png(OUT / "elements_sheet.png", sheet)
    print("лист:", OUT / "elements_sheet.png", sheet.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
