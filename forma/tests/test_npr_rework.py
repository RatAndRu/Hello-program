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
from forma.geometry import color_to_float_rgb  # noqa: E402


def _pixels(values, albedos, normals=None):
    """Независимые пиксели без контура с явными beauty и albedo."""
    img = np.asarray(values, dtype=np.float32).reshape(1, -1, 3)
    albedo = np.asarray(albedos, dtype=np.float32).reshape(1, -1, 3)
    if img.shape != albedo.shape:
        raise ValueError("values/albedos должны иметь одинаковый размер")
    count = img.shape[1]
    z = np.zeros((1, count), dtype=np.float32)
    nrm = (np.tile(np.array([0, 0, 1], dtype=np.float32), (1, count, 1))
           if normals is None else np.asarray(normals, dtype=np.float32).reshape(1, count, 3))
    ids = np.ones((1, count), dtype=np.int32)
    return img, z, nrm, ids, albedo


def _paper_luma(hex_color="#fbfbf7"):
    return float(np.dot(color_to_float_rgb(hex_color), [0.299, 0.587, 0.114]))


class MaterialToneTests(unittest.TestCase):
    def test_manga_distinguishes_all_material_light_quadrants(self):
        # Тёмный на свету, тёмный в тени, светлый в тени, светлый на свету.
        # Первые два beauty-пикселя раньше схлопывались materialBlack в один
        # сплошной чёрный; светлый в тени нельзя путать с чёрным материалом.
        img, z, nrm, ids, albedo = _pixels(
            [[0.12, 0.12, 0.12], [0.025, 0.025, 0.025],
             [0.12, 0.12, 0.12], [0.86, 0.86, 0.86]],
            [[0.035, 0.035, 0.035], [0.035, 0.035, 0.035],
             [0.86, 0.86, 0.86], [0.86, 0.86, 0.86]],
        )
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "манга", "line": 0, "tone": 0.0,
                                 "paper_tex": 0})
        dark_lit, dark_shadow, light_shadow, light_lit = out[0].mean(axis=1)
        self.assertGreater(dark_lit, dark_shadow + 0.12, out)
        self.assertGreater(light_shadow, dark_shadow + 0.20, out)
        self.assertGreater(light_lit, light_shadow + 0.12, out)
        self.assertLess(dark_lit, light_shadow - 0.12, out)

    def test_manga_separates_black_material_from_shadow_and_green(self):
        # Насыщенный зелёный не является spot black даже при низкой luma.
        img, z, nrm, ids, albedo = _pixels(
            [[0.025, 0.025, 0.025], [0.12, 0.12, 0.12], [0.04, 0.24, 0.07]],
            [[0.035, 0.035, 0.035], [0.86, 0.86, 0.86], [0.03, 0.55, 0.12]],
        )
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "манга", "line": 0, "tone": 0.0,
                                 "paper_tex": 0})
        black_shadow, shadow, green = out[0].mean(axis=1)
        self.assertLess(black_shadow, shadow - 0.25, out)
        self.assertGreater(shadow, 0.25, out)
        self.assertGreater(green, black_shadow + 0.12, out)

    def test_manga_uniform_background_is_clean_paper(self):
        # Равномерно освещённый пол может быть темнее бумаги, но это не тень.
        # Старый paper-minus-beauty порог покрывал такой фон точками целиком.
        h = w = 64
        img = np.full((h, w, 3), 0.82, dtype=np.float32)
        z = np.full((h, w), np.nan, dtype=np.float32)
        nrm = np.zeros((h, w, 3), dtype=np.float32)
        ids = np.zeros((h, w), dtype=np.int32)
        albedo = np.zeros_like(img)
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "манга", "line": 0, "tone": 0.75,
                                 "paper_tex": 0})
        expected = _paper_luma()
        self.assertLess(abs(float(out.mean()) - expected), 0.015, out.mean())
        self.assertLess(float(out.std()), 0.015, out.std())

    def test_manga_keeps_only_local_contact_shadow_on_paper(self):
        h = w = 81
        paper = np.asarray(color_to_float_rgb("#fbfbf7"), dtype=np.float32)
        img = np.tile(paper, (h, w, 1)).astype(np.float32)
        img[33:49, 33:49] *= 0.35
        z = np.full((h, w), np.nan, dtype=np.float32)
        nrm = np.zeros((h, w, 3), dtype=np.float32)
        ids = np.zeros((h, w), dtype=np.int32)
        albedo = np.zeros_like(img)
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "манга", "line": 0, "tone": 0.75,
                                 "paper_tex": 0})
        center = float(out[36:46, 36:46].mean())
        outside = float(out[:20, :20].mean())
        self.assertLess(center, outside - 0.03, (center, outside))
        self.assertLess(abs(outside - _paper_luma()), 0.015, outside)

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

    def test_anime_specular_does_not_change_flat_cel_color(self):
        # Одна нормаль и один материал: разный PBR/specular не должен создавать
        # ложный градиент и дополнительные цветовые ступени в 2D anime.
        img, z, nrm, ids, albedo = _pixels(
            [[0.20, 0.42, 0.24], [0.80, 0.90, 0.82], [1.0, 1.0, 1.0]],
            [[0.03, 0.55, 0.12]] * 3,
        )
        out = apply_style(img, z, nrm, ids, albedo=albedo,
                          style={"mode": "аниме", "line": 0, "paper_tex": 0,
                                 "toon": 3}, light_dir=[0, 0, 1])
        self.assertLess(float(np.max(np.abs(out[0, 0] - out[0, 1]))), 1e-6, out)
        self.assertLess(float(np.max(np.abs(out[0, 0] - out[0, 2]))), 1e-6, out)

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

    def test_sketch_strokes_follow_surface_form(self):
        h = w = 96
        albedo = np.full((h, w, 3), 0.82, dtype=np.float32)
        img = albedo * 0.20
        z = np.zeros((h, w), dtype=np.float32)
        flat = np.tile(np.array([0, 0, 1], dtype=np.float32), (h, w, 1))
        curved = flat.copy()
        curved[:, :, 0] = np.linspace(-0.65, 0.65, w, dtype=np.float32)[None, :]
        curved[:, :, 1] = np.linspace(0.35, -0.35, h, dtype=np.float32)[:, None]
        curved /= np.linalg.norm(curved, axis=2, keepdims=True)
        ids = np.ones((h, w), dtype=np.int32)
        style = {"mode": "скетч", "line": 0, "paper_tex": 0,
                 "hatch": 0.9, "hatch_step": 6}
        a = apply_style(img, z, flat, ids, albedo=albedo, style=style)
        b = apply_style(img, z, curved, ids, albedo=albedo, style=style)
        self.assertGreater(float(np.abs(a - b).mean()), 0.005, np.abs(a - b).mean())


if __name__ == "__main__":
    unittest.main()
