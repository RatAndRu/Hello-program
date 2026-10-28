"""Органические формы: соус по поверхности, кляксы и верёвочные узлы.

Все контуры и пути вычисляются здесь. Референсные изображения не содержат
никаких исходных координат и не используются как сетки или шаблоны.
"""
from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (catmull_rom, circle_profile, ellipse_profile, loft_solid,
                       manifold_from_arrays, manifold_mesh, sweep_solid)
from .ops import anchor, detail_level, make_solid, op


_DETAIL_SAMPLES = (3, 4, 6, 8, 12, 16)
_DETAIL_SIDES = (8, 10, 12, 16, 20, 24)


def _combine(parts: list[mf.Manifold], what: str) -> mf.Manifold:
    """Объединяет непересекающиеся замкнутые части без лишнего boolean."""
    verts_all = []
    faces_all = []
    offset = 0
    for part in parts:
        verts, faces = manifold_mesh(part)
        if len(verts) == 0 or len(faces) == 0:
            raise GeometryError(f"{what}: пустая часть.")
        verts_all.append(verts)
        faces_all.append(faces + offset)
        offset += len(verts)
    return manifold_from_arrays(np.vstack(verts_all), np.vstack(faces_all), what)


def _default_style(solid, color: str, rough: float, args) -> None:
    style = args.style()
    if not style.get("color"):
        solid.color = color
    if "rough" not in style:
        solid.rough = rough
    solid.meta["smooth_normals"] = True


# --------------------------------------------------------------------------- #
#  Соус: круглая полоса, спроецированная на верхнюю поверхность носителя
# --------------------------------------------------------------------------- #
def _down_hit(targets, x: float, y: float, z_top: float, reach: float):
    best = None
    for target in targets:
        hits = target.manifold.ray_cast([float(x), float(y), float(z_top)],
                                        [float(x), float(y), float(z_top - reach)])
        if not hits:
            continue
        hit = hits[0]
        point = np.asarray(hit.position, dtype=np.float64)
        if best is None or point[2] > best[0][2]:
            normal = np.asarray(hit.normal, dtype=np.float64)
            normal /= max(float(np.linalg.norm(normal)), 1e-12)
            best = (point, normal)
    return best


@op("sauce", aliases=("соус", "горчица", "кетчуп", "drizzle", "sauce_drizzle",
                      "поливка", "растекание"),
    category="Форма и деформации",
    summary="Строит объёмную полосу соуса: волну или зигзаг с круглым сечением. "
            "Если указан носитель [объект], каждая точка проецируется лучом на "
            "его верхнюю поверхность и учитывает её нормаль; носитель сохраняется "
            "отдельным объектом. seed меняет фазу, мелкие неровности и ветви drips.",
    example="сосиска = capsule radius=15 height=150\n"
            "сосиска = rotate [сосиска] angle=90 axis=y\n"
            "горчица = sauce [сосиска] length=105 amplitude=12 waves=5 radius=2.2 "
            "pattern=зигзаг drips=2 seed=4 color=#e7b700",
    params={"objects": "необязательный носитель [объект] — соус ляжет на его верх",
            "length": "длина основной полосы, мм (120; для носителя — 75% его длины)",
            "amplitude": "боковой размах, мм (18; для носителя — 30% его ширины)",
            "radius": "радиус круглой полосы, мм (2.4)",
            "waves": "число полных колебаний (5)",
            "pattern": "зигзаг, волна или прямая (зигзаг)",
            "axis": "направление длины: x или y (x)",
            "jitter": "случайная неровность 0…1 (0.12)",
            "drips": "число боковых ветвей-растеканий (0)",
            "drip_length": "длина каждой ветви, мм (авто по размаху)",
            "gap": "просвет между соусом и носителем, мм (0.08)",
            "seed": "повторяемый сдвиг узора и ветвей (0)",
            "detail": "детализация 0…5: путь и круглое сечение (3)",
            "at": "положение для отдельного соуса; для носителя — добавочный сдвиг",
            "center": "центрировать отдельный соус в at вместо постановки низа"},
    positional=["objects"])
def sauce(a, name):
    targets = a.solids() if a.has("objects") else []
    radius = float(a.num("radius", 2.4, minv=0.05))
    gap = float(a.num("gap", 0.08, minv=0.0))
    waves = float(a.num("waves", 5.0, minv=0.0, maxv=100.0))
    seed = int(a.num("seed", 0) or 0)
    jitter = float(a.num("jitter", 0.12, minv=0.0, maxv=1.0))
    pattern = (a.text("pattern", "зигзаг") or "зигзаг").strip().lower()
    pattern = {"зигзаг": "зигзаг", "zigzag": "зигзаг", "волна": "волна",
               "wave": "волна", "синус": "волна", "прямая": "прямая",
               "line": "прямая", "линия": "прямая"}.get(pattern)
    if pattern is None:
        raise GeometryError("sauce: pattern=зигзаг, волна или прямая.")
    axis = (a.text("axis", "x") or "x").strip().lower()
    axis = {"х": "x", "у": "y"}.get(axis, axis)
    if axis not in ("x", "y"):
        raise GeometryError("sauce: axis=x или y.")
    level = detail_level(a)
    rng = np.random.default_rng(seed)

    if targets:
        boxes = [t.manifold.bounding_box() for t in targets]
        lo = np.min(np.asarray([b[:3] for b in boxes]), axis=0)
        hi = np.max(np.asarray([b[3:] for b in boxes]), axis=0)
        center = (lo + hi) / 2.0
        spans = hi - lo
        along = 0 if axis == "x" else 1
        side = 1 - along
        length = float(a.num("length", float(spans[along]) * 0.75,
                             minv=radius * 4.0))
        amplitude = float(a.num("amplitude", float(spans[side]) * 0.30, minv=0.0))
        z_top = float(hi[2]) + max(2.0, radius * 3.0)
        reach = float(spans[2]) + max(4.0, radius * 6.0)
    else:
        center = np.zeros(3)
        length = float(a.num("length", 120.0, minv=radius * 4.0))
        amplitude = float(a.num("amplitude", 18.0, minv=0.0))
        z_top = reach = 0.0

    count = max(32, min(320, int(length / max(radius * 0.8, 0.2))
                        * _DETAIL_SAMPLES[level] // 4))
    t = np.linspace(0.0, 1.0, count)
    phase = 2.0 * math.pi * waves * t + float(rng.uniform(-0.35, 0.35))
    if pattern == "зигзаг":
        signal = 2.0 / math.pi * np.arcsin(np.sin(phase))
    elif pattern == "волна":
        signal = np.sin(phase)
    else:
        signal = np.zeros_like(t)
    noise = (0.55 * np.sin(phase * 0.37 + rng.uniform(-math.pi, math.pi))
             + 0.45 * np.sin(phase * 0.71 + rng.uniform(-math.pi, math.pi)))
    lateral = amplitude * (signal + jitter * noise)
    along_pos = (t - 0.5) * length
    xy = np.zeros((count, 2))
    along = 0 if axis == "x" else 1
    side = 1 - along
    xy[:, along] = center[along] + along_pos
    xy[:, side] = center[side] + lateral

    def project(points_xy: np.ndarray, required: bool = True):
        points = []
        for x, y in points_xy:
            if targets:
                hit = _down_hit(targets, float(x), float(y), z_top, reach)
                if hit is None:
                    if required:
                        raise GeometryError(
                            "sauce: часть пути вышла за верхнюю поверхность носителя.",
                            hint="Уменьшите length/amplitude или выберите более широкий носитель.")
                    break
                p, n = hit
                points.append(p + n * (radius + gap))
            else:
                points.append(np.array([x, y, radius + 0.12]))
        return np.asarray(points, dtype=np.float64)

    main = project(xy)
    if len(main) < 2:
        raise GeometryError("sauce: не удалось построить путь.")
    parts = [sweep_solid(main, circle_profile(radius, _DETAIL_SIDES[level]),
                         up_hint=(0, 0, 1), what="соус", round_caps=0.75)]
    drips = int(a.num("drips", 0, minv=0, maxv=24))
    drip_length = float(a.num("drip_length", max(radius * 5.0, amplitude * 0.9),
                              minv=radius))
    for i in range(drips):
        index = int((i + 1) * (count - 1) / (drips + 1))
        index = int(np.clip(index + rng.integers(-3, 4), 0, count - 1))
        start = xy[index].copy()
        sign = -1.0 if i % 2 else 1.0
        branch_t = np.linspace(0.0, 1.0, max(12, 8 + level * 4))
        branch = np.repeat(start[None, :], len(branch_t), axis=0)
        branch[:, side] += sign * drip_length * branch_t
        branch[:, along] += radius * 0.8 * np.sin(math.pi * branch_t) * rng.uniform(-1, 1)
        projected = project(branch, required=False)
        if len(projected) >= 2:
            parts.append(sweep_solid(
                projected, circle_profile(radius * 0.82, _DETAIL_SIDES[level]),
                up_hint=(0, 0, 1), what="растекание соуса", round_caps=0.8))
    result = parts[0] if len(parts) == 1 else mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    # Совпадающие стартовые сечения ветвей иногда оставляют нулевой boolean-осколок.
    components = result.decompose()
    positive = [p for p in components if p.volume() > 1e-6]
    if len(positive) != len(components):
        result = _combine(positive, "соус")
    if targets and a.has("at"):
        result = result.translate(tuple(a.vec("at", 3)))
    elif not targets:
        result = anchor(result, a.vec("at", 3, default=(0, 0, 0)),
                        a.boolean("center", False))
    out = make_solid(a.scene, name, result, a, kind="sauce")
    out.meta["seed"] = seed
    out.notes.append(f"соус: {pattern}, ветвей {len(parts) - 1}, носитель: {'да' if targets else 'нет'}")
    _default_style(out, "#e5b91f", 0.28, a)
    return out


# --------------------------------------------------------------------------- #
#  Клякса: гладкий радиальный сплайн, настоящий объём и отдельные брызги
# --------------------------------------------------------------------------- #
def _periodic_radius(control: np.ndarray, samples: int) -> np.ndarray:
    """Кубический Hermite-сплайн по равномерному углу, без самопересечений."""
    n = len(control)
    ts = np.linspace(0.0, 1.0, samples, endpoint=False)
    out = []
    for i in range(n):
        r0 = float(control[i])
        r1 = float(control[(i + 1) % n])
        m0 = (r1 - float(control[(i - 1) % n])) * 0.5
        m1 = (float(control[(i + 2) % n]) - r0) * 0.5
        h00 = 2 * ts ** 3 - 3 * ts ** 2 + 1
        h10 = ts ** 3 - 2 * ts ** 2 + ts
        h01 = -2 * ts ** 3 + 3 * ts ** 2
        h11 = ts ** 3 - ts ** 2
        out.append(h00 * r0 + h10 * m0 + h01 * r1 + h11 * m1)
    return np.concatenate(out)


def _blot_outline(radius: float, lobes: int, irregularity: float,
                  seed: int, detail: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tips = rng.uniform(0.78, 1.52, lobes)
    valleys = rng.uniform(0.40, 0.70, lobes)
    tips = 1.12 + irregularity * (tips - 1.12)
    valleys = 0.56 + irregularity * (valleys - 0.56)
    control = np.empty(lobes * 2)
    control[0::2] = tips
    control[1::2] = valleys
    radii = _periodic_radius(control, _DETAIL_SAMPLES[detail])
    angles = np.linspace(0.0, 2 * math.pi, len(radii), endpoint=False)
    angles += float(rng.uniform(0.0, 2 * math.pi))
    outline = np.stack([radii * np.cos(angles), radii * np.sin(angles)], axis=1)
    outline *= radius / max(float(np.max(np.linalg.norm(outline, axis=1))), 1e-9)
    return outline


@op("blot", aliases=("клякса", "splat", "ink_blot", "брызги"),
    category="Примитивы",
    summary="Объёмная клякса с гладкими выступами, скруглённым краем, выпуклым "
            "верхом и необязательными отдельными брызгами. Контур строится "
            "периодическим сплайном; seed воспроизводимо меняет выступы и брызги.",
    example="клякса = blot radius=45 thickness=4 dome=1.4 lobes=9 "
            "irregularity=.85 droplets=7 seed=12 color=#d51f72",
    params={"radius": "максимальный радиус основной кляксы, мм (45)",
            "thickness": "толщина основания без выпуклости, мм (4)",
            "dome": "дополнительная выпуклость верха, мм (1.2)",
            "lobes": "число выступов 3…32 (9)",
            "irregularity": "нерегулярность 0…1 (0.85)",
            "droplets": "число отдельных брызг 0…64 (6)",
            "spread": "разброс брызг, множитель радиуса 0.8…4 (1.35)",
            "seed": "повторяемая рандомизация контура и брызг (0)",
            "detail": "детализация 0…5: гладкость контура и брызг (3)",
            "at": "положение [x,y,z], по умолчанию низ на at",
            "center": "центрировать всю форму в at"},
    positional=["radius"])
def blot(a, name):
    radius = float(a.num("radius", 45.0, minv=0.2))
    thickness = float(a.num("thickness", 4.0, minv=0.05))
    dome = float(a.num("dome", 1.2, minv=0.0))
    lobes = int(a.num("lobes", 9, minv=3, maxv=32))
    irregularity = float(a.num("irregularity", 0.85, minv=0.0, maxv=1.0))
    droplets = int(a.num("droplets", 6, minv=0, maxv=64))
    spread = float(a.num("spread", 1.35, minv=0.8, maxv=4.0))
    seed = int(a.num("seed", 0) or 0)
    level = detail_level(a)
    outline = _blot_outline(radius, lobes, irregularity, seed, level)
    scales = [0.90, 0.98, 1.0, 0.98, 0.88]
    heights = [0.0, thickness * 0.12, thickness * 0.34,
               thickness * 0.72, thickness]
    if dome > 1e-9:
        scales += [0.58, 0.06]
        heights += [thickness + dome * 0.68, thickness + dome]
    sections = [outline * scale for scale in scales]
    body = loft_solid(sections, heights, axis="z", caps=True, what="клякса")
    parts = [body]
    rng = np.random.default_rng(seed + 7919)
    placed: list[tuple[np.ndarray, float]] = []
    for _ in range(droplets):
        accepted = None
        for _attempt in range(160):
            angle = float(rng.uniform(0, 2 * math.pi))
            drop_r = float(radius * rng.uniform(0.035, 0.095))
            distance = float(radius * spread * rng.uniform(0.92, 1.35))
            center = np.array([math.cos(angle), math.sin(angle)]) * distance
            if np.min(np.linalg.norm(outline - center, axis=1)) < drop_r * 1.45:
                continue
            if any(np.linalg.norm(center - old) < (drop_r + old_r) * 1.35
                   for old, old_r in placed):
                continue
            accepted = (center, drop_r)
            break
        if accepted is None:
            a.scene.log("warn", "клякса: одну брызгу не удалось разместить без пересечения",
                        a.cmd.line)
            continue
        center, drop_r = accepted
        placed.append(accepted)
        rz = min(drop_r * 0.55, thickness * 0.42)
        matrix = np.eye(3, 4)
        matrix[0, 0] = drop_r
        matrix[1, 1] = drop_r * float(rng.uniform(0.78, 1.12))
        matrix[2, 2] = max(rz, 0.02)
        drop = mf.Manifold.sphere(1.0, _DETAIL_SIDES[level] * 2).transform(matrix)
        drop = drop.translate((float(center[0]), float(center[1]), max(rz, 0.02)))
        parts.append(drop)
    result = _combine(parts, "клякса и брызги")
    result = anchor(result, a.vec("at", 3, default=(0, 0, 0)),
                    a.boolean("center", False))
    out = make_solid(a.scene, name, result, a, kind="blot")
    out.meta.update({"seed": seed, "lobes": lobes, "droplets": len(placed)})
    out.notes.append(f"клякса: выступов {lobes}, брызг {len(placed)}, seed {seed}")
    _default_style(out, "#d51f72", 0.38, a)
    return out


# --------------------------------------------------------------------------- #
#  Узлы: открытые 3D-пути с настоящими переплетениями и свободными концами
# --------------------------------------------------------------------------- #
_KNOT_KINDS = {
    "простой": "простой", "overhand": "простой", "overhand_knot": "простой",
    "восьмерка": "восьмерка", "восьмёрка": "восьмерка", "figure8": "восьмерка",
    "figure_eight": "восьмерка", "бант": "бант", "bow": "бант", "шнурки": "бант",
    "галстук": "галстук", "tie": "галстук", "four_in_hand": "галстук",
}


def _raw_knot_paths(kind: str, detail: int) -> list[np.ndarray]:
    n = 48 + detail * 24
    if kind == "простой":
        t = np.linspace(0.28, 2 * math.pi - 0.28, n)
        return [np.stack([np.sin(t) + 2 * np.sin(2 * t),
                          np.cos(t) - 2 * np.cos(2 * t),
                          -np.sin(3 * t)], axis=1)]
    if kind == "восьмерка":
        t = np.linspace(0.35, 2 * math.pi - 0.35, n * 2)
        return [np.stack([(2 + np.cos(2 * t)) * np.cos(3 * t),
                          (2 + np.cos(2 * t)) * np.sin(3 * t),
                          np.sin(4 * t)], axis=1)]
    if kind == "бант":
        control = np.array([
            [-60, -15, 0], [-30, -15, 0], [0, 0, 8],
            [-20, 25, 6], [-45, 25, 2], [-50, 5, -2], [-25, -5, -6],
            [0, 0, 0], [25, -5, 6], [50, -5, 2], [45, -25, -2],
            [20, -25, -6], [0, 0, -8], [30, 15, 0], [60, 15, 0],
        ], dtype=float)
        return [catmull_rom(control, samples=_DETAIL_SAMPLES[detail])]
    # Галстучный четырёхручной узел — плоская лента, а не круглый шнур.
    control = np.array([
        [-10, 45, 0], [-10, 25, 0], [-5, 12, 3], [12, 15, 5],
        [15, 0, 4], [5, -12, 0], [-10, -15, -4], [-15, 0, -5],
        [-5, 15, -3], [5, 5, 4], [10, -15, 3], [15, -45, 0],
    ], dtype=float)
    return [catmull_rom(control, samples=_DETAIL_SAMPLES[detail])]


def _add_tails(path: np.ndarray, length: float) -> np.ndarray:
    if length <= 1e-9:
        return path
    start_t = path[1] - path[0]
    end_t = path[-1] - path[-2]
    start_t /= max(float(np.linalg.norm(start_t)), 1e-9)
    end_t /= max(float(np.linalg.norm(end_t)), 1e-9)
    steps = max(3, int(length / 3.0))
    head = path[0] - np.linspace(length, length / steps, steps)[:, None] * start_t
    tail = path[-1] + np.linspace(length / steps, length, steps)[:, None] * end_t
    return np.vstack([head, path, tail])


def _knot_paths(kind: str, size: float, radius: float, height: float,
                tail: float, detail: int) -> list[np.ndarray]:
    paths = _raw_knot_paths(kind, detail)
    all_points = np.vstack(paths)
    lo = all_points.min(axis=0)
    hi = all_points.max(axis=0)
    center_xy = (lo[:2] + hi[:2]) / 2.0
    span = max(float(hi[0] - lo[0]), float(hi[1] - lo[1]))
    z_center = (lo[2] + hi[2]) / 2.0
    z_span = max(float(hi[2] - lo[2]), 1e-9)
    actual_height = height if height > 0 else radius * (16.0 if kind == "галстук" else 7.0)
    fitted = []
    for path in paths:
        p = path.copy()
        p[:, :2] = (p[:, :2] - center_xy) * (size / max(span, 1e-9))
        p[:, 2] = (p[:, 2] - z_center) * (actual_height / z_span)
        fitted.append(_add_tails(p, tail))
    return fitted


@op("knot", aliases=("узел", "узлы", "rope_knot", "knots", "шнурок"),
    category="Примитивы",
    summary="Заготовки верёвочных узлов настоящим 3D-sweep: простой, восьмёрка, "
            "бант и галстучный. Ветви имеют высоту "
            "над/под и свободные концы; это не плоские значки и не замкнутые кольца.",
    example="восьмёрка = knot kind=восьмерка size=105 radius=2.6 height=18 tail=18\n"
            "бант = knot kind=бант size=100 radius=2.2 color=#c6a66a",
    params={"kind": "простой, восьмерка, бант или галстук (простой)",
            "size": "размер тела узла без концов, мм (100)",
            "radius": "радиус верёвки; для галстука — базовый размер ленты (2.5)",
            "height": "глубина переплетений над/под, мм (0 — авто; явное значение не ниже безопасного просвета)",
            "tail": "длина каждого свободного конца, мм (15)",
            "detail": "детализация 0…5: сплайн пути и сечение (3)",
            "at": "положение [x,y,z], по умолчанию низ на at",
            "center": "центрировать узел в at"},
    positional=["kind"])
def knot(a, name):
    raw_kind = (a.text("kind", "простой") or "простой").strip().lower()
    kind = _KNOT_KINDS.get(raw_kind)
    if kind is None:
        raise GeometryError(f"knot: неизвестная заготовка «{raw_kind}».",
                            hint="kind: простой, восьмерка, бант или галстук.")
    size = float(a.num("size", 100.0, minv=10.0))
    radius = float(a.num("radius", 2.5, minv=0.1))
    height = float(a.num("height", 0.0, minv=0.0))
    tail = float(a.num("tail", 15.0, minv=0.0))
    safe_height = radius * {"простой": 3.0, "восьмерка": 3.0,
                            "бант": 5.0, "галстук": 14.0}[kind]
    if 0 < height < safe_height:
        raise GeometryError(
            f"knot {kind}: height={height:g} слишком мало для radius={radius:g}.",
            hint=f"Оставьте height=0 для автоматического безопасного просвета или задайте не менее {safe_height:g} мм.")
    level = detail_level(a)
    paths = _knot_paths(kind, size, radius, height, tail, level)
    profile = (ellipse_profile(radius * 2.4, radius * 1.2, _DETAIL_SIDES[level] * 2)
               if kind == "галстук" else circle_profile(radius, _DETAIL_SIDES[level]))
    parts = [sweep_solid(path, profile, up_hint=(0, 0, 1),
                         what=f"узел {kind}", round_caps=0.65) for path in paths]
    result = _combine(parts, f"узел {kind}")
    if kind == "галстук":
        result = result.rotate((90.0, 0.0, 0.0))
    result = anchor(result, a.vec("at", 3, default=(0, 0, 0)),
                    a.boolean("center", False))
    out = make_solid(a.scene, name, result, a, kind="knot")
    out.meta.update({"knot_kind": kind, "rope_radius": radius})
    out.notes.append(f"узел: {kind}, верёвок {len(parts)}, концы с просветом")
    _default_style(out, "#c8a66b", 0.72, a)
    return out
