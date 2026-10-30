"""0.46: фактическая геометрия поверхностных инструментов и чистка каталога."""

from __future__ import annotations

import math
import os
import tempfile
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

from forma.geometry import manifold_mesh
from forma.run import build
from forma.webui import EXAMPLES, load_example

ROOT = Path(__file__).resolve().parents[1]
REMOVED_PROJECTS = (
    "funnel", "orientation", "surface", "half_oval", "hook", "graded",
    "wifi", "chain", "origami", "mates", "primitives", "shape_controls",
    "mech", "polygons", "bottle", "furniture_hardware", "showcase",
    "tools_gallery_1", "tools_gallery_2", "tools_gallery_3", "tools_gallery_4",
    "architecture_selectable_055", "handle_rosettes_055", "selection_details_055",
    "smooth_transitions_054", "fittings_053", "glyphs_expansion_053",
)


def ok(script: str, analyze: bool = False):
    result = build(script, analyze_model=analyze)
    if not result.ok:
        raise AssertionError((result.error or {}).get("message", result.error))
    return result


def one(script: str, name: str = "р"):
    return ok(script).scene.resolve(name).manifold


def vertices(m: mf.Manifold) -> np.ndarray:
    return np.asarray(m.to_mesh().vert_properties, dtype=np.float64)[:, :3]


def valid(m: mf.Manifold) -> bool:
    return m.status() == mf.Error.NoError and not m.is_empty() and m.volume() > 0


class RemovedCatalogTest(unittest.TestCase):
    def test_removed_commands_are_not_registered(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS
        for name in ("display", "skirt", "jacket"):
            with self.subTest(name=name):
                self.assertNotIn(name, OPS)
                self.assertFalse(build(f"д = {name}", analyze_model=False).ok)
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for name in ("display", "skirt", "jacket"):
            self.assertNotIn(f"op: '{name}'", app)

    def test_removed_projects_are_absent(self):
        self.assertEqual(len(EXAMPLES), 20)
        for key in REMOVED_PROJECTS:
            with self.subTest(key=key):
                self.assertFalse((ROOT / "examples" / f"{key}.forma").exists())
                with self.assertRaises(Exception):
                    load_example(key)

    def test_tool_galleries_are_not_in_the_application(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for index in range(1, 5):
            with self.subTest(gallery=index):
                key = f"tools_gallery_{index}"
                self.assertNotIn(key, app)
                with self.assertRaises(Exception):
                    load_example(key)


class PorousGeometryTest(unittest.TestCase):
    def test_spherical_and_cylindrical_pits_have_exact_dimensions(self):
        from forma.ops_surface import _pit_tool
        base = mf.Manifold.cube((40, 40, 20), True).translate((0, 0, 10))
        for cylindrical, depth in ((False, 2.0), (True, 6.0)):
            with self.subTest(cylindrical=cylindrical):
                tool = _pit_tool(5.0, depth, cylindrical, 0.0, 0.0, 0.0, 24,
                                 np.random.default_rng(3)).translate((0, 0, 20))
                cut = base - tool
                self.assertTrue(valid(cut))
                self.assertAlmostEqual(tool.bounding_box()[2], 20.0 - depth, delta=1e-6)
                expected = (math.pi * 5.0 ** 2 * depth if cylindrical else
                            math.pi * depth / 6.0 * (3.0 * 5.0 ** 2 + depth ** 2))
                self.assertAlmostEqual(base.volume() - cut.volume(), expected,
                                       delta=expected * 0.025)

    def test_width_overrides_size_and_seed_is_repeatable(self):
        common = "о = box size=[90,70,24]\nр = porous [о] mode=поры count=5 depth=2 smooth=0 seed=11"
        by_width = one(common + " size=1 width=10\n")
        by_radius = one(common + " size=5\n")
        repeated = one(common + " size=5\n")
        self.assertAlmostEqual(by_width.volume(), by_radius.volume(), delta=1e-6)
        self.assertTrue(np.array_equal(vertices(by_width), vertices(by_radius)))
        self.assertTrue(np.array_equal(vertices(by_radius), vertices(repeated)))

    def test_centres_do_not_overlap_and_overpacking_is_rejected(self):
        from forma.ops_surface import _spaced_surface_points
        base = ok("о = box size=[80,60,20]").scene.resolve("о").manifold
        v, f = manifold_mesh(base)
        pts, _ = _spaced_surface_points(v, f, 12, 2.0, np.random.default_rng(5))
        self.assertEqual(len(pts), 12)
        distances = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
        distances += np.eye(12) * 1000.0
        self.assertGreaterEqual(float(distances.min()), 4.1 - 1e-6)
        rejected = build("о = box size=[10,10,10]\nр = porous [о] size=4 count=20",
                         analyze_model=False)
        self.assertFalse(rejected.ok)
        self.assertIn("не помещаются", (rejected.error or {}).get("message", ""))

    def test_count_depth_and_surface_modifiers_change_geometry(self):
        prefix = "о = box size=[120,100,30]\nр = porous [о] size=2.5 smooth=0 seed=4"
        few = one(prefix + " count=4 depth=1\n")
        many = one(prefix + " count=16 depth=1\n")
        deep = one(prefix + " count=4 depth=3\n")
        rough = one(prefix + " count=4 depth=1 rough=.8 uneven=.7\n")
        self.assertLess(many.volume(), few.volume())
        self.assertLess(deep.volume(), few.volume())
        self.assertNotAlmostEqual(rough.volume(), few.volume(), delta=1e-4)
        for m in (few, many, deep, rough):
            self.assertTrue(valid(m))


class ShavePointTest(unittest.TestCase):
    def test_cut_plane_is_a_plane(self):
        m = one("о = box size=[80,60,40]\nр = cut_plane [о] depth=8\n")
        self.assertTrue(valid(m))
        self.assertAlmostEqual(m.bounding_box()[5], 32.0, delta=1e-6)
        self.assertAlmostEqual(m.slice(32.0 - 1e-4).area(), 80.0 * 60.0, delta=0.1)

    def test_perimeter_groove_profiles_are_distinct(self):
        volumes = {}
        for profile in ("прямоугольная", "овальная", "треугольная", "трапециевидная"):
            m = one("о = box size=[80,60,40]\n"
                    f"р = shave [о] depth=8 groove={profile} "
                    "groove_width=5 groove_depth=2 groove_offset=4 segments=64\n")
            self.assertTrue(valid(m))
            self.assertEqual(len([p for p in m.decompose() if p.volume() > 1e-6]), 1)
            self.assertFalse(any(p.volume() < -1e-6 for p in m.decompose()))
            self.assertAlmostEqual(m.bounding_box()[5], 40.0, delta=1e-6)
            volumes[profile] = m.volume()
        self.assertLess(volumes["прямоугольная"], volumes["овальная"])
        self.assertLess(volumes["овальная"], volumes["трапециевидная"])
        self.assertLess(volumes["трапециевидная"], volumes["треугольная"])

    def test_point_is_one_valid_body_with_one_tip(self):
        m = one("о = cylinder radius=10 height=90 segments=64\n"
                "р = point [о] length=25 side=верх segments=64\n")
        self.assertTrue(valid(m))
        self.assertEqual(len(m.decompose()), 1)
        self.assertEqual(m.genus(), 0)
        self.assertAlmostEqual(m.bounding_box()[5], 90.0, delta=1e-6)
        self.assertEqual(np.count_nonzero(np.isclose(vertices(m)[:, 2], 90.0)), 1)


class WrinkleCrackTest(unittest.TestCase):
    def test_all_wrinkle_modes_are_valid_and_detailed(self):
        for mode in ("радиус", "высота", "шум", "клетка", "трещины"):
            with self.subTest(mode=mode):
                m = one("о = cylinder radius=30 height=70 segments=48\n"
                        f"р = wrinkle [о] mode={mode} amp=2 freq=8 detail=1.2 seed=3\n")
                self.assertTrue(valid(m))
                self.assertGreater(m.num_tri(), 3000)

    def test_angular_modes_preserve_flat_end_rings(self):
        for mode in ("радиус", "трещины"):
            with self.subTest(mode=mode):
                m = one("о = cylinder radius=35 height=90 segments=64\n"
                        f"р = wrinkle [о] mode={mode} amp=3 freq=10\n")
                v = vertices(m)
                for z in (0.0, 90.0):
                    ring = v[np.isclose(v[:, 2], z, atol=1e-6)]
                    outer = ring[np.linalg.norm(ring[:, :2], axis=1) > 34.9]
                    self.assertGreater(len(outer), 40)
                    radii = np.linalg.norm(outer[:, :2], axis=1)
                    # refine_to_length добавляет точки на хордах исходного
                    # 64-угольника: они чуть ближе оси, но не выходят наружу.
                    self.assertGreater(float(radii.min()), 34.85)
                    self.assertLessEqual(float(radii.max()), 35.0 + 1e-5)

    def test_outer_sleeve_keeps_inner_wall(self):
        prefix = ("н = cylinder radius=40 height=90 segments=64\n"
                  "в = cylinder radius=28 height=90 segments=64\n"
                  "о = difference [н,в]\n")
        outer = one(prefix + "р = wrinkle [о] mode=радиус amp=2.5 freq=10 surface=наружная\n")
        both = one(prefix + "р = wrinkle [о] mode=радиус amp=2.5 freq=10 surface=вся\n")
        self.assertTrue(valid(outer))
        self.assertTrue(valid(both))
        hit_outer = outer.ray_cast([0, 0, 45], [100, 0, 45])[0]
        hit_both = both.ray_cast([0, 0, 45], [100, 0, 45])[0]
        self.assertAlmostEqual(float(hit_outer.position[0]), 28.0, delta=1e-4)
        self.assertGreater(abs(float(hit_both.position[0]) - 28.0), 1.0)

    def test_crack_modes_remove_material_and_repeat(self):
        for mode in ("удар", "разлом", "дерево"):
            script = ("о = box size=[90,70,16]\n"
                      f"р = crack [о] mode={mode} count=5 radius=30 width=2 depth=1 detail=.8 seed=4\n")
            with self.subTest(mode=mode):
                base = ok("о = box size=[90,70,16]").scene.resolve("о").manifold
                m = one(script)
                self.assertTrue(valid(m))
                self.assertLess(m.volume(), base.volume())
                self.assertTrue(np.array_equal(vertices(m), vertices(one(script))))


class FoldCorrugationTest(unittest.TestCase):
    def test_accordion_has_equal_flat_panels(self):
        from forma.ops_sheet import _accordion_path
        ps, _pu, _pz, pt, _radius, panel = _accordion_path(
            240.0, 5, 150.0, 0.8, 0.15, 1.0, 0.5)
        straight = np.isclose(np.diff(pt), 0.0, atol=1e-12)
        lengths = np.diff(ps)[straight]
        self.assertEqual(len(lengths), 5)
        self.assertTrue(np.allclose(lengths, panel, atol=1e-8))

    def test_fold_and_diagonal_fold_keep_volume(self):
        base = ok("о = sheet width=100 length=240 thickness=1").scene.resolve("о").manifold
        folded = one("о = sheet width=100 length=240 thickness=1\n"
                     "р = fold [о] parts=5 angle=150 gap=.8 sharp=.15 axis=x\n")
        diagonal = one("о = sheet width=120 length=120 thickness=1\n"
                       "р = сгиб [о] at=[0,0,1] dir=45 angle=120 gap=.5\n")
        self.assertTrue(valid(folded))
        self.assertTrue(valid(diagonal))
        self.assertAlmostEqual(folded.volume(), base.volume(), delta=base.volume() * 0.03)

    def test_crease_makes_real_ridge_and_groove(self):
        ridge = one("о = sheet width=120 length=100 thickness=1\n"
                    "р = складка [о] from=[-50,0,1] to=[50,0,1] r=6 depth=5 mode=гребень taper=.3\n")
        groove = one("о = box size=[120,90,30]\n"
                     "р = складка [о] from=[-48,0,30] to=[48,0,30] r=6 depth=4 mode=канавка taper=.3\n")
        self.assertTrue(valid(ridge))
        self.assertTrue(valid(groove))
        self.assertGreater(ridge.bounding_box()[5], 5.5)
        hit = groove.ray_cast([0, 0, 100], [0, 0, -100])[0]
        self.assertAlmostEqual(float(hit.position[2]), 26.0, delta=0.25)

    def test_rib_and_waffle_have_different_geometry(self):
        rib = one("о = sheet width=100 length=140 thickness=1\n"
                  "р = corrugate [о] mode=рифление step=20 amp=5 angle=0\n")
        waffle = one("о = sheet width=100 length=140 thickness=1\n"
                     "р = corrugate [о] mode=вафля step=20 amp=5 angle=0\n")
        rv, _ = manifold_mesh(rib)
        wv, _ = manifold_mesh(waffle)
        k = 2.0 * math.pi / 20.0
        wave = np.sin(k * rv[:, 0])
        expected_rib = 5.0 * np.sign(wave) * np.power(np.abs(wave), 0.45)
        expected_waffle = 5.0 * np.sin(k * wv[:, 0]) * np.sin(k * wv[:, 1])
        # Manifold волен перенумеровать вершины. Поэтому проверяем саму
        # геометрию: после вычитания волны остаётся исходная толщина 0…1.
        rib_rest = rv[:, 2] - expected_rib
        waffle_rest = wv[:, 2] - expected_waffle
        self.assertGreaterEqual(float(rib_rest.min()), -1e-5)
        self.assertLessEqual(float(rib_rest.max()), 1.0 + 1e-5)
        self.assertGreaterEqual(float(waffle_rest.min()), -1e-5)
        self.assertLessEqual(float(waffle_rest.max()), 1.0 + 1e-5)
        self.assertGreater(float(np.ptp(wv[:, 2] - rv[:, 2])), 5.0)


class SurfaceAssetsHairTest(unittest.TestCase):
    def test_builtin_relief_works_outside_repository_cwd(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                m = one("о = box size=[60,50,12]\nр = relief [о] depth=2 mode=плоскость\n")
            finally:
                # Windows не удаляет временный каталог, пока он остаётся cwd.
                os.chdir(old)
        self.assertTrue(valid(m))
        self.assertGreater(m.num_tri(), 1000)
        spec = (ROOT / "packaging/forma.spec").read_text(encoding="utf-8")
        self.assertIn('docs" / "pattern.png', spec)

    def test_pattern_refines_mesh_without_changing_shape(self):
        plain = ok("о = box size=[60,60,60]").scene.resolve("о").manifold
        painted = ok("о = box size=[60,60,60]\npattern о #d94f3d shape=круги size=10 step=20\n").scene.resolve("о").manifold
        self.assertGreater(painted.num_tri(), plain.num_tri() * 10)
        self.assertAlmostEqual(painted.volume(), plain.volume(), delta=1e-5)
        self.assertTrue(np.allclose(vertices(painted).min(axis=0), vertices(plain).min(axis=0)))
        self.assertTrue(np.allclose(vertices(painted).max(axis=0), vertices(plain).max(axis=0)))

    def test_hair_grows_on_host_without_creating_a_head(self):
        base = ok("о = box size=[50,40,14]").scene.resolve("о").manifold
        for style in ("иголки", "волоски", "локоны", "мех"):
            with self.subTest(style=style):
                m = one("о = box size=[50,40,14]\n"
                        f"р = hair [о] style={style} surface=верх count=10 length=12 spread=0 seed=4\n")
                self.assertTrue(valid(m))
                self.assertEqual(len(m.decompose()), 1)
                self.assertAlmostEqual((m ^ base).volume(), base.volume(), delta=1e-4)
                self.assertGreater(m.bounding_box()[5], 20.0)
        self.assertFalse(build("р = hair style=мех", analyze_model=False).ok)

    def test_bark_is_irregular_and_seeded(self):
        a = one("р = bark height=100 radius=35 grooves=11 depth=4 taper=.2 seed=3\n")
        b = one("р = bark height=100 radius=35 grooves=11 depth=4 taper=.2 seed=3\n")
        c = one("р = bark height=100 radius=35 grooves=11 depth=4 taper=.2 seed=4\n")
        self.assertTrue(valid(a))
        self.assertTrue(np.array_equal(vertices(a), vertices(b)))
        self.assertFalse(np.array_equal(vertices(a), vertices(c)))
        rings = []
        v = vertices(a)
        for z in (25.0, 50.0, 75.0):
            ring = v[np.isclose(v[:, 2], z, atol=1e-5)]
            radii = np.linalg.norm(ring[:, :2], axis=1)
            rings.append(radii)
            self.assertGreater(float(np.ptp(radii)), 1.0)
        self.assertFalse(np.allclose(rings[0], rings[1], atol=1e-4))


if __name__ == "__main__":
    unittest.main()
