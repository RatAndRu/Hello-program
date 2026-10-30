"""Тесты измерения по фотографии (forma.vision)."""
from __future__ import annotations

import math
import unittest

import numpy as np

from forma.vision.silhouette import (measure, camera_elevation, compare, iou,
                                     mask_by_background)


def rect_mask(w, h, x0=20, y0=20, W=200, H=200):
    m = np.zeros((H, W), dtype=bool)
    m[y0:y0 + h, x0:x0 + w] = True
    return m


def ellipse_mask(a, b, cx=100, cy=100, W=260, H=260):
    yy, xx = np.mgrid[0:H, 0:W]
    return ((xx - cx) / a) ** 2 + ((yy - cy) / b) ** 2 <= 1.0


class SilhouetteTest(unittest.TestCase):
    def test_measure_rectangle(self):
        m = rect_mask(60, 120)
        s = measure(m, profile_rows=4)
        self.assertEqual((s.width, s.height), (60, 120))
        self.assertAlmostEqual(s.fill, 1.0, places=2)
        self.assertLess(s.symmetry_err_pct, 1.0)      # прямоугольник симметричен

    def test_symmetry_flags_asymmetric_part(self):
        """Выступ с одной стороны должен быть замечен: 43 % у нашего референса."""
        m = rect_mask(60, 120)
        m[40:60, 20:110] = True      # «бобышка» справа
        s = measure(m, profile_rows=4)
        self.assertGreater(s.symmetry_err_pct, 8.0)
        self.assertEqual(len(s.width_profile), 4)

    def test_identical_masks_iou_is_one(self):
        m = ellipse_mask(60, 40)
        self.assertAlmostEqual(iou(m, m), 1.0, places=3)
        c = compare(m, m)
        self.assertEqual(c["verdict"], "похоже")
        self.assertLess(c["row_err_px"], 0.5)

    def test_narrower_model_is_rejected(self):
        """Модель на 15 % уже должна провалить проверку, а не «сойти».

        Это главный тест: раньше сравнение нормировало каждый силуэт по своему
        габариту, и модель с любым масштабом давала IoU 0.96.
        """
        ref = ellipse_mask(60, 40)
        thin = ellipse_mask(51, 40)
        c = compare(ref, thin)
        self.assertEqual(c["verdict"], "не похоже")
        self.assertLess(c["aspect_err_pct"], -10.0)

    def test_side_error_finds_missing_boss(self):
        """Пропущенная бобышка с одной стороны — это перекос, а не «ширина».

        Так выглядит наш референс: у фотографии справа есть бобышка с
        отверстием, у модели её нет. Общий IoU падает слабо, асимметрия — резко.
        """
        ref = rect_mask(60, 120)
        ref[40:60, 20:110] = True                  # бобышка справа
        no_boss = rect_mask(60, 120)               # без бобышки
        c = compare(ref, no_boss)
        self.assertEqual(c["verdict"], "не похоже")
        self.assertLess(c["side_err"], -6.0)

    def test_narrow_row_is_seen_as_row_error(self):
        """Срез половины ширины: ширина по строкам должна разойтись сильно."""
        ref = rect_mask(60, 120)
        narrow = rect_mask(30, 120)
        c = compare(ref, narrow)
        self.assertEqual(c["verdict"], "не похоже")
        self.assertGreater(c["row_err_px"], 15.0)

    def test_top_arc_recovers_elevation(self):
        """Наклон камеры по эллипсу верхней кромки: b/a = sin(угла)."""
        for elev in (20.0, 35.0):
            a = 90.0
            b = a * math.sin(math.radians(elev))
            m = np.zeros((320, 260), dtype=bool)
            # «стакан»: верхний эллипс + цилиндрическая стенка вниз
            yy, xx = np.mgrid[0:320, 0:260]
            top = ((xx - 130) / a) ** 2 + ((yy - 100) / b) ** 2 <= 1.0
            tube = (np.abs(xx - 130) <= a) & (yy >= 100) & (yy <= 260)
            m = top | tube
            cam = camera_elevation(m)
            self.assertTrue(cam["ok"], cam)
            self.assertAlmostEqual(cam["elevation_deg"], elev, delta=2.0)

    def test_mask_by_background_on_gradient(self):
        """Фон-градиент (синяя студийная заливка) отделяется от серой детали."""
        H, W = 160, 160
        yy, xx = np.mgrid[0:H, 0:W]
        t = yy / (H - 1)
        bg = np.stack([120 + 40 * t, 175 + 30 * t, 229 + 20 * t], axis=2)
        img = bg.astype(np.uint8)
        img[50:120, 40:100] = (150, 150, 152)      # серая деталь
        m = mask_by_background(img, tol=14)
        self.assertTrue(m[80, 70])
        self.assertFalse(m[10, 10])
        s = measure(m)
        self.assertEqual((s.width, s.height), (60, 70))


class CompareContractTest(unittest.TestCase):
    def test_worst_cell_reports_location(self):
        ref = rect_mask(80, 140, x0=40, y0=20, W=200, H=200)
        broken = ref.copy()
        broken[:80, :] = False                     # верх отрезан
        c = compare(ref, broken)
        self.assertIsNotNone(c["worst_cell"])
        self.assertEqual(c["worst_cell"]["cell"][0], 0)   # верхняя клетка
        self.assertEqual(c["verdict"], "не похоже")


if __name__ == "__main__":
    unittest.main()
