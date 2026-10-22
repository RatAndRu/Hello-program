"""Геометрические утилиты: сетки, профили, развёртки, экспорт.

Все размеры — миллиметры, ось Z — вверх (как в большинстве CAD и 3D-печати).
Для GLB координаты переводятся в стандартную Y-up систему.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Iterable, Sequence

import manifold3d as mf
import numpy as np

from .errors import GeometryError

Vec3 = tuple[float, float, float]
EPS = 1e-9


# --------------------------------------------------------------------------- #
#  Базовые преобразования Manifold <-> numpy
# --------------------------------------------------------------------------- #

def auto_segments(radius: float, tolerance: float = 0.12,
                  min_n: int = 12, max_n: int = 256) -> int:
    """Сколько сегментов нужно, чтобы огранка была не грубее допуска.

    Раньше у примитивов стояло фиксированное число сегментов: маленький шарик
    получал тысячи лишних треугольников, а большой — заметные грани. Здесь
    число сегментов считается по радиусу и допуску (стрелка прогиба хорды).
    """
    r = max(float(radius), 1e-6)
    tol = min(max(float(tolerance), 1e-3), r * 0.5)
    n = math.pi / math.acos(max(-0.999999, min(1.0, 1.0 - tol / r)))
    n = int(math.ceil(n / 4.0) * 4)
    return int(max(min_n, min(max_n, n)))


# Допуск огранки по умолчанию, мм. 0,06 мм на модели 100–200 мм глазом не
# видно, а число сегментов (и треугольников) падает в разы.
FINENESS_MM = 0.06


def limit_segments(requested, radius: float, tolerance: float = FINENESS_MM,
                   max_n: int = 512) -> int:
    """Ограничивает число сегментов разумным: лишние грани на ровной
    поверхности не видны, но раздувают модель.

    ``requested`` — сколько попросил сценарий (None — посчитать самому).
    Возвращает число сегментов, при котором стрелка прогиба хорды не больше
    ``tolerance`` мм.
    """
    need = auto_segments(radius, tolerance=tolerance, max_n=max_n)
    if requested is None:
        return int(need)
    return int(min(max(8, int(requested)), need))


def manifold_mesh(m: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    """Возвращает (vertices float64 Nx3, faces int64 Nx3)."""
    mesh = m.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)
    if verts.ndim != 2 or verts.shape[1] < 3:
        verts = np.zeros((0, 3), dtype=np.float64)
    else:
        verts = verts[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
    return verts, faces


def manifold_from_arrays(verts: np.ndarray, faces: np.ndarray, what: str = "фигура") -> mf.Manifold:
    """Собирает Manifold из массивов, проверяя корректность."""
    verts = np.ascontiguousarray(verts, dtype=np.float32)
    faces = np.ascontiguousarray(faces, dtype=np.uint32)
    if len(verts) == 0 or len(faces) == 0:
        raise GeometryError(f"Не удалось построить {what}: пустая сетка.")
    # используем только позиции
    mesh = mf.Mesh(vert_properties=verts, tri_verts=faces)
    solid = mf.Manifold(mesh)
    status = solid.status()
    if status != mf.Error.NoError:
        raise GeometryError(
            f"Не удалось построить {what}: сетка не является замкнутой ({status.name}).",
            hint="Проверьте, что профиль не самопересекается и все сечения имеют одинаковое число точек.",
        )
    if solid.is_empty() or solid.volume() <= 0:
        raise GeometryError(
            f"{what.capitalize()} получилась пустой.",
            hint="Проверьте размеры и порядок точек профиля (против часовой стрелки).",
        )
    return solid


def solid_info(m: mf.Manifold) -> dict:
    bb = m.bounding_box()
    return {
        "bbox": [float(v) for v in bb],
        "size": [float(bb[3] - bb[0]), float(bb[4] - bb[1]), float(bb[5] - bb[2])],
        "volume": float(m.volume()),
        "area": float(m.surface_area()),
        "tris": int(m.num_tri()),
        "verts": int(m.num_vert()),
        "genus": int(m.genus()),
        "status": m.status().name,
    }


# --------------------------------------------------------------------------- #
#  2D-профили
# --------------------------------------------------------------------------- #

def as_points(value, dims: int = 2, name: str = "points") -> np.ndarray:
    """Приводит список/массив к форме (N, dims). Понимает плоский список чисел."""
    if value is None:
        raise GeometryError(f"Не задан параметр {name}.")
    if isinstance(value, np.ndarray):
        arr = value.astype(np.float64)
    elif isinstance(value, (list, tuple)):
        if len(value) == 0:
            return np.zeros((0, dims))
        items = list(value)
        if all(isinstance(x, (list, tuple, np.ndarray)) for x in items):
            arr = np.array([[float(c) for c in x] for x in items], dtype=np.float64)
        elif all(not isinstance(x, (list, tuple, np.ndarray)) for x in items):
            nums = [float(x) for x in items]
            if len(nums) % dims != 0:
                raise GeometryError(
                    f"Параметр {name}: {len(nums)} чисел не делится на {dims}.",
                    hint="Точки задаются как [[x,y],[x,y],...] или плоским списком x,y,x,y,...",
                )
            arr = np.array(nums, dtype=np.float64).reshape(-1, dims)
        else:
            raise GeometryError(f"Параметр {name}: смешанный формат точек.")
    else:
        raise GeometryError(f"Параметр {name} должен быть списком точек.")

    if arr.ndim == 1 and arr.size % dims == 0:
        arr = arr.reshape(-1, dims)
    if arr.ndim != 2 or arr.shape[1] < dims:
        raise GeometryError(f"Параметр {name}: ожидаются точки по {dims} координат.")
    if arr.shape[1] > dims:
        arr = arr[:, :dims]
    if not np.all(np.isfinite(arr)):
        raise GeometryError(f"Параметр {name}: есть бесконечные или нечисловые координаты.")
    return arr


def polygon_area(points2d: np.ndarray) -> float:
    p = np.asarray(points2d, dtype=np.float64)
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def ensure_ccw(points2d: np.ndarray) -> np.ndarray:
    return points2d if polygon_area(points2d) >= 0 else points2d[::-1].copy()


def dedupe_points(points2d: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Убирает совпадающие подряд точки, оставляя замкнутость."""
    pts = np.asarray(points2d, dtype=np.float64)
    if len(pts) < 2:
        return pts
    keep = [0]
    for i in range(1, len(pts)):
        if np.linalg.norm(pts[i] - pts[keep[-1]]) > tol:
            keep.append(i)
    out = pts[keep]
    if len(out) > 2 and np.linalg.norm(out[0] - out[-1]) <= tol:
        out = out[:-1]
    return out


def catmull_rom(points: np.ndarray, closed: bool = False, samples: int = 8,
                alpha: float = 0.5) -> np.ndarray:
    """Сглаживание ломаной сплайном Катмулла-Рома (для профилей и путей)."""
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    samples = max(1, int(samples))
    if n < 2 or samples <= 1:
        return pts.copy()

    if closed:
        idx = lambda i: pts[i % n]  # noqa: E731
        seg_count = n
    else:
        idx = lambda i: pts[min(max(i, 0), n - 1)]  # noqa: E731
        seg_count = n - 1

    out = []
    for i in range(seg_count):
        p0, p1, p2, p3 = idx(i - 1), idx(i), idx(i + 1), idx(i + 2)
        # центростремительная параметризация: меньше «выбросов» на изломах
        t0 = 0.0
        t1 = t0 + max(float(np.linalg.norm(p1 - p0)) ** 0.5, 1e-6)
        t2 = t1 + max(float(np.linalg.norm(p2 - p1)) ** 0.5, 1e-6)
        t3 = t2 + max(float(np.linalg.norm(p3 - p2)) ** 0.5, 1e-6)
        for sc in range(samples):
            t = t1 + (t2 - t1) * (sc / samples)
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    if not closed:
        out.append(pts[-1])
    return np.asarray(out, dtype=np.float64)


def smooth_closed_profile(points2d: np.ndarray, samples: int = 4,
                          keep_count: bool = False) -> np.ndarray:
    """Сглаживает замкнутый 2D-профиль без выбросов: результат остаётся
    внутри исходного прямоугольника, радиус не становится отрицательным."""
    pts = np.asarray(points2d, dtype=np.float64)
    if len(pts) < 4 or samples < 2:
        return pts.copy()
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    out = catmull_rom(pts, closed=True, samples=int(samples))
    out = np.clip(out, lo, hi)
    if not keep_count:
        out[:, 0] = np.clip(out[:, 0], 0.0, None)
        return dedupe_points(out)
    return out


def _arc(center: Vec3, radius: float, a0: float, a1: float, steps: int) -> np.ndarray:
    steps = max(2, int(steps))
    t = np.linspace(a0, a1, steps + 1)
    return np.stack([center[0] + radius * np.cos(t), center[1] + radius * np.sin(t)], axis=1)


def fillet_polyline(points2d: np.ndarray, radius: float, closed: bool = True,
                    arc_steps: int = 8, skip_axis: bool = False) -> np.ndarray:
    """Скругляет углы замкнутого профиля дугами радиуса radius.

    Это то, что делает профиль кружки «заводским»: прямые стенки и
    аккуратные скругления в углах.
    """
    pts = np.asarray(points2d, dtype=np.float64)
    n = len(pts)
    if radius <= 0 or n < 3:
        return pts.copy()

    out: list[np.ndarray] = []
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            out.append(pts[i])
            continue
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        if skip_axis and (cur[0] < 1e-6 or (prev[0] < 1e-6 and nxt[0] < 1e-6)):
            out.append(cur)
            continue
        v0 = prev - cur
        v1 = nxt - cur
        l0 = float(np.linalg.norm(v0))
        l1 = float(np.linalg.norm(v1))
        if l0 < 1e-9 or l1 < 1e-9:
            continue
        u0 = v0 / l0
        u1 = v1 / l1
        ang = math.acos(max(-1.0, min(1.0, float(np.dot(u0, u1)))))
        if ang > math.pi - 1e-4 or ang < 1e-4:
            out.append(cur)
            continue
        t = radius / math.tan(ang / 2.0)
        t = min(t, 0.48 * l0, 0.48 * l1)
        if t < 1e-6:
            out.append(cur)
            continue
        r_eff = t * math.tan(ang / 2.0)
        a_pt = cur + u0 * t
        b_pt = cur + u1 * t
        bis = u0 + u1
        bl = float(np.linalg.norm(bis))
        if bl < 1e-9:
            out.append(cur)
            continue
        bis /= bl
        d = t / math.cos(ang / 2.0)
        center = cur + bis * d
        aa = math.atan2(a_pt[1] - center[1], a_pt[0] - center[0])
        bb = math.atan2(b_pt[1] - center[1], b_pt[0] - center[0])
        delta = (bb - aa + math.pi) % (2 * math.pi) - math.pi
        steps = max(2, int(abs(delta) / (math.pi / 24)) + 1)
        steps = min(max(steps, arc_steps), 48)
        arc = _arc(center, r_eff, aa, aa + delta, steps)
        out.extend([arc[0], *arc[1:]])
    arr = np.asarray(out, dtype=np.float64)
    return dedupe_points(arr)


def circle_profile(radius: float, sides: int = 32) -> np.ndarray:
    """Окружность в плоскости XY, против часовой стрелки."""
    sides = max(3, int(sides))
    t = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    return np.stack([radius * np.cos(t), radius * np.sin(t)], axis=1)


def ellipse_profile(width: float, height: float, sides: int = 32) -> np.ndarray:
    sides = max(3, int(sides))
    t = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    return np.stack([width / 2 * np.cos(t), height / 2 * np.sin(t)], axis=1)


# --------------------------------------------------------------------------- #
#  Сетки: трубы (sweep / loft) и кривые крышки
# --------------------------------------------------------------------------- #

def triangulate_2d(points2d: np.ndarray) -> np.ndarray:
    """Триангуляция простого многоугольника (CCW) средствами Manifold."""
    pts = np.ascontiguousarray(ensure_ccw(dedupe_points(points2d)), dtype=np.float64)
    try:
        tris = mf.triangulate([pts])
    except Exception as exc:  # pragma: no cover - защита от неожиданностей
        raise GeometryError(f"Не удалось триангулировать профиль: {exc}") from exc
    return np.asarray(tris, dtype=np.int64).reshape(-1, 3)


def _rings_to_arrays(rings: list[np.ndarray], profile2d: np.ndarray,
                     cap_start: bool = True, cap_end: bool = True) -> tuple[np.ndarray, np.ndarray]:
    n = len(rings[0])
    verts = np.concatenate(rings, axis=0)
    faces: list[tuple[int, int, int]] = []
    for i in range(len(rings) - 1):
        a = i * n
        b = (i + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((a + j, a + j2, b + j2))
            faces.append((a + j, b + j2, b + j))
    tris = triangulate_2d(profile2d)
    if cap_start:
        base = 0
        for t in tris:
            faces.append((base + int(t[2]), base + int(t[1]), base + int(t[0])))
    if cap_end:
        base = (len(rings) - 1) * n
        for t in tris:
            faces.append((base + int(t[0]), base + int(t[1]), base + int(t[2])))
    return verts, np.asarray(faces, dtype=np.int64)


def sweep_solid(path: np.ndarray, profile: np.ndarray, closed_path: bool = False,
                twist_deg: float = 0.0, scale_end: float = 1.0,
                up_hint: Sequence[float] = (0.0, 0.0, 1.0),
                what: str = "развёртка",
                scale_curve: Sequence[float] | None = None,
                round_caps: float = 0.0) -> mf.Manifold:
    """Развёртка 2D-профиля вдоль 3D-пути (с параллельным переносом)."""
    path = np.asarray(path, dtype=np.float64)
    profile = ensure_ccw(dedupe_points(np.asarray(profile, dtype=np.float64)))
    if len(path) < 2:
        raise GeometryError("Путь развёртки должен содержать минимум 2 точки.")
    if len(profile) < 3:
        raise GeometryError("Профиль развёртки должен содержать минимум 3 точки.")

    # касательные
    tangents = np.zeros_like(path)
    for i in range(len(path)):
        if closed_path:
            t = path[(i + 1) % len(path)] - path[(i - 1) % len(path)]
        elif i == 0:
            t = path[1] - path[0]
        elif i == len(path) - 1:
            t = path[-1] - path[-2]
        else:
            t = path[i + 1] - path[i - 1]
        n = np.linalg.norm(t)
        if n < EPS:
            raise GeometryError("В пути развёртки есть совпадающие точки.")
        tangents[i] = t / n

    up = np.asarray(up_hint, dtype=np.float64)
    if abs(float(np.dot(up / (np.linalg.norm(up) + EPS), tangents[0]))) > 0.98:
        up = np.array([0.0, 1.0, 0.0])
    right = np.cross(up, tangents[0])
    rn = np.linalg.norm(right)
    if rn < EPS:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right /= rn
    up = np.cross(tangents[0], right)
    up /= np.linalg.norm(up) + EPS

    rings = []
    frames = []
    npts = len(path) if closed_path else len(path)
    total = npts if closed_path else max(1, len(path) - 1)
    for i in range(len(path)):
        if i > 0:
            # параллельный перенос вектора up на новую касательную
            up = up - tangents[i] * float(np.dot(up, tangents[i]))
            un = np.linalg.norm(up)
            if un < EPS:
                up = np.cross(tangents[i], right)
            else:
                up /= un
            right = np.cross(up, tangents[i])
            right /= np.linalg.norm(right) + EPS
            up = np.cross(tangents[i], right)
            up /= np.linalg.norm(up) + EPS
        frac = i / total
        if scale_curve:
            # плавная «луковица»: радиус по длине пути (для банана, ручек, носиков)
            xs = np.linspace(0.0, 1.0, len(scale_curve))
            sc = float(np.interp(frac, xs, np.asarray(scale_curve, dtype=np.float64)))
        else:
            sc = 1.0 + (scale_end - 1.0) * frac
        ang = math.radians(twist_deg) * frac
        ca, sa = math.cos(ang), math.sin(ang)
        px = profile[:, 0] * sc
        py = profile[:, 1] * sc
        lx = px * ca - py * sa
        ly = px * sa + py * ca
        rings.append(path[i] + right[None, :] * lx[:, None] + up[None, :] * ly[:, None])
        frames.append((path[i].copy(), right.copy(), up.copy(), sc))

    if round_caps > 0.0 and not closed_path and len(frames) >= 2:
        # Полукруглые торцы: несколько колец, сжимающихся к точке.
        # Спасает бананы, ручки и носики от плоских «срезов».
        steps = 4
        p0, r0, u0, sc0 = frames[0]
        p1, r1, u1, sc1 = frames[-1]
        t0 = tangents[0]
        t1 = tangents[-1]
        rad0 = float(np.max(np.linalg.norm(profile, axis=1))) * sc0 * round_caps
        rad1 = float(np.max(np.linalg.norm(profile, axis=1))) * sc1 * round_caps
        head, tail = [], []
        for k in range(1, steps + 1):
            phi = (math.pi / 2) * k / steps
            f = math.cos(phi)
            head.append(p0 - t0 * (rad0 * math.sin(phi))
                        + r0[None, :] * (profile[:, 0] * sc0 * f)[:, None]
                        + u0[None, :] * (profile[:, 1] * sc0 * f)[:, None])
            tail.append(p1 + t1 * (rad1 * math.sin(phi))
                        + r1[None, :] * (profile[:, 0] * sc1 * f)[:, None]
                        + u1[None, :] * (profile[:, 1] * sc1 * f)[:, None])
        rings = list(reversed(head)) + rings + tail
    verts, faces = _rings_to_arrays(rings, profile, cap_start=not closed_path,
                                    cap_end=not closed_path)
    if closed_path:
        n = len(profile)
        a = (len(rings) - 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces = np.vstack([faces, [[a + j, a + j2, j2], [a + j, j2, j]]])
    return manifold_from_arrays(verts, faces, what)


def loft_solid(sections: list[np.ndarray], positions: Sequence[float],
               axis: str = "z", caps: bool = True, what: str = "лофт") -> mf.Manifold:
    """Соединяет 2D-сечения, расставленные вдоль оси."""
    if len(sections) < 2:
        raise GeometryError("Лофт требует минимум 2 сечения.")
    if len(sections) != len(positions):
        raise GeometryError("Число сечений и позиций должно совпадать.")
    counts = {len(s) for s in sections}
    if len(counts) != 1:
        raise GeometryError(
            f"У сечений разное число точек ({sorted(counts)}).",
            hint="Для лофта все сечения должны иметь одинаковое количество точек.",
        )
    first = dedupe_points(np.asarray(sections[0], dtype=np.float64))
    if len(first) != len(sections[0]):
        raise GeometryError("В сечении есть совпадающие точки.")
    flip = polygon_area(first) < 0
    prof = first[::-1].copy() if flip else first
    secs = []
    for s in sections:
        arr = np.asarray(s, dtype=np.float64)
        secs.append(arr[::-1].copy() if flip else arr)
    us = [s[:, 0] for s in secs]
    vs = [s[:, 1] for s in secs]
    ws = list(positions)

    # проверка соответствия точек: не позволим сечениям «перекрутиться»
    n = len(prof)
    rings = []
    for k in range(len(secs)):
        u, v, w = us[k], vs[k], ws[k]
        if axis == "z":
            ring = np.stack([u, v, np.full(n, w)], axis=1)
        elif axis == "x":
            ring = np.stack([np.full(n, w), u, v], axis=1)
        elif axis == "y":
            ring = np.stack([u, np.full(n, w), v], axis=1)
        else:
            raise GeometryError("Ось лофта должна быть x, y или z.")
        rings.append(ring)

    verts, faces = _rings_to_arrays(rings, prof, cap_start=caps, cap_end=caps)
    return manifold_from_arrays(verts, faces, what)


def rings_from_sections(sections: list[np.ndarray], positions: Sequence[float],
                        axis: str) -> list[np.ndarray]:
    """Только кольца (без сетки) — используется для сглаженного лофта."""
    n = len(sections[0])
    rings = []
    for k, (s, w) in enumerate(zip(sections, positions)):
        u, v = s[:, 0], s[:, 1]
        if axis == "z":
            rings.append(np.stack([u, v, np.full(n, w)], axis=1))
        elif axis == "x":
            rings.append(np.stack([np.full(n, w), u, v], axis=1))
        elif axis == "y":
            rings.append(np.stack([u, np.full(n, w), v], axis=1))
        else:
            raise GeometryError("Ось лофта должна быть x, y или z.")
    return rings


def loft_solid_smooth(sections: list[np.ndarray], positions: Sequence[float],
                      axis: str = "z", caps: bool = True, smooth: int = 4,
                      what: str = "лофт") -> mf.Manifold:
    """Лофт со сглаживанием вдоль оси (полезно для кузовов, бутылок, туш)."""
    if smooth <= 1:
        return loft_solid(sections, positions, axis=axis, caps=caps, what=what)
    first = dedupe_points(np.asarray(sections[0], dtype=np.float64))
    flip = polygon_area(first) < 0
    secs = [np.asarray(s, dtype=np.float64)[::-1].copy() if flip else np.asarray(s, dtype=np.float64)
            for s in sections]
    base_rings = rings_from_sections(secs, positions, axis)
    # сглаживаем траекторию каждой вершины сечения
    stack = np.stack(base_rings, axis=0)  # (S, N, 3)
    S, N, _ = stack.shape
    out = []
    for j in range(N):
        cr = catmull_rom(stack[:, j, :], closed=False, samples=int(smooth))
        out.append(cr)
    # out[j] имеет длину ((S-1)*smooth + 1)
    rings = [np.stack([out[j][i] for j in range(N)], axis=0) for i in range(len(out[0]))]
    prof = secs[0]
    verts, faces = _rings_to_arrays(rings, prof, cap_start=caps, cap_end=caps)
    return manifold_from_arrays(verts, faces, what)


def hull_of_manifolds(solids: Iterable[mf.Manifold]) -> mf.Manifold:
    pts = []
    for s in solids:
        v, _ = manifold_mesh(s)
        if len(v):
            pts.append(v)
    if not pts:
        raise GeometryError("Для выпуклой оболочки нет точек.")
    allp = np.concatenate(pts, axis=0)
    # прореживаем очень большие облака точек
    if len(allp) > 60000:
        step = max(1, len(allp) // 60000)
        allp = allp[::step]
    hull = mf.Manifold.hull_points(np.ascontiguousarray(allp, dtype=np.float64))
    if hull.is_empty():
        raise GeometryError("Выпуклая оболочка не построена (точки лежат в одной плоскости).")
    return hull


# --------------------------------------------------------------------------- #
#  Нормали с разделением по углу (для красивого рендера)
# --------------------------------------------------------------------------- #

def crease_normals(verts: np.ndarray, faces: np.ndarray, angle_deg: float = 38.0):
    """Возвращает (verts, normals, faces) с расщеплением рёбер жёсткости.

    Позволяет одновременно иметь гладкие стенки цилиндра и острые грани куба.
    """
    verts = np.asarray(verts, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if len(faces) == 0:
        return verts, np.zeros_like(verts), faces

    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    area = np.linalg.norm(cross, axis=1)
    fn = np.zeros_like(cross)
    good = area > 1e-12
    fn[good] = cross[good] / area[good, None]
    cos_t = math.cos(math.radians(angle_deg))

    # инцидентность вершин и граней
    flat_v = faces.ravel()
    flat_f = np.repeat(np.arange(len(faces)), 3)
    order = np.argsort(flat_v, kind="stable")
    sv = flat_v[order]
    sf = flat_f[order]
    uniq, starts = np.unique(sv, return_index=True)
    ends = np.append(starts[1:], len(sv))

    new_verts: list[np.ndarray] = []
    new_normals: list[np.ndarray] = []
    new_faces = np.zeros_like(faces)
    counter = 0
    # Быстрый путь для больших органических мешей: одна гладкая нормаль на вершину
    if len(verts) > 400000:
        vnorm = np.zeros_like(verts)
        for fi in range(len(faces)):
            w = max(area[fi], 1e-12)
            vnorm[faces[fi]] += fn[fi] * w
        norms = np.linalg.norm(vnorm, axis=1)
        goodv = norms > 1e-12
        vnorm[goodv] /= norms[goodv, None]
        return verts, vnorm, faces

    for vi in range(len(uniq)):
        v = int(uniq[vi])
        incident = sf[starts[vi]:ends[vi]]
        clusters: list[dict] = []
        for f in incident:
            nrm = fn[f]
            placed = False
            for cl in clusters:
                if float(np.dot(nrm, cl["rep"])) >= cos_t:
                    cl["faces"].append(int(f))
                    cl["sum"] += fn[f] * max(area[f], 1e-12)
                    placed = True
                    break
            if not placed:
                clusters.append({"rep": nrm, "faces": [int(f)], "sum": fn[f] * max(area[f], 1e-12)})
        # если кластер один — не плодим вершины
        for cl in clusters:
            s = cl["sum"]
            ln = float(np.linalg.norm(s))
            nrm = s / ln if ln > 1e-12 else np.array([0.0, 0.0, 1.0])
            new_verts.append(verts[v])
            new_normals.append(nrm)
            for f in cl["faces"]:
                # заменяем только тот угол, который соответствовал этой вершине
                for k in range(3):
                    if faces[f, k] == v and new_faces[f, k] == 0:
                        new_faces[f, k] = counter + 1
            counter += 1
    remap = new_faces - 1
    return (np.asarray(new_verts, dtype=np.float64),
            np.asarray(new_normals, dtype=np.float64),
            remap.astype(np.int64))


# --------------------------------------------------------------------------- #
#  Экспорт
# --------------------------------------------------------------------------- #

def _glb_geometry(m: mf.Manifold, max_tris: int = 4_000_000):
    verts, faces = manifold_mesh(m)
    nv, normals, nf = crease_normals(verts, faces, 38.0)
    # Z-up -> Y-up
    nv_y = np.stack([nv[:, 0], nv[:, 2], -nv[:, 1]], axis=1)
    nrm_y = np.stack([normals[:, 0], normals[:, 2], -normals[:, 1]], axis=1)
    return nv_y, nrm_y, nf


def export_glb(objects, with_normals: bool = True, animation: dict | None = None,
               animations: list[dict] | None = None, keys: dict | None = None,
               groups: dict | None = None) -> bytes:
    """Собирает GLB с отдельным материалом на каждый объект.

    Поддерживает текстуры (UV-развёртка + baseColorTexture) и анимацию
    (вращение / формирование / разлёт) прямо в файле — Blender её увидит.
    """
    import trimesh
    from trimesh.visual.material import PBRMaterial
    from .textures import load_texture_image, uv_for, uv_triangles

    scene = trimesh.Scene()
    centers: dict[str, np.ndarray] = {}
    diagonal = 1.0
    if objects:
        lo = np.array([1e18, 1e18, 1e18])
        hi = -lo.copy()
        for obj in objects:
            bb = obj.manifold.bounding_box()
            lo = np.minimum(lo, bb[:3])
            hi = np.maximum(hi, bb[3:])
        diagonal = float(np.linalg.norm(hi - lo)) or 1.0
    for obj in objects:
        if obj.manifold.is_empty():
            continue
        if with_normals:
            verts, normals, faces = _glb_geometry(obj.manifold)
        else:
            verts, faces = manifold_mesh(obj.manifold)
            verts = np.stack([verts[:, 0], verts[:, 2], -verts[:, 1]], axis=1)
            normals = None
        rgba = color_to_gltf(obj.color)
        uv_mode = getattr(obj, "uv", "auto") or "auto"
        material = PBRMaterial(
            name=f"mat_{obj.name}",
            baseColorFactor=rgba,
            metallicFactor=float(obj.metal),
            roughnessFactor=float(obj.rough),
            doubleSided=False,
        )
        uv = uv_for(verts, uv_mode)
        if getattr(obj, "tex", None):
            image = load_texture_image(obj.tex.get("path", ""))
            if image is not None and len(faces):
                material.baseColorTexture = image
                material.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
                normal_image = load_texture_image(obj.tex.get("normal_path", ""))
                if normal_image is not None:
                    material.normalTexture = normal_image
                # разворачиваем геометрию по треугольникам: шов текстуры не виден
                flat_faces = faces.reshape(-1)
                # verts уже в Y-up glTF, поэтому bbox считаем по ним же
                uv = uv_triangles(verts, faces, uv_mode, bbox=None)
                verts = verts[flat_faces]
                if normals is not None:
                    normals = normals[flat_faces]
                faces = np.arange(len(verts), dtype=np.int64).reshape(-1, 3)
        visual = (trimesh.visual.TextureVisuals(uv=uv, material=material) if uv is not None
                  else trimesh.visual.TextureVisuals(material=material))
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals,
                               process=False, visual=visual)
        mesh.metadata["name"] = obj.name
        scene.add_geometry(mesh, node_name=obj.name, geom_name=obj.name)
        centers[obj.name] = verts.mean(axis=0)
    if len(scene.geometry) == 0:
        raise GeometryError("Нечего экспортировать: нет видимых объектов.")
    data = trimesh.exchange.gltf.export_glb(scene, include_normals=True)
    clips = [sp for sp in (animations or []) if sp]
    if animation and not clips:
        clips = [animation]
    if clips or keys:
        try:
            data = add_glb_animations(bytes(data), clips, centers, diagonal, keys=keys,
                                      groups=groups)
        except Exception:
            pass  # анимация — бонус: без неё файл остаётся корректным
    return bytes(data)


# --------------------------------------------------------------------------- #
#  Анимация внутри GLB (без внешних зависимостей)
# --------------------------------------------------------------------------- #

def _glb_read(data: bytes) -> tuple[dict, bytes]:
    import json
    import struct as _struct
    if data[:4] != b"glTF":
        raise GeometryError("Это не GLB-файл.")
    offset = 12
    doc, binary = None, b""
    while offset < len(data):
        length, ctype = _struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8: offset + 8 + length]
        offset += 8 + length
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            binary = chunk
    if doc is None:
        raise GeometryError("В GLB нет JSON-описания.")
    return doc, binary


def _glb_write(doc: dict, binary: bytes) -> bytes:
    import json
    import struct as _struct
    js = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bn = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(js) + (8 + len(bn) if bn else 0)
    out = b"glTF" + _struct.pack("<II", 2, total)
    out += _struct.pack("<II", len(js), 0x4E4F534A) + js
    if bn:
        out += _struct.pack("<II", len(bn), 0x004E4942) + bn
    return out


def add_glb_animation(data: bytes, spec: dict, centers: dict | None = None,
                      diagonal: float = 1.0) -> bytes:
    """Добавляет в GLB одну анимацию (совместимость со старым вызовом)."""
    return add_glb_animations(data, [spec], centers, diagonal)


def _gltf_axis(axis: str, sign: float = 1.0) -> np.ndarray:
    """Ось сценария (Z-up) в координатах glTF (Y-up): x→x, y→−z, z→y."""
    a = str(axis or "z").lower()
    vec = {"x": (1.0, 0.0, 0.0), "y": (0.0, 0.0, -1.0), "z": (0.0, 1.0, 0.0)}.get(a)
    if vec is None:
        vec = (0.0, 1.0, 0.0)
    return np.array(vec, dtype=np.float64) * float(sign)


def _gltf_vec(v) -> np.ndarray:
    return np.array([float(v[0]), float(v[2]), -float(v[1])], dtype=np.float64)


def _qrot(q, v) -> np.ndarray:
    """Поворот вектора кватернионом (x, y, z, w)."""
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    xyz = q[:3]
    w = q[3]
    t = np.cross(xyz, v) + w * v
    return v + 2.0 * np.cross(xyz, t)


def _quat(axis: np.ndarray, angle: float) -> np.ndarray:
    ax = np.asarray(axis, dtype=np.float64)
    ln = float(np.linalg.norm(ax))
    if ln < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    ax = ax / ln
    h = float(angle) / 2.0
    return np.array([ax[0] * np.sin(h), ax[1] * np.sin(h), ax[2] * np.sin(h),
                     np.cos(h)], dtype=np.float64)


def _qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], dtype=np.float64)


def _qconj(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=np.float64)


# поворот из системы сценария (Z-up) в glTF (Y-up): −90° вокруг X
_Q_TO_GLTF = _quat(np.array([1.0, 0.0, 0.0]), -np.pi / 2)


def _euler_modeling_to_gltf(rot_deg) -> np.ndarray:
    """Углы Эйлера сценария (градусы, X→Y→Z) → кватернион glTF."""
    rx, ry, rz = [np.radians(float(v)) for v in rot_deg]
    q = _qmul(_qmul(_quat(np.array([0.0, 0.0, 1.0]), rz),
                    _quat(np.array([0.0, 1.0, 0.0]), ry)),
              _quat(np.array([1.0, 0.0, 0.0]), rx))
    return _qmul(_qmul(_Q_TO_GLTF, q), _qconj(_Q_TO_GLTF))


def _node_trs(node: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Разбирает узел на translation / rotation / scale (matrix тоже понимает)."""
    if "matrix" in node:
        m = np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
        t = m[:3, 3].copy()
        sx = float(np.linalg.norm(m[:3, 0])) or 1.0
        sy = float(np.linalg.norm(m[:3, 1])) or 1.0
        sz = float(np.linalg.norm(m[:3, 2])) or 1.0
        rot = np.stack([m[:3, 0] / sx, m[:3, 1] / sy, m[:3, 2] / sz], axis=1)
        # матрица → кватернион
        tr = rot[0, 0] + rot[1, 1] + rot[2, 2]
        if tr > 0:
            w = np.sqrt(tr + 1.0) * 2
            q = np.array([(rot[2, 1] - rot[1, 2]) / w, (rot[0, 2] - rot[2, 0]) / w,
                          (rot[1, 0] - rot[0, 1]) / w, 0.25 * w])
        elif rot[0, 0] > rot[1, 1] and rot[0, 0] > rot[2, 2]:
            w = np.sqrt(1.0 + rot[0, 0] - rot[1, 1] - rot[2, 2]) * 2
            q = np.array([0.25 * w, (rot[0, 1] + rot[1, 0]) / w,
                          (rot[0, 2] + rot[2, 0]) / w, (rot[2, 1] - rot[1, 2]) / w])
        elif rot[1, 1] > rot[2, 2]:
            w = np.sqrt(1.0 + rot[1, 1] - rot[0, 0] - rot[2, 2]) * 2
            q = np.array([(rot[0, 1] + rot[1, 0]) / w, 0.25 * w,
                          (rot[1, 2] + rot[2, 1]) / w, (rot[0, 2] - rot[2, 0]) / w])
        else:
            w = np.sqrt(1.0 + rot[2, 2] - rot[0, 0] - rot[1, 1]) * 2
            q = np.array([(rot[0, 2] + rot[2, 0]) / w, (rot[1, 2] + rot[2, 1]) / w,
                          0.25 * w, (rot[1, 0] - rot[0, 1]) / w])
        q = q / (np.linalg.norm(q) or 1.0)
        return t, q, np.array([sx, sy, sz])
    return (np.array(node.get("translation") or [0.0, 0.0, 0.0], dtype=np.float64),
            np.array(node.get("rotation") or [0.0, 0.0, 0.0, 1.0], dtype=np.float64),
            np.array(node.get("scale") or [1.0, 1.0, 1.0], dtype=np.float64))


def _set_trs(node: dict, t, q, s) -> None:
    node.pop("matrix", None)
    node["translation"] = [float(v) for v in t]
    node["rotation"] = [float(v) for v in q]
    node["scale"] = [float(v) for v in s]


def add_glb_animations(data: bytes, specs: list[dict], centers: dict | None = None,
                       diagonal: float = 1.0, keys: dict | None = None,
                       groups: dict | None = None) -> bytes:
    """Добавляет в GLB клипы анимации и ключевые кадры объектов.

    Поддерживаются spin, formation, explode, move, scale, turn и ключевые кадры
    (``keys``: {имя: [{t, pos, rot, scale}]}). Сборка по шагам и морфинг — это
    отдельные модели, они живут в окне приложения и в GLB не переносятся.
    """
    specs = [dict(sp) for sp in (specs or [])
             if str(sp.get("kind") or "").lower()
             not in ("assembly", "morph", "wait")]
    key_tracks = {name: [dict(k) for k in items if items] for name, items in (keys or {}).items()}
    key_tracks = {name: items for name, items in key_tracks.items() if items}
    if not specs and not key_tracks:
        return data

    doc, binary = _glb_read(data)
    nodes = doc.setdefault("nodes", [])
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    doc["scenes"] = scenes
    roots = list(scenes[0].get("nodes") or [])
    if not roots:
        roots = list(range(len(nodes)))

    # группы объектов: узел-группа, чтобы дверь или ящик ехали целиком
    group_nodes: dict[str, int] = {}
    group_spec = {str(g): [str(m) for m in members]
                  for g, members in (groups or {}).items() if members}
    if group_spec:
        by_first = {str(node.get("name") or ""): i for i, node in enumerate(nodes)}
        parents: dict[int, int] = {}
        for i, node in enumerate(nodes):
            for ch in node.get("children") or []:
                parents[ch] = i
        for gname, members in group_spec.items():
            idxs = [by_first[m] for m in members if m in by_first]
            if not idxs:
                continue
            gi = len(nodes)
            nodes.append({"name": gname, "children": []})
            for i in idxs:
                parent = parents.pop(i, None)
                if parent is not None:
                    kids = nodes[parent].get("children") or []
                    if i in kids:
                        kids.remove(i)
                if i in roots:
                    roots.remove(i)
                nodes[gi]["children"].append(i)
            roots.append(gi)
            scenes[0]["nodes"] = list(roots)
            group_nodes[gname] = gi

    values = [np.asarray(v, dtype=np.float64) for v in (centers or {}).values()
              if v is not None]
    pts = np.array(values) if values else np.zeros((1, 3))
    center = (pts.min(axis=0) + pts.max(axis=0)) / 2.0

    root_index = len(nodes)
    nodes.append({"name": "FormaAnimationRoot", "children": list(roots),
                  "translation": [float(center[0]), float(center[1]), float(center[2])]})
    for idx in roots:
        node = nodes[idx]
        t, q, sc = _node_trs(node)
        _set_trs(node, t - center, q, sc)
    scenes[0]["nodes"] = [root_index]

    by_name = {str(node.get("name") or ""): i for i, node in enumerate(nodes)}
    pivots: dict[str, int] = {}

    def find_parent(idx: int) -> int | None:
        for i, node in enumerate(nodes):
            if idx in (node.get("children") or []):
                return i
        return None

    def pivot(name: str) -> int | None:
        """Узел-подвес в центре объекта: вокруг него крутим и масштабируем деталь."""
        if name in pivots:
            return pivots[name]
        idx = by_name.get(name)
        if idx is None:
            return None
        c = centers.get(name) if centers else None
        if c is None:
            return idx
        local = np.asarray(c, dtype=np.float64) - center
        node = nodes[idx]
        t, q, sc = _node_trs(node)
        _set_trs(node, t - local, q, sc)
        p = len(nodes)
        nodes.append({"name": f"FormaPivot_{name}",
                      "translation": [float(v) for v in local], "children": [idx]})
        parent = find_parent(idx)
        if parent is not None:
            kids = nodes[parent]["children"]
            kids[kids.index(idx)] = p
        elif idx in scenes[0]["nodes"]:
            scenes[0]["nodes"][scenes[0]["nodes"].index(idx)] = p
        pivots[name] = p
        return p

    doc.setdefault("accessors", [])
    doc.setdefault("bufferViews", [])
    if doc.get("buffers"):
        doc["buffers"][0]["byteLength"] = len(binary)
    else:
        doc["buffers"] = [{"byteLength": len(binary)}]

    def add_accessor(arr: np.ndarray, atype: str, with_bounds: bool = False):
        nonlocal binary
        arr = np.asarray(arr, dtype=np.float32)
        while len(binary) % 4:
            binary += b"\x00"
        view = {"buffer": 0, "byteOffset": len(binary), "byteLength": int(arr.nbytes)}
        binary += arr.tobytes()
        doc["bufferViews"].append(view)
        acc = {"bufferView": len(doc["bufferViews"]) - 1,
               "componentType": 5126, "count": int(arr.shape[0]), "type": atype}
        if with_bounds:
            flat = arr.reshape(-1, 1) if arr.ndim == 1 else arr
            acc["min"] = [float(flat[:, i].min()) for i in range(flat.shape[1])]
            acc["max"] = [float(flat[:, i].max()) for i in range(flat.shape[1])]
        doc["accessors"].append(acc)
        return len(doc["accessors"]) - 1

    def clean_keys(pairs):
        out = []
        for t, val in pairs:
            if out and abs(float(t) - out[-1][0]) < 1e-6:
                out[-1] = (float(t), val)
            else:
                out.append((float(t), val))
        return ([p[0] for p in out], [p[1] for p in out])

    def animation(name: str, channels: list[dict]) -> None:
        if not channels:
            return
        times = channels[0]["times"]
        time_acc = add_accessor(np.asarray(times, dtype=np.float32).reshape(-1, 1),
                                "SCALAR", with_bounds=True)
        samplers = []
        clean = []
        for i, ch in enumerate(channels):
            samplers.append({"input": time_acc, "output": ch["acc"],
                             "interpolation": "LINEAR"})
            clean.append({"sampler": i, "target": {"node": ch["node"], "path": ch["path"]}})
        doc.setdefault("animations", []).append(
            {"name": name, "samplers": samplers, "channels": clean})

    names_used: dict[str, int] = {}

    def unique_name(base: str) -> str:
        names_used[base] = names_used.get(base, 0) + 1
        return base if names_used[base] == 1 else f"{base}_{names_used[base]}"

    clip_names = {"spin": "FormaSpin", "formation": "FormaFormation",
                  "explode": "FormaExplode", "move": "FormaMove",
                  "scale": "FormaScale", "turn": "FormaTurn"}

    # --- клипы ---------------------------------------------------------- #
    for spec in specs:
        kind = str(spec.get("kind") or "spin").lower()
        seconds = max(0.2, min(float(spec.get("seconds") or 4.0), 600.0))
        start = max(0.0, float(spec.get("start") or 0.0))
        steps = max(2, int(spec.get("steps") or 48))
        target_name = spec.get("object")
        is_group = bool(target_name and str(target_name) in group_nodes)
        node_idx = root_index
        if target_name:
            node_idx = pivot(str(target_name)) or group_nodes.get(str(target_name)) \
                or root_index
        node = nodes[node_idx]
        base_t, base_q, base_s = _node_trs(node)
        channels = []

        if kind == "formation":
            ts, vals = clean_keys([(0.0, 0.001), (start, 0.001),
                                   (start + seconds * 0.85, 1.0), (start + seconds, 1.0)])
            arr = np.asarray(vals, dtype=np.float64).reshape(-1, 1).repeat(3, axis=1)
            arr = arr * np.asarray(base_s, dtype=np.float64).reshape(1, 3)
            channels.append({"node": node_idx, "path": "scale", "times": ts,
                             "acc": add_accessor(arr, "VEC3")})
        elif kind == "explode":
            amount = float(spec.get("amount") or diagonal * 0.18)
            for idx in roots:
                name = str(nodes[idx].get("name") or "")
                c = centers.get(name) if centers else None
                if c is None:
                    continue
                d = np.asarray(c, dtype=np.float64) - center
                ln = float(np.linalg.norm(d))
                d = d / ln if ln > 1e-9 else np.array([0.0, 1.0, 0.0])
                t_idx = pivots.get(name, idx)
                t_node = nodes[t_idx]
                bt, _bq, _bs = _node_trs(t_node)
                end = bt + d * amount
                ts, vals = clean_keys([(0.0, list(bt)), (start, list(bt)),
                                       (start + seconds, list(end))])
                channels.append({"node": t_idx, "path": "translation", "times": ts,
                                 "acc": add_accessor(np.asarray(vals), "VEC3")})
        elif kind == "move":
            delta = _gltf_vec(spec.get("delta") or [0.0, 0.0, 0.0])
            ts = [start, start + seconds] if not start else [0.0, start, start + seconds]
            vals = [list(base_t)] * (len(ts) - 1) + [list(base_t + delta)]
            channels.append({"node": node_idx, "path": "translation", "times": ts,
                             "acc": add_accessor(np.asarray(vals), "VEC3")})
        elif kind == "scale":
            f0 = float(spec.get("from") or 1.0)
            f1 = float(spec.get("to") or 1.5)
            ts = [start, start + seconds] if not start else [0.0, start, start + seconds]
            vals = [list(base_s * f0)] * (len(ts) - 1) + [list(base_s * f1)]
            channels.append({"node": node_idx, "path": "scale", "times": ts,
                             "acc": add_accessor(np.asarray(vals), "VEC3")})
        else:  # spin / turn / roll
            if kind == "turn":
                angle = np.radians(float(spec.get("angle") or 90.0))
            elif kind == "roll":
                angle = float(spec.get("radians") or 0.0)
            else:
                angle = 2 * np.pi * float(spec.get("axis_sign") or 1.0) \
                    * float(spec.get("turns") or 1.0)
            axis = _gltf_axis(spec.get("axis") or "z")
            pivot_raw = spec.get("pivot")
            if is_group and pivot_raw:
                # группа крутится вокруг петли: кроме поворота нужен сдвиг
                p = _gltf_vec(pivot_raw)
                n = max(8, min(int(steps), 72))
                ts, rots, trs = [], [], []
                if start > 1e-6:
                    ts.append(0.0)
                    rots.append(list(base_q))
                    trs.append(list(base_t))
                for k in range(n):
                    u = k / (n - 1)
                    q = _qmul(_quat(axis, angle * u), base_q)
                    t = base_t + p - _qrot(q, p)
                    ts.append(start + seconds * u)
                    rots.append(list(q))
                    trs.append(list(t))
                channels.append({"node": node_idx, "path": "rotation", "times": ts,
                                 "acc": add_accessor(np.asarray(rots), "VEC4")})
                channels.append({"node": node_idx, "path": "translation", "times": ts,
                                 "acc": add_accessor(np.asarray(trs), "VEC3")})
            else:
                q0 = base_q
                q1 = _qmul(_quat(axis, angle), base_q)
                ts = [start, start + seconds] if not start else [0.0, start, start + seconds]
                vals = [list(q0)] * (len(ts) - 1) + [list(q1)]
                channels.append({"node": node_idx, "path": "rotation", "times": ts,
                                 "acc": add_accessor(np.asarray(vals), "VEC4")})

        if channels:
            animation(unique_name(clip_names.get(kind, "FormaAnimation")), channels)

    # --- ключевые кадры объектов --------------------------------------- #
    for name, items in key_tracks.items():
        idx = pivot(name)
        if idx is None:
            continue
        node = nodes[idx]
        base_t, base_q, base_s = _node_trs(node)
        items = sorted(items, key=lambda k: float(k.get("t") or 0.0))
        need_pos = any("pos" in k for k in items)
        need_rot = any("rot" in k for k in items)
        need_scale = any("scale" in k for k in items)
        times: list[float] = []
        if items and float(items[0].get("t") or 0.0) > 1e-6:
            times.append(0.0)
        for k in items:
            t = max(0.0, float(k.get("t") or 0.0))
            if not times or abs(t - times[-1]) > 1e-6:
                times.append(t)
            else:
                times[-1] = t
        pos_vals, rot_vals, scale_vals = [], [], []
        for k in items:
            pos = _gltf_vec(k["pos"]) if "pos" in k else np.zeros(3)
            pos_vals.append(base_t + pos)
            rot_vals.append(_qmul(_euler_modeling_to_gltf(k["rot"]), base_q)
                            if "rot" in k else base_q)
            scale_vals.append(base_s * float(k["scale"]) if "scale" in k else base_s)
        # если первый ключ позже нуля — до него объект стоит в базовом состоянии
        pad = len(times) - len(items)
        if pad:
            pos_vals.insert(0, base_t)
            rot_vals.insert(0, base_q)
            scale_vals.insert(0, base_s)
        channels = []
        if need_pos:
            channels.append({"node": idx, "path": "translation", "times": times,
                             "acc": add_accessor(np.asarray(pos_vals), "VEC3")})
        if need_rot:
            channels.append({"node": idx, "path": "rotation", "times": times,
                             "acc": add_accessor(np.asarray(rot_vals), "VEC4")})
        if need_scale:
            channels.append({"node": idx, "path": "scale", "times": times,
                             "acc": add_accessor(np.asarray(scale_vals), "VEC3")})
        animation(unique_name(f"FormaKeys_{name}"), channels)

    if doc.get("buffers"):
        doc["buffers"][0]["byteLength"] = len(binary)
    return _glb_write(doc, binary)

def export_stl(objects) -> bytes:
    """Бинарный STL (Z-up, мм) — для 3D-печати."""
    chunks = []
    for obj in objects:
        verts, faces = manifold_mesh(obj.manifold)
        tri = verts[faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(n, axis=1)
        good = ln > 1e-12
        n[good] /= ln[good, None]
        rec = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        rec["n"] = n.astype(np.float32)
        rec["v"] = tri.astype(np.float32)
        chunks.append(rec.tobytes())
    header = b"Forma3D binary STL"
    body = b"".join(chunks)
    count = len(body) // 50
    return header.ljust(80, b" ") + struct.pack("<I", count) + body


def export_3mf(objects) -> bytes:
    """3MF (ZIP + XML) — формат для слайсеров и Windows-программ 3D-печати."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    verts_all, faces_all = [], []
    offset = 0
    names = []
    for obj in objects:
        verts, _normals, faces = _glb_geometry(obj.manifold)
        verts_all.append(verts)
        faces_all.append(faces + offset)
        offset += len(verts)
        names.append(escape(getattr(obj, "name", "деталь")))
    if not verts_all:
        raise GeometryError("Нечего экспортировать: нет видимых объектов.")
    v = np.vstack(verts_all).astype(np.float64)
    f = np.vstack(faces_all).astype(np.int64)
    # 3MF использует Z-up и миллиметры — переводим из внутренних Y-up координат
    v = np.stack([v[:, 0], -v[:, 2], v[:, 1]], axis=1)
    parts = []
    for tri in f:
        parts.append(f'<triangle v1="{tri[0]}" v2="{tri[1]}" v3="{tri[2]}"/>')
    vertex_xml = "".join(
        f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in v)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="ru-RU" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        f'<metadata name="Title">{names[0] if names else "Форма 3D"}</metadata>\n'
        '<resources><object id="1" type="model"><mesh><vertices>'
        + vertex_xml
        + '</vertices><triangles>' + "".join(parts) + '</triangles></mesh></object></resources>\n'
        '<build><item objectid="1"/></build></model>\n')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '</Types>\n')
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def export_ply(objects) -> bytes:
    """Бинарный PLY с нормалями — открывается в Blender, MeshLab, CloudCompare."""
    verts_all, normals_all, faces_all = [], [], []
    offset = 0
    for obj in objects:
        verts, normals, faces = _glb_geometry(obj.manifold)
        verts_all.append(verts)
        normals_all.append(normals)
        faces_all.append(faces + offset)
        offset += len(verts)
    if not verts_all:
        raise GeometryError("Нечего экспортировать: нет видимых объектов.")
    v = np.vstack(verts_all).astype("<f4")
    n = np.vstack(normals_all).astype("<f4")
    f = np.vstack(faces_all).astype("<u4")
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        "comment Forma3D export (Y-up, mm)\n"
        f"element vertex {len(v)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        f"element face {len(f)}\n"
        "property list uchar uint vertex_indices\nend_header\n"
    ).encode("ascii")
    body = np.hstack([v, n]).tobytes()
    tri = np.hstack([np.full((len(f), 1), 3, dtype=np.uint8), f]).tobytes()
    return header + body + tri


def export_obj(objects) -> bytes:
    lines = ["# Forma3D export (mm, Z-up)"]
    offset = 1
    for obj in objects:
        verts, faces = manifold_mesh(obj.manifold)
        lines.append(f"o {obj.name}")
        for v in verts:
            lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
        for f in faces:
            lines.append(f"f {f[0] + offset} {f[1] + offset} {f[2] + offset}")
        offset += len(verts)
    return ("\n".join(lines) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
#  Цвета и PNG
# --------------------------------------------------------------------------- #

CSS_COLORS = {
    "white": "#ffffff", "black": "#111318", "gray": "#8d93a1", "grey": "#8d93a1",
    "silver": "#c8ccd4", "red": "#d94a4a", "orange": "#e8843c", "yellow": "#e8c84a",
    "green": "#4fae6d", "mint": "#68d6b1", "teal": "#2fa9a9", "cyan": "#54c7e8",
    "blue": "#4a7fe0", "navy": "#34457a", "purple": "#8a6be0", "violet": "#a074e8",
    "pink": "#e07a9e", "brown": "#8a5a3c", "wood": "#b98a5a", "gold": "#f0c14b",
    "copper": "#c07a4a", "steel": "#b8c0cc", "ceramic": "#e6e9ef", "rubber": "#2b2d33",
    "белый": "#ffffff", "чёрный": "#111318", "черный": "#111318", "серый": "#8d93a1",
    "красный": "#d94a4a", "оранжевый": "#e8843c", "жёлтый": "#e8c84a",
    "желтый": "#e8c84a", "зелёный": "#4fae6d", "зеленый": "#4fae6d",
    "голубой": "#54c7e8", "синий": "#4a7fe0", "фиолетовый": "#8a6be0",
    "розовый": "#e07a9e", "коричневый": "#8a5a3c", "золотой": "#f0c14b",
    "медный": "#c07a4a", "стальной": "#b8c0cc", "керамика": "#e6e9ef",
}

MATERIAL_PRESETS = {
    "ceramic": {"color": "#dfe4ec", "metal": 0.0, "rough": 0.35, "density": 2.5},
    "керамика": {"color": "#dfe4ec", "metal": 0.0, "rough": 0.35, "density": 2.5},
    "metal": {"color": "#c3c9d4", "metal": 1.0, "rough": 0.28, "density": 7.8},
    "steel": {"color": "#b9c1cd", "metal": 1.0, "rough": 0.3, "density": 7.85},
    "сталь": {"color": "#b9c1cd", "metal": 1.0, "rough": 0.3, "density": 7.85},
    "aluminum": {"color": "#cdd3dc", "metal": 1.0, "rough": 0.35, "density": 2.7},
    "dural": {"color": "#c9d2dd", "metal": 1.0, "rough": 0.32, "density": 2.78},
    "gold": {"color": "#f0c96a", "metal": 1.0, "rough": 0.18, "density": 19.3},
    "copper": {"color": "#c98052", "metal": 1.0, "rough": 0.25, "density": 8.96},
    "plastic": {"color": "#7aa2ff", "metal": 0.0, "rough": 0.45, "density": 1.24},
    "пластик": {"color": "#7aa2ff", "metal": 0.0, "rough": 0.45, "density": 1.24},
    "pla": {"color": "#8fb8ff", "metal": 0.0, "rough": 0.5, "density": 1.24},
    "petg": {"color": "#9fd0ff", "metal": 0.0, "rough": 0.4, "density": 1.27},
    "wood": {"color": "#b98a5a", "metal": 0.0, "rough": 0.72, "density": 0.7},
    "дерево": {"color": "#b98a5a", "metal": 0.0, "rough": 0.72, "density": 0.7},
    "rubber": {"color": "#2b2d33", "metal": 0.0, "rough": 0.9, "density": 1.1},
    "резина": {"color": "#2b2d33", "metal": 0.0, "rough": 0.9, "density": 1.1},
    "glass": {"color": "#cfe8f2", "metal": 0.0, "rough": 0.08, "density": 2.5},
    "стекло": {"color": "#cfe8f2", "metal": 0.0, "rough": 0.08, "density": 2.5},
}


def normalize_color(value: str) -> str:
    s = str(value).strip().lower()
    if s in CSS_COLORS:
        return CSS_COLORS[s]
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
            return "#" + h
    raise GeometryError(f"Неизвестный цвет «{value}».",
                        hint="Используйте #RRGGBB или название: красный, синий, steel, gold...")


def color_to_rgba(color: str) -> list[int]:
    c = normalize_color(color).lstrip("#")
    return [int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255]


def color_to_gltf(color: str) -> list[float]:
    """Цвет для glTF: компоненты строго 0…1 (иначе материалы и текстуры горят белым)."""
    c = normalize_color(color).lstrip("#")
    return [round(int(c[0:2], 16) / 255.0, 4),
            round(int(c[2:4], 16) / 255.0, 4),
            round(int(c[4:6], 16) / 255.0, 4), 1.0]


def color_to_float_rgb(color: str) -> tuple[float, float, float]:
    c = normalize_color(color).lstrip("#")
    return (int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png_encode(arr: np.ndarray) -> bytes:
    """PNG без внешних библиотек: RGB или RGBA, 8 бит, без интерлейса."""
    arr = np.asarray(arr, dtype=np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=2)
    h, w, ch = arr.shape
    if ch not in (3, 4):
        arr = arr[:, :, :3]
        ch = 3
    color_type = 2 if ch == 3 else 6
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw, 6))
    png += _png_chunk(b"IEND", b"")
    return png


def write_png(path, rgb: np.ndarray) -> None:
    """Минималистичный PNG-энкодер (RGB/RGBA, uint8). Без внешних зависимостей."""
    import os
    data = _png_encode(rgb)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def png_bytes(rgb: np.ndarray) -> bytes:
    return _png_encode(rgb)


def read_png(path) -> np.ndarray | None:
    """Читает PNG, который пишет само приложение (8 бит, RGB/RGBA, без интерлейса).

    Нужен, чтобы текстуры не требовали Pillow: свои узоры мы пишем сами,
    а сторонние PNG с другими настройками просто пропускаются.
    """
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    idat = bytearray()
    w = h = 0
    color_type = 2
    bit_depth = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            w, h, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk)
            if bit_depth != 8 or interlace != 0:
                return None
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None or w <= 0 or h <= 0:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except Exception:
        return None
    stride = w * channels
    if len(raw) < h * (stride + 1):
        return None
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    bpp = channels
    p = 0
    for y in range(h):
        ftype = raw[p]
        p += 1
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=p)
        p += stride
        if ftype == 0:
            cur = line.copy()
        elif ftype == 2:
            cur = (line.astype(np.int16) + prev).astype(np.uint8)
        elif ftype == 1:
            cur = line.copy()
            for i in range(bpp, stride):
                cur[i] = (int(cur[i]) + int(cur[i - bpp])) & 0xFF
        elif ftype == 3:
            cur = line.copy()
            for i in range(stride):
                left = int(cur[i - bpp]) if i >= bpp else 0
                cur[i] = (int(cur[i]) + ((left + int(prev[i])) >> 1)) & 0xFF
        elif ftype == 4:
            cur = line.copy()
            for i in range(stride):
                a = int(cur[i - bpp]) if i >= bpp else 0
                b = int(prev[i])
                c = int(prev[i - bpp]) if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (int(cur[i]) + pred) & 0xFF
        else:
            return None
        out[y] = cur
        prev = cur
    img = out.reshape(h, w, channels)
    if channels == 1:
        img = np.repeat(img, 3, axis=2)
    elif channels == 2:
        img = np.repeat(img[:, :, :1], 3, axis=2)
    return img


class SimpleImage:
    """Крошечная замена PIL.Image для GLB: только сохранение в PNG."""

    format = "PNG"

    def __init__(self, array: np.ndarray):
        self.array = np.asarray(array, dtype=np.uint8)

    @property
    def size(self):
        h, w = self.array.shape[:2]
        return (w, h)

    def save(self, fp, format: str | None = None) -> None:  # noqa: A002
        fp.write(_png_encode(self.array))

    def __array__(self, dtype=None):
        return self.array if dtype is None else self.array.astype(dtype)


def resize_rgb(arr: np.ndarray, size: int) -> np.ndarray:
    """Приводит картинку к size×size билинейно, без Pillow."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 2:
        a = np.stack([a, a, a], axis=2)
    a = a[:, :, :3]
    h, w, _ = a.shape
    if h == size and w == size:
        return np.clip(a, 0, 255).astype(np.uint8)
    ys = (np.arange(size) + 0.5) * (h / size) - 0.5
    xs = (np.arange(size) + 0.5) * (w / size) - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, h - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, w - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)
    wy = np.clip(ys - y0, 0, 1)[:, None, None]
    wx = np.clip(xs - x0, 0, 1)[None, :, None]
    top = a[y0][:, x0] * (1 - wx) + a[y0][:, x1] * wx
    bot = a[y1][:, x0] * (1 - wx) + a[y1][:, x1] * wx
    out = top * (1 - wy) + bot * wy
    return np.clip(out, 0, 255).astype(np.uint8)


def fibonacci_sphere(n: int) -> np.ndarray:
    n = max(1, int(n))
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    theta = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)
