"""Регрессии кадров создания, которые нельзя проверить одним NoError."""
from __future__ import annotations

import unittest

from forma.run import build


class EditorAnimationFramesTest(unittest.TestCase):
    def test_group_transforms_are_not_dropped_and_keep_their_source_lines(self):
        script = """\
a = box size=[10,10,10]
b = box size=[5,5,5] at=[20,0,0]
g = group [a,b]
translate [g] offset=[0,0,10]
rotate [g] angle=20 axis=z
color a #ff0000
rotate [g] angle=20 axis=z
animate kind=assembly hold=0.8
"""
        result = build(script, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        frames = result.frames()
        self.assertEqual([f["n"] for f in frames], [1, 2, 4, 5, 7])
        self.assertEqual([f["line"] for f in frames], [1, 2, 4, 5, 7])
        self.assertEqual(frames[2]["affected"], ["a", "b"])
        self.assertEqual(frames[3]["affected"], ["a", "b"])
        self.assertNotIn("animate", [f["verb"] for f in frames])
        self.assertNotIn("color", [f["verb"] for f in frames])
        self.assertAlmostEqual(result.scene.animation_plan(len(frames))["duration"], 4.0)

    def test_every_frame_is_exactly_the_same_visible_scene_as_upto(self):
        script = """\
a = box size=[10,10,10]
b = box size=[5,5,5] at=[20,0,0]
g = group [a,b]
translate [g] offset=[0,0,10]
c = cylinder radius=3 height=8 at=[40,0,0]
hide b
"""
        result = build(script, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        for frame in result.frames():
            with self.subTest(frame=frame["n"]):
                partial = build(script, upto=frame["n"], analyze_model=False)
                self.assertTrue(partial.ok, partial.error)
                self.assertEqual([s.name for s in partial.visible_solids()], frame["objects"])

    def test_composite_object_is_one_visible_step_with_all_added_parts(self):
        script = """\
wall_socket = socket sockets=1 ground=да screws=да
animate kind=assembly hold=0.8
"""
        result = build(script, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        frames = result.frames()
        self.assertEqual(len(frames), 1)
        added = set(frames[0]["added"])
        self.assertIn("wall_socket", added)
        self.assertIn("wall_socket.insert_1", added)
        self.assertIn("wall_socket.bezel_1", added)
        self.assertEqual(frames[0]["line"], 1)


if __name__ == "__main__":
    unittest.main()
