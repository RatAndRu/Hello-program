"""0.41: канон ориентации, локальные стороны и отношения деталей.

Проверяется геометрия, а не только новые строки справки: куда смотрит лицо,
как разворачивается контактная сторона, где проходит заданный зазор, сохраняется
ли центр при parallel/perpendicular и действительно ли чаша открыта вверх.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401 — наполняет реестр
from forma import orient
from forma.instruction import commands_catalog
from forma.orient_notes import PRIMITIVE_ORIENTATIONS
from forma.run import build, commands_help


def _build(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def _solid(result, name: str):
    return result.scene.objects[name].manifold


def _size(result, name: str) -> np.ndarray:
    bb = _solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def _verts(manifold) -> np.ndarray:
    return np.asarray(manifold.to_mesh().vert_properties, dtype=np.float64)[:, :3]


def _inside(manifold, point) -> bool:
    probe = mf.Manifold.cube((0.5, 0.5, 0.5), True).translate(point)
    return bool((manifold ^ probe).volume() > 1e-7)


class OrientationNotesTest(unittest.TestCase):
    def test_every_primitive_has_own_orientation_note(self):
        primitives = {c["name"] for c in commands_help()
                      if c["category"] == "Примитивы"}
        self.assertEqual(len(primitives), 117)
        self.assertEqual(primitives, set(PRIMITIVE_ORIENTATIONS))
        for command in commands_help():
            if command["name"] in primitives:
                self.assertTrue(command.get("orientation"), command["name"])

    def test_notes_explain_asymmetry_and_void_axes(self):
        self.assertIn("−X", PRIMITIVE_ORIENTATIONS["crescent"])
        self.assertIn("+X", PRIMITIVE_ORIENTATIONS["crescent"])
        self.assertIn("остриё", PRIMITIVE_ORIENTATIONS["arrow"])
        self.assertIn("ось", PRIMITIVE_ORIENTATIONS["bead"].lower())
        self.assertIn("axis=z/x/y", PRIMITIVE_ORIENTATIONS["cube_hole"])
        self.assertIn("раскрыты +Z", PRIMITIVE_ORIENTATIONS["hemisphere"])

    def test_ai_catalog_contains_notes_and_new_relations(self):
        text = commands_catalog()
        self.assertIn("исходная ориентация:", text)
        self.assertIn("### parallel", text)
        self.assertIn("### perpendicular", text)
        self.assertIn("face", text)
        self.assertIn("plane=xz", text)


class CanonicalConstructorsTest(unittest.TestCase):
    def test_flat_sign_has_flat_local_axes(self):
        result = _build("с = star outer=60 depth=12 plane=плашмя")
        star = result.scene.objects["с"]
        self.assertLess(_size(result, "с")[2], 13.0)
        self.assertEqual(orient.faces(star)["перед"], "+Z")
        self.assertEqual(orient.faces(star)["верх"], "+Y")
        self.assertTrue(np.allclose(orient.axes_of(star) @ orient.axes_of(star).T,
                                    np.eye(3), atol=1e-8))

    def test_legacy_stand_false_is_also_flat(self):
        result = _build("с = arrow length=120 width=26 head=42 head_width=68 "
                        "depth=12 stand=нет")
        self.assertLess(_size(result, "с")[2], 13.0)
        self.assertEqual(orient.faces(result.scene.objects["с"])["перед"], "+Z")

    def test_spiral_stands_by_default_and_lies_on_request(self):
        upright = _build("с = spiral radius=60 turns=3 wire=6 height=6")
        flat = _build("с = spiral radius=60 turns=3 wire=6 height=6 plane=плашмя")
        self.assertAlmostEqual(_size(upright, "с")[1], 6.0, places=4)
        self.assertGreater(_size(upright, "с")[2], 50.0)
        self.assertAlmostEqual(_size(flat, "с")[2], 6.0, places=4)
        self.assertEqual(orient.faces(flat.scene.objects["с"])["перед"], "+Z")

    def test_text_yz_reads_along_y_and_faces_x(self):
        result = _build('т = text "AB" size=20 depth=2 plane=yz')
        text = result.scene.objects["т"]
        size = _size(result, "т")
        self.assertLess(size[0], 3.0)
        self.assertGreater(size[1], 20.0)
        self.assertGreater(size[2], 10.0)
        faces = orient.faces(text)
        self.assertEqual(faces["перед"], "+X")
        self.assertEqual(faces["право"], "+Y")
        self.assertEqual(faces["верх"], "+Z")

    def test_yin_yang_matching_halves_make_one_disc(self):
        # round=0 сохраняет общую S-кромку без скруглённого зазора.
        result = _build("а = yin_yang diameter=120 thick=16 form=плоская\n"
                        "б = yin_yang diameter=120 thick=16 side=правый form=плоская\n"
                        "в = union [а, б]")
        joined = _solid(result, "в")
        self.assertEqual(len(joined.decompose()), 1)
        expected = math.pi * 60.0 ** 2 * 16.0
        self.assertAlmostEqual(joined.volume() / expected, 1.0, delta=0.03)
        size = _size(result, "в")
        self.assertAlmostEqual(size[0], 120.0, delta=0.1)
        self.assertAlmostEqual(size[1], 16.0, delta=0.1)
        self.assertAlmostEqual(size[2], 120.0, delta=0.1)


class BowlOrientationTest(unittest.TestCase):
    def test_hemisphere_bowl_has_bottom_and_open_top(self):
        result = _build("м = hemisphere radius=50 wall=4")
        bowl = _solid(result, "м")
        self.assertEqual(len(bowl.decompose()), 1)
        self.assertEqual(bowl.genus(), 0)
        self.assertTrue(_inside(bowl, (0, 0, 2)))       # дно
        self.assertFalse(_inside(bowl, (0, 0, 30)))     # полость
        self.assertTrue(_inside(bowl, (47, 0, 48)))     # верхний борт
        rejected = build("м = hemisphere radius=10 wall=9",
                         analyze_model=False)
        self.assertFalse(rejected.ok)
        self.assertIn("Стенка чаши", (rejected.error or {}).get("message", ""))

    def test_paraboloid_bowl_has_bottom_and_open_top(self):
        result = _build("ч = paraboloid diameter=100 height=40 wall=3")
        bowl = _solid(result, "ч")
        self.assertTrue(_inside(bowl, (0, 0, 2)))
        self.assertFalse(_inside(bowl, (0, 0, 30)))
        self.assertTrue(_inside(bowl, (47, 0, 38)))

    def test_dome_still_points_up(self):
        result = _build("к = hemisphere radius=50")
        dome = _solid(result, "к")
        self.assertAlmostEqual(dome.bounding_box()[2], 0.0, places=4)
        self.assertAlmostEqual(dome.bounding_box()[5], 50.0, delta=0.1)
        self.assertEqual(dome.genus(), 0)
        self.assertTrue(_inside(dome, (0, 0, 25)))


class AxisRelationsTest(unittest.TestCase):
    def test_rotation_between_includes_antiparallel(self):
        for source, target in [([0, 0, 1], [1, 0, 0]),
                               ([0, -1, 0], [0, 1, 0]),
                               ([1, 2, 3], [-2, 1, 0.5])]:
            rotation = orient.rotation_between(source, target)
            got = rotation @ (np.asarray(source, dtype=float) /
                              np.linalg.norm(source))
            want = np.asarray(target, dtype=float) / np.linalg.norm(target)
            self.assertTrue(np.allclose(got, want, atol=1e-8))
            self.assertAlmostEqual(np.linalg.det(rotation), 1.0, places=8)

    def test_parallel_uses_rotated_host_axis_and_keeps_center(self):
        result = _build("х = cylinder radius=10 height=60\n"
                        "х = rotate [х] angle=90 axis=x pivot=[0,0,30]\n"
                        "д = box size=[20,10,30] at=[100,30,50] center=да\n"
                        "д = parallel [д] on=х")
        part = result.scene.objects["д"]
        host = result.scene.objects["х"]
        self.assertTrue(np.allclose(orient.axes_of(part)[:, 2],
                                    orient.axes_of(host)[:, 2], atol=1e-8))
        self.assertTrue(np.allclose(orient.bbox_center(part.manifold),
                                    [100, 30, 50], atol=1e-7))

    def test_perpendicular_direction_is_unambiguous(self):
        result = _build("х = cylinder radius=10 height=60\n"
                        "д = box size=[20,10,30]\n"
                        "д = perpendicular [д] on=х axis=top host_axis=top direction=+x")
        part = result.scene.objects["д"]
        self.assertTrue(np.allclose(orient.axes_of(part)[:, 2], [1, 0, 0], atol=1e-8))
        self.assertEqual(part.meta["axis_relation"]["kind"], "perpendicular")

    def test_perpendicular_rejects_only_parallel_direction(self):
        result = build("х = cylinder radius=10 height=60\n"
                       "д = box size=[20,10,30]\n"
                       "д = perpendicular [д] on=х direction=+z", analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("перпендикуляр", (result.error or {}).get("message", ""))


class ContactPlacementTest(unittest.TestCase):
    def test_own_face_rotates_to_rotated_host_and_gap_is_exact(self):
        result = _build("х = box size=[80,40,60]\n"
                        "х = rotate [х] angle=30 axis=z pivot=[0,0,30]\n"
                        "д = box size=[20,10,30]\n"
                        "д = place [д] on=х side=front face=top gap=3")
        host = result.scene.objects["х"]
        part = result.scene.objects["д"]
        host_front = -orient.axes_of(host)[:, 1]
        own_top = orient.axes_of(part)[:, 2]
        self.assertTrue(np.allclose(own_top, -host_front, atol=1e-8))
        # Для front местная ось +Y хозяина — задняя нормаль. Вдоль неё
        # ближняя точка хозяина и дальняя точка детали разделены ровно gap.
        back = orient.axes_of(host)[:, 1]
        hmin = float((_verts(host.manifold) @ back).min())
        pmax = float((_verts(part.manifold) @ back).max())
        self.assertAlmostEqual(hmin - pmax, 3.0, delta=1e-5)
        self.assertEqual(part.meta["contact"]["own_side"], "top")

    def test_front_to_front_does_not_add_arbitrary_roll(self):
        result = _build("х = box size=[80,40,60]\n"
                        "д = box size=[20,10,30]\n"
                        "д = place [д] on=х side=front face=front gap=0")
        part = result.scene.objects["д"]
        self.assertTrue(np.allclose(-orient.axes_of(part)[:, 1], [0, 1, 0], atol=1e-8))
        self.assertTrue(np.allclose(orient.axes_of(part)[:, 2], [0, 0, 1], atol=1e-8))
        self.assertAlmostEqual(part.manifold.bounding_box()[4], -20.0, places=7)

    def test_face_cannot_be_used_with_center(self):
        result = build("х = box size=[80,40,60]\n"
                       "д = box size=[20,10,30]\n"
                       "д = place [д] on=х side=center face=top", analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("side=center", (result.error or {}).get("message", ""))


class CompositeAxesAndPayloadTest(unittest.TestCase):
    def test_mirror_flat_and_children_share_axes(self):
        result = _build("э = mirror_plate width=180 height=90 plane=плашмя")
        self.assertGreaterEqual(len(result.scene.objects), 2)
        for obj in result.scene.objects.values():
            self.assertEqual(orient.faces(obj)["перед"], "+Z", obj.name)
            self.assertEqual(orient.faces(obj)["верх"], "+Y", obj.name)
        rejected = build("э = mirror_plate plane=диагональ", analyze_model=False)
        self.assertFalse(rejected.ok)

    def test_rotate_moves_children_and_their_axes_together(self):
        result = _build("э = mirror_plate width=180 height=90\n"
                        "э = rotate [э] angle=90 axis=z")
        body_axes = orient.axes_of(result.scene.objects["э"])
        for obj in result.scene.objects.values():
            self.assertTrue(np.allclose(orient.axes_of(obj), body_axes, atol=1e-8), obj.name)
        self.assertTrue(np.allclose(body_axes[:, 2], [0, 0, 1], atol=1e-8))

    def test_hardware_does_not_lose_axes_metadata(self):
        result = _build("в = screw d=4 length=25\n"
                        "в = rotate [в] angle=90 axis=x\n"
                        "г = nail d=2 length=20\n"
                        "г = rotate [г] angle=90 axis=x")
        for name in ("в", "г"):
            self.assertTrue(np.allclose(orient.axes_of(result.scene.objects[name])[:, 2],
                                        [0, -1, 0], atol=1e-8))

    def test_objects_payload_contains_actual_axes(self):
        result = _build('т = text "A" plane=yz')
        payload = result.payload()["objects"][0]
        self.assertIn("axes", payload)
        self.assertTrue(np.allclose(np.asarray(payload["axes"]),
                                    orient.axes_of(result.scene.objects["т"])))

    def test_viewer_has_selection_axes_and_excludes_them_from_mirrors(self):
        root = Path(__file__).resolve().parents[1]
        viewer = (root / "web" / "js" / "viewer.js").read_text(encoding="utf-8")
        app = (root / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("FormaLocalAxes", viewer)
        self.assertIn("ПРАВО", viewer)
        self.assertIn("ПЕРЁД", viewer)
        self.assertIn("this._localAxes ? [this._localAxes]", viewer)
        self.assertIn("state.viewer.objectAxes", app)


if __name__ == "__main__":
    unittest.main()
