"""Кубическая сетка-бюджет: объём, который модель имеет право занимать.

В окне давно есть режим **кубов** — кубические секторы вокруг модели, по
которым можно оставить заметку. Не хватало главного: сами кубы не ограничивали
геометрию. Теперь сетка задаётся в сценарии и работает как **бюджет объёма**:

    сетка cell=20 origin=[-60,-60,0] size=[6,4,3]   # 6×4×3 куба по 20 мм
    корпус = box size=[200,200,20]
    вписать корпус                                  # всё лишнее срезано по кубам
    check корпус в_сетке                            # отчёт: сколько объёма вне бюджета

Зачем: чтобы не считать в голове, «влезет ли», и не бояться, что деталь
вылезет за отведённое место. Кубы можно выбирать по одному (`cells=`) или
блоками (`ranges=`), как рамкой в окне.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import make_solid, op

# Потолок числа кубов: больше — сетка перестаёт быть инструментом ограничения
# и превращается в воксельный движок, который здесь не нужен.
MAX_CELLS = 60_000


def _ints(values, what: str) -> list[int]:
    out: list[int] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise GeometryError(f"{what}: ожидались целые индексы кубов.")
        out.append(int(round(float(v))))
    return out


def _cell_key(c) -> tuple[int, int, int]:
    return int(c[0]), int(c[1]), int(c[2])


def grid_of(scene) -> dict | None:
    """Текущая кубическая сетка сцены (или None)."""
    if scene is None:
        return None
    return getattr(scene, "grid", None)


def _boxes_of(cells: list[tuple[int, int, int]]) -> list[tuple[int, int, int, int, int, int]]:
    """Склеивает кубы в прямоугольные блоки — меньше булевых операций.

    Сначала собираем полосы вдоль X, потом сливаем одинаковые полосы по Y,
    потом по Z. Для прямоугольного выбора остаётся один блок вместо тысяч
    кубов, а для фигурного — десятки.
    """
    by_yz: dict[tuple[int, int], list[int]] = {}
    for i, j, k in cells:
        by_yz.setdefault((j, k), []).append(i)
    slabs: list[tuple[int, int, int, int]] = []      # i0, i1, j, k (по одному j,k)
    for (j, k), xs in by_yz.items():
        xs = sorted(set(xs))
        start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
                continue
            slabs.append((start, prev, j, k))
            start = prev = x
        slabs.append((start, prev, j, k))

    by_ik: dict[tuple[int, int, int], list[int]] = {}
    for i0, i1, j, k in slabs:
        by_ik.setdefault((i0, i1, k), []).append(j)
    sticks: list[tuple[int, int, int, int, int, int]] = []
    for (i0, i1, k), ys in by_ik.items():
        ys = sorted(set(ys))
        start = prev = ys[0]
        for y in ys[1:]:
            if y == prev + 1:
                prev = y
                continue
            sticks.append((i0, i1, start, prev, k, k))
            start = prev = y
        sticks.append((i0, i1, start, prev, k, k))

    by_ij: dict[tuple[int, int, int, int], list[int]] = {}
    for i0, i1, j0, j1, k, _k in sticks:
        by_ij.setdefault((i0, i1, j0, j1), []).append(k)
    boxes: list[tuple[int, int, int, int, int, int]] = []
    for (i0, i1, j0, j1), ks in by_ij.items():
        ks = sorted(set(ks))
        start = prev = ks[0]
        for z in ks[1:]:
            if z == prev + 1:
                prev = z
                continue
            boxes.append((i0, i1, j0, j1, start, prev))
            start = prev = z
        boxes.append((i0, i1, j0, j1, start, prev))
    return boxes


def _ranges_of(cells: list[tuple[int, int, int]]) -> list[list[int]]:
    """Плотное описание для окна: [[i0,i1,j0,j1,k0,k1], …]."""
    return [list(b) for b in _boxes_of(cells)]


def grid_shape(cell: float, origin, cells: list[tuple[int, int, int]]) -> mf.Manifold:
    """Тело из кубов сетки — бюджет объёма как настоящая геометрия."""
    cell = float(cell)
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    parts: list[mf.Manifold] = []
    for i0, i1, j0, j1, k0, k1 in _boxes_of(cells):
        size = ((i1 - i0 + 1) * cell, (j1 - j0 + 1) * cell, (k1 - k0 + 1) * cell)
        centre = (origin[0] + (i0 * cell + size[0] / 2.0),
                  origin[1] + (j0 * cell + size[1] / 2.0),
                  origin[2] + (k0 * cell + size[2] / 2.0))
        parts.append(mf.Manifold.cube(size, True).translate(centre))
    if not parts:
        raise GeometryError("Кубическая сетка пуста — не выбрано ни одного куба.")
    if len(parts) == 1:
        return parts[0]
    return mf.Manifold.batch_boolean(parts, mf.OpType.Add)


def grid_bounds(grid: dict) -> list[float]:
    cell = float(grid["cell"])
    ox, oy, oz = grid["origin"]
    cells = grid["cells"]
    i0 = min(c[0] for c in cells)
    j0 = min(c[1] for c in cells)
    k0 = min(c[2] for c in cells)
    i1 = max(c[0] for c in cells) + 1
    j1 = max(c[1] for c in cells) + 1
    k1 = max(c[2] for c in cells) + 1
    return [ox + i0 * cell, oy + j0 * cell, oz + k0 * cell,
            ox + i1 * cell, oy + j1 * cell, oz + k1 * cell]


def cells_from_grid(grid: dict, cell_size: float | None = None) -> list[tuple[int, int, int]]:
    cell = float(cell_size or grid["cell"])
    origin = grid["origin"]
    i0, j0, k0 = (math.floor((grid["bounds"][0] - origin[0]) / cell),
                  math.floor((grid["bounds"][1] - origin[1]) / cell),
                  math.floor((grid["bounds"][2] - origin[2]) / cell))
    out = []
    for i in range(int(round((grid["bounds"][3] - grid["bounds"][0]) / cell))):
        for j in range(int(round((grid["bounds"][4] - grid["bounds"][1]) / cell))):
            for k in range(int(round((grid["bounds"][5] - grid["bounds"][2]) / cell))):
                out.append((i0 + i, j0 + j, k0 + k))
    return out


def overflow_mm3(m: mf.Manifold, grid: dict) -> float:
    """Сколько объёма детали лежит вне кубов (мм³)."""
    try:
        shape = grid_shape(grid["cell"], grid["origin"], grid["cells"])
        outside = m - shape
        return max(float(outside.volume()), 0.0)
    except Exception:
        return 0.0


def _env_cells(scene, cell: float, origin, pad: float = 1.5) -> list[tuple[int, int, int]]:
    """Кубы вокруг всей модели — когда сетку задали «вокруг» без размеров."""
    boxes = [s.manifold.bounding_box() for s in scene.visible_solids()]
    if not boxes:
        raise GeometryError(
            "Сетке «вокруг» нужна модель в сцене.",
            hint="Сначала постройте деталь или задайте сетку размерами: size=[6,4,3]")
    lo = np.array([min(b[0] for b in boxes), min(b[1] for b in boxes),
                   min(b[2] for b in boxes)]) - cell * pad
    hi = np.array([max(b[3] for b in boxes), max(b[4] for b in boxes),
                   max(b[5] for b in boxes)]) + cell * pad
    o = np.asarray(origin, dtype=np.float64)
    i0 = int(math.floor((lo[0] - o[0]) / cell))
    j0 = int(math.floor((lo[1] - o[1]) / cell))
    k0 = int(math.floor((lo[2] - o[2]) / cell))
    ni = int(math.ceil((hi[0] - o[0]) / cell)) - i0
    nj = int(math.ceil((hi[1] - o[1]) / cell)) - j0
    nk = int(math.ceil((hi[2] - o[2]) / cell)) - k0
    if ni * nj * nk > MAX_CELLS:
        raise GeometryError(
            f"Сетка «вокруг» получилась слишком мелкой: {ni}×{nj}×{nk} кубов.",
            hint=f"Увеличьте cell — предел {MAX_CELLS} кубов.")
    return [(i0 + i, j0 + j, k0 + k)
            for i in range(ni) for j in range(nj) for k in range(nk)]


@op("сетка", aliases=("кубы", "кубическая_сетка", "сетка_объёма", "сетка_объема",
                      "бюджет", "grid", "voxel_grid"),
    category="Сцена и материал",
    summary="Кубическая сетка-бюджет: какие кубы модель имеет право занимать. "
            "Кубы можно перечислить по индексам, задать блоками (как рамкой в окне) "
            "или прямоугольником size. Вместе с `вписать` объём детали гарантированно "
            "не выйдет за эти кубы, а `check … в_сетке` покажет, сколько вышло.",
    example="сетка cell=20 origin=[-60, -60, 0] size=[6, 4, 3]\n"
            "корпус = box size=[300, 300, 40]\n"
            "вписать корпус\n"
            "check корпус в_сетке",
    params={"cell": "ребро куба, мм (20)",
            "origin": "угол куба с индексами 0,0,0 [x,y,z] (0,0,0)",
            "size": "прямоугольник из кубов [nx,ny,nz]",
            "cells": "отдельные кубы [[i,j,k], …]",
            "ranges": "блоки кубов [[i0,i1,j0,j1,k0,k1], …]",
            "around": "взять все кубы вокруг модели (да/нет)",
            "pad": "запас вокруг модели в кубах для around (1.5)"},
    positional="*")
def grid(a, name):
    scene = a.scene
    cell = float(a.num("cell", 20.0, minv=0.1))
    origin = np.asarray(a.vec("origin", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    around = a.boolean("around", False) or a.boolean("вокруг", False)
    pad = float(a.num("pad", 1.5, minv=0.0))
    cells: list[tuple[int, int, int]] = []

    if a.has("size"):
        dims = [max(1, int(round(v))) for v in a.vec("size", 3)]
        if dims[0] * dims[1] * dims[2] > MAX_CELLS:
            raise GeometryError(
                f"Сетка {dims[0]}×{dims[1]}×{dims[2]} — это {dims[0] * dims[1] * dims[2]} кубов.",
                hint=f"Предел — {MAX_CELLS}. Увеличьте куб или уменьшите прямоугольник.")
        i0 = j0 = k0 = 0
        cells += [(i0 + i, j0 + j, k0 + k)
                  for i in range(dims[0]) for j in range(dims[1]) for k in range(dims[2])]

    if a.has("cells"):
        for c in a.points("cells", 3):
            cells.append(_cell_key(_ints(list(c), "сетка cells")))

    if a.has("ranges"):
        raw = a.value("ranges")
        if not isinstance(raw, (list, tuple)):
            raise GeometryError("ranges: нужен список блоков [[i0,i1,j0,j1,k0,k1], …].")
        for block in raw:
            if not isinstance(block, (list, tuple)) or len(block) != 6:
                raise GeometryError("ranges: каждый блок — шесть чисел "
                                    "[i0,i1,j0,j1,k0,k1].")
            i0, i1, j0, j1, k0, k1 = _ints(list(block), "сетка ranges")
            i0, i1 = min(i0, i1), max(i0, i1)
            j0, j1 = min(j0, j1), max(j0, j1)
            k0, k1 = min(k0, k1), max(k0, k1)
            cells += [(i, j, k) for i in range(i0, i1 + 1)
                      for j in range(j0, j1 + 1) for k in range(k0, k1 + 1)]

    if around or not cells:
        if not cells:
            cells = _env_cells(scene, cell, origin, pad)
    cells = sorted(set(cells))
    if len(cells) > MAX_CELLS:
        raise GeometryError(f"Кубы: {len(cells)} — больше предела {MAX_CELLS}.",
                            hint="Укрупните cell или уменьшите выбор.")

    ox, oy, oz = (float(origin[0]), float(origin[1]), float(origin[2]))
    bounds = [ox + min(c[0] for c in cells) * cell, oy + min(c[1] for c in cells) * cell,
              oz + min(c[2] for c in cells) * cell,
              ox + (max(c[0] for c in cells) + 1) * cell,
              oy + (max(c[1] for c in cells) + 1) * cell,
              oz + (max(c[2] for c in cells) + 1) * cell]
    grid_data = {
        "cell": cell,
        "origin": [ox, oy, oz],
        "cells": [list(c) for c in cells],
        "ranges": _ranges_of(cells),
        "bounds": bounds,
        "volume_mm3": len(cells) * cell ** 3,
        "line": int(getattr(a.cmd, "line", 0) or 0),
    }
    scene.grid = grid_data
    nx = int(round((bounds[3] - bounds[0]) / cell))
    ny = int(round((bounds[4] - bounds[1]) / cell))
    nz = int(round((bounds[5] - bounds[2]) / cell))
    scene.log("info",
              f"сетка: {len(cells)} кубов по {cell:g} мм, "
              f"габарит {nx}×{ny}×{nz} = {bounds[3] - bounds[0]:g}×"
              f"{bounds[4] - bounds[1]:g}×{bounds[5] - bounds[2]:g} мм, "
              f"объём {grid_data['volume_mm3'] / 1000:g} см³", a.cmd.line)
    return None


@op("вписать", aliases=("в_сетку", "ограничить", "обрезать_по_сетке", "по_кубам",
                       "fit_grid", "clip_to_grid"),
    category="Булевы операции",
    summary="Обрезает деталь по кубической сетке: всё, что вышло за выбранные кубы, "
            "срезается. Так объём гарантированно не превысит отведённое место — "
            "не нужно проверять это вручную.",
    example="сетка cell=20 size=[6,4,3]\nблок = sphere radius=90 at=[0,0,30]\n"
            "блок = вписать блок",
    params={"objects": "объект (или [объект])"},
    positional=["objects"])
def fit_grid(a, name):
    solids = a.solids()
    grid = grid_of(a.scene)
    if not grid:
        raise GeometryError(
            "Сначала задайте кубическую сетку.",
            hint="Например: сетка cell=20 size=[6,4,3]")
    shape = grid_shape(grid["cell"], grid["origin"], grid["cells"])
    out = []
    for solid in solids:
        before = float(solid.manifold.volume())
        trimmed = solid.manifold ^ shape
        if trimmed.is_empty() or trimmed.volume() <= 1e-9:
            raise GeometryError(
                f"«{solid.name}» целиком вне кубической сетки — после обрезки пусто.",
                hint="Проверьте origin и size сетки: кубы должны пересекаться с деталью.")
        lost = max(before - float(trimmed.volume()), 0.0)
        placed = make_solid(a.scene, solid.name, trimmed, a, base=solid, kind="grid_fit")
        placed.notes.append(
            f"обрезано по сетке {grid['cell']:g} мм: снято {lost / 1000:.2f} см³"
            f" ({100 * lost / max(before, 1e-9):.1f}%)")
        a.scene.consume(solid)
        out.append(placed)
    return out[0] if len(out) == 1 else out
