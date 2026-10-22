"""Сечения, пробы материала, отклонение от эталона и экспорт 2D-контуров.

Здесь живут «глаза» нейросети: разрез детали контуром (DXF/SVG), проверка
«есть ли материал в точке» и числовое сравнение с эталоном (Хаусдорф).
"""

from __future__ import annotations

import math
from pathlib import Path

import manifold3d as mf
import numpy as np

from .geometry import manifold_mesh

PLANES = ("x", "y", "z")


# --------------------------------------------------------------------------- #
#  Плоскости и сечения
# --------------------------------------------------------------------------- #

def plane_matrix(plane: str) -> np.ndarray:
    """Матрица 3×4, переводящая плоскость сечения в Z=const.

    Для plane=z — тождественная; для x/y деталь поворачивается так, чтобы
    нужная ось стала вертикалью. Обратная матрица возвращает разрез на место.
    """
    plane = (plane or "z").lower()
    if plane == "z":
        return np.eye(3, 4)
    if plane == "x":
        # поворот −90° вокруг Y: x → z, z → −x
        return np.array([[0.0, 0.0, -1.0, 0.0],
                         [0.0, 1.0, 0.0, 0.0],
                         [1.0, 0.0, 0.0, 0.0]])
    if plane == "y":
        # поворот +90° вокруг X: y → z, z → −y
        return np.array([[1.0, 0.0, 0.0, 0.0],
                         [0.0, 0.0, -1.0, 0.0],
                         [0.0, 1.0, 0.0, 0.0]])
    raise ValueError(f"Неизвестная плоскость сечения: {plane}")


def inverse_matrix(m: np.ndarray) -> np.ndarray:
    r = m[:, :3]
    t = m[:, 3]
    inv = np.eye(3, 4)
    inv[:, :3] = r.T
    inv[:, 3] = -r.T @ t
    return inv


def axis_index(plane: str) -> int:
    return {"x": 0, "y": 1, "z": 2}.get((plane or "z").lower(), 2)


def plane_bounds(m: mf.Manifold, plane: str) -> tuple[float, float]:
    bb = m.bounding_box()
    i = axis_index(plane)
    return float(bb[i]), float(bb[i + 3])


def slice_section(m: mf.Manifold, plane: str = "z", at: float = 0.0) -> mf.CrossSection:
    """Сечение детали плоскостью. Возвращает 2D-контуры в координатах плоскости."""
    mat = plane_matrix(plane)
    local = m.transform(mat) if not np.allclose(mat, np.eye(3, 4)) else m
    lo, hi = plane_bounds(m, plane)
    height = float(at)
    if height < lo or height > hi:
        raise ValueError(f"Плоскость {plane}={at:g} вне детали ({lo:.2f}…{hi:.2f}).")
    cs = local.slice(height)
    if cs.is_empty() or cs.area() <= 1e-9:
        raise ValueError("Сечение пустое: плоскость проходит по краю или между частями.")
    return cs


def section_polygons(cs: mf.CrossSection) -> list[dict]:
    """Контуры с площадью: внешние и отверстия (даёт площадь со знаком)."""
    out: list[dict] = []
    for poly in cs.to_polygons():
        arr = np.asarray(poly, dtype=np.float64)
        if len(arr) < 3:
            continue
        x, y = arr[:, 0], arr[:, 1]
        area = 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        out.append({"points": arr, "area": area, "closed": True})
    out.sort(key=lambda p: -abs(p["area"]))
    return out


def polygons_payload(contours: list[dict], max_points: int = 240) -> list[list[list[float]]]:
    """Контуры для интерфейса: без тысяч точек, но с сохранением формы."""
    result = []
    for c in contours:
        pts = c["points"]
        step = max(1, int(math.ceil(len(pts) / max_points)))
        sample = pts[::step]
        if len(sample) < 3:
            sample = pts
        result.append([[round(float(p[0]), 3), round(float(p[1]), 3)] for p in sample])
    return result


def make_section_solid(cs: mf.CrossSection, plane: str, at: float,
                       thickness: float = 0.4) -> mf.Manifold:
    """Плоский «срез» как тонкое тело: его видно в окне и можно проверить."""
    thin = cs.extrude(max(0.1, float(thickness)))
    # extrude растёт от Z=0; центрируем по плоскости и возвращаем на место
    thin = thin.translate([0.0, 0.0, float(at) - float(thickness) / 2.0])
    inv = inverse_matrix(plane_matrix(plane))
    return thin.transform(inv)


def export_dxf(sections: list[dict], path: Path) -> Path:
    """Минимальный DXF R12: контуры линиями, миллиметры, слой на сечение."""
    path = Path(path)
    lines: list[str] = ["0", "SECTION", "2", "HEADER",
                        "9", "$ACADVER", "1", "AC1009",
                        "9", "$INSUNITS", "70", "4",
                        "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for idx, sec in enumerate(sections, start=1):
        layer = str(sec.get("layer") or f"SECTION_{idx}")
        for contour in sec.get("contours") or []:
            pts = np.asarray(contour, dtype=np.float64)
            if len(pts) < 3:
                continue
            for a, b in zip(pts, np.roll(pts, -1, axis=0)):
                lines += ["0", "LINE", "8", layer,
                          "10", f"{a[0]:.4f}", "20", f"{a[1]:.4f}", "30", "0.0",
                          "11", f"{b[0]:.4f}", "21", f"{b[1]:.4f}", "31", "0.0"]
    lines += ["0", "ENDSEC", "0", "EOF"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_svg(sections: list[dict], path: Path, size: float = 1000.0) -> Path:
    """SVG в миллиметрах: контуры как path с even-odd (отверстия остаются дырками)."""
    path = Path(path)
    all_pts = [np.asarray(c, dtype=np.float64) for sec in sections
               for c in (sec.get("contours") or []) if len(c) >= 3]
    if not all_pts:
        raise ValueError("Нет контуров для SVG.")
    lo = np.min(np.vstack([p.min(axis=0) for p in all_pts]), axis=0)
    hi = np.max(np.vstack([p.max(axis=0) for p in all_pts]), axis=0)
    w, h = max(1e-6, hi[0] - lo[0]), max(1e-6, hi[1] - lo[1])
    margin = max(w, h) * 0.02
    vb = (float(lo[0] - margin), float(lo[1] - margin),
          float(w + 2 * margin), float(h + 2 * margin))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{vb[2]:.2f}mm" '
             f'height="{vb[3]:.2f}mm" viewBox="{vb[0]:.4f} {vb[1]:.4f} '
             f'{vb[2]:.4f} {vb[3]:.4f}">',
             '<g fill="#cfe3ff" fill-opacity="0.35" fill-rule="evenodd" '
             'stroke="#1f4b7a" stroke-width="0.25">']
    for sec in sections:
        d = []
        for contour in sec.get("contours") or []:
            pts = np.asarray(contour, dtype=np.float64)
            if len(pts) < 3:
                continue
            d.append("M " + " L ".join(f"{p[0]:.4f} {p[1]:.4f}" for p in pts) + " Z")
        if d:
            parts.append(f'<path d="{" ".join(d)}" />')
    parts.append("</g></svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
#  Точка внутри материала
# --------------------------------------------------------------------------- #

def _point_in_polygons(px: float, py: float, contours: list[np.ndarray]) -> bool:
    inside = False
    for poly in contours:
        n = len(poly)
        x = poly[:, 0]
        y = poly[:, 1]
        j = n - 1
        for i in range(n):
            yi, yj = y[i], y[j]
            if (yi > py) != (yj > py):
                xc = x[i] + (py - yi) * (x[j] - x[i]) / (yj - yi + 1e-300)
                if px < xc:
                    inside = not inside
            j = i
    return inside


def _distance_to_contours(px: float, py: float, contours: list[np.ndarray]) -> float:
    best = float("inf")
    for poly in contours:
        a = poly
        b = np.roll(poly, -1, axis=0)
        ab = b - a
        ap = np.array([px, py]) - a
        denom = (ab * ab).sum(axis=1)
        t = np.where(denom > 1e-12, (ap * ab).sum(axis=1) / np.maximum(denom, 1e-12), 0.0)
        t = np.clip(t, 0.0, 1.0)
        closest = a + ab * t[:, None]
        d = np.linalg.norm(np.array([px, py]) - closest, axis=1)
        best = min(best, float(d.min()))
    return best


def point_info(m: mf.Manifold, point, tol: float = 0.05) -> dict:
    """Есть ли материал в точке и далеко ли до стенки (в плоскости сечения).

    Точное и дешёвое решение: сечение на высоте точки + правило чётности.
    """
    p = np.asarray(point, dtype=np.float64)
    bb = m.bounding_box()
    inside_box = all(bb[i] - 1e-9 <= p[i] <= bb[i + 3] + 1e-9 for i in range(3))
    if not inside_box:
        return {"inside": False, "distance": None, "on_surface": False,
                "outside_bbox": True}
    try:
        cs = m.slice(float(p[2]))
    except Exception:
        return {"inside": False, "distance": None, "on_surface": False,
                "outside_bbox": False}
    if cs.is_empty():
        return {"inside": False, "distance": None, "on_surface": False,
                "outside_bbox": False}
    contours = [np.asarray(poly, dtype=np.float64) for poly in cs.to_polygons()
                if len(poly) >= 3]
    if not contours:
        return {"inside": False, "distance": None, "on_surface": False,
                "outside_bbox": False}
    inside = _point_in_polygons(float(p[0]), float(p[1]), contours)
    dist = _distance_to_contours(float(p[0]), float(p[1]), contours)
    return {"inside": bool(inside), "distance": float(dist),
            "on_surface": dist <= max(tol, 1e-6), "outside_bbox": False}


# --------------------------------------------------------------------------- #
#  Хаусдорф: насколько одна поверхность отличается от другой
# --------------------------------------------------------------------------- #

def _sample_surface(v: np.ndarray, f: np.ndarray, limit: int = 1200) -> np.ndarray:
    """Точки на поверхности: вершины + центры + случайные точки внутри граней."""
    if len(f) == 0:
        return np.zeros((0, 3))
    tris = v[f]
    centroids = tris.mean(axis=1)
    count = len(tris)
    take = max(1, min(count, limit // 3))
    idx = np.linspace(0, count - 1, take).astype(int)
    rng = np.random.default_rng(7)
    u = rng.random(take)
    w = rng.random(take)
    flip = u + w > 1
    u[flip] = 1 - u[flip]
    w[flip] = 1 - w[flip]
    pts = tris[idx, 0] + (tris[idx, 1] - tris[idx, 0]) * u[:, None] \
        + (tris[idx, 2] - tris[idx, 0]) * w[:, None]
    verts = v[np.linspace(0, len(v) - 1, min(len(v), limit // 3)).astype(int)]
    return np.vstack([verts, centroids[idx], pts])


def _point_triangle_distance(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Расстояние от точек (K,3) до треугольников (K,3,3) — по одной паре."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    ab, ac, ap = b - a, c - a, points - a
    d1 = (ab * ap).sum(axis=1)
    d2 = (ac * ap).sum(axis=1)
    bp = points - b
    d3 = (ab * bp).sum(axis=1)
    d4 = (ac * bp).sum(axis=1)
    cp = points - c
    d5 = (ab * cp).sum(axis=1)
    d6 = (ac * cp).sum(axis=1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    v = vb / denom
    w = vc / denom
    u = 1.0 - v - w
    inside = (u >= -1e-9) & (v >= -1e-9) & (w >= -1e-9)
    proj = a + ab * v[:, None] + ac * w[:, None]
    dist = np.linalg.norm(points - proj, axis=1)
    # проекция вне треугольника — ближайшее ребро
    edge_ab = _seg_dist(points, a, b)
    edge_bc = _seg_dist(points, b, c)
    edge_ca = _seg_dist(points, c, a)
    dist = np.where(inside, dist, np.minimum(np.minimum(edge_ab, edge_bc), edge_ca))
    # вершины — на случай вырожденных треугольников
    vert = np.minimum(np.minimum(np.linalg.norm(points - a, axis=1),
                                 np.linalg.norm(points - b, axis=1)),
                      np.linalg.norm(points - c, axis=1))
    return np.minimum(dist, vert)


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = ((p - a) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-12)
    t = np.clip(t, 0.0, 1.0)
    return np.linalg.norm(p - (a + ab * t[:, None]), axis=1)


def _brute_distance(points: np.ndarray, v: np.ndarray, f: np.ndarray) -> np.ndarray:
    tris = v[f]
    out = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), 64):
        block = points[start:start + 64]
        best = np.full(len(block), float("inf"))
        for j in range(0, len(tris), 512):
            chunk = tris[j:j + 512]
            rep = block.shape[0]
            a = np.broadcast_to(chunk[None, :, 0, :], (rep, len(chunk), 3))
            b = np.broadcast_to(chunk[None, :, 1, :], (rep, len(chunk), 3))
            c = np.broadcast_to(chunk[None, :, 2, :], (rep, len(chunk), 3))
            p = np.broadcast_to(block[:, None, :], (rep, len(chunk), 3))
            d = _point_triangle_distance(p.reshape(-1, 3), np.stack([a, b, c], axis=2)
                                         .reshape(-1, 3, 3))
            best = np.minimum(best, d.reshape(rep, len(chunk)).min(axis=1))
        out[start:start + len(block)] = best
    return out


def _distance_to_mesh(points: np.ndarray, v: np.ndarray, f: np.ndarray,
                      cell: float | None = None) -> np.ndarray:
    """Расстояние от точек до поверхности: перебор для мелких, сетка для крупных."""
    if len(f) == 0 or len(points) == 0:
        return np.full(len(points), float("inf"))
    if len(f) <= 3000:
        return _brute_distance(points, v, f)
    tris = v[f]
    diag = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0)))
    cell = float(cell or max(diag / 24.0, 1e-3))
    centroids = tris.mean(axis=1)
    keys = np.floor(centroids / cell).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i, key in enumerate(map(tuple, keys)):
        buckets.setdefault(key, []).append(i)
    out = np.empty(len(points), dtype=np.float64)
    for i, point in enumerate(points):
        key = tuple(np.floor(point / cell).astype(np.int64))
        best = float("inf")
        for ring in range(0, 6):
            candidates: list[int] = []
            kx, ky, kz = key
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    for dz in range(-ring, ring + 1):
                        if max(abs(dx), abs(dy), abs(dz)) != ring:
                            continue
                        candidates.extend(buckets.get((kx + dx, ky + dy, kz + dz), ()))
            if candidates:
                arr = tris[np.asarray(candidates)]
                d = _point_triangle_distance(np.repeat(point[None, :], len(arr), axis=0), arr)
                best = min(best, float(d.min()))
            if best <= ring * cell:
                break
        out[i] = best
    # страховка: точки, до которых не дотянулись кольца, считаем полным перебором
    bad = ~np.isfinite(out) | (out > 5 * cell)
    if np.any(bad):
        out[bad] = _brute_distance(points[bad], v, f)
    return out


def hausdorff(a: mf.Manifold, b: mf.Manifold, samples: int = 1200) -> dict:
    """Оценка расстояния Хаусдорфа между поверхностями (мм)."""
    va, fa = manifold_mesh(a)
    vb, fb = manifold_mesh(b)
    if len(fa) == 0 or len(fb) == 0:
        raise ValueError("Пустая сетка для сравнения.")
    pa = _sample_surface(va, fa, samples)
    pb = _sample_surface(vb, fb, samples)
    ca = float(np.linalg.norm(va.max(axis=0) - va.min(axis=0))) / 48.0
    cb = float(np.linalg.norm(vb.max(axis=0) - vb.min(axis=0))) / 48.0
    da = _distance_to_mesh(pa, vb, fb, max(cb, 1e-3))
    db = _distance_to_mesh(pb, va, fa, max(ca, 1e-3))
    dist = np.concatenate([da, db])
    dist = dist[np.isfinite(dist)]
    if len(dist) == 0:
        raise ValueError("Не удалось измерить отклонение.")
    return {
        "max": float(dist.max()),
        "mean": float(dist.mean()),
        "p95": float(np.percentile(dist, 95)),
        "samples": int(len(dist)),
        "back": float(da.max()) if len(da) else None,
        "forward": float(db.max()) if len(db) else None,
    }

