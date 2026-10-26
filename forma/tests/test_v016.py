"""Тесты 0.16: сцены анимации, прыжок/падение/вентилятор, крепёж,
бесшовные текстуры, контекстное меню и покраска по полигонам."""

from __future__ import annotations

import pathlib
import unittest

import numpy as np

from forma.run import build

ROOT = pathlib.Path(__file__).resolve().parent.parent


def payload_of(script: str) -> dict:
    result = build(script)
    if not result.ok:
        raise AssertionError(result.error)
    return result.payload()


class TestAnimationKinds(unittest.TestCase):
    """Новые виды анимации: прыжок, падение, вентилятор."""

    def test_jump_defaults(self):
        p = payload_of("куб = box size=[40,40,40]\n"
                       "animate куб jump height=90 seconds=1.2")
        clip = p["timeline"]["clips"][0]
        self.assertEqual(clip["kind"], "jump")
        self.assertAlmostEqual(clip["height"], 90.0)
        self.assertTrue(clip["elastic"])
        self.assertAlmostEqual(clip["length"], 1.2)

    def test_fall_without_elastic(self):
        p = payload_of("куб = box size=[40,40,40]\n"
                       "animate куб fall height=200 elastic=нет")
        clip = p["timeline"]["clips"][0]
        self.assertEqual(clip["kind"], "fall")
        self.assertFalse(clip["elastic"])
        self.assertAlmostEqual(clip["height"], 200.0)

    def test_fan_turns_from_rpm(self):
        p = payload_of("лопасть = box size=[80,10,4]\n"
                       "animate лопасть fan rpm=600 seconds=3")
        clip = p["timeline"]["clips"][0]
        self.assertEqual(clip["kind"], "fan")
        self.assertAlmostEqual(clip["rpm"], 600.0)
        self.assertAlmostEqual(clip["turns"], 30.0)
        self.assertTrue(clip["loop"])

    def test_kind_aliases_are_registered(self):
        from forma.ops_studio import ANIMATIONS, KIND_NAMES_ANIM
        for alias in ("прыжок", "падение", "вентилятор"):
            self.assertIn(alias, ANIMATIONS)
        for kind in ("jump", "fall", "fan"):
            self.assertIn(kind, KIND_NAMES_ANIM)


class TestAnimationScenes(unittest.TestCase):
    """Несколько заготовленных сцен в одном файле."""

    SCRIPT = (
        "дверь = box size=[40,4,80]\n"
        "ящик = box size=[60,40,20]\n"
        "animate дверь turn angle=90 axis=z seconds=2 scene=дверь\n"
        "animate ящик move dy=-120 seconds=3 scene=ящик\n"
        "animate ящик move dy=120 seconds=1 scene=ящик\n"
    )

    def test_scene_list_and_durations(self):
        plan = payload_of(self.SCRIPT)["timeline"]
        self.assertEqual(plan["scenes"], ["дверь", "ящик"])
        self.assertAlmostEqual(plan["scene_durations"]["дверь"], 2.0)
        self.assertAlmostEqual(plan["scene_durations"]["ящик"], 4.0)
        self.assertAlmostEqual(plan["duration"], 4.0)

    def test_every_clip_knows_its_scene(self):
        plan = payload_of(self.SCRIPT)["timeline"]
        by_scene = [(c["object"], c["scene"]) for c in plan["clips"]]
        self.assertEqual(by_scene, [("дверь", "дверь"), ("ящик", "ящик"), ("ящик", "ящик")])

    def test_clips_without_scene_stay_global(self):
        p = payload_of("куб = box size=[10,10,10]\n"
                       "animate куб spin seconds=2\n"
                       "animate куб jump seconds=1 scene=прыжок")
        plan = p["timeline"]
        self.assertEqual(plan["scenes"], ["прыжок"])
        self.assertEqual(plan["clips"][0]["scene"], "")
        self.assertEqual(plan["clips"][1]["scene"], "прыжок")

    def test_wardrobe_example_has_scenes_and_handles(self):
        text = (ROOT / "examples" / "wardrobe.forma").read_text(encoding="utf-8")
        result = build(text)
        self.assertTrue(result.ok, result.error)
        plan = result.payload()["timeline"]
        self.assertEqual(plan["scenes"], ["дверь", "ящик"])
        handles = [c for c in plan["clips"] if c["object"] == "ручка_левая"]
        self.assertTrue(handles, "ручка двери должна анимироваться")
        wheels = [c for c in plan["clips"] if str(c["object"]).startswith("колесо_")]
        self.assertEqual(len(wheels), 12)
        self.assertTrue(all(c["kind"] == "roll" or c["kind"] == "wait" for c in wheels))

    def test_mechanics_example_builds(self):
        from forma.webui import load_example
        result = build(load_example("mechanics"))
        self.assertTrue(result.ok, result.error)
        plan = result.payload()["timeline"]
        self.assertEqual(plan["scenes"], ["вентилятор", "прыжок", "падение"])
        kinds = {c["kind"] for c in plan["clips"]}
        self.assertEqual(kinds, {"fan", "jump", "wait", "fall"})


class TestHardwareShapes(unittest.TestCase):
    """Крепёж и фурнитура: все детали — замкнутые тела из одного куска."""

    CASES = {
        "гайка": "g = nut d=8",
        "болт": "g = bolt d=8 length=30",
        "винт": "g = screw d=4 length=25",
        "уголок": "g = bracket width=60 depth=40 height=40",
        "шкив": "g = pulley diameter=80 width=20 bore=10",
    }

    def test_shapes_are_solid(self):
        for title, line in self.CASES.items():
            with self.subTest(title=title):
                result = build(line + "\ncheck g watertight\ncheck g parts 1")
                self.assertTrue(result.ok, result.error)
                checks = result.payload()["analysis"]["checks"]
                self.assertTrue(all(c["ok"] for c in checks), checks)

    def test_nut_has_thread_and_bore(self):
        plain = build("g = nut d=8 thread=нет").scene.objects["g"]
        threaded = build("g = nut d=8").scene.objects["g"]
        # винтовая канавка добавляет грани и убирает материал
        self.assertGreater(threaded.manifold.num_tri(), plain.manifold.num_tri() * 3)
        self.assertGreaterEqual(threaded.manifold.volume(), 0.0)
        self.assertTrue(threaded.manifold.is_empty() is False)

    def test_pulley_has_bore_and_groove(self):
        obj = build("g = pulley diameter=80 width=20 bore=10").scene.objects["g"]
        full = np.pi * 40 ** 2 * 20
        self.assertLess(obj.manifold.volume(), full * 0.995)
        self.assertGreater(obj.manifold.volume(), full * 0.85)

    def test_bolt_is_taller_than_shank(self):
        metrics = build("g = bolt d=8 length=30").payload()["analysis"]["metrics"]
        self.assertAlmostEqual(metrics["size"][2], 34.0, delta=1.5)

    def test_hardware_in_tools_library(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for op in ("nut", "bolt", "screw", "bracket", "pulley"):
            with self.subTest(op=op):
                self.assertIn(f"op: '{op}'", app)


class TestSeamlessUV(unittest.TestCase):
    """Развёртка по граням: масштаб в миллиметрах, без растянутого шва."""

    def test_auto_uv_is_world_scaled(self):
        from forma.textures import uv_triangles
        verts = np.array([[0, 0, 0], [140, 0, 0], [0, 0, 140]], dtype=float)
        faces = np.array([[0, 1, 2]])
        uv = uv_triangles(verts, faces, "auto", tile_mm=140.0)
        self.assertEqual(uv.shape, (3, 2))
        self.assertAlmostEqual(float(np.ptp(uv[:, 0])), 1.0, places=3)

    def test_adjacent_planar_triangles_share_edge_uv(self):
        from forma.textures import uv_triangles
        # два треугольника одной плоскости: общая точка → одинаковые UV
        verts = np.array([
            [0, 0, 0], [100, 0, 0], [100, 0, 100],
            [0, 0, 0], [100, 0, 100], [0, 0, 100],
        ], dtype=float)
        faces = np.array([[0, 1, 2], [3, 4, 5]])
        uv = uv_triangles(verts, faces, "auto", tile_mm=100.0)
        pairs = [(0, 3), (2, 4)]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertAlmostEqual(float(uv[a][0]), float(uv[b][0]), places=4)
                self.assertAlmostEqual(float(uv[a][1]), float(uv[b][1]), places=4)

    def test_texture_command_defaults_to_auto_uv(self):
        p = payload_of("куб = box size=[100,100,100]\n"
                       "texture куб kind=дерево")
        cube = next(o for o in p["objects"] if o["name"] == "куб")
        self.assertEqual(cube["uv"], "auto")

    def test_cylinder_mode_still_available(self):
        p = payload_of("куб = box size=[100,100,100]\n"
                       "texture куб kind=дерево uv=cylinder")
        cube = next(o for o in p["objects"] if o["name"] == "куб")
        self.assertEqual(cube["uv"], "cylinder")


class TestViewerInterface(unittest.TestCase):
    """Интерфейс: контекстное меню, покраска, выбор сцены, кубы предмета."""

    def test_viewer_api(self):
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        for marker in ("setScene(name)", "scenes()", "pickAt(clientX, clientY)",
                       "setObjectPolygons(name, on)", "paintAt(clientX, clientY",
                       "clearPaint()", "selectSpaceForObject(name)",
                       "onContextMenu", "onPaint"):
            with self.subTest(marker=marker):
                self.assertIn(marker, viewer)

    def test_context_menu_actions(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for text in ("function openContextMenu", "function renderSceneSelect",
                     "выделить предмет", "скрыть предмет", "показать полигонами",
                     "выделить кубы этого предмета", "удалить предмет", "paint-toggle"):
            with self.subTest(text=text):
                self.assertIn(text, app)

    def test_html_and_css(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for marker in ('id="ctx-menu"', 'id="anim-scene"', 'id="paint-toggle"',
                       'id="paint-color"', 'id="paint-clear"', 'id="ae-scene"',
                       'id="ae-height"', 'id="ae-rpm"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
        self.assertIn(".ctx-menu", css)
        self.assertIn(".anim-scene", css)

    def test_animation_kinds_in_editor(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for kind in ("jump", "fall", "fan"):
            with self.subTest(kind=kind):
                self.assertIn(f'value="{kind}"', html)
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("jump: 'прыжок'", app)
        self.assertIn("fall: 'падение'", app)
        self.assertIn("fan: 'вентилятор'", app)


class TestRollAndGroups(unittest.TestCase):
    """Качение и группы: регрессии 0.14 не должны вернуться."""

    def test_roll_angle_is_distance_over_radius(self):
        p = payload_of("к = cylinder radius=13 height=12\n"
                       "animate к roll distance=250 radius=13 axis=x")
        clip = p["timeline"]["clips"][0]
        self.assertAlmostEqual(clip["radians"], 250 / 13, places=4)

    def test_group_pivot_rotation(self):
        p = payload_of(
            "дверь = box size=[100,4,200]\n"
            "ручка = box size=[10,10,60] at=[-50,0,100]\n"
            "дверь_сборка = group [дверь, ручка]\n"
            "animate дверь_сборка turn angle=90 axis=z pivot=[-50,0,0] seconds=2")
        self.assertTrue(p["ok"])
        clip = p["timeline"]["clips"][0]
        self.assertEqual(clip["target_kind"], "group")
        self.assertEqual(clip["pivot"], [-50.0, 0.0, 0.0])
        self.assertEqual(p["groups"]["дверь_сборка"], ["дверь", "ручка"])

    def test_wardrobe_hardware_is_attached(self):
        """Ручка ящика — в группе ящика, петли — в группе двери."""
        script = (ROOT / "examples" / "wardrobe.forma").read_text(encoding="utf-8")
        p = payload_of(script)
        self.assertIn("ручка_ящика", p["groups"]["ящик_сборка"])
        self.assertIn("петля_1", p["groups"]["дверь"])
        self.assertIn("петля_2", p["groups"]["дверь"])


if __name__ == "__main__":
    unittest.main()
