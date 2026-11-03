"""Регрессы визуальной NPR-переработки: материал ≠ освещение ≠ контур.

Сцены намеренно маленькие. Они проверяют не арифметический NoError, а
наблюдаемые свойства рисунка, которые раньше терялись на кубе и лампе.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forma.anime import apply_style  # noqa: E402


def _pixels(values, albedos):
    """Три независимых пикселя без контура: чёрный, светлый в тени, зелёный."""
    img = np.asarray(values, dtype=np.float32).reshape(1, 3, 3)
    albedo = np.asarray(albedos, dtype=np.float32).reshape(1, 3, 3)
    z = np.zeros((1, 3), dtype=np.float32)
    normals = np.tile(np.array([0, 0, 1], dtype=np.float32), (1, 3, 1))
    ids = np.ones((1, 3), dtype=np.int32)
    return img, z, normals, ids, albedo


class MaterialToneTests(unittest.TestCase):
    def test_manga_separates_black_material_from_shadow_and_green(self):
        # Одинаковый beauty-luma у первых двух пикселей — старый порог не мог
        # отличить их. Альбедо даёт недостающий канал информации.
        img, z, nrm, ids, albedo = _pixels(
            [[0.12, 0.12, 0.12], [0.12, 0.12, 0.12], [0.04, 0.24, 0.07]],
            [[0.035, 0.035, 0.035], [0.86, 0.86, 0.86], [0.03, 0.55, 0.12]],
        )
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "манга", "line": 0, "tone": 0.0,
                                 "paper_tex": 0})
        black, shadow, green = out[0, :, :].mean(axis=1)
        self.assertLess(black, shadow - 0.25, out)
        self.assertGreater(shadow, 0.25, out)
        self.assertGreater(green, black + 0.12, out)

    def test_anime_uses_albedo_not_white_specular_holes(self):
        img, z, nrm, ids, albedo = _pixels(
            [[1.0, 1.0, 1.0], [0.75, 0.75, 0.75], [0.03, 0.24, 0.07]],
            [[0.03, 0.55, 0.12], [0.86, 0.86, 0.86], [0.03, 0.55, 0.12]],
        )
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "аниме", "line": 0, "paper_tex": 0})
        green = out[0, 0]
        self.assertGreater(float(green[1]), float(green[0]) * 1.8, out)
        self.assertGreater(float(green[1]), float(green[2]) * 1.8, out)
        self.assertLess(float(green.mean()), 0.90, out)

    def test_sketch_hatches_shadow_not_lit_face(self):
        h = w = 96
        albedo = np.full((h, w, 3), 0.82, dtype=np.float32)
        img = albedo.copy()
        img[:, w // 2:] *= 0.20
        z = np.zeros((h, w), dtype=np.float32)
        nrm = np.tile(np.array([0, 0, 1], dtype=np.float32), (h, w, 1))
        ids = np.ones((h, w), dtype=np.int32)
        common = {"mode": "скетч", "line": 0, "paper_tex": 0,
                  "hatch": 0.9, "hatch_step": 6}
        plain = apply_style(img, z, nrm, ids, albedo=albedo,
                            style={**common, "hatch": 0})
        sketch = apply_style(img, z, nrm, ids, albedo=albedo, style=common)
        diff = np.abs(sketch - plain).mean(axis=2)
        lit = float(diff[:, 8:w // 2 - 8].mean())
        shadow = float(diff[:, w // 2 + 8:-8].mean())
        self.assertGreater(shadow, lit * 2.0 + 0.005, (lit, shadow))


if __name__ == "__main__":
    unittest.main()
