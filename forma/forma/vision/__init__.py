"""Измерение по изображению: силуэт, ракурс, совпадение с фотографией.

Публичный интерфейс:

* :func:`forma.vision.silhouette.measure` — габарит, заполнение, симметрия,
  профили ширины;
* :func:`forma.vision.silhouette.camera_elevation` — наклон камеры по дуге
  верхней кромки;
* :func:`forma.vision.silhouette.compare` — IoU, ошибка строк, пропорции,
  перекос, худшая клетка;
* :func:`forma.vision.fit.fit_camera` — ракурс модели, подобранный рендером;
* :func:`forma.vision.fit.report` — полный отчёт «фото → модель → советы».
"""
from .silhouette import (Silhouette, measure, mask_by_background, mask_from_alpha,
                         camera_elevation, compare, iou)
from .fit import render_mask, fit_camera, compare_model, report

__all__ = ["Silhouette", "measure", "mask_by_background", "mask_from_alpha",
           "camera_elevation", "compare", "iou",
           "render_mask", "fit_camera", "compare_model", "report"]
