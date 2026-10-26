"""Лист, рулон, оригами-сгиб и гофрирование.

Плоскость здесь — не «висячий» полигон без объёма, а **очень тонкий
параллелепипед**: у листа есть толщина, замкнутый объём, его можно печатать,
склеивать и складывать с другими телами. Из этого же кирпича собраны
волнистый лист, свёрнутый в рулон, гофрокартон и двумерные узоры (вафля,
рифление).

Все деформации — это отображение вершин без изменения связей:
* лист и рулон строятся сразу как «толстая поверхность» (две сетки по
  нормали и борта между ними), поэтому поверхность не пересекает саму себя;
* сгиб — изометрическое отображение вдоль оси: длина листа сохраняется,
  а место сгиба проходится дугой радиуса из зазора `gap`;
* гофрирование — смещение по одной оси как функция от двух других, то есть
  график поверхности: он не может сам себя проткнуть, пока не разорвётся.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import anchor, make_solid, op
from .ops_extra import _derived, _one
from .ops_form import _closed

MAX_CELLS = 240          # узлов по одной стороне сетки листа
MAX_TRIS = 900_000


# --------------------------------------------------------------------------- #
#  «Толстая поверхность»: две сетки по нормали + борта
# --------------------------------------------------------------------------- #

def _thick_surface(point, nu: int, nv: int, thickness: float,
                   what: str) -> mf.Manifold:
    """Замкнутое тело толщиной ``thickness`` вокруг параметрической поверхности.

    ``point(s, t)`` получает массивы s, t ∈ [0,1] и возвращает мировые точки.
    Смещение — по нормали поверхности, поэтому толщина остаётся постоянной
    даже на волнах. Края сшиваются бортами: открытых полигонов не остаётся.
    """
    nu = max(2, int(nu))
    nv = max(2, int(nv))
    s = np.linspace(0.0, 1.0, nu + 1)
    t = np.linspace(0.0, 1.0, nv + 1)
    S, T = np.meshgrid(s, t, indexing="ij")
    P = np.asarray(point(S, T), dtype=np.float64)
    if P.shape != (nu + 1, nv + 1, 3):
        raise GeometryError(f"Не удалось разложить поверхность {what}.",
                            hint="Проверьте размеры листа: они должны быть больше нуля.")

    ds = np.gradient(P, axis=0)
    dt = np.gradient(P, axis=1)
    N = np.cross(ds, dt)
    norm = np.linalg.norm(N, axis=2, keepdims=True)
    if float(np.min(norm)) < 1e-9:
        raise GeometryError(f"Поверхность {what} вырождена.",
                            hint="Увеличьте толщину или уменьшите амплитуду волн.")
    N = N / norm
    half = thickness / 2.0
    top = P + N * half
    bottom = P - N * half

    w = nv + 1
    verts = np.concatenate([top.reshape(-1, 3), bottom.reshape(-1, 3)], axis=0)
    off = (nu + 1) * w
    faces: list[tuple[int, int, int]] = []

    # верх и низ — одна и та же сетка с противоположным обходом
    for i in range(nu):
        for j in range(nv):
            a = i * w + j
            b = (i + 1) * w + j
            c = (i + 1) * w + j + 1
            d = i * w + j + 1
            faces.append((a, b, c))
            faces.append((a, c, d))
            faces.append((off + a, off + c, off + b))
            faces.append((off + a, off + d, off + c))

    def wall(quad, outward) -> None:
        """Борт по четырём углам в порядке обхода: верх j, верх j+1, низ j+1, низ j."""
        p0, p1, q1, q0 = quad
        n = np.cross(verts[p1] - verts[p0], verts[q1] - verts[p0])
        if float(np.dot(n, outward)) < 0:
            faces.append((p0, q1, p1))
            faces.append((p0, q0, q1))
        else:
            faces.append((p0, p1, q1))
            faces.append((p0, q1, q0))

    # наружу смотрит сторона, противоположная росту параметра
    for j in range(nv):
        out = -(P[1, j] - P[0, j])
        wall((0 * w + j, 0 * w + j + 1,
              off + 0 * w + j + 1, off + 0 * w + j), out)
        out = P[nu, j] - P[nu - 1, j]
        wall((nu * w + j, nu * w + j + 1,
              off + nu * w + j + 1, off + nu * w + j), out)
    for i in range(nu):
        out = -(P[i, 1] - P[i, 0])
        wall((i * w, (i + 1) * w,
              off + (i + 1) * w, off + i * w), out)
        out = P[i, nv] - P[i, nv - 1]
        wall((i * w + nv, (i + 1) * w + nv,
              off + (i + 1) * w + nv, off + i * w + nv), out)

    solid = _closed(verts, np.asarray(faces, dtype=np.int64), what)
    if solid.volume() <= 1e-9:
        raise GeometryError(f"{what.capitalize()} получилась без объёма.",
                            hint="Увеличьте толщину листа.")
    return solid


# --------------------------------------------------------------------------- #
#  Лист: плоский, волнистый, свёрнутый в рулон
# --------------------------------------------------------------------------- #

_WAVE_DIRS = {
    "вдоль": "вдоль", "along": "вдоль", "length": "вдоль",
    "поперёк": "поперёк", "поперек": "поперёк", "across": "поперёк",
    "крест": "крест", "cross": "крест", "вафля": "крест", "waffle": "крест",
}


def _spiral(r0: float, gap: float, theta: float) -> tuple[np.ndarray, np.ndarray]:
    """Точки центральной линии архимедовой спирали и длина дуги по θ."""
    b = gap / (2.0 * math.pi)
    r = r0 + b * theta
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    return np.stack([x, y], axis=-1), r


def _solve_roll(length: float, gap: float, turns: float) -> tuple[float, np.ndarray, np.ndarray]:
    """Подбирает начальный радиус так, чтобы длина дуги спирали была ровно ``length``.

    Пользователь задаёт и длину листа, и число оборотов — они связаны: рулон
    не может быть длиннее листа. Если листа не хватает на витки, честно
    говорим, сколько нужно.
    """
    theta_max = 2.0 * math.pi * turns
    th = np.linspace(0.0, theta_max, 4001)
    b = gap / (2.0 * math.pi)
    # длина дуги dS/dθ = √(r² + b²), считаем через накопленную сумму
    def arc(r0: float) -> float:
        r = r0 + b * th
        return float(np.sum(np.sqrt(r * r + b * b)) * (th[1] - th[0]))

    lo, hi = 1e-3, max(length, 1.0)
    if arc(lo) > length:
        need = arc(lo)
        raise GeometryError(
            f"На {turns:g} оборота нужен лист длиной не меньше {need:.0f} мм, "
            f"а задано {length:.0f} мм.",
            hint="Уменьшите roll (обороты) или увеличьте length.")
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if arc(mid) < length:
            lo = mid
        else:
            hi = mid
    r0 = (lo + hi) / 2.0
    r = r0 + b * th
    seg = np.sqrt(r * r + b * b)
    cum = np.concatenate([[0.0], np.cumsum((seg[1:] + seg[:-1]) * 0.5 * (th[1] - th[0]))])
    cum /= max(cum[-1], 1e-9)
    return r0, th, cum


@op("sheet", aliases=("плоскость", "лист", "плоскость_лист", "sheet", "plane",
                      "panel", "пластина_лист"),
    category="Примитивы",
    summary="Плоскость — тонкий параллелепипед (лист бумаги, металла, картона), "
            "а не полигон без толщины: объём замкнут, деталь печатается и "
            "склеивается. Умеет волнистость (шаг и амплитуда, вдоль/поперёк/"
            "крестом) и свёртку в рулон: лист наматывается спиралью с зазором "
            "между витками, поэтому поверхность не пересекает саму себя.",
    example="лист = sheet width=160 length=240 thickness=1.2\n"
            "волна = sheet width=160 length=300 thickness=0.8 step=24 amp=6\n"
            "рулон = sheet width=120 length=600 thickness=0.6 roll=6 gap=1.4",
    params={"width": "ширина, мм (120)",
            "length": "длина листа, мм (200)",
            "thickness": "толщина, мм (1.2): лист — тонкий параллелепипед",
            "step": "шаг волны, мм; 0 — гладкий лист (0)",
            "amp": "амплитуда волны, мм (0)",
            "wave": "направление волны: вдоль, поперёк или крест («вдоль»)",
            "roll": "оборотов рулона, 0 — плоский лист (0)",
            "gap": "зазор между витками рулона, мм (толщина × 1.4)",
            "segments": "плотность сетки, узлов по стороне (авто)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def sheet(a, name):
    width = float(a.num("width", 120.0, minv=0.5, maxv=5000.0))
    length = float(a.num("length", 200.0, minv=0.5, maxv=8000.0))
    thickness = float(a.num("thickness", 1.2, minv=0.2, maxv=80.0))
    step = float(a.num("step", 0.0, minv=0.0, maxv=1000.0))
    amp = float(a.num("amp", 0.0, minv=0.0, maxv=300.0))
    wave_raw = (a.text("wave") or "вдоль").strip().lower()
    wave = _WAVE_DIRS.get(wave_raw)
    if wave is None:
        raise GeometryError(f"Неизвестное направление волны «{a.text('wave')}».",
                            hint="wave: вдоль, поперёк или крест.")
    roll = float(a.num("roll", 0.0, minv=0.0, maxv=60.0))
    gap = float(a.num("gap", max(thickness * 1.4, 0.5), minv=0.0, maxv=400.0))
    segments = int(a.num("segments", 0, minv=0, maxv=MAX_CELLS))
    if step > 0.0 and amp * 2.0 > length:
        raise GeometryError(
            f"Волна амплитудой {amp:g} мм не помещается на листе длиной {length:g} мм.",
            hint="Уменьшите amp или увеличьте length.")

    if roll > 0.0:
        if gap < thickness * 1.02:
            raise GeometryError(
                f"Зазор между витками {gap:g} мм меньше толщины листа {thickness:g} мм: "
                "витки проткнули бы друг друга.",
                hint="gap больше толщины (обычно в 1.2…2 раза).")
        if amp > 0.0:
            raise GeometryError(
                "Свёрнутый лист гладкий: волнистость задаётся до свёртки.",
                hint="Сначала сделайте волнистый лист (roll=0), а рулон — отдельной деталью.")
        r0, th, cum = _solve_roll(length, gap, roll)

        def point(s, t):
            si = np.clip(s, 0.0, 1.0)
            ti = np.clip(t, 0.0, 1.0)
            theta = np.interp(si, cum, th)
            b = gap / (2.0 * math.pi)
            r = r0 + b * theta
            y = (ti - 0.5) * width
            return np.stack([r * np.cos(theta), np.full_like(theta, 0.0) + y,
                             r * np.sin(theta)], axis=-1)

        nu = segments or int(np.clip(max(220, length / max(gap, 0.4) * 2.0), 24, MAX_CELLS))
        nv = max(6, min(64, int(width / 8) + 4))
        solid = _thick_surface(point, nu, nv, thickness, "рулон")
        # рулон лежит на боку: ось вдоль Y, поднимаем его на «пол»
        bb = solid.bounding_box()
        solid = solid.translate((0.0, 0.0, -bb[2]))
        solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
        a.scene.log("info", f"рулон: {roll:g} оборота, лист {length:g} мм, "
                            f"зазор {gap:g} мм, {solid.num_tri():,} трис".replace(",", " "),
                    a.cmd.line)
        return make_solid(a.scene, name, solid, a, kind="sheet")

    # Сетку ведём кратной волнам: тогда гребень попадает ровно в узел и
    # заявленная амплитуда не «срезается» выборкой.
    waves_u = (length / step) if (step > 0 and amp > 0 and wave in ("вдоль", "крест")) else 0.0
    waves_v = (width / step) if (step > 0 and amp > 0 and wave in ("поперёк", "крест")) else 0.0
    per = 16
    if waves_u * per * waves_v * per > 90_000:
        per = 10
    if segments:
        nu = nv = segments
    else:
        nu = int(np.clip(round(waves_u * per) if waves_u else length / 24.0, 6, MAX_CELLS))
        nv = int(np.clip(round(waves_v * per) if waves_v else width / 24.0, 6, MAX_CELLS))

    def point(s, t):
        x = (s - 0.5) * length
        y = (t - 0.5) * width
        z = np.zeros_like(x)
        if step > 0.0 and amp > 0.0:
            k = 2.0 * math.pi / step
            if wave == "вдоль":
                z = amp * np.sin(k * x)
            elif wave == "поперёк":
                z = amp * np.sin(k * y)
            else:
                z = amp * np.sin(k * x) * np.sin(k * y)
        return np.stack([x, y, z], axis=-1)

    solid = _thick_surface(point, nu, nv, thickness, "лист")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    a.scene.log("info", f"лист {length:g}×{width:g}×{thickness:g} мм"
                        + (f", волна {step:g}/{amp:g}" if amp > 0 and step > 0 else "")
                        + f", {solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="sheet")


# --------------------------------------------------------------------------- #
#  Сгибаемый лист: одиночный сгиб и гармошка в любом направлении
# --------------------------------------------------------------------------- #

def _fold_joint(a) -> str:
    raw = (a.text("joint", "круг") or "круг").strip().lower()
    value = {"круг": "круг", "дуга": "круг", "round": "круг",
             "широкая": "широкая", "широкий": "широкая", "wide": "широкая",
             "сплайн": "сплайн", "плавный": "сплайн", "spline": "сплайн",
             "фаска": "фаска", "chamfer": "фаска"}.get(raw)
    if value is None:
        raise GeometryError("joint: круг, широкая, сплайн или фаска.")
    return value


def _accordion_path(span: float, parts: int, angle_deg: float, gap: float,
                    sharp: float, thickness: float, offset: float,
                    joint: str = "круг"):
    # Острота должна менять именно радиус, а не только число сегментов.
    # Минимум чуть больше половины толщины: внутренняя сторона листа не
    # проходит через центр кривизны и не заворачивается сама в себя.
    base_radius = thickness + gap / 2.0
    min_radius = thickness * 0.52
    radius = min_radius + (base_radius - min_radius) * (1.0 - sharp) ** 2
    if joint == "широкая":
        radius *= 2.5
    turn = math.radians(angle_deg)
    curve_len = radius * turn
    arc_len = curve_len * (1.3 if joint == "фаска" else 1.0)
    half = arc_len / 2.0
    if parts == 2:
        # Одиночный сгиб можно сместить от центра. Обе дуговые половины
        # относятся к своим полотнищам, поэтому offset по-прежнему задаёт
        # именно положение середины сгиба на исходном листе.
        lines = [span * offset]
        panel = max(0.0, min(lines[0], span - lines[0]) - half)
    else:
        # Все ПЛОСКИЕ полотнища одинаковы. Старая раскладка ставила центры
        # дуг на i·span/parts: крайние полотнища получались длиннее средних
        # на половину дуги, что на гармошке выглядело как уширение каждой
        # второй складки. Сначала вычитаем дуги из исходной длины, а уже
        # остаток делим поровну между всеми parts полотнищами.
        panel = (span - (parts - 1) * arc_len) / parts
        lines = [(i + 1) * panel + arc_len * (i + 0.5) for i in range(parts - 1)]
    if panel <= max(0.02, thickness * 0.05):
        raise GeometryError(
            f"На плоскую часть листа остаётся {panel:.1f} мм, а сгиб занимает {arc_len:.1f} мм.",
            hint="Уменьшите gap, angle или parts; либо увеличьте лист.")
    pts = [(0.0, 0.0, 0.0, 0.0)]  # u, z, угол, длина исходного листа

    def arc_step(x, z, ang, sign, d_ang):
        cx = x + sign * radius * (-math.sin(ang))
        cz = z + sign * radius * math.cos(ang)
        a = ang + d_ang
        return (cx + sign * radius * math.sin(a),
                cz - sign * radius * math.cos(a), a)

    x = z = ang = current = 0.0
    half = arc_len / 2.0
    for index, line in enumerate(lines):
        sign = (-1.0) ** index
        start = line - half
        if start < current - 1e-9:
            raise GeometryError("Сгибы стоят слишком близко.", hint="Уменьшите gap или parts.")
        x += (start - current) * math.cos(ang)
        z += (start - current) * math.sin(ang)
        current = start
        pts.append((x, z, ang, current))
        if joint == "сплайн":
            # Угол поворота меняется по smoothstep: кривизна на входе и
            # выходе равна нулю, поэтому острая складка не упирается в кромку.
            n = max(24, int(turn / math.radians(6.0) * 2))
            start_ang = ang
            ds = arc_len / n
            for i in range(n):
                tm = (i + 0.5) / n
                te = (i + 1.0) / n
                am = start_ang + sign * turn * (3.0 * tm * tm - 2.0 * tm ** 3)
                ae = start_ang + sign * turn * (3.0 * te * te - 2.0 * te ** 3)
                x += math.cos(am) * ds
                z += math.sin(am) * ds
                ang = ae
                current += ds
                pts.append((x, z, ang, current))
        elif joint == "фаска":
            # Две касательные дуги по половине угла и прямой участок между
            # ними. Общий поворот сохраняется, но острого одиночного ребра нет.
            n = max(8, int(turn / math.radians(6.0)))
            for half_arc in range(2):
                for _ in range(n):
                    x, z, ang = arc_step(x, z, ang, sign,
                                         sign * (turn / 2.0) / n)
                    current += curve_len / (2.0 * n)
                    pts.append((x, z, ang, current))
                if half_arc == 0:
                    flat = curve_len * 0.3
                    for _ in range(3):
                        x += math.cos(ang) * flat / 3.0
                        z += math.sin(ang) * flat / 3.0
                        current += flat / 3.0
                        pts.append((x, z, ang, current))
        else:
            # Даже пресс-биг не должен собираться из трёх угловатых скачков.
            # Радиус по-прежнему задаёт sharp, но дуга имеет достаточную
            # тесселяцию и визуально остаётся плавной.
            n = (max(8, int(round(turn / math.radians(6.0) * (1.0 - 0.55 * sharp))))
                 if sharp > 0.01 and joint == "круг"
                 else max(16 if joint == "широкая" else 10,
                          int(turn / math.radians(6.0))))
            for _ in range(n):
                x, z, ang = arc_step(x, z, ang, sign, sign * turn / n)
                current += arc_len / n
                pts.append((x, z, ang, current))
    x += (span - current) * math.cos(ang)
    z += (span - current) * math.sin(ang)
    pts.append((x, z, ang, span))
    arr = np.asarray(pts, dtype=np.float64)
    return arr[:, 3], arr[:, 0], arr[:, 1], arr[:, 2], radius, panel


@op("fold_sheet", aliases=("сгибаемый_лист", "лист_гармошка", "гармошка",
                           "folding_sheet", "bend_sheet"), category="Примитивы",
    summary="Сгибаемый лист с постоянной толщиной: parts=2 — один сгиб в "
            "выбранном месте, parts>2 — гармошка с чередованием сторон. axis "
            "задаёт X, Y или диагональ, direction — произвольный угол линии "
            "сгиба в плоскости. gap — просвет слоёв, sharp — от округлой "
            "кривой до острого пресс-бигового ребра: радиус уменьшается "
            "квадратично до 0.52·толщины, поэтому высокая острота видна на "
            "самой сетке. joint добавляет три "
            "более плавных профиля: широкая, сплайн и фаска.",
    example="сгиб = fold_sheet length=240 width=160 thickness=1 parts=2 angle=110 gap=2\n"
            "гармошка = fold_sheet length=360 width=160 thickness=1 parts=5 angle=135 gap=2 sharp=.4\n"
            "диагональ = fold_sheet length=200 width=140 parts=2 axis=диагональ angle=90\n"
            "мягкая = fold_sheet length=240 width=160 parts=2 angle=135 sharp=1 joint=сплайн",
    params={"width": "ширина по Y, мм (120)",
            "length": "длина по X, мм (200)",
            "thickness": "толщина листа, мм (1.2)",
            "parts": "2 — один сгиб; 3…12 — гармошка (2)",
            "angle": "угол каждого сгиба 1…180° (120)",
            "gap": "просвет между слоями, мм; 0 — касание (0.5·толщины)",
            "sharp": "острота сгиба 0…1: 0 — округлый, 1 — пресс-биг (0)",
            "joint": "круг — обычная дуга; широкая — радиус ×2.5; "
                     "сплайн — плавная кривизна у концов; фаска — две дуги и прямой участок",
            "axis": "x, y или диагональ — направление длины до сгиба (x)",
            "direction": "необязательный угол направления в плоскости, °; перекрывает axis",
            "offset": "место одиночного сгиба 0.1…0.9 от длины (0.5)",
            "segments": "предельная плотность исходной сетки (авто)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def fold_sheet(a, name):
    width = float(a.num("width", 120.0, minv=0.5, maxv=5000.0))
    length = float(a.num("length", 200.0, minv=0.5, maxv=8000.0))
    thickness = float(a.num("thickness", 1.2, minv=0.2, maxv=80.0))
    parts = int(a.num("parts", 2, minv=2, maxv=12) or 2)
    angle_deg = float(a.num("angle", 120.0, minv=1.0, maxv=180.0))
    gap = float(a.num("gap", thickness * 0.5, minv=0.0, maxv=400.0) or 0.0)
    sharp = float(a.num("sharp", 0.0, minv=0.0, maxv=1.0) or 0.0)
    joint = _fold_joint(a)
    offset = float(a.num("offset", 0.5, minv=0.1, maxv=0.9))
    axis = (a.text("axis", "x") or "x").strip().lower()
    direction = a.num("direction", None, minv=-180.0, maxv=180.0)
    if direction is None:
        if axis in ("x", "х", "вдоль"):
            direction = 0.0
        elif axis in ("y", "у", "поперёк", "поперек"):
            direction = 90.0
        elif axis in ("диагональ", "угол", "diag", "diagonal"):
            direction = 45.0
        else:
            raise GeometryError("fold_sheet: axis=x, y или диагональ.")
    phi = math.radians(float(direction))
    ca, sa = math.cos(phi), math.sin(phi)
    span = abs(length * ca) + abs(width * sa)
    ps, pu, pz, pt, radius, panel = _accordion_path(
        span, parts, angle_deg, gap, sharp, thickness, offset, joint)

    solid = mf.Manifold.cube((length, width, thickness), True)
    segments = int(a.num("segments", 0, minv=0, maxv=MAX_CELLS) or 0)
    refine = max(0.2, min(radius / 2.5, panel / 12.0))
    if segments:
        refine = min(refine, max(length, width) / segments)
    solid = solid.refine_to_length(refine)
    verts, faces = manifold_mesh(solid)
    u = verts[:, 0] * ca + verts[:, 1] * sa
    v = -verts[:, 0] * sa + verts[:, 1] * ca
    lo = float(u.min())
    along = np.clip(u - lo, 0.0, ps[-1])
    new_u = np.interp(along, ps, pu) + lo
    tau = np.interp(along, ps, pt)
    new_z = np.interp(along, ps, pz)
    off = verts[:, 2]
    mapped_u = new_u - np.sin(tau) * off
    mapped_z = new_z + np.cos(tau) * off
    moved = np.empty_like(verts)
    moved[:, 0] = mapped_u * ca - v * sa
    moved[:, 1] = mapped_u * sa + v * ca
    moved[:, 2] = mapped_z
    folded = manifold_from_arrays(moved, faces, "сгибаемый лист")
    folded = folded.simplify(max(0.01, min(radius, panel) * 0.02))
    before = float(solid.volume())
    after = float(folded.volume())
    tolerance = min(0.25, 0.02 + len(ps) * thickness / max(span, 1e-6))
    if before > 1e-6 and abs(after - before) / before > tolerance:
        raise GeometryError("Сгиб замкнул лист в себя.",
                            hint="Увеличьте gap или уменьшите angle/parts.")
    folded = anchor(folded, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, folded, a, kind="fold_sheet")
    out.meta["fold_radius"] = float(radius)
    out.meta["fold_sharp"] = float(sharp)
    out.notes.append(f"сгибаемый лист: parts={parts}, angle={angle_deg:g}°, "
                     f"direction={float(direction):g}°, gap={gap:g}, sharp={sharp:g}, joint={joint}")
    return out


# --------------------------------------------------------------------------- #
#  Гофрирование: смещение по оси как функция от двух других
# --------------------------------------------------------------------------- #

_CORRUGATE_MODES = {
    "гофра": "гофра", "гофр": "гофра", "flute": "гофра", "волна": "гофра",
    "вафля": "вафля", "waffle": "вафля", "клетка": "вафля",
    "рифление": "рифление", "рифленый": "рифление", "рифлёный": "рифление",
    "rib": "рифление", "ромб": "рифление", "diamond": "рифление",
    "зигзаг": "зигзаг", "zigzag": "зигзаг", "пила": "зигзаг",
}


def _axis_index(a, key: str = "axis", default: str = "z") -> int:
    raw = (a.text(key) or default).strip().lower()
    raw = {"x": "x", "х": "x", "y": "y", "у": "y", "z": "z", "з": "z"}.get(raw, raw)
    if raw not in ("x", "y", "z"):
        raise GeometryError(f"Неизвестная ось «{a.text(key)}».",
                            hint=f"{key}: x, y или z.")
    return "xyz".index(raw)


@op("corrugate", aliases=("гофра", "гофрирование", "рифление", "вафля", "corrugate",
                          "flute", "рифлёный", "гофрировать"),
    category="Форма и деформации",
    summary="Гофрирование готовой детали: гофра (синус), вафля (клетка), "
            "рифление (косые рёбра) или зигзаг. Смещение идёт по одной оси как "
            "функция от двух других, поэтому поверхность не может проткнуть "
            "саму себя. step — шаг узора, amp — высота, angle — поворот узора. "
            "Подходит листу, пластине, металлу, бумаге.",
    example="лист = sheet width=200 length=260 thickness=1\n"
            "corrugate лист step=20 amp=6\n"
            "металл = sheet width=200 length=260 thickness=1.5\n"
            "corrugate металл step=16 amp=3 mode=рифление angle=45",
    params={"objects": "объект [a] или a",
            "step": "шаг узора, мм (20)",
            "amp": "высота волны, мм (4)",
            "mode": "гофра, вафля, рифление или зигзаг («гофра»)",
            "angle": "поворот узора в плоскости, градусы (0)",
            "axis": "по какой оси поднимать волны: x, y или z («z»)",
            "detail": "длина ребра перед деформацией, мм (авто step/8)"},
    positional=["objects"])
def corrugate(a, name):
    base = _one(a, "corrugate")
    step = float(a.num("step", 20.0, minv=0.2, maxv=4000.0))
    amp = float(a.num("amp", 4.0, minv=0.0, maxv=500.0))
    mode_raw = (a.text("mode") or "гофра").strip().lower()
    mode = _CORRUGATE_MODES.get(mode_raw)
    if mode is None:
        raise GeometryError(f"Неизвестный узор «{a.text('mode')}».",
                            hint="mode: гофра, вафля, рифление или зигзаг.")
    angle = math.radians(float(a.num("angle", 0.0, minv=-180.0, maxv=180.0)))
    axis = _axis_index(a, "axis", "z")
    if amp <= 1e-6:
        return _derived(a, name, base.manifold, base, "corrugate")

    m = base.manifold
    detail = a.num("detail", None, minv=0.02)
    # Не меньше двенадцати рёбер на волну: восьми было недостаточно — на
    # крутых рифлях и вафле проступала диагональ триангуляции.
    refine = float(detail) if detail else max(0.08, step / 12.0)
    m = m.refine_to_length(_refine_for(m, refine))
    verts, faces = manifold_mesh(m)
    if len(verts) > MAX_TRIS:
        raise GeometryError(
            f"Слишком плотная сетка для гофрирования: {len(verts):,} вершин.".replace(",", " "),
            hint="Упростите деталь командой simplify или увеличьте detail.")

    u = [verts[:, i] for i in range(3)]
    k = 2.0 * math.pi / step
    other = [i for i in range(3) if i != axis]
    ca, sa = math.cos(angle), math.sin(angle)
    x1 = u[other[0]] * ca + u[other[1]] * sa
    y1 = -u[other[0]] * sa + u[other[1]] * ca
    if mode == "гофра":
        off = np.sin(k * x1)
    elif mode == "вафля":
        off = np.sin(k * x1) * np.sin(k * y1)
    elif mode == "рифление":
        # Параллельные рёбра с пологой вершиной и крутыми боками. Прежняя
        # сумма двух косых синусов была тождественна sin(x)·cos(y): на листе
        # она давала почти ту же двумерную вафлю. Здесь координата y1 не
        # участвует вовсе — рифление действительно идёт прямыми полосами.
        wave = np.sin(k * x1)
        off = np.sign(wave) * np.power(np.abs(wave), 0.45)
    else:                                        # зигзаг
        off = 2.0 / math.pi * np.arcsin(np.sin(k * x1))
    moved = verts.copy()
    moved[:, axis] += amp * off
    solid = manifold_from_arrays(moved, faces, "гофрирование")
    a.scene.log("info", f"гофрирование: {mode}, шаг {step:g}, высота {amp:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return _derived(a, name, solid, base, "corrugate")


def _refine_for(m: mf.Manifold, length: float) -> float:
    """Множитель ``refine_to_length`` — как в складках, чтобы не мельчить зря."""
    bb = m.bounding_box()
    span = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2], 1e-3)
    return float(max(length, span / 400.0))


# --------------------------------------------------------------------------- #
#  Сгиб: оригами пополам, на треть и мельче
# --------------------------------------------------------------------------- #

@op("fold", aliases=("сложить", "сгиб", "оригами", "fold", "origami"),
    category="Форма и деформации",
    summary="Складывает деталь как бумагу: пополам, на треть или мельче, "
            "гармошкой с чередованием сторон. Длина вдоль оси сохраняется "
            "(сгиб изометрический), место сгиба проходится дугой радиуса из "
            "gap, а gap задаёт, насколько близко лягут слои. joint=широкая, "
            "сплайн или фаска даёт три более плавных профиля. Если слои не "
            "помещаются, команда честно скажет, что увеличить.",
    example="лист = sheet width=160 length=240 thickness=1\n"
            "fold лист parts=2 angle=180 gap=2\n"
            "полоса = sheet width=80 length=300 thickness=1\n"
            "fold полоса parts=4 angle=120 gap=2.5",
    params={"objects": "объект [a] или a",
            "parts": "на сколько частей сложить: 2 — пополам, 3 — на треть (2)",
            "angle": "угол сгиба в градусах, 180 — совсем пополам (180)",
            "gap": "просвет между слоями после складывания, мм (толщина × 0.5)",
            "sharp": "жёсткость складки 0…1 (0): 1 — пресс-биг, ребро почти острое",
            "joint": "круг, широкая, сплайн или фаска — профиль дуги сгиба",
            "axis": "вдоль какой оси делить лист: x, y («x»)",
            "offset": "где линия сгиба, 0.1…0.9 от длины (0.5)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["objects"])
def fold(a, name):
    base = _one(a, "fold")
    parts = int(a.num("parts", 2, minv=2, maxv=12))
    angle_deg = float(a.num("angle", 180.0, minv=1.0, maxv=180.0))
    axis = _axis_index(a, "axis", "x")
    offset = float(a.num("offset", 0.5, minv=0.1, maxv=0.9))
    m = base.manifold
    bb = m.bounding_box()
    ext = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    span = float(ext[axis])
    if span < 1e-3:
        raise GeometryError("У детали нет длины вдоль выбранной оси.",
                            hint="Выберите другую axis или поверните деталь.")
    # толщина «слоя» — самая тонкая сторона габарита
    thin = max(min(ext), 1e-3)
    gap = a.num("gap", None, minv=0.02)
    gap = float(gap) if gap else thin * 0.5
    # Путь идёт по нижней поверхности листа. После полуоборота слой лежит
    # выше основания на 2r и занимает [2r − t, 2r], поэтому
    # 2r = 2t + gap: между слоями остаётся ровно просвет gap, а внутренний
    # радиус сгиба (r − t = gap/2) не проваливается сквозь себя.
    sharp = float(a.num("sharp", 0.0, minv=0.0, maxv=1.0))
    # Жёсткая складка: радиус сгиба упирается в толщину листа (внутренний
    # радиус стремится к нулю), а дуга дробится крупно — на рендере ребро
    # читается линией, а не круглой трубой.
    joint = _fold_joint(a)
    turn = math.radians(angle_deg)
    lo = bb[axis]
    ps, px, pz, pt, radius, panel = _accordion_path(
        span, parts, angle_deg, gap, sharp, thin, offset, joint)
    px = px + lo
    # Сетку дробим под сгиб: иначе один большой треугольник на всю деталь
    # «срезает» дугу и объём уезжает.
    m = m.refine_to_length(_refine_for(m, max(0.25, min(radius / 2.5, panel / 12.0))))
    verts, faces = manifold_mesh(m)
    # вдоль axis лист делится на части; сгиб идёт в плоскости (axis, up),
    # третья ось — линия сгиба, она не меняется
    up = 2 if axis != 2 else 1
    v_along = verts[:, axis] - lo
    s_of = np.clip(v_along, 0.0, ps[-1])
    new_along = np.interp(s_of, ps, px)
    new_up = np.interp(s_of, ps, pz)
    tau = np.interp(s_of, ps, pt)
    offset_up = verts[:, up] - bb[up]
    moved = verts.copy()
    moved[:, axis] = new_along - np.sin(tau) * offset_up
    moved[:, up] = bb[up] + new_up + np.cos(tau) * offset_up
    solid = manifold_from_arrays(moved, faces, "сгиб")
    # мелкая сетка нужна только у самого сгиба: плоские полотнища снова
    # собираем в крупные треугольники, иначе лист весит сотни тысяч граней
    solid = solid.simplify(max(0.01, min(radius, panel) * 0.02))

    before = float(m.volume())
    after = float(solid.volume())
    # изгиб честно теряет объём на внутренней стороне сгиба: t²θ/2 на каждый
    # сгиб. Разрешаем втрое больше — этого хватает на погрешность сетки, но
    # самопересечение всё равно видно.
    tol = min(0.25, 0.01 + 3.0 * (parts - 1) * turn * thin / (2.0 * max(span, 1e-6)))
    if before > 1e-6 and abs(after - before) / before > tol:
        raise GeometryError(
            "Сгиб замкнул деталь в себя: слои не помещаются.",
            hint="Увеличьте gap или уменьшите angle.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    a.scene.log("info", f"сгиб: {parts} части, {angle_deg:g}°, зазор {gap:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return _derived(a, name, solid, base, "fold")


# --------------------------------------------------------------------------- #
#  Гофрокартон: линеры и гофра одним телом
# --------------------------------------------------------------------------- #

@op("cardboard", aliases=("гофрокартон", "картон", "cardboard", "corrugated_board"),
    category="Примитивы",
    summary="Гофрированный картон: плоские линеры и гофра между ними одним "
            "целым телом. layer=2 — двухслойный (линер + гофра), 3 — "
            "трёхслойный (линер, гофра, линер). Шаг и высота гофры "
            "настраиваются; лист стоит на полу, как обычный лист картона.",
    example="картон = cardboard width=200 height=300 liner=0.4 flute=3.5 step=8\n"
            "двухслойный = cardboard width=150 height=200 layer=2 flute=2.5 step=6",
    params={"width": "ширина, мм (200)",
            "height": "высота листа, мм (300)",
            "liner": "толщина плоского слоя, мм (0.4)",
            "flute": "высота гофры между линерами, мм (3.5)",
            "step": "шаг гофры, мм (8)",
            "layer": "2 — линер + гофра, 3 — линер + гофра + линер (3)",
            "segments": "плотность сетки (авто)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cardboard(a, name):
    width = float(a.num("width", 200.0, minv=2.0, maxv=5000.0))
    height = float(a.num("height", 300.0, minv=2.0, maxv=5000.0))
    liner = float(a.num("liner", 0.4, minv=0.1, maxv=20.0))
    flute = float(a.num("flute", 3.5, minv=0.4, maxv=200.0))
    step = float(a.num("step", 8.0, minv=1.0, maxv=400.0))
    layers = int(a.num("layer", 3, minv=2, maxv=3))
    if flute < liner * 1.2:
        raise GeometryError(f"Гофра высотой {flute:g} мм ниже линера {liner:g} мм.",
                            hint="flute больше liner, обычно 2…8 мм.")
    if step < flute * 1.2:
        raise GeometryError(
            f"Шаг гофры {step:g} мм меньше её высоты {flute:g} мм: гофра сложится сама в себя.",
            hint="step больше flute (обычно в 1.5…3 раза).")

    depth = liner * (2 if layers == 3 else 1) + flute
    wobble = (flute / 2.0 + liner * 0.35)
    mid = liner + flute / 2.0
    seg = int(a.num("segments", 0, minv=0, maxv=MAX_CELLS))
    nu = seg or int(np.clip(max(24, height / step * 10), 24, MAX_CELLS))
    nv = seg or 8

    def flute_point(s, t):
        x = (s - 0.5) * height
        y = (t - 0.5) * width
        z = mid + wobble * np.sin(2.0 * math.pi * x / step)
        return np.stack([x, y, z], axis=-1)

    core = _thick_surface(flute_point, nu, nv, max(0.3, liner * 0.6), "гофра")
    liners = []
    z0 = 0.0 if layers == 3 else mid - wobble
    liners.append(mf.Manifold.cube((height, width, liner)).translate(
        (-height / 2.0, -width / 2.0, z0)))
    if layers == 3:
        liners.append(mf.Manifold.cube((height, width, liner)).translate(
            (-height / 2.0, -width / 2.0, depth - liner)))
    solid = core
    for box in liners:
        solid = solid + box
    if solid.decompose() and len([p for p in solid.decompose() if p.volume() > 0]) != 1:
        # гофра не дотянулась до линера — поднимаем её на клей
        raise GeometryError("Гофра не соединилась с линерами.",
                            hint="Увеличьте flute или уменьшите step.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    a.scene.log("info", f"гофрокартон {layers}-слойный: {height:g}×{width:g}×{depth:g} мм, "
                        f"гофра {flute:g}/{step:g}, {solid.num_tri():,} трис".replace(",", " "),
                a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="cardboard")
