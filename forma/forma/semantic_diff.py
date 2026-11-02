"""Семантическое сравнение сцен Forma без сравнения сырых mesh-id."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _scene(value):
    return value.scene if hasattr(value, "scene") else value


def _numbers_equal(a, b, tolerance: float) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not math.isfinite(float(a)) or not math.isfinite(float(b)):
            return float(a) == float(b)
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=tolerance)
    return a == b


def _parameter_diff(before: dict, after: dict, tolerance: float) -> dict:
    a_keys, b_keys = set(before), set(after)
    changed = {}
    for key in sorted(a_keys & b_keys):
        old, new = before[key], after[key]
        if _numbers_equal(old, new, tolerance):
            continue
        item = {"before": old, "after": new}
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            item["delta"] = float(new) - float(old)
        changed[key] = item
    return {
        "added": {key: after[key] for key in sorted(b_keys - a_keys)},
        "removed": {key: before[key] for key in sorted(a_keys - b_keys)},
        "changed": changed,
    }


def _measurement(before: float, after: float) -> dict:
    return {"before": float(before), "after": float(after),
            "delta": float(after) - float(before)}


def _vector_measurement(before, after) -> dict:
    a = np.asarray(before, dtype=np.float64)
    b = np.asarray(after, dtype=np.float64)
    return {"before": a.tolist(), "after": b.tolist(), "delta": (b - a).tolist()}


def _object_measurements(solid) -> dict:
    stats = solid.stats()
    return {
        "size": np.asarray(stats["size"], dtype=np.float64),
        "bbox": np.asarray(stats["bbox"], dtype=np.float64),
        "volume": float(stats["volume"]),
        "area": float(stats["area"]),
        "parts": int(len(solid.manifold.decompose())),
        "genus": int(solid.manifold.genus()),
        "triangles": int(solid.manifold.num_tri()),
    }


def _json_value(value):
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=str)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _object_attributes(solid) -> dict:
    return _json_value({
        "op": solid.op, "color": solid.color, "metal": solid.metal,
        "rough": solid.rough, "density": solid.density, "visible": solid.visible,
        "emissive": solid.emissive, "emissive_strength": solid.emissive_strength,
        "mirror": solid.mirror, "transmission": solid.transmission,
        "tex": solid.tex, "paint": solid.paint, "brush": solid.brush,
        "notes": solid.notes, "meta": solid.meta,
    })


def _object_changed(name: str, before, after, linear_tol: float,
                    area_tol: float | None, volume_tol: float | None) -> dict | None:
    a, b = _object_measurements(before), _object_measurements(after)
    attributes_before, attributes_after = _object_attributes(before), _object_attributes(after)
    scale = max(1.0, float(np.max(a["size"])), float(np.max(b["size"])))
    # Если допуски производных величин не заданы, связываем их с линейным:
    # δS ≈ периметр·δL, δV ≈ площадь·δL. Коэффициент 12 покрывает box с запасом.
    effective_area = area_tol if area_tol is not None else max(1e-8, 12 * linear_tol * scale)
    effective_volume = (volume_tol if volume_tol is not None
                        else max(1e-9, 12 * linear_tol * scale * scale))
    measurements = {
        "size": _vector_measurement(a["size"], b["size"]),
        "bbox": _vector_measurement(a["bbox"], b["bbox"]),
        "volume": _measurement(a["volume"], b["volume"]),
        "area": _measurement(a["area"], b["area"]),
        "center": _vector_measurement(
            (a["bbox"][[0, 1, 2]] + a["bbox"][[3, 4, 5]]) / 2,
            (b["bbox"][[0, 1, 2]] + b["bbox"][[3, 4, 5]]) / 2),
    }
    linear_delta = max(
        float(np.max(np.abs(a["size"] - b["size"]))),
        float(np.max(np.abs(a["bbox"] - b["bbox"]))),
    )
    reasons = []
    if linear_delta > linear_tol:
        reasons.append("geometry")
    if abs(a["volume"] - b["volume"]) > effective_volume:
        reasons.append("volume")
    if abs(a["area"] - b["area"]) > effective_area:
        reasons.append("area")
    if a["parts"] != b["parts"]:
        reasons.append("parts")
    if a["genus"] != b["genus"]:
        reasons.append("genus")
    if before.kind != after.kind:
        reasons.append("kind")
    if attributes_before != attributes_after:
        reasons.append("attributes")
    if not reasons:
        return None
    return {
        "name": name,
        "before_kind": before.kind,
        "after_kind": after.kind,
        "attributes": ({"before": attributes_before, "after": attributes_after}
                       if attributes_before != attributes_after else None),
        "reasons": sorted(set(reasons)),
        "measurements": measurements,
        "effective_tolerances": {"linear": linear_tol, "area": effective_area,
                                 "volume": effective_volume},
        "topology": {
            "parts": {"before": a["parts"], "after": b["parts"]},
            "genus": {"before": a["genus"], "after": b["genus"]},
            "triangles": {"before": a["triangles"], "after": b["triangles"]},
        },
    }


def _contour_changed(name: str, before, after, tolerance: float) -> dict | None:
    a, b = before.to_dict(), after.to_dict()
    # sample — производная от аналитики и допуска, а не самостоятельный параметр.
    a_core = {k: v for k, v in a.items() if k != "sample"}
    b_core = {k: v for k, v in b.items() if k != "sample"}
    if a_core == b_core:
        return None
    return {"name": name, "before": a, "after": b,
            "sample_points_delta": b["sample"]["points"] - a["sample"]["points"],
            "tolerance": tolerance}


def semantic_diff(before, after, linear_tol: float = 1e-3,
                  area_tol: float | None = None,
                  volume_tol: float | None = None) -> dict[str, Any]:
    """Возвращает JSON-совместимый diff двух BuildResult или Scene.

    linear_tol — мм, area_tol — мм², volume_tol — мм³. Нулевые и отрицательные
    допуски запрещены: они превращают вычисления с плавающей точкой в шум.
    """
    linear_tol = float(linear_tol)
    if not math.isfinite(linear_tol) or linear_tol <= 0:
        raise ValueError("linear_tol должен быть положительным числом, мм.")
    if area_tol is not None:
        area_tol = float(area_tol)
    if volume_tol is not None:
        volume_tol = float(volume_tol)
    if ((area_tol is not None and (not math.isfinite(area_tol) or area_tol <= 0)) or
            (volume_tol is not None and (not math.isfinite(volume_tol) or volume_tol <= 0))):
        raise ValueError("area_tol и volume_tol должны быть положительными.")
    a_scene, b_scene = _scene(before), _scene(after)
    if a_scene is None or b_scene is None:
        raise ValueError("Для semantic_diff нужны две успешно построенные сцены.")
    a_objects, b_objects = a_scene.objects, b_scene.objects
    added = sorted(set(b_objects) - set(a_objects))
    removed = sorted(set(a_objects) - set(b_objects))
    changed = []
    for name in sorted(set(a_objects) & set(b_objects)):
        item = _object_changed(name, a_objects[name], b_objects[name],
                               linear_tol, area_tol, volume_tol)
        if item is not None:
            changed.append(item)
    a_contours, b_contours = a_scene.contours, b_scene.contours
    contour_changes = []
    for name in sorted(set(a_contours) & set(b_contours)):
        item = _contour_changed(name, a_contours[name], b_contours[name], linear_tol)
        if item is not None:
            contour_changes.append(item)
    return {
        "schema": "forma.semantic-diff.v1",
        "units": {"linear": "mm", "area": "mm^2", "volume": "mm^3"},
        "tolerances": {
            "linear": linear_tol,
            "area": area_tol if area_tol is not None else "auto",
            "volume": volume_tol if volume_tol is not None else "auto",
            "auto_rules": {
                "area": "max(1e-8, 12 * linear * max_object_size)",
                "volume": "max(1e-9, 12 * linear * max_object_size^2)",
            },
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "parameters": _parameter_diff(a_scene.params, b_scene.params, linear_tol),
        "contours": {
            "added": sorted(set(b_contours) - set(a_contours)),
            "removed": sorted(set(a_contours) - set(b_contours)),
            "changed": contour_changes,
        },
    }
