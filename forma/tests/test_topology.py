"""Регрессии топологии твёрдых тел и экспортной сварки.

Fixtures воспроизводят реальные дефекты 0.58: полюса bulb, boolean-следы
gear и совпадающие вершины SDF alien. Quad/SubD-правила здесь намеренно
отсутствуют: для Manifold важны замкнутость, обход и невырожденные треугольники.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import numpy as np
import trimesh

from forma.errors import GeometryError
from forma.geometry import _validate_export_arrays, manifold_mesh
from forma.run import build
from forma.topology import analyze_topology, manifold_topology

ROOT = Path(__file__).resolve().parents[1]


def cube_arrays() -> tuple[np.ndarray, np.ndarray]:
    verts = np.array([
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ], dtype=float)
    faces = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return verts, faces


def built(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{result.log}")
    return result


def glb_reports(data: bytes) -> list[dict]:
    scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
    reports = []
    for name, mesh in scene.geometry.items():
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        report = analyze_topology(np.asarray(mesh.vertices), np.asarray(mesh.faces))
        report["name"] = name
        report["exact_watertight"] = bool(mesh.is_watertight)
        report["exact_winding"] = bool(mesh.is_winding_consistent)
        reports.append(report)
    return reports


class TopologyArrayTest(unittest.TestCase):
    def test_closed_cube_and_open_cube_are_distinguished(self):
        verts, faces = cube_arrays()
        good = analyze_topology(verts, faces)
        self.assertTrue(good["ok"])
        self.assertEqual(good["boundary_edges"], 0)
        self.assertEqual(good["non_manifold_edges"], 0)
        self.assertAlmostEqual(good["volume"], 8.0)

        bad = analyze_topology(verts, faces[:-1])
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["boundary_edges"], 3)

    def test_flipped_face_is_an_error(self):
        verts, faces = cube_arrays()
        faces[4] = faces[4, ::-1]
        report = analyze_topology(verts, faces)
        self.assertFalse(report["ok"])
        self.assertGreater(report["inconsistent_winding"], 0)

    def test_export_gate_rejects_an_open_shell(self):
        verts, faces = cube_arrays()
        with self.assertRaises(GeometryError):
            _validate_export_arrays(verts, faces[:-1], "open-cube")

    def test_coordinate_weld_finds_collapsed_triangle(self):
        verts, faces = cube_arrays()
        # Отдельная грань с двумя разными индексами, но совпадающими координатами.
        verts = np.vstack([verts, verts[0], verts[1], verts[0]])
        faces = np.vstack([faces, [8, 9, 10]])
        report = analyze_topology(verts, faces)
        self.assertGreaterEqual(report["degenerate_index"], 1)


class TopologyExportRegressionTest(unittest.TestCase):
    """Эти же fixtures дают ошибку на старом экспорте и обязаны быть чистыми теперь."""

    def assert_clean_glb(self, data: bytes):
        reports = glb_reports(data)
        self.assertTrue(reports)
        for report in reports:
            with self.subTest(object=report["name"]):
                self.assertTrue(report["ok"], report)
                self.assertTrue(report["exact_watertight"], report)
                self.assertTrue(report["exact_winding"], report)
                self.assertEqual(report["loose_vertices"], 0)

    def test_gear_boolean_traces_are_removed_only_at_export(self):
        result = built("g = gear teeth=36 module=2.6 thickness=8 bore=5 hub=12")
        solid = result.scene.objects["g"]
        before = analyze_topology(*manifold_mesh(solid.manifold))
        # В 0.58 здесь 32 грани; важен сам воспроизводимый дефект, не точное число.
        self.assertGreater(before["degenerate_index"], 0)
        after = manifold_topology(solid.manifold)
        self.assertTrue(after["ok"])
        self.assertGreater(after["removed_degenerate_faces"], 0)
        self.assertAlmostEqual(after["volume"], solid.manifold.volume(),
                               delta=max(1e-4, solid.manifold.volume() * 1e-7))
        self.assert_clean_glb(result.glb())

    def test_bulb_poles_and_loose_vertices_do_not_reach_glb(self):
        result = built(
            "b = bulb shape=candle base=E14 diameter=18 height=32 "
            "glass_wall=0.3 thread=да glow=да segments=48"
        )
        before = analyze_topology(*manifold_mesh(result.scene.objects["b"].manifold))
        self.assertGreater(before["degenerate_index"], 0)
        self.assert_clean_glb(result.glb())

    def test_alien_sdf_uses_guarded_adaptive_cleanup(self):
        result = built((ROOT / "examples" / "alien.forma").read_text(encoding="utf-8"))
        solid = result.scene.objects["пришелец"]
        report = manifold_topology(solid.manifold)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["non_manifold_edges"], 0)
        meshing = solid.meta["meshing"]
        self.assertTrue(meshing["adaptive"])
        self.assertGreater(meshing["non_manifold_before"], 0)
        self.assertEqual(meshing["non_manifold_after"], 0)
        self.assertLessEqual(abs(meshing["volume_delta_pct"]), 0.2)
        self.assertLessEqual(meshing["bbox_delta_mm"], meshing["step_mm"] * 0.1 + 1e-9)
        self.assertEqual(meshing["genus_before"], meshing["genus_after"])
        self.assertEqual(meshing["parts_before"], meshing["parts_after"])
        self.assert_clean_glb(result.glb())

    def test_expanded_sphere_seat_has_no_coplanar_seam(self):
        result = built(
            "s = sphere radius=35 segments=48 expand=.16 expand_side=верх "
            "expand_smooth=.65 expand_seat=4 expand_joint=посадка"
        )
        solid = result.scene.objects["s"]
        # В 0.58 совпадающие крышки пояса и верхней половины давали 44
        # non-manifold ребра на z=0 и три микротуннеля. Наружная форма при
        # исправлении остаётся той же, но экспортная копия обязана быть замкнутой.
        self.assertEqual(solid.manifold.genus(), 0)
        after = manifold_topology(solid.manifold)
        self.assertTrue(after["ok"], after)
        self.assertEqual(after["non_manifold_edges"], 0)
        self.assertEqual(after["boundary_edges"], 0)
        self.assert_clean_glb(result.glb())

    def test_flush_expanded_curved_solids_have_no_seam_defects(self):
        cases = (
            ("sphere", "radius=35 segments=48", 0.65),
            ("ellipsoid", "x=40 y=30 z=35 segments=48", 0.0),
            ("ellipsoid", "x=40 y=30 z=35 segments=48", 0.65),
        )
        for op, dims, smooth in cases:
            with self.subTest(op=op, smooth=smooth):
                result = built(
                    f"s = {op} {dims} expand=.16 expand_side=верх "
                    f"expand_smooth={smooth} expand_joint=стык"
                )
                solid = result.scene.objects["s"]
                self.assertEqual(solid.manifold.genus(), 0)
                after = manifold_topology(solid.manifold)
                self.assertTrue(after["ok"], after)
                self.assert_clean_glb(result.glb())

    def test_mug_flat_slivers_are_not_an_export_error(self):
        result = built((ROOT / "examples" / "mug.forma").read_text(encoding="utf-8"))
        report = manifold_topology(result.visible_solids()[0].manifold)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["sliver_area_pct"], 0.5)
        self.assertLess(report["bend_sliver_area_pct"], report["sliver_area_pct"] * 0.1)
        self.assert_clean_glb(result.glb())

    def test_vase_is_a_healthy_control(self):
        result = built((ROOT / "examples" / "vase.forma").read_text(encoding="utf-8"))
        report = manifold_topology(result.visible_solids()[0].manifold)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["bend_sliver_area_pct"], 0.0)
        self.assert_clean_glb(result.glb())

    def test_topology_check_uses_the_same_export_diagnostics(self):
        result = build(
            "g = gear teeth=36 module=2.6 thickness=8 bore=5 hub=12\n"
            "check g topology"
        )
        self.assertTrue(result.ok, result.error)
        checks = result.analysis["checks"]
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]["ok"], checks[0])


if __name__ == "__main__":
    unittest.main()
