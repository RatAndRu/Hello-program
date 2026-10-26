"""Механические готовые детали: лестница, рычаг, кнопка.

Это предметы, у которых важна не только форма, но и **устройство**: у
лестницы — форма боковых реек и перекладин, у рычага — палка и ручка, у
кнопки — подвижная шляпка и неподвижное гнездо. Кнопка специально делается
двумя объектами: так её шляпку можно анимировать отдельно от платформы, не
разрезая геометрию командами.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .model import Solid
from .ops import detail_factor, op
from .ops_shapes import _profile
from .shape_features import apply_smooth


def _segments(a, default: int, minv: int = 12, maxv: int = 256) -> int:
    asked = a.int("segments", None, minv=8, maxv=maxv)
    base = int(asked) if asked else int(default)
    return int(max(minv, min(maxv, round(base * detail_factor(a)))))


def _placed_all(a, parts: list[mf.Manifold]) -> list[mf.Manifold]:
    """Сдвигает всю сборку одним смещением: центр по XY, низ на z = at."""
    at = np.asarray(a.vec("at", 3, default=(0, 0, 0)), dtype=np.float64)
    bb = parts[0].bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    lo = min(p.bounding_box()[2] for p in parts)
    hi = max(p.bounding_box()[5] for p in parts)
    if a.boolean("center", False):
        tz = at[2] - (lo + hi) / 2.0
    else:
        tz = at[2] - lo
    shift = (at[0] - cx, at[1] - cy, tz)
    return [p.translate(shift) for p in parts]


def _extra(a, base_name: str, suffix: str, m: mf.Manifold, kind: str) -> Solid:
    """Добавляет в сцену вторую деталь с собственным именем.

    Имя собирается без точки (``кнопка_гнездо``), чтобы на него можно было
    сослаться в сценарии: имя с точкой DSL не примет.
    """
    solid = Solid(name=f"{base_name}_{suffix}", manifold=m,
                  color=a.scene.next_color(), metal=0.0, rough=0.5, kind=kind,
                  op=a.spec.name, line=a.cmd.line)
    return a.scene.add(solid)


def _cross_section_rail(length: float, size: float, shape: str,
                        segments: int) -> mf.Manifold:
    """Рейка вдоль X длиной ``length`` с сечением ``shape`` (капсула/брусок/овал)."""
    half = max(0.2, size / 2.0)
    if shape == "капсула":
        if length <= 2 * half + 0.2:
            raise GeometryError(
                f"Рейка-капсула короче своего диаметра: длина {length:g}, "
                f"толщина {size:g} мм.",
                hint="Увеличьте length или уменьшите rail_d.")
        body = mf.Manifold.cylinder(length - 2 * half, half, half, segments)
        body = body.rotate((0.0, 90.0, 0.0)).translate((half, 0.0, 0.0))
        caps = [mf.Manifold.sphere(half, segments).translate((x, 0.0, 0.0))
                for x in (half, length - half)]
        return mf.Manifold.batch_boolean([body, *caps], mf.OpType.Add)
    if shape == "овал":
        # Плоская stadium-рейка, не вытянутый эллипсоид: две плоские
        # боковые грани ±Y, прямые участки сверху/снизу и полукруглые торцы.
        if length <= size + 0.2:
            raise GeometryError("Овальная рейка короче своего диаметра.")
        pts = [(half, -half), (length - half, -half)]
        arc_steps = max(8, segments // 2)
        for i in range(1, arc_steps + 1):
            ang = -math.pi / 2.0 + math.pi * i / arc_steps
            pts.append((length - half + half * math.cos(ang), half * math.sin(ang)))
        pts.append((half, half))
        for i in range(1, arc_steps + 1):
            ang = math.pi / 2.0 + math.pi * i / arc_steps
            pts.append((half + half * math.cos(ang), half * math.sin(ang)))
        body = mf.Manifold.extrude(mf.CrossSection([_profile(pts)]), size)
        return body.rotate((90.0, 0.0, 0.0)).translate((0.0, half, 0.0))
    # брусок: небольшое скругление рёбер по размеру рейки
    return mf.Manifold.cube((length, size, size), center=True).translate(
        (length / 2.0, 0.0, 0.0))


def _rung(length: float, size: float, shape: str, segments: int) -> mf.Manifold:
    """Перекладина вдоль Y между рейками."""
    half = max(0.2, size / 2.0)
    if shape == "цилиндр":
        # цилиндр вдоль Z → поворот на 90° переводит его в Y, центр остаётся в нуле
        body = mf.Manifold.cylinder(length, half, half, segments)
        return body.rotate((90.0, 0.0, 0.0)).translate((0.0, length / 2.0, 0.0))
    return mf.Manifold.cube((size, length, size), center=True)


# --------------------------------------------------------------------------- #
#  Лестница
# --------------------------------------------------------------------------- #
@op("ladder", aliases=("лестница", "стремянка", "приставная_лестница",
                           "ladder_steps", "ladder"),
    category="Примитивы",
    summary="Лестница целиком: две боковые рейки и перекладины между ними. "
            "Форма реек — капсула, брусок или овал; форма перекладин — "
            "цилиндр или брусок. Число перекладин, длина, ширина и наклон "
            "задаются числами, поэтому одна строка даёт приставную лестницу, "
            "стремянку или декоративную перекладину.",
    example="приставная = ladder length=1800 width=420 rungs=9 tilt=72\n"
            "деревянная = ladder length=1500 width=380 rail=брусок rail_d=44 "
            "rung=брусок rung_d=34 rungs=7 tilt=75\n"
            "канатная = ladder length=1200 width=300 rail=овал rail_d=22 rung_d=16 rungs=6",
    params={"length": "длина реек, мм (1800)",
            "width": "расстояние между рейками, мм (420)",
            "rail": "форма рейки: капсула, брусок или овал — «капсула»",
            "rail_d": "толщина рейки, мм (38)",
            "rungs": "сколько перекладин (9)",
            "rung": "форма перекладины: цилиндр или брусок — «цилиндр»",
            "rung_d": "толщина перекладины, мм (30)",
            "tilt": "наклон к полу, градусы: 90 — стоит, 0 — лежит (75)",
            "margin": "отступ первой перекладины от края, мм (авто)",
            "segments": "сегментов у круглых частей (по детализации)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def ladder(a, name):
    length = float(a.num("length", 1800.0, minv=50.0))
    width = float(a.num("width", 420.0, minv=20.0))
    rail_shape = (a.text("rail", "капсула") or "капсула").strip().lower()
    rail_shape = {"капсула": "капсула", "труба": "капсула", "круглая": "капсула",
                  "брусок": "брусок", "квадрат": "брусок", "прямоугольная": "брусок",
                  "параллелепипед": "брусок", "овал": "овал", "овальная": "овал",
                  "эллипс": "овал"}.get(rail_shape)
    if rail_shape is None:
        raise GeometryError(
            f"Неизвестная форма рейки: «{a.text('rail')}».",
            hint="rail=капсула, брусок или овал.")
    rail_d = float(a.num("rail_d", 38.0, minv=2.0))
    rungs = int(a.int("rungs", 9, minv=1, maxv=80) or 9)
    rung_shape = (a.text("rung", "цилиндр") or "цилиндр").strip().lower()
    rung_shape = {"цилиндр": "цилиндр", "труба": "цилиндр", "круглая": "цилиндр",
                  "брусок": "брусок", "квадрат": "брусок", "прямоугольная": "брусок",
                  "параллелепипед": "брусок"}.get(rung_shape)
    if rung_shape is None:
        raise GeometryError(
            f"Неизвестная форма перекладины: «{a.text('rung')}».",
            hint="rung=цилиндр или брусок.")
    rung_d = float(a.num("rung_d", 30.0, minv=1.0))
    tilt = float(a.num("tilt", 75.0, minv=0.0, maxv=90.0))   # 0 — лежит, 90 — стоит
    segments = _segments(a, 32, minv=12)
    if rail_d * 2.0 >= width:
        raise GeometryError(
            f"Рейки толщиной {rail_d:g} мм не помещаются: между ними {width:g} мм.",
            hint=f"rail_d должен быть меньше {width / 2:g} мм.")
    margin = a.num("margin", None, minv=0.0)
    margin = float(min(length * 0.12, max(rail_d * 1.5, 60.0)) if margin is None
                   else margin)
    if rungs > 1 and margin * 2.0 + rung_d >= length:
        raise GeometryError("Перекладины не помещаются в такую короткую лестницу.")
    rails = []
    for side in (-1.0, 1.0):
        rail = _cross_section_rail(length, rail_d, rail_shape, segments)
        rails.append(rail.translate((0.0, side * width / 2.0, 0.0)))
    if rung_d > rail_d + 1e-6:
        raise GeometryError("Перекладина толще рейки: её нельзя чисто состыковать.",
                            hint="Уменьшите rung_d или увеличьте rail_d.")
    # Торец заходит в рейку лишь на 0.05 мм для гарантированно слитного
    # булева стыка; наружу он не проходит и сквозь рейку не торчит.
    rung_length = width - rail_d + 0.1
    span = length - 2.0 * margin
    positions = [margin] if rungs == 1 else [
        margin + span * i / (rungs - 1) for i in range(rungs)]
    parts = list(rails)
    for x in positions:
        rung = _rung(rung_length, rung_d, rung_shape, segments)
        parts.append(rung.translate((x, 0.0, 0.0)))
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    # наклон: 0 — лежит, 90 — стоит; вращаем вокруг нижнего конца
    if tilt > 1e-6:
        # поворот вокруг Y на -tilt: +X уходит вверх, при 90° лестница стоит
        solid = solid.rotate((0.0, -tilt, 0.0))
    placed = _placed_all(a, [solid])[0]
    out = _make(a, name, placed, "ladder")
    out.notes.append(f"лестница {length:g} мм, {rungs} перекладин, рейка "
                     f"{rail_shape} {rail_d:g} мм, перекладина {rung_shape} "
                     f"{rung_d:g} мм, наклон {tilt:g}°")
    return out


# --------------------------------------------------------------------------- #
#  Рычаг
# --------------------------------------------------------------------------- #
@op("lever", aliases=("рычаг", "ручка_рычаг", "рычажок", "lever_handle"),
    category="Примитивы",
    summary="Рычаг с палкой и наконечником на конце. knob=шар даёт "
            "продолговатый шар, knob=цилиндр — втулку; knob_h задаёт длину "
            "обоих наконечников. Палка состыкована с поверхностью и не "
            "торчит сквозь него.",
    example="рычаг = lever length=180 diameter=14 knob=шар knob_d=34 knob_h=60\n"
            "брусок = lever length=140 shaft=брусок size=20 knob=цилиндр knob_d=30 knob_h=70",
    params={"length": "общая длина с наконечником по X, мм (180)",
            "shaft": "палка: цилиндр или брусок — «цилиндр»",
            "diameter": "диаметр палки, мм (14)",
            "size": "сечение палки-бруска, мм (равно diameter)",
            "knob": "наконечник: шар или цилиндр — «шар»",
            "knob_d": "толщина наконечника, мм (34)",
            "knob_h": "длина наконечника вдоль X, мм; работает и для шара (60)",
            "angle": "наклон вверх, градусы −89…89 (0)",
            "segments": "сегментов у круглых частей (по детализации)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def lever(a, name):
    length = float(a.num("length", 180.0, minv=5.0, maxv=10000.0))
    shaft_shape = (a.text("shaft", "цилиндр") or "цилиндр").strip().lower()
    shaft_shape = {"цилиндр": "цилиндр", "труба": "цилиндр", "круглый": "цилиндр",
                   "брусок": "брусок", "квадрат": "брусок",
                   "параллелепипед": "брусок"}.get(shaft_shape)
    if shaft_shape is None:
        raise GeometryError("shaft=цилиндр или брусок.")
    diameter = float(a.num("diameter", 14.0, minv=0.5, maxv=1000.0))
    size = float(a.num("size", diameter, minv=0.5, maxv=1000.0))
    knob_shape = (a.text("knob", "шар") or "шар").strip().lower()
    knob_shape = {"шар": "шар", "сфера": "шар", "круглая": "шар",
                  "цилиндр": "цилиндр", "труба": "цилиндр"}.get(knob_shape)
    if knob_shape is None:
        raise GeometryError("knob=шар или цилиндр; режима «нет» больше нет.")
    knob_d = float(a.num("knob_d", 34.0, minv=1.0, maxv=2000.0))
    knob_h = float(a.num("knob_h", 60.0, minv=1.0, maxv=5000.0))
    angle = float(a.num("angle", 0.0, minv=-89.0, maxv=89.0))
    segments = _segments(a, 40, minv=12)
    if knob_h > length:
        raise GeometryError("knob_h не может быть больше общей длины рычага.")
    needed = diameter if shaft_shape == "цилиндр" else size * math.sqrt(2.0)
    if knob_d + 1e-6 < needed:
        raise GeometryError("Наконечник тоньше палки: чистый стык невозможен.",
                            hint=f"knob_d должен быть не меньше {needed:g} мм.")

    shaft_length = length - knob_h / 2.0  # заготовка до центра наконечника
    if shaft_shape == "цилиндр":
        shaft = mf.Manifold.cylinder(shaft_length, diameter / 2.0, diameter / 2.0,
                                     segments).rotate((0.0, 90.0, 0.0))
    else:
        shaft = mf.Manifold.cube((shaft_length, size, size)).translate(
            (0.0, -size / 2.0, -size / 2.0))
    if knob_shape == "шар":
        knob = mf.Manifold.sphere(1.0, segments).scale(
            (knob_h / 2.0, knob_d / 2.0, knob_d / 2.0))
        knob = knob.translate((length - knob_h / 2.0, 0.0, 0.0))
    else:
        knob = mf.Manifold.cylinder(knob_h, knob_d / 2.0, knob_d / 2.0,
                                    segments).rotate((0.0, 90.0, 0.0))
        knob = knob.translate((length - knob_h, 0.0, 0.0))
    # Убрать всю заготовку палки изнутри наконечника. Внешняя поверхность
    # наконечника остаётся чистой, а стык повторяет её форму.
    shaft = shaft - knob
    solid = shaft + knob
    if abs(angle) > 1e-6:
        solid = solid.rotate((0.0, -angle, 0.0))
    placed = _placed_all(a, [solid])[0]
    out = _make(a, name, placed, "lever")
    out.notes.append(f"рычаг {length:g} мм, палка {shaft_shape}, наконечник "
                     f"{knob_shape} {knob_d:g}×{knob_h:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Кнопка — две отдельные детали
# --------------------------------------------------------------------------- #
@op("button", aliases=("кнопка", "клавиша", "button_cap", "push_button"),
    category="Примитивы",
    summary="Кнопка из двух деталей: шляпка и гнездо. Шляпка сверху плоская, "
            "вогнутая (ложбинка под палец) или выпуклая; гнездо — цилиндр или "
            "квадратная платформа. fit=плотно сажает шляпку без зазора, "
            "fit=зазор оставляет кольцевую щель и вырез под кнопку — так "
            "шляпку видно отдельно и легко анимировать: она отдельный объект.",
    example="к = button diameter=30 height=10 top=вогнутая\n"
            "к = button diameter=34 height=12 fit=зазор gap=3 base=квадрат\n"
            "аварийная = button diameter=60 height=18 top=выпуклая "
            "base_d=110 base_h=14",
    params={"diameter": "диаметр шляпки, мм (30)",
            "height": "высота шляпки, мм (10)",
            "top": "верх: плоская, вогнутая или выпуклая — «вогнутая»",
            "sag": "глубина ложбинки или высота купола, мм (авто 0.25·height)",
            "base": "гнездо: цилиндр или квадрат — «цилиндр»",
            "base_d": "диаметр или сторона гнезда, мм (авто 2.2·diameter)",
            "base_h": "высота гнезда, мм (8)",
            "fit": "плотно или зазор — «плотно»",
            "gap": "зазор по кругу при fit=зазор, мм (3)",
            "smooth": "уровни Loop-сглаживания шляпки и гнезда 0…4 (0)",
            "segments": "сегментов у круглых частей (по детализации)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def button(a, name):
    diameter = float(a.num("diameter", 30.0, minv=1.0))
    height = float(a.num("height", 10.0, minv=0.6))
    top = (a.text("top", "вогнутая") or "вогнутая").strip().lower()
    top = {"плоская": "плоская", "ровная": "плоская", "flat": "плоская",
           "вогнутая": "вогнутая", "ложбинка": "вогнутая", "concave": "вогнутая",
           "выпуклая": "выпуклая", "купол": "выпуклая", "convex": "выпуклая"}.get(top)
    if top is None:
        raise GeometryError(f"Неизвестный верх кнопки: «{a.text('top')}».",
                            hint="top=плоская, вогнутая или выпуклая.")
    sag = a.num("sag", None, minv=0.05)
    sag = float(max(0.2, min(height * 0.45, diameter * 0.12)) if sag is None
                else sag)
    if sag >= height * 0.9 and top == "вогнутая":
        raise GeometryError(f"Ложбинка {sag:g} мм глубже самой шляпки {height:g} мм.",
                            hint=f"sag должен быть меньше {height * 0.9:g} мм.")
    base_shape = (a.text("base", "цилиндр") or "цилиндр").strip().lower()
    base_shape = {"цилиндр": "цилиндр", "круг": "цилиндр", "круглая": "цилиндр",
                  "квадрат": "квадрат", "квадратная": "квадрат",
                  "прямоугольник": "квадрат"}.get(base_shape)
    if base_shape is None:
        raise GeometryError(f"Неизвестное гнездо: «{a.text('base')}».",
                            hint="base=цилиндр или квадрат.")
    base_d = float(a.num("base_d", diameter * 2.2, minv=diameter * 1.05))
    base_h = float(a.num("base_h", 8.0, minv=1.0))
    fit = (a.text("fit", "плотно") or "плотно").strip().lower()
    fit = {"плотно": "плотно", "tight": "плотно", "без_зазора": "плотно",
           "зазор": "зазор", "с_зазором": "зазор", "loose": "зазор"}.get(fit)
    if fit is None:
        raise GeometryError(f"Неизвестная посадка: «{a.text('fit')}».",
                            hint="fit=плотно или зазор.")
    gap = float(a.num("gap", 3.0, minv=0.0))
    segments = _segments(a, max(32, int(diameter * 2)), minv=16)
    radius = diameter / 2.0

    # --- шляпка: тело вращения, верх по выбору
    prof: list[tuple[float, float]] = [(0.0, 0.0), (radius, 0.0), (radius, height)]
    if top == "вогнутая":
        steps = 10
        for k in range(1, steps + 1):
            s = k / steps
            r = radius * (1.0 - s)
            z = height - sag * (1.0 - (1.0 - s) ** 2)   # пологая ложбинка
            prof.append((max(0.0, r), z))
    elif top == "выпуклая":
        steps = 10
        for k in range(1, steps + 1):
            s = k / steps
            r = radius * (1.0 - s)
            z = height + sag * (1.0 - (1.0 - s) ** 2)
            prof.append((max(0.0, r), z))
    else:
        prof.append((0.0, height))
    cap = mf.Manifold.revolve(mf.CrossSection([_profile(prof)]), segments)

    # --- гнездо: платформа с вырезом под шляпку
    clearance = 0.3 if fit == "плотно" else gap
    socket_r = radius + clearance
    socket_depth = min(height * 0.35, 2.5) if fit == "плотно" else min(
        height * 0.5, 4.0)
    if base_shape == "цилиндр":
        plate = mf.Manifold.cylinder(base_h, base_d / 2.0, base_d / 2.0, segments)
    else:
        # куб по умолчанию растёт от угла — центрируем по XY и поднимаем на base_h
        plate = mf.Manifold.cube((base_d, base_d, base_h), center=True).translate(
            (0.0, 0.0, base_h / 2.0))
    # вырез ровно socket_depth глубиной: от base_h - socket_depth и выше
    cutter = mf.Manifold.cylinder(socket_depth + 1.0, socket_r, socket_r, segments)
    cutter = cutter.translate((0.0, 0.0, base_h - socket_depth))
    plate = plate - cutter
    if plate.is_empty() or plate.volume() <= 1e-6:
        raise GeometryError("Гнездо кнопки получилось пустым: вырез съел платформу.",
                            hint="Увеличьте base_d или уменьшите diameter.")
    cap = cap.translate((0.0, 0.0, base_h - socket_depth))
    plate = apply_smooth(plate, a, "гнездо кнопки")
    cap = apply_smooth(cap, a, "шляпка кнопки")
    placed = _placed_all(a, [plate, cap])
    # главный объект — шляпка: её и анимируют; гнездо живёт отдельно
    main = _make(a, name, placed[1], "button")
    _extra(a, main.name, "гнездо", placed[0], "button_base")
    main.notes.append(
        f"шляпка ø{diameter:g}×{height:g} мм, верх {top}"
        + (f" {sag:g} мм" if top != "плоская" else "")
        + f"; гнездо {base_shape} {base_d:g}×{base_h:g} мм, посадка {fit}"
        + (f" {gap:g} мм" if fit == "зазор" else ""))
    main.notes.append("шляпка и гнездо — два объекта: шляпку можно двигать и "
                      "анимировать отдельно")
    return main


def _make(a, name: str, solid: mf.Manifold, kind: str):
    from .ops import make_solid
    return make_solid(a.scene, name, solid, a, kind=kind)
