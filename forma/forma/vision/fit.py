"""Быстрое сравнение твёрдой модели с измеренным силуэтом.

Ракурс подбирается анализом через синтез: одна и та же подготовленная сетка
проецируется с нескольких ортографических камер. Здесь нужен только бинарный
силуэт, поэтому освещение, нормали, материалы, z-buffer и PNG не вычисляются.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .. import render
from ..geometry import manifold_mesh
from .silhouette import _as_mask, camera_elevation, compare, iou, mask_by_background, measure

__all__ = ["render_mask", "fit_camera", "compare_model", "report"]

DEFAULT_AZIM = (-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0)
DEFAULT_ELEV = (10.0, 25.0, 40.0)


def _unit(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float64)
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-12 else vector


def _camera(center: np.ndarray, radius: float, azim_deg: float, elev_deg: float,
            size: int) -> dict:
    """Та же ортографическая камера, что в render, без записи в render.VIEWS."""
    azim = math.radians(azim_deg)
    elev = math.radians(elev_deg)
    eye = _unit((math.cos(elev) * math.cos(azim),
                 math.cos(elev) * math.sin(azim), math.sin(elev)))
    forward = -eye
    right = _unit(np.cross(forward, np.array([0.0, 0.0, 1.0])))
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    up = _unit(np.cross(right, forward))
    return {
        "f": forward, "right": right, "up": up,
        "scale": size * 0.46 / max(radius, 1e-9),
        "center": np.asarray(center, dtype=np.float64),
        "eye": np.asarray(center, dtype=np.float64) - forward * radius * 4,
        "w": size, "h": size,
    }


class _MaskRenderer:
    """Подготовленная геометрия; повторные ракурсы не тесселируют тела заново."""

    def __init__(self, solids, size: int, max_cells: int = 300_000):
        if not isinstance(size, int) or size < 16:
            raise ValueError("size должен быть целым не меньше 16")
        self.size = size
        self.max_cells = max(10_000, int(max_cells))
        meshes = []
        for solid in solids:
            vertices, faces = manifold_mesh(solid.manifold)
            if len(faces):
                meshes.append((np.asarray(vertices, dtype=np.float64),
                               np.asarray(faces, dtype=np.int64)))
        if not meshes:
            raise ValueError("нет объектов для рендера")
        self.meshes = meshes
        all_vertices = np.concatenate([vertices for vertices, _faces in meshes], axis=0)
        if not np.isfinite(all_vertices).all():
            raise ValueError("геометрия содержит нечисловые координаты")
        lo, hi = all_vertices.min(axis=0), all_vertices.max(axis=0)
        self.center = (lo + hi) / 2.0
        self.radius = float(np.linalg.norm(hi - lo)) / 2.0
        if self.radius <= 1e-9:
            raise ValueError("нулевой габарит модели")

    def render(self, azim_deg: float, elev_deg: float, mirror: bool = False) -> np.ndarray:
        camera = _camera(self.center, self.radius, float(azim_deg), float(elev_deg), self.size)
        mask = self._raster(camera)
        # Только явный запрос: по умолчанию +X остаётся справа при виде спереди.
        return mask[:, ::-1] if mirror else mask

    def _raster(self, camera: dict) -> np.ndarray:
        """Объединение проекций треугольников; глубина для силуэта не нужна."""
        size = self.size
        out = np.zeros((size, size), dtype=bool)
        # Округление bounding box до степени двойки даёт небольшое число
        # векторных batches даже на модели с сотнями тысяч треугольников.
        pow2 = np.array([1] + [1 << (value - 1).bit_length()
                               for value in range(1, size + 1)], dtype=np.int64)
        for vertices, faces in self.meshes:
            screen, _depth = render._project(vertices, camera)
            triangles = screen[faces]
            lower = triangles.min(axis=1)
            upper = triangles.max(axis=1)
            minx = np.maximum(np.floor(lower[:, 0]).astype(np.int64), 0)
            miny = np.maximum(np.floor(lower[:, 1]).astype(np.int64), 0)
            maxx = np.minimum(np.ceil(upper[:, 0]).astype(np.int64), size - 1)
            maxy = np.minimum(np.ceil(upper[:, 1]).astype(np.int64), size - 1)
            area = ((triangles[:, 1, 0] - triangles[:, 0, 0])
                    * (triangles[:, 2, 1] - triangles[:, 0, 1])
                    - (triangles[:, 2, 0] - triangles[:, 0, 0])
                    * (triangles[:, 1, 1] - triangles[:, 0, 1]))
            keep = (minx <= maxx) & (miny <= maxy) & (np.abs(area) > 1e-12)
            if not keep.any():
                continue
            triangles = triangles[keep]
            area = area[keep]
            minx, miny = minx[keep], miny[keep]
            maxx, maxy = maxx[keep], maxy[keep]
            widths, heights = maxx - minx + 1, maxy - miny + 1
            group_w, group_h = pow2[widths], pow2[heights]
            codes = group_w * (size + 1) + group_h
            for code in np.unique(codes):
                ids = np.flatnonzero(codes == code)
                width, height = int(group_w[ids[0]]), int(group_h[ids[0]])
                yy, xx = np.mgrid[:height, :width]
                chunk = max(1, self.max_cells // (width * height))
                for start in range(0, len(ids), chunk):
                    selected = ids[start:start + chunk]
                    tri = triangles[selected]
                    denominator = area[selected, None, None]
                    ox, oy = minx[selected, None, None], miny[selected, None, None]
                    x = ox + xx[None, :, :] + 0.5
                    y = oy + yy[None, :, :] + 0.5
                    w0 = ((tri[:, 1, 0, None, None] - x) * (tri[:, 2, 1, None, None] - y)
                          - (tri[:, 2, 0, None, None] - x)
                          * (tri[:, 1, 1, None, None] - y)) / denominator
                    w1 = ((tri[:, 2, 0, None, None] - x) * (tri[:, 0, 1, None, None] - y)
                          - (tri[:, 0, 0, None, None] - x)
                          * (tri[:, 2, 1, None, None] - y)) / denominator
                    inside = (w0 >= -1e-6) & (w1 >= -1e-6) & ((1.0 - w0 - w1) >= -1e-6)
                    inside &= ((xx[None, :, :] < widths[selected, None, None])
                               & (yy[None, :, :] < heights[selected, None, None]))
                    if inside.any():
                        flat = (oy + yy[None, :, :]) * size + ox + xx[None, :, :]
                        out.flat[flat[inside]] = True
        return out


def render_mask(solids, azim_deg: float = 45.0, elev_deg: float = 25.0,
                size: int = 320, mirror: bool = False) -> np.ndarray:
    """Бинарная проекция модели без полного shaded render."""
    return _MaskRenderer(solids, size).render(azim_deg, elev_deg, mirror=mirror)


def _angle_values(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not np.isfinite(result).all():
        raise ValueError(f"{name}: нужен непустой список конечных углов")
    return result


def _grid_step(values: tuple[float, ...], default: float) -> float:
    ordered = sorted(set(values))
    differences = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    return min(differences) if differences else default


def _fit_with_renderer(reference_mask: np.ndarray, renderer: _MaskRenderer,
                       azim: Sequence[float], elev: Sequence[float], refine: int,
                       mirror: bool) -> dict:
    reference_mask = _as_mask(reference_mask)
    azim = _angle_values(azim, "azim")
    elev = _angle_values(elev, "elev")
    if not isinstance(refine, int) or refine < 0:
        raise ValueError("refine должен быть неотрицательным целым")
    tried: list[dict] = []
    cache: dict[tuple[float, float], float] = {}

    def score(a: float, e: float) -> float:
        key = (round(float(a), 7), round(float(e), 7))
        if key not in cache:
            mask = renderer.render(a, e, mirror=mirror)
            cache[key] = iou(reference_mask, mask)
            tried.append({"azim": float(a), "elev": float(e), "iou": cache[key]})
        return cache[key]

    best: tuple[float, float, float] | None = None
    for a in azim:
        for e in elev:
            value = score(a, e)
            if best is None or value > best[0]:
                best = (value, float(a), float(e))
    assert best is not None

    step_a, step_e = _grid_step(azim, 15.0), _grid_step(elev, 10.0)
    for _level in range(refine):
        step_a /= 2.0
        step_e /= 2.0
        # Каждое улучшение строго больше 1e-4; лимит страхует от неожиданно
        # плоской дискретной метрики и гарантирует завершение.
        for _iteration in range(64):
            improved = False
            _value, a0, e0 = best
            for da, de in ((step_a, 0.0), (-step_a, 0.0),
                           (0.0, step_e), (0.0, -step_e)):
                a, e = a0 + da, e0 + de
                if not -89.0 <= e <= 89.0:
                    continue
                value = score(a, e)
                if value > best[0] + 1e-4:
                    best = (value, a, e)
                    improved = True
                    break
            if not improved:
                break

    value, a, e = best
    ordered = sorted(tried, key=lambda item: (-item["iou"], item["azim"], item["elev"]))
    return {
        "azim_deg": float(a), "elev_deg": float(e), "iou": float(value),
        "verdict": ("кандидат ракурса" if value >= 0.85 else
                    "силуэт модели не совпадает: сначала проверьте форму и пропорции"),
        "projection": "orthographic", "mirrored": bool(mirror),
        "top": ordered[:6], "renders": len(tried),
    }


def fit_camera(reference_mask: np.ndarray, solids,
               azim: Sequence[float] = DEFAULT_AZIM,
               elev: Sequence[float] = DEFAULT_ELEV,
               size: int = 320, refine: int = 2, mirror: bool = False) -> dict:
    """Подбирает кандидата ортографической камеры по IoU силуэта."""
    reference_mask = _as_mask(reference_mask)
    renderer = _MaskRenderer(solids, size)
    return _fit_with_renderer(reference_mask, renderer, azim, elev, refine, mirror)


def _comparison(reference_mask: np.ndarray, model_mask: np.ndarray) -> dict:
    result = compare(reference_mask, model_mask)
    result["fill_ref"] = measure(reference_mask).fill
    result["fill_model"] = measure(model_mask).fill
    return result


def compare_model(reference_mask: np.ndarray, solids, azim_deg: float, elev_deg: float,
                  size: int = 320, mirror: bool = False) -> dict:
    """Метрики одной проекции; не заменяет проверку других видов и размеров."""
    reference_mask = _as_mask(reference_mask)
    model_mask = render_mask(solids, azim_deg, elev_deg, size, mirror=mirror)
    return _comparison(reference_mask, model_mask)


def report(reference_rgb: np.ndarray, solids, tol: float = 14.0, size: int = 320,
           azim: Sequence[float] | None = None, elev: Sequence[float] | None = None,
           refine: int = 2, mirror: bool = False) -> dict:
    """Паспорт фото, кандидат камеры и явные границы одновидового вывода."""
    mask = mask_by_background(reference_rgb, tol=tol)
    reference = measure(mask)
    renderer = _MaskRenderer(solids, size)
    fitted = _fit_with_renderer(
        mask, renderer, DEFAULT_AZIM if azim is None else azim,
        DEFAULT_ELEV if elev is None else elev, refine, mirror)
    model_mask = renderer.render(fitted["azim_deg"], fitted["elev_deg"], mirror=mirror)
    comparison = _comparison(mask, model_mask)
    return {
        "reference": reference.as_dict(),
        "photo_tilt": camera_elevation(mask),
        "camera": fitted,
        "compare": comparison,
        "provenance": {
            "reference": "measured_from_mask",
            "photo_tilt": "estimated_from_top_arc",
            "camera": "fitted_by_orthographic_silhouette",
            "absolute_scale": "unknown_without_reference_dimension",
            "hidden_geometry": "not_validated",
        },
        "limitations": [
            "Совпадения одного силуэта недостаточно для доказательства правильного объёма.",
            "Ортографическая камера — приближение; перспектива фотографии требует отдельной калибровки.",
            "Абсолютный масштаб и невидимые поверхности без дополнительных данных остаются неизвестными.",
        ],
        "advice": _advice(comparison),
    }


def _advice(result: dict) -> list:
    advice = []
    if abs(result["aspect_err_pct"]) > 6:
        word = "шире" if result["aspect_err_pct"] > 0 else "уже"
        advice.append(("пропорции", f"модель {word} фото на {abs(result['aspect_err_pct']):.0f} % "
                                    f"(ширина/высота {result['aspect_model']:.2f} против "
                                    f"{result['aspect_ref']:.2f})"))
    if result["row_err_px"] > 4:
        advice.append(("профиль", f"медианная ошибка ширины строк {result['row_err_px']:.1f} px "
                                   "в нормированном кадре 256"))
    if abs(result["side_err"]) > 6:
        advice.append(("перекос", "ошибка слева и справа разная: проверьте центры и поворот детали"))
    if result["iou"] < 0.90:
        advice.append(("форма", f"IoU {result['iou']:.2f} < 0.90 — силуэт ещё не совпадает"))
    if not result["passed"] and result["worst_cell"] is not None:
        advice.append(("локальная форма",
                       f"худшая клетка {result['worst_cell']['cell']}: "
                       f"IoU {result['worst_cell']['iou']:.2f}"))
    if result["passed"]:
        advice.append(("силуэт", "пороги пройдены только для этого ракурса; проверьте другие виды "
                                  "и опорные размеры"))
    return advice
