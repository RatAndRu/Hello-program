"""0.47: новые профили, настоящие полости и дополнительный пакет примитивов."""

from __future__ import annotations

import unittest

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401
from forma.geometry import manifold_mesh
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


def size(m: mf.Manifold) -> np.ndarray:
    bb = m.bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m: mf.Manifold, point, edge=0.10) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-9)


class NewCavityTest(unittest.TestCase):
    def test_cylinder_top_cavity_is_blind(self):
        m = solid("о = cylinder radius=30 height=60 wall=3")
        one(m)
        np.testing.assert_allclose(size(m), [60, 60, 60], atol=1e-6)
        self.assertTrue(inside(m, (0, 0, 1.5)))       # оставшееся дно
        self.assertFalse(inside(m, (0, 0, 30)))      # полость
        self.assertTrue(inside(m, (28.5, 0, 30)))    # боковая стенка
        self.assertFalse(inside(m, (0, 0, 59)))      # открытый верх

    def test_cylinder_bottom_cavity_keeps_top(self):
        m = solid("о = cylinder radius=30 height=60 wall=3 cavity=низ cavity_depth=40")
        one(m)
        self.assertFalse(inside(m, (0, 0, 10)))
        self.assertTrue(inside(m, (0, 0, 50)))
        self.assertFalse(inside(m, (0, 0, 0.2)))

    def test_cylinder_custom_top_has_cavity_too(self):
        full = solid("о = cylinder radius=30 r2=24 height=60 top_scale=[1.2,.8] top_offset=[5,2]")
        hollow = solid("о = cylinder radius=30 r2=24 height=60 wall=3 "
                       "top_scale=[1.2,.8] top_offset=[5,2]")
        one(hollow)
        self.assertLess(hollow.volume(), full.volume())
        np.testing.assert_allclose(size(hollow), size(full), atol=1e-6)

    def test_pyramid_cavity_is_open_only_at_base(self):
        full = solid("о = pyramid sides=4 radius=40 height=60")
        m = solid("о = pyramid sides=4 radius=40 height=60 wall=3")
        one(m)
        self.assertLess(m.volume(), full.volume())
        self.assertFalse(inside(m, (0, 0, 1)))
        self.assertTrue(inside(m, (0, 0, 58)))
        np.testing.assert_allclose(size(m), size(full), atol=1e-6)

    def test_ring_has_closed_channel_inside_rim(self):
        full = solid("о = ring diameter=30 width=10 thickness=6")
        m = solid("о = ring diameter=30 width=10 thickness=6 cavity=1.2")
        one(m)
        self.assertLess(m.volume(), full.volume())
        self.assertFalse(inside(m, (0, 0, 5)))        # центральное отверстие
        self.assertFalse(inside(m, (18, 0, 5)))       # закрытый канал
        self.assertTrue(inside(m, (20.5, 0, 5)))      # наружная стенка
        self.assertTrue(inside(m, (18, 0, 9.5)))      # верхняя стенка канала
        np.testing.assert_allclose(size(m), size(full), atol=1e-6)


class ConeAndStripTest(unittest.TestCase):
    def test_three_cone_profiles_have_different_real_geometry(self):
        straight = solid("о = cone radius=30 height=60")
        parabola = solid("о = cone radius=30 height=60 form=парабола")
        hill = solid("о = cone radius=30 height=60 form=холмик")
        for m in (straight, parabola, hill):
            one(m)
            np.testing.assert_allclose(size(m), [60, 60, 60], atol=1e-6)
        self.assertLess(straight.volume(), parabola.volume())
        self.assertLess(parabola.volume(), hill.volume())

    def test_cone_hollow_and_smoothing(self):
        full = solid("о = cone radius=30 height=60 form=парабола")
        m = solid("о = cone radius=30 height=60 form=парабола wall=3")
        smooth = solid("о = cone radius=30 height=60 form=парабола smooth=1")
        one(m)
        one(smooth)
        self.assertLess(m.volume(), full.volume())
        self.assertFalse(inside(m, (0, 0, 1)))
        self.assertTrue(inside(m, (0, 0, 58)))
        np.testing.assert_allclose(size(smooth), [60, 60, 60], atol=1e-6)
        self.assertGreater(smooth.num_tri(), full.num_tri())

    def test_horseshoe_strip_is_one_continuous_band(self):
        m = solid("о = strip length=200 width=12 thickness=4 path=подкова curve=35")
        one(m)
        self.assertAlmostEqual(size(m)[0], 82.0, delta=1e-6)
        self.assertAlmostEqual(m.volume(), 200 * 12 * 4, delta=80.0)
        self.assertEqual(m.genus(), 0)


class AdditionalPackageTest(unittest.TestCase):
    def test_grating_circle_and_triangle_patterns(self):
        for pattern in ("круги", "треугольники"):
            with self.subTest(pattern=pattern):
                m = solid(f"о = grating width=180 height=120 pattern={pattern} cols=6 rows=4 bar=3")
                one(m)
                self.assertEqual(m.genus(), 24)

    def test_fireball_is_default_and_flat_thick_is_exact(self):
        volume = solid("о = yin_yang diameter=120 thick=16 hole=16")
        flat = solid("о = yin_yang diameter=120 thick=16 form=плоская hole=16")
        one(volume)
        self.assertGreater(volume.volume(), flat.volume())
        self.assertGreater(size(volume)[0], size(flat)[0])
        self.assertAlmostEqual(size(flat)[1], 16.0, delta=1e-6)

    def test_tee_and_yoke_keep_ovals_distinct_from_capsules(self):
        for op, dims in (("tee", [90, 14, 80]), ("yoke", [80, 14, 110])):
            with self.subTest(op=op):
                capsule = solid(f"о = {op} shape=капсулы" + (" stem=22" if op == "tee" else ""))
                oval = solid(f"о = {op} shape=овалы" + (" stem=22" if op == "tee" else ""))
                one(capsule)
                one(oval)
                # Овалы сохраняют прежнюю выдавленную сетку. Настоящие
                # капсулы округлены ещё и по глубине, поэтому заметно легче
                # и имеют собственную сферическую тесселяцию торцов.
                self.assertLess(capsule.volume(), oval.volume() * 0.95)
                self.assertGreater(capsule.num_tri(), oval.num_tri())
                np.testing.assert_allclose(size(capsule), dims, atol=1e-6)
                np.testing.assert_allclose(size(oval), dims, atol=1e-6)

    def test_hollow_spring_and_worm_channels(self):
        spring_full = solid("о = spring diameter=22 wire=3 turns=10 pitch=7")
        spring_hollow = solid("о = spring diameter=22 wire=3 hole=1 turns=10 pitch=7")
        worm_bore = solid("о = worm profile=трапеция thread_w=5 tip_w=2 end=конус bore=6")
        worm_channel = solid("о = worm profile=трапеция thread_w=5 tip_w=2 end=конус bore=6 channel=1")
        for m in (spring_hollow, worm_channel):
            one(m)
        self.assertLess(spring_hollow.volume(), spring_full.volume())
        self.assertLess(worm_channel.volume(), worm_bore.volume())
        self.assertAlmostEqual(size(worm_channel)[2], 90.0, delta=1e-6)

    def test_lever_lens_modes_and_grommet_fills(self):
        convex = solid("о = lever length=180 diameter=14 knob=линза knob_d=34 knob_h=60")
        concave = solid("о = lever length=180 diameter=14 knob=вогнутая knob_d=34 knob_h=60")
        one(convex)
        one(concave)
        self.assertAlmostEqual(size(convex)[0], 180.0, delta=1e-6)
        self.assertAlmostEqual(size(concave)[0], 180.0, delta=1e-6)
        self.assertLess(concave.volume(), convex.volume())
        # После постановки на пол ось рычага z=17, конец x=90. У вогнутой
        # линзы центр наружной стороны утоплен до x=72; палка туда не выходит.
        self.assertTrue(inside(convex, (80, 0, 17)))
        self.assertFalse(inside(concave, (80, 0, 17)))
        self.assertTrue(inside(concave, (80, 0, 32)))  # материал у края чаши
        flat = solid("о = grommet fill=ровно fill_h=1")
        dome = solid("о = grommet fill=выпуклая fill_h=2")
        bowl = solid("о = grommet fill=вогнутая fill_h=2")
        one(dome)
        one(bowl)
        self.assertAlmostEqual(size(flat)[2], 8.0, delta=1e-6)
        self.assertAlmostEqual(size(dome)[2], 10.0, delta=1e-6)
        self.assertTrue(inside(dome, (0, 0, 9)))
        self.assertFalse(inside(bowl, (0, 0, 9)))
        self.assertTrue(inside(dome, (5.8, 0, 7.9)))
        self.assertTrue(inside(bowl, (5.8, 0, 7.9)))

    def test_turbine_blade_settings_change_mesh(self):
        base = solid("о = turbine_blade")
        other = solid("о = turbine_blade length=150 chord=64 root_h=12 tip=скругление twist=-30 camber=-.08")
        one(base)
        one(other)
        self.assertAlmostEqual(size(base)[2], 180.0, delta=1e-6)
        self.assertAlmostEqual(size(other)[2], 150.0, delta=1e-6)
        v1, _ = manifold_mesh(base)
        v2, _ = manifold_mesh(other)
        self.assertFalse(np.allclose(np.asarray(v1), np.asarray(v2)))


if __name__ == "__main__":
    unittest.main()
