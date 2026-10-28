"""Соус по поверхности, параметрические кляксы и настоящие 3D-узлы."""
from __future__ import annotations

import io
from pathlib import Path
import unittest

import manifold3d as mf
import numpy as np
import trimesh

from forma.geometry import manifold_mesh
from forma.ops_organic import _knot_paths
from forma.run import build, help_list

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("простой", "восьмерка", "бант", "галстук")


def ok(script: str):
    result = build(script)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def one(script: str, name: str):
    return ok(script).scene.resolve(name).manifold


def valid(m: mf.Manifold) -> bool:
    return m.status() == mf.Error.NoError and not m.is_empty() and m.volume() > 0


class BlotTest(unittest.TestCase):
    def test_seed_is_reproducible_and_changes_the_actual_mesh(self):
        a = one("к = blot radius=45 droplets=7 seed=12", "к")
        b = one("к = blot radius=45 droplets=7 seed=12", "к")
        c = one("к = blot radius=45 droplets=7 seed=31", "к")
        va, fa = manifold_mesh(a)
        vb, fb = manifold_mesh(b)
        vc, _ = manifold_mesh(c)
        self.assertTrue(np.array_equal(va, vb))
        self.assertTrue(np.array_equal(fa, fb))
        self.assertFalse(np.array_equal(va, vc))
        self.assertGreater(abs(a.volume() - c.volume()), 1e-3)

    def test_body_droplets_bounds_and_detail(self):
        body = one("к = blot radius=45 thickness=4 dome=1.2 droplets=0 seed=3", "к")
        self.assertTrue(valid(body))
        self.assertEqual(len(body.decompose()), 1)
        bb = body.bounding_box()
        self.assertAlmostEqual(bb[5] - bb[2], 5.2, places=4)
        # anchor центрирует несимметричный bbox, поэтому мировой радиус не равен
        # радиусу от исходного центра контура; габариты при этом сохраняют предел 2R.
        self.assertLessEqual(bb[3] - bb[0], 90.0001)
        self.assertLessEqual(bb[4] - bb[1], 90.0001)
        splat = one("к = blot radius=45 droplets=7 seed=12", "к")
        self.assertTrue(valid(splat))
        self.assertEqual(len(splat.decompose()), 8)
        self.assertTrue(all(p.volume() > 0 for p in splat.decompose()))
        _, coarse = manifold_mesh(one("к = blot detail=0", "к"))
        _, fine = manifold_mesh(one("к = blot detail=5", "к"))
        self.assertGreater(len(fine), len(coarse) * 3)


class SauceTest(unittest.TestCase):
    def test_standalone_patterns_seed_and_radius(self):
        for pattern in ("зигзаг", "волна", "прямая"):
            with self.subTest(pattern=pattern):
                self.assertTrue(valid(one(f"с = sauce pattern={pattern}", "с")))
        a = one("с = sauce seed=4 drips=2", "с")
        b = one("с = sauce seed=4 drips=2", "с")
        c = one("с = sauce seed=9 drips=2", "с")
        va, _ = manifold_mesh(a)
        vb, _ = manifold_mesh(b)
        vc, _ = manifold_mesh(c)
        self.assertTrue(np.array_equal(va, vb))
        self.assertFalse(np.array_equal(va, vc))
        thin = one("с = sauce radius=1.2", "с")
        thick = one("с = sauce radius=3.6", "с")
        self.assertGreater(thick.volume(), thin.volume() * 2.0)

    def test_projection_preserves_target_and_avoids_embedded_rope(self):
        script = ("сосиска = capsule radius=15 height=150\n"
                  "сосиска = rotate [сосиска] angle=90 axis=y\n"
                  "горчица = sauce [сосиска] length=105 amplitude=12 waves=5 "
                  "radius=2.2 drips=2 seed=4")
        result = ok(script)
        self.assertEqual(set(result.scene.objects), {"сосиска", "горчица"})
        target = result.scene.resolve("сосиска").manifold
        sauce = result.scene.resolve("горчица").manifold
        self.assertTrue(valid(sauce))
        self.assertEqual(len(sauce.decompose()), 1)
        # Касание допускает лишь численный шум, но не скрытую трубу внутри сосиски.
        self.assertLess((target ^ sauce).volume(), 0.25)
        self.assertGreater(sauce.bounding_box()[5], target.bounding_box()[5])

    def test_path_outside_target_is_an_explicit_error(self):
        result = build("основа = box size=[50,50,10]\n"
                       "с = sauce [основа] length=200 amplitude=0 pattern=прямая")
        self.assertFalse(result.ok)
        self.assertIn("вышла", result.error["message"])


class KnotTest(unittest.TestCase):
    def test_all_knot_blanks_are_closed_and_have_centerline_clearance(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                m = one(f"у = knot kind={kind} size=100 radius=2.5 tail=15", "у")
                self.assertTrue(valid(m))
                self.assertEqual(len(m.decompose()), 1)
                path = _knot_paths(kind, 100, 2.5, 0, 15, 3)[0]
                profile_radius = 2.5 * (1.2 if kind == "галстук" else 1.0)
                arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
                minimum = float("inf")
                for i, point in enumerate(path):
                    distances = np.linalg.norm(path - point, axis=1)
                    nonlocal_points = np.abs(arc - arc[i]) > 4 * profile_radius
                    if np.any(nonlocal_points):
                        minimum = min(minimum, float(distances[nonlocal_points].min()))
                self.assertGreater(minimum, 2 * profile_radius * 0.98,
                                   f"{kind}: ветви сближаются до {minimum:.3f} мм")

    def test_explicit_height_cannot_hide_colliding_branches(self):
        bad = build("у = knot kind=бант radius=2.5 height=5")
        self.assertFalse(bad.ok)
        self.assertIn("безопасного", bad.error["hint"] + bad.error["message"])
        self.assertTrue(valid(one("у = knot kind=бант radius=2.5 height=12.5", "у")))
        self.assertTrue(valid(one("у = knot kind=галстук radius=2.5 height=35", "у")))

    def test_kind_size_radius_and_detail_are_real_parameters(self):
        overhand = one("у = knot kind=простой", "у")
        figure8 = one("у = knot kind=восьмерка", "у")
        self.assertFalse(np.array_equal(manifold_mesh(overhand)[0], manifold_mesh(figure8)[0]))
        small_path = _knot_paths("простой", 50, 2.5, 0, 0, 3)[0]
        large_path = _knot_paths("простой", 100, 2.5, 0, 0, 3)[0]
        small_span = np.ptp(small_path[:, 0])
        large_span = np.ptp(large_path[:, 0])
        self.assertAlmostEqual(large_span / small_span, 2.0, places=6)
        small = one("у = knot kind=простой size=50 tail=0", "у").bounding_box()
        large = one("у = knot kind=простой size=100 tail=0", "у").bounding_box()
        self.assertGreater((large[3] - large[0]) / (small[3] - small[0]), 1.85)
        thin = one("у = knot kind=простой radius=1.5", "у")
        thick = one("у = knot kind=простой radius=4.5", "у")
        self.assertGreater(thick.volume(), thin.volume() * 3.0)
        _, coarse = manifold_mesh(one("у = knot detail=0", "у"))
        _, fine = manifold_mesh(one("у = knot detail=5", "у"))
        self.assertGreater(len(fine), len(coarse) * 2)


class OrganicIntegrationTest(unittest.TestCase):
    def test_help_cards_and_blender_compatible_glb(self):
        help_by_name = {item["name"]: item for item in help_list()}
        for name in ("sauce", "blot", "knot"):
            self.assertIn(name, help_by_name)
            self.assertGreater(len(help_by_name[name]["summary"]), 60)
        self.assertIn("seed", {p["name"] for p in help_by_name["blot"]["params"]})
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        for name in ("sauce", "blot", "knot"):
            self.assertIn(f"op: '{name}'", js)
        result = ok("к = blot radius=30 droplets=3 seed=4 at=[0,0,0]\n"
                    "с = sauce length=70 at=[100,0,0]\n"
                    "у1 = knot kind=простой at=[0,120,0]\n"
                    "у2 = knot kind=восьмерка at=[120,120,0]\n"
                    "у3 = knot kind=бант at=[0,250,0]\n"
                    "у4 = knot kind=галстук at=[150,250,0]")
        scene = trimesh.load(io.BytesIO(result.glb()), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 6)
        for mesh in scene.geometry.values():
            mesh.merge_vertices(digits_vertex=5, merge_tex=True, merge_norm=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(mesh.is_winding_consistent)


if __name__ == "__main__":
    unittest.main()
