"""Геометрия и DSL разметки «снаружи / строго внутри» (0.72)."""

from __future__ import annotations

import io
import json
import unittest

from forma.errors import FormaError
from forma.face_visibility import _body, analyze_face_visibility
from forma.run import build


def scene_at(z=4, size=4):
    result = build(
        f"голова = box size=[20,20,20]\n"
        f"корень = box size=[{size},{size},{size}] at=[0,0,{z}]",
        analyze_model=False,
    )
    if not result.ok:
        raise AssertionError(result.error)
    return result.scene


def entry_for(report, name="корень"):
    return next(item for item in report["objects"] if item["object"] == name)


def planar_ids(body, z):
    return [i for i, tri in enumerate(body.tris)
            if max(abs(float(v[2]) - z) for v in tri) < 1e-6]


class FaceVisibilityGeometryTests(unittest.TestCase):
    def test_fully_embedded_root_is_strictly_inside(self):
        scene = scene_at(4)
        scene.objects["корень"].face_roles = {"inside": list(range(12))}
        report = analyze_face_visibility(scene)
        self.assertTrue(report["ok"])
        self.assertEqual(report["marked"], 12)
        self.assertEqual(report["checked"], 12)
        self.assertEqual(report["violations"], 0)
        self.assertTrue(all(item["container"] == "голова"
                            for item in entry_for(report)["faces"]))

    def test_embedded_root_cannot_be_called_outside(self):
        scene = scene_at(4)
        scene.objects["корень"].face_roles = {"outside": list(range(12))}
        report = analyze_face_visibility(scene)
        self.assertFalse(report["ok"])
        self.assertEqual(report["violations"], 12)
        self.assertTrue(all(item["actual"] == "inside"
                            for item in entry_for(report)["faces"]))

    def test_partial_root_every_crossing_polygon_is_rejected_red(self):
        scene = scene_at(-2)
        scene.objects["корень"].face_roles = {"inside": list(range(12))}
        report = analyze_face_visibility(scene)
        body = _body(scene.objects["корень"])
        top = set(planar_ids(body, 2))
        bottom = set(planar_ids(body, -2))
        side = set(range(12)) - top - bottom
        results = {item["face"]: item for item in entry_for(report)["faces"]}
        self.assertEqual(len(top), 2)
        self.assertEqual(len(bottom), 2)
        self.assertEqual(len(side), 8)
        self.assertTrue(all(results[i]["ok"] for i in top))
        self.assertTrue(all(not results[i]["ok"] and results[i]["actual"] == "outside"
                            for i in bottom))
        # Именно здесь центральная проба была бы недостаточна: грань пересекает
        # поверхность головы и частично торчит, поэтому strict inside = False.
        self.assertTrue(all(not results[i]["ok"] and results[i]["actual"] == "boundary"
                            for i in side))
        self.assertEqual(report["violations"], 10)

    def test_partial_root_blue_requires_whole_triangle_outside(self):
        scene = scene_at(-2)
        scene.objects["корень"].face_roles = {"outside": list(range(12))}
        report = analyze_face_visibility(scene)
        body = _body(scene.objects["корень"])
        top = set(planar_ids(body, 2))
        bottom = set(planar_ids(body, -2))
        side = set(range(12)) - top - bottom
        results = {item["face"]: item for item in entry_for(report)["faces"]}
        self.assertTrue(all(results[i]["ok"] for i in bottom))
        self.assertTrue(all(results[i]["actual"] == "inside" and not results[i]["ok"]
                            for i in top))
        self.assertTrue(all(results[i]["actual"] == "boundary" and not results[i]["ok"]
                            for i in side))

    def test_coplanar_contact_is_not_strictly_inside(self):
        scene = scene_at(0)
        scene.objects["корень"].face_roles = {"inside": list(range(12))}
        report = analyze_face_visibility(scene)
        body = _body(scene.objects["корень"])
        bottom = planar_ids(body, 0)
        results = {item["face"]: item for item in entry_for(report)["faces"]}
        self.assertTrue(all(results[i]["actual"] == "boundary" and not results[i]["ok"]
                            for i in bottom))

    def test_separate_object_is_outside(self):
        scene = scene_at(30)
        scene.objects["корень"].face_roles = {"outside": list(range(12))}
        report = analyze_face_visibility(scene)
        self.assertTrue(report["ok"])
        self.assertEqual(report["violations"], 0)

    def test_rotated_partial_root_has_no_sampling_loophole(self):
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[5,3,8] center=да at=[0,0,0]\n"
            "корень = rotate [корень] angle=23 axis=y\n"
            "корень = полигоны inside=[0,1,2,3,4,5,6,7,8,9,10,11]",
            analyze_model=False,
        )
        self.assertTrue(result.ok, result.error)
        report = analyze_face_visibility(result.scene)
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["actual"] == "boundary"
                            for item in entry_for(report)["faces"] if not item["ok"]))

    def test_second_container_can_prove_inside(self):
        result = build(
            "левая = box size=[20,20,20] at=[-100,0,0]\n"
            "правая = box size=[20,20,20] at=[100,0,0]\n"
            "корень = box size=[4,4,4] at=[100,0,4]\n"
            "корень = полигоны inside=[0,1,2,3,4,5,6,7,8,9,10,11]",
            analyze_model=False,
        )
        self.assertTrue(result.ok, result.error)
        report = analyze_face_visibility(result.scene)
        self.assertTrue(report["ok"])
        self.assertTrue(all(item["container"] == "правая"
                            for item in entry_for(report)["faces"]))


class FaceVisibilityDslTests(unittest.TestCase):
    def test_full_replacement_and_neutral_gray(self):
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[4,4,4] at=[0,0,4]\n"
            "корень = полигоны снаружи=[0,1] внутри=[2,3] серые=[4]\n"
            "check корень наружность",
            analyze_model=False,
        )
        self.assertTrue(result.ok, result.error)
        solid = result.scene.objects["корень"]
        self.assertEqual(solid.face_roles, {"outside": [0, 1], "inside": [2, 3]})
        payload = result.payload()
        root = next(item for item in payload["objects"] if item["name"] == "корень")
        self.assertEqual(root["face_roles"], solid.face_roles)
        self.assertEqual([frame["verb"] for frame in payload["frames"]], ["box", "box"])
        json.dumps(payload, ensure_ascii=False)

    def test_out_of_range_is_error_not_silent_wrong_face(self):
        result = build(
            "корень = box size=[4,4,4]\n"
            "корень = полигоны inside=[999]",
            analyze_model=False,
        )
        self.assertFalse(result.ok)
        self.assertIn("нет грани 999", result.error["message"])
        self.assertIn("доступны индексы", result.error["message"])

    def test_conflicting_colors_are_rejected(self):
        result = build(
            "корень = box size=[4,4,4]\n"
            "корень = полигоны outside=[2] inside=[2]",
            analyze_model=False,
        )
        self.assertFalse(result.ok)
        self.assertIn("одновременно", result.error["message"])

    def test_empty_command_clears_roles(self):
        scene = scene_at(4)
        scene.objects["корень"].face_roles = {"inside": [1, 2]}
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[4,4,4] at=[0,0,4]\n"
            "корень = полигоны",
            analyze_model=False,
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.scene.objects["корень"].face_roles, {})

    def test_check_and_automatic_metrics_report_violations(self):
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[4,4,4] at=[0,0,-2]\n"
            "корень = полигоны inside=[0,1,2,3,4,5,6,7,8,9,10,11]\n"
            "check корень наружность"
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.analysis["metrics"]["face_visibility"]["violations"], 10)
        self.assertEqual(result.analysis["face_visibility"]["violations"], 10)
        self.assertFalse(result.analysis["checks"][0]["ok"])
        self.assertTrue(any("Разметка граней" in text
                            for text in result.analysis["warnings"]))

    def test_check_does_not_pass_unmarked_object(self):
        result = build("корень = box size=[4,4,4]\ncheck корень наружность")
        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.analysis["checks"][0]["ok"])
        self.assertIn("нет разметки", result.analysis["checks"][0]["text"])

    def test_hidden_marked_object_is_explicitly_skipped(self):
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[4,4,4] at=[0,0,4]\n"
            "корень = полигоны inside=[0,1]\n"
            "hide корень"
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.analysis["face_visibility"]["skipped_hidden"], 2)
        self.assertTrue(any("не проверялась" in text
                            for text in result.analysis["warnings"]))

    def test_glb_faces_have_same_export_indices(self):
        import trimesh
        result = build(
            "голова = box size=[20,20,20]\n"
            "корень = box size=[4,4,4] at=[0,0,4]\n"
            "корень = полигоны inside=[0,1,2,3]"
        )
        self.assertTrue(result.ok, result.error)
        loaded = trimesh.load(io.BytesIO(result.glb()), file_type="glb", process=False)
        counts = sorted(len(mesh.faces) for mesh in loaded.geometry.values())
        self.assertEqual(counts, [12, 12])


if __name__ == "__main__":
    unittest.main()
