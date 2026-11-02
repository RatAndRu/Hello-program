"""Единая проверка пересечений отдельных тел на ``manifold3d``.

AABB здесь только отбрасывает заведомо разнесённые пары. Вердикт и объём
всегда получаются из булева пересечения ``left ^ right``; касание поверхностей
не считается пересечением, потому что его объём равен нулю.

Модуль используют команда ``interference``, правила ``check`` и автоматический
анализ. Он не знает ничего о DSL и не меняет геометрию сцены.
"""
from __future__ import annotations

import fnmatch
from itertools import combinations

import numpy as np

from .errors import GeometryError

__all__ = [
    "root", "merge_allow", "overlap_pairs", "pair_volume", "scan_pairs",
]


def root(name: str) -> str:
    """Корень составной детали: ``корпус.дно`` → ``корпус``."""
    return str(name).split(".")[0]


def merge_allow(*specs) -> str:
    """Объединить именованные списки разрешённых пар без дублирования."""
    out: list[str] = []
    for spec in specs:
        values = spec if isinstance(spec, (list, tuple)) else [spec]
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text and text not in out:
                out.append(text)
    return ",".join(out)


def _allow_patterns(spec) -> tuple[tuple[str, str], ...]:
    """Разобрать ``a:b,c:d`` и отклонить опечатку вместо молчаливого allow."""
    if not spec:
        return ()
    patterns = []
    for raw in str(spec).replace(";", ",").split(","):
        pair = raw.strip()
        if not pair:
            continue
        delimiter = ":" if ":" in pair else "|" if "|" in pair else None
        parts = pair.split(delimiter) if delimiter else []
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise GeometryError("allow задаётся парами a:b,c:d.")
        a, b = (part.strip() for part in parts)
        patterns.append((a, b))
    return tuple(patterns)


def _matches_allow(patterns, left: str, right: str) -> bool:
    return any(
        (fnmatch.fnmatchcase(left, a) and fnmatch.fnmatchcase(right, b)) or
        (fnmatch.fnmatchcase(left, b) and fnmatch.fnmatchcase(right, a))
        for a, b in patterns
    )


def _aabb_overlap(a, b) -> bool:
    """Строгий broad-phase: соприкосновение коробок не является кандидатом."""
    la, ra = a.bounding_box(), b.bounding_box()
    overlap = np.minimum(np.asarray(la[3:]), np.asarray(ra[3:])) - \
        np.maximum(np.asarray(la[:3]), np.asarray(ra[:3]))
    # Не используем произвольный epsilon: на очень больших деталях он мог бы
    # скрыть тонкий, но превышающий допуск объём. Точный этап сам отсеет шум.
    return bool(np.all(overlap > 0.0))


def pair_volume(left, right) -> float:
    """Точный объём общего материала двух ``Manifold`` в мм³."""
    if left.is_empty() or right.is_empty() or not _aabb_overlap(left, right):
        return 0.0
    intersection = left ^ right
    if intersection.is_empty():
        return 0.0
    return abs(float(intersection.volume()))


def scan_pairs(solids, tolerance: float = 0.01, allow: str | None = None,
               skip_parts: bool = True, share: float = 0.0,
               target: str | None = None, limit: int | None = None):
    """Сканировать пары и вернуть ``(pairs, stats)``.

    ``target`` ограничивает проход парами с указанным именем. Это важно для
    ``check деталь collision``: нельзя сначала обрезать общий топ пар сцены,
    иначе чужие большие пересечения способны скрыть дефект выбранной детали.
    ``limit`` обрезает только возвращаемый список, после сортировки; статистика
    ``matched`` и ``truncated`` сохраняет полное число найденных пар.
    """
    items = list(solids)
    tolerance = float(tolerance)
    share = float(share)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise GeometryError("Допуск пересечения должен быть конечным числом не меньше нуля.")
    if not np.isfinite(share) or not 0 <= share <= 1:
        raise GeometryError("Доля пересечения share должна быть в диапазоне 0…1.")
    if limit is not None and int(limit) < 1:
        raise GeometryError("Лимит пар должен быть не меньше единицы.")

    patterns = _allow_patterns(allow)
    pairs: list[dict] = []
    stats = {"objects": len(items), "candidates": 0, "allowed": 0,
             "skipped_parts": 0, "matched": 0, "truncated": 0}
    volumes: dict[int, float] = {}

    for left, right in combinations(items, 2):
        if target is not None and target not in (left.name, right.name):
            continue
        if skip_parts and root(left.name) == root(right.name):
            stats["skipped_parts"] += 1
            continue
        if _matches_allow(patterns, left.name, right.name):
            stats["allowed"] += 1
            continue
        if left.manifold.is_empty() or right.manifold.is_empty():
            continue
        if not _aabb_overlap(left.manifold, right.manifold):
            continue
        stats["candidates"] += 1
        intersection = left.manifold ^ right.manifold
        volume = 0.0 if intersection.is_empty() else abs(float(intersection.volume()))
        if volume <= tolerance:
            continue
        if share > 0:
            for solid in (left, right):
                key = id(solid)
                if key not in volumes:
                    volumes[key] = abs(float(solid.manifold.volume()))
            if volume < share * min(volumes[id(left)], volumes[id(right)]):
                continue
        bb = None if intersection.is_empty() else [
            round(float(value), 4) for value in intersection.bounding_box()
        ]
        pairs.append({"a": left.name, "b": right.name,
                      "volume_mm3": round(volume, 6), "bbox": bb})

    pairs.sort(key=lambda item: item["volume_mm3"], reverse=True)
    stats["matched"] = len(pairs)
    if limit is not None:
        limit = int(limit)
        stats["truncated"] = max(0, len(pairs) - limit)
        pairs = pairs[:limit]
    return pairs, stats


def overlap_pairs(solids, tolerance: float = 0.01, allow: str | None = None,
                  skip_parts: bool = True, limit: int = 100,
                  share: float = 0.0, target: str | None = None) -> list[dict]:
    """Пары выше абсолютного и относительного порогов, по убыванию объёма."""
    pairs, _ = scan_pairs(solids, tolerance=tolerance, allow=allow,
                          skip_parts=skip_parts, share=share, target=target,
                          limit=limit)
    return pairs
