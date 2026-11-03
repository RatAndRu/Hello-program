"""Подгонка размеров по силуэту с репером и явной неоднозначностью.

Одна фотография не восстанавливает скрытый объём. Здесь оптимизируются только
заявленные параметры существующей parametric build, а абсолютный масштаб
получается из пары «пиксели репера → миллиметры», иначе результат честно
остаётся неопределённым.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Callable, Sequence

import numpy as np

from ..ops import scale as scale_manifold
from .fit import fit_camera, render_mask
from .silhouette import _as_mask, compare, mask_by_background, measure


def _mask(reference) -> np.ndarray:
    array = np.asarray(reference)
    if array.ndim == 2:
        return _as_mask(array)
    if array.ndim == 3:
        return mask_by_background(array)
    raise ValueError("Нужна маска H×W или RGB-фотография H×W×3.")


def _solids_and_build(model, values, base_dir=None):
    if isinstance(model, str):
        from ..run import build
        result = build(model, overrides=values, analyze_model=False, base_dir=base_dir)
        if not result.ok:
            raise ValueError((result.error or {}).get("message", "parametric build failed"))
        return result.visible_solids(), result
    if hasattr(model, "visible_solids") and hasattr(model, "script"):
        if values:
            from ..run import build
            result = build(model.script, overrides=values, analyze_model=False,
                           base_dir=base_dir or getattr(model.scene, "base_dir", None))
            if not result.ok:
                raise ValueError((result.error or {}).get("message", "parametric build failed"))
            return result.visible_solids(), result
        return model.visible_solids(), model
    if callable(model):
        try:
            result = model(values)
        except TypeError:
            result = model()
        if hasattr(result, "visible_solids"):
            return result.visible_solids(), result
        return list(result), None
    if values:
        raise ValueError("Для статического списка Solid параметры оптимизации недоступны.")
    return list(model), None


def _bounds(solids):
    boxes = [solid.manifold.bounding_box() for solid in solids]
    if not boxes:
        raise ValueError("Нет видимых объектов для подгонки.")
    array = np.asarray(boxes, dtype=float)
    return array[:, :3].min(axis=0), array[:, 3:].max(axis=0)


def _parameter_specs(parameters, initial):
    if parameters is None:
        return {}
    if isinstance(parameters, (list, tuple)):
        parameters = {name: {} for name in parameters}
    result = {}
    for name, raw in parameters.items():
        current = float(initial.get(name, 0.0))
        if isinstance(raw, dict):
            spec = dict(raw)
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            spec = {"min": raw[0], "max": raw[1]}
        else:
            spec = {"step": raw}
        spec.setdefault("min", current - max(10.0, abs(current) * 2.0))
        spec.setdefault("max", current + max(10.0, abs(current) * 2.0))
        spec.setdefault("step", max(0.1, abs(current) * 0.1, (spec["max"] - spec["min"]) / 20.0))
        spec["min"], spec["max"], spec["step"] = float(spec["min"]), float(spec["max"]), float(spec["step"])
        if spec["min"] > spec["max"] or spec["step"] <= 0:
            raise ValueError(f"Некорректные границы параметра {name}.")
        result[str(name)] = spec
    return result


def _score(metrics):
    row = metrics.get("row_err_px", 100.0)
    if not math.isfinite(row):
        row = 256.0
    return (1.0 - float(metrics.get("iou", 0.0))
            + min(abs(float(metrics.get("aspect_err_pct", 100.0))), 100.0) / 400.0
            + row / 1024.0)


def _scaled(solids, factor):
    if abs(factor - 1.0) < 1e-12:
        return solids
    output = []
    for original in solids:
        solid = copy.copy(original)
        solid.manifold = scale_manifold(original.manifold, [factor, factor, factor])
        solid._stats = None
        output.append(solid)
    return output


def fit_dimensions(reference, model, parameters=None, *, reference_length_px: float | None = None,
                   reference_length_mm: float | None = None, reference_axis: str = "height",
                   camera: dict | None = None, size: int = 160, max_iter: int = 32,
                   mirror: bool = False, base_dir=None) -> dict:
    """Возвращает значения, масштаб, residual и диагностику неоднозначности.

    ``model`` — список Solid, Build, текст Forma или callable(values). Для
    callable/текста ``parameters`` задаёт координатный поиск; камера и IoU
    используют уже существующие silhouette/fit, а не новый рендерер.
    """
    reference_mask = _mask(reference)
    if int(size) < 16:
        raise ValueError("size для silhouette fitting должен быть не меньше 16 пикселей.")
    initial = {}
    baseline = None
    if isinstance(model, str):
        from ..run import build
        baseline = build(model, analyze_model=False, base_dir=base_dir)
        if not baseline.ok:
            raise ValueError((baseline.error or {}).get("message", "parametric build failed"))
        if baseline.scene:
            initial.update({key: float(value) for key, value in baseline.scene.params.items()
                            if isinstance(value, (int, float)) and not isinstance(value, bool)})
    elif hasattr(model, "scene") and getattr(model, "scene", None) is not None:
        initial.update({key: float(value) for key, value in model.scene.params.items()
                        if isinstance(value, (int, float)) and not isinstance(value, bool)})
    specs = _parameter_specs(parameters, initial)
    for name in specs:
        initial.setdefault(name, 0.0)
    if baseline is not None and not specs:
        solids, current_build = baseline.visible_solids(), baseline
    else:
        solids, current_build = _solids_and_build(model, initial if specs else {}, base_dir=base_dir)
    if not solids:
        raise ValueError("Модель не содержит видимых тел.")
    if camera is None:
        fitted_camera = fit_camera(reference_mask, solids, size=size, refine=1, mirror=mirror)
        azim, elev = fitted_camera["azim_deg"], fitted_camera["elev_deg"]
    else:
        azim = float(camera.get("azim_deg", camera.get("azim", 45.0)))
        elev = float(camera.get("elev_deg", camera.get("elev", 25.0)))
        fitted_camera = dict(camera)
    evaluations = 0
    history = []
    alternatives = []

    def evaluate(values):
        nonlocal evaluations
        candidate_solids, candidate_build = _solids_and_build(
            model, values if specs else {}, base_dir=base_dir)
        candidate_mask = render_mask(candidate_solids, azim, elev, size=size, mirror=mirror)
        metrics = compare(reference_mask, candidate_mask)
        evaluations += 1
        return _score(metrics), metrics, candidate_solids, candidate_build, candidate_mask

    best_score, best_metrics, best_solids, best_build, best_mask = evaluate(initial)
    best_values = dict(initial)
    history.append({"values": dict(best_values), "score": best_score, "iou": best_metrics["iou"]})
    # Координатный поиск с детерминированным уменьшением шага. Он не выдаёт
    # локальный минимум за доказательство единственного решения.
    steps = {name: spec["step"] for name, spec in specs.items()}
    for _pass in range(6):
        if evaluations >= max_iter or not specs:
            break
        improved = False
        for name, spec in specs.items():
            for direction in (1.0, -1.0):
                if evaluations >= max_iter:
                    break
                candidate_values = dict(best_values)
                candidate_values[name] = float(np.clip(best_values[name] + direction * steps[name],
                                                        spec["min"], spec["max"]))
                if abs(candidate_values[name] - best_values[name]) < 1e-12:
                    continue
                score, metrics, candidate_solids, candidate_build, candidate_mask = evaluate(candidate_values)
                history.append({"values": dict(candidate_values), "score": score, "iou": metrics["iou"]})
                if score < best_score - 1e-7:
                    best_score, best_metrics = score, metrics
                    best_solids, best_build, best_mask = candidate_solids, candidate_build, candidate_mask
                    best_values = candidate_values
                    improved = True
                elif score < best_score + 0.005:
                    alternatives.append({"values": dict(candidate_values), "score": score})
        if not improved:
            for name in steps:
                steps[name] *= 0.5
            if all(step < 1e-3 for step in steps.values()):
                break
    # Масштаб по реперу: репер сам может быть любой видимой длиной, а ось
    # результата выбирается явно. Без него абсолютный масштаб не выдумываем.
    axis = {"h": "height", "z": "height", "высота": "height",
            "w": "width", "x": "width", "ширина": "width",
            "d": "depth", "y": "depth", "глубина": "depth"}.get(str(reference_axis).lower(), reference_axis)
    if axis not in {"height", "width", "depth"}:
        raise ValueError("reference_axis: height, width или depth.")
    ref_measure = measure(reference_mask)
    diagnostics = ["Подгонка относится к одной ортографической проекции; скрытая геометрия не проверена."]
    ambiguous = False
    target_mm = None
    scale = 1.0
    if reference_length_px is not None or reference_length_mm is not None:
        if reference_length_px is None or reference_length_mm is None:
            raise ValueError("Для репера нужны одновременно reference_length_px и reference_length_mm.")
        reference_length_px = float(reference_length_px)
        reference_length_mm = float(reference_length_mm)
        if (not math.isfinite(reference_length_px) or not math.isfinite(reference_length_mm)
                or reference_length_px <= 0 or reference_length_mm <= 0):
            raise ValueError("Длина репера в px и мм должна быть положительной и конечной.")
        mm_per_px = reference_length_mm / reference_length_px
        reference_pixels = ref_measure.height if axis == "height" else ref_measure.width
        if axis == "depth":
            diagnostics.append("Глубина по одному виду не наблюдается напрямую; использована видимая ширина силуэта.")
            ambiguous = True
        target_value = float(reference_pixels * mm_per_px)
        target_mm = {axis: target_value}
        lo, hi = _bounds(best_solids)
        index = {"width": 0, "depth": 1, "height": 2}[axis]
        current = float(hi[index] - lo[index])
        if current <= 1e-9:
            raise ValueError(f"Текущий габарит {axis} равен нулю; масштаб не определён.")
        scale = target_value / current
    else:
        diagnostics.append("Абсолютный масштаб неизвестен без репера: задайте px и мм одной видимой длины.")
        ambiguous = True
    if alternatives:
        diagnostics.append("Есть близкие по residual наборы параметров; одного силуэта недостаточно для уникального выбора.")
        ambiguous = True
    if best_metrics["iou"] < 0.90:
        diagnostics.append(f"Остаточная ошибка формы высока: IoU {best_metrics['iou']:.3f} < 0.90.")
    scaled_solids = _scaled(best_solids, scale)
    lo, hi = _bounds(scaled_solids)
    residual = dict(best_metrics)
    residual["score"] = float(best_score)
    residual["rmse_px"] = float(best_metrics.get("row_err_px", float("nan")) / math.sqrt(2.0))
    residual["evaluations"] = evaluations
    return {
        "ok": bool(best_metrics["iou"] >= 0.85),
        "values": best_values,
        "scale": float(scale),
        "target_mm": target_mm,
        "scaled_size": (hi - lo).tolist(),
        "camera": {"azim_deg": float(azim), "elev_deg": float(elev), **fitted_camera},
        "reference": ref_measure.as_dict(),
        "residual": residual,
        "ambiguous": bool(ambiguous),
        "diagnostics": diagnostics,
        "history": history[-40:],
        "evaluations": evaluations,
        "build": best_build,
        "solids": scaled_solids,
        "provenance": {"shape": "existing_silhouette_camera_fit", "scale": "reference_length" if target_mm else "unknown",
                       "hidden_geometry": "not_validated"},
    }


fit_by_photo = fit_dimensions
fit_photo = fit_dimensions
