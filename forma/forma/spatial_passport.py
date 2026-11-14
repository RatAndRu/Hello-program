"""Пространственный паспорт видимой сцены: измерения, а не угадывание формы.

Это производный снимок построенной сцены; источник проекта остаётся .forma.
Значения габаритов и срезов получаются из существующих Manifold-тел. Оценки
по ограничивающим коробкам и прореженные контуры не заменяют проверку контакта.
"""
from __future__ import annotations

import hashlib
import itertools
import math

from . import cuts
from .errors import FormaError


_LIMITS = {
    "fast": {"section_objects": 8, "levels": (0.5,), "pair_limit": 4000,
             "contours": 8, "points": 64, "triangles_per_object": 80000},
    "detail": {"section_objects": 16, "levels": (0.25, 0.5, 0.75), "pair_limit": 10000,
               "contours": 20, "points": 96, "triangles_per_object": 120000},
}
_AXES = ("x", "y", "z")


def _num(value):
    result = float(value)
    if not math.isfinite(result):
        raise FormaError("Невозможно измерить паспорт: в модели неконечные координаты.")
    return round(result, 6)


def _object(solid, groups):
    m = solid.manifold
    bb = [_num(v) for v in m.bounding_box()]
    return {
        "name": solid.name,
        "bbox_mm": bb,
        "size_mm": [_num(bb[i + 3] - bb[i]) for i in range(3)],
        "bbox_center_mm": [_num((bb[i] + bb[i + 3]) / 2) for i in range(3)],
        "volume_mm3": _num(m.volume()),
        "surface_area_mm2": _num(m.surface_area()),
        "triangles": int(m.num_tri()),
        "vertices": int(m.num_vert()),
        "manifold_status": m.status().name,
        "material": {"color": solid.color, "metal": _num(solid.metal),
                     "roughness": _num(solid.rough), "transmission": _num(solid.transmission),
                     "density_g_cm3": _num(solid.density)},
        "mass_estimate_g": _num(m.volume() / 1000 * solid.density),
        "groups": [str(k) for k, v in groups.items() if solid.name in v],
        "operation": solid.op,
        "source_line": int(solid.line or 0),
    }


def _relation(a, b):
    """Говорим только о коробках; наложение коробок не доказывает пересечение тел."""
    aa, bb = a["bbox_mm"], b["bbox_mm"]
    axes = {}
    square_gap = 0.0
    for i, axis in enumerate(_AXES):
        if bb[i] > aa[i + 3]:
            position, gap = "positive", bb[i] - aa[i + 3]
        elif aa[i] > bb[i + 3]:
            position, gap = "negative", aa[i] - bb[i + 3]
        else:
            position, gap = "overlap_or_touch", 0.0
        overlap = max(0.0, min(aa[i + 3], bb[i + 3]) - max(aa[i], bb[i]))
        axes[axis] = {"b_relative_to_a": position, "bbox_gap_mm": _num(gap),
                      "bbox_overlap_mm": _num(overlap)}
        square_gap += gap * gap
    return {"a": a["name"], "b": b["name"], "axes": axes,
            "bbox_distance_lower_bound_mm": _num(math.sqrt(square_gap)),
            "note": "Только габаритные коробки; контакт и пересечение тел не проверены."}


def _sections(solid, levels, max_contours, max_points):
    bb = solid.manifold.bounding_box()
    out = []
    for i, axis in enumerate(_AXES):
        for fraction in levels:
            at = float(bb[i] + (bb[i + 3] - bb[i]) * fraction)
            entry = {"object": solid.name, "axis": axis, "at_mm": _num(at),
                     "fraction_of_bbox": fraction}
            try:
                cs = cuts.slice_section(solid.manifold, axis, at)
                polygons = cuts.section_polygons(cs)
                selected = polygons[:max_contours]
                entry.update({
                    "status": "ok",
                    "area_mm2": _num(cs.area()),
                    "contour_count": len(polygons),
                    "negative_contours_in_slice": sum(p["area"] < 0 for p in polygons),
                    "contours_omitted": max(0, len(polygons) - len(selected)),
                    "contours": [{"signed_area_mm2": _num(p["area"]),
                                  "original_points": len(p["points"]),
                                  "points_mm": cuts.polygons_payload([p], max_points=max_points)[0]}
                                 for p in selected],
                })
            except ValueError as exc:
                # Плоскость может проходить по пустоте между частями объекта.
                entry.update({"status": "empty_or_invalid", "reason": str(exc)})
            except Exception as exc:
                # Не выдавать неудачный срез за отсутствие материала.
                entry.update({"status": "failed", "reason": str(exc)})
            out.append(entry)
    return out


def create_passport(scene, script: str, mode: str = "fast") -> dict:
    """Собрать ограниченный отчёт без изменения геометрии или сценария."""
    if mode not in _LIMITS:
        raise FormaError("Режим паспорта: fast или detail.")
    limits = _LIMITS[mode]
    solids = list(scene.visible_solids()) if scene is not None else []
    if not solids:
        raise FormaError("Нет видимых объектов для пространственного паспорта.")
    objects = [_object(s, getattr(scene, "groups", {}) or {}) for s in solids]
    total_pairs = len(objects) * (len(objects) - 1) // 2
    pairs = [_relation(a, b) for a, b in itertools.islice(
        itertools.combinations(objects, 2), limits["pair_limit"])]
    # Приоритет крупным деталям, а не порядку команд; список пропусков явный.
    ranked = sorted(zip(solids, objects),
                    key=lambda pair: (-abs(pair[1]["volume_mm3"]), pair[1]["name"]))
    sections, skipped = [], []
    included = 0
    for solid, obj in ranked:
        if obj["triangles"] > limits["triangles_per_object"]:
            skipped.append({"object": obj["name"], "reason": "превышен лимит треугольников для сечений"})
        elif included >= limits["section_objects"]:
            skipped.append({"object": obj["name"], "reason": "достигнут лимит объектов для сечений"})
        else:
            sections.extend(_sections(solid, limits["levels"], limits["contours"], limits["points"]))
            included += 1
    lower = [min(o["bbox_mm"][i] for o in objects) for i in range(3)]
    upper = [max(o["bbox_mm"][i + 3] for o in objects) for i in range(3)]
    return {
        "schema": "forma.spatial-passport.v1", "mode": mode,
        "source_sha256_utf8": hashlib.sha256((script or "").encode("utf-8")).hexdigest(),
        "units": {"length": "mm", "area": "mm2", "volume": "mm3"},
        "orientation": {"up": "+Z", "down": "-Z", "right": "+X", "front": "-Y"},
        "facts": {"visible_object_count": len(objects), "scene_bbox_mm": lower + upper,
                  "objects": objects,
                  "bbox_relations": {"total_possible": total_pairs, "returned": len(pairs),
                                     "omitted": total_pairs - len(pairs), "pairs": pairs},
                  "sections": sections, "sections_skipped_objects": skipped},
        "slice_coordinates": {"z": ["X", "Y"], "x": ["-Z", "Y"], "y": ["X", "-Z"]},
        "hypotheses": [],
        "limitations": [
            "Измерены только видимые тела построенной сцены, а не физический предмет.",
            "Центр — центр габаритной коробки, не центр масс; масса оценена по плотности материала.",
            "Отношения относятся только к габаритным коробкам: наложение не доказывает контакт или пересечение тел.",
            "Сечения только на указанных уровнях и не доказывают отсутствие отверстий, полостей и тонких деталей в других местах.",
            "Контуры могут быть ограничены и прорежены; площадь вычислена по полному сечению, а не по показанным точкам.",
            "Не измеряются назначение деталей, физическое равновесие, самопересечения и точные зазоры между телами.",
        ],
    }


def passport_markdown(data: dict) -> str:
    facts = data["facts"]
    lines = ["# Пространственный паспорт Forma 3D", "",
             f"Режим: {data['mode']}. Источник .forma, SHA-256: `{data['source_sha256_utf8']}`.",
             "Оси: +Z вверх, +X вправо, −Y вперёд; размеры в мм.", "",
             "## Измерения видимых объектов", "",
             "| Объект | Габариты XYZ, мм | Центр коробки XYZ, мм | Объём, мм³ | Треугольники |",
             "|---|---|---|---:|---:|"]
    for obj in facts["objects"]:
        name = str(obj["name"]).replace("|", "\\|").replace("\n", " ")
        size = " × ".join(f"{v:g}" for v in obj["size_mm"])
        center = ", ".join(f"{v:g}" for v in obj["bbox_center_mm"])
        lines.append(f"| {name} | {size} | {center} | {obj['volume_mm3']:g} | {obj['triangles']} |")
    r = facts["bbox_relations"]
    lines += ["", "## Отношения и сечения", "",
              f"Отношения коробок: {r['returned']} из {r['total_possible']}; пропущено {r['omitted']}. "
              "Полные координаты и пары — в passport.json.",
              f"Срезов: {len(facts['sections'])}; пропущено объектов: {len(facts['sections_skipped_objects'])}.",
              "Контуры, уровни, площади и причины пропусков — в passport.json.",
              "", "## Гипотезы", "", "Автоматические предположения о назначении и контакте не делаются.",
              "", "## Ограничения", ""]
    lines.extend("- " + s for s in data["limitations"])
    return "\n".join(lines) + "\n"
