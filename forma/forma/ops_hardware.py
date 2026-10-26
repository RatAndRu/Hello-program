"""Крепёж и фурнитура: гайки, болты, винты, петли, уголки, подшипники,
ролики и шкивы.

Это настоящие замкнутые тела с резьбой, отверстиями под крепёж и посадочными
местами: их можно ставить в сборку, резать, проверять на герметичность и
считать массу. Размеры по умолчанию — под метрический крепёж (M8, M6, …).
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from . import orient
from .errors import GeometryError
from .ops import anchor, make_solid, op
from .shape_features import rounded_extrude, transition_radius
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



def _axis_matrix(axis) -> np.ndarray:
    """Матрица поворота: локальная +Z смотрит в вектор axis."""
    target = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(target))
    if norm < 1e-9:
        raise GeometryError("Нулевое направление.")
    t = target / norm
    z = np.asarray([0.0, 0.0, 1.0])
    v = np.cross(z, t)
    c = float(np.dot(z, t))
    if np.linalg.norm(v) < 1e-9:
        r = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        vx = np.asarray([[0.0, -v[2], v[1]],
                         [v[2], 0.0, -v[0]],
                         [-v[1], v[0], 0.0]])
        r = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
    mat = np.eye(3, 4, dtype=np.float64)
    mat[:, :3] = r
    return mat


def _orient_axis(solid: mf.Manifold, direction) -> mf.Manifold:
    """Разворачивает деталь так, чтобы её локальная +Z смотрела в direction."""
    return solid.transform(np.ascontiguousarray(_axis_matrix(direction), dtype=np.float64))


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
    summary="Саморез: слепой крестовой или шестилопастной Torx-карман с "
            "регулируемой глубиной. По умолчанию резьба доходит непосредственно "
            "до головки без гладкой шейки; neck>0 возвращает шейку. Вершина "
            "резьбы не выходит за d.",
    example="саморез = screw d=4 length=25 head=потай drive=крест",
    params={"d": "диаметр резьбы, мм (4)",
            "length": "длина стержня без головки, мм (25)",
            "full": "полная длина с головкой — перекрывает length",
            "head": "потай, полукруг, шестигранник или нет (потай)",
            "head_only": "да — оставить только головку без стержня и острия (нет)",
            "only_head": "синоним head_only",
            "head_d": "диаметр головки (2 × d)",
            "head_h": "высота головки (у потайной считается по 90°)",
            "drive": "шлиц: крест, шлиц, звезда, шестигранник или нет (крест)",
            "drive_size": "размер шлица, мм (0.42 × head_d)",
            "drive_depth": "глубина слепого шлица, мм; автоматически не сквозь головку",
            "neck": "гладкая шейка ПОД ГОЛОВКОЙ, мм (0 — резьба сразу от головки)",
            "pitch": "шаг резьбы, мм (0.45 × d)",
            "thread": "нарезать резьбу (да)",
            "tip": "длина острия, мм (1.3 × d)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def screw(a, name):
    d = float(a.num("d", 4.0, minv=0.5, maxv=100.0))
    length = float(a.num("length", 25.0, minv=1.0, maxv=1000.0))
    head = (a.text("head") or "потай").strip().lower()
    if head in ("countersunk", "потайной", "потай", "зенкованная", "csk"):
        head = "потай"
    elif head in ("pan", "полукруг", "полукруглая", "полуцилиндр"):
        head = "полукруг"
    elif head in ("hex", "шестигранник", "шестигранная"):
        head = "шестигранник"
    elif head in ("нет", "none", "без", "без_головки"):
        head = "нет"
    else:
        raise GeometryError("Головка винта: потай, полукруг, шестигранник или нет.")
    head_only = a.boolean("head_only", False) or a.boolean("only_head", False)
    if head_only and head == "нет":
        raise GeometryError("head_only=да требует головку: выберите потай, полукруг или шестигранник.")
    drive = (a.text("drive") or "крест").strip().lower()
    if drive in ("phillips", "ph", "крестовая", "крест", "philips"):
        drive = "крест"
    elif drive in ("slot", "шлиц", "плоский", "прямой"):
        drive = "шлиц"
    elif drive in ("torx", "звезда", "звёздочка", "звездочка"):
        drive = "звезда"
    elif drive in ("hex", "шестигранник", "внутренний_шестигранник", "имбус"):
        drive = "шестигранник"
    elif drive in ("нет", "none", "без"):
        drive = "нет"
    else:
        raise GeometryError("Шлиц: крест, шлиц, звезда, шестигранник или нет.")
    head_d = float(a.num("head_d", 2.05 * d, minv=1.2 * d, maxv=20 * d))
    pitch = float(a.num("pitch", max(0.3, 0.45 * d), minv=0.1, maxv=10.0))
    thread = a.boolean("thread", True)
    tip_len = float(a.num("tip", 1.3 * d, minv=0.1, maxv=6 * d))
    neck = float(a.num("neck", 0.0, minv=0.0, maxv=length * 0.6) or 0.0)
    head_h = float(a.num("head_h", 0.0, minv=0.0) or 0.0)
    if a.has("full"):
        full = float(a.num("full", length + 2.0 * d, minv=2.0))
        length = max(1.0, full - max(head_h, d * 0.55 if head == "полукруг" else d * 0.5))
    # высота головки: у потайной — из угла 90°, у остальных — по диаметру
    if head_h <= 0:
        head_h = max(0.6, (head_d - d) / 2.0) if head == "потай" else max(1.0, 0.6 * d)
    # ГОСТ/DIN: у потайного самореза длина — полная, вместе с головкой;
    # у полукруглой и шестигранной головка считается отдельно. Остриё входит
    # в длину всегда, поэтому 16-мм саморез не выйдет из 18-мм доски.
    body_len = 0.0 if head_only else length - (head_h + 0.35 if head == "потай" else 0.0)
    if not head_only and body_len < max(2.0, d):
        raise GeometryError(
            "Саморез короче своей головки.",
            hint=f"Для головки Ø{head_d:g} мм нужна длина больше {head_h * 2 + d:g} мм.")
    tip_len = 0.0 if head_only else min(tip_len, max(0.5, body_len * 0.45))
    neck = 0.0 if head_only else min(neck, max(0.0, body_len - tip_len - pitch * 1.2))
    thread_len = 0.0 if head_only else max(0.0, body_len - tip_len - neck)
    if thread and not head_only and thread_len < pitch * 1.5:
        thread = False
    if head_only:
        thread = False
        body = mf.Manifold()
    else:
        # --- стержень -------------------------------------------------------
        core_r = max(0.25, d / 2.0 - min(pitch * 0.5, d * 0.14))
        shank = _cyl(max(0.1, thread_len), core_r, 56).translate((0, 0, tip_len))
        if thread:
            ridge = _helix_ridge(core_r, thread_len, pitch, d / 2.0 - core_r,
                                 pitch * 0.52, steps_per_turn=44, inset=0.5,
                                 fade=min(pitch, thread_len * 0.45),
                                 fade_top=(0.0 if neck <= 0.05
                                           else min(pitch, thread_len * 0.45)))
            shank = shank + ridge.translate((0, 0, tip_len))
        # Гладкая шейка находится сверху, под головкой, а не между резьбой и жалом.
        if neck > 0.05:
            shank = shank + _cyl(neck, d / 2.0 - (d / 2.0 - core_r) * 0.35, 56).translate(
                (0, 0, body_len - neck))
        # --- остриё: жало с небольшим плоским кончиком ----------------------
        tip = mf.Manifold.cylinder(float(tip_len), float(max(core_r, 0.35)), 0.16, 40)
        tip = tip.rotate((180, 0, 0)).translate((0, 0, tip_len))
        body = shank + tip
    # --- головка ------------------------------------------------------------
    if head == "потай":
        cap = mf.Manifold.cylinder(float(head_h), float(d / 2.0), float(head_d / 2.0), 56)
        cap = cap.translate((0, 0, body_len))
        rim = _cyl(0.35, head_d / 2.0, 56).translate(
            (0, 0, (head_h if head_only else length) - 0.35))
        cap = cap + rim
    elif head == "полукруг":
        cap = _cyl(head_h, head_d / 2.0, 56).translate((0, 0, body_len))
        dome = mf.Manifold.sphere(head_d / 2.0, 40).translate((0, 0, body_len))
        cap = (cap + dome) - _box((head_d * 2, head_d * 2, head_d * 2)).translate(
            (0, 0, body_len - head_d * 0.2))
        cap = cap + _cyl(head_h + 0.42, head_d / 2.0 - 0.15, 56).translate(
            (0, 0, body_len))
    elif head == "шестигранник":
        cap = _hex_prism(head_d, head_h).translate((0, 0, body_len))
    else:
        cap = None
    body = (cap if head_only else body + cap) if cap is not None else body
    # --- шлиц ---------------------------------------------------------------
    if drive != "нет" and head != "нет":
        # Реальная вершина после сборки: у полукруглой головки это купол,
        # а не воображаемая плоскость body_len+head_h внутри него.
        top = float(body.bounding_box()[5])
        size = float(a.num("drive_size", 0.42 * head_d, minv=0.3, maxv=head_d * 0.8))
        available = max(0.2, top - body_len)
        deep_req = float(a.num("drive_depth", max(0.4, min(head_h * 0.55, size * 0.75)),
                                minv=0.1))
        deep = min(deep_req, available * 0.65)
        z_tool = top + 0.5 - deep / 2.0
        if drive == "крест":
            # Два кармана с общим дном top−deep; верхний запас +1 мм нужен
            # только для чистого булева реза. Размер меньше радиуса головки.
            slot_a = _box((size, size * 0.24, deep + 1.0)).translate((0, 0, z_tool))
            slot_b = _box((size, size * 0.24, deep + 1.0)).rotate((0, 0, 90)).translate(
                (0, 0, z_tool))
            body = body - (slot_a + slot_b)
        elif drive == "шлиц":
            slot = _box((head_d * 1.02, max(0.5, size * 0.3), deep + 1.0)).translate(
                (0, 0, z_tool))
            body = body - slot
        elif drive == "звезда":
            # Torx: ШЕСТЬ плавных лопастей вокруг одного слепого кармана.
            # Шесть повёрнутых брусков давали двенадцатилучевую решётку,
            # непохожую на реальный шлиц и оставлявшую острые перемычки.
            pts = []
            for i in range(96):
                ang = 2.0 * math.pi * i / 96.0
                radius = size * 0.5 * (0.80 + 0.20 * math.cos(6.0 * ang))
                pts.append((radius * math.cos(ang), radius * math.sin(ang)))
            pocket = mf.CrossSection([np.asarray(pts, dtype=np.float64)])
            tool = mf.Manifold.extrude(pocket, deep + 1.0).translate((0, 0, top - deep))
            body = body - tool
        else:
            body = body - _hex_prism(size, deep + 1.0).translate((0, 0, top - deep))
    total = body_len + (head_h if cap is not None else 0.0)
    out = _finish(a, name, body, "screw",
                  f"саморез Ø{d:g}×{length:g} (полная {total:g}) · головка {head}"
                  f" · шлиц {drive}")
    # update, а не замена словаря: make_solid уже записал локальные axes.
    out.meta.update({"screw": True, "head": head, "head_only": bool(head_only),
                     "head_h": head_h if cap is not None else 0.0,
                     "drive_depth": deep if drive != "нет" and head != "нет" else 0.0,
                     "length": 0.0 if head_only else length, "tip": tip_len, "d": d,
                     "neck": neck, "thread_length": thread_len if thread else 0.0})
    return out


# --------------------------------------------------------------------------- #
#  Гвоздь
# --------------------------------------------------------------------------- #
@op("nail", aliases=("гвоздь", "гвоздик", "clout"), category="Примитивы",
    summary="Строительный гвоздь: круглая шляпка, гладкий стержень и остриё. "
            "Им прибивают заднюю стенку шкафа — головка остаётся на поверхности.",
    example="гвоздь = nail d=2 length=20 head_d=5",
    params={"d": "диаметр стержня, мм (2)", "length": "полная длина, мм (20)",
            "head_d": "диаметр шляпки, мм (2.2 × d)", "head_h": "толщина шляпки (0.4 × d)",
            "tip": "длина острия (3 × d)", "at": "положение [x,y,z]",
            "center": "центрировать в at"})
def nail(a, name):
    d = float(a.num("d", 2.0, minv=0.3, maxv=20.0))
    length = float(a.num("length", 20.0, minv=2.0, maxv=500.0))
    head_d = float(a.num("head_d", 2.2 * d, minv=1.2 * d, maxv=8 * d))
    head_h = float(a.num("head_h", 0.4 * d, minv=0.15, maxv=3 * d))
    tip = float(a.num("tip", min(3.0 * d, length * 0.4), minv=0.2, maxv=length * 0.8))
    shank_len = max(0.5, length - head_h - tip)
    shank = _cyl(shank_len, d / 2.0, 24).translate((0, 0, tip))
    point = mf.Manifold.cylinder(float(tip), float(d / 2.0), 0.12, 20)
    point = point.rotate((180, 0, 0)).translate((0, 0, tip))
    head = _cyl(head_h, head_d / 2.0, 24).translate((0, 0, length - head_h))
    solid = shank + point + head
    out = _finish(a, name, solid, "nail",
                  f"гвоздь Ø{d:g}×{length:g} мм · шляпка Ø{head_d:g}")
    out.meta.update({"nail": True, "head": "полукруг", "head_h": head_h,
                     "length": length, "d": d})
    return out


# --------------------------------------------------------------------------- #
#  Ввернуть саморез в доску
# --------------------------------------------------------------------------- #
@op("drive", aliases=("ввернуть", "вкрутить", "ввинтить", "ввернуть_шуруп"),
    category="Примитивы",
    summary="Ставит готовый саморез в доску по нормали: головка ложится на "
            "поверхность (или утапливается), стержень идёт внутрь материала. "
            "Проверяет, что остриё осталось в доске и не вылезло с другой стороны.",
    example="стенка = box size=[200,18,200] at=[0,9,160]\n"
            "саморез = screw d=3.5 length=12\n"
            "ввернуть саморез в=стенка точка=[0,0,260] направление=[0,1,0] sink=0.6",
    params={"screw": "имя самореза (или positional)",
            "into": "имя доски, в которую он входит",
            "point": "точка на поверхности доски [x,y,z]",
            "direction": "направление внутрь доски [x,y,z] (по умолчанию — от точки к центру доски)",
            "sink": "утопить головку от поверхности, мм (0)",
            "check": "проверять, что остриё осталось в доске (да)",
            "at": "положение [x,y,z]", "center": "центрировать в at"},
    positional=["screw", "into"])
def drive(a, name):
    screw_name = (a.text("screw", "") or "").strip().strip('"')
    into_name = (a.text("into", "") or "").strip().strip('"')
    if not a.extra and not screw_name:
        raise GeometryError("Укажите саморез: ввернуть саморез в=доска …")
    target = screw_name or a.extra[0]
    body_name = into_name or (a.extra[1] if len(a.extra) > 1 else "")
    screw_obj = a.scene.resolve(target)
    if not body_name:
        raise GeometryError("Укажите доску: … в=имя_доски",
                            hint="Например: ввернуть саморез в=стенка точка=[0,2,40]")
    board = a.scene.resolve(body_name)
    point = a.vec("point", 3, required=True)
    p = np.asarray(point, dtype=np.float64)
    lo = np.asarray(board.manifold.bounding_box()[:3], dtype=np.float64)
    hi = np.asarray(board.manifold.bounding_box()[3:], dtype=np.float64)
    centre = (lo + hi) / 2.0
    if a.has("direction"):
        direction = np.asarray(a.vec("direction", 3), dtype=np.float64)
    else:
        direction = centre - p
    if np.linalg.norm(direction) < 1e-6:
        raise GeometryError("Направление не определено — укажите direction.")
    direction = direction / np.linalg.norm(direction)
    sink = float(a.num("sink", 0.0, minv=0.0) or 0.0)
    bb = screw_obj.manifold.bounding_box()
    top = float(bb[5])          # верх головки в локальных координатах
    bottom = float(bb[2])       # кончик острия (после сборки — на нуле)
    info = getattr(screw_obj, "meta", {}) or {}
    head_kind = info.get("head") or "потай"
    # потайная головка ложится верхом заподлицо, остальные — опорной площадкой:
    # у них головка остаётся над поверхностью и не тонет в доске
    bearing = top if head_kind == "потай" else top - float(info.get("head_h") or 0.0)
    # голова смотрит наружу: локальная +Z → −direction
    solid = _orient_axis(screw_obj.manifold, -direction)
    # sink — насколько головка утоплена В материал: сдвигаем саморез внутрь
    origin = p + direction * (bearing - sink)
    solid = solid.translate(tuple(origin.tolist()))
    # проверка: остриё должно остаться в доске (шар 0.4 мм целиком в материале)
    tip_world = origin + direction * bottom
    probe = mf.Manifold.sphere(0.4, 10).translate(tuple(tip_world.tolist()))
    if a.boolean("check", True) and not (probe - board.manifold).is_empty():
        depth = float(np.dot(tip_world - p, direction))
        raise GeometryError(
            "Остриё самореза выходит из доски.",
            hint=f"Кончик уходит на {depth:.1f} мм от поверхности, а доска тоньше. "
                 "Уменьшите length или точку ставьте ближе к центру доски.")
    placed = make_solid(a.scene, name, solid, a, kind="drive")
    rotation = _axis_matrix(-direction)[:, :3]
    orient.set_axes(placed, rotation @ orient.axes_of(screw_obj))
    placed.notes.append(f"{target} в {body_name}: голова утоплена {sink:g} мм")
    a.scene.consume(screw_obj)
    return placed


# --------------------------------------------------------------------------- #
#  Петля
# --------------------------------------------------------------------------- #
@op("bracket", aliases=("уголок", "крепежный_уголок", "bracket"), category="Примитивы",
    summary="Крепёжный уголок с произвольным раскрытием 0…180°: 90° — "
            "привычные полки, 0° — одна плоская деталь, 180° — плоская полоса "
            "в разные стороны. Отверстия следуют за полками, round добавляет "
            "радиус шарнира, corner=заполненный закрывает наружный угол без "
            "зазора, smooth скругляет только переходные рёбра.",
    example="уголок = bracket width=60 depth=40 height=40 thickness=3 angle=90\n"
            "тупой = bracket width=60 depth=40 height=40 thickness=3 angle=135 smooth=1",
    params={"width": "ширина по X, мм (60)", "depth": "длина базовой полки (40)",
            "height": "длина поворачиваемой полки (40)", "thickness": "толщина стали (3)",
            "angle": "угол между полками 0…180° (90)",
            "holes": "отверстий на полку (0 — без отверстий)",
            "round": "радиус цилиндрического шарнира в месте сгиба, мм (0)",
            "corner": "обычный или заполненный — сплошной наружный угол без зазора",
            "smooth": "ступени скругления переходных рёбер 0…4 (0), "
                      "без Loop-стягивания широких полок",
            "at": "положение", "center": "центрировать в at"})
def bracket(a, name):
    w = float(a.num("width", 60.0, minv=5.0, maxv=600.0))
    depth = float(a.num("depth", 40.0, minv=3.0, maxv=600.0))
    height = float(a.num("height", 40.0, minv=3.0, maxv=600.0))
    t = float(a.num("thickness", 3.0, minv=0.4, maxv=30.0))
    angle = float(a.num("angle", 90.0, minv=0.0, maxv=180.0) or 0.0)
    theta = math.radians(angle)
    direction = np.array([0.0, math.cos(theta), math.sin(theta)])

    def cross_poly(points):
        pts = [(float(p[0]), float(p[1])) for p in points]
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                   - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))
        return mf.CrossSection([pts if area > 0 else pts[::-1]])

    def strip(p0, p1, thickness):
        p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        vec = p1 - p0
        normal = np.array([-vec[1], vec[0]]) / max(float(np.linalg.norm(vec)), 1e-12)
        side = normal * (thickness / 2.0)
        return cross_poly([p0 - side, p1 - side, p1 + side, p0 + side])

    # Обе полки — одно двумерное сечение, выдавленное по X. Никаких
    # совпадающих торцов и непредсказуемого Loop на стыке.
    horz = strip((0.0, 0.0), (depth, 0.0), t)
    vert = strip((0.0, 0.0), (float(direction[1]) * height,
                              float(direction[2]) * height), t)
    cross = mf.CrossSection.batch_boolean([horz, vert], mf.OpType.Add)
    corner = (a.text("corner", "обычный") or "обычный").strip().lower()
    if corner in ("заполненный", "заполнить", "сплошной", "filled", "solid"):
        filled = cross_poly([(-t / 2, -t / 2), (t / 2, -t / 2),
                             (t / 2, t / 2), (-t / 2, t / 2)])
        cross = mf.CrossSection.batch_boolean([cross, filled], mf.OpType.Add)
    elif corner not in ("обычный", "пустой", "open", "normal"):
        raise GeometryError("bracket: corner=обычный или заполненный.")
    r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if r > 0.0 and 1e-6 < angle < 180.0 - 1e-6:
        r = min(r, min(depth, height) * 0.45, t * 2.5)
        angles = np.arange(48, dtype=float) * (2.0 * math.pi / 48.0)
        hinge = cross_poly(np.column_stack([r * np.cos(angles), r * np.sin(angles)]))
        cross = mf.CrossSection.batch_boolean([cross, hinge], mf.OpType.Add)
    edge_r = transition_radius(a, min(w * 0.45, t * 0.45))
    body = rounded_extrude(cross, w, edge_r, "уголок")
    matrix = np.array([[0.0, 0.0, 1.0, -w / 2.0],
                       [1.0, 0.0, 0.0, 0.0],
                       [0.0, 1.0, 0.0, 0.0]])
    body = body.transform(matrix)
    holes = int(a.num("holes", 0, minv=0, maxv=10) or 0)
    if holes:
        rr = max(0.9, min(t * 1.2, 2.4))
        for i in range(holes):
            x = -w / 2.0 + w * (i + 1) / (holes + 1)
            body = body - _hole_z(x, depth * 0.62, -2.0 * t, 4.0 * t, rr)
            cutter = mf.Manifold.cylinder(4.0 * t, rr, rr, 32, center=True)
            cutter = cutter.rotate((angle, 0.0, 0.0))
            pos = direction * (height * 0.62)
            cutter = cutter.translate((x, float(pos[1]), float(pos[2])))
            body = body - cutter
    return _finish(a, name, body, "bracket",
                   f"уголок {angle:g}° · {w:g}×{height:g}×{depth:g} · сталь {t:g} мм")


# --------------------------------------------------------------------------- #
#  Подшипник
# --------------------------------------------------------------------------- #
@op("pulley", aliases=("шкив", "шкиф", "шкив_ручья", "pulley_wheel"),
    category="Примитивы",
    summary="Шкив с одним или несколькими симметричными ручьями. grooves "
            "задаёт число канавок, groove/groove_depth/groove_angle — ширину, "
            "глубину и угол каждой; все они повторяются в одном профиле.",
    example="шкив = pulley diameter=80 width=20 bore=10 groove=6 groove_depth=3\n"
            "двойной = pulley diameter=90 width=32 bore=12 grooves=2 groove=7 groove_depth=3",
    params={"diameter": "наружный диаметр (80)", "width": "ширина обода (20)",
            "bore": "диаметр отверстия под вал (10); 0 — сплошной шкив",
            "grooves": "число симметричных ручьёв 1…8 (1)",
            "groove": "ширина каждого ручья (6)",
            "groove_depth": "глубина каждого ручья (2.4)",
            "groove_angle": "угол раскрытия ручья, градусы (30)",
            "at": "положение", "center": "центрировать в at"})
def pulley(a, name):
    d = float(a.num("diameter", 80.0, minv=10.0, maxv=1000.0))
    width = float(a.num("width", 20.0, minv=4.0, maxv=300.0))
    bore = float(a.num("bore", 10.0, minv=0.0, maxv=d * 0.7) or 0.0)
    grooves = int(a.int("grooves", 1, minv=1, maxv=8) or 1)
    groove = float(a.num("groove", 6.0, minv=1.0, maxv=width * 0.8))
    gdepth = float(a.num("groove_depth", 2.4, minv=0.2, maxv=d * 0.25))
    gangle = float(a.num("groove_angle", 30.0, minv=5.0, maxv=90.0))
    if bore >= d * 0.75:
        raise GeometryError("Отверстие под вал слишком велико для этого диаметра.")
    R = d / 2.0
    h = width / 2.0
    half = groove / 2.0
    if R - gdepth <= bore / 2.0 + 0.5:
        raise GeometryError("groove_depth почти достигает отверстия под вал.")
    pitch = groove * 1.35
    total = groove + pitch * (grooves - 1)
    if total > width - 1.0:
        raise GeometryError(
            f"{grooves} ручьёв по {groove:g} мм не помещаются на ширине {width:g} мм.",
            hint="Увеличьте width или уменьшите groove/число grooves.")
    centers = [h + (i - (grooves - 1) / 2.0) * pitch for i in range(grooves)]
    # стенка ручья наклонена: у поверхности шире, к дну уже
    slope = math.tan(math.radians(gangle / 2.0)) * gdepth
    half_bottom = min(half * 0.8, max(0.05, half - slope))
    profile: list[tuple[float, float]] = [(bore / 2.0, 0.0), (R, 0.0)]
    for center in centers:
        profile += [(R, center - half),
                    (R - gdepth, center - half_bottom),
                    (R - gdepth, center + half_bottom),
                    (R, center + half)]
    profile += [(R, width), (bore / 2.0, width)]
    cs = mf.CrossSection([profile])
    body = mf.Manifold.revolve(cs, 96)
    return _finish(a, name, body, "pulley",
                   f"шкив Ø{d:g}×{width:g} · вал Ø{bore:g} · ручьёв {grooves}, "
                   f"{groove:g}×{gdepth:g} мм")
