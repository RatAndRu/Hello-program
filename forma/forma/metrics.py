"""Измерения модели и словесный отчёт для человека и нейросети."""

from __future__ import annotations

import math
from typing import Any

import manifold3d as mf
import numpy as np

from .geometry import fibonacci_sphere, manifold_mesh
from .values import fmt

AXIS_NAMES = {"x": "X (ширина)", "y": "Y (глубина)", "z": "Z (высота)"}


def _face_data(m: mf.Manifold):
    v, f = manifold_mesh(m)
    if len(f) == 0:
        return v, f, np.zeros(0), np.zeros(0)
    tri = v[f]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2.0
    n = np.zeros_like(cross)
    good = area > 1e-12
    n[good] = cross[good] / (2 * area[good, None])
    return v, f, area, n


def flat_bottom_percent(m: mf.Manifold) -> float:
    v, f, area, n = _face_data(m)
    if len(area) == 0:
        return 0.0
    zmin = v[:, 2].min()
    zmax = v[:, 2].max()
    tol = max(0.4, (zmax - zmin) * 0.005)
    tri_z = v[f][:, :, 2].mean(axis=1)
    mask = (n[:, 2] < -0.9) & (tri_z <= zmin + tol)
    total = area.sum()
    return float(area[mask].sum() / total * 100) if total > 0 else 0.0


def overhang_percent(m: mf.Manifold) -> float:
    v, f, area, n = _face_data(m)
    if len(area) == 0:
        return 0.0
    zmin = v[:, 2].min()
    zmax = v[:, 2].max()
    if zmax - zmin < 5:
        return 0.0
    tri_z = v[f][:, :, 2].mean(axis=1)
    mask = (n[:, 2] < -0.35) & (tri_z > zmin + max(1.0, (zmax - zmin) * 0.02))
    total = area.sum()
    return float(area[mask].sum() / total * 100) if total > 0 else 0.0


def wall_thickness(m: mf.Manifold, samples: int = 128) -> dict | None:
    """Оценка толщины материала лучами из центра наружу.

    Учитываются только участки «внутри материала»: вход в тело (нормаль вдоль
    луча) и выход из тела (нормаль против луча). Для полых тел (кружка, ваза,
    бутылка) эти участки — стенки, и у них ярко выраженный пик. Для сплошных
    тел пика нет: хорды сопоставимы с размером объекта.
    """
    bb = m.bounding_box()
    diag = math.sqrt((bb[3] - bb[0]) ** 2 + (bb[4] - bb[1]) ** 2 + (bb[5] - bb[2]) ** 2)
    if diag < 1e-6:
        return None
    center = np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2])
    gaps: list[tuple[float, list[float]]] = []
    for d in fibonacci_sphere(samples):
        origin = center + d * diag
        end = center - d * diag
        try:
            hits = m.ray_cast([float(x) for x in origin], [float(x) for x in end])
        except Exception:
            continue
        if len(hits) < 2:
            continue
        hits = sorted(hits, key=lambda h: h.distance)
        for a, b in zip(hits, hits[1:]):
            na = np.asarray(a.normal, dtype=np.float64)
            nb = np.asarray(b.normal, dtype=np.float64)
            enter = float(np.dot(na, d)) > 0.15
            exit_ = float(np.dot(nb, d)) < -0.15
            if enter and exit_:
                # середина «стенки» — где именно она тонкая
                mid = (a.distance + b.distance) / 2.0
                point = center - d * mid
                gaps.append((abs(b.distance - a.distance) * diag * 2,
                             [float(point[0]), float(point[1]), float(point[2])]))
    if len(gaps) < 10:
        return None
    positions = {i: g[1] for i, g in enumerate(gaps)}
    arr = np.asarray([g[0] for g in gaps], dtype=np.float64)
    arr = arr[arr > 0.08]
    if len(arr) < 10:
        return None
    # «стенка» — это заведомо тонкий участок по сравнению с габаритом объекта
    thin = arr[arr < diag * 0.22]
    if len(thin) < max(6, int(0.10 * len(arr))):
        return None
    bins = int(np.clip(len(thin) // 5, 10, 36))
    hist, edges = np.histogram(thin, bins=bins)
    smooth = np.convolve(hist, np.array([0.25, 0.5, 0.25]), mode="same")
    peak = int(np.argmax(smooth))
    lo_edge, hi_edge = float(edges[peak]), float(edges[peak + 1])
    pad = (hi_edge - lo_edge) * 0.6
    keep = (thin >= lo_edge - pad) & (thin <= hi_edge + pad)
    cluster = thin[keep]
    if len(cluster) < 5:
        return None
    ratio = len(cluster) / len(thin)
    med = float(np.median(cluster))
    mad = float(np.median(np.abs(cluster - med))) / max(med, 1e-9)
    if ratio < 0.16 or mad > 0.30:
        return None
    min_value = float(np.min(cluster))
    min_point = None
    for idx in range(len(arr)):
        if abs(arr[idx] - min_value) < 1e-9:
            min_point = positions.get(idx)
            break
    return {
        "min_point": min_point,
        "min": min_value,
        "p10": float(np.percentile(cluster, 10)),
        "median": med,
        "p90": float(np.percentile(cluster, 90)),
        "max": float(np.max(cluster)),
        "samples": int(len(arr)),
        "consistency": float(ratio),
    }


def symmetry_error(m: mf.Manifold, axis: str, plane: float | None = None,
                   max_tris: int = 90_000) -> float | None:
    if m.num_tri() > max_tris:
        return None
    idx = {"x": 0, "y": 1, "z": 2}.get(axis)
    if idx is None:
        return None
    bb = m.bounding_box()
    c = float(plane) if plane is not None else 0.0
    if not (bb[idx] - 1e-6 <= c <= bb[idx + 3] + 1e-6):
        c = (bb[idx] + bb[idx + 3]) / 2
    off = [0.0, 0.0, 0.0]
    off[idx] = 2 * c
    mirrored = m.mirror([1.0 if i == idx else 0.0 for i in range(3)]).translate(off)
    try:
        diff = (m - mirrored).volume() + (mirrored - m).volume()
    except Exception:
        return None
    vol = m.volume()
    if vol <= 0:
        return None
    return float(max(0.0, diff) / vol * 100)


def collect_solid(solid, wall: bool = True, symmetry: bool = False,
                  symmetry_axes: tuple[str, ...] = ("x", "y", "z")) -> dict:
    m = solid.manifold
    info = solid.stats()
    bb = info["bbox"]
    data = {
        "name": solid.name,
        "color": solid.color,
        "metal": solid.metal,
        "rough": solid.rough,
        "density": solid.density,
        "visible": solid.visible,
        "kind": solid.kind,
        "op": solid.op,
        "line": solid.line,
        "bbox": bb,
        "size": info["size"],
        "center": [(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2],
        "volume_cm3": info["volume"] / 1000.0,
        "area_cm2": info["area"] / 100.0,
        "mass_g": info["volume"] / 1000.0 * solid.density,
        "tris": info["tris"],
        "verts": info["verts"],
        "genus": info["genus"],
        "status": info["status"],
        "flat_bottom_pct": flat_bottom_percent(m),
        "overhang_pct": overhang_percent(m),
    }
    try:
        data["parts"] = len(m.decompose())
    except Exception:
        data["parts"] = 1
    data["wall"] = wall_thickness(m) if wall else None
    data["symmetry"] = {}
    if symmetry:
        for axis in symmetry_axes:
            data["symmetry"][axis] = symmetry_error(m, axis)
    return data


class MetricsCache:
    def __init__(self, scene=None):
        self.scene = scene
        self._cache: dict[str, dict] = {}

    def get(self, solid, wall: bool = True) -> dict:
        key = f"{solid.name}:{solid.manifold.num_tri()}:{int(wall)}"
        if key not in self._cache:
            self._cache[key] = collect_solid(solid, wall=wall)
        return self._cache[key]

    def symmetry(self, solid, axis: str, plane: float | None = None) -> float | None:
        key = f"sym:{solid.name}:{axis}:{plane}"
        if key not in self._cache:
            self._cache[key] = {"value": symmetry_error(solid.manifold, axis, plane)}
        return self._cache[key]["value"]


def union_visible(scene) -> tuple[mf.Manifold | None, list]:
    solids = scene.visible_solids()
    if not solids:
        return None, []
    if len(solids) == 1:
        return solids[0].manifold, solids
    total = sum(s.stats()["tris"] for s in solids)
    if total > 150_000:
        return None, solids
    try:
        merged = mf.Manifold.batch_boolean([s.manifold for s in solids], mf.OpType.Add)
        if merged.is_empty():
            return None, solids
        return merged, solids
    except Exception:
        return None, solids


def analyze(scene, previous: dict | None = None, check_results: list[dict] | None = None) -> dict:
    from .checks import evaluate_checks

    cache = MetricsCache(scene)
    visible = scene.visible_solids()
    if not visible:
        raise ValueError("В сцене нет видимых объектов.")

    objects = [cache.get(s) for s in visible]
    main = max(objects, key=lambda o: o["volume_cm3"])
    union, solids = union_visible(scene)
    warnings: list[str] = []
    advice: list[str] = []

    if union is not None:
        gbb = union.bounding_box()
        gvol = union.volume() / 1000.0
        gtris = union.num_tri()
        garea = union.surface_area() / 100.0
        ggenus = union.genus()
        try:
            gparts = len(union.decompose())
        except Exception:
            gparts = len(visible)
        gflat = flat_bottom_percent(union)
        gover = overhang_percent(union)
        gwall = wall_thickness(union, 120)
        gsym = {axis: symmetry_error(union, axis) for axis in ("x", "y", "z")}
        density = max(s.density for s in visible)
        gmass = gvol * density
    else:
        bbs = [o["bbox"] for o in objects]
        gbb = [min(b[0] for b in bbs), min(b[1] for b in bbs), min(b[2] for b in bbs),
               max(b[3] for b in bbs), max(b[4] for b in bbs), max(b[5] for b in bbs)]
        gvol = sum(o["volume_cm3"] for o in objects)
        gtris = sum(o["tris"] for o in objects)
        garea = sum(o["area_cm2"] for o in objects)
        ggenus = sum(o["genus"] for o in objects)
        gparts = sum(o["parts"] for o in objects)
        gflat = main["flat_bottom_pct"]
        gover = main["overhang_pct"]
        gwall = main["wall"]
        gsym = main.get("symmetry") or {}
        gmass = sum(o["mass_g"] for o in objects)
        density = max(s.density for s in visible)

    gsize = [gbb[3] - gbb[0], gbb[4] - gbb[1], gbb[5] - gbb[2]]
    metrics = {
        "bbox": gbb,
        "size": gsize,
        "volume_cm3": gvol,
        "mass_g": gmass,
        "area_cm2": garea,
        "tris": gtris,
        "genus": ggenus,
        "parts": gparts,
        "flat_bottom_pct": gflat,
        "overhang_pct": gover,
        "wall": gwall,
        "symmetry": gsym,
        "density": density,
        "density_note": "плотность взята по материалу объектов",
        "visible_count": len(visible),
        "total_count": len(scene.objects),
        "objects": objects,
        "main": main["name"],
    }

    # ---- предупреждения ---------------------------------------------------
    if gparts > 1:
        warnings.append(f"Модель состоит из {gparts} отдельных частей — для печати их лучше объединить.")
    if gwall and gwall["p10"] < 1.2:
        warnings.append(f"Тонкие стенки: минимум {fmt(gwall['min'])} мм — печать будет хрупкой.")
    elif gwall and gwall["p10"] < 2.4:
        warnings.append(f"Стенки {fmt(gwall['p10'])} мм — тонковато для прочной печати (лучше ≥ 2.4 мм).")
    if gover > 25:
        warnings.append(f"Большие нависания ({fmt(gover)}% площади) — понадобятся поддержки.")
    if gflat < 3 and gsize[2] > 20:
        warnings.append("Нет выраженного плоского дна — модель может быть неустойчивой.")
    if gtris > 400_000:
        warnings.append(f"Очень много треугольников ({gtris:,}) — приложение и печать будут медленнее."
                        .replace(",", " "))
    if gbb[2] < -0.01:
        warnings.append(f"Модель опущена ниже пола (z={fmt(gbb[2])} мм).")
    elif abs(gbb[2]) > 0.01:
        warnings.append(f"Модель не стоит на полу: низ на z={fmt(gbb[2])} мм.")
    if min(gsize) < 0.8:
        warnings.append("Один из габаритов меньше 0.8 мм — деталь может не напечататься.")
    if max(gsize) > 5000:
        warnings.append("Модель больше 5 метров — проверьте единицы измерения (в сценарии миллиметры).")
    if ggenus > 0:
        warnings.append(f"В модели есть сквозные отверстия: род {ggenus}.")
    if gwall is None and max(gsize) > 20:
        advice.append("Если нужна полая деталь, используйте shell thickness=… open=top.")

    checks = check_results if check_results is not None else evaluate_checks(scene, cache)
    passed = sum(1 for c in checks if c["ok"])

    compare = compare_with_previous(metrics, previous)
    if compare:
        parts = []
        for key, label, unit, digits in (("volume_cm3", "объём", "см³", 1),
                                         ("mass_g", "масса", "г", 0),
                                         ("tris", "треугольников", "", 0)):
            delta = compare.get(key)
            if delta is not None and abs(delta) > (0.05 if digits else 0.5):
                sign = "+" if delta > 0 else "−"
                parts.append(f"{label} {sign}{fmt(abs(delta), digits)} {unit}".strip())
        for i, label in enumerate(("ширина", "глубина", "высота")):
            delta = compare["size"][i]
            if abs(delta) > 0.05:
                sign = "+" if delta > 0 else "−"
                parts.append(f"{label} {sign}{fmt(abs(delta))} мм")
        if parts:
            compare["summary"] = ", ".join(parts)

    return {
        "metrics": metrics,
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        "warnings": warnings,
        "advice": advice,
        "compare": compare,
        "text": build_text(scene, metrics, checks, warnings, advice, compare),
    }


def compare_with_previous(current: dict, previous: dict | None) -> dict | None:
    if not previous:
        return None
    prev = previous.get("metrics") if "metrics" in previous else previous
    if not prev:
        return None
    out: dict[str, Any] = {}
    for key in ("volume_cm3", "mass_g", "tris", "area_cm2"):
        if key in prev and key in current:
            out[key] = float(current[key] - prev[key])
    if "size" in prev and "size" in current:
        out["size"] = [float(a - b) for a, b in zip(current["size"], prev["size"])]
    return out


def build_text(scene, m: dict, checks: list[dict], warnings: list[str],
               advice: list[str], compare: dict | None) -> str:
    s = m["size"]
    lines = []
    lines.append("ОТЧЁТ О МОДЕЛИ")
    lines.append(f"Объектов: {m['total_count']} (видимых {m['visible_count']}), "
                 f"треугольников: {m['tris']:,}".replace(",", " "))
    lines.append("")
    lines.append("ГЕОМЕТРИЯ")
    lines.append(f"• габариты: {fmt(s[0])} × {fmt(s[1])} × {fmt(s[2])} мм (Ш×Г×В)")
    lines.append(f"• объём материала: {fmt(m['volume_cm3'])} см³")
    lines.append(f"• масса: {fmt(m['mass_g'], 0)} г (плотность {fmt(m['density'], 2)} г/см³)")
    bb = m.get("bbox") or []
    if len(bb) == 6:
        lines.append(f"• центр: ({fmt((bb[0] + bb[3]) / 2)}, {fmt((bb[1] + bb[4]) / 2)}, "
                     f"{fmt((bb[2] + bb[5]) / 2)}) мм; границы X {fmt(bb[0])}…{fmt(bb[3])}, "
                     f"Y {fmt(bb[1])}…{fmt(bb[4])}, Z {fmt(bb[2])}…{fmt(bb[5])}")
    lines.append(f"• площадь поверхности: {fmt(m['area_cm2'])} см²")
    lines.append(f"• частей: {m['parts']}" + (", единое тело" if m["parts"] == 1 else ""))
    lines.append(f"• сквозных отверстий (род): {m['genus']}")
    if m.get("wall"):
        w = m["wall"]
        lines.append(f"• толщина материала: медиана {fmt(w['median'])} мм "
                     f"(мин {fmt(w['min'])}, макс {fmt(w['max'])})")
    else:
        lines.append("• толщина материала: объект сплошной (полости не обнаружено)")
    lines.append(f"• плоское дно: {fmt(m['flat_bottom_pct'])}% площади")
    lines.append(f"• нависания: {fmt(m['overhang_pct'])}% площади")
    if m.get("symmetry"):
        sym = []
        for axis in ("x", "y", "z"):
            v = m["symmetry"].get(axis)
            if v is not None:
                sym.append(f"{axis.upper()} {fmt(max(0.0, 100 - v), 1)}%")
        if sym:
            lines.append("• симметрия: " + ", ".join(sym))
    if len(m["objects"]) > 1:
        lines.append("")
        lines.append("ОБЪЕКТЫ")
        for o in m["objects"]:
            c = o.get("center") or [0, 0, 0]
            lines.append(f"• {o['name']}: {fmt(o['size'][0])}×{fmt(o['size'][1])}×{fmt(o['size'][2])} мм, "
                         f"{fmt(o['volume_cm3'])} см³, {o['tris']:,} трис".replace(",", " ")
                         + f", центр ({fmt(c[0])}, {fmt(c[1])}, {fmt(c[2])})")
    lines.append("")
    if checks:
        lines.append(f"ПРОВЕРКИ: {sum(1 for c in checks if c['ok'])} из {len(checks)}")
        for c in checks:
            mark = "✓" if c["ok"] else "✗"
            lines.append(f"  {mark} {c['text']}")
    else:
        lines.append("ПРОВЕРКИ: не заданы (добавьте строки check … в сценарий)")
    if warnings:
        lines.append("")
        lines.append("ЗАМЕЧАНИЯ")
        for w in warnings:
            lines.append(f"• {w}")
    if advice:
        lines.append("")
        lines.append("СОВЕТЫ")
        for a in advice:
            lines.append(f"• {a}")
    if compare and compare.get("summary"):
        lines.append("")
        lines.append("ИЗМЕНЕНИЯ С ПРЕДЫДУЩЕЙ ВЕРСИЕЙ")
        lines.append("• " + compare["summary"])
    lines.append("")
    lines.append("Все размеры в миллиметрах, ось Z — вверх.")
    return "\n".join(lines)

# --------------------------------------------------------------------------- #
#  Качество сетки: острые рёбра и «тонкие» треугольники
# --------------------------------------------------------------------------- #

def edge_angles(m: mf.Manifold) -> np.ndarray:
    """Углы между соседними гранями, ° (0 — плоско, 90 — прямой угол)."""
    from .geometry import manifold_mesh
    v, f = manifold_mesh(m)
    if len(f) == 0:
        return np.zeros(0, dtype=np.float64)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(n, axis=1)
    good = length > 1e-12
    n[good] /= length[good, None]
    n[~good] = 0.0
    nv = len(v)
    keys = np.concatenate([
        np.sort(np.stack([f[:, 0], f[:, 1]], axis=1), axis=1),
        np.sort(np.stack([f[:, 1], f[:, 2]], axis=1), axis=1),
        np.sort(np.stack([f[:, 2], f[:, 0]], axis=1), axis=1),
    ])
    face_ids = np.tile(np.arange(len(f)), 3)
    codes = keys[:, 0].astype(np.int64) * nv + keys[:, 1].astype(np.int64)
    uniq, inverse = np.unique(codes, return_inverse=True)
    counts = np.bincount(inverse, minlength=len(uniq))
    # нормали граней, приходящихся на ребро (для рёбер с двумя гранями)
    order = np.argsort(inverse, kind="stable")
    sorted_inv = inverse[order]
    starts = np.flatnonzero(np.r_[True, sorted_inv[1:] != sorted_inv[:-1]])
    idx2 = np.flatnonzero(counts == 2)
    out = []
    for e in idx2:
        ids = face_ids[order[starts[e]:starts[e] + 2]]
        if len(ids) != 2:
            continue
        c = float(np.clip(np.dot(n[ids[0]], n[ids[1]]), -1.0, 1.0))
        out.append(math.degrees(math.acos(c)))
    return np.asarray(out, dtype=np.float64)


def tri_quality(m: mf.Manifold) -> dict:
    """Доля треугольников с очень острым углом (тонкие, «игольчатые»)."""
    from .geometry import manifold_mesh
    v, f = manifold_mesh(m)
    if len(f) == 0:
        return {"min_angle": 0.0, "bad_pct": 0.0, "bad": 0, "total": 0}
    tri = v[f]
    a = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
    b = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
    c = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
    eps = 1e-9
    ang = []
    for x, y, z in ((a, b, c), (b, c, a), (c, a, b)):
        cos = (y * y + z * z - x * x) / (2 * np.maximum(y * z, eps))
        ang.append(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
    stacked = np.stack(ang, axis=0)
    biggest = stacked.max(axis=0)
    smallest = np.minimum(stacked.min(axis=0), np.clip(180.0 - biggest, 0.0, 180.0))
    bad = int((smallest < 8.0).sum())
    return {"min_angle": float(smallest.min()) if len(smallest) else 0.0,
            "bad_pct": bad / len(smallest) * 100.0, "bad": bad, "total": int(len(smallest))}
