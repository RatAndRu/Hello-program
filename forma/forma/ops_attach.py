"""Привязка к настоящей границе детали, а не к её габаритной коробке.

`place [a] on=тор` ставит деталь относительно **центра габарита**: сверху,
снизу, слева… Для тора это коробка вокруг кольца, и «сбоку» получается
сбоку от коробки, а не на самом кольце. Здесь — `на_границе`: деталь
садится на **ближайшую точку настоящей поверхности** хозяина и разворачивается
по её нормали, если попросить.

    шайба = cylinder radius=6 height=4
    шайба = на_границе [шайба] on=кольцо point=[40,0,20] offset=1
    шарик = sphere radius=5
    шарик = на_границе [шарик] on=кольцо point=[0,-40,20] align=нормаль
"""

from __future__ import annotations

import manifold3d as mf
import numpy as np

from . import cuts, orient
from .errors import GeometryError
from .ops import make_solid, op, rotate as rotate_manifold, translate as translate_manifold


def _mesh(manifold: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    tris = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
    return verts, tris


def _closest_on_triangle(p: np.ndarray, a: np.ndarray, b: np.ndarray,
                         c: np.ndarray) -> np.ndarray:
    """Ближайшая точка треугольника по Эриксону (Real-Time Collision Detection)."""
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = float(np.dot(ab, ap))
    d2 = float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        return a
    bp = p - b
    d3 = float(np.dot(ab, bp))
    d4 = float(np.dot(ac, bp))
    if d3 >= 0.0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        return a + v * ab
    cp = p - c
    d5 = float(np.dot(ab, cp))
    d6 = float(np.dot(ac, cp))
    if d6 >= 0.0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        return a + w * ac
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return b + w * (c - b)
    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    return a + ab * v + ac * w


def _nearest_surface(manifold: mf.Manifold,
                     probe: np.ndarray,
                     side: str = "любая") -> tuple[np.ndarray, np.ndarray]:
    """Ближайшая точка поверхности и её внешняя нормаль.

    side — ограничить поиск одной стороной: «верх» ищет только в верхней
    половине детали. Это нужно, когда ближайшая точка неоднозначна: у тора
    из центра отверстия одинаково близки все внутренние стенки.
    """
    verts, tris = _mesh(manifold)
    if len(verts) == 0 or len(tris) == 0:
        raise GeometryError("на_границе: у детали нет поверхности.",
                            hint="Проверьте, что деталь построилась.")
    key = orient.side_key(side) if side and side not in ("любая", "any", "anywhere") else ""
    if key and key in orient.SIDE_VECTORS and key != "center":
        d = orient.SIDE_VECTORS[key]
        proj = verts @ d
        mid = (float(proj.min()) + float(proj.max())) / 2.0
        centroids = verts[tris].mean(axis=1)
        allowed = (centroids @ d) >= mid
        if allowed.any():
            tris = tris[allowed]
    d2 = np.einsum("ij,ij->i", verts - probe, verts - probe)
    nearest = np.argsort(d2)[:24]
    mask = np.isin(tris, nearest).any(axis=1)
    cand = tris[mask]
    if len(cand) == 0:
        cand = tris
    if len(cand) > 4000:                      # тяжёлая деталь — берём ближние
        centres = verts[cand].mean(axis=1)
        keep = np.argsort(np.einsum("ij,ij->i", centres - probe, centres - probe))[:4000]
        cand = cand[keep]
    best = None
    best_d = np.inf
    for tri in cand:
        pa, pb, pc = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        q = _closest_on_triangle(probe, pa, pb, pc)
        dist = float(np.linalg.norm(q - probe))
        if dist < best_d:
            best_d = dist
            best = (q, pa, pb, pc)
    q, pa, pb, pc = best
    normal = np.cross(pb - pa, pc - pa)
    n = float(np.linalg.norm(normal))
    if n < 1e-12:
        raise GeometryError("на_границе: не удалось определить нормаль поверхности.")
    normal = normal / n
    # треугольники manifold3d ориентированы наружу; проверяем это честно —
    # точка чуть снаружи по нормали не должна попасть в материал. Так годится
    # и для вогнутых мест: у кольца тора «наружу» смотрит внутрь отверстия.
    bb = np.array(manifold.bounding_box(), dtype=np.float64)
    size = max(float(bb[3] - bb[0]), float(bb[4] - bb[1]), float(bb[5] - bb[2]), 1e-6)
    step = max(0.05, size * 0.002)
    try:
        info = cuts.point_info(manifold, q + normal * step)
        if info.get("inside"):
            normal = -normal
    except Exception:
        c = (bb[:3] + bb[3:]) * 0.5
        if float(np.dot(normal, q - c)) < 0.0:
            normal = -normal
    return q, normal


def _rotation_to(vec_from: np.ndarray, vec_to: np.ndarray) -> np.ndarray:
    """Матрица поворота, переводящая vec_from в vec_to."""
    a = vec_from / max(float(np.linalg.norm(vec_from)), 1e-12)
    b = vec_to / max(float(np.linalg.norm(vec_to)), 1e-12)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if float(np.linalg.norm(v)) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(axis, a))) > 0.9:
            axis = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, axis)
        axis /= max(float(np.linalg.norm(axis)), 1e-12)
        return _rotation_matrix(axis, np.pi)
    skew = np.array([[0.0, -v[2], v[1]],
                     [v[2], 0.0, -v[0]],
                     [-v[1], v[0], 0.0]])
    return np.eye(3) + skew + skew @ skew * ((1.0 - c) / max(float(np.dot(v, v)), 1e-12))


def _rotation_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def _apply(m: mf.Manifold, matrix: np.ndarray, shift: np.ndarray) -> mf.Manifold:
    full = np.zeros((3, 4), dtype=np.float64)
    full[:, :3] = matrix
    full[:, 3] = shift
    return m.transform(np.ascontiguousarray(full))


@op("на_границе", aliases=("snap", "к_границе", "приставить", "по_границе",
                           "surface_snap", "привязать"),
    category="Массивы и преобразования",
    summary="Ставит деталь на настоящую границу другой детали: находит "
            "ближайшую точку её поверхности к точке «к» и приставляет деталь "
            "к ней с зазором. Это не центр габарита, а сама поверхность — "
            "можно посадить шайбу на кольцо тора или шарик на его бок. "
            "align=нормаль ещё и разворачивает деталь по нормали.",
    example="кольцо = torus major=40 minor=8\n"
            "шайба = cylinder radius=6 height=4\n"
            "шайба = на_границе [шайба] on=кольцо point=[40,0,20] offset=1\n"
            "шарик = sphere radius=6\n"
            "шарик = на_границе [шарик] on=кольцо point=[0,-40,20] align=нормаль",
    params={"objects": "деталь, которую ставим",
            "on": "к чему приставить (имя хозяина)",
            "point": "точка, к которой ищем ближайшую точку поверхности [x,y,z] "
                     "(по умолчанию центр детали); пишется и как точка=", 
            "offset": "зазор от поверхности, мм (0)",
            "align": "нет или нормаль — развернуть деталь по нормали (нет)",
            "сторона": "искать только на этой стороне: верх, низ, лево, право, "
                       "перёд, зад или любая",
            "sides": "то же, что сторона",
            "at": "сдвиг после посадки [x,y,z]"},
    positional=["objects"])
def snap_to_surface(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("на_границе ставит одну деталь за раз.",
                            hint="Формат: на_границе [шайба] on=кольцо точка=[40,0,20]")
    part = solids[0]
    host_name = (a.text("on") or "").strip()
    if not host_name:
        raise GeometryError("на_границе: не указано, к чему приставить.",
                            hint="Например: на_границе [шайба] on=кольцо")
    host = a.scene.resolve(host_name)
    if host is part:
        raise GeometryError("на_границе: деталь и хозяин — одно и то же.")

    pb = part.manifold.bounding_box()
    part_centre = np.array([(pb[0] + pb[3]) * 0.5, (pb[1] + pb[4]) * 0.5,
                            (pb[2] + pb[5]) * 0.5])
    probe = a.vec("point", 3, default=None)
    probe = (np.asarray(probe, dtype=np.float64).reshape(3)
             if probe is not None else part_centre)
    offset = float(a.num("offset", 0.0, minv=-1e6, maxv=1e6) or 0.0)
    align = (a.text("align", "нет") or "нет").strip().lower()
    side = (a.text("сторона") or a.text("sides") or "любая")

    point, normal = _nearest_surface(host.manifold, probe, side)
    matrix = np.eye(3)
    if align in ("нормаль", "normal", "да", "yes", "1"):
        matrix = _rotation_to(np.array([0.0, 0.0, 1.0]), normal)

    verts, _tris = _mesh(part.manifold)
    local = (verts - part_centre) @ matrix.T
    reach = float(np.max(local @ normal)) if len(local) else 0.0
    target = point + normal * (reach + offset)
    shift = target - part_centre
    moved = _apply(part.manifold, matrix, shift)
    if a.has("at"):
        moved = translate_manifold(moved, np.asarray(a.vec("at", 3), dtype=np.float64))

    part_axes = orient.axes_of(part)
    a.scene.consume(part)
    made = make_solid(a.scene, name, moved, a, base=part, kind="на_границе")
    if align in ("нормаль", "normal", "да", "yes", "1"):
        orient.set_axes(made, matrix @ part_axes)
    made.notes.append(f"на границе {host.name}: точка "
                      f"({point[0]:.1f}, {point[1]:.1f}, {point[2]:.1f})")
    a.scene.log("info", f"на_границе: {part.name} → поверхность {host.name}, "
                        f"зазор {offset:g} мм", a.cmd.line)
    return made
