"""0.26: аниме/манга-стиль — контуры по форме, тон, растр и бумага."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from forma.anime import (PRESETS, apply_style, is_active, normalize_mode,
                         normalize_style, style_from_args)
from forma.errors import GeometryError
from forma.render import render_single
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError((result.error or {}).get("message", result.error))
    return result


def fails(script: str) -> str:
    result = build(script, analyze_model=False)
    if result.ok:
        raise AssertionError("ожидалась ошибка")
    return (result.error or {}).get("message", "")


def flat_scene(size: int = 64):
    """Простая «сцена»: полоса слева ближе, справа дальше + нормали."""
    h = w = size
    img = np.full((h, w, 3), 0.6, dtype=np.float32)
    z = np.full((h, w), 100.0, dtype=np.float32)
    z[:, w // 2:] = 120.0
    nrm = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (h, w, 1))
    ids = np.zeros((h, w), dtype=np.int32)
    ids[:, w // 2:] = 1
    return img, z, nrm, ids


class AnimeStyleTests(unittest.TestCase):
    def test_presets_are_complete(self):
        for name in ("аниме", "манга", "комикс", "линия", "выкл"):
            self.assertIn(name, PRESETS)
            st = normalize_style({"mode": name})
            for key in ("mode", "line", "color", "inner", "crease", "depth",
                        "seams", "toon", "tone", "paper", "shade"):
                self.assertIn(key, st, key)
            self.assertEqual(st["mode"], name)

    def test_mode_aliases(self):
        self.assertEqual(normalize_mode("anime"), "аниме")
        self.assertEqual(normalize_mode("manga"), "манга")
        self.assertEqual(normalize_mode("line"), "линия")
        self.assertEqual(normalize_mode("off"), "выкл")
        self.assertNotEqual(normalize_mode("контуры"), "выкл")
        self.assertNotEqual(normalize_mode("обводка"), "выкл")
        # неизвестный стиль — понятная ошибка, а не молчаливая подмена
        with self.assertRaises(GeometryError):
            normalize_mode("что-то")

    def test_ranges(self):
        with self.assertRaises(GeometryError):
            normalize_style({"line": 99})
        with self.assertRaises(GeometryError):
            normalize_style({"crease": 0})
        with self.assertRaises(GeometryError):
            normalize_style({"depth": 2})
        with self.assertRaises(GeometryError):
            normalize_style({"toon": 12})
        with self.assertRaises(GeometryError):
            normalize_style({"tone": 3})

    def test_off_style(self):
        st = normalize_style({})
        self.assertEqual(st["mode"], "выкл")
        self.assertFalse(is_active(st))
        self.assertTrue(is_active({"mode": "аниме"}))
        self.assertFalse(is_active(None))

    def test_command(self):
        result = ok("ан = anime mode=манга line=2.4 crease=40 tone=0.5\n"
                    "ш = sphere radius=20")
        style = result.scene.settings["anime"]
        self.assertEqual(style["mode"], "манга")
        self.assertAlmostEqual(style["line"], 2.4)
        self.assertAlmostEqual(style["crease"], 40.0)
        self.assertAlmostEqual(style["tone"], 0.5)

    def test_command_aliases_and_off(self):
        result = ok("ш = sphere radius=20\nконтуры режим=аниме")
        self.assertEqual(result.scene.settings["anime"]["mode"], "аниме")
        off = ok("ш = sphere radius=20\nanime off=да")
        self.assertEqual(off.scene.settings["anime"]["mode"], "выкл")
        # выключенный стиль не оставляет «бумаги» — снимок остаётся обычным
        self.assertIsNone(off.scene.settings["anime"]["paper"])

    def test_command_bad_value(self):
        self.assertIn("0 до 12", fails("ш = sphere radius=10\nanime line=40"))

    def test_style_from_args_keeps_mode(self):
        class Args:
            def text(self, name):
                return {"mode": "manga", "off": None, "color": None, "paper": None}[name]

            def has(self, name):
                return name in ("line",)

            def num(self, name, default=None):
                return 3.5

            def boolean(self, name, default=None):
                return default

        st = style_from_args(Args())
        self.assertEqual(st["mode"], "манга")
        self.assertAlmostEqual(st["line"], 3.5)


class AnimeRenderTests(unittest.TestCase):
    def test_offscreen_frame_unchanged_when_off(self):
        img, z, nrm, ids = flat_scene()
        out = apply_style(img, z, nrm, ids, None, {"mode": "выкл"})
        self.assertTrue(np.array_equal(out, img))

    def test_edges_drawn_on_depth_jump(self):
        img, z, nrm, ids = flat_scene()
        out = apply_style(img, z, nrm, ids, None,
                          {"mode": "аниме", "toon": 0, "line": 3})
        band = out[:, 30:34, :]
        self.assertLess(float(band.mean()), 0.2)        # на стыке — чёрная линия
        self.assertGreater(float(out[:, 5:15, :].mean()), 0.4)  # остальное светлое

    def test_seams_drawn_on_object_border(self):
        img, z, nrm, ids = flat_scene()
        out = apply_style(img, z, nrm, ids, None,
                          {"mode": "аниме", "toon": 0, "line": 2, "seams": True})
        self.assertLess(float(out[:, 30:34, :].mean()), 0.2)
        solo = apply_style(img, z, nrm, np.zeros_like(ids), None,
                           {"mode": "аниме", "toon": 0, "line": 2, "seams": False})
        # без стыков линия остаётся (перепад глубины), но чуть тоньше/светлее
        self.assertLessEqual(float(solo.mean()), float(out.mean()) + 1e-6)

    def test_crease_needs_inner(self):
        img, z, nrm, ids = flat_scene()
        nrm2 = nrm.copy()
        nrm2[:, 40:] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        with_inner = apply_style(img, z, nrm2, ids, None,
                                 {"mode": "аниме", "toon": 0, "line": 2,
                                  "inner": True, "depth": 0.6, "seams": False})
        without = apply_style(img, z, nrm2, ids, None,
                              {"mode": "аниме", "toon": 0, "line": 2,
                               "inner": False, "depth": 0.6, "seams": False})
        self.assertLess(float(with_inner[:, 38:42, :].mean()),
                        float(without[:, 38:42, :].mean()) - 0.05)

    def test_manga_is_gray_and_has_dots(self):
        img, z, nrm, ids = flat_scene(96)
        # мягкое затенение слева направо: в тенях должен появиться растр
        ramp = np.linspace(0.25, 0.95, 96, dtype=np.float32)
        img = img * ramp[None, :, None]
        out = apply_style(img, z, nrm, ids, None,
                          {"mode": "манга", "tone": 0.9})
        body = out[10:50, 10:50, :]
        spread = float(np.abs(body - body.mean(axis=2, keepdims=True)).mean())
        self.assertLess(spread, 0.02)                    # без цвета
        self.assertGreater(float(body.std()), 0.01)      # растр виден

    def test_line_mode_has_no_shading(self):
        img, z, nrm, ids = flat_scene()
        img[:] = np.array([0.35, 0.5, 0.8], dtype=np.float32)
        out = apply_style(img, z, nrm, ids, None, {"mode": "линия"})
        inner = out[5:25, 5:25, :]
        self.assertGreater(float(inner.mean()), 0.9)     # тело стало бумагой

    def test_paper_fills_background(self):
        img, z, nrm, ids = flat_scene()
        z[:8, :] = np.nan
        out = apply_style(img, z, nrm, ids, None,
                          {"mode": "манга", "paper": "#ffeecc"})
        r, g, b = out[2, 2]
        self.assertGreater(float(r), 0.9)
        self.assertGreater(float(r), float(b))

    def test_emissive_not_inked(self):
        img, z, nrm, ids = flat_scene()
        glow = np.zeros(z.shape, dtype=bool)
        glow[40:50, 40:50] = True
        out = apply_style(img, z, nrm, ids, glow,
                          {"mode": "манга", "tone": 0.0, "line": 2})
        self.assertGreater(float(out[44:47, 44:47, :].mean()), 0.9)


class AnimeRenderFileTests(unittest.TestCase):
    def _render(self, style) -> np.ndarray:
        result = ok("ваза = lathe points=[[0,0],[20,0],[30,25],[12,50],[0,50]]\n"
                    "куб = box size=[40,40,40] at=[55,0,20]")
        with tempfile.TemporaryDirectory() as tmp:
            path = render_single(result.visible_solids(), tmp,
                                 filename="view.png", size=220, ss=2, style=style)
            from forma.geometry import read_png_gray
            return read_png_gray(path)

    def test_render_changes_picture(self):
        plain = self._render(None)
        anime = self._render(normalize_style({"mode": "аниме"}))
        self.assertEqual(plain.shape, anime.shape)
        self.assertGreater(float(np.abs(plain - anime).mean()), 0.02)

    def test_line_mode_render_is_light(self):
        line = self._render(normalize_style({"mode": "линия"}))
        # почти вся площадь — бумага, тёмных пикселей немного
        self.assertLess(float((line < 0.35).mean()), 0.22)
        self.assertGreater(float(line.mean()), 0.75)

    def test_manga_render_is_contrasty(self):
        manga = self._render(normalize_style({"mode": "манга"}))
        self.assertGreater(float(manga.std()), 0.12)


class AnimeRegistryTests(unittest.TestCase):
    def test_op_registered(self):
        import forma.run  # noqa: F401 — реестр наполняется при импорте
        from forma.ops import OPS
        self.assertIn("anime", OPS)
        self.assertIn("аниме", OPS["anime"].aliases)
        self.assertGreaterEqual(len(OPS), 144)


if __name__ == "__main__":
    unittest.main()
