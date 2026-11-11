"""0.76: контакт слоёв и сохранение толщины при драпировке.

Проверки смотрят не только на счётчик контактов: объём пересечения двух
полученных тел вычисляется отдельно через Manifold. Полый рукав проверяется
в составе готового сценария, входящего в поставку.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest

import manifold3d as mf
import numpy as np

from forma import cloth
from forma.cloth_collision import SurfaceContacts
from forma.geometry import manifold_mesh
from forma.ops_interior import _drape_intersections, _drape_support_intersections
from forma.run import build


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "drape_layers_076.forma"


def build_ok(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"Сцена не собралась: {result.error}")
    return result


class SweptContactTest(unittest.TestCase):
    def test_fast_vertex_hits_middle_of_triangle(self):
        # У верхнего треугольника вершина пересекает нижнюю грань за один
        # шаг, но не приближается ни к одной из её трёх вершин.
        vertices = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0],
                             [.3, .3, .7], [.3, 1, .7], [1, .3, .7]], dtype=float)
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
        parts = np.array([0, 0, 0, 3, 3, 3], dtype=np.int64)
        solver = SurfaceContacts(vertices, faces, np.zeros((0, 2), dtype=np.int64),
                                 0.1, parts, np.array([0, 0, 1]))
        previous = vertices.copy()
        current = vertices.copy()
        current[3:, 2] = -0.2
        fixed = current[:3].copy()
        free = np.array([False, False, False, True, True, True])
        count, _ = solver.project(previous, current, free, rounds=12)
        self.assertGreater(count, 0)
        self.assertGreaterEqual(float(current[3:, 2].min()), 0.099)
        np.testing.assert_array_equal(current[:3], fixed)

    def test_contact_moves_opposite_sides_of_one_wall_together(self):
        vertices = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0],
                             [.3, .3, .7], [.3, 1, .7], [1, .3, .7],
                             [.3, .3, 1.0], [.3, 1, 1.0], [1, .3, 1.0]])
        faces = np.array([[0, 1, 2], [3, 4, 5], [6, 8, 7]], dtype=np.int64)
        shell = np.array([[3, 6], [4, 7], [5, 8]], dtype=np.int64)
        parts = np.array([0, 0, 0, 3, 3, 3, 3, 3, 3], dtype=np.int64)
        solver = SurfaceContacts(vertices, faces, shell, 0.1, parts, np.array([0, 0, 1]))
        current = vertices.copy()
        current[3:6, 2] -= .9
        current[6:, 2] -= .9
        free = np.array([False, False, False, True, True, True, True, True, True])
        count, _ = solver.project(vertices, current, free, rounds=12)
        self.assertGreater(count, 0)
        self.assertGreaterEqual(float(current[3:6, 2].min()), .099)
        np.testing.assert_allclose(current[6:, 2] - current[3:6, 2], .3, atol=1e-9)

    def test_adjacent_triangles_do_not_repel_themselves(self):
        vertices = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
        faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
        solver = SurfaceContacts(vertices, faces, np.zeros((0, 2), dtype=np.int64),
                                 .1, np.zeros(4, dtype=np.int64), np.array([0, 0, 1]))
        current = vertices.copy()
        count, _ = solver.project(vertices, current, np.ones(4, dtype=bool), rounds=4)
        self.assertEqual(count, 0)
        np.testing.assert_array_equal(current, vertices)

    def test_volume_gradient_matches_finite_difference(self):
        body = mf.Manifold.cube((11, 9, 3), True).translate((8, -4, 30))
        vertices, faces = manifold_mesh(body)
        volume, gradient = cloth._volume_data(vertices, faces)
        epsilon = 1e-5
        for vertex, axis in ((0, 0), (1, 1), (5, 2)):
            moved = vertices.copy()
            moved[vertex, axis] += epsilon
            later, _ = cloth._volume_data(moved, faces)
            self.assertAlmostEqual((later - volume) / epsilon, gradient[vertex, axis], places=5)


class ActualLayersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = """
пол = box size=[120,120,10] at=[0,0,-10]
низ = box size=[40,40,0.6] at=[0,0,20]
верх = box size=[30,30,0.6] at=[1,0,28]
слои = drape [низ,верх] on=пол mesh=6 particles=800 steps=40 self={flag}
"""
        cls.colliding = build_ok(template.format(flag="да"))
        cls.unchecked = build_ok(template.format(flag="нет"))

    def test_distinct_layers_do_not_overlap_on_floor(self):
        scene = self.colliding.scene
        lower = scene.objects["слои"].manifold
        upper = scene.objects["слои.02"].manifold
        self.assertLess(abs(float((lower ^ upper).volume())), 1e-4)
        self.assertGreater(upper.bounding_box()[2], lower.bounding_box()[5] - .05)
        self.assertGreater(lower.volume() / scene.objects["низ"].manifold.volume(), .9)
        self.assertGreater(upper.volume() / scene.objects["верх"].manifold.volume(), .9)
        meta = scene.objects["слои"].meta["cloth"]
        self.assertEqual(meta["self_method"], "surfaces")
        self.assertGreater(meta["self_pairs"], 0)
        self.assertTrue(meta["parts_overlap_checked"])
        self.assertTrue(meta["parts_overlap_complete"])
        self.assertLess(meta["strain_p90"], .05)

    def test_disabling_contact_really_changes_the_result(self):
        scene = self.unchecked.scene
        lower = scene.objects["слои"].manifold
        upper = scene.objects["слои.02"].manifold
        self.assertGreater(float((lower ^ upper).volume()), 100.0)
        self.assertEqual(scene.objects["слои"].meta["cloth"]["self_method"], "off")
        self.assertFalse(scene.objects["слои"].meta["cloth"]["parts_overlap_checked"])

    def test_close_initial_layers_preserve_both_material_shells(self):
        # Зазор 0.2 мм меньше толщины стенки. Попарный поиск по всей сцене
        # раньше связывал противоположные листы и терял их собственную толщину.
        result = build_ok("""
пол = box size=[100,100,10] at=[0,0,-10]
низ = box size=[30,30,0.6] at=[0,0,20]
верх = box size=[30,30,0.6] at=[0,0,20.8]
слои = drape [низ,верх] on=пол mesh=6 particles=800 steps=40
""")
        scene = result.scene
        first = scene.objects["слои"].manifold
        second = scene.objects["слои.02"].manifold
        self.assertGreater(first.volume() / scene.objects["низ"].manifold.volume(), .9)
        self.assertGreater(second.volume() / scene.objects["верх"].manifold.volume(), .9)
        self.assertLess(abs((first ^ second).volume()), .02)
        meta = scene.objects["слои"].meta["cloth"]
        self.assertTrue(meta["parts_overlap_complete"])
        if meta["parts_overlap_volume"] > 1e-4:
            self.assertTrue(any(log["level"] == "warn" and "пересечение" in log["message"]
                                for log in scene.logs))

    def test_sideways_gravity_and_explicit_clearance(self):
        result = build_ok("""
стена = box size=[8,100,100] at=[0,0,0]
низ = box size=[0.6,40,40] at=[-22,0,20]
верх = box size=[0.6,30,30] at=[-30,1,24]
слои = drape [низ,верх] on=стена gravity=x+ mesh=6 particles=800 steps=45 self=да self_gap=0.25
""")
        first = result.scene.objects["слои"].manifold
        second = result.scene.objects["слои.02"].manifold
        self.assertLess(abs((first ^ second).volume()), 1e-4)
        self.assertLess(second.bounding_box()[3], first.bounding_box()[0])
        meta = result.scene.objects["слои"].meta["cloth"]
        self.assertEqual(meta["gravity"], [1.0, 0.0, 0.0])
        self.assertAlmostEqual(meta["self_gap"], .25)

    def test_unresolved_intersection_is_reported(self):
        result = build_ok("""
пол = box size=[100,100,10] at=[0,0,-10]
низ = box size=[30,30,0.6] at=[0,0,20]
верх = box size=[30,30,0.6] at=[0,0,20.3]
слои = drape [низ,верх] on=пол mesh=8 particles=400 steps=1 self=да pin=edges
""")
        meta = result.scene.objects["слои"].meta["cloth"]
        self.assertGreater(meta["parts_overlap_volume"], 10)
        self.assertFalse(meta["converged"])
        self.assertTrue(any(log["level"] == "warn" and "равновесие не подтверждено" in log["message"]
                            for log in result.scene.logs))
        self.assertTrue(any(log["level"] == "warn" and "пересечение" in log["message"]
                            for log in result.scene.logs))

    def test_pairwise_check_reports_limit(self):
        box = mf.Manifold.cube((5, 5, 5), True)
        volume, checked, complete = _drape_intersections([box, box.translate((1, 0, 0))])
        self.assertAlmostEqual(volume, 100.0)
        self.assertEqual(checked, 1)
        self.assertTrue(complete)
        _volume, checked, complete = _drape_intersections([box, box], max_checks=0)
        self.assertEqual(checked, 0)
        self.assertFalse(complete)

    def test_negative_boolean_volume_is_not_reported_as_clear(self):
        class BadCommon:
            def __init__(self, value):
                self.value = value

            def status(self):
                return mf.Error.NoError

            def volume(self):
                return self.value

        class BadBody:
            def __init__(self, value):
                self.value = value

            def bounding_box(self):
                return (0, 0, 0, 1, 1, 1)

            def __xor__(self, other):
                return BadCommon(self.value)

        for negative in (-1.0, -1e-12, float('nan')):
            with self.subTest(volume=negative):
                _volume, checked, complete = _drape_intersections([BadBody(negative), BadBody(negative)])
                self.assertEqual(checked, 1)
                self.assertFalse(complete)
                _volume, checked, complete = _drape_support_intersections([BadBody(negative)],
                                                                         [BadBody(negative)])
                self.assertEqual(checked, 1)
                self.assertFalse(complete)

    def test_zero_bend_and_invalid_clearance(self):
        source = ("пол = box size=[80,80,10] at=[0,0,-10]\n"
                  "ткань = box size=[30,30,0.6] at=[0,0,20]\n")
        result = build_ok(source + "итог = drape ткань on=пол mesh=8 steps=4 bend=0 self=нет")
        self.assertEqual(result.scene.objects["итог"].meta["cloth"]["bend"], 0.0)
        invalid = build(source + "итог = drape ткань on=пол self_gap=0.0001", analyze_model=False)
        self.assertFalse(invalid.ok)
        self.assertIn("self_gap", str(invalid.error))

    def test_layered_result_is_deterministic(self):
        script = ("пол = box size=[80,80,10] at=[0,0,-10]\n"
                  "низ = box size=[30,30,0.6] at=[0,0,20]\n"
                  "верх = box size=[24,24,0.6] at=[0,0,25]\n"
                  "итог = drape [низ,верх] on=пол mesh=8 particles=400 steps=30")
        first = build_ok(script).scene.objects["итог.02"].manifold
        second = build_ok(script).scene.objects["итог.02"].manifold
        np.testing.assert_allclose(first.bounding_box(), second.bounding_box(), atol=1e-9)
        self.assertAlmostEqual(first.volume(), second.volume(), places=6)

    def test_card_inserts_existing_objects_and_multiple_supports(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node не установлен")
        command = subprocess.run([node, str(ROOT / "tests" / "interior_tools_test.js"),
                                  "--drape-custom"], check=True, capture_output=True,
                                 text=True, timeout=30).stdout.strip()
        script = """
пол = box size=[120,120,10] at=[0,0,-10]
стол = box size=[30,30,5]
нижний = box size=[40,40,0.6] at=[0,0,20]
верхний = box size=[30,30,0.6] at=[1,0,28]
драпировка = box size=[1,1,1] at=[100,0,0]
""" + command
        result = build_ok(script)
        meta = result.scene.objects["драпировка_2"].meta["cloth"]
        self.assertEqual(meta["parts"], 2)
        self.assertEqual(meta["supports"], 2)
        self.assertAlmostEqual(meta["self_gap"], .25)


class ReadyExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_ok(EXAMPLE.read_text(encoding="utf-8"))

    def test_example_contains_two_separate_layers_and_supports(self):
        scene = self.result.scene
        self.assertEqual(len(self.result.visible_solids()), 5)
        low = scene.objects["слои"].manifold
        high = scene.objects["слои.02"].manifold
        self.assertLess(abs((low ^ high).volume()), 1e-4)
        meta = scene.objects["слои"].meta["cloth"]
        self.assertEqual(meta["supports"], 2)
        self.assertTrue(meta["parts_overlap_checked"])
        self.assertLess(meta["strain_p90"], .1)
        self.assertGreater(low.volume() / scene.objects["низ"].manifold.volume(), .85)
        self.assertGreater(high.volume() / scene.objects["верх"].manifold.volume(), .8)

    def test_hollow_sleeve_deforms_and_retains_most_material(self):
        scene = self.result.scene
        original = scene.objects["рукав"].manifold
        sleeve = scene.objects["уложенный_рукав"].manifold
        before, after = original.bounding_box(), sleeve.bounding_box()
        self.assertLess(after[5] - after[2], .4 * (before[5] - before[2]))
        self.assertGreater(sleeve.volume() / original.volume(), .8)
        self.assertLess(scene.objects["уложенный_рукав"].meta["cloth"]["strain_p90"], .1)


if __name__ == "__main__":
    unittest.main()
