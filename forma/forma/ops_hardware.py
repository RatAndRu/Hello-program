"""Крепёж и фурнитура: гайки, болты, винты, петли, уголки, подшипники,
ролики и шкивы.

Это настоящие замкнутые тела с резьбой, отверстиями под крепёж и посадочными
местами: их можно ставить в сборку, резать, проверять на герметичность и
считать массу. Размеры по умолчанию — под метрический крепёж (M8, M6, …).
"""

from __future__ import annotations

import math

import manifold3d as mf

from .errors import GeometryError
from .ops import anchor, make_solid, op
from .ops_tech import _helix_ridge


# --------------------------------------------------------------------------- #
#  Помощники
# --------------------------------------------------------------------------- #
def _cyl(h: float, r: float, seg: int = 64) -> mf.Manifold:
    return mf.Manifold.cylinder(float(h), float(r), float(r), int(seg))


def _box(size) -> mf.Manifold:
    return mf.Manifold.cube([float(v) for v in size], True)


def _hex_prism(across_flats: float, height: float) -> mf.Manifold:
    """Шестигранная призма: across_flats — размер «под ключ»."""
    r = float(across_flats) / math.sqrt(3.0)
    return mf.Manifold.cylinder(float(height), r, r, 6)


def _hole_z(x: float, y: float, z0: float, height: float, r: float,
            seg: int = 32) -> mf.Manifold:
    return _cyl(height, r, seg).translate((x, y, z0))


def _hole_y(x: float, z: float, y0: float, length: float, r: float,
            seg: int = 32) -> mf.Manifold:
    return _cyl(length, r, seg).rotate((90, 0, 0)).translate((x, y0, z))


def _thread_bore(diameter: float, pitch: float, length: float,
                 steps_per_turn: int = 40) -> mf.Manifold:
    """Внутренняя резьба: цилиндрическая полость с винтовым выступом."""
    core = max(0.6, diameter / 2.0 - pitch * 0.55)
    bore = _cyl(length + 0.4, core, 72).translate((0, 0, -0.2))
    depth = min(pitch * 0.55, core * 0.32)
    ridge = _helix_ridge(core, length, pitch, depth, pitch * 0.5,
                         steps_per_turn=steps_per_turn, inset=0.35)
    return bore + ridge


def _thread_shank(diameter: float, length: float, pitch: float,
                  steps_per_turn: int = 48) -> mf.Manifold:
    """Стержень с наружной резьбой: тело + винтовой гребень."""
    depth = min(pitch * 0.55, diameter * 0.12)
    core = max(0.6, diameter / 2.0 - depth)
    body = _cyl(length, core, 56)
    ridge = _helix_ridge(core, length, pitch, depth, pitch * 0.5,
                         steps_per_turn=steps_per_turn, inset=0.5)
    return body + ridge


def _finish(a, name: str, solid: mf.Manifold, kind: str, note: str):
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Деталь получилась пустой — проверьте размеры.")
    placed = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, placed, a, kind=kind)
    out.notes.append(note)
    a.scene.log("info", note, a.cmd.line)
    return out


def _size(a, key: str, default: float, minv: float = 0.2,
          maxv: float = 2000.0) -> float:
    return float(a.num(key, default, minv=minv, maxv=maxv))


# --------------------------------------------------------------------------- #
#  Гайка
# --------------------------------------------------------------------------- #
@op("nut", aliases=("гайка", "гайка_шестигранная", "hex_nut"), category="Примитивы",
    summary="Шестигранная гайка с внутренней резьбой. Размер «под ключ» "
            "подбирается автоматически по диаметру резьбы.",
    example="гайка = nut d=8 pitch=1.25",
    params={"d": "диаметр резьбы, мм (8)", "diameter": "то же, что d",
            "pitch": "шаг резьбы (1.25)", "h": "высота гайки (6.4)",
            "s": "размер под ключ (13)", "thread": "нарезать резьбу (да)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def nut(a, name):
    d = float(a.num("d", a.num("diameter", 8.0), minv=1.0, maxv=300.0))
    pitch = float(a.num("pitch", max(0.35, 0.15 * d), minv=0.1, maxv=20.0))
    h = float(a.num("h", max(1.2, 0.8 * d), minv=0.6, maxv=400.0))
    s = float(a.num("s", max(d + 2.0, 1.6 * d), minv=d * 0.9, maxv=600.0))
    thread = a.boolean("thread", True)
    if s <= d * 0.95:
        raise GeometryError("Размер под ключ должен быть больше диаметра резьбы.")
    body = _hex_prism(s, h)
    if thread:
        body = body - _thread_bore(d, pitch, h)
    else:
        body = body - _cyl(h + 0.4, d * 0.42, 48).translate((0, 0, -0.2))
    return _finish(a, name, body, "nut",
                   f"гайка M{d:g} · под ключ {s:g} мм · высота {h:g} мм"
                   + (" · резьба" if thread else ""))


# --------------------------------------------------------------------------- #
#  Болт
# --------------------------------------------------------------------------- #
@op("bolt", aliases=("болт", "винт_с_шестигранником", "hex_bolt"), category="Примитивы",
    summary="Болт с шестигранной головкой и метрической резьбой на стержне.",
    example="болт = bolt d=8 length=30",
    params={"d": "диаметр резьбы, мм (8)", "length": "длина стержня (30)",
            "pitch": "шаг резьбы (1.25)", "head": "высота головки (5.6)",
            "s": "размер под ключ (13)", "thread": "нарезать резьбу (да)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def bolt(a, name):
    d = float(a.num("d", 8.0, minv=1.0, maxv=300.0))
    length = float(a.num("length", 30.0, minv=1.0, maxv=2000.0))
    pitch = float(a.num("pitch", max(0.35, 0.15 * d), minv=0.1, maxv=20.0))
    head_h = float(a.num("head", max(0.8, 0.7 * d), minv=0.4, maxv=200.0))
    s = float(a.num("s", max(d + 2.0, 1.6 * d), minv=d * 0.9, maxv=600.0))
    thread = a.boolean("thread", True)
    shank = _thread_shank(d, length, pitch) if thread else _cyl(length, d / 2.0, 56)
    head = _hex_prism(s, head_h).translate((0, 0, length))
    # фаска на головке: срезаем верхнюю кромку конусом
    chamfer = _cyl(head_h * 0.35, s * 0.62, 6).rotate((180, 0, 0)).translate(
        (0, 0, length + head_h + 0.01))
    body = (shank + head) - chamfer
    return _finish(a, name, body, "bolt",
                   f"болт M{d:g}×{length:g} · головка под ключ {s:g} мм"
                   + (" · резьба" if thread else ""))


# --------------------------------------------------------------------------- #
#  Винт / саморез
# --------------------------------------------------------------------------- #
@op("screw", aliases=("винт", "саморез", "шуруп"), category="Примитивы",
    summary="Винт с потайной или полукруглой головкой и частой резьбой; "
            "подходит для крепления фурнитуры и дерева.",
    example="винт = screw d=4 length=25 head=потай",
    params={"d": "диаметр, мм (4)", "length": "длина стержня (25)",
            "head": "потай, полукруг или шестигранник (потай)",
            "head_d": "диаметр головки (2 × d)", "pitch": "шаг резьбы (0.7)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def screw(a, name):
    d = float(a.num("d", 4.0, minv=0.5, maxv=100.0))
    length = float(a.num("length", 25.0, minv=1.0, maxv=1000.0))
    head = (a.text("head") or "потай").strip().lower()
    if head in ("countersunk", "потайной", "потай"):
        head = "потай"
    elif head in ("pan", "полукруг", "полукруглая"):
        head = "полукруг"
    elif head in ("hex", "шестигранник", "шестигранная"):
        head = "шестигранник"
    else:
        raise GeometryError("Головка винта: потай, полукруг или шестигранник.")
    head_d = float(a.num("head_d", 2.0 * d, minv=1.2 * d, maxv=20 * d))
    pitch = float(a.num("pitch", max(0.25, 0.2 * d), minv=0.1, maxv=10.0))
    shank = _thread_shank(d, length, pitch, steps_per_turn=40)
    # остриё: короткий конус снизу, чтобы саморез входил в материал
    tip = mf.Manifold.cylinder(float(d * 0.9), float(d / 2.0), 0.01, 40).rotate((180, 0, 0))
    body = (shank + tip)
    if head == "потай":
        cap = mf.Manifold.cylinder(float(d), float(head_d / 2.0), float(d / 2.0), 40)
        cap = cap.translate((0, 0, length))
    elif head == "полукруг":
        cap = _cyl(d * 0.6, head_d / 2.0, 40).translate((0, 0, length))
        dome = mf.Manifold.sphere(head_d / 2.0, 32).translate((0, 0, length + d * 0.6))
        cap = mf.Manifold.batch_boolean(
            [cap + dome, _cyl(d * 1.6, head_d / 2.0, 40).translate((0, 0, length))],
            mf.OpType.Intersect)
    else:
        cap = _hex_prism(1.6 * d, 0.7 * d).translate((0, 0, length))
    body = body + cap
    return _finish(a, name, body, "screw",
                   f"винт Ø{d:g}×{length:g} · головка {head}")


# --------------------------------------------------------------------------- #
#  Петля
# --------------------------------------------------------------------------- #
@op("hinge", aliases=("петля", "шарнир", "hinge"), category="Примитивы",
    summary="Мебельная петля: две пластины, шарнир и ось. Отверстия под "
            "саморезы уже просверлены — деталь готова к сборке.",
    example="петля = hinge width=45 height=35 thickness=2",
    params={"width": "ширина одной пластины (45)", "height": "высота пластины (35)",
            "thickness": "толщина пластины (2)", "pin": "диаметр шарнира (8)",
            "holes": "отверстий на пластину (2)", "at": "положение",
            "center": "центрировать в at"})
def hinge(a, name):
    width = float(a.num("width", 45.0, minv=5.0, maxv=500.0))
    height = float(a.num("height", 35.0, minv=5.0, maxv=500.0))
    thick = float(a.num("thickness", 2.0, minv=0.3, maxv=20.0))
    pin = float(a.num("pin", 8.0, minv=1.0, maxv=80.0))
    holes = int(a.num("holes", 2, minv=0, maxv=12))
    barrel = _cyl(height, pin / 2.0, 48).translate((0, 0, 0))
    # пластины заходят в шарнир — иначе лежат на нём по касательной и деталь
    # распадается на отдельные тела
    overlap = pin * 0.45
    leaf_l = _box((width, thick, height)).translate(
        (-pin / 2.0 - width / 2.0 + overlap, 0, height / 2.0))
    leaf_r = _box((width, thick, height)).translate(
        (pin / 2.0 + width / 2.0 - overlap, 0, height / 2.0))
    # ось шарнира выступает сверху и снизу
    pin_h = height + pin * 0.5
    pin_m = _cyl(pin_h, pin * 0.22, 32).translate((0, 0, -pin * 0.25))
    body = barrel + leaf_l + leaf_r + pin_m
    if holes:
        r = max(0.8, pin * 0.22)
        for side in (-1.0, 1.0):
            for i in range(holes):
                z = height * (i + 1) / (holes + 1)
                body = body - _hole_y(side * (pin / 2.0 + width * 0.55), z,
                                      -thick, thick * 2.0, r)
    return _finish(a, name, body, "hinge",
                   f"петля {width:g}×{height:g} мм · шарнир Ø{pin:g} · отверстий {holes * 2}")


# --------------------------------------------------------------------------- #
#  Уголок
# --------------------------------------------------------------------------- #
@op("bracket", aliases=("уголок", "крепежный_уголок", "bracket"), category="Примитивы",
    summary="Уголок для сборки корпусов: две полки под 90°, отверстия под "
            "саморезы или болты.",
    example="уголок = bracket width=60 depth=40 height=40 thickness=3",
    params={"width": "ширина, мм (60)", "depth": "глубина полки (40)",
            "height": "высота полки (40)", "thickness": "толщина стали (3)",
            "holes": "отверстий на полку (2)", "at": "положение",
            "center": "центрировать в at"})
def bracket(a, name):
    w = float(a.num("width", 60.0, minv=5.0, maxv=600.0))
    depth = float(a.num("depth", 40.0, minv=3.0, maxv=600.0))
    height = float(a.num("height", 40.0, minv=3.0, maxv=600.0))
    t = float(a.num("thickness", 3.0, minv=0.4, maxv=30.0))
    holes = int(a.num("holes", 2, minv=0, maxv=10))
    vert = _box((w, t, height)).translate((0, t / 2.0, height / 2.0))
    horz = _box((w, depth, t)).translate((0, depth / 2.0, t / 2.0))
    # скругление внешнего угла сгиба — фаска 45°
    body = vert + horz
    if holes:
        r = max(0.9, min(t * 1.2, 2.4))
        for i in range(holes):
            x = -w / 2.0 + w * (i + 1) / (holes + 1)
            body = body - _hole_y(x, height * 0.62, -t, t * 3.0, r)
            body = body - _hole_z(x, depth * 0.62, -t, t * 3.0, r)
    return _finish(a, name, body, "bracket",
                   f"уголок {w:g}×{height:g}×{depth:g} · сталь {t:g} мм · отверстий {holes * 2}")


# --------------------------------------------------------------------------- #
#  Подшипник
# --------------------------------------------------------------------------- #
@op("bearing", aliases=("подшипник", "bearing_ring"), category="Примитивы",
    summary="Шариковый подшипник: наружное и внутреннее кольца, шарики и "
            "посадочное отверстие под вал.",
    example="подшипник = bearing outer=40 inner=17 width=12",
    params={"outer": "наружный диаметр (40)", "inner": "диаметр вала (17)",
            "width": "ширина (12)", "balls": "число шариков (9)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def bearing(a, name):
    outer = float(a.num("outer", 40.0, minv=6.0, maxv=1000.0))
    inner = float(a.num("inner", 17.0, minv=1.0, maxv=900.0))
    width = float(a.num("width", 12.0, minv=2.0, maxv=300.0))
    count = int(a.num("balls", 9, minv=6, maxv=40))
    if inner >= outer * 0.75:
        raise GeometryError("Внутренний диаметр должен быть заметно меньше наружного.")
    ring = (outer - inner) * 0.22          # толщина кольца
    outer_ring = _cyl(width, outer / 2.0, 80) - _cyl(width + 0.2, outer / 2.0 - ring, 80)
    inner_ring = _cyl(width, inner / 2.0 + ring * 1.4, 64) - _cyl(width + 0.2, inner / 2.0, 64)
    body = outer_ring + inner_ring
    gap = (outer / 2.0 - ring) - (inner / 2.0 + ring * 1.4)
    ball_r = max(0.4, min(gap * 0.42, width * 0.35))
    mid = (outer / 2.0 - ring + inner / 2.0 + ring * 1.4) / 2.0
    for i in range(count):
        ang = 2.0 * math.pi * i / count
        body = body + mf.Manifold.sphere(ball_r, 20).translate(
            (mid * math.cos(ang), mid * math.sin(ang), width / 2.0))
    return _finish(a, name, body, "bearing",
                   f"подшипник {outer:g}×{inner:g}×{width:g} · шариков {count}")


# --------------------------------------------------------------------------- #
#  Ролик (колесо с вилкой)
# --------------------------------------------------------------------------- #
@op("caster", aliases=("ролик", "колесо_с_вилкой", "caster_wheel"), category="Примитивы",
    summary="Мебельный ролик: колесо, вилка, площадка и ось. Колёсико уже "
            "смотрит осью по X — можно сразу ставить под шкаф и анимировать качение.",
    example="ролик = caster wheel=50 width=18",
    params={"wheel": "диаметр колеса (50)", "width": "ширина колеса (18)",
            "plate": "размер площадки (45)", "at": "положение",
            "center": "центрировать в at"})
def caster(a, name):
    wheel = float(a.num("wheel", 50.0, minv=8.0, maxv=400.0))
    width = float(a.num("width", 18.0, minv=4.0, maxv=200.0))
    plate = float(a.num("plate", 45.0, minv=12.0, maxv=300.0))
    r = wheel / 2.0
    t = max(1.5, r * 0.12)
    wheel_m = _cyl(width, r, 64).rotate((0, 90, 0)).translate((0, 0, r))
    axle = _cyl(width + 2.0 * t + 2.0, max(1.0, r * 0.14), 24).rotate((0, 90, 0)).translate(
        (0, 0, r))
    fork_h = r * 0.95
    fork_l = _box((t, width * 0.6 + t, fork_h)).translate(
        (-(width / 2.0 + t / 2.0), 0, r + fork_h / 2.0 - t))
    fork_r = _box((t, width * 0.6 + t, fork_h)).translate(
        ((width / 2.0 + t / 2.0), 0, r + fork_h / 2.0 - t))
    top = _cyl(max(2.0, t), plate * 0.32, 48).translate((0, 0, r + fork_h - t))
    plate_m = _box((plate, plate, max(2.0, t))).translate((0, 0, r + fork_h - t
                                                         + max(2.0, t) / 2.0))
    body = wheel_m + axle + fork_l + fork_r + top + plate_m
    return _finish(a, name, body, "caster",
                   f"ролик Ø{wheel:g} · ширина {width:g} · площадка {plate:g} мм")


# --------------------------------------------------------------------------- #
#  Шкив
# --------------------------------------------------------------------------- #
@op("pulley", aliases=("шкив", "шкив_ручья", "pulley_wheel"), category="Примитивы",
    summary="Шкив с канавкой под ремень и посадочным отверстием: годится для "
            "ременных передач и механизмов.",
    example="шкив = pulley diameter=80 width=20 bore=10 groove=6",
    params={"diameter": "наружный диаметр (80)", "width": "ширина обода (20)",
            "bore": "диаметр отверстия под вал (10)", "groove": "ширина канавки (6)",
            "at": "положение", "center": "центрировать в at"})
def pulley(a, name):
    d = float(a.num("diameter", 80.0, minv=10.0, maxv=1000.0))
    width = float(a.num("width", 20.0, minv=4.0, maxv=300.0))
    bore = float(a.num("bore", 10.0, minv=1.0, maxv=d * 0.7))
    groove = float(a.num("groove", 6.0, minv=1.0, maxv=width * 0.8))
    if bore >= d * 0.75:
        raise GeometryError("Отверстие под вал слишком велико для этого диаметра.")
    R = d / 2.0
    g = groove / 2.0
    h = width / 2.0
    profile = [
        (bore / 2.0, 0.0),
        (R, 0.0),
        (R, h - g * 0.6),
        (R - groove * 0.5, h),
        (R, h + g * 0.6),
        (R, width),
        (bore / 2.0, width),
    ]
    cs = mf.CrossSection([profile])
    body = mf.Manifold.revolve(cs, 96)
    # щёки шкива чуть уже обода — канавка читается силуэтом
    return _finish(a, name, body, "pulley",
                   f"шкив Ø{d:g}×{width:g} · вал Ø{bore:g} · канавка {groove:g} мм")
