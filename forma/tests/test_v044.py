"""0.44: полосы, сквозные решётки, шипы, колонны и дуговые профили."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401
from forma.ops import lookup
from forma.ops_kit import _path_length, _simple_pipe_path
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def ok(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def solid(result, name="о"):
    return result.scene.objects[name].manifold


def size(result, name="о"):
    bb = solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m, point, edge=0.16) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-8)


class RegistryTest(unittest.TestCase):
    def test_only_requested_profile_returns(self):
        for op in ("strip", "grating", "spikes", "column", "arc_prism", "profile2020"):
            with self.subTest(op=op):
                self.assertIsNotNone(lookup(op))
        for op in ("rail", "bearing", "hinge", "caster", "rack", "coupling",
                   "heatsink", "leg", "форма_п", "форма_у"):
            with self.subTest(removed=op):
                self.assertIsNone(lookup(op))

    def test_cards_and_orientation_notes_exist(self):
        text = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        notes = (ROOT / "forma/orient_notes.py").read_text(encoding="utf-8")
        for op in ("strip", "grating", "column", "arc_prism", "profile2020"):
            with self.subTest(op=op):
                self.assertIn(f"op: '{op}'", text)
                self.assertIn(f'"{op}"', notes)
        # spikes теперь инструмент над объектом, а не примитив: карточка есть,
        # записи в перечне исходных ориентаций примитивов быть не должно.
        self.assertIn("op: 'spikes'", text)
        self.assertNotIn("op: 'leg'", text)


class StripTest(unittest.TestCase):
    def test_all_ends_and_paths_are_one_volume(self):
        for ends in ("прямоугольные", "треугольные", "овальные"):
            for path in ("прямая", "S", "зигзаг"):
                with self.subTest(ends=ends, path=path):
                    b = ok(f"о = strip ends={ends} path={path} curve=35 thickness=4")
                    self.assertEqual(len(solid(b).decompose()), 1)
                    self.assertGreater(solid(b).volume(), 100.0)
                    self.assertAlmostEqual(solid(b).bounding_box()[2], 0.0, places=5)

    def test_left_and_right_collapse_are_independent(self):
        left = ok("о = strip collapse_left=0.8 collapse_right=0 thickness=4 width=40")
        right = ok("о = strip collapse_left=0 collapse_right=0.8 thickness=4 width=40")
        self.assertAlmostEqual(solid(left).volume(), solid(right).volume(), delta=1.0)
        # Верхняя точка у +Y исчезает только при схлопывании левой кромки.
        self.assertFalse(inside(solid(left), (0, 18, 3.6)))
        self.assertTrue(inside(solid(right), (0, 18, 3.6)))
        self.assertTrue(inside(solid(left), (0, -18, 3.6)))
        self.assertFalse(inside(solid(right), (0, -18, 3.6)))

    def test_four_recesses_are_through_holes(self):
        for shape in ("круг", "прямоугольник", "квадрат", "треугольник"):
            with self.subTest(shape=shape):
                b = ok(f"о = strip recess={shape} recess_size=16 thickness=4")
                self.assertFalse(inside(solid(b), (0, 0, 2)))
                self.assertTrue(inside(solid(b), (0, 17, 2)))
                self.assertEqual(len(solid(b).decompose()), 1)

    def test_bend_and_smoothing_keep_body(self):
        flat = ok("о = strip thickness=4")
        bent = ok("о = strip thickness=4 bend=75 smooth=1")
        self.assertEqual(len(solid(bent).decompose()), 1)
        self.assertGreater(size(bent)[2], 30.0)
        self.assertAlmostEqual(solid(bent).volume(), solid(flat).volume(),
                               delta=solid(flat).volume() * 0.08)


class GratingTest(unittest.TestCase):
    def test_every_pattern_has_real_through_openings(self):
        probes = {
            "планки": (-94 + (188 - 7 * 3) / 8 / 2, 0),
            "клетка": (-94 + (188 - 4 * 3) / 5 / 2,
                       -54 + (108 - 3 * 3) / 4 / 2),
            "соты": (-94 + 22 / math.sqrt(3), -54 + 22 / math.sqrt(3)),
        }
        for pattern, (x, y) in probes.items():
            with self.subTest(pattern=pattern):
                b = ok(f"о = grating pattern={pattern} width=200 height=120 depth=4 "
                       "bar=3 frame=6 cell=22")
                m = solid(b)
                self.assertEqual(len(m.decompose()), 1)
                self.assertFalse(inside(m, (x, y, 2)), "ячейка должна быть пустой по всей толщине")
                self.assertTrue(inside(m, (-97, 0, 2)), "рамка должна остаться материалом")
                self.assertGreater(b.scene.objects["о"].meta["openings"], 0)

    def test_bar_and_frame_change_material_volume(self):
        thin = ok("о = grating pattern=клетка bar=2 frame=4")
        thick = ok("о = grating pattern=клетка bar=5 frame=8")
        self.assertGreater(solid(thick).volume(), solid(thin).volume())
        self.assertEqual(len(solid(thick).decompose()), 1)


class SpikesTest(unittest.TestCase):
    def test_array_is_connected_and_dimensions_are_true(self):
        b = ok("о = box size=[120,80,4] round=0\n"
               "о = spikes [о] surface=верх cols=4 rows=3 height=28 base_d=12 tip_d=0.8")
        self.assertEqual(len(solid(b).decompose()), 1)
        self.assertEqual(b.scene.objects["о"].meta["spikes"], 12)
        np.testing.assert_allclose(size(b), (120, 80, 32), atol=1e-5)

    def test_tip_sides_and_lean_change_shape(self):
        pointed = ok("о = box size=[120,80,4] round=0\n"
                         "о = spikes [о] surface=верх tip_d=0 sides=3 lean=0")
        blunt = ok("о = box size=[120,80,4] round=0\n"
                       "о = spikes [о] surface=верх tip_d=5 sides=24 lean=0")
        leaned = ok("о = box size=[120,80,4] round=0\n"
                        "о = spikes [о] surface=верх tip_d=0.8 sides=12 lean=20 direction=90")
        self.assertLess(solid(pointed).volume(), solid(blunt).volume())
        self.assertGreater(size(leaned)[1], 80.0)
        self.assertEqual(len(solid(leaned).decompose()), 1)


class ColumnTest(unittest.TestCase):
    def _middle_width(self, b):
        # Стержень идёт от площадки z=12 до бортика z=170: его середина 91.
        slab = mf.Manifold.cube((200, 200, 0.2), True).translate((0, 0, 91))
        section = solid(b) ^ slab
        bb = section.bounding_box()
        return bb[3] - bb[0]

    def test_three_forms_have_real_middle_profile(self):
        even = ok("о = column form=ровная height=180 width=42")
        hour = ok("о = column form=песочные height=180 width=42 waist=0.55")
        taper = ok("о = column form=конус height=180 width=42 taper=0.5")
        self.assertAlmostEqual(self._middle_width(even), 42, delta=0.05)
        self.assertAlmostEqual(self._middle_width(hour), 42 * 0.55, delta=0.05)
        self.assertAlmostEqual(self._middle_width(taper), 42 * 0.75, delta=0.05)
        for b in (even, hour, taper):
            self.assertEqual(len(solid(b).decompose()), 1)
            self.assertAlmostEqual(size(b)[2], 180.0, delta=1e-5)
            self.assertAlmostEqual(size(b)[0], 72.0, delta=1e-5)

    def test_square_section_optional_plates_and_smoothing(self):
        b = ok("о = column section=брусок width=40 depth=26 base_size=0 rim=0 "
               "form=ровная height=100 smooth=1")
        self.assertEqual(len(solid(b).decompose()), 1)
        self.assertAlmostEqual(size(b)[2], 100.0, delta=1e-4)
        self.assertLess(size(b)[0], 41.0)
        self.assertLess(size(b)[1], 35.0)


class ArcPrismTest(unittest.TestCase):
    def test_zero_arcs_match_regular_triangular_prism(self):
        curved = ok("о = arc_prism a=100 b=90 c=90 height=120 arc_a=0 arc_b=0 arc_c=0")
        regular = ok("о = tri_prism a=100 b=90 c=90 height=120")
        self.assertAlmostEqual(solid(curved).volume(), solid(regular).volume(), delta=0.01)

    def test_each_side_is_independently_convex_or_concave(self):
        base = solid(ok("о = arc_prism arc_a=0 arc_b=0 arc_c=0")).volume()
        for key in ("arc_a", "arc_b", "arc_c"):
            with self.subTest(key=key):
                values = {"arc_a": 0, "arc_b": 0, "arc_c": 0}
                values[key] = 10
                script_p = "о = arc_prism " + " ".join(f"{k}={v}" for k, v in values.items())
                values[key] = -10
                script_n = "о = arc_prism " + " ".join(f"{k}={v}" for k, v in values.items())
                self.assertGreater(solid(ok(script_p)).volume(), base)
                self.assertLess(solid(ok(script_n)).volume(), base)

    def test_tent_combination_is_one_body(self):
        b = ok("о = arc_prism arc_a=0 arc_b=-16 arc_c=-16")
        self.assertEqual(len(solid(b).decompose()), 1)
        self.assertAlmostEqual(size(b)[2], 120.0, places=5)


class Profile2020Test(unittest.TestCase):
    def test_all_grooves_and_rails_keep_four_open_channels(self):
        for groove in ("прямоугольная", "треугольная", "овальная"):
            for rail in ("прямая", "скруглённая", "фаска"):
                with self.subTest(groove=groove, rail=rail):
                    b = ok(f"о = profile2020 length=80 groove={groove} rail={rail}")
                    m = solid(b)
                    self.assertEqual(len(m.decompose()), 1)
                    for point in ((9.5, 0, 40), (-9.5, 0, 40),
                                  (0, 9.5, 40), (0, -9.5, 40)):
                        self.assertFalse(inside(m, point))
                    self.assertFalse(inside(m, (0, 0, 40)))
                    self.assertTrue(inside(m, (3.2, 0, 40)))

    def test_axial_hole_shapes_are_distinct_and_through(self):
        volumes = {}
        for shape in ("круг", "квадрат", "треугольник", "шестигранник"):
            with self.subTest(shape=shape):
                b = ok(f"о = profile2020 length=60 bore=5 bore_shape={shape}")
                volumes[shape] = solid(b).volume()
                self.assertFalse(inside(solid(b), (0, 0, 30)))
                self.assertEqual(len(solid(b).decompose()), 1)
        self.assertEqual(len({round(v, 3) for v in volumes.values()}), 4)
        solid_bore = ok("о = profile2020 length=60 bore=0")
        self.assertTrue(inside(solid(solid_bore), (0, 0, 30)))


class PipeTest(unittest.TestCase):
    def test_simple_and_legacy_modes_are_compatible(self):
        simple = ok("о = pipe length=180 diameter=24 wall=2")
        legacy = ok("о = pipe path=[[0,0,0],[0,0,100],[80,0,100]] diameter=20 wall=2")
        self.assertEqual(simple.scene.objects["о"].meta["path_mode"], "simple")
        self.assertEqual(legacy.scene.objects["о"].meta["path_mode"], "legacy")
        self.assertEqual(len(solid(simple).decompose()), 1)
        self.assertEqual(len(solid(legacy).decompose()), 1)

    def test_smooth_bends_cover_signed_angles_up_to_180(self):
        for angle in (15, 45, 90, 135, -90, 180):
            with self.subTest(angle=angle):
                b = ok(f"о = pipe length=400 angle={angle} radius=70 "
                       "diameter=20 wall=2 joint=плавный")
                self.assertEqual(len(solid(b).decompose()), 1)
                pts = _simple_pipe_path(400, angle, 70, "плавный", 20)
                self.assertAlmostEqual(_path_length(pts), 400.0, delta=2.0)
                tangent = pts[-1] - pts[-2]
                measured = math.degrees(math.atan2(tangent[2], tangent[0]))
                self.assertAlmostEqual(measured, angle, delta=0.2)

    def test_sharp_and_smooth_joints_are_different(self):
        sharp = ok("о = pipe length=180 angle=60 joint=острый diameter=20 wall=1.5")
        smooth = ok("о = pipe length=180 angle=60 radius=50 joint=плавный diameter=20 wall=1.5")
        self.assertEqual(len(solid(sharp).decompose()), 1)
        self.assertNotAlmostEqual(solid(sharp).volume(), solid(smooth).volume(), delta=1.0)
        self.assertEqual(sharp.scene.objects["о"].meta["joint"], "острый")
        self.assertEqual(smooth.scene.objects["о"].meta["joint"], "плавный")


class RevisedSolidsTest(unittest.TestCase):
    def test_disc_and_oval_curvature_is_real(self):
        for op, dims in (("disc", "diameter=100"), ("oval", "width=160 length=100")):
            with self.subTest(op=op):
                flat = ok(f"о = {op} {dims} thickness=6 top=плоская")
                concave = ok(f"о = {op} {dims} thickness=6 top=вогнутая sag=3")
                convex = ok(f"о = {op} {dims} thickness=6 top=выпуклая sag=3")
                self.assertLess(solid(concave).volume(), solid(flat).volume())
                self.assertGreater(solid(convex).volume(), solid(flat).volume())
                self.assertAlmostEqual(size(concave)[2], 6.0, places=5)
                self.assertAlmostEqual(size(convex)[2], 9.0, places=5)
                self.assertFalse(inside(solid(concave), (0, 0, 4.5)))
                self.assertTrue(inside(solid(convex), (0, 0, 7.5)))

    def test_cube_hole_three_shapes_and_axes(self):
        volumes = []
        for shape in ("круг", "квадрат", "треугольник"):
            for axis in ("x", "y", "z"):
                with self.subTest(shape=shape, axis=axis):
                    b = ok(f"о = cube_hole size=[40,40,40] hole=16 hole_shape={shape} axis={axis}")
                    self.assertFalse(inside(solid(b), (0, 0, 20)))
                    self.assertTrue(inside(solid(b), (17, 17, 20)))
                    self.assertEqual(len(solid(b).decompose()), 1)
                    volumes.append(solid(b).volume())
        # Поворот не меняет объём одной и той же формы; разные формы различимы.
        self.assertAlmostEqual(volumes[0], volumes[1], delta=0.01)
        self.assertAlmostEqual(volumes[0], volumes[2], delta=0.01)
        self.assertEqual(len({round(volumes[i], 2) for i in (0, 3, 6)}), 3)


if __name__ == "__main__":
    unittest.main()
