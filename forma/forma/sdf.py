"""Векторные SDF-поля: быстрая сборка органических форм (анатомия, метаболы).

В отличие от `from_sdf` (поштучный вызов Python-функции), здесь поле считается
сразу массивами numpy: каждое примитивное тело добавляется только в своей
области сетки. Это позволяет за секунды строить тела из сотен «мышц».
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays

BIG = 1.0e5


def _norm(v) -> np.ndarray:
    arr = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(arr))
    return arr / n if n > 1e-12 else arr


def rotation_matrix(axis, angle_deg: float) -> np.ndarray:
    ax = _norm(axis)
    if not np.any(ax):
        return np.eye(3)
    a = math.radians(angle_deg)
    x, y, z = ax
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ], dtype=np.float64)


class Field:
    """Поле расстояний со знаком на регулярной сетке."""

    def __init__(self, bounds, resolution: float):
        self.bounds = [float(b) for b in bounds]
        self.h = float(resolution)
        if self.h <= 0:
            raise GeometryError("Разрешение SDF должно быть положительным.")
        self.n = [int(math.ceil((self.bounds[i + 3] - self.bounds[i]) / self.h)) + 1
                  for i in range(3)]
        total = int(np.prod(self.n))
        if total > 80_000_000:
            raise GeometryError(
                f"Слишком подробная сетка для SDF ({total:,} точек).".replace(",", " "),
                hint="Увеличьте resolution или уменьшите размеры области.",
            )
        self.F = np.full(tuple(self.n), BIG, dtype=np.float32)

    # ------------------------------------------------------------------ #
    def _slice(self, lo, hi):
        h = self.h
        b = self.bounds
        idx = []
        for i in range(3):
            a = max(0, int(math.floor((lo[i] - b[i]) / h)))
            c = min(self.n[i] - 1, int(math.ceil((hi[i] - b[i]) / h)))
            idx.append((a, c))
        return idx

    def _coords(self, idx):
        h = self.h
        b = self.bounds
        xs = b[0] + np.arange(idx[0][0], idx[0][1] + 1) * h
        ys = b[1] + np.arange(idx[1][0], idx[1][1] + 1) * h
        zs = b[2] + np.arange(idx[2][0], idx[2][1] + 1) * h
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        return X, Y, Z, (slice(idx[0][0], idx[0][1] + 1),
                         slice(idx[1][0], idx[1][1] + 1),
                         slice(idx[2][0], idx[2][1] + 1))

    # ------------------------------------------------------------------ #
    def add(self, prim, blend: float = 0.0, strength: float = 1.0):
        """Плавно добавляет тело (smooth union). blend — радиус слияния, мм."""
        k = max(0.0, float(blend))
        margin = k * 1.5 + 3 * self.h
        lo = np.asarray(prim.lo, dtype=np.float64) - margin
        hi = np.asarray(prim.hi, dtype=np.float64) + margin
        idx = self._slice(lo, hi)
        X, Y, Z, sl = self._coords(idx)
        d = prim.sdf(X, Y, Z) * float(strength)
        cur = self.F[sl]
        if k <= 1e-9:
            self.F[sl] = np.minimum(cur, d)
        else:
            h = np.clip(0.5 + 0.5 * (cur - d) / k, 0.0, 1.0)
            smin = cur + (d - cur) * h - k * h * (1.0 - h)
            self.F[sl] = smin.astype(np.float32)
        return self

    def cut(self, prim, blend: float = 0.0):
        """Плавно вычитает тело (smooth subtract)."""
        k = max(0.0, float(blend))
        margin = k * 1.5 + 3 * self.h
        lo = np.asarray(prim.lo, dtype=np.float64) - margin
        hi = np.asarray(prim.hi, dtype=np.float64) + margin
        idx = self._slice(lo, hi)
        X, Y, Z, sl = self._coords(idx)
        d = prim.sdf(X, Y, Z)
        cur = self.F[sl]
        if k <= 1e-9:
            self.F[sl] = np.maximum(cur, -d)
        else:
            a = -cur
            b = -(-d)
            h = np.clip(0.5 + 0.5 * (a - b) / k, 0.0, 1.0)
            smin = a + (b - a) * h - k * h * (1.0 - h)
            self.F[sl] = np.maximum(-smin, cur).astype(np.float32)
        return self

    def add_many(self, prims: Iterable, blend: float = 0.0):
        for p in prims:
            self.add(p, blend)
        return self

    # ------------------------------------------------------------------ #
    def mesh(self, smooth_iters: int = 0, simplify: float = 0.0,
             what: str = "фигура", clean: float = 0.0,
             polish: float = 0.0) -> mf.Manifold:
        """Строит Manifold по полю расстояний.

        polish > 0 — «полировка» поверхности: G1-сглаживание рёбер мельче
        указанного угла и удвоение плотности сетки. Именно это убирает
        «лесенки» марширующих кубов на плавных переходах.
        """
        from .mesher import mesh_field

        verts, faces = mesh_field(self.F, origin=self.bounds[:3], spacing=self.h)
        if len(verts) == 0 or len(faces) == 0:
            raise GeometryError(f"Не удалось построить {what}: пустая поверхность.",
                                hint="Проверьте размеры и разрешение.")
        faces = faces.astype(np.int64)
        # ориентация: нормали смотрят изнутри наружу — приводим к CCW-наружу
        v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
        vol = np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0
        if vol < 0:
            faces = faces[:, ::-1]
        if smooth_iters > 0:
            verts = _laplacian_smooth(verts, faces, smooth_iters)
        solid = manifold_from_arrays(verts, faces, what)
        if clean > 0:
            solid = _drop_specks(solid, clean)
        solid = solid.simplify(float(simplify)) if simplify > 0 else solid
        if polish > 0:
            try:
                solid = solid.smooth_out(float(polish), 0.35).refine(2)
            except Exception:
                pass
        if solid.is_empty():
            raise GeometryError(f"Не удалось построить {what}.")
        return solid


def _drop_specks(m: mf.Manifold, keep_ratio: float = 0.01) -> mf.Manifold:
    """Убирает крошечные обрывки поверхности (артефакты marching cubes)."""
    parts = m.decompose()
    if len(parts) <= 1:
        return m
    volumes = [p.volume() for p in parts]
    total = sum(v for v in volumes if v > 0)
    if total <= 0:
        return m
    keep = [p for p, v in zip(parts, volumes) if v >= total * float(keep_ratio)]
    if not keep or len(keep) == len(parts):
        return m
    return mf.Manifold.batch_boolean(keep, mf.OpType.Add)


def _laplacian_smooth(verts: np.ndarray, faces: np.ndarray, iters: int,
                      factor: float = 0.5) -> np.ndarray:
    n = len(verts)
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]],
                       faces[:, [1, 0]], faces[:, [2, 1]], faces[:, [0, 2]]])
    src, dst = edges[:, 0], edges[:, 1]
    deg = np.bincount(src, minlength=n).astype(np.float64)
    deg[deg == 0] = 1.0
    out = verts.copy()
    for _ in range(int(iters)):
        acc = np.zeros_like(out)
        for axis in range(3):
            acc[:, axis] = np.bincount(src, weights=out[dst, axis], minlength=n)
        avg = acc / deg[:, None]
        out = out * (1 - factor) + avg * factor
    return out


# --------------------------------------------------------------------------- #
#  Примитивы
# --------------------------------------------------------------------------- #

class Prim:
    lo: np.ndarray
    hi: np.ndarray

    def sdf(self, x, y, z):  # pragma: no cover - интерфейс
        raise NotImplementedError

    def translated(self, offset):
        off = np.asarray(offset, dtype=np.float64)
        self.lo = self.lo + off
        self.hi = self.hi + off
        return self


@dataclass
class Sphere(Prim):
    c: tuple
    r: float

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        self.c = tuple(float(v) for v in c)
        self.lo = c - self.r
        self.hi = c + self.r

    def sdf(self, x, y, z):
        return np.sqrt((x - self.c[0]) ** 2 + (y - self.c[1]) ** 2 + (z - self.c[2]) ** 2) - self.r


@dataclass
class Ellipsoid(Prim):
    c: tuple
    radii: tuple
    rot: np.ndarray | None = None

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        r = np.asarray(self.radii, dtype=np.float64)
        self.c = tuple(float(v) for v in c)
        self.radii = tuple(float(v) for v in r)
        self.rot = None if self.rot is None else np.asarray(self.rot, dtype=np.float64)
        ext = r if self.rot is None else np.abs(self.rot) @ r
        self.lo = c - ext
        self.hi = c + ext

    def sdf(self, x, y, z):
        px = x - self.c[0]
        py = y - self.c[1]
        pz = z - self.c[2]
        if self.rot is not None:
            # обратное вращение
            r = self.rot
            lx = r[0, 0] * px + r[1, 0] * py + r[2, 0] * pz
            ly = r[0, 1] * px + r[1, 1] * py + r[2, 1] * pz
            lz = r[0, 2] * px + r[1, 2] * py + r[2, 2] * pz
            px, py, pz = lx, ly, lz
        rx, ry, rz = self.radii
        k0 = np.sqrt((px / rx) ** 2 + (py / ry) ** 2 + (pz / rz) ** 2)
        k1 = np.sqrt((px / (rx * rx)) ** 2 + (py / (ry * ry)) ** 2 + (pz / (rz * rz)) ** 2)
        k1 = np.where(k1 < 1e-9, 1e-9, k1)
        return k0 * (k0 - 1.0) / k1


@dataclass
class Capsule(Prim):
    a: tuple
    b: tuple
    r: float

    def __post_init__(self):
        a = np.asarray(self.a, dtype=np.float64)
        b = np.asarray(self.b, dtype=np.float64)
        self.a = tuple(float(v) for v in a)
        self.b = tuple(float(v) for v in b)
        self.lo = np.minimum(a, b) - self.r
        self.hi = np.maximum(a, b) + self.r

    def sdf(self, x, y, z):
        ax, ay, az = self.a
        bx, by, bz = self.b
        px, py, pz = x - ax, y - ay, z - az
        ex, ey, ez = bx - ax, by - ay, bz - az
        denom = ex * ex + ey * ey + ez * ez
        if denom < 1e-12:
            return np.sqrt(px * px + py * py + pz * pz) - self.r
        t = np.clip((px * ex + py * ey + pz * ez) / denom, 0.0, 1.0)
        dx, dy, dz = px - ex * t, py - ey * t, pz - ez * t
        return np.sqrt(dx * dx + dy * dy + dz * dz) - self.r


@dataclass
class RoundBox(Prim):
    c: tuple
    size: tuple
    r: float = 0.0
    rot: np.ndarray | None = None

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        s = np.asarray(self.size, dtype=np.float64) / 2.0
        self.c = tuple(float(v) for v in c)
        self.size = tuple(float(v) for v in self.size)
        self.rot = None if self.rot is None else np.asarray(self.rot, dtype=np.float64)
        ext = (s + self.r) if self.rot is None else np.abs(self.rot) @ (s + self.r)
        self.lo = c - ext
        self.hi = c + ext

    def sdf(self, x, y, z):
        px, py, pz = x - self.c[0], y - self.c[1], z - self.c[2]
        if self.rot is not None:
            r = self.rot
            lx = r[0, 0] * px + r[1, 0] * py + r[2, 0] * pz
            ly = r[0, 1] * px + r[1, 1] * py + r[2, 1] * pz
            lz = r[0, 2] * px + r[1, 2] * py + r[2, 2] * pz
            px, py, pz = lx, ly, lz
        hx, hy, hz = self.size[0] / 2, self.size[1] / 2, self.size[2] / 2
        qx = np.abs(px) - hx + self.r
        qy = np.abs(py) - hy + self.r
        qz = np.abs(pz) - hz + self.r
        ax, ay, az = np.maximum(qx, 0), np.maximum(qy, 0), np.maximum(qz, 0)
        inner = np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0)
        return np.sqrt(ax * ax + ay * ay + az * az) + inner - self.r


@dataclass
class Cone(Prim):
    """Конус/цилиндр вдоль оси от точки a (радиус ra) к точке b (радиус rb)."""
    a: tuple
    b: tuple
    ra: float
    rb: float

    def __post_init__(self):
        a = np.asarray(self.a, dtype=np.float64)
        b = np.asarray(self.b, dtype=np.float64)
        self.a = tuple(float(v) for v in a)
        self.b = tuple(float(v) for v in b)
        self.lo = np.minimum(a, b) - max(self.ra, self.rb)
        self.hi = np.maximum(a, b) + max(self.ra, self.rb)

    def sdf(self, x, y, z):
        ax, ay, az = self.a
        bx, by, bz = self.b
        px, py, pz = x - ax, y - ay, z - az
        ex, ey, ez = bx - ax, by - ay, bz - az
        denom = ex * ex + ey * ey + ez * ez
        if denom < 1e-12:
            return np.sqrt(px * px + py * py + pz * pz) - max(self.ra, self.rb)
        t = np.clip((px * ex + py * ey + pz * ez) / denom, 0.0, 1.0)
        dx, dy, dz = px - ex * t, py - ey * t, pz - ez * t
        radial = np.sqrt(dx * dx + dy * dy + dz * dz)
        return radial - (self.ra + (self.rb - self.ra) * t)


@dataclass
class RoundedCylinder(Prim):
    """Цилиндр с настоящими дуговыми кромками вокруг одной из осей."""

    c: tuple
    radius: float
    length: float
    edge: float = 0.0
    axis: str = "z"

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        self.c = tuple(float(v) for v in c)
        self.axis = str(self.axis).lower()
        if self.axis not in ("x", "y", "z"):
            raise GeometryError("RoundedCylinder: axis должен быть x, y или z")
        self.radius = float(self.radius)
        self.length = float(self.length)
        self.edge = min(max(0.0, float(self.edge)), self.radius * 0.499,
                        self.length * 0.499)
        ext = np.asarray([self.radius] * 3, dtype=np.float64)
        ext["xyz".index(self.axis)] = self.length * 0.5
        self.lo = c - ext
        self.hi = c + ext

    def sdf(self, x, y, z):
        p = (x - self.c[0], y - self.c[1], z - self.c[2])
        axis = "xyz".index(self.axis)
        radial_axes = [i for i in range(3) if i != axis]
        radial = np.sqrt(p[radial_axes[0]] ** 2 + p[radial_axes[1]] ** 2)
        # Ядро — цилиндр радиуса R-edge и длины L-2*edge. Его
        # Минковски-сумма со сферой edge даёт плоские торцы и дуговые кромки.
        qr = radial - (self.radius - self.edge)
        qa = np.abs(p[axis]) - (self.length * 0.5 - self.edge)
        outside = np.sqrt(np.maximum(qr, 0.0) ** 2 + np.maximum(qa, 0.0) ** 2)
        inside = np.minimum(np.maximum(qr, qa), 0.0)
        return outside + inside - self.edge


@dataclass
class EllipseCylinder(Prim):
    """Плоская эллиптическая пластина вдоль Y с дуговой кромкой.

    В отличие от Ellipsoid имеет плоские торцы: обратная сторона розетки
    действительно прилегает к двери всей площадью, а не одной точкой.
    """

    c: tuple
    rx: float
    rz: float
    length: float
    edge: float = 0.0

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        self.c = tuple(float(v) for v in c)
        self.rx = float(self.rx)
        self.rz = float(self.rz)
        self.length = float(self.length)
        self.edge = min(max(0.0, float(self.edge)), self.rx * 0.499,
                        self.rz * 0.499, self.length * 0.499)
        ext = np.asarray([self.rx, self.length * 0.5, self.rz], dtype=np.float64)
        self.lo = c - ext
        self.hi = c + ext

    def sdf(self, x, y, z):
        rx = self.rx - self.edge
        rz = self.rz - self.edge
        px = x - self.c[0]
        py = y - self.c[1]
        pz = z - self.c[2]
        k0 = np.sqrt((px / rx) ** 2 + (pz / rz) ** 2)
        gradient = np.sqrt((px / (rx * rx)) ** 2 + (pz / (rz * rz)) ** 2)
        # Регуляризованное расстояние до эллипса. В центре градиент
        # вырождается, поэтому там явно задаём отрицательное расстояние.
        planar = np.where(k0 > 1e-10,
                          (k0 - 1.0) * k0 / np.maximum(gradient, 1e-12),
                          -min(rx, rz))
        axial = np.abs(py) - (self.length * 0.5 - self.edge)
        outside = np.sqrt(np.maximum(planar, 0.0) ** 2 + np.maximum(axial, 0.0) ** 2)
        inside = np.minimum(np.maximum(planar, axial), 0.0)
        return outside + inside - self.edge


@dataclass
class Tube(Prim):
    """Скруглённая переменная трубка по polyline как единый SDF-примитив.

    Все сегменты вычисляются внутри одного поля. Поэтому smooth union соединяет
    всю трубку с соседней деталью, а не склеивает каждый её сегмент заново.
    z_scale сохраняет эллиптическое сечение рычагов без потери центральной линии.
    """

    points: object
    radii: object
    z_scale: float = 1.0
    joint: float = 0.12

    def __post_init__(self):
        points = np.asarray(self.points, dtype=np.float64).reshape(-1, 3)
        if len(points) == 0:
            raise GeometryError("Tube: нужна хотя бы одна точка")
        radii = np.asarray(self.radii, dtype=np.float64)
        if radii.ndim == 0:
            radii = np.full(len(points), float(radii))
        radii = radii.reshape(-1)
        if len(radii) != len(points) or np.any(radii <= 0):
            raise GeometryError("Tube: radii должны быть положительными и совпадать с points")
        self.points = points
        self.radii = radii
        self.z_scale = float(self.z_scale)
        if self.z_scale <= 0:
            raise GeometryError("Tube: z_scale должен быть положительным")
        self.joint = float(np.clip(self.joint, 0.0, 0.5))
        pad = np.column_stack((radii, radii, radii * self.z_scale)) * (1.0 + self.joint * 0.25)
        self.lo = np.min(points - pad, axis=0)
        self.hi = np.max(points + pad, axis=0)

    def sdf(self, x, y, z):
        px = np.asarray(x, dtype=np.float64)
        py = np.asarray(y, dtype=np.float64)
        pz = np.asarray(z, dtype=np.float64) / self.z_scale
        best = np.full_like(px, BIG, dtype=np.float64)
        points = self.points
        for i in range(max(1, len(points) - 1)):
            a = points[min(i, len(points) - 1)]
            b = points[min(i + 1, len(points) - 1)]
            ax, ay, az = a[0], a[1], a[2] / self.z_scale
            bx, by, bz = b[0], b[1], b[2] / self.z_scale
            ex, ey, ez = bx - ax, by - ay, bz - az
            denom = ex * ex + ey * ey + ez * ez
            qx, qy, qz = px - ax, py - ay, pz - az
            t = np.clip((qx * ex + qy * ey + qz * ez) / max(denom, 1e-12), 0.0, 1.0)
            dx, dy, dz = qx - ex * t, qy - ey * t, qz - ez * t
            ra = self.radii[min(i, len(points) - 1)]
            rb = self.radii[min(i + 1, len(points) - 1)]
            distance = np.sqrt(dx * dx + dy * dy + dz * dz) - (ra + (rb - ra) * t)
            if i == 0 or self.joint <= 1e-9:
                best = distance if i == 0 else np.minimum(best, distance)
            else:
                # Маленький smooth min только внутри ОДНОГО поля убирает
                # касательный излом polyline. Отдельные меши/булевы операции
                # для сегментов по-прежнему не создаются.
                k = min(float(ra), float(rb)) * self.joint
                h = np.clip(0.5 + 0.5 * (best - distance) / max(k, 1e-12), 0.0, 1.0)
                best = best + (distance - best) * h - k * h * (1.0 - h)
        return best * self.z_scale


@dataclass
class Torus(Prim):
    c: tuple
    R: float
    r: float
    axis: str = "z"

    def __post_init__(self):
        c = np.asarray(self.c, dtype=np.float64)
        self.c = tuple(float(v) for v in c)
        ext = np.array([self.R + self.r] * 3, dtype=np.float64)
        if self.axis == "z":
            ext[2] = self.r
        elif self.axis == "y":
            ext[1] = self.r
        else:
            ext[0] = self.r
        self.lo = c - ext
        self.hi = c + ext

    def sdf(self, x, y, z):
        px, py, pz = x - self.c[0], y - self.c[1], z - self.c[2]
        if self.axis == "z":
            q = np.sqrt(px * px + py * py)
            return np.sqrt((q - self.R) ** 2 + pz * pz) - self.r
        if self.axis == "x":
            q = np.sqrt(py * py + pz * pz)
            return np.sqrt((q - self.R) ** 2 + px * px) - self.r
        q = np.sqrt(px * px + pz * pz)
        return np.sqrt((q - self.R) ** 2 + py * py) - self.r


def smoothstep(a, b, v):
    t = np.clip((v - a) / (b - a), 0.0, 1.0) if abs(b - a) > 1e-12 else np.zeros_like(v)
    return t * t * (3 - 2 * t)


def sphere(c, r) -> Sphere:
    return Sphere(c, r)


def ellipsoid(c, radii, rot=None) -> Ellipsoid:
    return Ellipsoid(c, radii, rot)


def capsule(a, b, r) -> Capsule:
    return Capsule(a, b, r)


def round_box(c, size, r=0.0, rot=None) -> RoundBox:
    return RoundBox(c, size, r, rot)


def cone(a, b, ra, rb=None) -> Cone:
    return Cone(a, b, ra, ra if rb is None else rb)


def rounded_cylinder(c, radius, length, edge=0.0, axis="z"):
    return RoundedCylinder(c, radius, length, edge, axis)


def tube(points, radii, z_scale=1.0, joint=0.12):
    return Tube(points, radii, z_scale, joint)


def lerp(a, b, t):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return tuple(float(v) for v in (a + (b - a) * t))
