"""Тесты 0.14: группы, анимация по объектам, петля, качение, кадры, GLB."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.run import build  # noqa: E402


def ok(script: str, **kwargs):
    b = build(script, **kwargs)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


def glb_json(data: bytes) -> dict:
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2
    off, chunks = 12, []
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        chunks.append((ctype, data[off + 8: off + 8 + clen]))
        off += 8 + clen
    return json.loads(chunks[0][1].decode("utf-8"))


DOOR = """
корпус = box size=[80, 40, 60] center=да at=[0, 0, 30]
дверь = box size=[38, 2, 50] center=да at=[-20, 20, 30]
ручка = cylinder radius=2 height=10 center=да at=[-3, 24, 30]
группа_двери = group [дверь, ручка]
"""


class TestGroups(unittest.TestCase):
    def test_group_members(self):
        b = ok(DOOR)
        self.assertEqual(b.scene.groups["группа_двери"], ["дверь", "ручка"])
        payload = b.payload(light=True)
        self.assertEqual(payload["groups"]["группа_двери"], ["дверь", "ручка"])

    def test_group_color_and_visibility(self):
        b = ok(DOOR + "\ncolor группа_двери #112233\nhide группа_двери")
        self.assertEqual(b.scene.objects["дверь"].color.lower(), "#112233")
        self.assertEqual(b.scene.objects["ручка"].color.lower(), "#112233")
        self.assertFalse(b.scene.objects["дверь"].visible)
        self.assertFalse(b.scene.objects["ручка"].visible)
        self.assertTrue(b.scene.objects["корпус"].visible)

    def test_group_delete_cleans_group(self):
        b = ok(DOOR + "\ndelete ручка")
        self.assertNotIn("ручка", b.scene.objects)
        self.assertEqual(b.scene.groups["группа_двери"], ["дверь"])

    def test_group_name_must_not_clash_with_object(self):
        b = build(DOOR + "\nдверь = box size=[1, 1, 1]")
        self.assertFalse(b.ok)

    def test_object_in_two_groups_rejected(self):
        b = build(DOOR + "\nвторая = group [дверь]")
        self.assertFalse(b.ok)

    def test_group_of_missing_object_rejected(self):
        b = build("a = box size=[10,10,10]\ng = group [a, нет_такого]")
        self.assertFalse(b.ok)


class TestAnimationPlan(unittest.TestCase):
    def test_turn_with_pivot_and_group(self):
        b = ok(DOOR + "\nanimate группа_двери turn angle=-95 axis=z pivot=[-38, 21, 0] seconds=2")
        clip = b.payload(light=True)["timeline"]["clips"][0]
        self.assertEqual(clip["kind"], "turn")
        self.assertEqual(clip["object"], "группа_двери")
        self.assertEqual(clip["target_kind"], "group")
        self.assertEqual(clip["pivot"], [-38.0, 21.0, 0.0])
        self.assertAlmostEqual(clip["angle"], -95.0)

    def test_spin_turns(self):
        b = ok("к = cylinder radius=10 height=30\na = animate к spin turns=3 seconds=6")
        clip = b.payload(light=True)["timeline"]["clips"][0]
        self.assertEqual(clip["turns"], 3.0)
        self.assertEqual(clip["seconds"], 6.0)

    def test_roll_radians_and_sign(self):
        b = ok("колесо = cylinder radius=13 height=12\n"
               "animate колесо roll distance=250 radius=13 axis=x seconds=2\n"
               "animate колесо roll distance=250 radius=13 axis=-x seconds=2 track=2")
        clips = b.payload(light=True)["timeline"]["clips"]
        self.assertAlmostEqual(clips[0]["radians"], 250 / 13, places=5)
        self.assertAlmostEqual(clips[1]["radians"], -250 / 13, places=5)

    def test_move_group_delta(self):
        b = ok(DOOR + "\nanimate группа_двери move dy=-250 seconds=2")
        clip = b.payload(light=True)["timeline"]["clips"][0]
        self.assertEqual(clip["kind"], "move")
        self.assertEqual(clip["delta"], [0.0, -250.0, 0.0])

    def test_parallel_objects_same_track(self):
        b = ok(DOOR + "\nanimate группа_двери turn angle=-90 axis=z pivot=[-38,21,0] seconds=2\n"
               "animate дверь move dy=-100 seconds=2")
        clips = b.payload(light=True)["timeline"]["clips"]
        self.assertEqual(len(clips), 2)
        self.assertEqual([c["start"] for c in clips], [0.0, 0.0])
        self.assertEqual(len({c["object"] for c in clips}), 2)

    def test_queue_per_object(self):
        b = ok(DOOR + "\nanimate группа_двери turn angle=-90 axis=z pivot=[-38,21,0] seconds=2\n"
               "animate группа_двери wait seconds=1\n"
               "animate группа_двери turn angle=90 axis=z pivot=[-38,21,0] seconds=2")
        clips = b.payload(light=True)["timeline"]["clips"]
        starts = [c["start"] for c in clips]
        self.assertEqual(starts, [0.0, 2.0, 3.0])
        self.assertAlmostEqual(clips[-1]["end"], 5.0)

    def test_tracks_are_independent(self):
        b = ok("a = box size=[10, 10, 10]\nb = box size=[10, 10, 10] at=[20, 0, 0]\n"
               "animate a spin seconds=4 track=1\nanimate b move dy=50 seconds=2 track=2")
        clips = b.payload(light=True)["timeline"]["clips"]
        self.assertEqual([c["track"] for c in clips], [1, 2])
        self.assertEqual(clips[1]["start"], 0.0)

    def test_track_range(self):
        b = build("a = box size=[10, 10, 10]\nanimate a spin track=99")
        self.assertFalse(b.ok)

    def test_keyframes_still_work(self):
        b = ok("a = box size=[10, 10, 10]\n"
               "keyframe a at=0 pos=[0,0,0]\nkeyframe a at=2 pos=[0,0,40]")
        keys = b.payload(light=True)["timeline"]["keys"]
        self.assertEqual(len(keys), 2)


class TestFrames(unittest.TestCase):
    def test_frames_have_added_and_removed(self):
        b = ok("a = box size=[10, 10, 10]\n"
               "b = cylinder radius=5 height=10 at=[20, 0, 0]\n"
               "delete b")
        frames = b.frames()
        self.assertTrue(frames)
        self.assertIn("a", frames[0]["added"])
        self.assertIn("b", frames[-1]["removed"])
        self.assertEqual(frames[0]["added"], ["a"])


class TestGlbGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = ok(DOOR + "\n"
                   "animate группа_двери turn angle=-90 axis=z pivot=[-38,21,0] seconds=2\n"
                   "animate дверь roll distance=26 radius=13 axis=x seconds=1 track=2\n"
                   "animate корпус move dy=-30 seconds=1 track=3")
        cls.data = glb_json(cls.b.glb())

    def test_group_nodes_exist(self):
        names = {n.get("name"): n for n in self.data["nodes"]}
        self.assertIn("группа_двери", names)
        group = names["группа_двери"]
        children = [self.data["nodes"][i].get("name") for i in group.get("children", [])]
        # у объекта с личным клипом появляется узел-петля FormaPivot_<имя>
        self.assertEqual(sorted(children), ["FormaPivot_дверь", "ручка"])

    def test_scene_root(self):
        names = {n.get("name"): i for i, n in enumerate(self.data["nodes"])}
        root = names["FormaAnimationRoot"]
        self.assertIn(root, self.data["scenes"][0]["nodes"])

    def test_group_turn_has_rotation_and_translation(self):
        names = {n.get("name"): i for i, n in enumerate(self.data["nodes"])}
        door = names["группа_двери"]
        channels = []
        for anim in self.data.get("animations", []):
            for ch in anim["channels"]:
                if ch["target"].get("node") == door:
                    channels.append(ch["target"]["path"])
        self.assertIn("rotation", channels)
        self.assertIn("translation", channels)

    def test_roll_and_move_channels(self):
        names = {n.get("name"): i for i, n in enumerate(self.data["nodes"])}
        obj = names["FormaPivot_дверь"]
        hull = names["FormaPivot_корпус"]
        paths = {}
        for anim in self.data.get("animations", []):
            for ch in anim["channels"]:
                node = ch["target"].get("node")
                paths.setdefault(node, set()).add(ch["target"]["path"])
        self.assertEqual(paths.get(obj), {"rotation"})
        self.assertEqual(paths.get(hull), {"translation"})


if __name__ == "__main__":
    unittest.main()
