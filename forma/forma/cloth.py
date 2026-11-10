"""Драпировка: релаксация к равновесию вместо анимации.

Это не физический движок с историей кадров: считается **одно** состояние —
как детали улягутся под гравитацией на опоры. Отсюда три свойства, важных для
редактора твёрдых тел:

* результат детерминирован — та же строка ``.forma`` всегда даёт ту же сетку
  (порядок обхода фиксирован, критерий остановки — по смещению, а не по часам);
* состояние не хранится между сборками: в сцене только геометрия;
* длины рёбер удерживаются ограничениями: деформация ограничена, но конечное
  число шагов не гарантирует абсолютно нерастяжимую геометрию.

Из чего состоит расчёт:

1. **Частицы** — все вершины сетки детали (после подразбиения до шага ``mesh``).
   Для листа это обе стороны и торец: толщина уже есть в геометрии.
2. **Длины рёбер** — жёсткие связи. Поправки копятся по всем связям сразу и
   делятся на число связей узла (метод Якоби): это даёт векторный расчёт на
   numpy без циклов по цветам и без гонок за вершины.
3. **Изгиб** — связи «через ребро» (пара вершин напротив общего ребра): так
   изгибная жёсткость работает без углов и сингулярностей.
4. **Форма** (shape matching) — каждая связная часть тянется к своей исходной
   позе с весом ``rigid``: 0 — ткань, 1 — жёсткое тело. Кубик, звено цепи и
   пружина падают как тела, лист и рукав мнутся.
5. **Контакт с опорами** — настоящий, по треугольникам: ближайшая точка,
   выталкивание по нормали, трение по касательной. Опор может быть сколько
   угодно: стол, полка, пол — все сразу. Замкнутая оболочка ложится на опору
   своей геометрией, открытому листу толщина «достраивается» параметром.
6. **Толщина оболочки** — связи между противоположными сторонами тонкой
   детали: без них лист сминается в фольгу и теряет толщину.
7. **Самоколлизия** гибких частей — кандидаты вершина—треугольник за шаг,
   с исключением соседей и противоположных сторон одной стенки. Для полностью
   жёстких частей сохранён быстрый контакт частиц, чтобы звенья держали форму.

Шаг ограничен, но это приближённый решатель: быстрые столкновения рёбер,
очень тонкие опоры и сложные начальные самопересечения могут остаться. Итог
нескольких деталей дополнительно проверяется по их объёмному пересечению.
"""

from __future__ import annotations

import time

import numpy as np

from .errors import GeometryError
from .cloth_collision import SurfaceContacts

# Слова направления гравитации: как удобно писать в сцене.
GRAVITY_WORDS = {
    "z-": (0.0, 0.0, -1.0), "-z": (0.0, 0.0, -1.0), "вниз": (0.0, 0.0, -1.0),
    "z+": (0.0, 0.0, 1.0), "+z": (0.0, 0.0, 1.0), "вверх": (0.0, 0.0, 1.0),
    "x-": (-1.0, 0.0, 0.0), "x+": (1.0, 0.0, 0.0),
    "y-": (0.0, -1.0, 0.0), "y+": (0.0, 1.0, 0.0),
    "-x": (-1.0, 0.0, 0.0), "+x": (1.0, 0.0, 0.0),
    "-y": (0.0, -1.0, 0.0), "+y": (0.0, 1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
}


def parse_gravity(text, default=(0.0, 0.0, -1.0)) -> np.ndarray:
    """Направление гравитации: ``z-``, ``x+``, ``[0,0,-1]`` или пусто (вниз)."""
    raw = (text or "").strip().lower()
    if not raw:
        vector = np.asarray(default, dtype=float)
    elif raw in GRAVITY_WORDS:
        vector = np.asarray(GRAVITY_WORDS[raw], dtype=float)
    elif raw.startswith("["):
        body = raw.strip("[]")
        try:
            parts = [float(piece) for piece in body.replace(";", ",").split(",") if piece.strip()]
        except ValueError as exc:
            raise GeometryError("gravity: ожидается ось (z-) или вектор [x,y,z].",
                                hint="Например: gravity=z- или gravity=[0,0,-1].") from exc
        if len(parts) != 3:
            raise GeometryError("gravity: в векторе должно быть три числа.")
        vector = np.asarray(parts, dtype=float)
    else:
        raise GeometryError(f"gravity: неизвестное направление «{text}».",
                            hint="Оси: z- вниз, z+ вверх, x-, x+, y-, y+ или вектор [x,y,z].")
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        return np.zeros(3)
    return vector / length


def _edge_arrays(faces: np.ndarray):
    """Рёбра сетки без повторов: ``(E, 2)``."""
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    return np.unique(np.sort(edges, axis=1), axis=0).astype(np.int64)


def _bend_arrays(faces: np.ndarray, vertices: np.ndarray):
    """Пары «противоположные вершины через ребро» — связь на изгиб."""
    opposite: dict[tuple[int, int], list[int]] = {}
    for face in faces:
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        for u, v, w in ((a, b, c), (b, c, a), (c, a, b)):
            opposite.setdefault((min(u, v), max(u, v)), []).append(w)
    pairs = np.asarray([(ws[0], ws[1]) for ws in opposite.values()
                        if len(ws) == 2 and ws[0] != ws[1]], dtype=np.int64)
    if not len(pairs):
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    rest = np.linalg.norm(vertices[pairs[:, 1]] - vertices[pairs[:, 0]], axis=1)
    return pairs, rest


def _excluded_codes(faces: np.ndarray, count: int) -> np.ndarray:
    """Пары вершин, которые нельзя расталкивать: соседи по сетке (кольцо 2).

    Ткань касается себя именно через сгиб: вершины на разных сторонах одного
    ребра стоят рядом законно. Если их расталкивать, складка не образуется.
    """
    neighbours: dict[int, set[int]] = {}
    for face in faces:
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        for u, v in ((a, b), (b, c), (c, a)):
            neighbours.setdefault(u, set()).add(v)
            neighbours.setdefault(v, set()).add(u)
    codes: set[int] = set()
    for u, near in neighbours.items():
        ring = set(near)
        for v in near:
            ring |= neighbours.get(v, set())
        for v in ring:
            if v >= u:
                codes.add(u * count + v)
    if not codes:
        return np.zeros(0, dtype=np.int64)
    return np.asarray(sorted(codes), dtype=np.int64)


def _pair_codes(pairs: np.ndarray, count: int) -> np.ndarray:
    low = np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    high = np.maximum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    return low * count + high


def subdivide_to(vertices: np.ndarray, faces: np.ndarray, max_edge: float,
                 max_vertices: int = 12_000):
    """Дробит сетку до шага ``max_edge``, не выходя за бюджет частиц.

    Шаг выбирается так, чтобы число вершин уложилось в ``max_vertices``: один
    проход деления учетверяет сетку, поэтому уровень подбирается заранее.
    Делятся только длинные рёбра (схема «красное—зелёное»), короткие остаются
    как есть: у тонкого листа торец заведомо короче шага, и равномерное деление
    1→4 превратило бы его в микроскопические рёбра, на которых релаксация
    разваливается.

    Возвращает готовую к расчёту сетку: без «висячих» вершин и с сохранённой
    замкнутостью.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    step = max(float(max_edge), 1e-3)
    if len(faces) == 0 or len(vertices) == 0:
        return vertices, faces
    tri = vertices[faces]
    lengths = np.concatenate((
        np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
        np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
        np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1),
    ))
    min_rest = float(lengths.min()) if len(lengths) else step
    longest = float(lengths.max())
    target = step
    # проход деления учетверяет сетку, поэтому следующий проход применяем только
    # если он ещё укладывается в бюджет частиц
    for _ in range(8):
        if longest <= target:
            break
        new_vertices, new_faces = _refine_long(vertices, faces, target)
        if len(new_vertices) == len(vertices):
            break
        if max_vertices > 0 and len(new_vertices) > max_vertices:
            break
        vertices, faces = new_vertices, new_faces
    return _weld(vertices, faces, min(0.05 * target, 0.4 * min_rest))


def _weld(vertices: np.ndarray, faces: np.ndarray, tolerance: float):
    """Склеивает вершины ближе допуска и убирает вырожденные треугольники.

    Дробление тонкого листа даёт на торце силосы: рёбра в сотые доли шага.
    Такие рёбра бесполезны (длину 0.01 мм не удержать) и опасны — они делают
    матрицу жёсткости почти вырожденной. Склейка возвращает нормальный шаг.
    """
    if tolerance <= 0 or len(vertices) == 0:
        return vertices, faces
    for shift in (np.zeros(3), np.full(3, tolerance * 0.5)):
        if len(vertices) == 0:
            break
        grid = np.floor((vertices - shift) / tolerance).astype(np.int64)
        keys = _cell_keys(grid)
        _unique, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
        mapped = inverse[faces]
        good = (mapped[:, 0] != mapped[:, 1]) & (mapped[:, 1] != mapped[:, 2]) & \
            (mapped[:, 2] != mapped[:, 0])
        vertices, faces = vertices[first], mapped[good].astype(np.int64)
    return vertices, faces


def _refine_long(vertices: np.ndarray, faces: np.ndarray, target: float):
    count = len(vertices)
    tri = vertices[faces]
    long_ab = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1) > target
    long_bc = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1) > target
    long_ca = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1) > target
    if not np.any(long_ab | long_bc | long_ca):
        return vertices, faces

    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    low = edges.min(axis=1).astype(np.int64)
    high = edges.max(axis=1).astype(np.int64)
    keys = low * count + high
    order = np.argsort(keys, kind="stable")
    unique_keys, first = np.unique(keys[order], return_index=True)
    # середины только у тех рёбер, которые действительно делятся: иначе в сетке
    # копятся вершины, не связанные ни с одной гранью
    edge_length = np.linalg.norm(vertices[low[order][first]] - vertices[high[order][first]],
                                 axis=1)
    split = edge_length > target
    split_keys = unique_keys[split]
    midpoints = (vertices[low[order][first]] + vertices[high[order][first]])[split] * 0.5
    start = count

    def edge_mid(i: np.ndarray, j: np.ndarray) -> np.ndarray:
        key = np.minimum(i, j).astype(np.int64) * count + np.maximum(i, j).astype(np.int64)
        return start + np.searchsorted(split_keys, key)

    a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
    ab = edge_mid(a, b)
    bc = edge_mid(b, c)
    ca = edge_mid(c, a)
    pieces: list[np.ndarray] = []

    none = ~(long_ab | long_bc | long_ca)
    if np.any(none):
        pieces.append(np.stack((a[none], b[none], c[none]), axis=1))
    only = long_ab & ~long_bc & ~long_ca
    if np.any(only):
        pieces.append(np.stack((a[only], ab[only], c[only]), axis=1))
        pieces.append(np.stack((ab[only], b[only], c[only]), axis=1))
    only = ~long_ab & long_bc & ~long_ca
    if np.any(only):
        pieces.append(np.stack((b[only], bc[only], a[only]), axis=1))
        pieces.append(np.stack((bc[only], c[only], a[only]), axis=1))
    only = ~long_ab & ~long_bc & long_ca
    if np.any(only):
        pieces.append(np.stack((c[only], ca[only], b[only]), axis=1))
        pieces.append(np.stack((ca[only], a[only], b[only]), axis=1))
    only = long_ab & long_bc & ~long_ca
    if np.any(only):
        pieces.append(np.stack((a[only], ab[only], c[only]), axis=1))
        pieces.append(np.stack((ab[only], b[only], bc[only]), axis=1))
        pieces.append(np.stack((ab[only], bc[only], c[only]), axis=1))
    only = ~long_ab & long_bc & long_ca
    if np.any(only):
        pieces.append(np.stack((b[only], bc[only], a[only]), axis=1))
        pieces.append(np.stack((bc[only], c[only], ca[only]), axis=1))
        pieces.append(np.stack((bc[only], ca[only], a[only]), axis=1))
    only = long_ab & ~long_bc & long_ca
    if np.any(only):
        pieces.append(np.stack((c[only], ca[only], b[only]), axis=1))
        pieces.append(np.stack((ca[only], a[only], ab[only]), axis=1))
        pieces.append(np.stack((ca[only], ab[only], b[only]), axis=1))
    all_three = long_ab & long_bc & long_ca
    if np.any(all_three):
        pieces.append(np.stack((a[all_three], ab[all_three], ca[all_three]), axis=1))
        pieces.append(np.stack((ab[all_three], b[all_three], bc[all_three]), axis=1))
        pieces.append(np.stack((ca[all_three], bc[all_three], c[all_three]), axis=1))
        pieces.append(np.stack((ab[all_three], bc[all_three], ca[all_three]), axis=1))
    if not pieces:
        return vertices, faces
    return np.vstack((vertices, midpoints)), np.concatenate(pieces, axis=0).astype(np.int64)


def _cell_keys(index: np.ndarray, big: int = 2_000_003) -> np.ndarray:
    index = np.asarray(index, dtype=np.int64) + 1_000_000
    return (index[:, 0] * big + index[:, 1]) * big + index[:, 2]


def _closest_on_triangles(p: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Ближайшая точка треугольника (Ericson, Real-Time Collision Detection)."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-20, 1e-20, denom)
    v = vb / denom
    w = vc / denom
    result = a + ab * v[:, None] + ac * w[:, None]

    mask = (d1 <= 0) & (d2 <= 0)
    result[mask] = a[mask]
    mask = (d3 >= 0) & (d4 <= d3)
    result[mask] = b[mask]
    mask = (d6 >= 0) & (d5 <= d6)
    result[mask] = c[mask]
    mask = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / np.where(np.abs(d1 - d3) < 1e-20, 1e-20, d1 - d3)
    result[mask] = (a + ab * t[:, None])[mask]
    mask = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / np.where(np.abs(d2 - d6) < 1e-20, 1e-20, d2 - d6)
    result[mask] = (a + ac * t[:, None])[mask]
    mask = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t = (d4 - d3) / np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-20, 1e-20,
                             (d4 - d3) + (d5 - d6))
    result[mask] = (b + (c - b) * t[:, None])[mask]
    return result


class SupportField:
    """Треугольники опор в сетке ячеек: ближайшая точка и нормаль для частицы.

    Треугольники заранее раскладываются по ячейкам (с запасом в одну ячейку),
    поэтому частице достаточно одной ячейки: всё, что ближе ячейки, уже там.
    """

    def __init__(self, triangles: np.ndarray, cell: float):
        self.tri = np.ascontiguousarray(np.asarray(triangles, dtype=np.float64))
        if not len(self.tri):
            raise GeometryError("drape: у опор нет ни одного треугольника.")
        self.cell = float(max(cell, 1e-2))
        self.origin = self.tri.reshape(-1, 3).min(axis=0) - 2.0 * self.cell
        self._build()

    def _build(self):
        # Огромная опора (пол на всю сцену) не должна требовать миллионы ячеек:
        # ячейка укрупняется, пока перечень не станет обозримым.
        cell = self.cell
        while True:
            self.cell = cell
            self.origin = self.tri.reshape(-1, 3).min(axis=0) - 2.0 * cell
            lo, size = self._raster_bounds(cell)
            counts = size.prod(axis=1).astype(np.int64)
            total = int(counts.sum())
            if total <= 4_000_000:
                break
            cell *= 1.5
        tri_ids = np.repeat(np.arange(len(self.tri)), counts)
        starts = np.cumsum(counts) - counts
        local = np.arange(total, dtype=np.int64) - np.repeat(starts, counts)
        sx = size[tri_ids, 0]
        sy = size[tri_ids, 1]
        ix = local % sx
        iy = (local // sx) % sy
        iz = local // (sx * sy)
        cells = lo[tri_ids] + np.stack((ix, iy, iz), axis=1)
        keys = _cell_keys(cells)
        order = np.argsort(keys, kind="stable")
        self.sorted_keys = keys[order]
        self.sorted_tri = tri_ids[order].astype(np.int64)

    def _raster_bounds(self, cell: float):
        origin = self.tri.reshape(-1, 3).min(axis=0) - 2.0 * cell
        lo = np.floor((self.tri.min(axis=1) - origin) / cell).astype(np.int64) - 1
        hi = np.floor((self.tri.max(axis=1) - origin) / cell).astype(np.int64) + 1
        return lo, np.maximum(hi - lo + 1, 1)

    def candidates(self, points: np.ndarray):
        """Индексы пар ``(частица, треугольник)`` для одной ячейки на частицу."""
        index = np.floor((points - self.origin) / self.cell).astype(np.int64)
        keys = _cell_keys(index)
        left = np.searchsorted(self.sorted_keys, keys, side="left")
        right = np.searchsorted(self.sorted_keys, keys, side="right")
        sizes = right - left
        active = sizes > 0
        if not np.any(active):
            empty = np.zeros(0, dtype=np.int64)
            return empty, empty
        starts = np.repeat(left[active], sizes[active])
        inner = np.arange(int(sizes.sum()), dtype=np.int64) - np.repeat(
            np.cumsum(sizes[active]) - sizes[active], sizes[active])
        owners = np.repeat(np.nonzero(active)[0], sizes[active])
        return owners, self.sorted_tri[starts + inner]

    def closest(self, points: np.ndarray):
        """``(distance, point, normal)`` — по нормали: снаружи > 0, внутри < 0.

        Треугольник выбирается по **обычному** расстоянию до него, а знак берётся
        из нормали этого же треугольника. Если выбирать по знаковой величине,
        боковые грани «выигрывают» у верхней и деталь проваливается мимо опоры:
        точка над столом оказывается «внутри» по всем четырём боковым плоскостям.
        """
        count = len(points)
        distance = np.full(count, np.inf)
        point = np.zeros((count, 3))
        normal_out = np.zeros((count, 3))
        normal_out[:, 2] = 1.0
        owners, tri_ids = self.candidates(points)
        if len(owners):
            tri = self.tri[tri_ids]
            closest = _closest_on_triangles(points[owners], tri)
            normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            norm = np.linalg.norm(normal, axis=1)
            good = norm > 1e-12
            normal[good] /= norm[good, None]
            delta = points[owners] - closest
            flat = np.linalg.norm(delta, axis=1)
            signed = np.einsum("ij,ij->i", delta, normal)
            # нормаль обошла плоскость треугольника: считаем точку снаружи
            beyond = ~good | (np.abs(signed) < 1e-9)
            if np.any(beyond):
                signed[beyond] = flat[beyond]
                normal[beyond] = delta[beyond] / np.maximum(flat[beyond], 1e-12)[:, None]
                normal[beyond & ~good] = np.array([0.0, 0.0, 1.0])
            # по каждой частице — самый близкий треугольник; дубликаты в
            # fancy-индексации перезаписывают друг друга, поэтому берём первые
            order = np.lexsort((flat, owners))
            ordered = owners[order]
            first = np.ones(len(order), dtype=bool)
            first[1:] = ordered[1:] != ordered[:-1]
            pick = order[first]
            ids = owners[pick]
            distance[ids] = signed[pick]
            point[ids] = closest[pick]
            normal_out[ids] = normal[pick]
        return distance, point, normal_out


class ParticleHash:
    """Сетка частиц для самоколлизии: пары ближе допуска, кроме соседей по сетке."""

    def __init__(self, points: np.ndarray, cell: float):
        self.cell = float(max(cell, 1e-3))
        self.count = len(points)
        self.origin = points.min(axis=0) - self.cell
        self.index = np.floor((points - self.origin) / self.cell).astype(np.int64)
        keys = _cell_keys(self.index)
        order = np.argsort(keys, kind="stable")
        self.sorted_keys = keys[order]
        self.sorted_ids = order.astype(np.int64)
        self.offsets = np.array([[dx, dy, dz] for dx in (0, 1) for dy in (-1, 0, 1)
                                 for dz in (-1, 0, 1)], dtype=np.int64)

    def pairs(self, points: np.ndarray, min_distance: float, excluded: np.ndarray):
        """Пары ``(i, j)``, ``i < j``, которые ближе ``min_distance``."""
        found: list[np.ndarray] = []
        for offset in self.offsets:
            keys = _cell_keys(self.index + offset)
            left = np.searchsorted(self.sorted_keys, keys, side="left")
            right = np.searchsorted(self.sorted_keys, keys, side="right")
            sizes = right - left
            active = sizes > 0
            if not np.any(active):
                continue
            starts = np.repeat(left[active], sizes[active])
            inner = np.arange(int(sizes.sum()), dtype=np.int64) - np.repeat(
                np.cumsum(sizes[active]) - sizes[active], sizes[active])
            other = self.sorted_ids[starts + inner]
            owner = np.repeat(np.nonzero(active)[0], sizes[active])
            keep = owner < other
            if not np.any(keep):
                continue
            owner, other = owner[keep], other[keep]
            delta = points[other] - points[owner]
            distance = np.linalg.norm(delta, axis=1)
            close = distance < min_distance
            if np.any(close):
                found.append(np.stack((owner[close], other[close]), axis=1))
        if not found:
            return np.zeros((0, 2), dtype=np.int64)
        pairs = np.unique(np.concatenate(found, axis=0), axis=0)
        if len(excluded) and len(pairs):
            pairs = pairs[~np.isin(_pair_codes(pairs, self.count), excluded)]
        return pairs


def is_closed(faces: np.ndarray) -> bool:
    """Замкнута ли сетка: каждое ребро принадлежит ровно двум треугольникам.

    От этого зависит контакт с опорами. У замкнутой детали толщина уже в
    геометрии, и частицы надо пускать ровно на поверхность опоры. У открытого
    листа толщины нет — её задаёт параметр ``thickness``, и частицы держатся на
    половине этой толщины над опорой.
    """
    edges = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]],
                                    faces[:, [2, 0]]), axis=0), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(len(unique)) and bool(np.all(counts == 2))


def vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Сглаженные нормали вершин (площадные веса)."""
    tri = vertices[faces]
    face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    count = len(vertices)
    normal = np.zeros((count, 3))
    for axis in range(3):
        for corner in range(3):
            normal[:, axis] += np.bincount(faces[:, corner],
                                           weights=face_normals[:, axis], minlength=count)
    length = np.linalg.norm(normal, axis=1)
    good = length > 1e-12
    normal[good] /= length[good, None]
    return normal


def shell_pairs(vertices: np.ndarray, faces: np.ndarray, thickness: float,
                opposing_only: bool = True):
    """Пары вершин «сквозь толщину» и их исходные расстояния.

    У тонкой оболочки обе стороны — отдельные частицы, и ничто не мешает им
    сойтись: лист превращается в смятую фольгу, толщина исчезает. Связи между
    противоположными сторонами держат её ровно так, как деталь была построена.
    Пары ищутся по нормали, поэтому соседи по той же стороне в них не попадают.
    """
    thickness = float(max(thickness, 1e-3))
    if len(vertices) < 8:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    normal = vertex_normals(vertices, faces)
    reach = 2.2 * thickness
    grid = ParticleHash(vertices, reach)
    pairs = grid.pairs(vertices, reach, np.zeros(0, dtype=np.int64))
    if not len(pairs):
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    delta = vertices[pairs[:, 1]] - vertices[pairs[:, 0]]
    distance = np.linalg.norm(delta, axis=1)
    good = distance > 1e-6
    if not np.any(good):
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    pairs, delta, distance = pairs[good], delta[good], distance[good]
    direction = delta / distance[:, None]
    # у противоположных сторон нормали смотрят в разные стороны, поэтому
    # важна не сторона, а совпадение линии пары с нормалью
    facing = np.abs(np.einsum("ij,ij->i", direction, normal[pairs[:, 0]]))
    opposite = np.einsum("ij,ij->i", normal[pairs[:, 0]], normal[pairs[:, 1]])
    aligned = (facing > (0.3 if opposing_only else 0.7)) & ((opposite < -0.2) if opposing_only else True)
    if not np.any(aligned):
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    pairs, distance = pairs[aligned], distance[aligned]
    order = np.lexsort((distance, pairs[:, 0]))
    pairs, distance = pairs[order], distance[order]
    first = np.ones(len(pairs), dtype=bool)
    first[1:] = pairs[1:, 0] != pairs[:-1, 0]
    pairs, distance = pairs[first], distance[first]
    if opposing_only:
        # У оболочки каждой вершине отвечает одна вершина с другой стороны.
        # Иначе цепочка пересекающихся пар связывает целую область и рвёт
        # рукав при столкновении.
        order = np.argsort(distance, kind="stable")
        occupied = np.zeros(len(vertices), dtype=bool)
        chosen = []
        for slot in order:
            a, b = pairs[slot]
            if not occupied[a] and not occupied[b]:
                occupied[a] = occupied[b] = True
                chosen.append(slot)
        pairs, distance = pairs[chosen], distance[chosen]
    return pairs.astype(np.int64), distance


def _components(faces: np.ndarray, count: int) -> np.ndarray:
    """Связные части сетки: подпись для каждой вершины."""
    parent = np.arange(count)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for face in faces:
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        for u, v in ((a, b), (b, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[rv] = ru
    return np.array([find(i) for i in range(count)], dtype=np.int64)


def _thickness_of(vertices: np.ndarray, faces: np.ndarray) -> float:
    tri = vertices[faces]
    volume = float(np.einsum("ij,ij->i", tri[:, 0],
                             np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)
    area = float(0.5 * np.linalg.norm(
        np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum())
    if area <= 1e-9:
        return 0.0
    return 2.0 * abs(volume) / area              # оценка толщины оболочки


def _rigid_weight(vertices: np.ndarray, faces: np.ndarray,
                  nodes: np.ndarray | None = None) -> float:
    """Насколько кусок держит форму.

    Два признака сразу, иначе тонкая проволока звена цепи считалась бы тканью:

    * абсолютная толщина ``2V/A`` — тонкий лист гнётся, толстая плита нет;
    * толщина относительно собственного размера — у звена цепи проволока
      3 мм при звене 26 мм, и это уже тело, а не ткань; у скатерти 0.4 мм
      при 200 мм — наоборот.
    """
    thickness = _thickness_of(vertices, faces)
    if thickness <= 0.0:
        return 0.0
    absolute = (thickness - 1.5) / 4.5           # 1.5 мм — ткань, 6 мм — тело
    if nodes is None:
        nodes = np.unique(faces)
    size = float(np.max(np.ptp(vertices[nodes], axis=0))) if len(nodes) else 0.0
    relative = (thickness / size - 0.02) / 0.04 if size > 1e-9 else 1.0
    return float(min(1.0, max(0.0, absolute, relative)))


def auto_rigid(vertices: np.ndarray, faces: np.ndarray) -> float:
    """Тонкое гнётся, толстое держит форму."""
    return _rigid_weight(vertices, faces)


def auto_rigid_parts(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """То же, но для каждой связной части отдельно.

    Цепь, пружина или набор корпусов состоят из кусков: каждое звено должно
    держать свою форму, даже если рядом лежит тонкая ткань.
    """
    components = _components(faces, len(vertices))
    keys = np.unique(components)
    weights = np.zeros(len(keys), dtype=np.float64)
    for slot, key in enumerate(keys):
        mine = faces[components[faces[:, 0]] == key]
        if len(mine) < 4:
            weights[slot] = 1.0
            continue
        weights[slot] = _rigid_weight(vertices, mine)
    return weights


def place(vertices: np.ndarray, supports: np.ndarray, gravity: np.ndarray,
          gap: float) -> np.ndarray:
    """Ставит деталь вплотную к сцене: её крайняя точка — над верхом опор.

    Без этого падение занимало бы все шаги: расчёт интересен не полётом, а тем,
    как деталь ложится.
    """
    if not len(supports) or not np.any(gravity):
        return vertices.copy()
    axis = gravity / np.linalg.norm(gravity)
    # «самая нижняя» точка детали и «самая верхняя» точка сцены: по оси гравитации
    lowest = float((vertices @ axis).max())
    scene_top = float((np.asarray(supports).reshape(-1, 3) @ axis).min())
    shift = (scene_top - float(gap)) - lowest
    return vertices + axis * shift


def _shell_pairs_by_component(vertices: np.ndarray, faces: np.ndarray,
                              components: np.ndarray, weights: np.ndarray,
                              thickness: float):
    """Связи стенки ищутся внутри каждого гибкого куска, не между слоями.

    Два полотнища могут изначально стоять ближе собственной толщины. Общий
    поиск тогда выбрал бы ближайшие вершины разных листов и потерял бы связи
    между сторонами самого материала.
    """
    all_pairs, all_rest = [], []
    for slot, key in enumerate(np.unique(components)):
        if weights[slot] >= 0.7:
            continue
        ids = np.nonzero(components == key)[0]
        mine = faces[components[faces[:, 0]] == key]
        if not len(ids) or not len(mine):
            continue
        remap = np.full(len(vertices), -1, dtype=np.int64)
        remap[ids] = np.arange(len(ids))
        local_faces = remap[mine]
        local_vertices = vertices[ids]
        natural = _thickness_of(local_vertices, local_faces) or thickness
        pairs, rest = shell_pairs(local_vertices, local_faces, max(thickness, natural))
        if len(pairs):
            all_pairs.append(ids[pairs])
            all_rest.append(rest)
    if not all_pairs:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    return np.concatenate(all_pairs), np.concatenate(all_rest)


def _volume_data(vertices: np.ndarray, faces: np.ndarray):
    """Знаковый объём замкнутой поверхности и его градиент по вершинам."""
    tri = vertices[faces]
    cross_bc = np.cross(tri[:, 1], tri[:, 2])
    volume = float(np.einsum("ij,ij->i", tri[:, 0], cross_bc).sum() / 6.0)
    cross_ca = np.cross(tri[:, 2], tri[:, 0])
    cross_ab = np.cross(tri[:, 0], tri[:, 1])
    grad = np.zeros_like(vertices)
    for axis in range(3):
        grad[:, axis] = (np.bincount(faces[:, 0], weights=cross_bc[:, axis], minlength=len(vertices))
                         + np.bincount(faces[:, 1], weights=cross_ca[:, axis], minlength=len(vertices))
                         + np.bincount(faces[:, 2], weights=cross_ab[:, axis], minlength=len(vertices))) / 6.0
    return volume, grad


def simulate(vertices: np.ndarray, faces: np.ndarray, supports: np.ndarray, *,
             gravity: np.ndarray, g: float = 0.2, steps: int = 55,
             iterations: int = 14, stiffness: float = 1.0, bend: float = 0.25,
             damping: float = 0.88, friction: float = 0.6, rigid: float = 0.0,
             thickness: float = 0.5, self_collision: bool = True,
             self_gap: float | None = None, pinned: np.ndarray | None = None,
             tolerance: float = 0.01, stable_steps: int = 10, relax: float = 1.4, gap: float = 0.0) -> dict:
    """Релаксация к равновесию. Возвращает новые вершины и измерения."""
    started = time.perf_counter()
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    count = len(vertices)
    if count == 0 or len(faces) == 0:
        raise GeometryError("drape: пустая сетка.")
    gravity = np.asarray(gravity, dtype=np.float64)
    if pinned is None:
        pinned = np.zeros(count, dtype=bool)
    pinned = np.asarray(pinned, dtype=bool)
    free = ~pinned

    thickness = max(float(thickness), 0.02)
    closed = is_closed(faces)
    median_edge = float(np.median(
        np.linalg.norm(vertices[faces[:, 1]] - vertices[faces[:, 0]], axis=1)))
    cell = max(4.0, 1.25 * median_edge, 6.0 * thickness)
    max_move = min(cell * 0.5, 1.0)
    # Замкнутая оболочка ложится на опору своей геометрией: частица уходит не
    # глубже поверхности. Открытому листу толщины не хватает — её задаёт
    # параметр thickness, и частицы держатся на половине толщины над опорой.
    # Если пускать к поверхности и тех и других, тонкий лист расплющивается:
    # обе его стороны встают на одну высоту.
    offset = (0.0 if closed else thickness * 0.5) + max(float(gap), 0.0)

    # --- предварительные данные: рёбра, изгиб, соседи, связные части ---
    edges = _edge_arrays(faces)
    rest = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    bend_pairs, bend_rest = _bend_arrays(faces, vertices)
    components = _components(faces, count)
    comp_ids = [np.nonzero(components == key)[0] for key in np.unique(components)]
    rest_local = [vertices[ids] - vertices[ids].mean(axis=0) for ids in comp_ids]
    if rigid is None:
        rigid_weights = np.zeros(len(comp_ids))
    else:
        given = np.atleast_1d(np.asarray(rigid, dtype=np.float64))
        if given.size == 1:
            rigid_weights = np.full(len(comp_ids), float(given[0]))
        elif given.size == len(comp_ids):
            rigid_weights = given.astype(np.float64)
        else:
            raise GeometryError("drape: rigid задан не по числу частей детали.",
                                hint=f"Частей {len(comp_ids)}, значений {given.size}.")
    rigid_only = bool(len(rigid_weights) and np.all(rigid_weights >= 0.7))
    volume_constraints = []
    if not rigid_only:
        for slot, ids in enumerate(comp_ids):
            if rigid_weights[slot] >= 0.7:
                continue
            local_faces = faces[components[faces[:, 0]] == components[ids[0]]]
            if len(local_faces) and is_closed(local_faces):
                volume, _ = _volume_data(vertices, local_faces)
                if abs(volume) > 1e-9:
                    volume_constraints.append((local_faces, volume))

    # У стенки сохраняем не только расстояние между сторонами, но и их
    # направление по нормали: иначе обе поверхности могут соскользнуть друг
    # относительно друга и сплющиться на опоре.
    if rigid_only:
        natural = _thickness_of(vertices, faces) or thickness
        shell, shell_rest = shell_pairs(vertices, faces, max(thickness, natural),
                                        opposing_only=False)
    else:
        shell, shell_rest = _shell_pairs_by_component(vertices, faces, components,
                                                       rigid_weights, thickness)
    shell_sign = np.ones(len(shell))
    if len(shell) and not rigid_only:
        n0 = vertex_normals(vertices, faces)
        signs = np.einsum("ij,ij->i", vertices[shell[:, 1]] - vertices[shell[:, 0]],
                          n0[shell[:, 0]] - n0[shell[:, 1]])
        shell_sign = np.where(signs < 0, -1.0, 1.0)
    self_distance = ((max(0.02, min(0.8, 1.5 * thickness)) if closed
                      else 0.5 * thickness) if self_collision else 0.0)
    if rigid_only and self_collision:
        self_distance = thickness * 0.75
    if self_collision and self_gap is not None:
        self_distance = max(float(self_gap), 1e-4)
    self_contacts = (SurfaceContacts(vertices, faces, shell, self_distance, components, -gravity)
                     if self_collision and not rigid_only else None)
    rigid_excluded = _excluded_codes(faces, count) if self_collision and rigid_only else None

    # --- степени частиц и индексы для общей поправки (метод Якоби) ---
    # рёбра и изгиб складываются в один проход: две «разбросанные» суммы на
    # три координаты вместо десятка bincount на каждую группу рёбер
    edge_a, edge_b = edges[:, 0], edges[:, 1]
    pair_a = np.concatenate((edge_a, bend_pairs[:, 0] if len(bend_pairs)
                             else np.zeros(0, dtype=np.int64),
                             shell[:, 0] if rigid_only and len(shell) else np.zeros(0, dtype=np.int64)))
    pair_b = np.concatenate((edge_b, bend_pairs[:, 1] if len(bend_pairs)
                             else np.zeros(0, dtype=np.int64),
                             shell[:, 1] if rigid_only and len(shell) else np.zeros(0, dtype=np.int64)))
    degree = np.bincount(pair_a, minlength=count) + np.bincount(pair_b, minlength=count)
    degree = np.maximum(degree, 1).astype(np.float64)
    axis_of = np.arange(3, dtype=np.int64)
    index_a = (pair_a[:, None] * 3 + axis_of).ravel()
    index_b = (pair_b[:, None] * 3 + axis_of).ravel()

    supports = np.asarray(supports, dtype=np.float64) if supports is not None else None
    field = SupportField(supports, cell) if supports is not None and len(supports) else None
    position = (place(vertices, supports, gravity, gap=cell * 0.02)
                if field is not None else vertices.copy())
    # закрепления берутся уже после постановки на сцену: иначе закреплённые узлы
    # остаются там, где деталь была до расчёта, и ткань растягивается к ним
    fixed = position[pinned].copy()
    previous = position.copy()
    contacts = 0
    self_pairs = 0
    still = 0
    converged_at = int(steps)
    converged = False
    movement = 0.0
    total_contacts = 0

    support_contact = np.zeros(count, dtype=bool)
    support_normal = np.zeros((count, 3), dtype=np.float64)
    for step in range(int(steps)):
        velocity = (position - previous) * float(damping)
        speed = np.linalg.norm(velocity, axis=1)
        velocity *= np.minimum(1.0, max_move / np.maximum(speed, 1e-12))[:, None]
        previous = position.copy()
        position[free] += velocity[free] + gravity * float(g)
        position[pinned] = fixed
        if self_contacts is not None:
            found, _overlap = self_contacts.project(previous, position, free,
                                                     support_contact, rounds=12)
            self_pairs = max(self_pairs, found)

        for it in range(int(iterations)):
            # --- длины рёбер и изгиб: одна общая поправка (метод Якоби) ---
            delta = position[edge_b] - position[edge_a]
            length = np.linalg.norm(delta, axis=1)
            share = ((length - rest) * float(stiffness)
                     / np.maximum(length, 1e-12) * 0.5)[:, None]
            push_edge = delta * share
            if len(bend_pairs):
                a, b = bend_pairs[:, 0], bend_pairs[:, 1]
                delta = position[b] - position[a]
                length = np.linalg.norm(delta, axis=1)
                share = ((length - bend_rest) * float(bend)
                         / np.maximum(length, 1e-12) * 0.5)[:, None]
                push = np.concatenate((push_edge, delta * share), axis=0)
            else:
                push = push_edge
            if rigid_only and len(shell):
                delta = position[shell[:, 1]] - position[shell[:, 0]]
                length = np.linalg.norm(delta, axis=1)
                share = ((length - shell_rest) / np.maximum(length, 1e-12) * 0.5)[:, None]
                push = np.concatenate((push, delta * share), axis=0)
            acc = (np.bincount(index_a, weights=push.ravel(), minlength=count * 3)
                   - np.bincount(index_b, weights=push.ravel(), minlength=count * 3))
            acc = acc.reshape(count, 3)
            position[free] += acc[free] * float(relax) / degree[free, None]

            if np.any(rigid_weights > 0):           # форма целых частей
                for slot, ids in enumerate(comp_ids):
                    if rigid_weights[slot] <= 0:
                        continue
                    current = position[ids]
                    center = current.mean(axis=0)
                    source = rest_local[slot]
                    try:
                        u, _s, vt = np.linalg.svd((current - center).T @ source)
                    except np.linalg.LinAlgError:
                        continue
                    rotation = u @ vt
                    if np.linalg.det(rotation) < 0:
                        u[:, -1] *= -1
                        rotation = u @ vt
                    goal = source @ rotation.T + center
                    position[ids] += (goal - current) * float(rigid_weights[slot])

            if field is not None and (it % 2 == 0 or it == iterations - 1):
                distance, _point, normal = field.closest(position)
                near = np.isfinite(distance) & (distance < offset)
                support_contact = np.isfinite(distance) & (distance < offset + 0.01)
                support_normal = normal
                if np.any(near):
                    ids = np.nonzero(near)[0]
                    position[ids] += normal[ids] * (offset - distance[ids])[:, None]
                    contacts = max(contacts, int(len(ids)))
            if len(shell) and not rigid_only:
                a, b = shell[:, 0], shell[:, 1]
                delta = position[b] - position[a]
                normal = vertex_normals(position, faces)
                direction = normal[a] - normal[b]
                norm = np.linalg.norm(direction, axis=1)
                direction /= np.maximum(norm, 1e-12)[:, None]
                target = direction * (shell_sign * shell_rest)[:, None]
                correction = delta - target
                wa = (free[a] & ~support_contact[a]).astype(float)
                wb = (free[b] & ~support_contact[b]).astype(float)
                # Обе стороны могут быть прижаты к одной опоре после большого
                # шага. Тогда освобождаем ту сторону, которая должна смотреть
                # от опоры наружу; иначе толщина уже никогда не восстановится.
                both = support_contact[a] & support_contact[b]
                toward = np.einsum("ij,ij->i", target, support_normal[a])
                wa[both] = (free[a] & (toward <= 0.05 * shell_rest))[both]
                wb[both] = (free[b] & (toward >= -0.05 * shell_rest))[both]
                total = np.maximum(wa + wb, 1e-9)
                shell_degree = (np.bincount(a, weights=wa, minlength=count)
                                + np.bincount(b, weights=wb, minlength=count))
                for axis in range(3):
                    acc = (np.bincount(a, weights=correction[:, axis] * wa / total, minlength=count)
                           - np.bincount(b, weights=correction[:, axis] * wb / total, minlength=count))
                    position[:, axis] += acc * 0.8 / np.maximum(shell_degree, 1.0)
            # Приближённо удерживаем объём материала каждой замкнутой гибкой
            # части, не объём её полости. Это не гарантия локальной толщины.
            if volume_constraints:
                for local_faces, target_volume in volume_constraints:
                    volume, grad = _volume_data(position, local_faces)
                    grad[~free | support_contact] = 0.0
                    denom = float(np.einsum("ij,ij->", grad, grad))
                    if denom > 1e-12:
                        adjustment = (target_volume - volume) / denom * grad
                        magnitudes = np.linalg.norm(adjustment, axis=1)
                        adjustment *= np.minimum(1.0, 0.2 / np.maximum(magnitudes, 1e-12))[:, None]
                        position += adjustment
            position[pinned] = fixed

        if friction > 0 and field is not None:       # трение — один раз за шаг
            distance, _point, normal = field.closest(position)
            near = np.isfinite(distance) & (distance < offset + 1e-3)
            if np.any(near):
                ids = np.nonzero(near)[0]
                moved = position[ids] - previous[ids]
                along = np.einsum("ij,ij->i", moved, normal[ids])
                moved -= normal[ids] * along[:, None]
                position[ids] -= moved * float(friction)
                position[pinned] = fixed

        if rigid_excluded is not None:
            grid = ParticleHash(position, max(self_distance, 1e-3))
            pairs = grid.pairs(position, self_distance, rigid_excluded)
            if len(pairs):
                self_pairs = max(self_pairs, len(pairs))
                delta = position[pairs[:, 1]] - position[pairs[:, 0]]
                length = np.maximum(np.linalg.norm(delta, axis=1), 1e-9)
                normal = delta / length[:, None]
                wa = free[pairs[:, 0]].astype(float)
                wb = free[pairs[:, 1]].astype(float)
                correction = normal * ((self_distance - length) / np.maximum(wa + wb, 1e-9))[:, None]
                position[pairs[:, 0]] -= correction * wa[:, None]
                position[pairs[:, 1]] += correction * wb[:, None]
            position[pinned] = fixed
        if self_contacts is not None:
            found, _overlap = self_contacts.project(previous, position, free,
                                                     support_contact, rounds=12)
            self_pairs = max(self_pairs, found)
            if field is not None:
                distance, _point, normal = field.closest(position)
                near = np.isfinite(distance) & (distance < offset)
                position[near] += normal[near] * (offset - distance[near])[:, None]
            position[pinned] = fixed

        if not np.all(np.isfinite(position)) or float(np.max(np.abs(position))) > 1e7:
            raise GeometryError("drape: расчёт потерял устойчивость.",
                                hint="Уменьшите g, увеличьте iterations или шаг сетки mesh.")
        total_contacts = max(total_contacts, contacts)
        movement = float(np.max(np.linalg.norm(position - previous, axis=1)))
        if movement < tolerance:
            still += 1
            if still >= int(stable_steps):
                converged_at = step + 2 - still
                converged = True
                break
        else:
            still = 0

    final_lengths = np.linalg.norm(position[edges[:, 1]] - position[edges[:, 0]], axis=1)
    # деформация считается по «настоящим» рёбрам: у торца тонкого листа есть
    # рёбра в сотые доли миллиметра, и процент от них ничего не значит
    typical = rest >= 0.5 * float(np.median(rest))
    if not np.any(typical):
        typical = np.ones(len(rest), dtype=bool)
    relative = np.abs(final_lengths[typical] - rest[typical]) / rest[typical]
    strain = float(np.max(relative))
    strain_p90 = float(np.percentile(relative, 90))
    stretch = float(np.max(np.abs(final_lengths[typical] - rest[typical])))
    contacts_final = 0
    penetration = 0.0
    if field is not None:
        distance, _point, _normal = field.closest(position)
        good = np.isfinite(distance)
        contacts_final = int(np.count_nonzero(good & (distance < offset + 1e-3)))
        if np.any(good):
            penetration = float(np.max(np.maximum(offset - distance[good], 0.0)))
    return {
        "vertices": position,
        "steps": int(converged_at),
        "converged": bool(converged),
        "last_motion": float(movement),
        "strain": strain,
        "stretch": stretch,
        "strain_p90": strain_p90,
        "contacts": contacts_final,
        "contacts_max": int(total_contacts),
        "self_pairs": int(self_pairs),
        "self_gap": float(self_distance),
        "self_method": "particles" if rigid_only and self_collision else
                       ("surfaces" if self_collision else "off"),
        "vertices_count": count,
        "edges": int(len(edges)),
        "bend": int(len(bend_pairs)),
        "shell": int(len(shell)),
        "seconds": round(time.perf_counter() - started, 3),
        "thickness": float(thickness),
        "rigid": float(np.max(rigid_weights)) if len(rigid_weights) else 0.0,
        "penetration": penetration,
        "closed": bool(closed),
        "cell": cell,
    }
