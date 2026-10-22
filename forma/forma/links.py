"""Мастер зазоров: что с чем соединено и что висит в воздухе.

Считается по точному расстоянию между телами (Manifold.min_gap), а не по
габаритам, поэтому «касается» и «висит на 2 мм» различаются честно.
"""

from __future__ import annotations

from .geometry import solid_parts

TOUCH = 0.05      # ближе этого — детали касаются
NEAR = 12.0       # «почти рядом»: попадает в отчёт как подозрительное


def _box(solid) -> list[float]:
    return [float(v) for v in solid.bbox]


def _gap(a, b, search: float) -> float:
    try:
        return float(a.manifold.min_gap(b.manifold, search))
    except Exception:
        return search


def _near(a: list[float], b: list[float], tol: float) -> bool:
    return not (b[0] > a[3] + tol or a[0] > b[3] + tol
                or b[1] > a[4] + tol or a[1] > b[4] + tol
                or b[2] > a[5] + tol or a[2] > b[5] + tol)


def analyse(solids, tol: float = TOUCH, near: float = NEAR) -> dict:
    """Возвращает связи: группы, висящие детали и ближайшие зазоры."""
    items = [s for s in solids if getattr(s, "visible", True)]
    names = [s.name for s in items]
    boxes = [_box(s) for s in items]
    n = len(items)
    if n == 0:
        return {"ok": True, "objects": 0, "groups": [], "loose": [], "pairs": []}

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    gaps: list[tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if not _near(boxes[i], boxes[j], near):
                continue
            gap = _gap(items[i], items[j], near)
            gaps.append((gap, i, j))
            if gap <= tol:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=len, reverse=True)
    main = ordered[0] if ordered else []

    loose = []
    for group in ordered[1:]:
        for idx in group:
            best = min((g for g in gaps if idx in (g[1], g[2])), default=None)
            if best is None:
                # Соседей рядом не было — меряем точное расстояние до всех.
                best = None
                for j in range(n):
                    if j == idx:
                        continue
                    d = _gap(items[idx], items[j], 2000.0)
                    if best is None or d < best[0]:
                        best = (d, idx, j)
            if best is None:
                loose.append({"name": items[idx].name, "nearest": None, "gap": None,
                              "parts": solid_parts(items[idx].manifold)})
                continue
            gap, i, j = best
            other = items[j].name if i == idx else items[i].name
            loose.append({"name": items[idx].name, "nearest": other,
                          "gap": round(gap, 3),
                          "parts": solid_parts(items[idx].manifold)})

    pairs = [{"a": items[i].name, "b": items[j].name, "gap": round(gap, 3)}
             for gap, i, j in sorted(gaps)[:40]]

    return {
        "ok": True,
        "objects": n,
        "tolerance": tol,
        "groups": len(ordered),
        "main": len(main),
        "loose": loose,
        "pairs": pairs,
        "touches": sum(1 for g, _, _ in gaps if g <= tol),
    }


def scene_links(scene) -> dict:
    solids = [s for s in scene.objects.values() if s.visible]
    data = analyse(solids)
    data["mates"] = list(getattr(scene, "mates", []) or [])
    return data
