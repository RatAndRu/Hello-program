"""Тесты 0.15: готовые фигуры, конец анимации, кубические секторы, «Инструменты».

Фигуры проверяются как обычные тела: герметичность, число частей, габариты.
Кубические секторы — через серверные приписки: в замечании остаются индексы
кубов и координаты, а тот же текст с координатами попадает в сценарий.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402


def ok(script: str, **kwargs):
    b = build(script, **kwargs)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


def checks(b) -> list[dict]:
    return list(b.analysis.get("checks") or [])


class TestShapes(unittest.TestCase):
    """Готовые фигуры: одна команда вместо десятка булевых операций."""

    CASES = {
        "star": "ф = star points=5 outer=60 inner=25 depth=12 bevel=2",
        "pyramid": "ф = pyramid sides=4 radius=60 height=90",
        "plate": "ф = plate diameter=220 depth=26 wall=4",
        "spring": "ф = spring diameter=22 wire=3 turns=10 pitch=7",
        "gear": "ф = gear teeth=20 module=2 thickness=8 bore=8",
        "washer": "ф = washer outer=40 inner=16 thickness=4",
        "cube_hole": "ф = cube_hole size=[40,40,40] hole=16",
        "ring": "ф = ring diameter=20 width=6 thickness=2.2",
    }

    def test_each_shape_is_watertight(self):
        for name, script in self.CASES.items():
            with self.subTest(shape=name):
                b = ok(script + "\ncheck ф watertight\ncheck ф parts 1")
                self.assertTrue(b.scene.objects["ф"].manifold.genus() >= 0)
                result = checks(b)
                self.assertEqual(len(result), 2, result)
                self.assertTrue(all(c["ok"] for c in result), result)

    def test_star_dimensions(self):
        # с 0.41 звезда стоит: X — ширина, Y — толщина, Z — высота
        b = ok("ф = star points=5 outer=60 inner=25 depth=12", analyze_model=False)
        bb = b.scene.objects["ф"].manifold.bounding_box()
        width, thick, height = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
        self.assertAlmostEqual(thick, 12.0, places=3)
        self.assertGreater(width, 110.0)
        self.assertGreater(height, 100.0)
        self.assertLess(max(width, height), 2 * 60.0 + 0.5)

    def test_star_bevel_keeps_size(self):
        plain = ok("ф = star points=5 outer=60 inner=25 depth=12", analyze_model=False)
        cut = ok("ф = star points=5 outer=60 inner=25 depth=12 bevel=2", analyze_model=False)
        a = plain.scene.objects["ф"].manifold.bounding_box()
        b = cut.scene.objects["ф"].manifold.bounding_box()
        self.assertAlmostEqual(a[3] - a[0], b[3] - b[0], places=2)
        self.assertLess(cut.scene.objects["ф"].manifold.volume(),
                        plain.scene.objects["ф"].manifold.volume())

    def test_new_primitives_sizes(self):
        pyr = ok("ф = pyramid sides=4 radius=60 height=90", analyze_model=False)
        bb = pyr.scene.objects["ф"].manifold.bounding_box()
        self.assertAlmostEqual(bb[5] - bb[2], 90.0, places=2)
        ico = ok("ф = icosphere radius=40 divisions=2", analyze_model=False)
        bb = ico.scene.objects["ф"].manifold.bounding_box()
        self.assertAlmostEqual(bb[3] - bb[0], 80.0, delta=0.5)
        gem = ok("ф = diamond diameter=40 crown=14 pavilion=26 sides=8",
                 analyze_model=False)
        bb = gem.scene.objects["ф"].manifold.bounding_box()
        self.assertAlmostEqual(bb[5] - bb[2], 40.0, places=2)

    def test_taper_and_ring_parameters(self):
        # призма сужается к концу: верх меньше низа
        taper = ok("ф = prism sides=6 radius=20 height=30 r2=8", analyze_model=False)
        self.assertAlmostEqual(taper.scene.objects["ф"].manifold.bounding_box()[3],
                               20.0, places=2)
        # тор можно задавать наружным/внутренним радиусом и толщиной
        a = ok("ф = torus outer=40 inner=24 thickness=8", analyze_model=False)
        b = ok("ф = torus major=32 minor=8", analyze_model=False)
        va = a.scene.objects["ф"].manifold.volume()
        vb = b.scene.objects["ф"].manifold.volume()
        self.assertAlmostEqual(va, vb, delta=vb * 0.02)
        # кольцо — то же, но с плоским ободом
        r1 = ok("ф = ring diameter=20 width=6 thickness=2.2", analyze_model=False)
        r2 = ok("ф = ring inner=20 outer=24.4 height=6", analyze_model=False)
        self.assertAlmostEqual(r1.scene.objects["ф"].manifold.volume(),
                               r2.scene.objects["ф"].manifold.volume(), delta=1.0)

    def test_leaf_has_pointed_ends(self):
        leaf = ok("ф = leaf length=90 width=45 thickness=2", analyze_model=False)
        mesh = manifold_mesh(leaf.scene.objects["ф"].manifold)
        v = mesh[0] if isinstance(mesh, tuple) else mesh
        # кончик листа — остриё: длина идёт по X, изгиб — по Y (толщина)
        xs = v[:, 0] if v.shape[1] == 3 else v[:, 0]
        self.assertAlmostEqual(float(xs.min()), -45.0, delta=0.6)
        self.assertAlmostEqual(float(xs.max()), 45.0, delta=0.6)
        near = v[np.abs(xs - float(xs.max())) < 0.35]
        # лист стоит: ширина ушла в высоту, поэтому у кончика сходится Z
        mid_z = float((v[:, 2].min() + v[:, 2].max()) / 2.0)
        self.assertLess(float(np.abs(near[:, 2] - mid_z).max()), 1.5)

    def test_spring_height_follows_turns_and_pitch(self):
        b = ok("ф = spring diameter=22 wire=3 turns=10 pitch=7", analyze_model=False)
        bb = b.scene.objects["ф"].manifold.bounding_box()
        height = bb[5] - bb[2]
        self.assertAlmostEqual(height, 10 * 7 + 3.0, delta=1.0)

    def test_gear_has_bore_and_teeth(self):
        b = ok("ф = gear teeth=20 module=2 thickness=8 bore=8", analyze_model=False)
        solid = b.scene.objects["ф"]
        self.assertEqual(solid.manifold.genus(), 1)
        bb = solid.manifold.bounding_box()
        self.assertAlmostEqual(bb[3] - bb[0], 44.0, delta=0.6)

    def test_cube_hole_axes(self):
        for axis in ("z", "x", "y"):
            with self.subTest(axis=axis):
                b = ok(f"ф = cube_hole size=[40,30,20] hole=10 axis={axis}",
                       analyze_model=False)
                self.assertEqual(b.scene.objects["ф"].manifold.genus(), 1)
                b2 = ok(f"ф = cube_hole size=[40,30,20] hole=10 axis={axis}\n"
                        "check ф genus 1\ncheck ф watertight")
                self.assertTrue(all(c["ok"] for c in checks(b2)), checks(b2))

    def test_aliases_are_commands(self):
        aliases = {
            "звезда": "star outer=40 inner=16",
            "яйцо": "egg height=60 diameter=42 proportion=0.5",
            "арка": "arch radius=120 width=40 thickness=30",
            "полусфера": "hemisphere radius=50",
            "облако": "cloud size=[120,70,60] puffs=8",
            "тарелка": "plate diameter=180 depth=20",
            "пружина": "spring diameter=18 wire=2 turns=6 pitch=5",
            "шестерня": "gear teeth=14 module=2",
            "шайба": "washer outer=30 inner=12 thickness=3",
            "кубик_с_отверстием": "cube_hole size=[30,30,30] hole=10",
            "кольцо": "ring diameter=18 width=5 thickness=2",
        }
        for name, body in aliases.items():
            with self.subTest(alias=name):
                b = ok(f"ф = {name} {body}", analyze_model=False)
                self.assertIn("ф", b.scene.objects)

    def test_bad_dimensions_explained(self):
        b = build("ф = star points=5 outer=40 inner=50")
        self.assertFalse(b.ok)
        self.assertIn("Впадина", b.error["message"])
        b = build("ф = spring diameter=10 wire=6")
        self.assertFalse(b.ok)
        self.assertIn("Проволока", b.error["message"])

    def test_all_shapes_fit_poly_budget(self):
        limits = {"star": 900, "pyramid": 64, "plate": 6500, "spring": 14000,
                  "gear": 2200, "washer": 1600, "cube_hole": 900, "ring": 7200}
        for name, script in self.CASES.items():
            with self.subTest(shape=name):
                b = ok(script, analyze_model=False)
                tris = b.scene.objects["ф"].stats()["tris"]
                self.assertLessEqual(tris, limits[name], f"{name}: {tris} трис")


class TestAnimationEnd(unittest.TestCase):
    """Настройка «дойти до конца и остаться на последнем кадре»."""

    def test_loop_false_in_timeline(self):
        b = ok("ф = box size=[10,10,10]\nanimate kind=spin seconds=2 loop=нет")
        clip = b.payload(light=True)["timeline"]["clips"][0]
        self.assertFalse(clip["loop"])

    def test_loop_true_by_default(self):
        b = ok("ф = box size=[10,10,10]\nanimate kind=spin seconds=2")
        clip = b.payload(light=True)["timeline"]["clips"][0]
        self.assertTrue(clip["loop"])

    def test_viewer_has_loop_mode(self):
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        self.assertIn("setLoopMode(mode)", viewer)
        self.assertIn("this.loopMode", viewer)
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("applyLoopMode", app)
        self.assertIn("forma_loop_mode", app)


class TestSpaceSectors(unittest.TestCase):
    """Кубические секторы: замечание несёт индексы и координаты."""

    def test_note_keeps_cube_coordinates(self):
        from forma.agent import build_prompt
        from forma.webui import AppState

        st = AppState()
        st.build("ф = box size=[80,40,20]", auto=False)
        note = st.add_note({
            "kind": "пространство", "object": "секторы: 6",
            "text": "поставить здесь полку",
            "cells": 6, "cell": 50, "indices": "i 0…1, j 0…0, k 0…1",
            "center": [50, -50, 25], "size": [100, 100, 50],
            "volume_cm3": 500, "tris": 0, "area_mm2": 0,
        })
        self.assertEqual(note["cells"], 6)
        self.assertEqual(note["indices"], "i 0…1, j 0…0, k 0…1")
        self.assertEqual(note["center"], [50.0, -50.0, 25.0])
        self.assertEqual(st.actions[-1]["kind"], "приписка к пространству")
        text = build_prompt(st.last_build, "полка", notes=st.notes, with_reference=False)
        self.assertIn("6 куб.", text)
        self.assertIn("i 0…1, j 0…0, k 0…1", text)
        self.assertIn("центр (50.0, -50.0, 25.0)", text)

    def test_space_ui_is_present(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for marker in ('id="btn-space"', 'id="space-card"', 'id="space-note"',
                       'id="space-size"', 'id="space-save"'):
            self.assertIn(marker, html)
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("setSpaceMode", app)
        self.assertIn("saveSpaceNote", app)
        self.assertIn("spaceSelection", app)
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        self.assertIn("_buildSpaceGrid", viewer)
        self.assertIn("indices", viewer)


class TestExamplesAndTools(unittest.TestCase):
    """Примеры сокращены, а их место заняли «Инструменты»."""

    def test_examples_list(self):
        from forma.webui import EXAMPLES
        keys = [key for _, key in EXAMPLES]
        self.assertEqual(keys, [
            "primitives", "shape_controls", "ribbon_grids", "cavity_folds", "more_solids", "mech", "mug", "car", "vase", "bottle", "alien", "gear",
            "mannequin", "apple", "human_studio", "animation_tracks", "wardrobe",
            "mechanics", "polygons", "showcase", "units",
            "motorcycle", "clock", "mates", "anime_face", "origami", "chain",
            "wifi", "graded", "hook", "half_oval", "surface",
            "funnel", "orientation",
        ])

    def test_removed_examples_are_gone(self):
        from forma.webui import load_example
        for key in ("banana", "mushroom", "cube_hole", "mug_studio",
                    "animation", "tech", "tools"):
            with self.subTest(key=key):
                with self.assertRaises(Exception):
                    load_example(key)

    def test_kept_examples_exist(self):
        from forma.webui import EXAMPLES, load_example
        for _, key in EXAMPLES:
            with self.subTest(key=key):
                self.assertGreater(len(load_example(key)), 50)

    def test_tools_modal_and_library(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for marker in ('id="btn-tools"', 'id="tools-modal"', 'id="tools-body"'):
            self.assertIn(marker, html)
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("const TOOL_SHAPES", app)
        self.assertIn("const TOOL_RECIPES", app)
        self.assertIn("function renderTools", app)
        self.assertIn("function addShapeTool", app)
        # все восемь фигур доступны из библиотеки
        for op in ("star", "pyramid", "plate", "spring", "gear", "washer",
                   "cube_hole", "ring", "egg", "arch", "hemisphere", "cloud"):
            self.assertIn(f"op: '{op}'", app)

    def test_shape_commands_in_help(self):
        import forma.run  # noqa: F401  — регистрирует команды
        from forma.ops import OPS

        for name in ("star", "pyramid", "icosphere", "diamond", "plate",
                     "spring", "gear", "washer", "cube_hole", "ring"):
            spec = OPS[name]
            self.assertEqual(spec.category, "Примитивы")
            self.assertTrue(spec.example)
            self.assertTrue(spec.params)


if __name__ == "__main__":
    unittest.main()
