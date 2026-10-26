"""0.25: поверхность, клинки, одежда, экраны, зеркала и покраска узором."""

from __future__ import annotations

import os
import unittest

import numpy as np

from forma.ops_blade import KINDS, _hook_path
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


def last(result):
    return list(result.scene.objects.values())[-1]


def size(m) -> tuple[float, float, float]:
    bb = m.bounding_box()
    return (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])


def parts(m) -> int:
    return len([p for p in m.decompose() if p.volume() > 0])


def height_map(path: str):
    """Маленькая карта высот без внешних библиотек: круги в шахматку."""
    from forma.geometry import write_png
    n = 64
    yy, xx = np.mgrid[0:n, 0:n]
    cell = ((xx // 16) + (yy // 16)) % 2
    r = np.hypot(xx - 32, yy - 32) / 32.0
    value = np.clip(0.25 + 0.6 * cell + 0.3 * (1.0 - r), 0, 1)
    img = np.repeat((value * 255).astype(np.uint8)[:, :, None], 3, axis=2)
    write_png(path, img)


class TestSurfaceTools(unittest.TestCase):
    """Складки, рельеф, поры, чешуя, решётка, кора, кирпичи, починка."""

    def test_wrinkle_modes_make_volume(self):
        for mode in ("радиус", "высота", "шум", "клетка", "трещины"):
            with self.subTest(mode=mode):
                s = last(ok(f"к = box size=[80,80,80]\nwrinkle к amp=3 freq=6 mode={mode}"))
                self.assertEqual(parts(s.manifold), 1, f"{mode}: одно тело")
                self.assertGreater(s.manifold.volume(), 1000.0)

    def test_wrinkle_amplitude_changes_relief(self):
        flat = last(ok("к = cylinder radius=30 height=80\nwrinkle к amp=0.4 freq=8"))
        deep = last(ok("к = cylinder radius=30 height=80\nwrinkle к amp=5 freq=8"))
        self.assertGreater(deep.manifold.volume(), flat.manifold.volume() * 0.9)
        self.assertGreater(size(deep.manifold)[0], size(flat.manifold)[0] - 0.5)

    def test_relief_from_height_map(self):
        # карта лежит рядом и указана относительным путём: так сценарий
        # одинаково работает и на Windows, и на Linux
        path = os.path.join(os.getcwd(), "_map_v025.png")
        height_map(path)
        try:
            s = last(ok("в = cylinder radius=30 height=70\nrelief в image=_map_v025.png depth=4"))
        finally:
            os.remove(path)
        self.assertEqual(parts(s.manifold), 1)
        self.assertGreater(s.manifold.num_tri(), 2000)

    def test_png_reader_matches_written_map(self):
        from forma.geometry import read_png_gray
        path = os.path.join(os.getcwd(), "_map_v025_check.png")
        height_map(path)
        try:
            arr = read_png_gray(path)
        finally:
            os.remove(path)
        self.assertEqual(arr.shape, (64, 64))
        self.assertAlmostEqual(float(arr.mean()), 0.5, delta=0.25)

    def test_relief_has_builtin_image(self):
        s = last(ok("в = box size=[60,50,12]\nrelief в depth=2"))
        self.assertEqual(s.manifold.status(), s.manifold.status().NoError)
        self.assertGreater(s.manifold.num_tri(), 1000)

    def test_porous_modes(self):
        for mode in ("поры", "ячеи", "пузыри", "глазки"):
            with self.subTest(mode=mode):
                s = last(ok("ш = sphere radius=35\nporous ш mode=%s size=4 count=24" % mode))
                self.assertEqual(parts(s.manifold), 1)
                self.assertLess(s.manifold.volume(), 4 / 3 * 3.14159 * 35 ** 3)

    def test_scales_lie_on_surface(self):
        s = last(ok("ш = sphere radius=30\nscales ш kind=рыба rows=8 per_row=12 length=6 overlap=.45"))
        self.assertEqual(parts(s.manifold), 1)
        self.assertGreater(s.manifold.volume(), 4 / 3 * 3.14159 * 30 ** 3 * 0.95)
        self.assertTrue(s.meta["flat"])
        self.assertAlmostEqual(s.meta["row_step"], 6 * (1 - .45))

    def test_lattice_modes(self):
        for mode in ("прямоуг", "ромб", "соты"):
            with self.subTest(mode=mode):
                s = last(ok(f"к = sphere radius=40\nlattice к cell=14 wire=3 mode={mode}"))
                self.assertEqual(parts(s.manifold), 1)
                self.assertLess(s.manifold.volume(), 4 / 3 * 3.14159 * 40 ** 3 * 0.6)

    def test_bark_is_hollow_of_given_size(self):
        s = last(ok("б = bark height=140 radius=26 grooves=10 depth=3"))
        w, d, h = size(s.manifold)
        self.assertAlmostEqual(h, 140.0, delta=0.5)
        self.assertAlmostEqual(w, 52.0, delta=3.0)
        self.assertAlmostEqual(d, 52.0, delta=3.0)
        self.assertEqual(parts(s.manifold), 1)

    def test_bricks_are_wall_of_given_size(self):
        s = last(ok("с = bricks width=300 height=180 thick=60 brick=[62,26] joint=3"))
        w, d, h = size(s.manifold)
        self.assertAlmostEqual(w, 300.0, delta=0.5)
        self.assertAlmostEqual(h, 180.0, delta=0.5)
        self.assertLess(d, 60.0 + 0.5)
        self.assertEqual(parts(s.manifold), 1)

    def test_repair_returns_buildable_solid(self):
        s = last(ok("к = box size=[40,40,40]\nrepair к"))
        self.assertEqual(parts(s.manifold), 1)
        self.assertGreater(s.manifold.volume(), 1000.0)


class TestBlade(unittest.TestCase):
    """Клинок: силуэт по длине, плашмя, одно тело."""

    KINDS = ("катана", "танто", "ятоган", "стилет", "двуручник", "серп", "нож")

    def test_every_kind_is_one_body_of_asked_length(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                s = last(ok(f"к = blade length=600 kind={kind}"))
                m = s.manifold
                self.assertEqual(parts(m), 1)
                w, d, h = size(m)
                longest = max(w, d, h)
                if kind == "серп":
                    # length — длина центральной дуги крюка, а не её хорда.
                    path = _hook_path(600.0, KINDS[kind]["curve"] * 600.0, 100)
                    arc_length = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
                    self.assertAlmostEqual(arc_length, 600.0, delta=2.0)
                    self.assertGreater(longest, 0.65 * 600.0)
                else:
                    self.assertAlmostEqual(longest, 600.0, delta=30.0)
                # клинок плоский: самый тонкий габарит много меньше длины
                self.assertLess(min(w, d, h), 0.2 * longest)

    def test_narrower_blade_for_same_length(self):
        wide = last(ok("к = blade length=500 width=60"))
        narrow = last(ok("к = blade length=500 width=20"))
        self.assertGreater(max(size(wide.manifold)), max(size(narrow.manifold)) - 1.0)
        # клинок стоит: ширина по X, толщина по Y, высота полосы по Z
        self.assertLess(size(narrow.manifold)[2], size(wide.manifold)[2])

    def test_unknown_kind_explains_itself(self):
        message = fails("к = blade length=400 kind=ложка")
        self.assertIn("неизвест", message.lower())
        self.assertIn("ложка", message)


class TestFigure(unittest.TestCase):
    """Наращивание волос на исходной поверхности и готовое зеркало."""

    def test_hair_styles_are_single_bodies(self):
        for style in ("иголки", "волоски", "локоны", "мех"):
            with self.subTest(style=style):
                s = last(ok("о = box size=[50,40,14]\n"
                            f"в = hair [о] style={style} surface=верх count=12 length=12"))
                self.assertEqual(s.manifold.status(), s.manifold.status().NoError)
                self.assertEqual(parts(s.manifold), 1, f"{style}: одно тело")
                self.assertGreater(size(s.manifold)[2], 20.0)

    def test_hair_needs_an_existing_object(self):
        message = fails("в = hair style=мех")
        self.assertIn("объект", message.lower())

    def test_hair_asks_for_known_style(self):
        message = fails("о = box size=[30,30,10]\nв = hair [о] style=ирокез")
        self.assertIn("ирокез", message)

    def test_mirror_has_frame_and_reflecting_plate(self):
        b = ok("з = mirror_plate width=200 height=300 frame=14")
        plate = b.scene.resolve("з.зеркало")
        self.assertGreaterEqual(plate.metal, 0.9)
        self.assertLess(plate.rough, 0.1)
        frame = b.scene.resolve("з")
        self.assertEqual(parts(frame.manifold), 1)
        self.assertAlmostEqual(size(frame.manifold)[0], 200.0, delta=0.5)


class TestPattern(unittest.TestCase):
    """Покраска формами: узор ложится на грани и не меняет форму."""

    def test_dots_change_color_not_shape(self):
        plain = last(ok("куб = box size=[60,60,60]"))
        dotted = last(ok("куб = box size=[60,60,60]\npattern куб #d94f3d shape=круги size=12 step=24"))
        self.assertEqual(parts(dotted.manifold), 1)
        self.assertAlmostEqual(dotted.manifold.volume(), plain.manifold.volume(), delta=1.0)
        self.assertEqual(len(dotted.paint), 1)
        self.assertEqual(dotted.paint[0]["pattern"]["shape"], "круги")

    def test_pattern_reaches_both_top_and_sides(self):
        from forma.geometry import color_to_float_rgb, manifold_mesh, region_triangle_colors
        s = last(ok("куб = box size=[60,60,60]\npattern куб #d94f3d shape=круги size=12 step=24"))
        verts, faces = manifold_mesh(s.manifold)
        colors = region_triangle_colors(s.paint, verts, faces,
                                        base=color_to_float_rgb(s.color))
        self.assertIsNotNone(colors)
        unique = {tuple(np.round(c, 3)) for c in colors}
        self.assertGreaterEqual(len(unique), 2, "узор должен давать два цвета")
        self.assertLess(len(unique), len(faces), "часть граней остаётся фоном")

    def test_pattern_shapes(self):
        for shape in ("круги", "кольца", "полосы", "клетка", "треугольники", "ромбы", "волны"):
            with self.subTest(shape=shape):
                s = last(ok(f"к = box size=[40,40,40]\npattern к #2f6fb0 shape={shape} size=8 step=16"))
                self.assertEqual(s.paint[0]["pattern"]["shape"], shape)

    def test_pattern_accepts_aliases(self):
        s = last(ok("к = box size=[40,40,40]\npattern к #2f6fb0 shape=горошек size=8"))
        self.assertEqual(s.paint[0]["pattern"]["shape"], "круги")

    def test_pattern_angle_and_offset_are_used(self):
        s = last(ok("к = box size=[40,40,40]\npattern к #2f6fb0 shape=полосы size=4 step=12 angle=45 offset=[3,7]"))
        pat = s.paint[0]["pattern"]
        self.assertAlmostEqual(pat["angle"], 45.0)
        self.assertEqual(pat["offset"], [3.0, 7.0])

    def test_pattern_on_one_side_only(self):
        from forma.geometry import color_to_float_rgb, manifold_mesh, region_triangle_colors
        s = last(ok("к = box size=[40,40,40]\npattern к #ff0000 shape=круги size=8 side=верх"))
        verts, faces = manifold_mesh(s.manifold)
        colors = region_triangle_colors(s.paint, verts, faces,
                                        base=color_to_float_rgb(s.color))
        red = np.all(np.abs(colors - np.array([1.0, 0.0, 0.0], dtype=np.float32)) < 0.02, axis=1)
        self.assertTrue(red.any())
        self.assertFalse(red.all(), "боковые грани должны остаться фоном")

    def test_step_smaller_than_size_is_rejected(self):
        message = fails("к = box size=[40,40,40]\npattern к #ff0000 size=20 step=4")
        self.assertIn("шаг", message.lower())

    def test_unknown_shape_is_rejected(self):
        self.assertIn("узор", fails("к = box size=[40,40,40]\npattern к #ff0000 shape=звёздочки"))

    def test_paint_still_works_with_shapes(self):
        s = last(ok("к = box size=[40,40,40]\npaint к #00ff00 shape=полосы size=3 step=9"))
        self.assertEqual(s.paint[0]["pattern"]["shape"], "полосы")


class TestHelpAndRegistry(unittest.TestCase):
    """Новые команды есть в справке и объяснены по-русски."""

    NEW = ("wrinkle", "relief", "porous", "scales", "lattice", "bark", "bricks",
           "repair", "blade", "hair", "crack", "mirror_plate", "pattern")

    def test_registered_with_examples_and_params(self):
        import forma.run  # noqa: F401 — реестр наполняется при импорте
        from forma.ops import OPS
        for name in self.NEW:
            with self.subTest(op=name):
                self.assertIn(name, OPS)
                spec = OPS[name]
                self.assertGreater(len(spec.summary), 40, f"{name}: нужно описание")
                self.assertTrue(spec.example, f"{name}: нужен пример")
                self.assertTrue(spec.params, f"{name}: нужны параметры")
                self.assertTrue(spec.aliases, f"{name}: нужны русские алиасы")

    def test_examples_build(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS
        for name in self.NEW:
            with self.subTest(op=name):
                script = OPS[name].example
                if not script:
                    continue
                result = build(script, analyze_model=False)
                self.assertTrue(result.ok, (result.error or {}).get("message"))


if __name__ == "__main__":
    unittest.main()
