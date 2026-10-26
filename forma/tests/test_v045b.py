"""0.45: рамки с полостями, рельефные кубы и сгибаемый лист."""

from __future__ import annotations

import unittest

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def solid(result, name="о"):
    return result.scene.objects[name].manifold


def size(result, name="о"):
    bb = solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m, point, edge=0.12) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-9)


def one(m):
    assert m.status() == mf.Error.NoError, m.status()
    parts = [p for p in m.decompose() if p.volume() > 1e-6]
    assert len(parts) == 1, len(parts)


class CavityFrameTest(unittest.TestCase):
    def test_l_cavity_has_exact_area_and_one_through_void(self):
        m = solid(ok("о = cavity_frame size=[100,90] depth=8 cavity=Г "
                     "cavity_size=[50,40] line_width=6 margin=8"))
        one(m)
        # Сквозная Г: 50*6 + 40*6 - 6*6; рамка стоит в XZ.
        self.assertAlmostEqual(m.volume(), (100 * 90 - (50 * 6 + 40 * 6 - 36)) * 8,
                               delta=1e-5)
        self.assertEqual(m.genus(), 1)
        np.testing.assert_allclose(size(ok("о = cavity_frame size=[100,90] depth=8")),
                                   [100, 8, 90], atol=1e-6)

    def test_line_is_straight_and_becomes_oval_in_round_frame(self):
        rectangular = solid(ok("о = cavity_frame size=[100,90] depth=8 cavity=линия "
                               "cavity_size=[60,6]"))
        circular = solid(ok("о = cavity_frame outer=круг size=[100,100] depth=8 "
                            "cavity=линия cavity_size=[60,6]"))
        one(rectangular)
        one(circular)
        self.assertAlmostEqual(rectangular.volume(), (100 * 90 - 60 * 6) * 8, delta=1e-5)
        # Прямой овал — капсула: прямоугольник (L-W)*W + два полукруга.
        capsule_area = (60 - 6) * 6 + np.pi * 3 ** 2
        expected_circle = (np.pi * 50 ** 2 - capsule_area) * 8
        self.assertAlmostEqual(circular.volume(), expected_circle, delta=expected_circle * 0.002)
        self.assertGreater(circular.volume(), (np.pi * 50 ** 2 - 60 * 6) * 8)

    def test_round_frame_places_corner_cavity_inside_with_margin(self):
        # Раньше центр по квадратной сетке (40,40) выпадал из R=50.
        for cavity in ("квадрат", "круг"):
            with self.subTest(cavity=cavity):
                m = solid(ok(f"о = cavity_frame outer=круг size=[100,100] depth=8 "
                             f"cavity={cavity} cavity_size=[20,20] margin=10"))
                one(m)
                self.assertEqual(m.genus(), 1)
                np.testing.assert_allclose(size_from_manifold(m), [100, 8, 100], atol=1e-6)

    def test_all_corners_and_edge_rounding_are_real(self):
        base = None
        for corner in ("право_верх", "лево_верх", "право_низ", "лево_низ"):
            with self.subTest(corner=corner):
                m = solid(ok(f"о = cavity_frame outer=круг size=[100,100] depth=8 "
                             f"cavity=круг cavity_size=[20,20] corner={corner} margin=10"))
                one(m)
                if base is None:
                    base = m
                self.assertAlmostEqual(m.volume(), base.volume(), delta=1e-5)
        sharp = solid(ok("о = cavity_frame size=[100,90] depth=8 cavity=квадрат "
                         "cavity_size=[30,30] round=0"))
        rounded = solid(ok("о = cavity_frame size=[100,90] depth=8 cavity=квадрат "
                           "cavity_size=[30,30] round=1.2"))
        one(rounded)
        self.assertNotAlmostEqual(sharp.volume(), rounded.volume(), delta=0.1)
        self.assertGreater(rounded.num_tri(), sharp.num_tri())


class FaceBoxTest(unittest.TestCase):
    def test_convex_and_concave_faces_change_volume_in_opposite_directions(self):
        plain = solid(ok("о = face_box size=[60,50,40]"))
        convex = solid(ok("о = face_box size=[60,50,40] mode=выпуклый relief=4"))
        concave = solid(ok("о = face_box size=[60,50,40] mode=вогнутый relief=4"))
        for m in (plain, convex, concave):
            one(m)
        self.assertAlmostEqual(plain.volume(), 60 * 50 * 40, delta=1e-5)
        self.assertGreater(convex.volume(), plain.volume())
        self.assertLess(concave.volume(), plain.volume())
        np.testing.assert_allclose(size_from_manifold(convex), [68, 58, 48], atol=1e-6)
        np.testing.assert_allclose(size_from_manifold(concave), [60, 50, 40], atol=1e-6)

    def test_lens_trapezoid_and_square_profiles_are_distinct(self):
        volumes = []
        for profile in ("линза", "трапеция", "квадрат"):
            with self.subTest(profile=profile):
                m = solid(ok(f"о = face_box size=[60,50,40] mode=выпуклый "
                             f"profile={profile} relief=5 margin=6"))
                one(m)
                volumes.append(m.volume())
        self.assertGreater(min(volumes), 60 * 50 * 40)
        self.assertEqual(len({round(v, 3) for v in volumes}), 3)

    def test_faces_can_select_only_top_and_lists(self):
        m = solid(ok("о = face_box size=[60,50,40] mode=выпуклый faces=верх relief=4"))
        one(m)
        bb = m.bounding_box()
        np.testing.assert_allclose(size_from_manifold(m), [60, 50, 44], atol=1e-6)
        self.assertAlmostEqual(bb[2], 0.0, delta=1e-6)
        self.assertAlmostEqual(bb[5], 44.0, delta=1e-6)
        multi = solid(ok("о = face_box size=[60,50,40] mode=выпуклый "
                         "faces=[верх,перед] relief=4"))
        one(multi)
        np.testing.assert_allclose(size_from_manifold(multi), [60, 54, 44], atol=1e-6)

    def test_single_corner_is_exact_tetrahedron_at_requested_corner(self):
        cut = 12.0
        m = solid(ok(f"о = face_box size=[80,80,80] corner_cut={cut} "
                     "corners=один corner=перед_право_верх"))
        one(m)
        self.assertAlmostEqual(m.volume(), 80 ** 3 - cut ** 3 / 6, delta=1e-5)
        self.assertFalse(inside(m, (39, -39, 79)))
        self.assertTrue(inside(m, (-39, 39, 79)))
        self.assertTrue(inside(m, (-39, -39, 1)))

    def test_upper_lower_and_all_corner_cuts_have_exact_volumes(self):
        for where, count in (("верх", 4), ("низ", 4), ("все", 8)):
            with self.subTest(where=where):
                m = solid(ok(f"о = face_box size=[80,80,80] corner_cut=12 corners={where}"))
                one(m)
                self.assertAlmostEqual(m.volume(), 80 ** 3 - count * 12 ** 3 / 6, delta=1e-5)
        upper = solid(ok("о = face_box size=[80,80,80] corner_cut=12 corners=верх"))
        self.assertFalse(inside(upper, (39, -39, 79)))
        self.assertTrue(inside(upper, (39, -39, 1)))

    def test_default_is_an_unmodified_rectangular_box(self):
        a = solid(ok("о = face_box size=[60,50,40]"))
        b = solid(ok("о = box size=[60,50,40] round=0"))
        self.assertAlmostEqual(a.volume(), b.volume(), delta=1e-6)
        np.testing.assert_allclose(size_from_manifold(a), size_from_manifold(b), atol=1e-6)


class FoldSheetTest(unittest.TestCase):
    def test_single_fold_is_connected_and_angle_changes_shape(self):
        acute = solid(ok("о = fold_sheet width=120 length=80 thickness=1.2 parts=2 angle=45"))
        nearly_flat = solid(ok("о = fold_sheet width=120 length=80 thickness=1.2 parts=2 angle=1"))
        one(acute)
        one(nearly_flat)
        self.assertNotAlmostEqual(acute.volume(), nearly_flat.volume(), delta=0.01)
        self.assertLess(size_from_manifold(acute)[0], size_from_manifold(nearly_flat)[0])
        self.assertGreater(size_from_manifold(acute)[2], 1.2)

    def test_accordion_has_requested_panel_count_and_stays_one_solid(self):
        m = solid(ok("о = fold_sheet width=120 length=80 thickness=1.2 parts=4 angle=120 gap=0.6"))
        one(m)
        # Чередование направлений даёт складку, а не четыре независимые пластины.
        self.assertGreater(m.num_tri(), 100)
        self.assertGreater(m.volume(), 0.9 * 120 * 80 * 1.2)
        self.assertLess(m.volume(), 1.1 * 120 * 80 * 1.2)

    def test_axis_diagonal_and_explicit_direction_are_not_decorative(self):
        x = solid(ok("о = fold_sheet width=120 length=80 parts=2 axis=x angle=90"))
        y = solid(ok("о = fold_sheet width=120 length=80 parts=2 axis=y angle=90"))
        diagonal = solid(ok("о = fold_sheet width=120 length=80 parts=2 axis=диагональ angle=90"))
        explicit = solid(ok("о = fold_sheet width=120 length=80 parts=2 direction=90 angle=90"))
        for m in (x, y, diagonal, explicit):
            one(m)
        self.assertNotAlmostEqual(x.volume(), y.volume(), delta=0.01)
        self.assertNotAlmostEqual(x.volume(), diagonal.volume(), delta=0.01)
        self.assertAlmostEqual(y.volume(), explicit.volume(), delta=1e-5)

    def test_gap_sharpness_and_offset_change_actual_geometry(self):
        sharp = solid(ok("о = fold_sheet parts=3 angle=120 gap=0 sharp=1"))
        smooth = solid(ok("о = fold_sheet parts=3 angle=120 gap=3 sharp=0"))
        shifted = solid(ok("о = fold_sheet parts=2 angle=90 offset=0.7"))
        centred = solid(ok("о = fold_sheet parts=2 angle=90 offset=0.5"))
        for m in (sharp, smooth, shifted, centred):
            one(m)
        self.assertNotAlmostEqual(sharp.volume(), smooth.volume(), delta=0.01)
        self.assertNotAlmostEqual(shifted.volume(), centred.volume(), delta=0.01)


class BoxHoleTest(unittest.TestCase):
    def test_each_axis_has_an_independent_through_hole(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                m = solid(ok(f"о = box size=[60,50,40] round=0 hole_{axis}=12"))
                one(m)
                self.assertEqual(m.genus(), 1)
                self.assertFalse(inside(m, (0, 0, 20)))
                self.assertTrue(inside(m, (25, 20, 35)))

    def test_all_axes_and_shapes_work_simultaneously(self):
        m = solid(ok("о = box size=[60,50,40] round=0 hole_x=12 hole_x_shape=круг "
                     "hole_y=14 hole_y_shape=квадрат hole_z=20 hole_z_shape=овал oval_aspect=2"))
        one(m)
        self.assertEqual(m.genus(), 5)
        self.assertFalse(inside(m, (0, 0, 20)))
        square = solid(ok("о = box size=[60,50,40] round=0 hole_z=14 hole_z_shape=квадрат"))
        circle = solid(ok("о = box size=[60,50,40] round=0 hole_z=14 hole_z_shape=круг"))
        self.assertLess(square.volume(), circle.volume())

    def test_oval_is_straight_oriented_and_aspect_is_effective(self):
        m = solid(ok("о = box size=[60,50,40] round=0 hole_z=12 hole_z_shape=овал oval_aspect=2"))
        one(m)
        self.assertFalse(inside(m, (5, 0, 20)))
        self.assertTrue(inside(m, (0, 5, 20)))
        circular = solid(ok("о = box size=[60,50,40] round=0 hole_z=12 hole_z_shape=овал oval_aspect=1"))
        self.assertGreater(m.volume(), circular.volume())


class NewGlyphModesTest(unittest.TestCase):
    def test_egg_has_volume_flat_silhouette_and_cookie_cutter(self):
        volume = solid(ok("о = egg height=60 diameter=42"))
        flat = solid(ok("о = egg height=60 diameter=42 flat=да depth=6 plane=плашмя"))
        mold = solid(ok("о = egg height=60 diameter=42 flat=да depth=6 wall=3 plane=плашмя"))
        for m in (volume, flat, mold):
            one(m)
        self.assertEqual(volume.genus(), 0)
        self.assertEqual(flat.genus(), 0)
        self.assertEqual(mold.genus(), 1)
        self.assertAlmostEqual(size_from_manifold(flat)[2], 6.0, delta=1e-6)
        self.assertLess(mold.volume(), flat.volume())

    def test_drop_has_volume_flat_silhouette_and_cookie_cutter(self):
        volume = solid(ok("о = drop radius=14 height=36"))
        flat = solid(ok("о = drop radius=14 height=36 flat=да depth=5 plane=плашмя"))
        mold = solid(ok("о = drop radius=14 height=36 flat=да depth=5 wall=2 plane=плашмя"))
        for m in (volume, flat, mold):
            one(m)
        self.assertEqual(volume.genus(), 0)
        self.assertEqual(flat.genus(), 0)
        self.assertEqual(mold.genus(), 1)
        self.assertAlmostEqual(size_from_manifold(flat)[2], 5.0, delta=1e-6)
        self.assertLess(mold.volume(), flat.volume())

    def test_arrow_wall_makes_real_cookie_cutter(self):
        filled = solid(ok("о = arrow length=120 wall=0 round=0"))
        mold = solid(ok("о = arrow length=120 wall=3 round=0"))
        one(filled)
        one(mold)
        self.assertEqual(filled.genus(), 0)
        self.assertEqual(mold.genus(), 1)
        self.assertLess(mold.volume(), filled.volume())

    def test_saw_accepts_zero_hole(self):
        solid_saw = solid(ok("о = saw diameter=100 teeth=20 hole=0 windows=0"))
        bored = solid(ok("о = saw diameter=100 teeth=20 hole=12 windows=0"))
        one(solid_saw)
        one(bored)
        self.assertEqual(solid_saw.genus(), 0)
        self.assertEqual(bored.genus(), 1)
        self.assertTrue(inside(solid_saw, (0, 0, 50)))
        self.assertFalse(inside(bored, (0, 0, 50)))

    def test_tee_branch_shape_changes_geometry_and_old_widths_still_work(self):
        bars = solid(ok("о = tee arm=90 bar=20 stem=22 leg=60 shape=бруски round=0"))
        capsules = solid(ok("о = tee arm=90 bar=20 stem=22 leg=60 shape=капсулы round=0"))
        wider = solid(ok("о = tee arm=90 bar=26 stem=22 leg=60 shape=бруски round=0"))
        for m in (bars, capsules, wider):
            one(m)
        self.assertLess(capsules.volume(), bars.volume())
        self.assertGreater(wider.volume(), bars.volume())
        self.assertGreater(capsules.num_tri(), bars.num_tri())

    def test_yoke_smoothing_is_actual_geometry(self):
        sharp = solid(ok("о = yoke shape=бруски smooth=0"))
        smooth = solid(ok("о = yoke shape=бруски smooth=1"))
        one(sharp)
        one(smooth)
        self.assertNotAlmostEqual(sharp.volume(), smooth.volume(), delta=0.01)
        self.assertGreater(smooth.num_tri(), sharp.num_tri())


def size_from_manifold(m):
    bb = m.bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


if __name__ == "__main__":
    unittest.main()
