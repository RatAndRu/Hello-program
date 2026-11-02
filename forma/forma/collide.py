"""Точные пересечения между отдельными деталями — на manifold3d.

Здесь один раз живёт логика «какие пары тел реально пересекаются и на сколько
кубических миллиметров». Её используют:

* команда `interference` (отчёт по требованию);
* правило `collision` в `check` (утверждение в сценарии);
* автоматическое предупреждение в `metrics.analyze` — чтобы пересечение
  замечалось без того, чтобы о нём попросили.

Почему не AABB: коробки пересекаются у половины нормальных сборок (деталь в
пазу, ручка над столом), а тела — нет. Поэтому AABB служит только быстрым
отбором, а вердикт даёт точный объём пересечения `Intersection`.

Порог: объём в мм³. `tolerance=0.01` — шум сетки; для «пересечение заметно»
используйте относительный порог `share` (доля меньшего тела).
"""
from __future__ import annotations

import fnmatch
from itertools import combinations

import numpy as np

__all__ = ["root", "overlap_pairs", "pair_volume", "scan_pairs"]


def root(name: str) -> str:
    """Корень имени сборки: `нож.лезвие` → `нож`.

    Детали одной сборки касаются друг друга по построению (паз, посадка),
    поэтому по умолчанию такие пары не считаются дефектом.
    """
    return str(name).split(".")[0]


def _allowed(spec: str | None, left: str, right: str) -> bool:
    """Разрешённые пары: `allow="втулка:вал,нож.*:винт"`."""
    if not spec:
        return False
    for raw in str(spec).replace(";", ",").split(","):
        pair = raw.strip()
        if not pair:
            continue
        parts = pair.split(":") if ":" in pair else pair.split("|")
        if len(parts) != 2:
            continue
        a, b = (v.strip() for v in parts)
        if ((fnmatch.fnmatchcase(left, a) and fnmatch.fnmatchcase(right, b)) or
                (fnmatch.fnmatchcase(left, b) and fnmatch.fnmatchcase(right, a))):
            return True
    return False


def _aabb_overlap(a, b) -> bool:
    la, ra = a.bounding_box(), b.bounding_box()
    overlap = np.minimum(np.asarray(la[3:]), np.asarray(ra[3:])) - \
        np.maximum(np.asarray(la[:3]), np.asarray(ra[:3]))
    return bool(np.all(overlap > 1e-7))


def pair_volume(left, right) -> float:
    """Объём пересечения двух тел, мм³. Ноль, если не пересекаются."""
    inter = left ^ right
    if inter.is_empty():
        return 0.0
    return abs(float(inter.volume()))


def scan_pairs(solids, tolerance: float = 0.01, allow: str | None = None,
          skip_parts: bool = True, share: float = 0.0):
    """Полный проход по парам: (пары, счётчики)."""
    pairs: list[dict] = []
    stats = {"objects": 0, "candidates": 0, "allowed": 0, "skipped_parts": 0}
    volumes: dict[str, float] = {}
    for left, right in combinations(list(solids), 2):
        stats["objects"] = max(stats["objects"], 0)
        if skip_parts and root(left.name) == root(right.name):
            stats["skipped_parts"] += 1
            continue
        if _allowed(allow, left.name, right.name):
            stats["allowed"] += 1
            continue
        if not _aabb_overlap(left.manifold, right.manifold):
            continue
        stats["candidates"] += 1
        inter = left.manifold ^ right.manifold
        volume = 0.0 if inter.is_empty() else abs(float(inter.volume()))
        if volume <= tolerance:
            continue
        if share > 0:
            for solid in (left, right):
                if solid.name not in volumes:
                    volumes[solid.name] = abs(float(solid.manifold.volume()))
            if volume < share * min(volumes[left.name], volumes[right.name]):
                continue
        bb = inter.bounding_box() if not inter.is_empty() else None
        pairs.append({"a": left.name, "b": right.name,
                      "volume_mm3": round(volume, 6),
                      "bbox": [round(float(v), 4) for v in bb] if bb else None})
    pairs.sort(key=lambda item: item["volume_mm3"], reverse=True)
    stats["objects"] = len(list(solids))
    return pairs, stats


def overlap_pairs(solids, tolerance: float = 0.01, allow: str | None = None,
                  skip_parts: bool = True, limit: int = 100,
                  share: float = 0.0) -> list[dict]:
    """Список пар, чьё пересечение больше порога, по убыванию объёма.

    `share` — доля меньшего тела (0…1): `share=0.01` значит «жаловаться только
    на пересечение больше 1 % объёма меньшей детали».
    """
    pairs, _ = scan_pairs(solids, tolerance=tolerance, allow=allow,
                     skip_parts=skip_parts, share=share)
    return pairs[:limit]
