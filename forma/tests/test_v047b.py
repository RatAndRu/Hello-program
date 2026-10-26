"""Дополнение 0.47: детальные вмятины, новые полости, сгибы и пуговица."""

from __future__ import annotations

import math
import unittest

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401
from forma.geometry import manifold_mesh
from forma.ops_sheet import _accordion_path
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def solid(script: str, name: str = "о") -> mf.Manifold:
    return ok(script).scene.objects[name].manifold


def one(m: mf.Manifold):
    assert m.status() == mf.Error.NoError, m.status()
    positive = [p for p in m.decompose() if p.volume() > 1e-6]
    assert len(positive) == 1, [(p.volume(), p.bounding_box()) for p in m.decompose()]
    assert m.volume() > 0


def size(m: mf.Manifold) -> np.ndarray:
    bb = m.bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m: mf.Manifold, point, edge=0.08) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-9)


class DetailedFaceAndCavityTest(unittest.TestCase):
    def test_face_dimple_detail_really_refines_without_changing_bounds(self):
        command = ("о = face_box size=[60,50,40] mode=вогнутый profile=линза "
                   "relief=8 margin=5 faces=верх")
        coarse = solid(command + " detail=0")
        medium = solid(command + " detail=3")
        fine = solid(command + " detail=5")
        for m in (coarse, medium, fine):
            one(m)
            np.testing.assert_allclose(size(m), [60, 50, 40], atol=1e-6)
        self.assertGreater(medium.num_tri(), coarse.num_tri() * 3)
        self.assertGreater(fine.num_tri(), medium.num_tri())
        # Уточнение меняет представление кривой вмятины, а не габарит куба.
        self.assertNotAlmostEqual(coarse.volume(), fine.volume(), places=3)
        self.assertLess(abs(medium.volume() - fine.volume()),
                        abs(coarse.volume() - fine.volume()))

    def test_prism_top_and_bottom_cavities_leave_opposite_bottom(self):
        full = solid("о = prism sides=6 radius=35 height=60")
        top = solid("о = prism sides=6 radius=35 height=60 wall=3 "
                    "cavity=верх cavity_depth=40")
        bottom = solid("о = prism sides=6 radius=35 height=60 wall=3 "
                       "cavity=низ cavity_depth=40")
        for m in (top, bottom):
            one(m)
            self.assertLess(m.volume(), full.volume())
            np.testing.assert_allclose(size(m), size(full), atol=1e-6)
        self.assertTrue(inside(top, (0, 0, 10)))
        self.assertFalse(inside(top, (0, 0, 30)))
        self.assertFalse(inside(bottom, (0, 0, 30)))
        self.assertTrue(inside(bottom, (0, 0, 50)))

    def test_custom_prism_cavity_follows_taper_shift_and_twist(self):
        base = ("о = prism sides=5 radius=35 r2=25 height=60 top_offset=[8,4] "
                "top_scale=[1.1,.9] twist=20")
        full = solid(base)
        hollow = solid(base + " wall=3 cavity_depth=45")
        one(hollow)
        self.assertLess(hollow.volume(), full.volume())
        np.testing.assert_allclose(size(hollow), size(full), atol=1e-6)
        # Центр полости на z=30 смещён вместе с верхним контуром.
        self.assertFalse(inside(hollow, (4, 2, 30)))
        self.assertTrue(inside(hollow, (2, 1, 7)))


class PipeFoldAndStripTest(unittest.TestCase):
    def test_pipe_can_be_a_solid_rod_straight_and_bent(self):
        for tail, point in (("length=80", (0, 0, 10)),
                            ("length=100 angle=75 radius=45", None)):
            with self.subTest(tail=tail):
                hollow = solid(f"о = pipe diameter=20 wall=2 {tail}")
                filled = solid(f"о = pipe diameter=20 wall=2 hole=нет {tail}")
                one(filled)
                self.assertGreater(filled.volume(), hollow.volume() * 1.15)
                np.testing.assert_allclose(size(filled), size(hollow), atol=1e-6)
                if point is not None:
                    self.assertFalse(inside(hollow, point))
                    self.assertTrue(inside(filled, point))

    def test_sharp_round_joint_is_not_reduced_to_three_flat_jumps(self):
        ps, _pu, _pz, angles, _radius, _panel = _accordion_path(
            200, 2, 120, 1, 1, 1.2, .5, "круг")
        self.assertGreaterEqual(len(ps), 10)  # вход/выход + минимум 8 дуг
        self.assertLessEqual(float(np.max(np.abs(np.diff(angles)))),
                             math.radians(15) + 1e-9)

    def test_four_joint_profiles_work_on_standalone_and_existing_sheet(self):
        volumes = []
        wrapped_volumes = []
        for joint in ("круг", "широкая", "сплайн", "фаска"):
            with self.subTest(joint=joint):
                direct = solid("о = fold_sheet width=90 length=180 thickness=1.2 "
                               f"parts=3 angle=115 gap=1 sharp=.4 joint={joint}")
                wrapped = solid("л = sheet width=90 length=180 thickness=1.2\n"
                                "о = fold [л] parts=3 angle=115 gap=1 sharp=.4 "
                                f"joint={joint}")
                one(direct)
                one(wrapped)
                volumes.append(direct.volume())
                wrapped_volumes.append(wrapped.volume())
        self.assertEqual(len({round(v, 3) for v in volumes}), 4)
        self.assertEqual(len({round(v, 3) for v in wrapped_volumes}), 4)

    def test_surface_fold_along_accepts_all_joint_profiles(self):
        for joint in ("круг", "широкая", "сплайн", "фаска"):
            with self.subTest(joint=joint):
                m = solid("л = sheet width=80 length=160 thickness=1\n"
                          f"о = сгиб [л] parts=2 angle=105 gap=.8 joint={joint}")
                one(m)
                self.assertGreater(size(m)[2], 20)

    def test_j_strip_is_one_continuous_asymmetric_hook(self):
        m = solid("о = strip length=180 width=10 thickness=4 path=J curve=24")
        one(m)
        self.assertEqual(m.genus(), 0)
        self.assertAlmostEqual(m.volume(), 180 * 10 * 4, delta=35)
        self.assertAlmostEqual(size(m)[0], 58, delta=1e-6)
        self.assertGreater(size(m)[1], 100)


class ConcaveOutlineTest(unittest.TestCase):
    def test_disc_and_oval_have_real_concave_sides_and_axis_tips(self):
        for op, tail, dims in (("disc", "diameter=100", [100, 100, 5]),
                               ("oval", "width=160 length=100", [160, 100, 5])):
            with self.subTest(op=op):
                ordinary = solid(f"о = {op} {tail} thickness=5")
                shallow = solid(f"о = {op} {tail} thickness=5 "
                                "outline=вогнутая4 indent=.15")
                deep = solid(f"о = {op} {tail} thickness=5 "
                             "outline=вогнутая4 indent=.55")
                for m in (shallow, deep):
                    one(m)
                    np.testing.assert_allclose(size(m), dims, atol=1e-6)
                self.assertLess(deep.volume(), shallow.volume())
                self.assertLess(shallow.volume(), ordinary.volume())
                verts, _ = manifold_mesh(deep)
                verts = np.asarray(verts)
                # Кончики остаются на осях, а промежуточные дуги уходят внутрь.
                self.assertAlmostEqual(float(np.max(verts[:, 0])), dims[0] / 2, delta=1e-6)
                self.assertAlmostEqual(float(np.max(verts[:, 1])), dims[1] / 2, delta=1e-6)

    def test_concave_outline_supports_domes_bowls_and_actual_edge(self):
        for top in ("плоская", "выпуклая", "вогнутая"):
            with self.subTest(top=top):
                m = solid("о = oval width=160 length=100 thickness=8 sag=3 "
                          f"top={top} outline=вогнутая4 indent=.3 edge=2 edge_band=12")
                one(m)
                np.testing.assert_allclose(size(m)[:2], [160, 100], atol=1e-6)
                self.assertGreater(m.num_tri(), 1000)


class SewingButtonTest(unittest.TestCase):
    def test_every_face_hole_count_is_real_and_topology_matches(self):
        for count in range(9):
            with self.subTest(count=count):
                m = solid("о = sewing_button diameter=30 thickness=4 holes="
                          f"{count} hole_d=3 pitch=8 rim_side=нет top=плоская detail=2")
                one(m)
                self.assertEqual(m.genus(), count)
                np.testing.assert_allclose(size(m), [30, 30, 4], atol=1e-6)

    def test_one_sided_rim_and_face_curvature_are_geometric(self):
        top = solid("о = sewing_button diameter=30 thickness=4 holes=0 top=плоская "
                    "rim_side=верх rim=3 rim_h=6")
        bottom = solid("о = sewing_button diameter=30 thickness=4 holes=0 top=плоская "
                       "rim_side=низ rim=3 rim_h=6")
        plain = solid("о = sewing_button diameter=30 thickness=4 holes=0 top=плоская "
                      "rim_side=нет")
        for m in (top, bottom):
            one(m)
            np.testing.assert_allclose(size(m), [30, 30, 10], atol=1e-6)
        # Наружная кромка занимает всю высоту в обоих случаях: основной диск
        # тоже доходит до неё. Сторону различает продолжение над/под полем.
        self.assertTrue(inside(top, (13.5, 0, 8)))
        self.assertFalse(inside(top, (0, 0, 8)))
        self.assertTrue(inside(top, (0, 0, 2)))
        self.assertTrue(inside(bottom, (0, 0, 8)))
        self.assertFalse(inside(bottom, (0, 0, 2)))
        self.assertTrue(inside(bottom, (13.5, 0, 2)))
        self.assertGreater(top.volume(), plain.volume())
        convex = solid("о = sewing_button diameter=30 thickness=4 holes=0 "
                       "rim_side=нет top=выпуклая sag=2")
        concave = solid("о = sewing_button diameter=30 thickness=4 holes=0 "
                        "rim_side=нет top=вогнутая sag=2")
        one(convex)
        one(concave)
        self.assertGreater(convex.volume(), plain.volume())
        self.assertLess(concave.volume(), plain.volume())

    def test_loop_and_perforated_trapezoid_have_open_back_eye(self):
        for kind in ("ушко", "трапеция"):
            with self.subTest(kind=kind):
                m = solid(f"о = sewing_button diameter=24 thickness=3 kind={kind} "
                          "top=выпуклая sag=2 eye_d=5.3 shank_w=8.2 shank_h=9.1")
                one(m)
                self.assertEqual(m.genus(), 1)
                eye_z = 9.1 - 0.58 * 9.1
                self.assertFalse(inside(m, (0, 0, eye_z)))
                self.assertTrue(inside(m, (3.35, 0, eye_z)))


if __name__ == "__main__":
    unittest.main()
