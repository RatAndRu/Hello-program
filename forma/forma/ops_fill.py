"""Наполнение: крупа в миске, галька в ящике, горка предметов.

Идея простая и физичная: контейнер мы не трогаем, а «сыпем» в него мелкие
детали сверху. Для каждой колонки сетки находим пол — первый луч вниз,
который упирается в поверхность, смотрящую вверх. Боковые лучи проверяют,
что колонка внутри полости, а не снаружи (иначе зёрна повисли бы над
ручкой кружки). Дальше колонка заполняется снизу вверх до уровня.

Всё детерминировано: seed задаёт раскладку, повороты и размеры, поэтому
одна и та же строка сценария даёт одну и ту же кашу.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import make_solid, merge_solids, op
from .ops_kit import _one, _placed

GRAINS = {
    "шар": "sphere", "шарик": "sphere", "sphere": "sphere",
    "горох": "pea", "горошек": "pea", "pea": "pea",
    "зерно": "grain", "крупа": "grain", "рис": "grain", "grain": "grain",
    "капля": "drop", "drop": "drop", "слеза": "drop",
    "куб": "cube", "кубик": "cube", "cube": "cube",
    "галька": "pebble", "камень": "pebble", "pebble": "pebble",
}
GRAIN_NAMES = {"sphere": "шар", "pea": "горох", "grain": "зерно",
               "drop": "капля", "cube": "куб", "pebble": "галька"}

MAX_GRAINS = 1600
MAX_GRAIN_MM = 30.0


def _unit_sphere(segments: int = 8) -> mf.Manifold:
    return mf.Manifold.sphere(0.5, int(segments))


def _grain_template(kind: str) -> mf.Manifold:
    """Единичное зерно: вписано в шар радиуса 0.5, центр в начале координат.

    Единый габарит нужен для просчёта укладки: если у всех зёрен радиус
    описанной сферы одинаков, шаг сетки гарантирует, что они не пересекутся.
    """
    if kind == "sphere":
        return _unit_sphere(8)
    if kind == "pea":
        return _unit_sphere(6)
    if kind == "cube":
        edge = 2.0 * 0.5 / math.sqrt(3.0)
        return mf.Manifold.cube((edge, edge, edge), center=True)
    if kind == "grain":
        # зерно риса/гречки: вытянутый эллипсоид с лёгким ребром
        base = _unit_sphere(6)
        return base.scale([1.0, 0.62, 0.44])
    if kind == "pebble":
        base = _unit_sphere(7)
        return base.scale([0.96, 0.86, 0.60])
    if kind == "drop":
        # капля: полусфера снизу и сужение вверх, вписана в шар радиуса 0.5
        steps = 14
        prof: list[tuple[float, float]] = [(0.0, -0.5)]
        for i in range(1, steps + 1):
            t = i / steps
            prof.append((0.30 * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2)), -0.5 + 0.3 * t))
        for i in range(1, steps + 1):
            u = i / steps
            prof.append((0.30 * max(0.0, (1.0 - u) ** 1.7), -0.2 + 0.7 * u))
        cs = mf.CrossSection([prof])
        return mf.Manifold.revolve(cs, 12)
    raise GeometryError(f"Неизвестное зерно «{kind}».")


def _grain_kind(a) -> str:
    raw = (a.text("grain") or "капля").strip().lower()
    kind = GRAINS.get(raw)
    if not kind:
        raise GeometryError(
            f"Неизвестная форма зерна «{raw}».",
            hint="Доступно: " + ", ".join(sorted(set(GRAIN_NAMES.values()))) + ".")
    return kind


def _rotation(rng: np.random.Generator, amount: float) -> np.ndarray:
    """Случайный поворот, «подмешанный» к единичному на долю amount."""
    q = rng.normal(size=4)
    q /= np.linalg.norm(q) or 1.0
    w, x, y, z = q
    rot = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    if amount >= 0.999:
        return rot
    angle = math.acos(max(-1.0, min(1.0, (np.trace(rot) - 1.0) / 2.0)))
    if angle < 1e-6:
        return np.eye(3)
    axis = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    norm = np.linalg.norm(axis)
    if norm < 1e-9:
        return np.eye(3)
    axis /= norm
    ang = angle * amount
    c, s = math.cos(ang), math.sin(ang)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + s * k + (1 - c) * (k @ k)


def _place(template: mf.Manifold, rng, size: float, rot_amount: float,
           stretch: float, pos) -> tuple[mf.Manifold, float]:
    """Ставит зерно: масштаб, поворот, посадка дном на пол. Возвращает (тело, высота)."""
    s = size * stretch
    scale = np.diag([s, s * (1.0 + rng.uniform(-0.12, 0.12)),
                     s * (1.0 + rng.uniform(-0.12, 0.12))])
    m = _rotation(rng, rot_amount) @ scale
    mat = np.column_stack([m, np.zeros(3)])
    body = template.transform(mat.tolist())
    bb = body.bounding_box()
    height = float(bb[5] - bb[2])
    body = body.translate([float(pos[0]), float(pos[1]), float(pos[2]) - float(bb[2])])
    return body, height


def _cast_down(manifold: mf.Manifold, x: float, y: float, z_from: float,
               z_to: float):
    hits = manifold.ray_cast([x, y, z_from], [x, y, z_to])
    return hits[0] if hits else None


def _open_sides(manifold: mf.Manifold, point, reach: float, need: float,
                dirs: int = 8) -> bool:
    """Колонка внутри полости: во все стороны есть стенка не ближе need."""
    px, py, pz = point
    for i in range(dirs):
        ang = 2.0 * math.pi * i / dirs
        ex = px + math.cos(ang) * reach
        ey = py + math.sin(ang) * reach
        hits = manifold.ray_cast([px, py, pz], [ex, ey, pz])
        if not hits:
            return False
        # distance у RayHit нормирована на длину луча — меряем по-настоящему
        near = min(float(np.linalg.norm(np.asarray(h.position) - np.asarray(point)))
                   for h in hits)
        if near < need:
            return False
    return True


def _build_grains(a, kind: str, size: float, count_cap: int, density: float,
                  rotate: float, seed: int, columns) -> tuple[list, int]:
    """Раскладывает зёрна по готовым колонкам: (x, y, пол, потолок)."""
    rng = np.random.default_rng(seed)
    template = _grain_template(kind)
    step = size * (0.82 + 0.30 * (1.0 - density))   # шаг по горизонтали
    grains: list[mf.Manifold] = []
    jitter = max(0.0, min(step - size, size * 0.3)) * 0.5 + size * 0.05
    for (x, y, floor, ceil) in columns:
        z = floor
        while z <= ceil - size * 0.25 and len(grains) < count_cap:
            gx = x + rng.uniform(-jitter, jitter)
            gy = y + rng.uniform(-jitter, jitter)
            stretch = 1.0 + rng.uniform(-0.5, 0.5) * 0.35
            body, height = _place(template, rng, size, rotate, stretch, (gx, gy, z))
            if z + height > ceil + size * 0.15:
                break
            grains.append(body)
            # укладываем со смятием: плотнее — меньше просветов между слоями
            z += max(size * 0.35, height * (0.62 + 0.28 * density))
        if len(grains) >= count_cap:
            break
    return grains, len(grains)


def _finish(a, name: str, grains: list[mf.Manifold], note: str):
    if not grains:
        raise GeometryError(
            "Не удалось ничего насыпать: похоже, у детали нет открытой полости сверху.",
            hint="Нужна миска, кружка или ящик с открытым верхом; "
                 "для горки без контейнера есть команда pile.")
    merged = (grains[0] if len(grains) == 1
              else mf.Manifold.batch_boolean(grains, mf.OpType.Add))
    if merged.is_empty():
        raise GeometryError("Наполнение получилось пустым.")
    if a.has("at") or a.boolean("center", False):
        merged = _placed(a, merged)
    solid = make_solid(a.scene, name, merged, a, kind="fill")
    solid.notes.append(note)
    return solid


def _align_z_to(normal) -> np.ndarray:
    """Матрица поворота, которая ставит +Z вдоль normal (склон горки)."""
    n = np.asarray(normal, dtype=np.float64)
    n /= np.linalg.norm(n) or 1.0
    z = np.array([0.0, 0.0, 1.0])
    if float(n @ z) > 0.999999:
        return np.eye(3)
    axis = np.cross(z, n)
    axis /= np.linalg.norm(axis)
    ang = math.acos(max(-1.0, min(1.0, float(n @ z))))
    c, s_ = math.cos(ang), math.sin(ang)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + s_ * k + (1 - c) * (k @ k)


def _normalize_template(m: mf.Manifold) -> mf.Manifold:
    """Приводит предмет к единичному габариту с центром в начале координат."""
    bb = m.bounding_box()
    size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    if size <= 1e-9:
        raise GeometryError("Предмет для горки получился пустым.")
    k = 1.0 / size
    centre = ((bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0)
    out = m.translate((-centre[0], -centre[1], -centre[2]))
    return out.scale((k, k, k))


def _pile_items(a, template: mf.Manifold, size: float, radius: float, height: float,
                count: int, seed: int, rotate: float, density: float) -> tuple[list, int]:
    """Горка из готовых предметов: укладываем их слоями, верхние — по нормали склона."""
    rng = np.random.default_rng(seed)
    items: list[mf.Manifold] = []
    p_exp = 1.7
    top_h = max(size * 0.8, height - size * 0.55)
    columns = _pile_columns(size * 0.92, radius, top_h)
    for (x, y, _floor, top) in columns:
        z = 0.0
        while z <= top - size * 0.15 and len(items) < count:
            r = math.hypot(x, y)
            slope = top_h * p_exp * (max(r, 1e-6) / radius) ** (p_exp - 1.0) / radius
            ang = math.atan2(y, x)
            normal = np.array([-slope * math.cos(ang), -slope * math.sin(ang), 1.0])
            normal /= np.linalg.norm(normal)
            # внутри насыпи предмет лежит как попало, на поверхности — по склону
            surface = z + size >= top - size * 0.1
            base_rot = _align_z_to(normal) if surface else np.eye(3)
            jitter = _rotation(rng, rotate)
            scale = size * (1.0 + rng.uniform(-0.12, 0.12))
            m = base_rot @ jitter @ np.diag([scale, scale, scale])
            body = template.transform(np.column_stack([m, np.zeros(3)]).tolist())
            bb = body.bounding_box()
            gx = x + rng.uniform(-size * 0.15, size * 0.15)
            gy = y + rng.uniform(-size * 0.15, size * 0.15)
            body = body.translate([gx, gy, z - float(bb[2])])
            items.append(body)
            z += size * (0.55 + 0.20 * density)
        if len(items) >= count:
            break
    return items, len(items)


@op("fill", aliases=("наполнить", "засыпать", "заполнение", "наполнение", "grains"),
    category="Форма и деформации",
    summary="Насыпает мелкие детали в открытую полость: крупа в миске, галька в ящике, "
            "конфеты в вазе. Уровень, плотность, форма зерна, повороты и seed — "
            "одна и та же строка всегда даёт одну и ту же раскладку.",
    example="тарелка = plate diameter=180 depth=55 wall=4\n"
            "каша = fill [тарелка] grain=зерно size=7 level=0.75 density=0.7 seed=3",
    params={"objects": "контейнер с открытым верхом (тарелка, миска, ящик)",
            "grain": "шар, горох, зерно, капля, куб или галька (капля)",
            "size": "характерный размер зерна, мм (6)",
            "level": "уровень наполнения 0…1 от глубины полости (0.8)",
            "density": "плотность укладки 0…1 (0.7)",
            "count": "предел числа зёрен (0 — по месту, не больше 1600)",
            "seed": "число для повтора раскладки (1)",
            "rotate": "случайный поворот 0…1 (0.6)",
            "inset": "зазор до стенки, мм (0.4)",
            "dome": "горка к центру 0…1: 0 — ровно, 1 — с горбом (0)",
            "as": "одно тело (по умолчанию) или отдельные объекты",
            "at": "сдвиг [x,y,z]", "center": "центрировать по высоте"},
    positional=["objects"])
def fill(a, name):
    base = _one(a, "fill")
    manifold = base.manifold
    bb = manifold.bounding_box()
    size = float(a.num("size", 6.0, minv=0.4))
    level = float(a.num("level", 0.8, minv=0.02, maxv=1.0) or 0.8)
    density = float(a.num("density", 0.7, minv=0.15, maxv=1.0) or 0.7)
    seed = int(a.num("seed", 1) or 1)
    rotate = float(a.num("rotate", 0.6, minv=0.0, maxv=1.0) or 0.0)
    inset = float(a.num("inset", 0.4, minv=0.0) or 0.0)
    limit = int(a.num("count", 0) or 0) or MAX_GRAINS
    limit = max(1, min(int(limit), MAX_GRAINS))
    dome = float(a.num("dome", 0.0, minv=0.0, maxv=1.0) or 0.0)
    separate = (a.text("as", "одно") or "одно").strip().lower() in (
        "отдельные", "отдельно", "отдельным", "separate", "objects")
    kind = _grain_kind(a)
    if base.kind in ("fill", "pile"):
        raise GeometryError("Наполнять можно только посуду и корпуса, а не горку.",
                            hint="Сначала соберите миску или ящик, потом команду fill.")

    span = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    reach = float(np.linalg.norm(span)) + 10.0
    for _attempt in range(4):
        step = size * (0.82 + 0.30 * (1.0 - density))
        cols_x = max(1, int((span[0] - 2 * size) // step))
        cols_y = max(1, int((span[1] - 2 * size) // step))
        x0 = (bb[0] + bb[3]) / 2.0 - (cols_x - 1) * step / 2.0
        y0 = (bb[1] + bb[4]) / 2.0 - (cols_y - 1) * step / 2.0

        columns = []
        z_min = None
        for iy in range(cols_y):
            for ix in range(cols_x):
                x = x0 + ix * step
                y = y0 + iy * step * 0.87
                hit = _cast_down(manifold, x, y, bb[5] + reach, bb[2] - reach)
                if hit is None or float(hit.normal[2]) < 0.35:
                    continue
                floor = float(hit.position[2])
                probe = floor + max(0.25, size * 0.4)
                if not _open_sides(manifold, (x, y, probe), reach,
                                   inset + size * 0.45):
                    continue
                columns.append((x, y, floor))
                z_min = floor if z_min is None else min(z_min, floor)
        if not columns or z_min is None:
            raise GeometryError(
                "В этой детали не нашлось полости, открытой вверх.",
                hint="Подойдёт тарелка, миска, кружка или корпус с открытым верхом. "
                     "Купол и закрытый сосуд наполнить нельзя.")
        z_level = z_min + level * max(1e-6, bb[5] - z_min)
        depth = max(1e-6, bb[5] - z_min)
        cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
        half = max(1e-6, min(bb[3] - bb[0], bb[4] - bb[1]) / 2.0)
        ready = []
        for (x, y, floor) in columns:
            # близость к центру: с dome крупа горбится посередине
            rr = min(1.0, math.hypot(x - cx, y - cy) / half)
            local_level = z_level + dome * depth * (1.0 - rr * rr) * (1.0 - level)
            # потолок: если над колонкой есть материал ниже уровня — не лезем в него
            ceil = local_level
            up = manifold.ray_cast([x, y, floor + 0.01], [x, y, local_level + reach])
            if up:
                top = float(up[0].position[2]) - size * 0.5
                if top < ceil:
                    ceil = top
            if ceil < floor + size * 0.5:
                continue
            ready.append((x, y, floor, ceil))
        need = 0
        for (_x, _y, f, c) in ready:
            if c > f:
                need += int((c - f) // (size * 0.85)) + 1
        if need <= limit or limit == MAX_GRAINS and size > MAX_GRAIN_MM:
            break
        grow = max(1.06, (need / limit) ** (1.0 / 3.0))
        size *= grow
        a.scene.log("info", f"fill: зёрен вышло бы {need} — размер поднят до "
                            f"{size:.1f} мм (предел {limit})", a.cmd.line)

    grains, made = _build_grains(a, kind, size, limit, density, rotate, seed, ready)
    if made < 1:
        raise GeometryError("Полость слишком мелкая для зерна такого размера.",
                            hint="Уменьшите size или увеличьте level.")
    note = f"наполнение: {made} зёрен «{GRAIN_NAMES.get(kind, kind)}» по {size:.1f} мм"
    a.scene.log("info", note, a.cmd.line)
    if not separate:
        return _finish(a, name, grains, note)
    if made > 150:
        raise GeometryError(
            f"Отдельными объектами можно делать не больше 150 зёрен, а их {made}.",
            hint="Увеличьте size, уменьшите level или оставьте as=одно.")
    solids = []
    for i, grain in enumerate(grains, 1):
        grain = _placed(a, grain) if (a.has("at") or a.boolean("center", False)) else grain
        item = make_solid(a.scene, f"{name}_{i}", grain, a, kind="fill")
        item.notes.append(note)
        solids.append(item)
    a.scene.log("info", f"наполнение: {made} отдельных объектов", a.cmd.line)
    return solids[-1]


def _pile_columns(size: float, radius: float, height: float) -> list:
    """Колонки насыпи: профиль конуса с мягким краем."""
    cols = max(1, int((2.0 * radius) // (size * 0.82)))
    step = 2.0 * radius / cols
    x0 = -0.5 * (cols - 1) * step
    out = []
    for iy in range(cols):
        for ix in range(cols):
            x = x0 + ix * step + (step * 0.5 if iy % 2 else 0.0)
            y = x0 + iy * step * 0.87
            r = math.hypot(x, y)
            if r > radius - size * 0.5:
                continue
            top = height * max(0.0, 1.0 - (r / radius) ** 1.7)
            if top < size * 0.6:
                continue
            out.append((x, y, 0.0, top))
    return out


@op("pile", aliases=("куча", "горка", "насыпь", "heap"), category="Форма и деформации",
    summary="Горка из мелких деталей на плоскости: песок, галька, конфеты, монеты. "
            "Основание, высота, плотность и seed задают форму.",
    example="горка = pile radius=120 height=45 grain=галька size=14 seed=5",
    params={"objects": "готовый предмет: горка сложится из его копий (необязательно)",
            "grain": "шар, горох, зерно, капля, куб или галька (галька)",
            "size": "характерный размер зерна, мм (14)",
            "radius": "радиус основания горки, мм (120)",
            "height": "высота горки, мм (45)",
            "density": "плотность укладки 0…1 (0.7)",
            "count": "предел числа зёрен (0 — по месту, не больше 1600)",
            "seed": "число для повтора раскладки (1)",
            "rotate": "случайный поворот 0…1 (0.8)",
            "at": "сдвиг [x,y,z]", "center": "центрировать по высоте"},
    positional=["objects"])
def pile(a, name):
    sources = a.solids() if (a.extra or a.has("objects")) else []
    custom = None
    if sources:
        custom = _normalize_template(merge_solids(sources))
        for s_ in sources:
            a.scene.consume(s_)
    kind = "custom" if custom is not None else _grain_kind(a)
    size = float(a.num("size", 14.0, minv=0.4))
    radius = float(a.num("radius", 120.0, minv=1.0))
    height = float(a.num("height", 45.0, minv=0.5))
    density = float(a.num("density", 0.7, minv=0.15, maxv=1.0) or 0.7)
    seed = int(a.num("seed", 1) or 1)
    rotate = float(a.num("rotate", 0.8, minv=0.0, maxv=1.0) or 0.0)
    limit = int(a.num("count", 0) or 0) or MAX_GRAINS
    limit = max(1, min(int(limit), MAX_GRAINS))

    if custom is not None:
        # горка из предметов: каждый лежит на склоне и наклонён по нормали
        volume = 0.5 * math.pi * radius * radius * height
        want = int(a.num("count", 0) or 0) or min(
            limit, max(6, int(volume / max(size ** 3 * 0.75, 1e-6))))
        grains, made = _pile_items(a, custom, size, radius, height, want,
                                   seed, rotate, density)
        label = "предметов"
    else:
        for _attempt in range(4):
            columns = _pile_columns(size, radius, height)
            need = sum(max(1, int(c // (size * 0.85))) for (_x, _y, _f, c) in columns)
            if need <= limit or size > MAX_GRAIN_MM:
                break
            size *= max(1.06, (need / limit) ** (1.0 / 3.0))
            a.scene.log("info", f"pile: зёрен вышло бы {need} — размер поднят до "
                                f"{size:.1f} мм (предел {limit})", a.cmd.line)
        grains, made = _build_grains(a, kind, size, limit, density, rotate, seed, columns)
        label = "шт."
    if made < 1:
        raise GeometryError("Горка не получилась: зерно крупнее её самой.",
                            hint="Уменьшите size или увеличьте radius/height.")
    if custom is not None:
        note = f"горка: {made} предметов по {size:.1f} мм"
    else:
        note = f"горка: {made} шт. «{GRAIN_NAMES.get(kind, kind)}» по {size:.1f} мм"
    a.scene.log("info", note, a.cmd.line)
    return _finish(a, name, grains, note)
