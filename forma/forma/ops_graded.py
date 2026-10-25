"""Градация: ряд копий с шагом изменения и с нарастающей силой инструмента.

Обычный `array` ставит одинаковые копии через равное расстояние. Но часто
нужен не повтор, а **изменение с шагом**: кольца Wi-Fi (точка, дуга, дуга
побольше, ещё больше), ряд вмятин всё глубже и глубже, кольца всё толще,
лестница из блоков, где каждый следующий выше предыдущего на одно и то же
число процентов.

Здесь два инструмента:

* `ряд` — копии с накоплением изменений: сдвиг `step` за копию, рост `grow`
  (множитель размера), поворот `turn` за копию, плюс необязательная
  деформация с силой, которая растёт или падает по шагу `шаг_силы`;
* `размер` — задать детали размер **по мерке**: `size = размер [б] width=1.5*width(а)`
  делает ширину б ровно в полтора раза больше ширины а (масштаб считается
  сам, вручную делить не нужно).

    ряд [кольцо] count=4 grow=1.35                     # Wi-Fi: кольца всё больше
    ряд [шарик] count=6 step=[0,0,26] инструмент=вмятина сила=1.2 шаг_силы=1.5
    size = размер [плитка] width=0.5*width(ящик) height=height(ящик)
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import (make_solid, op, rotate as rotate_manifold,
                  scale as scale_manifold, translate as translate_manifold)


def _bbox_center(bb) -> np.ndarray:
    return np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)], dtype=np.float64)


def _rotate_about(m: mf.Manifold, axis: str, angle: float, center) -> mf.Manifold:
    axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    return rotate_manifold(m, angle, axis_vec, center)


def _bump(q: np.ndarray) -> np.ndarray:
    """Гладкое пятно: 1 в центре, 0 на краю, без излома производной."""
    t = np.clip(1.0 - q * q, 0.0, 1.0)
    return t * t


def _tool_names() -> dict[str, str]:
    return {
        "вмятина": "dent", "вдавить": "dent", "dent": "dent", "удар": "dent",
        "скрутка": "twist", "скрутить": "twist", "twist": "twist",
        "сужение": "taper", "сузить": "taper", "taper": "taper",
        "сдвиг": "shear", "наклон": "shear", "shear": "shear",
        "надуть": "inflate", "выдувание": "inflate", "inflate": "inflate",
    }


def _deform(m: mf.Manifold, tool: str, strength: float,
            axis: str, soft: float, spot: float | None = None) -> mf.Manifold:
    """Одна деформация с заданной силой — по мотивам инструментов скульпта."""
    if abs(strength) < 1e-9:
        return m
    bb = m.bounding_box()
    center = _bbox_center(bb)
    lo = np.array([bb[0], bb[1], bb[2]], dtype=np.float64)
    hi = np.array([bb[3], bb[4], bb[5]], dtype=np.float64)
    size = np.maximum(hi - lo, 1e-6)
    ax = {"x": 0, "y": 1, "z": 2}[axis]
    other = [i for i in (0, 1, 2) if i != ax]

    if tool == "dent":
        # пятно на верхней точке оси: инструмент бьёт по детали сверху
        at = center.copy()
        at[ax] = hi[ax]
        radius = float(spot) if spot and spot > 0 else float(np.max(size[other]) * 0.35)
        radius = max(radius, 1e-3)
        direction = center - at
        n = float(np.linalg.norm(direction))
        direction = direction / n if n > 1e-9 else np.array([0.0, 0.0, -1.0])
        depth = float(np.clip(strength, -radius * 0.95, radius * 0.95))
        # мягкость меняет профиль пятна: 1 — пологая широкая вмятина,
        # 0 — узкий резкий удар. Амплитуду задаёт сила, а не мягкость.
        power = 0.5 + 1.6 * min(max(soft, 0.05), 1.0)

        def fn(p: np.ndarray) -> np.ndarray:
            q = np.linalg.norm(p - at, axis=1) / radius
            w = _bump(q) ** power
            return p + direction[None, :] * (depth * w)[:, None]

        return m.warp_batch(fn)

    if tool == "twist":
        deg = math.radians(float(strength))

        def fn(p: np.ndarray) -> np.ndarray:
            out = np.array(p, dtype=np.float64)
            t = (out[:, ax] - lo[ax]) / size[ax]
            ang = deg * t
            ca, sa = np.cos(ang), np.sin(ang)
            u = out[:, other[0]] - center[other[0]]
            v = out[:, other[1]] - center[other[1]]
            out[:, other[0]] = center[other[0]] + u * ca - v * sa
            out[:, other[1]] = center[other[1]] + u * sa + v * ca
            return out

        return m.warp_batch(fn)

    if tool == "taper":
        k = float(np.clip(strength, -0.9, 0.9))

        def fn(p: np.ndarray) -> np.ndarray:
            out = np.array(p, dtype=np.float64)
            t = (out[:, ax] - lo[ax]) / size[ax]
            f = 1.0 - k * t
            for i in other:
                out[:, i] = center[i] + (out[:, i] - center[i]) * f
            return out

        return m.warp_batch(fn)

    if tool == "shear":
        shift = float(strength)

        def fn(p: np.ndarray) -> np.ndarray:
            out = np.array(p, dtype=np.float64)
            t = (out[:, ax] - lo[ax]) / size[ax]
            out[:, other[0]] += shift * t
            return out

        return m.warp_batch(fn)

    # inflate: раздуть вокруг центра пятна — объём растёт, форма остаётся
    gain = float(strength)

    def fn(p: np.ndarray) -> np.ndarray:
        t = (p[:, ax] - lo[ax]) / size[ax]
        w = 1.0 - np.abs(2.0 * t - 1.0)
        w = np.clip(w, 0.0, 1.0) ** 0.7
        return center + (p - center) * (1.0 + gain * w)[:, None]

    return m.warp_batch(fn)


@op("ряд", aliases=("градация", "ступени", "graded", "graded_array", "лесенка",
                    "wifi", "веер_роста"),
    category="Массивы и преобразования",
    summary="Ряд копий с накоплением изменений: каждая следующая сдвинута на "
            "step, выросла в grow раз и повёрнута на turn градусов. Если задан "
            "инструмент, его сила на каждой копии меняется по шагу шаг_силы — "
            "вмятины всё глубже, кольца всё толще, как у значка Wi-Fi. "
            "Это массив не одинаковых копий, а ступеней изменения.",
    example="кольцо = torus major=10 minor=2\n"
            "волны = ряд [кольцо] count=4 grow=1.35\n"
            "шарик = sphere radius=12\n"
            "дырки = ряд [шарик] count=5 step=[30,0,0] инструмент=вмятина "
            "сила=1.0 шаг_силы=1.6\n"
            "кубик = box size=[20,20,20]\n"
            "лестница = ряд [кубик] count=6 step=[0,0,20] grow=1.12 turn=6 axis=z",
    params={"objects": "исходная деталь (или несколько — они свариваются)",
            "count": "сколько копий (включая первую), 2…200",
            "step": "сдвиг каждой следующей копии [dx,dy,dz] (0,0,0); "
                    "можно задать меркой: step=[0.5*width(а),0,0]",
            "grow": "во сколько раз растёт каждая следующая, 0.2…5 (1 — не растёт)",
            "turn": "поворот каждой следующей, градусы (0)",
            "axis": "ось поворота и деформаций: x, y или z (z)",
            "инструмент": "чем менять форму: вмятина, скрутка, сужение, сдвиг, "
                          "надуть (пусто — только преобразования)",
            "сила": "сила инструмента на первой копии (в мм или градусах)",
            "шаг_силы": "во сколько раз сила меняется от копии к копии (1)",
            "soft": "мягкость пятна вмятины 0…1 (0.6)",
            "radius": "радиус пятна для вмятины, мм (0.35 от детали)",
            "at": "сдвиг всего ряда [x,y,z]",
            "merge": "слить копии в одно тело (да)"},
    positional=["objects"])
def graded(a, name):
    sources = a.solids()
    if not sources:
        raise GeometryError("ряд: не указана деталь.",
                            hint="Например: ряд [кольцо] count=4 grow=1.35")
    base = sources[0]
    source = sources[0].manifold
    if len(sources) > 1:
        source = mf.Manifold.batch_boolean([s.manifold for s in sources],
                                           mf.OpType.Add)

    count = int(a.num("count", 4, minv=1, maxv=200))
    step = np.asarray(a.vec("step", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    grow = float(a.num("grow", 1.0, minv=0.2, maxv=5.0))
    turn = float(a.num("turn", 0.0, minv=-360.0, maxv=360.0) or 0.0)
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    soft = float(a.num("soft", 0.6, minv=0.05, maxv=1.0))
    spot = a.num("radius", None, minv=0.2)
    tool_raw = (a.text("инструмент", None) or "").strip().lower()
    tool = _tool_names().get(tool_raw, "") if tool_raw else ""
    if tool_raw and not tool:
        raise GeometryError(f"ряд: неизвестный инструмент «{tool_raw}».",
                            hint="Доступны: вмятина, скрутка, сужение, сдвиг, надуть.")
    strength = float(a.num("сила", 0.0) or 0.0)
    step_strength = float(a.num("шаг_силы", 1.0, minv=-4.0, maxv=4.0) or 1.0)
    merge = a.boolean("merge", True)

    own_center = _bbox_center(source.bounding_box())
    copies = []
    for i in range(count):
        piece = source
        if abs(grow - 1.0) > 1e-9 and i:
            f = grow ** i
            piece = scale_manifold(piece, (f, f, f), own_center)
        if tool and strength:
            value = strength * (step_strength ** i)
            piece = _deform(piece, tool, value, axis, soft, spot)
        if abs(turn) > 1e-9 and i:
            piece = _rotate_about(piece, axis, turn * i, own_center)
        if np.any(np.abs(step) > 1e-9) and i:
            piece = translate_manifold(piece, step * i)
        copies.append(piece)

    for s in sources:
        a.scene.consume(s)
    if merge:
        solid = mf.Manifold.batch_boolean(copies, mf.OpType.Add)
    else:
        solid = copies[0]
    if a.has("at"):
        solid = translate_manifold(solid, np.asarray(a.vec("at", 3), dtype=np.float64))

    if solid.num_tri() > 1_500_000:
        a.scene.log("warn", "ряд получился очень тяжёлым — уменьшите count.",
                    a.cmd.line)
    made = make_solid(a.scene, name, solid, a, base=base, kind="ряд")
    what = f"ряд: {count} копий, рост {grow:g}"
    if tool and strength:
        what += f", {tool_raw} {strength:g}×{step_strength:g} за копию"
    made.notes.append(what)
    a.scene.log("info", what, a.cmd.line)
    return made


@op("размер", aliases=("size_to", "под_размер", "по_размеру", "resize", "подогнать"),
    category="Массивы и преобразования",
    summary="Задаёт детали размер по мерке, а не множитель: width=1.5*width(а) "
            "сделает ширину ровно в полтора раза больше ширины а, "
            "height=height(а) уровняет по высоте. Масштаб считается сам, "
            "по фактическим габаритам. Пропорции остальных осей можно "
            "сохранить (keep=да).",
    example="ящик = box size=[80,50,40]\n"
            "плита = box size=[10,10,10]\n"
            "плита = размер [плита] width=width(ящик) depth=0.5*depth(ящик)\n"
            "кубик = sphere radius=10\n"
            "кубик = размер [кубик] height=1.5*height(ящик)",
    params={"objects": "деталь", "width": "какая станет ширина по X, мм",
            "depth": "какая станет глубина по Y, мм",
            "height": "какая станет высота по Z, мм",
            "length": "какой станет наибольший габарит, мм",
            "factor": "просто множитель размера (вместо мерок)",
            "keep": "сохранить пропорции: масштаб одинаков по всем осям (нет)",
            "pivot": "точка отсчёта масштаба (центр детали)"},
    positional=["objects"])
def resize(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("размер работает с одной деталью.",
                            hint="Формат: размер [плита] width=0.5*width(ящик)")
    base = solids[0]
    bb = base.manifold.bounding_box()
    cur = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=np.float64)
    cur = np.maximum(cur, 1e-6)

    want = np.array([np.nan, np.nan, np.nan], dtype=np.float64)
    for key, i in (("width", 0), ("depth", 1), ("height", 2)):
        value = a.num(key, None, minv=1e-6)
        if value is not None:
            want[i] = float(value)
    length = a.num("length", None, minv=1e-6)
    if length is not None:
        longest = int(np.argmax(cur))
        want[longest] = float(length)
    factor = a.num("factor", None, minv=1e-6)

    if factor is not None and np.isnan(want).all():
        scales = np.full(3, float(factor))
    else:
        if np.isnan(want).all():
            raise GeometryError("размер: не задано, каким должен стать размер.",
                                hint="Например: размер [плита] width=1.5*width(ящик)")
        scales = np.where(np.isnan(want), 1.0, want / cur)
        keep = a.boolean("keep", False)
        if keep:
            filled = scales[~np.isnan(want)]
            uniform = float(np.prod(filled)) ** (1.0 / max(len(filled), 1))
            scales = np.full(3, uniform)
    if np.any(scales <= 1e-9):
        raise GeometryError("размер: масштаб получился нулевым.",
                            hint="Проверьте мерки: они должны быть больше нуля.")
    pivot = a.vec("pivot", 3, default=tuple(_bbox_center(bb)))
    scaled = scale_manifold(base.manifold, tuple(scales), pivot)
    solid = make_solid(a.scene, name, scaled, a, base=base, kind="размер")
    a.scene.consume(base)
    nb = scaled.bounding_box()
    got = np.array([nb[3] - nb[0], nb[4] - nb[1], nb[5] - nb[2]])
    solid.notes.append(
        "размер {0:g}×{1:g}×{2:g} мм".format(*[round(float(v), 1) for v in got]))
    a.scene.log("info", "размер: {0:g}×{1:g}×{2:g} мм".format(
        *[round(float(v), 1) for v in got]), a.cmd.line)
    return solid
