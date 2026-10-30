"""Единая диагностика треугольной топологии твёрдых тел.

Вершины свариваются только в диагностической копии: швы NORMAL/UV в GLB не
являются дырками. Автоматического «улучшения» сетки здесь нет, кроме узкого
фильтра граней, которые уже вырождены по площади или после экспортной сварки.
Правила quad/SubD (полюса, петли, валентность) к треугольному Manifold не
применяются.
"""

from __future__ import annotations

import numpy as np

# Эти значения означают структурную ошибку тела. Плоские иглы, длинные
# треугольники и неравномерная плотность сюда не входят и не блокируют экспорт.
STRUCTURAL_KEYS = (
    "nonfinite_values",
    "degenerate_index",
    "degenerate_area",
    "duplicate_faces",
    "boundary_edges",
    "non_manifold_edges",
    "inconsistent_winding",
)


def _arrays(vertices, faces) -> tuple[np.ndarray, np.ndarray]:
    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if verts.ndim != 2 or verts.shape[1] < 3:
        raise ValueError("Вершины сетки должны иметь форму N×3.")
    verts = verts[:, :3]
    if len(tris) and (tris.min() < 0 or tris.max() >= len(verts)):
        raise ValueError("Грань ссылается на несуществующую вершину.")
    return verts, tris


def weld_tolerance(vertices, tolerance: float | None = None) -> float:
    """Допуск диагностической сварки в единицах модели (мм в Forma)."""
    if tolerance is not None:
        return max(float(tolerance), 1e-12)
    verts = np.asarray(vertices, dtype=np.float64)
    if not len(verts):
        return 1e-4
    finite = verts[np.isfinite(verts).all(axis=1)]
    if not len(finite):
        return 1e-4
    diagonal = float(np.linalg.norm(finite.max(axis=0) - finite.min(axis=0)))
    return max(1e-4, diagonal * 1e-7)


def weld_arrays(vertices, faces, tolerance: float | None = None):
    """Возвращает сваренную копию и число слитых совпадений.

    Координаты исходной модели не изменяются. Представитель группы — первая
    вершина, как и при обычной сварке в импортёрах; близкие вершины сближать
    обратно в исходной сетке не требуется.
    """
    verts, tris = _arrays(vertices, faces)
    eps = weld_tolerance(verts, tolerance)
    if not len(verts):
        return verts, tris, 0, eps
    # NaN/Inf сохраняются в отчёте отдельно; nan_to_num нужен только для того,
    # чтобы диагностика остальной сетки не падала на преобразовании в int64.
    safe = np.nan_to_num(verts, nan=0.0, posinf=0.0, neginf=0.0)
    scaled = safe / eps
    key_array = np.rint(scaled).astype(np.int64)
    cells: dict[tuple[int, int, int], list[int]] = {}
    for index, key in enumerate(key_array.tolist()):
        cells.setdefault(tuple(key), []).append(index)

    # Одной ячейки недостаточно: две точки на расстоянии < eps могут лежать по
    # разные стороны её границы. Проверяем 13 прямых соседей (обратные 13 дают
    # те же неупорядоченные пары) и объединяем только реально близкие вершины.
    parent = list(range(len(verts)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if (dx, dy, dz) > (0, 0, 0)
    ]
    for key, own in cells.items():
        if len(own) > 1:
            head = own[0]
            for other in own[1:]:
                union(head, other)
        cx, cy, cz = key
        for dx, dy, dz in offsets:
            other = cells.get((cx + dx, cy + dy, cz + dz))
            if not other:
                continue
            for i in own:
                ax, ay, az = safe[i]
                for j in other:
                    bx, by, bz = safe[j]
                    if abs(ax - bx) <= eps and abs(ay - by) <= eps and abs(az - bz) <= eps:
                        union(i, j)

    inverse = np.empty(len(verts), dtype=np.int64)
    roots: dict[int, int] = {}
    first: list[int] = []
    for index in range(len(verts)):
        root = find(index)
        if root not in roots:
            roots[root] = len(first)
            first.append(index)
        inverse[index] = roots[root]
    return verts[first], inverse[tris], int(len(verts) - len(first)), eps


def export_face_mask(vertices, faces, tolerance: float | None = None) -> np.ndarray:
    """Какие исходные грани остаются невырожденными в экспортной точности.

    Удаляются лишь нулевые по площади грани и треугольники, у которых два угла
    совпадают после диагностической сварки. Плоские иглы с ненулевой площадью
    сохраняются.
    """
    verts, tris = _arrays(vertices, faces)
    if not len(tris):
        return np.zeros(0, dtype=bool)
    tri = verts[tris]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(cross, axis=1)
    _welded, wf, _merged, _eps = weld_arrays(verts, tris, tolerance)
    distinct = (wf[:, 0] != wf[:, 1]) & (wf[:, 1] != wf[:, 2]) & (wf[:, 2] != wf[:, 0])
    return np.isfinite(area2) & (area2 > 1e-12) & distinct


def compact_arrays(vertices, faces) -> tuple[np.ndarray, np.ndarray]:
    """Убирает неиспользуемые вершины, сохраняя координаты использованных."""
    verts, tris = _arrays(vertices, faces)
    if not len(tris):
        return verts[:0], tris
    used = np.unique(tris.reshape(-1))
    remap = np.full(len(verts), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    return verts[used], remap[tris]


def clean_export_arrays(vertices, faces, tolerance: float | None = None):
    """Базовая очистка в фактической точности glTF (float32).

    Здесь НЕ используется диагностический допуск сварки: удалить близкую, но
    ещё ненулевую грань без одновременной сварки её вершин было бы разрушительно.
    Допускательная сварка с guard-проверками выполняется на уровне Manifold в
    ``geometry._clean_manifold_arrays``.
    """
    del tolerance  # точность записи не настраивается диагностическим порогом
    verts, tris = _arrays(vertices, faces)
    verts = np.asarray(verts, dtype=np.float32).astype(np.float64)
    if not len(tris):
        return verts[:0], tris
    tri = verts[tris]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(cross, axis=1)
    mask = np.isfinite(area2) & (area2 > 1e-12)
    return compact_arrays(verts, tris[mask])


def analyze_topology(vertices, faces, tolerance: float | None = None,
                     min_angle: float = 3.0, include_quality: bool = True) -> dict:
    """Считает структурные ошибки и контекстное качество треугольников.

    ``ok`` означает только структурную пригодность твёрдого тела. Иглы на
    плоскости и неравномерная плотность остаются метриками, а не запретом.
    """
    source, source_faces = _arrays(vertices, faces)
    nonfinite = int(np.size(source) - np.isfinite(source).sum())
    verts, wf, merged, eps = weld_arrays(source, source_faces, tolerance)
    degenerate_index = int((
        (wf[:, 0] == wf[:, 1]) | (wf[:, 1] == wf[:, 2]) | (wf[:, 2] == wf[:, 0])
    ).sum()) if len(wf) else 0
    if len(wf):
        distinct = (wf[:, 0] != wf[:, 1]) & (wf[:, 1] != wf[:, 2]) & (wf[:, 2] != wf[:, 0])
        faces = wf[distinct]
    else:
        faces = wf

    # Основные массивы геометрии после диагностической сварки.
    if len(faces):
        tri = verts[faces]
        cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area2 = np.linalg.norm(cross, axis=1)
        good_area = np.isfinite(area2) & (area2 > 1e-12)
        degenerate_area = int((~good_area).sum())
        lengths = np.stack([
            np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
            np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
            np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1),
        ], axis=1)
        volume = float(np.einsum(
            "ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])
        ).sum() / 6.0)
    else:
        tri = np.zeros((0, 3, 3), dtype=np.float64)
        cross = np.zeros((0, 3), dtype=np.float64)
        area2 = np.zeros(0)
        good_area = np.zeros(0, dtype=bool)
        lengths = np.zeros((0, 3))
        degenerate_area = 0
        volume = 0.0

    # Неориентированные рёбра и направление обхода. Вырожденные по индексам
    # грани уже исключены, поэтому нулевые рёбра не портят счётчики границы.
    directed = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2) if len(faces) else np.zeros((0, 2), dtype=np.int64)
    face_ids = np.repeat(np.arange(len(faces), dtype=np.int64), 3)
    undirected = np.sort(directed, axis=1)
    if len(undirected):
        _edges, edge_inverse, edge_counts = np.unique(
            undirected, axis=0, return_inverse=True, return_counts=True
        )
        edge_inverse = np.asarray(edge_inverse, dtype=np.int64).reshape(-1)
        boundary = int((edge_counts == 1).sum())
        non_manifold = int((edge_counts > 2).sum())
        signs = np.where(directed[:, 0] < directed[:, 1], 1, -1)
        orientation_sum = np.bincount(edge_inverse, weights=signs, minlength=len(edge_counts))
        inconsistent = int(((edge_counts == 2) & (orientation_sum != 0)).sum())
    else:
        _edges = np.zeros((0, 2), dtype=np.int64)
        edge_inverse = np.zeros(0, dtype=np.int64)
        edge_counts = np.zeros(0, dtype=np.int64)
        boundary = non_manifold = inconsistent = 0

    if len(faces):
        canonical = np.sort(faces, axis=1)
        _unique_faces, face_counts = np.unique(canonical, axis=0, return_counts=True)
        duplicate_faces = int((face_counts - 1).clip(min=0).sum())
        loose = int(len(verts) - len(np.unique(faces.reshape(-1))))
    else:
        duplicate_faces = 0
        loose = int(len(verts))

    # Контекстное качество: плоская игла и игла на плавном изгибе — разные
    # ситуации. Соседи проверяются через две длинные стороны, как в спецификации.
    slivers = stretched = bend_slivers = 0
    sliver_area = stretched_area = bend_area = 0.0
    min_seen = 0.0
    if include_quality and len(faces):
        normals = np.zeros_like(cross)
        normals[good_area] = cross[good_area] / area2[good_area, None]
        angles = np.full((len(faces), 3), 180.0)
        for corner in range(3):
            u = tri[:, (corner + 1) % 3] - tri[:, corner]
            v = tri[:, (corner + 2) % 3] - tri[:, corner]
            denominator = np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1)
            valid = good_area & (denominator > 0)
            cosine = np.ones(len(faces))
            cosine[valid] = np.einsum("ij,ij->i", u[valid], v[valid]) / denominator[valid]
            angles[:, corner] = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
        smallest = angles.min(axis=1)
        if good_area.any():
            min_seen = float(smallest[good_area].min())
        sliver_mask = good_area & (smallest < float(min_angle))
        areas = area2 * 0.5
        total_area = float(areas.sum())
        slivers = int(sliver_mask.sum())
        sliver_area = float(areas[sliver_mask].sum())
        shortest = lengths.min(axis=1)
        longest = lengths.max(axis=1)
        stretched_mask = good_area & (shortest > 0) & (longest / np.maximum(shortest, 1e-300) > 10.0)
        stretched = int(stretched_mask.sum())
        stretched_area = float(areas[stretched_mask].sum())

        # Для каждого ребра с двумя гранями сохраняем оба incident face id.
        if len(faces) and sliver_mask.any():
            order = np.argsort(edge_inverse, kind="stable")
            sorted_inverse = edge_inverse[order]
            starts = np.flatnonzero(np.r_[True, sorted_inverse[1:] != sorted_inverse[:-1]])
            incident = np.full((len(edge_counts), 2), -1, dtype=np.int64)
            for edge_id in np.flatnonzero(edge_counts == 2):
                begin = int(starts[edge_id])
                incident[edge_id] = face_ids[order[begin:begin + 2]]
            edge_ids = edge_inverse.reshape(-1, 3)
            own = face_ids.reshape(-1, 3)
            first = incident[edge_ids, 0]
            second = incident[edge_ids, 1]
            neighbor = np.where(first == own, second, first)
            neighbor_valid = (neighbor >= 0) & (neighbor != own)
            safe_neighbor = np.maximum(neighbor, 0)
            neighbor_normals = normals[safe_neighbor]
            dots = np.einsum("fij,fj->fi", neighbor_normals, normals)
            neighbor_angles = np.degrees(np.arccos(np.clip(dots, -1.0, 1.0)))
            # Ранг 1 и 2 — две самые длинные стороны треугольника.
            length_order = np.argsort(lengths, axis=1)
            ranks = np.empty_like(length_order)
            np.put_along_axis(
                ranks,
                length_order,
                np.broadcast_to(np.arange(3, dtype=np.int64), length_order.shape),
                axis=1,
            )
            relevant = neighbor_valid & (ranks >= 1)
            worst = np.max(np.where(relevant, neighbor_angles, 0.0), axis=1)
            bend_mask = sliver_mask & (worst > 2.0) & (worst <= 30.0)
            bend_slivers = int(bend_mask.sum())
            bend_area = float(areas[bend_mask].sum())
    else:
        areas = area2 * 0.5
        total_area = float(areas.sum())

    positive_lengths = lengths[np.isfinite(lengths) & (lengths > 0)]
    min_edge = float(positive_lengths.min()) if len(positive_lengths) else 0.0
    max_edge = float(positive_lengths.max()) if len(positive_lengths) else 0.0
    report = {
        "ok": False,
        "weld_tolerance": float(eps),
        "source_vertices": int(len(source)),
        "source_triangles": int(len(source_faces)),
        "vertices": int(len(verts)),
        "triangles": int(len(faces)),
        "merged_vertices": int(merged),
        "nonfinite_values": nonfinite,
        "degenerate_index": degenerate_index,
        "degenerate_area": degenerate_area,
        "duplicate_faces": duplicate_faces,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "inconsistent_winding": inconsistent,
        "loose_vertices": loose,
        "volume": volume,
        "area": total_area,
        "slivers": slivers,
        "sliver_area_pct": 100.0 * sliver_area / total_area if total_area else 0.0,
        "bend_slivers": bend_slivers,
        "bend_sliver_area_pct": 100.0 * bend_area / total_area if total_area else 0.0,
        "stretched": stretched,
        "stretched_area_pct": 100.0 * stretched_area / total_area if total_area else 0.0,
        "min_angle": min_seen,
        "min_edge": min_edge,
        "max_edge": max_edge,
        "edge_length_spread": max_edge / min_edge if min_edge else 0.0,
    }
    report["ok"] = all(report[key] == 0 for key in STRUCTURAL_KEYS)
    return report


def manifold_topology(manifold, tolerance: float | None = None) -> dict:
    """Топология экспортной копии Manifold с числом удалённых вырождений."""
    from .geometry import _clean_manifold_arrays, manifold_mesh

    verts, faces = manifold_mesh(manifold)
    clean_verts, clean_faces = _clean_manifold_arrays(manifold)
    report = analyze_topology(clean_verts, clean_faces, tolerance)
    report["removed_degenerate_faces"] = int(len(faces) - len(clean_faces))
    report["reduced_vertices"] = int(len(verts) - len(clean_verts))
    return report


def structural_summary(report: dict) -> str:
    """Короткое перечисление ошибок для export gate и check topology."""
    labels = {
        "nonfinite_values": "нечисловые координаты",
        "degenerate_index": "схлопнувшиеся грани",
        "degenerate_area": "грани нулевой площади",
        "duplicate_faces": "дубли граней",
        "boundary_edges": "граничные рёбра",
        "non_manifold_edges": "non-manifold рёбра",
        "inconsistent_winding": "несогласованный обход",
    }
    bad = [f"{labels[key]}: {report[key]}" for key in STRUCTURAL_KEYS if report.get(key)]
    return ", ".join(bad) if bad else "структурных ошибок нет"
