"""Подгонка камеры и проверка модели по фотографии (анализ через синтез).

Идея простая и честная: раз у нас есть свой рендерер, не нужно «угадывать»
ракурс фотографии — можно отрендерить модель с десятка ракурсов и сравнить
силуэты. Побеждает ракурс с наибольшим пересечением (IoU). Ошибка подгонки
измеряется в тех же пикселях, что и фотография, поэтому её видно без глаз.

Из этого получаются три вещи, которых не хватает нейросети:

1. **Раккурс.** Вместо догадок «наверное, изометрия» — число: азимут и подъём
   камеры, при которых силуэт модели совпадает с фотографией.
2. **Обратная связь по параметрам.** Для каждой детали модели считается, на
   сколько пикселей её силуэт шире/уже силуэта на фото в той же полосе высоты.
   Пиксели переводятся в миллиметры через масштаб кадра — это и есть «толщина
   не та».
3. **Критерий готовности.** Модель считается похожей, когда IoU ≥ 0.90 и
   медианная ошибка ширины по строкам ≤ 4 px в кадре 256. Тогда остановиться
   можно не «на глаз», а по числу.

Модуль не требует PIL: маска берётся прямо из буфера рендерера.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np

from .silhouette import Silhouette, measure, compare, iou, mask_by_background

__all__ = ["render_mask", "fit_camera", "compare_model", "report"]


# --------------------------------------------------------------------------
def _set_view(azim_deg: float, elev_deg: float) -> str:
    """Добавляет временный ракурс в таблицу рендерера и возвращает его ключ."""
    from .. import render

    key = f"_fit_{azim_deg:.1f}_{elev_deg:.1f}"
    a = math.radians(azim_deg)
    e = math.radians(elev_deg)
    d = (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))
    render.VIEWS[key] = (d, (0.0, 0.0, 1.0))
    return key


def render_mask(solids, azim_deg: float = 45.0, elev_deg: float = 25.0,
                size: int = 320, mirror: bool = False) -> np.ndarray:
    """Маска силуэта модели с заданного ракурса.

    Фон задаётся белым, поэтому маска — «пиксель не белый». Тени и сетка
    отключены: они искажают силуэт.
    """
    from .. import render

    meshes = render._prepare(solids)
    if not meshes:
        raise ValueError("нет объектов для рендера")
    allv = np.concatenate([m["verts"] for m in meshes], axis=0)
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    bbox = [float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2])]
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2
    key = _set_view(azim_deg, elev_deg)
    img, _cam = render._render_view(meshes, center, radius, key, size, 1, bbox,
                                    grid=False, shadow=False, bg=(1.0, 1.0, 1.0))
    arr = np.asarray(img)
    if arr.max() <= 1.0001:
        arr = arr * 255.0
    mask = (255.0 - arr).max(axis=2) > 12.0
    # зеркало по горизонтали: при съёмке «спереди» (−Y) левая сторона мира
    # попадает в правую часть кадра, и без отражения азимуты ищутся неверно
    return mask[:, ::-1] if mirror else mask


def fit_camera(reference_mask: np.ndarray, solids,
               azim: Sequence[float] = (15, 30, 45, 60, 75),
               elev: Sequence[float] = (10, 20, 30, 40),
               size: int = 320, refine: int = 2, mirror: bool = True) -> dict:
    """Ищет ракурс модели, силуэт которого ближе всего к фотографии.

    Сначала грубая сетка по азимуту и подъёму, затем ``refine`` уточняющих
    шагов вокруг лучшей точки (шаг делится вдвое). Возвращает лучший ракурс,
    IoU, таблицу всех замеров и совет, что делать дальше.
    """
    tried = []

    def score(a, e):
        m = render_mask(solids, a, e, size, mirror=mirror)
        v = iou(reference_mask, m)
        tried.append({"azim": float(a), "elev": float(e), "iou": float(v)})
        return v

    best = None
    for a in azim:
        for e in elev:
            v = score(a, e)
            if best is None or v > best[0]:
                best = (v, float(a), float(e))

    step_a = (azim[1] - azim[0]) if len(azim) > 1 else 15.0
    step_e = (elev[1] - elev[0]) if len(elev) > 1 else 10.0
    for _ in range(refine):
        step_a /= 2.0
        step_e /= 2.0
        v0, a0, e0 = best
        improved = True
        while improved:
            improved = False
            for da, de in ((step_a, 0), (-step_a, 0), (0, step_e), (0, -step_e)):
                a, e = a0 + da, e0 + de
                if not (-89 <= e <= 89):
                    continue
                v = score(a, e)
                if v > best[0] + 1e-4:
                    best = (v, a, e)
                    improved = True
                    break
            v0, a0, e0 = best

    v, a, e = best
    tried.sort(key=lambda t: -t["iou"])
    return {
        "azim_deg": a, "elev_deg": e, "iou": v,
        "verdict": "ракурс найден" if v >= 0.85 else
                   "силуэт модели не похож: сначала исправьте форму и пропорции",
        "top": tried[:6],
        "renders": len(tried),
    }


def compare_model(reference_mask: np.ndarray, solids, azim_deg: float, elev_deg: float,
                  size: int = 320, mirror: bool = True) -> dict:
    """Сравнивает модель с фотографией в найденном ракурсе.

    Возвращает IoU, ошибку ширины по строкам и **перекос** (разница ошибок
    слева/справа). Перекос — главный признак «деталь стоит не там»: форма в
    порядке, а центр или поворот сдвинуты.
    """
    m = render_mask(solids, azim_deg, elev_deg, size, mirror=mirror)
    c = compare(reference_mask, m)
    ref = measure(reference_mask)
    got = measure(m)
    c["fill_ref"] = ref.fill
    c["fill_model"] = got.fill
    return c


def report(reference_rgb: np.ndarray, solids, tol: float = 14.0, size: int = 320) -> dict:
    """Полный отчёт «фото → модель»: замер фото, ракурс, сравнение, советы."""
    mask = mask_by_background(reference_rgb, tol=tol)
    ref = measure(mask)
    from .silhouette import camera_elevation
    cam = camera_elevation(mask)
    fit = fit_camera(mask, solids, size=size)
    cmp_ = compare_model(mask, solids, fit["azim_deg"], fit["elev_deg"], size=size)
    return {"reference": ref.as_dict(), "photo_tilt": cam, "camera": fit, "compare": cmp_,
            "advice": _advice(cmp_)}


def _advice(c: dict) -> list:
    out = []
    if abs(c["aspect_err_pct"]) > 6:
        word = "шире" if c["aspect_err_pct"] > 0 else "уже"
        out.append(("пропорции", f"модель {word} фото на {abs(c['aspect_err_pct']):.0f} % "
                                 f"(отношение ширины к высоте {c['aspect_model']:.2f} против "
                                 f"{c['aspect_ref']:.2f}) — правьте радиусы и толщины, "
                                 f"прежде чем ракурс"))
    if abs(c.get("side_err", 0)) > 3:
        out.append(("перекос", "ошибка слева и справа разная — деталь смещена от оси "
                               "или повёрнута; проверьте центры (at=[x,y,z])"))
    if c["iou"] < 0.90:
        out.append(("форма", f"IoU {c['iou']:.2f} < 0.90 — силуэт ещё не тот"))
    if not out:
        out.append(("готово", "IoU ≥ 0.90 и ширина в норме — можно переходить к деталям"))
    return out
