"""Извлечение поверхности из поля расстояний — свой мешер без scipy/skimage.

Зачем свой. Раньше поверхность доставал `skimage.measure.marching_cubes`,
а scikit-image тянет за собой scipy — это десятки мегабайт в собранном EXE
ради одной функции. Здесь тот же результат считается массивами numpy:

* алгоритм — «surface nets» (двойственное контурирование без QEF):
  одна вершина на ячейку, где поле меняет знак, один четырёхугольник на
  пересечённое ребро сетки. Меш получается замкнутым и без неоднозначностей,
  которых полно у марширующих кубов;
* на гладких полях (капли, SDF-формулы, анатомия) это даёт более гладкую
  поверхность и меньше треугольников, чем marching cubes при том же шаге;
* считаются только ячейки у поверхности: память и время зависят от площади
  поверхности, а не от объёма области.

Соглашение о знаке: **внутри — значения меньше level, снаружи — больше**.
Поле автоматически окружается «снаружи», поэтому поверхность у границы
области закрывается крышкой, а не остаётся дыркой.
"""

from __future__ import annotations

import numpy as np

# углы ячейки: dx, dy, dz
_CORNERS = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
            (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1))
# рёбра ячейки: (угол A, угол B, ось)
_EDGES = ((0, 1, 0), (2, 3, 0), (4, 5, 0), (6, 7, 0),
          (0, 2, 1), (1, 3, 1), (4, 6, 1), (5, 7, 1),
          (0, 4, 2), (1, 5, 2), (2, 6, 2), (3, 7, 2))


def _pad_outside(values: np.ndarray, level: float) -> np.ndarray:
    """Добавляет слой «снаружи», чтобы поверхность на краю была замкнутой."""
    finite = values[np.isfinite(values)]
    span = float(finite.max() - finite.min()) if finite.size else 1.0
    far = float(level + max(span, 1e-6) * 2.0 + 1.0)
    return np.pad(np.asarray(values, dtype=np.float32), 1, mode="constant",
                  constant_values=far)


def _active_mask(ins: np.ndarray) -> np.ndarray:
    """Ячейки, где поле меняет знак (есть и «внутри», и «снаружи»)."""
    cx, cy, cz = ins.shape[0] - 1, ins.shape[1] - 1, ins.shape[2] - 1
    any_in = ins[:-1, :-1, :-1].copy()
    any_in |= ins[1:, :-1, :-1]
    any_in |= ins[:-1, 1:, :-1]
    any_in |= ins[1:, 1:, :-1]
    any_in |= ins[:-1, :-1, 1:]
    any_in |= ins[1:, :-1, 1:]
    any_in |= ins[:-1, 1:, 1:]
    any_in |= ins[1:, 1:, 1:]
    all_in = ins[:-1, :-1, :-1].copy()
    all_in &= ins[1:, :-1, :-1]
    all_in &= ins[:-1, 1:, :-1]
    all_in &= ins[1:, 1:, :-1]
    all_in &= ins[:-1, :-1, 1:]
    all_in &= ins[1:, :-1, 1:]
    all_in &= ins[:-1, 1:, 1:]
    all_in &= ins[1:, 1:, 1:]
    any_in ^= all_in
    return any_in


def _vertices(V: np.ndarray, ins: np.ndarray, level: float, h):
    """Одна вершина на активную ячейку — среднее точек пересечения её рёбер."""
    I, J, K = np.nonzero(_active_mask(ins))
    n = len(I)
    if n == 0:
        return None
    vals = [V[I + dx, J + dy, K + dz] for dx, dy, dz in _CORNERS]
    sums = np.zeros((n, 3), dtype=np.float32)
    counts = np.zeros(n, dtype=np.float32)
    for a, b, axis in _EDGES:
        va, vb = vals[a], vals[b]
        cross = (va < level) != (vb < level)
        if not cross.any():
            continue
        denom = np.where(cross, vb - va, 1.0)
        t = np.where(cross, (level - va) / denom, 0.0).astype(np.float32)
        ax, ay, az = _CORNERS[a]
        sums[:, 0] += np.where(cross, I + ax + (t if axis == 0 else 0.0), 0.0)
        sums[:, 1] += np.where(cross, J + ay + (t if axis == 1 else 0.0), 0.0)
        sums[:, 2] += np.where(cross, K + az + (t if axis == 2 else 0.0), 0.0)
        counts += cross
    pos = sums / np.maximum(counts, 1.0)[:, None]
    pos[:, 0] *= h[0]
    pos[:, 1] *= h[1]
    pos[:, 2] *= h[2]
    return I, J, K, pos.astype(np.float64)


def _quads(ins: np.ndarray, level: float, I, J, K, cy: int, cz: int):
    """Четырёхугольники вокруг пересечённых рёбер (согласованный обход)."""
    nx, ny, nz = ins.shape
    cx = nx - 1
    # линейные индексы вершин по активным ячейкам — для быстрого поиска
    lin = (I.astype(np.int64) * cy + J.astype(np.int64)) * cz + K.astype(np.int64)
    order = np.argsort(lin)
    lin_sorted = lin[order]
    vid_of = order  # позиция в порядке сортировки -> номер вершины

    def lookup(qi, qj, qk):
        q = (qi.astype(np.int64) * cy + qj.astype(np.int64)) * cz + qk.astype(np.int64)
        pos = np.searchsorted(lin_sorted, q)
        ok = (pos < len(lin_sorted)) & (lin_sorted[np.minimum(pos, len(lin_sorted) - 1)] == q)
        return np.where(ok, vid_of[np.minimum(pos, len(lin_sorted) - 1)], -1)

    quads = []
    flip = []

    def _add(cells, rev):
        # cells: список (di, dj, dk) — смещения ячеек вокруг ребра
        idx = [lookup(I0 + di, J0 + dj, K0 + dk) for di, dj, dk in cells]
        q = np.stack(idx, axis=1)
        ok = (q >= 0).all(axis=1)
        if ok.any():
            quads.append(q[ok])
            flip.append(rev[ok])

    # рёбра вдоль X: узлы (i,j,k)-(i+1,j,k); ячейки вокруг (i, j-1..j, k-1..k)
    e = (ins[:-1, 1:-1, 1:-1] != ins[1:, 1:-1, 1:-1])
    if e.any():
        I0, J0, K0 = np.nonzero(e)
        J0 = J0 + 1
        K0 = K0 + 1
        start_in = ins[:-1, 1:-1, 1:-1][e]
        _add([(0, -1, -1), (0, 0, -1), (0, 0, 0), (0, -1, 0)], ~start_in)

    # рёбра вдоль Y: узлы (i,j,k)-(i,j+1,k); ячейки вокруг (i-1..i, j, k-1..k)
    e = (ins[1:-1, :-1, 1:-1] != ins[1:-1, 1:, 1:-1])
    if e.any():
        I0, J0, K0 = np.nonzero(e)
        I0 = I0 + 1
        K0 = K0 + 1
        start_in = ins[1:-1, :-1, 1:-1][e]
        _add([(-1, 0, -1), (-1, 0, 0), (0, 0, 0), (0, 0, -1)], ~start_in)

    # рёбра вдоль Z: узлы (i,j,k)-(i,j,k+1); ячейки вокруг (i-1..i, j-1..j, k)
    e = (ins[1:-1, 1:-1, :-1] != ins[1:-1, 1:-1, 1:])
    if e.any():
        I0, J0, K0 = np.nonzero(e)
        I0 = I0 + 1
        J0 = J0 + 1
        start_in = ins[1:-1, 1:-1, :-1][e]
        _add([(-1, -1, 0), (0, -1, 0), (0, 0, 0), (-1, 0, 0)], ~start_in)

    if not quads:
        return np.zeros((0, 3), dtype=np.int64)
    q = np.concatenate(quads, axis=0)
    rev = np.concatenate(flip, axis=0)
    if rev.any():
        q[rev] = q[rev][:, ::-1]
    tri = np.concatenate([
        np.stack([q[:, 0], q[:, 1], q[:, 2]], axis=1),
        np.stack([q[:, 0], q[:, 2], q[:, 3]], axis=1),
    ], axis=0)
    return tri.astype(np.int64)


def mesh_field(values, origin=(0.0, 0.0, 0.0), spacing=1.0, level: float = 0.0):
    """Строит (вершины, грани) по полю расстояний.

    values  — трёхмерный массив (внутри < level, снаружи > level);
    origin  — координаты узла [0,0,0]; spacing — шаг сетки (мм),
              число или три числа.
    """
    V = np.asarray(values, dtype=np.float32)
    if V.ndim != 3:
        raise ValueError("Поле должно быть трёхмерным массивом.")
    V = _pad_outside(V, level)
    try:
        hs = tuple(float(s) for s in spacing)  # type: ignore[arg-type]
        if len(hs) != 3:
            raise TypeError
    except TypeError:
        hs = (float(spacing),) * 3

    ins = V < level
    res = _vertices(V, ins, level, hs)
    if res is None:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)
    I, J, K, pos = res

    cy, cz = ins.shape[1] - 1, ins.shape[2] - 1
    faces = _quads(ins, level, I, J, K, cy, cz)

    ox, oy, oz = (float(o) for o in origin)
    verts = pos + np.array([ox - hs[0], oy - hs[1], oz - hs[2]])
    return verts, faces
