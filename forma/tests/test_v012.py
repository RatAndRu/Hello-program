"""Тесты 0.12: дорожки, свои клипы, ключевые кадры, измерения, place on=."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import _glb_read  # noqa: E402
from forma.run import build  # noqa: E402


def ok(script: str, **kwargs):
    b = build(script, **kwargs)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


class TestTracks(unittest.TestCase):
    def test_two_tracks_play_in_parallel(self):
        b = ok("к = box size=[20, 20, 20]\n"
               "animate kind=spin seconds=4 track=1\n"
               "animate kind=explode seconds=2 amount=15 track=2")
        plan = b.payload()["timeline"]
        self.assertEqual(plan["track_count"], 2)
        self.assertEqual(plan["tracks"], [1, 2])
        # обе дорожки начинаются с нуля, длительность — по самой долгой
        self.assertEqual([c["start"] for c in plan["clips"]], [0.0, 0.0])
        self.assertAlmostEqual(plan["duration"], 4.0, places=2)

    def test_clips_on_one_track_go_one_after_another(self):
        b = ok("к = box size=[10, 10, 10]\n"
               "animate kind=spin seconds=2 track=1\n"
               "animate kind=scale to=1.5 seconds=3 track=1")
        clips = b.payload()["timeline"]["clips"]
        self.assertAlmostEqual(clips[1]["start"], clips[0]["end"], places=2)
        self.assertAlmostEqual(clips[1]["end"], 5.0, places=2)

    def test_track_is_limited(self):
        b = build("к = box size=[10, 10, 10]\nanimate kind=spin track=99")
        self.assertFalse(b.ok)
        self.assertIn("дорож", (b.error or {}).get("message", "").lower())


class TestOwnClips(unittest.TestCase):
    def script(self):
        return (
            "а = box size=[40, 20, 10]\n"
            "б = box size=[10, 10, 10]\n"
            "б = place [б] on=а side=top\n"
            "animate kind=move object=б dz=30 seconds=2 track=1\n"
            "animate kind=scale object=б to=1.5 seconds=2 track=2\n"
            "animate kind=turn object=б angle=90 axis=x seconds=2 track=3\n"
            "animate kind=wait seconds=1\n"
        )

    def test_move_scale_turn_and_wait(self):
        plan = ok(self.script()).payload()["timeline"]
        kinds = [c["kind"] for c in plan["clips"]]
        self.assertEqual(kinds, ["move", "scale", "turn", "wait"])
        move = plan["clips"][0]
        self.assertEqual(move["object"], "б")
        self.assertEqual(move["delta"], [0, 0, 30])
        self.assertEqual(plan["clips"][1]["to"], 1.5)
        self.assertEqual(plan["clips"][2]["angle"], 90)
        self.assertEqual(plan["clips"][2]["axis"], "x")

    def test_signed_axis(self):
        plan = ok("к = box size=[10, 10, 10]\n"
                  "animate kind=turn axis=-z angle=45 seconds=1").payload()["timeline"]
        clip = plan["clips"][0]
        self.assertEqual(clip["axis"], "z")
        self.assertEqual(clip["axis_sign"], -1)

    def test_move_without_offset_is_an_error(self):
        b = build("к = box size=[10, 10, 10]\nanimate kind=move seconds=2")
        self.assertFalse(b.ok)
        self.assertIn("dx", (b.error or {}).get("message", "").lower())

    def test_scale_needs_two_values(self):
        b = build("к = box size=[10, 10, 10]\n"
                  "animate kind=scale from=1 to=1 seconds=2")
        self.assertFalse(b.ok)

    def test_unknown_object_is_an_error(self):
        b = build("к = box size=[10, 10, 10]\n"
                  "animate kind=move object=нет dx=5 seconds=2")
        self.assertFalse(b.ok)
        self.assertIn("нет", (b.error or {}).get("message", ""))


class TestMorph(unittest.TestCase):
    def test_morph_clip_keeps_parameter(self):
        plan = ok("R = 40\nк = cylinder radius=R height=60\n"
                  "animate kind=morph param=R from=25 to=55 seconds=3").payload()["timeline"]
        clip = plan["clips"][0]
        self.assertEqual(clip["kind"], "morph")
        self.assertEqual(clip["param"], "R")
        self.assertEqual(clip["from"], 25)
        self.assertEqual(clip["to"], 55)
        self.assertGreaterEqual(clip["samples"], 2)

    def test_morph_without_parameter_is_an_error(self):
        b = build("к = box size=[10, 10, 10]\nanimate kind=morph from=1 to=2")
        self.assertFalse(b.ok)

    def test_overrides_change_geometry(self):
        script = "R = 40\nк = cylinder radius=R height=60 segments=48"
        small = ok(script, overrides={"R": 20})
        big = ok(script, overrides={"R": 50})
        small = list(small.scene.objects.values())[0]
        big = list(big.scene.objects.values())[0]
        self.assertAlmostEqual(small.bbox[3] - small.bbox[0], 40.0, places=1)
        self.assertAlmostEqual(big.bbox[3] - big.bbox[0], 100.0, places=1)


class TestKeyframes(unittest.TestCase):
    def script(self):
        return ("к = box size=[10, 10, 10]\n"
                "keyframe к at=0 pos=[0, 0, 0]\n"
                "keyframe к at=2 pos=[0, 0, 20] rot=[0, 0, 90] scale=1.2\n")

    def test_keys_reach_payload(self):
        plan = ok(self.script()).payload()["timeline"]
        self.assertEqual(plan["key_count"], 2)
        self.assertEqual(plan["duration"], 2.0)
        self.assertEqual(plan["keys"][1]["pos"], [0, 0, 20])
        self.assertEqual(plan["keys"][1]["rot"], [0, 0, 90])
        self.assertEqual(plan["keys"][1]["scale"], 1.2)

    def test_keys_only_animation_is_still_animation(self):
        plan = ok(self.script()).payload()["timeline"]
        self.assertTrue(plan["has"])

    def test_empty_key_is_an_error(self):
        b = build("к = box size=[10, 10, 10]\nkeyframe к at=1")
        self.assertFalse(b.ok)

    def test_unknown_object_for_key(self):
        b = build("к = box size=[10, 10, 10]\nkeyframe нет at=1 pos=[1, 2, 3]")
        self.assertFalse(b.ok)


class TestGlbAnimation(unittest.TestCase):
    def test_all_clip_kinds_and_keys_are_written(self):
        b = ok("а = box size=[40, 20, 10]\n"
               "animate kind=spin axis=z seconds=2 track=1\n"
               "animate kind=move dx=20 seconds=2 track=2\n"
               "animate kind=scale to=1.4 seconds=2 track=3\n"
               "animate kind=turn angle=45 axis=x seconds=2 track=4\n"
               "keyframe а at=0 pos=[0, 0, 0]\n"
               "keyframe а at=2 pos=[0, 0, 10]\n")
        doc, _ = _glb_read(b.glb())
        names = {a["name"] for a in doc.get("animations", [])}
        for expected in ("FormaSpin", "FormaMove", "FormaScale", "FormaTurn"):
            self.assertIn(expected, names)
        self.assertTrue(any(n.startswith("FormaKeys_") for n in names), names)
        node_names = {n.get("name") for n in doc["nodes"]}
        self.assertIn("FormaAnimationRoot", node_names)
        self.assertIn("FormaPivot_а", node_names)

    def test_two_clips_of_one_kind_get_unique_names(self):
        b = ok("к = box size=[10, 10, 10]\n"
               "animate kind=spin seconds=1 track=1\n"
               "animate kind=spin seconds=1 track=2")
        doc, _ = _glb_read(b.glb())
        names = [a["name"] for a in doc.get("animations", [])]
        self.assertEqual(len(names), len(set(names)))

    def test_key_channels_target_pivot(self):
        b = ok("к = box size=[10, 10, 10]\n"
               "keyframe к at=0 pos=[0, 0, 0]\nkeyframe к at=1 pos=[0, 0, 15]\n")
        doc, _ = _glb_read(b.glb())
        clip = next(a for a in doc["animations"] if a["name"].startswith("FormaKeys_"))
        nodes = {doc["nodes"][ch["target"]["node"]].get("name") for ch in clip["channels"]}
        self.assertEqual(nodes, {"FormaPivot_к"})


class TestGlbSkipsRuntimeClips(unittest.TestCase):
    def test_morph_assembly_and_wait_stay_in_app(self):
        """morph/wait/assembly — кадры приложения: пустых клипов в GLB быть не должно."""
        b = ok("R = 30\nк = cylinder radius=R height=40\n"
               "с = sphere radius=6\n"
               "animate kind=morph param=R from=20 to=40 seconds=2\n"
               "animate kind=wait seconds=1\n"
               "animate kind=assembly hold=0.5\n"
               "animate kind=spin seconds=2")
        doc, _ = _glb_read(b.glb())
        names = [a["name"] for a in doc.get("animations", [])]
        self.assertEqual(names, ["FormaSpin"])

    def test_example_with_tracks_builds(self):
        script = (ROOT / "examples" / "animation_tracks.forma").read_text(encoding="utf-8")
        plan = ok(script).payload()["timeline"]
        self.assertEqual(plan["track_count"], 4)
        self.assertGreaterEqual(plan["key_count"], 2)
        self.assertGreaterEqual(len(plan["clips"]), 6)


class TestHelp(unittest.TestCase):
    def test_help_describes_tracks_and_keyframes(self):
        from forma import ops_basic, ops_curves, ops_extra, ops_scene, ops_sdf  # noqa: F401
        from forma import ops_shape, ops_studio  # noqa: F401
        from forma.ops import OPS
        animate = OPS["animate"]
        for key in ("track", "object", "dx", "angle", "param", "samples"):
            self.assertIn(key, animate.params, key)
        keyframe = OPS["keyframe"]
        self.assertIn("pos", str(keyframe.params) + str(keyframe.example))
        self.assertIn("z", animate.example.lower())


class TestMeasuresAndPlace(unittest.TestCase):
    def test_measures_are_numbers(self):
        b = ok("к = box size=[80, 60, 40]\n"
               "h = height(к)\nw = width(к)\nz = top(к) + 10\n")
        self.assertAlmostEqual(b.scene.params["h"], 40.0, places=3)
        self.assertAlmostEqual(b.scene.params["w"], 80.0, places=3)
        self.assertAlmostEqual(b.scene.params["z"], 50.0, places=3)

    def test_measure_inside_command(self):
        b = ok("к = box size=[40, 40, 40]\n"
               "h = height(к)\n"
               "с = box size=[10, 10, 10]\n"
               "с = place [с] on=к side=top offset=2\n")
        top = list(b.scene.objects["с"].bbox)[2]
        self.assertAlmostEqual(top, 40.0 + 2.0, places=1)

    def test_place_on_side_bottom(self):
        b = ok("к = box size=[40, 40, 40]\n"
               "с = box size=[10, 10, 10]\n"
               "с = place [с] on=к side=bottom\n")
        self.assertAlmostEqual(list(b.scene.objects["с"].bbox)[5], 0.0, places=1)

    def test_place_center_puts_object_in_middle(self):
        b = ok("к = box size=[40, 40, 40]\n"
               "с = box size=[10, 10, 10]\n"
               "с = place [с] on=к side=center\n")
        bb = list(b.scene.objects["с"].bbox)
        self.assertAlmostEqual((bb[0] + bb[3]) / 2, 0.0, places=1)
        self.assertAlmostEqual((bb[2] + bb[5]) / 2, 20.0, places=1)


class TestAssemblyInTimeline(unittest.TestCase):
    def test_assembly_clip_has_own_duration(self):
        b = ok("а = box size=[10, 10, 10]\n"
               "б = sphere radius=8\n"
               "в = cylinder radius=5 height=20\n"
               "animate kind=assembly hold=0.5 track=1\n"
               "animate kind=spin seconds=2 track=2")
        plan = b.payload()["timeline"]
        assembly = plan["assembly"]
        self.assertEqual(assembly["kind"], "assembly")
        steps = len(b.payload()["frames"])
        self.assertAlmostEqual(assembly["length"], 0.5 * max(1, steps), places=1)
        self.assertAlmostEqual(plan["duration"], max(assembly["end"], 2.0), places=2)


class TestWebWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.viewer = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")
        cls.app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        cls.index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_viewer_methods_exist(self):
        methods = set(re.findall(r"^\s{2}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
                                 self.viewer, re.M))
        for name in ("_applyPlan", "_sampleKeys", "_buildKeyTracks", "_modelingQuat",
                     "_axisVector", "_applyItemTransform", "preloadFrame"):
            self.assertIn(name, methods, name)

    def test_viewer_supports_new_kinds(self):
        body = self.viewer.split("_applyPlan(t) {", 1)[1].split("\n  _tickAnimation", 1)[0]
        for kind in ("'move'", "'scale'", "'turn'", "'spin'", "'explode'", "'formation'"):
            self.assertIn(kind, body, kind)
        self.assertIn("_keyTracks", body)

    def test_viewer_keeps_keys_from_payload(self):
        self.assertIn("keys: animation?.keys || []", self.viewer)

    def test_timeline_scrolls_inside_panel(self):
        block = self.css.split(".anim-tracks {", 1)[1].split("}", 1)[0]
        self.assertIn("max-height", block)
        self.assertIn("overflow-y: auto", block)
        steps = self.css.split(".anim-steps {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-x: auto", steps)

    def test_editor_has_new_controls(self):
        for ident in ("ae-track", "ae-object", "ae-dx", "ae-angle", "ae-param",
                      "ae-samples", "ak-object", "ak-pos", "ak-rot", "ak-scale", "anim-keys"):
            self.assertIn(f'id="{ident}"', self.index, ident)

    def test_app_renders_keys_and_tracks(self):
        for needle in ("function renderAnimKeys", "function addKeyframe",
                       "function refreshAnimSelectors", "function updateSequence",
                       "function startPreviewAnimation", "animTrackList"):
            self.assertIn(needle, self.app, needle)


if __name__ == "__main__":
    unittest.main()
