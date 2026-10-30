"""Измерения модели и словесный отчёт для человека и нейросети."""

from __future__ import annotations

import math
from typing import Any

import manifold3d as mf
import numpy as np

from .geometry import fibonacci_sphere, manifold_mesh, solid_parts
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


def wall_thickness(m: mf.Manifold, samples: int = 96) -> dict | None:
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
    # Сплошную деталь толщиной не меряем: у монолита «стенка» — это весь габарит.
    bbox_volume = max((bb[3] - bb[0]) * (bb[4] - bb[1]) * (bb[5] - bb[2]), 1e-9)
    if m.volume() / bbox_volume > 0.62:
        return None
    # Толщина — статистика по лучам: подробная сетка ей не нужна.
    # Считаем на упрощённой копии (до 0,2 мм), это в разы быстрее.
    approx = 0.0
    if m.num_tri() > 3000:
        approx = float(min(0.2, max(0.05, diag / 2000.0)))
        try:
            simple = m.simplify(approx)
            if not simple.is_empty() and simple.num_tri() > 500:
                m = simple
        except Exception:
            approx = 0.0
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
        # Плавно меняющаяся толщина (кружка с тонким дном, литая деталь):
        # резкого пика нет — берём нижнюю половину тонких хорд.
        fallback = thin[thin <= np.median(thin)]
        if len(fallback) < 8:
            return None
        cluster = fallback
        ratio = len(cluster) / len(thin)
        med = float(np.median(cluster))
        mad = float(np.median(np.abs(cluster - med))) / max(med, 1e-9)
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
        "approx": approx,
    }


def find_holes(m: mf.Manifold, levels: int = 9, min_diameter: float = 0.6,
               max_count: int = 12) -> list[dict]:
    """Ищет вертикальные отверстия и полости по сечениям z.

    Камеры и полости (крупные контуры) отделяются от отверстий по диаметру:
    отверстие не может занимать половину ширины детали. Это приближение —
    горизонтальные отверстия ищутся командой section plane=x/y.
    """
    from .cuts import section_polygons

    bb = m.bounding_box()
    height = bb[5] - bb[2]
    if height <= 1e-6:
        return []
    levels = max(4, min(int(levels), 15))
    groups: list[dict] = []
    used = 0
    for k in range(levels):
        z = bb[2] + height * (k + 0.5) / levels
        try:
            cs = m.slice(z)
        except Exception:
            continue
        if cs.is_empty():
            continue
        polygons = section_polygons(cs)
        if not polygons:
            continue
        used += 1
        for contour in polygons:
            area = contour["area"]
            if area >= -1e-9:
                continue
            pts = contour["points"]
            cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
            diameter = 2.0 * math.sqrt(abs(area) / math.pi)
            if diameter < min_diameter:
                continue
            target = None
            for group in groups:
                last_d = group["_d"][-1]
                tol = max(1.5, 0.15 * max(diameter, last_d))
                if (math.hypot(group["_x"][-1] - cx, group["_y"][-1] - cy) <= tol
                        and abs(last_d - diameter) <= 0.3 * max(diameter, last_d)):
                    target = group
                    break
            if target is None:
                target = {"_x": [], "_y": [], "_d": [], "levels": [], "z": []}
                groups.append(target)
            target["_x"].append(cx)
            target["_y"].append(cy)
            target["_d"].append(diameter)
            target["levels"].append(k)
            target["z"].append(z)
    holes = []
    for group in groups:
        if not group["levels"]:
            continue
        kmin, kmax = min(group["levels"]), max(group["levels"])
        depth = (kmax - kmin + 1) * height / levels
        through = kmin <= 0.15 * levels and kmax >= levels - 1 - 0.15 * levels
        holes.append({
            "x": round(float(sum(group["_x"]) / len(group["_x"])), 3),
            "y": round(float(sum(group["_y"]) / len(group["_y"])), 3),
            "diameter": round(float(sum(group["_d"]) / len(group["_d"])), 3),
            "depth": round(float(depth), 3),
            "through": bool(through),
            "levels": len(group["levels"]),
        })
    holes.sort(key=lambda h: (-h["diameter"], h["x"]))
    if used and len(holes) > max_count:
        holes = holes[:max_count]
    return holes


def detail_passport(solid, base: dict | None = None, with_holes: bool = True) -> dict:
    """Паспорт детали: габариты, центр, масса, стенка, отверстия."""
    data = dict(base or collect_solid(solid, wall=True))
    info = solid.stats()
    size = info["size"]
    holes: list[dict] = []
    if with_holes:
        try:
            holes = find_holes(solid.manifold)
        except Exception:
            holes = []
    limit = 0.5 * max(1e-6, min(size[0], size[1]) if min(size[0], size[1]) > 1e-6 else size[2])
    data["holes"] = [h for h in holes if h["diameter"] <= limit]
    data["cavity"] = [h for h in holes if h["diameter"] > limit]
    data["passport"] = True
    return data


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
        "emissive": getattr(solid, "emissive", "") or "",
        "emissive_strength": getattr(solid, "emissive_strength", 1.0),
        "transmission": getattr(solid, "transmission", 0.0),
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
    from .topology import manifold_topology
    data["topology"] = manifold_topology(m)
    try:
        data["parts"] = solid_parts(m)
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
        # None и 0.0 означают одно и то же (плоскость по центру/через начало),
        # поэтому ключ кэша у них общий — иначе считаем одно и то же дважды.
        key = f"sym:{solid.name}:{solid.manifold.num_tri()}:{axis}:{float(plane or 0.0)}"
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


def _requested_axes(scene, check_results: list[dict] | None) -> set[str]:
    """Какие оси симметрии реально спрашивают проверки (остальные не считаем)."""
    axes: set[str] = set()
    for r in check_results or []:
        axis = r.get("axis")
        if r.get("rule") == "symmetric" and axis:
            axes.add(str(axis))
    for spec in getattr(scene, "checks", []) or []:
        rule = (spec.get("rule") or "").lower()
        if rule not in ("symmetric", "симметрия", "симметричность"):
            continue
        args = spec.get("args") or []
        if args:
            raw = str(args[0]).strip().lower()
            axis = {"ширина": "x", "глубина": "y", "высота": "z",
                    "width": "x", "depth": "y", "height": "z"}.get(raw, raw)
            if axis in ("x", "y", "z"):
                axes.add(axis)
    return axes


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
            gparts = solid_parts(union)
        except Exception:
            gparts = len(visible)
        gflat = flat_bottom_percent(union)
        gover = overhang_percent(union)
        # для одного объекта сплошной «union» — это он же: не считаем дважды
        gwall = objects[0]["wall"] if len(visible) == 1 else wall_thickness(union, 96)
        # симметрия — самая дорогая метрика (булевы операции). Считаем её по
        # тем осям, которые просят проверки, и по всем трём — только если
        # сетка небольшая и это дёшево.
        axes = _requested_axes(scene, check_results)
        if gtris <= 15_000:
            axes.update(("x", "y", "z"))
        if len(visible) == 1:
            # один объект: считаем через кэш сцены, чтобы проверка ниже
            # не считала то же самое второй раз
            gsym = {axis: cache.symmetry(visible[0], axis) for axis in sorted(axes)}
        else:
            gsym = {axis: symmetry_error(union, axis) for axis in sorted(axes)}
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
        axes = _requested_axes(scene, check_results)
        if axes and not gsym:
            biggest = max(visible, key=lambda s: s.manifold.volume())
            gsym = {axis: cache.symmetry(biggest, axis) for axis in sorted(axes)}
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
    try:
        main_solid = next((s for s in visible if s.name == main["name"]), visible[0])
        metrics["passport"] = detail_passport(main_solid, base=main)
    except Exception:
        metrics["passport"] = None

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
    bad_topology = [o for o in objects if not o["topology"]["ok"]]
    if bad_topology:
        names = ", ".join(o["name"] for o in bad_topology[:4])
        more = f" и ещё {len(bad_topology) - 4}" if len(bad_topology) > 4 else ""
        warnings.append(
            f"Топологическая сварка нашла структурные ошибки: {names}{more}. "
            "Экспорт будет остановлен до исправления исходной сетки."
        )
    # ---- кубическая сетка: бюджет объёма -------------------------------
    grid = getattr(scene, "grid", None)
    if grid:
        try:
            from .ops_grid import overflow_mm3
            outside = []
            for solid in visible:
                over = overflow_mm3(solid.manifold, grid)
                if over > max(float(solid.manifold.volume()) * 5e-4, 1.0):
                    outside.append((solid.name, over))
            if outside:
                worst = max(outside, key=lambda pair: pair[1])
                detail = ", ".join(f"«{n}» {fmt(v / 1000)} см³" for n, v in outside[:3])
                warnings.append(
                    f"Вне кубической сетки: {detail}. Впишите деталь в бюджет "
                    f"(`вписать {worst[0]}`) или расширьте сетку.")
            else:
                advice.append(
                    f"Кубический бюджет соблюдён: {len(grid['cells'])} кубов по "
                    f"{fmt(grid['cell'])} мм, {fmt(grid['volume_mm3'] / 1000)} см³.")
        except Exception:
            pass

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
    passport = m.get("passport")
    if passport:
        ps = passport["size"]
        pc = passport["center"]
        lines.append("")
        lines.append(f"ПАСПОРТ ДЕТАЛИ (главный объект «{passport['name']}»)")
        lines.append(f"• габариты {fmt(ps[0])} × {fmt(ps[1])} × {fmt(ps[2])} мм; "
                     f"центр ({fmt(pc[0])}, {fmt(pc[1])}, {fmt(pc[2])})")
        pw = passport.get("wall")
        if pw:
            lines.append(f"• материал: {fmt(passport['volume_cm3'])} см³, "
                         f"{fmt(passport['mass_g'], 0)} г; минимальная стенка "
                         f"{fmt(pw['min'])} мм (медиана {fmt(pw['median'])})")
        else:
            lines.append(f"• материал: {fmt(passport['volume_cm3'])} см³, "
                         f"{fmt(passport['mass_g'], 0)} г; деталь сплошная")
        cavity = passport.get("cavity") or []
        if cavity:
            lines.append("• полость: есть, ø" + ", ".join(fmt(c["diameter"]) for c in cavity[:3])
                         + " мм (внутренний объём)")
        holes = passport.get("holes") or []
        if holes:
            items = []
            for hole in holes[:6]:
                kind = "сквозное" if hole["through"] else f"глухое {fmt(hole['depth'])} мм"
                items.append(f"ø{fmt(hole['diameter'])} в ({fmt(hole['x'])}, {fmt(hole['y'])}) {kind}")
            lines.append("• отверстия: " + "; ".join(items))
        else:
            lines.append("• отверстия: вертикальных нет")
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
    elif m["tris"] > 15_000:
        lines.append("• симметрия: не измерялась (самая дорогая метрика) — "
                     "добавьте check имя symmetric x")
    sections = getattr(scene, "sections", []) or []
    if sections:
        lines.append("")
        lines.append("СЕЧЕНИЯ")
        for sec in sections[-6:]:
            lines.append(f"• {sec.get('object')} {sec.get('plane')}={fmt(sec.get('at'))} мм: "
                         f"площадь {fmt((sec.get('area') or 0) / 100)} см², контуров "
                         f"{len(sec.get('contours') or [])} "
                         f"({sec.get('outer') or 0} внешних, {sec.get('holes') or 0} внутренних); "
                         f"файлы {sec.get('layer')}.dxf/.svg")
    probes = getattr(scene, "probes", []) or []
    if probes:
        lines.append("")
        lines.append("ПРОБЫ МАТЕРИАЛА")
        for probe in probes[-6:]:
            pt = probe.get("point") or [0, 0, 0]
            where = f"({fmt(pt[0])}, {fmt(pt[1])}, {fmt(pt[2])})"
            if probe.get("outside_bbox"):
                lines.append(f"• {where} — вне габаритов, материала нет")
            elif probe.get("inside"):
                dist = probe.get("distance")
                extra = "" if dist is None else f", до стенки {fmt(dist)} мм"
                lines.append(f"• {where} — материал есть{extra}")
            else:
                dist = probe.get("distance")
                extra = "" if dist is None else f", до стенки {fmt(dist)} мм"
                lines.append(f"• {where} — пусто{extra}")
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
    # 3° — уже настоящая «игла»; веерные треугольники торцов (≈8°) нормальны
    bad = int((smallest < 3.0).sum())
    return {"min_angle": float(smallest.min()) if len(smallest) else 0.0,
            "bad_pct": bad / len(smallest) * 100.0, "bad": bad, "total": int(len(smallest))}
