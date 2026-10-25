"""Люди и вещи: волосы и мех, юбка, пиджак, экраны, зеркало.

Здесь собраны «сборные» предметы, которые вручную собираются из десятка
деталей. Каждая команда делает это сама: строит каркас, обшивает его
поверхностью, добавляет мелкие детали и в конце сваривает всё в одно тело
через `union` + `fuse` — чтобы модель не выглядела «набором примитивов».
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (circle_profile, ellipse_profile, manifold_from_arrays,
                       sweep_solid, limit_segments, FINENESS_MM)
from .ops import anchor, make_solid, op
from .ops_extra import _fuse_surface
from .ops_shape import shell_manifold
from .ops_shapes import _cross, _profile, ensure_volume


def _place(a, m: mf.Manifold) -> mf.Manifold:
    return anchor(m, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _anchor_all(a, parts: list[mf.Manifold]) -> list[mf.Manifold]:
    """Ставит сборку целиком: центр по XY и низ на z=0 считает по первому телу.

    `anchor` центрирует каждый объект отдельно, поэтому панель, стекло и
    цифры нельзя ставить поодиночке — они разъедутся. Здесь один сдвиг на всех.
    """
    at = np.asarray(a.vec("at", 3, default=(0, 0, 0)), dtype=np.float64)
    bb = parts[0].bounding_box()
    cx, cy, cz = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2
    if a.boolean("center", False):
        tx, ty, tz = at
    else:
        tx, ty, tz = at[0], at[1], at[2] + (bb[5] - bb[2]) / 2
    d = (float(tx - cx), float(ty - cy), float(tz - cz))
    return [p.translate(d) for p in parts]


def _weld(parts: list[mf.Manifold], radius: float = 1.5,
          smooth: bool = True) -> mf.Manifold:
    """Склеивает детали и сваривает стыки — модель остаётся одним объёмом.

    Сварка (`fuse`) дробит сетку под свой радиус. На сборках из десятков
    деталей это легко даёт сотни тысяч треугольников, поэтому:
      * шаг дробления берётся крупным (detail), а не radius/4;
      * если после склейки граней уже много, сварка пропускается — лучше
        честный `union`, чем съеденная память и минута ожидания.
    """
    if not parts:
        raise GeometryError("Нечего собирать: ни одной детали.")
    joined = parts[0] if len(parts) == 1 else mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if smooth and radius > 1e-6 and joined.num_tri() < 60_000:
        try:
            detail = max(2.0, float(radius) * 1.5)
            joined = _fuse_surface(joined, float(radius), 34.0, "concave", detail)
        except Exception:
            pass                    # сварка — украшение, не повод падать
    return joined


def _drop_specks(m: mf.Manifold, keep: float = 0.004) -> mf.Manifold:
    """Выбрасывает крошки: куски мельче 0.4 % объёма главного тела.

    После union из десятков деталей иногда остаются вырожденные обрывки
    (объём 0, нулевой габарит) — они ломают проверку «одно тело» и мусорят
    в списке частей.
    """
    pieces = [p for p in m.decompose() if p.volume() > 0]
    if len(pieces) <= 1:
        return m
    main = max(p.volume() for p in pieces)
    good = [p for p in pieces if p.volume() >= main * keep]
    if len(good) == len(pieces):
        return m
    return mf.Manifold.batch_boolean(good, mf.OpType.Add)


def _revolve_closed(profile_at, n_phi: int, n_u: int) -> mf.Manifold:
    """Тело по замкнутому профилю (r, z), который может зависеть от угла.

    ``profile_at(k, phi) -> (r, z)``: точка профиля номер k на угле phi.
    Профиль обходится по кругу (наружная стенка вверх, внутренняя вниз), по
    этому получается сразу полое тело без крышек и без ошибок ориентации.
    """
    phis = np.linspace(0.0, 2.0 * math.pi, n_phi, endpoint=False)
    return _revolve_closed_arrays(profile_at, phis, n_u)


def _revolve_closed_arrays(profile_at, phis: np.ndarray, n_u: int) -> mf.Manifold:
    rings = []
    for k in range(n_u):
        ring = np.empty((len(phis), 3), dtype=np.float64)
        for i, phi in enumerate(phis):
            r, z = profile_at(k, float(phi))
            ring[i] = (r * math.cos(phi), r * math.sin(phi), z)
        rings.append(ring)
    n_phi, n_k = len(phis), n_u
    verts = np.vstack(rings)
    faces = []
    for k in range(n_k):
        k2 = (k + 1) % n_k
        a0, b0 = k * n_phi, k2 * n_phi
        for j in range(n_phi):
            j2 = (j + 1) % n_phi
            faces.append((a0 + j, a0 + j2, b0 + j2))
            faces.append((a0 + j, b0 + j2, b0 + j))
    faces_arr = np.asarray(faces, dtype=np.int64)
    try:
        return manifold_from_arrays(verts, faces_arr, "тела вращения")
    except GeometryError:
        # профиль обошли в другую сторону — просто меняем ориентацию
        return manifold_from_arrays(verts, faces_arr[:, ::-1].copy(), "тела вращения")


# --------------------------------------------------------------------------- #
#  Волосы и мех
# --------------------------------------------------------------------------- #
@op("hair", aliases=("волосы", "причёска", "прическа", "чёлка", "мех", "шерсть",
                     "hair_style", "fur"),
    category="Примитивы",
    summary="Волосы из прядей-клиньев: каждая прядь — плоское веретено, "
            "проведённое по дуге от макушки вниз с сужением к кончику. "
            "style=аниме — 24 широкие пряди с чёлкой и остриями; хвост — "
            "собранные назад волосы плюс жгут; короткий — шапочка до шеи; "
            "мех — густые короткие клоки по всей сфере (кот, собака). "
            "Результат — одно тело: пряди сварены у корней.",
    example="причёска = hair length=200 style=аниме clumps=28\n"
            "кот = hair radius=70 length=16 style=мех density=160\n"
            "хвост = hair length=260 style=хвост radius=80",
    params={"radius": "радиус головы, мм (65)",
            "length": "длина волос, мм (180)",
            "style": "аниме, хвост, короткий или мех — «аниме»",
            "clumps": "число прядей (24); у меха — до 300",
            "spikes": "насколько рваные кончики 0…1 (0.5)",
            "density": "у меха: сколько клоков (120)",
            "thick": "ширина пряди в долях длины (0.22)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def hair(a, name):
    radius = float(a.num("radius", 65.0, minv=3.0))
    length = float(a.num("length", 180.0, minv=2.0))
    style = (a.text("style") or "аниме").strip().lower()
    style = {"аниме": "аниме", "anime": "аниме", "хвост": "хвост", "tail": "хвост",
             "короткий": "короткий", "short": "короткий", "мех": "мех", "fur": "мех",
             "шерсть": "мех"}.get(style)
    if style is None:
        raise GeometryError(f"Неизвестная причёска «{a.text('style')}».",
                            hint="style: аниме, хвост, короткий или мех.")
    clumps = int(a.num("clumps", 24 if style != "мех" else 120, minv=3, maxv=400))
    density = int(a.num("density", clumps, minv=3, maxv=400))
    spikes = float(a.num("spikes", 0.5, minv=0.0, maxv=1.0))
    thick_k = float(a.num("thick", 0.22 if style != "мех" else 0.30,
                          minv=0.05, maxv=0.9))
    count = density if style == "мех" else clumps
    rng = np.random.default_rng(7)
    strands: list[mf.Manifold] = []
    # шапочка-основа: пряди и клоки в неё врезаются, и модель выходит одним телом
    cap = mf.Manifold.sphere(radius * 0.985, 24)
    cap = cap - mf.Manifold.cube([radius * 3, radius * 3, radius * 2.4], True) \
        .translate((0, 0, -radius * 1.2 - radius * 0.55))
    strands.append(cap)
    crown_z = radius * 0.92

    for i in range(count):
        phi = 2.0 * math.pi * (i * 0.61803398875)        # золотое сечение: ровно
        t = (i + 0.5) / count
        if style == "мех":
            # клоки по всей сфере, торчат по нормали
            polar = math.acos(1.0 - 1.6 * t)             # верхняя часть сферы
            base = np.array([math.sin(polar) * math.cos(phi),
                             math.sin(polar) * math.sin(phi),
                             math.cos(polar)]) * radius
            out = base / max(float(np.linalg.norm(base)), 1e-9)
            ln = length * (0.65 + 0.7 * rng.random())
            tip = base + out * ln + np.array([0, 0, ln * 0.15])
            mid = base + out * ln * 0.5 + np.array([0, 0, ln * 0.05])
            w = ln * thick_k
            prof = ellipse_profile(w, w * 0.42, 8)
            path = np.stack([base - out * ln * 0.25, mid, tip])
            strands.append(sweep_solid(path, prof, what="клока",
                                       scale_curve=[1.0, 0.75, 0.12],
                                       round_caps=1.0))
            continue
        # точка на скальпе: сверху-сзади, чёлка спереди
        front = (i % 5 == 0)
        polar = math.radians(28.0 + 46.0 * rng.random()) if not front else math.radians(22.0)
        azim = (phi * 0.9) if not front else (-math.pi / 2 + (rng.random() - 0.5) * 1.5)
        base = np.array([math.sin(polar) * math.cos(azim),
                         math.sin(polar) * math.sin(azim),
                         math.cos(polar)]) * radius * 0.98
        base[2] = max(base[2], -radius * 0.15)
        out = base / max(float(np.linalg.norm(base)), 1e-9)
        drop = np.array([0.0, 0.0, -1.0])
        if style == "хвост":
            back = np.array([0.0, 1.0, 0.0])
            out = out * 0.35 + back * 0.65 + drop * 0.35
        else:
            out = out * 0.55 + drop * 0.75
        out /= max(float(np.linalg.norm(out)), 1e-9)
        ln = length * (0.75 + 0.5 * rng.random())
        side = np.cross(out, np.array([0.0, 0.0, 1.0]))
        if float(np.linalg.norm(side)) < 1e-6:
            side = np.array([1.0, 0.0, 0.0])
        side /= float(np.linalg.norm(side))
        sway = side * ln * (0.10 + 0.16 * spikes) * (rng.random() - 0.35)
        p0 = base - out * ln * 0.12
        p1 = base + out * ln * 0.45 + sway * 0.5
        p2 = base + out * ln * 1.0 + sway
        w = ln * thick_k
        prof = ellipse_profile(w, w * 0.26, 10)
        strands.append(sweep_solid(np.stack([p0, p1, p2]), prof, what="пряди",
                                   scale_curve=[1.0, 1.0, 0.06],
                                   round_caps=1.0))

    if style == "хвост":
        # жгут назад + резинка
        path = np.array([[0.0, radius * 0.75, radius * 0.45],
                         [0.0, radius * 1.25, radius * 0.15],
                         [0.0, radius * 1.55, -length * 0.35]])
        prof = ellipse_profile(radius * 0.34, radius * 0.15, 12)
        strands.append(sweep_solid(path, prof, what="хвоста",
                                   scale_curve=[0.85, 1.0, 0.25], round_caps=1.0))
    solid = _weld(strands, radius * 0.05)
    solid = _drop_specks(solid)
    solid = ensure_volume(solid, "причёски")
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    a.scene.log("info", f"волосы: {style}, {len(strands)} прядей, частей {parts}, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    if parts > 6:
        a.scene.log("warn", f"пряди не сварились: {parts} отдельных кусков — "
                            f"увеличьте thick или уменьшите length", a.cmd.line)
    return make_solid(a.scene, name, _place(a, solid), a, kind="hair")


# --------------------------------------------------------------------------- #
#  Юбка
# --------------------------------------------------------------------------- #
@op("skirt", aliases=("юбка", "плиссе", "юбка_плиссе", "skirt_pleated"),
    category="Примитивы",
    summary="Юбка телом вращения со складками: у пояса гладко, книзу складки "
            "расходятся. pleats задаёт число складок, depth — их глубину, "
            "waist и hem — обхват сверху и снизу. Толщина стенки настоящая, "
            "низ открыт — юбку можно посадить на фигуру.",
    example="юбка = skirt waist=76 hem=190 length=240 pleats=12 depth=10 thick=3\n"
            "плиссе = skirt waist=64 hem=120 length=180 pleats=32 depth=5 thick=2",
    params={"waist": "диаметр пояса, мм (70)",
            "hem": "диаметр подола, мм (180)",
            "length": "длина, мм (220)",
            "pleats": "число складок (12)",
            "depth": "глубина складки, мм (0.08 подола)",
            "thick": "толщина ткани, мм (2)",
            "flare": "насколько резко расширяется книзу 0…1 (0.35)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["waist", "hem", "length"])
def skirt(a, name):
    waist = float(a.num("waist", 70.0, minv=5.0))
    hem = float(a.num("hem", 180.0, minv=5.0))
    length = float(a.num("length", 220.0, minv=3.0))
    pleats = int(a.num("pleats", 12, minv=0, maxv=120))
    depth = float(a.num("depth", hem * 0.05, minv=0.0))
    thick = float(a.num("thick", 2.0, minv=0.2))
    flare = float(a.num("flare", 0.35, minv=0.05, maxv=1.0))
    if thick * 2 >= min(waist, hem) * 0.4:
        raise GeometryError(f"Ткань {thick:g} мм слишком толстая для пояса {waist:g} мм.",
                            hint="thick ≈ 1…4 мм.")
    if depth >= (hem - waist) * 0.5 * flare + waist * 0.3:
        raise GeometryError("Складки глубже самой юбки.", hint="depth ≤ 0.15 × hem.")
    n_phi = int(a.num("segments", 0) or 0) or max(96, pleats * 12)
    n_phi = int(max(24, min(512, n_phi)))
    n_u = max(6, int(length / 12.0))

    def outer(u: float, phi: float) -> float:
        base = (waist + (hem - waist) * (u ** (1.0 / max(flare, 0.05)))) / 2.0
        if pleats > 0:
            fade = min(1.0, (1.0 - u) ** 0.7)          # у пояса складок нет
            base = base + depth * fade * math.cos(pleats * phi)
        return max(base, thick * 1.2)

    def profile_at(k: int, phi: float):
        # 0 → пояс снаружи, дальше вниз по наружной стенке до подола,
        # затем вверх по внутренней стенке и обратно к поясу
        if k < n_u:
            u = k / (n_u - 1)
            return outer(u, phi), length * (1.0 - u)
        u = (2 * n_u - 1 - k) / (n_u - 1)
        return max(outer(u, phi) - thick, 0.4), length * (1.0 - u)

    solid = _revolve_closed(profile_at, n_phi, 2 * n_u)
    solid = ensure_volume(solid, "юбки")
    a.scene.log("info", f"юбка: {pleats} складок, {length:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, _place(a, solid), a, kind="skirt")


# --------------------------------------------------------------------------- #
#  Пиджак / смокинг
# --------------------------------------------------------------------------- #
@op("jacket", aliases=("пиджак", "смокинг", "куртка", "пальто", "jacket_suit",
                       "tuxedo"),
    category="Примитивы",
    summary="Пиджак одной деталью: торс из сечений (шея → плечи → грудь → "
            "талия → бёдра), рукава по дуге, лацканы, воротник и пуговицы. "
            "Всё сварено, поэтому силуэт читается как одежда, а не как "
            "«торс и две трубы». lapels=да — смокинг с широкими лацканами, "
            "style=смокинг делает талию уже и плечи шире.",
    example="пиджак = jacket height=740 chest=1040 waist=920\n"
            "смокинг = jacket height=760 chest=1060 style=смокинг buttons=2",
    params={"height": "длина от плеча до низа, мм (740)",
            "chest": "обхват груди, мм (104)",
            "waist": "обхват талии, мм (92)",
            "hips": "обхват бёдер, мм (100)",
            "shoulders": "полуобхват плеч, мм (46)",
            "sleeves": "делать рукава (да)",
            "lapels": "лацканы и воротник (да)",
            "buttons": "число пуговиц 0…4 (2)",
            "depth": "толщина тела под одеждой, мм (24)",
            "style": "классика или смокинг — «классика»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["height", "chest"])
def jacket(a, name):
    height = float(a.num("height", 740.0, minv=50.0))
    # Обхваты в миллиметрах, как на бирке: 104 см груди — это 46-й размер.
    # Полуобхват считается из периметра эллипса (C ≈ π(a + b), b = ratio·a),
    # поэтому пиджак не выходит вдвое уже настоящего.
    chest = float(a.num("chest", height * 1.36, minv=100.0))
    waist = float(a.num("waist", chest * 0.88, minv=100.0))
    hips = float(a.num("hips", chest * 0.98, minv=100.0))
    shoulders = float(a.num("shoulders", chest * 0.44, minv=40.0))   # ширина плеч
    ratio = float(a.num("depth", 0.62, minv=0.35, maxv=1.0))         # глубина/ширина
    style = (a.text("style") or "классика").strip().lower()
    tuxedo = style in ("смокинг", "tuxedo", "фрак")
    if tuxedo:
        waist *= 0.94
        shoulders *= 1.04

    def half(girth: float) -> tuple[float, float]:
        """Обхват → (полуширина, полуглубина) эллипса того же периметра."""
        rx = girth / (math.pi * (1.0 + ratio))
        return rx, rx * ratio

    if chest <= waist * 1.02:
        a.scene.log("info", "пиджак: талия не уже груди — силуэт будет прямым",
                    a.cmd.line)

    r_hip, d_hip = half(hips)
    r_waist, d_waist = half(waist)
    r_chest, d_chest = half(chest)
    r_shoulder = max(r_chest * 1.04, shoulders / 2.0)
    # профиль по высоте: (доля высоты, полуширина, полуглубина)
    profile = [
        (0.00, r_hip * 1.05, d_hip * 1.07),
        (0.30, r_hip, d_hip),
        (0.55, r_waist, d_waist),
        (0.78, r_chest, d_chest),
        (0.92, r_shoulder, d_chest * 0.94),
        (1.00, r_shoulder * 0.60, d_chest * 0.55),
    ]
    n_phi = 72
    phis = np.linspace(0.0, 2.0 * math.pi, n_phi, endpoint=False)
    rings = []
    for u, rx, ry in profile:
        z = height * u
        py = ry * np.sin(phis)
        py = np.where(py > 0, py * 0.88, py)      # спина площе груди
        rings.append(np.stack([rx * np.cos(phis), py, np.full(n_phi, z)], axis=1))
    verts = np.vstack(rings)
    faces: list[tuple[int, int, int]] = []
    for k in range(len(rings) - 1):
        a0, b0 = k * n_phi, (k + 1) * n_phi
        for j in range(n_phi):
            j2 = (j + 1) % n_phi
            faces.append((a0 + j, a0 + j2, b0 + j2))
            faces.append((a0 + j, b0 + j2, b0 + j))
    bot = len(verts)
    verts = np.vstack([verts, np.array([[0.0, 0.0, 0.0]])])
    top = len(verts)
    verts = np.vstack([verts, np.array([[0.0, 0.0, height * 0.995]])])
    for j in range(n_phi):
        j2 = (j + 1) % n_phi
        faces.append((bot, j2, j))
        base_top = (len(rings) - 1) * n_phi
        faces.append((top, base_top + j, base_top + j2))
    torso = manifold_from_arrays(verts, np.asarray(faces, dtype=np.int64), "торса")
    torso = shell_manifold(torso, max(2.0, height * 0.005), "top")
    parts = [torso]

    # рукава: от плеча вниз по дуге, первый узел — глубоко в торсе,
    # иначе рукав «висит» отдельной трубой рядом с пиджаком
    if a.boolean("sleeves", True):
        r0 = max(5.0, r_chest * 0.21)
        for side in (-1, 1):
            path = np.array([[side * (r_shoulder - r0 * 1.15), 0.0, height * 0.87],
                             [side * (r_shoulder + r0 * 0.02), 0.0, height * 0.76],
                             [side * (r_shoulder - r0 * 0.02), 0.0, height * 0.52],
                             [side * (r_shoulder - r0 * 0.30), 0.0, height * 0.30]])
            parts.append(sweep_solid(path, circle_profile(r0, 20), what="рукава",
                                     scale_curve=[1.0, 0.94, 0.84, 0.7],
                                     round_caps=0.2))
            cuff = mf.Manifold.cylinder(height * 0.006, r0 * 0.8, r0 * 0.8, 24, True)
            cuff = cuff.translate((side * (r_shoulder - r0 * 0.30), 0.0, height * 0.30))
            parts.append(cuff)

    # лацканы: плоские полосы от шеи к груди, врезаны в грудь
    if a.boolean("lapels", True):
        for side in (-1, 1):
            path = np.array([[side * r_shoulder * 0.34, -d_chest * 0.92, height * 0.96],
                             [side * r_shoulder * 0.62, -d_chest * 1.02, height * 0.80],
                             [side * r_shoulder * 0.46, -d_chest * 0.98, height * 0.62]])
            prof = ellipse_profile(r_chest * 0.16, max(1.6, height * 0.005), 10)
            parts.append(sweep_solid(path, prof, what="лацкана",
                                     scale_curve=[0.5, 1.0, 0.5], round_caps=1.0))
        collar = mf.Manifold.cube([r_shoulder * 0.92, d_chest * 1.02, height * 0.012], True)
        collar = collar.translate((0.0, d_chest * 0.10, height * 0.965))
        parts.append(collar)

    # пуговицы — врезаны в грудь, чтобы не висели отдельными шариками
    count = int(a.num("buttons", 2, minv=0, maxv=4))
    for i in range(count):
        z = height * (0.62 - 0.07 * i)
        rr = max(1.2, r_chest * 0.055)
        btn = mf.Manifold.cylinder(rr * 0.7, rr, rr, 16, True)
        btn = btn.translate((0.0, -d_chest * 0.96, z))
        parts.append(btn)

    joined = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    try:
        joined = joined.set_tolerance(max(0.8, height * 0.002))
    except Exception:
        pass
    pieces = [p for p in joined.decompose() if p.volume() > 0]
    if len(pieces) > 1:
        main = max(p.volume() for p in pieces)
        keep = [p for p in pieces if p.volume() >= main * 0.02]
        joined = mf.Manifold.batch_boolean(keep, mf.OpType.Add)
    solid = ensure_volume(joined, "пиджака")
    parts_n = len([p for p in solid.decompose() if p.volume() > 0])
    a.scene.log("info", f"пиджак: грудь {chest:g} мм, плечи {shoulders:g} мм, "
                        f"частей {parts_n}, {solid.num_tri():,} трис".replace(",", " "),
                a.cmd.line)
    return make_solid(a.scene, name, _place(a, solid), a, kind="jacket")


# --------------------------------------------------------------------------- #
#  Экран: смартфон, будильник, монитор
# --------------------------------------------------------------------------- #
def _extra(a, base_name: str, suffix: str, m: mf.Manifold, kind: str, *,
           color: str, metal: float = 0.0, rough: float = 0.5,
           emissive: str = "", glow: float = 1.0, transmission: float = 0.0):
    """Добавляет в сцену доп. объект с собственным материалом.

    Корпус и «начинка» экрана — разные материалы (пластик, стекло,
    светодиоды), поэтому команда делает не одно тело, а корпус + панель
    + стекло. Корпус при этом всегда один замкнутый объём.
    """
    from .model import Solid
    solid = Solid(name=f"{base_name}.{suffix}", manifold=m, color=color, metal=metal,
                  rough=rough, emissive=emissive, emissive_strength=glow,
                  transmission=transmission, kind=kind, op=a.spec.name,
                  line=a.cmd.line)
    return a.scene.add(solid)


@op("display", aliases=("экран", "смартфон", "телефон", "монитор", "дисплей",
                        "phone", "screen_device"),
    category="Примитивы",
    summary="Устройство с экраном целиком: корпус, ниша, светящаяся панель, "
            "стекло и кнопки. style=смартфон — скруглённый корпус с камерой; "
            "будильник — «мыльница» с верхней кнопкой и подставкой; монитор — "
            "тонкая панель на ножке. content=led ставит на панель горящие "
            "семисегментные цифры, content=ui — полоски интерфейса. "
            "Стекло прозрачное (transmission), панель — material=screen.",
    example='телефон = display width=71 height=147 thick=8 style=смартфон\n'
            'часы = display width=180 height=90 thick=46 style=будильник content=led '
            'text="21:38"\n'
            'монитор = display width=520 height=320 thick=26 style=монитор',
    params={"width": "ширина, мм (71)",
            "height": "высота, мм (147)",
            "thick": "толщина корпуса, мм (8)",
            "style": "смартфон, будильник или монитор — «смартфон»",
            "content": "led, ui или пусто — панель без рисунка (пусто)",
            "text": "что показать на LED-панели (21:38)",
            "bezel": "ширина рамки вокруг экрана, мм (авто)",
            "glass": "делать стекло поверх панели (да)",
            "stand": "подставка: да/нет (да у будильника и монитора)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["width", "height"])
def display(a, name):
    width = float(a.num("width", 71.0, minv=6.0))
    height = float(a.num("height", 147.0, minv=6.0))
    thick = float(a.num("thick", 8.0, minv=1.0))
    style = (a.text("style") or "смартфон").strip().lower()
    style = {"смартфон": "смартфон", "телефон": "смартфон", "phone": "смартфон",
             "будильник": "будильник", "часы": "будильник", "clock": "будильник",
             "монитор": "монитор", "monitor": "монитор"}.get(style)
    if style is None:
        raise GeometryError(f"Неизвестный вид экрана «{a.text('style')}».",
                            hint="style: смартфон, будильник или монитор.")
    content = (a.text("content") or "").strip().lower()
    if content in ("", "нет", "no"):
        content = ""
    if content not in ("", "led", "ui"):
        raise GeometryError("content: led, ui или пусто.")
    text = a.text("text") or "21:38"
    bezel = float(a.num("bezel", max(3.0, min(width, height) * 0.05), minv=0.5))
    do_glass = a.boolean("glass", True)
    # смартфон лежит экраном вверх, часы и монитор стоят на подставке
    upright = style != "смартфон"
    stand = a.boolean("stand", upright)
    if bezel * 2 >= min(width, height) * 0.8:
        raise GeometryError(f"Рамка {bezel:g} мм не оставляет места экрану.",
                            hint="bezel ≈ 3–8 % от меньшей стороны.")

    # Строим «плоско»: X — ширина, Y — высота, Z — толщина, экран смотрит в +Z.
    # Потом, если нужно, поворачиваем на 90° вокруг X (экран смотрит в −Y).
    body_r = min(3.0 + thick * 0.5, min(width, height) * 0.12)
    if style == "смартфон":
        pts = [(-width / 2 + body_r, -height / 2), (width / 2 - body_r, -height / 2),
               (width / 2, -height / 2 + body_r), (width / 2, height / 2 - body_r),
               (width / 2 - body_r, height / 2), (-width / 2 + body_r, height / 2),
               (-width / 2, height / 2 - body_r), (-width / 2, -height / 2 + body_r)]
    else:
        pts = [(-width / 2, -height / 2), (width / 2, -height / 2),
               (width / 2, height / 2), (-width / 2, height / 2)]
    body = _cross(pts).offset(-body_r, mf.JoinType.Round, 2.0, 16) \
                       .offset(body_r, mf.JoinType.Round, 2.0, 16)
    inset = body.offset(-bezel, mf.JoinType.Round, 2.0, 16)
    if inset.is_empty() or inset.area() <= 1e-6:
        raise GeometryError("Рамка съела весь экран.", hint="Уменьшите bezel.")

    # Ниша под экран — мелкая: панель стоит почти заподлицо со стеклом.
    # Раньше она уходила на 90 % толщины, и у толстых корпусов цифры прятались
    # на дне глубокого колодца: стенки срезали их по краям.
    panel_depth = max(0.8, thick * 0.09)
    glass_h = max(0.6, thick * 0.07)
    gap = max(0.35, thick * 0.03)
    floor = max(0.6, thick - (panel_depth + glass_h + gap))
    if floor < thick * 0.45:      # очень толстый корпус: глубже четверти не копаем
        floor = max(thick * 0.45, panel_depth + glass_h + gap)
    case = body.extrude(thick)
    case = case - inset.extrude(thick - floor + 0.05).translate((0, 0, floor))
    case_parts = [case]
    if style == "смартфон":
        # объектив — в верхней рамке, а не над нишей экрана (иначе висит отдельно)
        cam = mf.Manifold.cylinder(0.9, width * 0.035, width * 0.035, 24, True)
        case_parts.append(cam.translate((0.0, height / 2 - bezel * 0.55, thick - 0.35)))
        btn = mf.Manifold.cube([1.6, width * 0.10, 2.2], True)
        case_parts.append(btn.translate((width / 2 - 0.4, height * 0.05, thick * 0.5)))
    elif style == "будильник":
        top_btn = mf.Manifold.cube([width * 0.34, thick * 0.5, 3.0], True)
        case_parts.append(top_btn.translate((0.0, height / 2 + 1.0, thick * 0.5)))
    body_m = mf.Manifold.batch_boolean(case_parts, mf.OpType.Add)

    panel = inset.extrude(panel_depth).translate((0, 0, floor))
    if content == "ui":
        bb = inset.bounds()
        bars = []
        for i in range(4):
            w = (bb[2] - bb[0]) * (0.55 if i % 2 else 0.72)
            hh = max(1.0, (bb[3] - bb[1]) * 0.055)
            y = bb[1] + (bb[3] - bb[1]) * (0.30 + 0.16 * i)
            bars.append(mf.Manifold.cube([w, hh, 0.6], True).translate(
                ((bb[0] + bb[2]) / 2.0, y, floor + panel_depth - 0.2)))
        panel = mf.Manifold.batch_boolean([panel] + bars, mf.OpType.Add)
    digits = None
    if content == "led":
        digits_h = min(inset.bounds()[3] - inset.bounds()[1],
                       inset.bounds()[2] - inset.bounds()[0]) * 0.52
        digits = _seven_scene(text, digits_h,
                              min(inset.bounds()[2] - inset.bounds()[0], width))
        if digits is not None and not digits.is_empty():
            digits = digits.translate((0.0, 0.0, floor + panel_depth - 0.1))
        else:
            digits = None
    glass = None
    if do_glass:
        g = inset.offset(-max(0.3, bezel * 0.06), mf.JoinType.Round, 1.0, 8)
        if not g.is_empty():
            glass = g.extrude(glass_h).translate((0, 0, thick - glass_h - 0.2))

    # поворот в вертикальное положение: экран смотрит в −Y, высота идёт по Z
    def place(m):
        if m is None:
            return None
        if upright:
            m = m.rotate((90.0, 0.0, 0.0)).translate((0.0, 0.0, height / 2.0))
        return m

    body_m = place(body_m)
    if stand and upright:
        # подставка в мировых координатах: нога на полу, сзади корпуса
        foot_h = max(6.0, height * 0.03)
        foot_deep = min(max(24.0, thick * 0.9), height * 0.3)
        foot = mf.Manifold.cube([width * 0.46, foot_deep, foot_h], True)
        # нога стоит под корпусом и чуть заходит назад: не «полка» позади
        foot = foot.translate((0.0, foot_deep * 0.18, foot_h / 2.0))
        body_m = mf.Manifold.batch_boolean([body_m, foot], mf.OpType.Add)
    try:
        body_m = body_m.set_tolerance(max(0.12, thick * 0.015))
    except Exception:
        pass
    body_m = ensure_volume(body_m, "корпуса")
    panel = ensure_volume(place(panel), "панели")
    extras = [panel]
    if digits is not None:
        digits = ensure_volume(place(digits), "цифр")
        extras.append(digits)
    if glass is not None:
        glass = ensure_volume(place(glass), "стекла")
        extras.append(glass)
    placed = _anchor_all(a, [body_m] + extras)
    main = make_solid(a.scene, name, placed[0], a, kind="display")
    base = main.name
    _extra(a, base, "экран", placed[1], "panel", color="#11151b", metal=0.0, rough=0.22)
    k = 2
    if digits is not None:
        _extra(a, base, "цифры", placed[k], "digits", color="#ff3b30",
               metal=0.0, rough=0.35, emissive="#ff2d20", glow=2.2)
        k += 1
    if glass is not None:
        _extra(a, base, "стекло", placed[k], "glass", color="#cfe6ef",
               metal=0.0, rough=0.03, transmission=0.82)

    a.scene.log("info", f"экран: {style} {width:g}×{height:g}, content={content or 'нет'}, "
                        f"{body_m.num_tri():,} трис корпуса".replace(",", " "),
                a.cmd.line)
    return main


def _seven_scene(text: str, size: float, max_width: float):
    """Цифры для панели: собираем seven_seg напрямую, без сцены."""
    from .ops_shapes import seven_seg
    h = size
    w, t = h * 0.58, h * 0.15
    gap = h * 0.32

    def char_w(ch: str) -> float:
        return w * 0.34 if ch == ":" else (w * 0.45 if ch == " " else w)

    total = sum(char_w(c) for c in text) + gap * max(0, len(text) - 1)
    if total > max_width * 0.92:
        k = max_width * 0.92 / total
        h, w, t, gap = h * k, w * k, t * k, gap * k

    class _FakeArgs:
        def __init__(self):
            self.scene = _NullScene()
            self.cmd = type("C", (), {"line": 0, "text": ""})()
            self.spec = type("S", (), {"name": "seven_seg"})()

        def style(self):
            return {}

        def text(self, key, default=None, choices=None):
            return text if key == "text" else default

        def num(self, key, default=None, required=False, minv=None, maxv=None):
            table = {"height": h, "width": w, "thick": t, "gap": gap,
                     "depth": 0.9, "slant": 0.0}
            return table.get(key, default)

        def boolean(self, key, default=False):
            return default

        def vec(self, key, dims=3, default=None, required=False):
            return default

        def has(self, key):
            return False

    class _NullScene:
        def log(self, *args, **kwargs):
            pass

        def next_color(self):
            return "#c9d1e3"

        def consume(self, *args, **kwargs):
            pass

        def add(self, solid):
            return solid

        def auto_name(self, kind):
            return kind

    solid = seven_seg(_FakeArgs(), "цифры")
    return solid.manifold if hasattr(solid, "manifold") else solid


# --------------------------------------------------------------------------- #
#  Зеркало
# --------------------------------------------------------------------------- #
@op("mirror_plate", aliases=("зеркало", "зеркальная_плита", "mirror_glass"),
    category="Примитивы",
    summary="Зеркало целиком: рама, отражающая пластина и задник с креплением. "
            "Пластина получает материал mirror (metal=1, rough=0.02) и "
            "отражает соседние детали — и в окне, и на PNG-снимке. Форма "
            "рамы — прямоугольная, круглая или овальная.",
    example="зеркало = mirror_plate width=600 height=900 frame=40\n"
            "круглое = mirror_plate width=500 height=500 shape=круг frame=30",
    params={"width": "ширина, мм (600)", "height": "высота, мм (900)",
            "frame": "ширина рамы, мм (35)",
            "depth": "толщина, мм (24)",
            "shape": "прямоуг, круг или овал — «прямоуг»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["width", "height"])
def mirror_plate(a, name):
    width = float(a.num("width", 600.0, minv=20.0))
    height = float(a.num("height", 900.0, minv=20.0))
    frame = float(a.num("frame", 35.0, minv=2.0))
    depth = float(a.num("depth", 24.0, minv=3.0))
    shape = (a.text("shape") or "прямоуг").strip().lower()
    if shape in ("круг", "круглое", "round"):
        shape = "круг"
    elif shape in ("овал", "ellipse", "овальное"):
        shape = "овал"
    else:
        shape = "прямоуг"
    if frame * 2 >= min(width, height) * 0.8:
        raise GeometryError("Рама съела всё зеркало.",
                            hint="frame ≤ 0.3 × меньшей стороны.")
    if shape == "круг":
        d = min(width, height)
        outer_prof = ellipse_profile(d, d, 96)
        inner_prof = ellipse_profile(d - 2 * frame, d - 2 * frame, 96)
    elif shape == "овал":
        outer_prof = ellipse_profile(width, height, 96)
        inner_prof = ellipse_profile(width - 2 * frame, height - 2 * frame, 96)
    else:
        outer_prof = np.array([(-width / 2, -height / 2), (width / 2, -height / 2),
                               (width / 2, height / 2), (-width / 2, height / 2)])
        inner_prof = np.array([(-width / 2 + frame, -height / 2 + frame),
                               (width / 2 - frame, -height / 2 + frame),
                               (width / 2 - frame, height / 2 - frame),
                               (-width / 2 + frame, height / 2 - frame)])
    outer = _cross([tuple(p) for p in outer_prof])
    inner = _cross([tuple(p) for p in inner_prof])

    rim = outer.extrude(depth) - inner.extrude(depth * 1.2).translate((0, 0, -depth * 0.1))
    # задник и подвес — с перекрытием, чтобы union дал одно тело
    back = outer.extrude(depth * 0.12)
    hanger = mf.Manifold.cube([min(60.0, width * 0.2), 8.0, depth * 0.7], True).translate(
        (0.0, height * 0.32, depth * 0.05))
    body = mf.Manifold.batch_boolean([rim, back, hanger], mf.OpType.Add)
    try:
        body = body.set_tolerance(max(0.2, depth * 0.02))
    except Exception:
        pass
    body = ensure_volume(body, "рамы зеркала")
    # отражающая пластина — отдельный материал (metal=1, rough≈0)
    plate = inner.offset(0.6, mf.JoinType.Round, 1.0, 8).extrude(max(1.2, depth * 0.08))
    plate = plate.translate((0, 0, depth * 0.55))
    plate = ensure_volume(plate, "зеркальной пластины")
    placed = _anchor_all(a, [body, plate])
    main = make_solid(a.scene, name, placed[0], a, kind="mirror_plate")
    _extra(a, main.name, "зеркало", placed[1], "mirror",
           color="#e8f1fb", metal=1.0, rough=0.02)
    a.scene.log("info", f"зеркало: {width:g}×{height:g} мм, рама {frame:g} мм, "
                        f"{body.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return main


