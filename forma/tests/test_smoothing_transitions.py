"""Регрессии гладких сопряжений, плотности сетки и бюджета полигонажа."""

from __future__ import annotations

import unittest

import numpy as np

from forma.ops_extra import _edge_map, _sharp_edge_count
from forma.run import build
from forma.sdf import Field, RoundedCylinder, Tube


def build_one(script: str, name: str = "о"):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    item = result.scene.objects[name]
    mesh = item.manifold
    if mesh.status().name != "NoError" or mesh.is_empty() or len(mesh.decompose()) != 1:
        raise AssertionError((mesh.status(), mesh.is_empty(), len(mesh.decompose())))
    return item


class SDFPrimitiveTest(unittest.TestCase):
    def test_rounded_cylinder_has_flat_ends_and_true_axis(self):
        prim = RoundedCylinder((0.0, -3.0, 26.0), 26.0, 6.0, 1.2, "y")
        field = Field([-28.0, -8.0, -2.0, 28.0, 2.0, 54.0], 0.65)
        field.add(prim)
        solid = field.mesh(smooth_iters=1, simplify=0.02, what="test rounded cylinder")
        self.assertEqual(len(solid.decompose()), 1)
        bb = solid.bounding_box()
        self.assertAlmostEqual(bb[1], -6.0, delta=0.15)
        self.assertAlmostEqual(bb[4], 0.0, delta=0.15)
        self.assertAlmostEqual(bb[2], 0.0, delta=0.15)
        self.assertAlmostEqual(bb[5], 52.0, delta=0.15)
        self.assertGreater(solid.num_tri(), 2_000)

    def test_tube_is_one_elliptical_variable_radius_surface(self):
        tube = Tube([(0.0, 0.0, 20.0), (20.0, 0.0, 20.0), (40.0, 0.0, 20.0)],
                    [5.0, 7.0, 4.0], z_scale=0.6)
        field = Field([-7.0, -9.0, 13.0, 46.0, 9.0, 27.0], 0.5)
        field.add(tube)
        solid = field.mesh(smooth_iters=2, simplify=0.02, what="test tube")
        self.assertEqual(len(solid.decompose()), 1)
        bb = solid.bounding_box()
        self.assertGreater(bb[4] - bb[1], 13.4)  # радиус Y не сжат
        self.assertLess(bb[5] - bb[2], 8.8)      # эллипс по Z, а не круг
        self.assertGreater(solid.volume(), 1_800.0)


class DoorHandleTransitionTest(unittest.TestCase):
    def test_blend_changes_geometry_and_resolution_controls_mesh(self):
        hard = build_one("о = door_handle form=рельефная blend=0 resolution=.8")
        soft = build_one("о = door_handle form=рельефная blend=5 resolution=.8")
        self.assertNotAlmostEqual(hard.manifold.volume(), soft.manifold.volume(), delta=1.0)
        self.assertGreater(hard.manifold.num_tri(), 5_000)
        fine = build_one("о = door_handle form=рельефная blend=5 resolution=.52")
        self.assertGreater(fine.manifold.num_tri(), soft.manifold.num_tri() * 1.6)
        self.assertAlmostEqual(fine.meta["primitive_params"]["resolution"], 0.52, places=6)
        limited = build_one("о = door_handle form=рельефная blend=5 resolution=.4")
        actual = limited.meta["primitive_params"]["resolution"]
        self.assertGreater(actual, 0.4)   # бюджет 8 млн ячеек не молча игнорируется
        self.assertLess(actual, 0.55)


class FireballTransitionTest(unittest.TestCase):
    def test_shared_ring_is_c1_not_merely_watertight(self):
        item = build_one("о = yin_yang form=объёмная")
        mesh = item.manifold.to_mesh()
        verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        tris = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
        edges, faces, key, normals = _edge_map(verts, tris)
        same = np.nonzero(key[1:] == key[:-1])[0]
        paired = edges[same]
        x_join = 60.0 * 0.38
        near = ((np.abs(verts[paired[:, 0], 0] - x_join) < 0.6)
                & (np.abs(verts[paired[:, 1], 0] - x_join) < 0.6))
        delta_x = np.abs(verts[paired[:, 0], 0] - verts[paired[:, 1], 0])
        length = np.linalg.norm(verts[paired[:, 0]] - verts[paired[:, 1]], axis=1)
        near &= delta_x < 0.2 * length
        self.assertGreaterEqual(int(np.count_nonzero(near)), 80)
        n1, n2 = normals[faces[same]], normals[faces[same + 1]]
        dots = np.clip(np.einsum("ij,ij->i", n1, n2), -1.0, 1.0)
        angles = np.degrees(np.arccos(dots[near]))
        # До исправления: median 13.13°, max 23.76°. После C1-входа и
        # локального polish: median 0.41°, max 0.42° на эталонной сетке.
        self.assertLess(float(np.median(angles)), 1.5)
        self.assertLess(float(np.max(angles)), 2.0)
        self.assertGreater(item.manifold.num_tri(), 25_000)


class FuseTransitionTest(unittest.TestCase):
    PARTS = ("тело = ellipsoid x=40 y=40 z=24 segments=128 detail=5\n"
             "стержень = cylinder radius=14 height=60 segments=128 detail=5 at=[0,0,30]\n"
             "диск = cylinder radius=22 height=4 segments=128 detail=5 at=[0,0,76]\n"
             "вершина = sphere radius=18 segments=128 detail=5 at=[0,0,78]\n"
             "кольцо = torus major=18 minor=2.5 segments=128 detail=5 minor_segments=32 at=[0,0,78]\n")

    def test_fuse_preserves_intentional_sharp_edges(self):
        joined = build_one(self.PARTS + "о = union [тело,стержень,диск,вершина,кольцо]")
        fused = build_one(self.PARTS + "о = fuse [тело,стержень,диск,вершина,кольцо] "
                          "radius=5 detail=1.5 max_tris=180000")
        self.assertLessEqual(fused.manifold.num_tri(), 180_000)
        self.assertGreater(fused.meta["fuse_seams"], 0)
        self.assertGreater(_sharp_edge_count(fused.manifold, 60.0), 0)
        self.assertNotAlmostEqual(joined.manifold.volume(), fused.manifold.volume(), delta=0.01)

    def test_fuse_honours_triangle_budget_and_polish_switch(self):
        base = ("а = sphere radius=40 segments=48 at=[0,0,40]\n"
                "б = cylinder radius=16 height=40 segments=48\n")
        limited = build_one(base + "о = fuse [а,б] radius=8 detail=1 max_tris=30000")
        self.assertLessEqual(limited.manifold.num_tri(), 30_000)
        self.assertGreater(limited.meta["fuse_detail"], 1.0)
        unpolished = build_one(base + "о = fuse [а,б] radius=8 detail=2 polish=0")
        polished = build_one(base + "о = fuse [а,б] radius=8 detail=2 polish=1")
        self.assertEqual(unpolished.manifold.num_tri(), polished.manifold.num_tri())
        self.assertNotAlmostEqual(unpolished.manifold.volume(), polished.manifold.volume(), delta=0.01)


if __name__ == "__main__":
    unittest.main()
