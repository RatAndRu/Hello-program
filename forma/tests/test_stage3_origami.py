"""Приёмочные тесты этапа 3: лист, оригами и управляемые механизмы."""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
import contextlib
import io
from pathlib import Path

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forma.run import build  # noqa: E402
from forma.cli import main as cli_main  # noqa: E402


def ok(script: str):
    result = build(script)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def bbox(solid):
    return np.asarray(solid.manifold.bounding_box(), dtype=float)


class Stage3OrigamiTests(unittest.TestCase):
    def test_fold_history_is_bounded_and_serializable(self):
        from forma.model import Scene
        from forma.origami import record_fold

        scene = Scene()
        solid = mf.Manifold.cube((2, 2, 1))
        for index in range(40):
            record_fold(scene, "лист", {"angle": index, "kind": "fold"}, solid)
        self.assertLessEqual(len(scene.fold_history), 32)
        per_object = [item for item in scene.fold_history if item["object"] == "лист"]
        self.assertLessEqual(len(per_object), 8)
        json.dumps(scene.fold_history, ensure_ascii=False)
        self.assertNotIn("manifold", json.dumps(scene.fold_history))
        self.assertLessEqual(len(scene._fold_snapshots), 32)

    def test_accordion_history_uses_actual_crease_centers(self):
        from forma.ops_sheet import _accordion_path
        params = "width=30 length=100 thickness=1 parts=4 angle=60 gap=0.5"
        scripts = (f"согнутый = fold_sheet {params}",
                   f"лист = sheet width=30 length=100 thickness=1\nсогнутый = fold лист parts=4 angle=60 gap=0.5")
        _, _, _, _, radius, panel = _accordion_path(100, 4, 60, 0.5, 0.0, 1.0, 0.5, "круг")
        arc = radius * math.radians(60)
        expected = [(i + 1) * panel + arc * (i + 0.5) - 50 for i in range(3)]
        for script in scripts:
            with self.subTest(script=script):
                result = ok(script)
                lines = result.scene.fold_history[-1]["lines"]
                actual = [line["point"][0] for line in lines]
                for got, want in zip(actual, expected):
                    self.assertAlmostEqual(got, want, places=5)
                self.assertEqual([line["assignment"] for line in lines], ["M", "V", "M"])
        along = ok("""лист = sheet width=30 length=100 thickness=1
согнутый = сгиб лист dir=90 at=[0,0,1] parts=4 angle=60 gap=0.5
""")
        along_lines = along.scene.fold_history[-1]["lines"]
        self.assertEqual(len(along_lines), 3)
        self.assertEqual([line["assignment"] for line in along_lines], ["M", "V", "M"])

    def test_unfold_restores_plane_and_leaves_real_groove(self):
        flat = ok("лист = sheet width=30 length=40 thickness=1").scene.objects["лист"]
        result = ok("""лист = sheet width=30 length=40 thickness=1
согнутый = fold_sheet width=30 length=40 thickness=1 angle=45 gap=0.2
разогнутый = unfold согнутый groove=0.5 depth=0.25
""")
        unfolded = result.scene.objects["разогнутый"]
        bounds = bbox(unfolded)
        self.assertAlmostEqual(bounds[2], 0.0, places=5)
        self.assertAlmostEqual(bounds[5], 1.0, places=5)
        # Прямоугольная канавка: 0.5 мм × 0.25 мм × 30 мм = 3.75 мм³.
        self.assertAlmostEqual(flat.manifold.volume() - unfolded.manifold.volume(), 3.75, places=4)
        self.assertEqual(result.scene.fold_history, [])
        self.assertEqual(unfolded.meta["unfold"]["groove"], 0.5)
        self.assertEqual(unfolded.manifold.status(), mf.Error.NoError)

    def test_unfold_without_history_has_clear_error(self):
        result = build("лист = sheet width=20 length=20 thickness=1\nразгиб = unfold лист")
        self.assertFalse(result.ok)
        self.assertIn("истори", result.error["message"].lower())

    def test_fold_and_cp_roundtrip_preserves_creases(self):
        from forma.origami import (decode_cp, decode_fold, encode_cp, encode_fold,
                                   pattern_from_scene)

        result = ok("""лист = sheet width=30 length=40 thickness=0.8
согнутый = fold_sheet width=30 length=40 thickness=0.8 angle=35
""")
        pattern = pattern_from_scene(result.scene)
        self.assertGreaterEqual(len(pattern["edges_vertices"]), 3)
        assignments = set(pattern["edges_assignment"])
        self.assertTrue({"M", "V"}.intersection(assignments))
        self.assertIn("B", assignments)
        restored = decode_fold(encode_fold(pattern))
        self.assertEqual(len(restored["vertices_coords"]), len(pattern["vertices_coords"]))
        self.assertEqual(len(restored["edges_vertices"]), len(pattern["edges_vertices"]))
        cp = encode_cp(pattern)
        cp_restored = decode_cp(cp)
        self.assertEqual(len(cp_restored["vertices_coords"]), len(pattern["vertices_coords"]))
        self.assertEqual(len(cp_restored["edges_vertices"]), len(pattern["edges_vertices"]))
        self.assertTrue({"M", "V"}.intersection(cp_restored["edges_assignment"]))

    def test_cp_preserves_rectangular_aspect_ratio(self):
        from forma.origami import decode_cp, encode_cp
        pattern = {"vertices_coords": [[0, 0], [40, 0], [40, 20], [0, 20]],
                   "edges_vertices": [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]],
                   "edges_assignment": ["B", "B", "B", "B", "M"]}
        restored = decode_cp(encode_cp(pattern))
        coords = np.asarray(restored["vertices_coords"], dtype=float)
        span = coords.max(axis=0) - coords.min(axis=0)
        self.assertAlmostEqual(span[0] / span[1], 2.0, places=6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rect.cp"
            path.write_text(encode_cp(pattern), encoding="utf-8")
            result = ok(f"схема = fold_pattern file={path} thickness=0.5")
        bb = result.scene.objects["схема"].manifold.bounding_box()
        self.assertAlmostEqual((bb[3] - bb[0]) / (bb[4] - bb[1]), 2.0, places=5)

    def test_fold_polygon_and_boundary_only_export(self):
        from forma.origami import pattern_from_scene
        pattern = {"vertices_coords": [[0, 0], [30, 0], [0, 20]],
                   "edges_vertices": [[0, 1], [1, 2], [2, 0]],
                   "edges_assignment": ["B", "B", "B"], "faces_vertices": [[0, 1, 2]]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "triangle.fold"
            path.write_text(json.dumps(pattern), encoding="utf-8")
            result = ok(f"треугольник = fold_pattern file={path} thickness=0.5")
        solid = result.scene.objects["треугольник"].manifold
        self.assertAlmostEqual(solid.volume(), 150.0, delta=0.02)
        exported = pattern_from_scene(result.scene)
        self.assertEqual(exported["edges_assignment"], ["B", "B", "B"])
        self.assertEqual(len(exported["vertices_coords"]), 3)

    def test_fold_pattern_command_builds_editable_sheet(self):
        from forma.origami import encode_fold

        pattern = {
            "file_spec": 1.0,
            "file_creator": "Forma test",
            "vertices_coords": [[0, 0], [40, 0], [40, 30], [0, 30]],
            "edges_vertices": [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]],
            "edges_assignment": ["B", "B", "B", "B", "M"],
            "edges_foldAngle": [180, 180, 180, 180, -150],
            "faces_vertices": [[0, 1, 2], [0, 2, 3]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pattern.fold"
            path.write_text(encode_fold(pattern), encoding="utf-8")
            result = ok(f"деталь = fold_pattern file={path} thickness=0.7")
        solid = result.scene.objects["деталь"]
        self.assertEqual(solid.manifold.status(), mf.Error.NoError)
        self.assertGreater(solid.manifold.volume(), 800)
        self.assertEqual(len(result.scene.fold_history), 1)
        self.assertEqual(result.scene.fold_history[0]["source"], "FOLD")

    def test_packet_has_real_stack_thickness(self):
        base = ok("слой = sheet width=20 length=10 thickness=0.8").scene.objects["слой"]
        result = ok("""слой = sheet width=20 length=10 thickness=0.8
пакет = packet слой layers=5 gap=0.2
""")
        packet = result.scene.objects["пакет"]
        self.assertAlmostEqual(bbox(packet)[5] - bbox(packet)[2], 4.8, places=5)
        self.assertAlmostEqual(packet.manifold.volume(), base.manifold.volume() * 5, places=4)
        self.assertEqual(len(packet.manifold.decompose()), 5)
        self.assertAlmostEqual(packet.meta["packet"]["thickness"], 4.8, places=6)

    def test_hinge_rotates_about_real_pivot(self):
        result = ok("""деталь = box size=[20,4,2] at=[10,0,0]
повёрнутая = hinge_move деталь angle=90 axis=z pivot=[0,0,0]
""")
        moved = result.scene.objects["повёрнутая"]
        bounds = bbox(moved)
        np.testing.assert_allclose(bounds, [-2, 0, 0, 2, 20, 2], atol=1e-5)
        self.assertEqual(result.scene.mechanisms[-1]["type"], "hinge")
        self.assertEqual(result.scene.mechanisms[-1]["steps_checked"], 8)

    def test_hinge_checks_intermediate_collision(self):
        script = """деталь = box size=[30,4,2] at=[15,0,0]
стена = box size=[4,20,10] at=[12,12,0]
повёрнутая = hinge_move деталь angle=90 axis=z pivot=[0,0,0] against=[стена] steps=8
"""
        result = build(script)
        self.assertFalse(result.ok)
        self.assertIn("столкнов", result.error["message"].lower())
        allowed = ok(script.replace("steps=8", "steps=8 allow=да"))
        self.assertTrue(allowed.scene.mechanisms[-1]["collisions"])

    def test_slider_translation_and_collision(self):
        moved = ok("""деталь = box size=[4,4,4]
сдвинутая = slider деталь distance=10 direction=[1,0,0] steps=4
""").scene.objects["сдвинутая"]
        self.assertAlmostEqual(bbox(moved)[0], 8.0, places=5)
        self.assertAlmostEqual(bbox(moved)[3], 12.0, places=5)
        blocked = build("""деталь = box size=[4,4,4]
стена = box size=[2,10,10] at=[6,0,0]
сдвинутая = slider деталь distance=10 direction=[1,0,0] against=[стена]
""")
        self.assertFalse(blocked.ok)
        self.assertIn("столкнов", blocked.error["message"].lower())

    def test_kerf_cut_removes_requested_width(self):
        result = ok("""лист = sheet width=30 length=40 thickness=1
рез = kerf_cut лист from=[0,-20,0.5] to=[0,20,0.5] kerf=0.6
""")
        cut = result.scene.objects["рез"]
        parts = sorted(cut.manifold.decompose(), key=lambda m: m.bounding_box()[0])
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0].bounding_box()[3], -0.3, places=5)
        self.assertAlmostEqual(parts[1].bounding_box()[0], 0.3, places=5)
        self.assertAlmostEqual(40 * 30 - cut.manifold.volume(), 18.0, places=4)
        self.assertEqual(cut.meta["kerf"]["width"], 0.6)

    def test_shallow_kerf_is_a_groove_not_a_through_cut(self):
        result = ok("""лист = sheet width=30 length=40 thickness=1
надрез = kerf_cut лист from=[0,-20,0.5] to=[0,20,0.5] kerf=0.6 depth=0.25 side=top
""")
        cut = result.scene.objects["надрез"]
        self.assertEqual(len(cut.manifold.decompose()), 1)
        self.assertAlmostEqual(40 * 30 - cut.manifold.volume(), 4.5, places=4)

    def test_existing_fold_and_fold_line_can_unfold(self):
        for command in ("fold лист angle=35", "сгиб лист angle=35 dir=0 at=[0,0,1]"):
            with self.subTest(command=command):
                result = ok(f"лист = sheet width=30 length=40 thickness=1\n"
                            f"согнутый = {command}\n"
                            "разгиб = unfold согнутый groove=0.4 depth=0.2")
                self.assertEqual(result.scene.fold_history, [])
                self.assertEqual(result.scene.objects["разгиб"].manifold.status(), mf.Error.NoError)

    def test_cli_exports_fold_and_cp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "sheet.forma"
            script.write_text("согнутый = fold_sheet width=30 length=40 thickness=0.8 angle=35\n",
                              encoding="utf-8")
            outputs = {}
            for fmt in ("fold", "cp"):
                target = root / f"pattern.{fmt}"
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cli_main(["export", str(script), "--format", fmt, "--out", str(target)])
                self.assertEqual(code, 0)
                self.assertTrue(target.exists())
                outputs[fmt] = target.read_text(encoding="utf-8")
            # Тот же контракт проверяется через Web UI/AppState, а не только CLI.
            import os
            from unittest.mock import patch
            from forma.webui import AppState
            with patch.dict(os.environ, {"FORMA_DATA": str(root), "FORMA_DEMO": "0"}):
                state = AppState()
                self.assertTrue(state.build(script.read_text(encoding="utf-8"))["ok"])
                with patch.object(state, "_to_downloads", lambda path: path):
                    for fmt in ("fold", "cp"):
                        answer = state.export(fmt)
                        self.assertTrue(Path(answer["path"]).exists())
        self.assertIn("edges_vertices", json.loads(outputs["fold"]))
        self.assertTrue(any(line.startswith(("2 ", "3 ")) for line in outputs["cp"].splitlines()))

    def test_pattern_import_respects_at(self):
        from forma.origami import encode_fold
        pattern = {"vertices_coords": [[0, 0], [40, 0], [40, 30], [0, 30]],
                   "edges_vertices": [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]],
                   "edges_assignment": ["B", "B", "B", "B", "V"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pattern.fold"
            path.write_text(encode_fold(pattern), encoding="utf-8")
            result = ok(f"схема = fold_pattern file={path} at=[10,20,30] thickness=0.7")
        solid = result.scene.objects["схема"]
        self.assertAlmostEqual(solid.manifold.bounding_box()[2], 30.0, places=5)
        self.assertAlmostEqual(result.scene.fold_history[0]["lines"][0]["point"][2], 30.7, places=5)
        self.assertGreaterEqual(result.scene.fold_history[0]["lines"][0]["point"][0], -10.0)


if __name__ == "__main__":
    unittest.main()
