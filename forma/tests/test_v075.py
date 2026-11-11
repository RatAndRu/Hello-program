"""0.75.0: драпировка равновесием вместо карты высот.

Старый `drape` проецировал узел на высотную карту опоры: поднутрения и
свисающие края он не видел вовсе. Новый считает контакт по треугольникам всех
опор, удерживает длины рёбер связями, а толстые куски держит формой. Здесь
проверяется именно это — по факту, через сборку сцены:

* гравитация задаётся словом, осью или вектором, а число осталось старым `g`;
* лист ложится на стол и свисает до пола, а не «прилипает» к верхней карте;
* несколько опор работают одновременно;
* кубик падает как тело, лист мнётся;
* толщина тонкой оболочки не исчезает: пара «сквозь толщину» держит размер;
* прежние имена параметров (`detail`, `iterations`, `constraints`, `gap`, `z`)
  продолжают собираться, чтобы старые `.forma` не сломались;
* расчёт детерминирован: две одинаковые сборки дают одно и то же.
"""

from __future__ import annotations

import unittest

import numpy as np

from forma import cloth
from forma.errors import GeometryError
from forma.geometry import manifold_mesh
from forma.run import build
from forma import ops_interior


def build_ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"сборка не прошла: {result.error}")
    return result


def box(size, at=(0.0, 0.0, 0.0)):
    """Замкнутая коробка в мировых координатах — как `box … at=…` в .forma."""
    half = np.asarray(size, dtype=float) * 0.5
    corners = np.array([[x, y, z] for x in (-half[0], half[0])
                        for y in (-half[1], half[1]) for z in (-half[2], half[2])])
    corners = corners + np.asarray(at, dtype=float)
    quads = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return corners, np.asarray(quads, dtype=np.int64)


class GravityTest(unittest.TestCase):
    def test_words_axes_and_vectors(self):
        for text, expected in (("z-", (0, 0, -1)), ("вниз", (0, 0, -1)), ("вверх", (0, 0, 1)),
                               ("x+", (1, 0, 0)), ("-y", (0, -1, 0)), ("[0,0,-2]", (0, 0, -1)),
                               ("[1,0,0]", (1, 0, 0))):
            with self.subTest(text=text):
                np.testing.assert_allclose(cloth.parse_gravity(text), expected, atol=1e-9)

    def test_empty_means_down_and_zero_stays_zero(self):
        np.testing.assert_allclose(cloth.parse_gravity(""), (0, 0, -1))
        np.testing.assert_allclose(cloth.parse_gravity("[0,0,0]"), (0, 0, 0))

    def test_unknown_word_is_explained(self):
        with self.assertRaises(GeometryError) as caught:
            cloth.parse_gravity("вбок")
        self.assertIn("gravity", str(caught.exception))


class MeshPreparationTest(unittest.TestCase):
    def test_subdivision_keeps_shell_closed_and_within_budget(self):
        vertices, faces = box((150, 150, 0.4))
        dense, dense_faces = cloth.subdivide_to(vertices, faces, 4.0, 4000)
        self.assertLessEqual(len(dense), 4000)
        self.assertTrue(cloth.is_closed(dense_faces))
        used = np.unique(dense_faces)
        self.assertEqual(len(used), len(dense))          # нет «висячих» вершин
        edges = np.concatenate((dense_faces[:, [0, 1]], dense_faces[:, [1, 2]],
                                dense_faces[:, [2, 0]]), axis=0)
        lengths = np.linalg.norm(dense[edges[:, 0]] - dense[edges[:, 1]], axis=1)
        self.assertGreater(float(lengths.min()), 0.02)   # без микроскопических рёбер
        self.assertLess(float(np.median(lengths)), 6.0)
        self.assertLess(float(lengths.max()), 0.2 * 150.0)   # длинные рёбра раздроблены

    def test_open_surface_is_not_closed(self):
        vertices, faces = box((20, 20, 0.2))
        self.assertTrue(cloth.is_closed(faces))
        self.assertFalse(cloth.is_closed(faces[:-4]))    # сняли дно — оболочка открыта


class ShellThicknessTest(unittest.TestCase):
    def test_pairs_hold_the_original_thickness(self):
        vertices, faces = box((120, 90, 0.4), (0, 0, 60))
        vertices, faces = cloth.subdivide_to(vertices, faces, 4.0, 2000)
        pairs, rest = cloth.shell_pairs(vertices, faces, 0.4)
        self.assertGreater(len(pairs), 100)
        self.assertAlmostEqual(float(np.median(rest)), 0.4, delta=0.05)
        supports = box((300, 300, 40), (0, 0, -20))[0][box((300, 300, 40), (0, 0, -20))[1]]
        report = cloth.simulate(vertices, faces, supports,
                                gravity=cloth.parse_gravity("z-"), thickness=0.4,
                                steps=30, iterations=10, self_collision=False)
        moved = report["vertices"]
        lengths = np.linalg.norm(moved[pairs[:, 1]] - moved[pairs[:, 0]], axis=1)
        self.assertLess(float(np.median(np.abs(lengths - rest))), 0.1)
        self.assertGreater(float(np.median(lengths)), 0.5 * 0.4)


class DrapeSceneTest(unittest.TestCase):
    def test_tablecloth_lies_on_table_and_reaches_floor(self):
        result = build_ok("""
лист = box size=[200,200,0.4] at=[0,0,70]
стол = box size=[80,80,40]
пол = box size=[400,400,20] at=[0,0,-20]
скатерть = drape лист on=[стол, пол] mesh=4
""")
        meta = result.scene.objects["скатерть"].meta["cloth"]
        self.assertGreater(meta["contacts"], 100)
        self.assertEqual(meta["supports"], 2)
        self.assertEqual(meta["parts"], 1)
        self.assertLess(meta["strain_p90"], 0.35)
        bounds = result.scene.objects["скатерть"].manifold.bounding_box()
        self.assertAlmostEqual(bounds[2], 0.0, delta=0.3)      # лежит на полу
        self.assertAlmostEqual(bounds[5], 40.0, delta=0.6)     # лежит на столе
        self.assertFalse(result.scene.objects["лист"].visible)

    def test_several_supports_shape_one_sheet(self):
        result = build_ok("""
лист = box size=[170,60,0.4] at=[0,0,60]
тумба1 = box size=[40,40,30] at=[-55,0,0]
тумба2 = box size=[40,40,30] at=[55,0,0]
мост = drape лист on=[тумба1, тумба2] mesh=4
""")
        meta = result.scene.objects["мост"].meta["cloth"]
        self.assertEqual(meta["supports"], 2)
        self.assertGreater(meta["contacts"], 50)
        bounds = result.scene.objects["мост"].manifold.bounding_box()
        self.assertGreater(bounds[5], 28.0)                    # верх на тумбах
        self.assertLess(bounds[2], 10.0)                       # края свисают

    def test_cube_falls_as_a_body(self):
        result = build_ok("""
кубик = box size=[30,30,30] at=[0,0,90]
стол = box size=[120,120,20]
упал = drape кубик on=стол mesh=4
""")
        meta = result.scene.objects["упал"].meta["cloth"]
        self.assertGreater(meta["rigid"], 0.9)                 # жёсткий кусок
        self.assertLess(meta["strain_p90"], 0.05)              # форма сохранена
        bounds = result.scene.objects["упал"].manifold.bounding_box()
        self.assertAlmostEqual(bounds[2], 20.0, delta=0.3)     # стоит на столе
        self.assertAlmostEqual(bounds[5] - bounds[2], 30.0, delta=0.4)

    def test_two_parts_are_draped_in_one_call(self):
        result = build_ok("""
плита = box size=[70,40,0.4] at=[-45,0,70]
плита2 = box size=[70,40,0.4] at=[45,0,70]
пол = box size=[400,400,20] at=[0,0,-20]
обе = drape [плита, плита2] on=пол mesh=5
""")
        meta = result.scene.objects["обе"].meta["cloth"]
        self.assertEqual(meta["parts"], 2)
        self.assertIn("обе.02", result.scene.objects)
        bounds = result.scene.objects["обе"].manifold.bounding_box()
        self.assertLess(bounds[2], 0.6)

    def test_side_gravity_presses_against_a_wall(self):
        # Гравитация вбок: пол превращается в стену, лист прижимается к ней,
        # а не падает вниз. Ось гравитации действительно меняет сцену.
        result = build_ok("""
лист = box size=[80,80,0.4] at=[-60,0,60]
стена = box size=[20,200,160] at=[0,0,0]
боком = drape лист on=стена gravity=x+ mesh=4
""")
        bounds = result.scene.objects["боком"].manifold.bounding_box()
        self.assertLess(bounds[3], 0.6)                        # прижат к стене
        self.assertGreater(bounds[0], -60.0)   # не улетел от стены
        self.assertLess(bounds[5] - bounds[2], 90.0)           # не растянут в высоту


class DrapeCompatibilityTest(unittest.TestCase):
    def test_numeric_gravity_is_still_the_old_acceleration(self):
        result = build_ok("""
лист = box size=[60,60,0.4] at=[0,0,40]
пол = box size=[400,400,20] at=[0,0,-20]
мягко = drape лист on=пол gravity=0.15 mesh=5
""")
        meta = result.scene.objects["мягко"].meta["cloth"]
        self.assertAlmostEqual(meta["g"], 0.15, places=6)
        self.assertEqual(meta["gravity"], [0.0, 0.0, -1.0])

    def test_legacy_parameter_names_still_build(self):
        result = build_ok("""
ткань = box size=[60,40,0.3] at=[0,0,20]
опора = box size=[40,30,15] at=[0,0,0]
d = drape [ткань] on=опора detail=12 iterations=20 constraints=8
    stiffness=0.9 bend=0.12 damping=0.86 gap=0.05 thickness=0.15 pin=none
""".replace("\n    ", " "))
        meta = result.scene.objects["d"].meta["cloth"]
        self.assertGreater(meta["vertices"], 100)
        self.assertLessEqual(meta["vertices"], 6 * 12 * 12 + 400)
        self.assertAlmostEqual(meta["thickness"], 0.15, places=3)

    def test_floor_level_replaces_missing_supports(self):
        result = build_ok("cloth = box size=[60,40,0.3] at=[0,0,20]\n"
                          "d = drape [cloth] z=0 mesh=5 pin=none")
        bounds = result.scene.objects["d"].manifold.bounding_box()
        self.assertAlmostEqual(bounds[2], 0.0, delta=0.3)

    def test_without_supports_and_floor_the_reason_is_clear(self):
        result = build("cloth = box size=[60,40,0.3] at=[0,0,20]\nd = drape [cloth]")
        self.assertFalse(result.ok)
        self.assertIn("опор", str(result.error["message"]).lower())

    def test_self_flag_turns_collision_off(self):
        script = ("лист = box size=[50,50,0.4] at=[0,0,40]\n"
                  "пол = box size=[300,300,20] at=[0,0,-20]\n"
                  "d = drape лист on=пол mesh=5 self=нет\n")
        result = build_ok(script)
        self.assertFalse(result.scene.objects["d"].meta["cloth"]["self_collision"])

    def test_pins_keep_nodes_exactly_where_they_were(self):
        vertices, faces = box((60, 60, 0.4), (0, 0, 40))
        vertices, faces = cloth.subdivide_to(vertices, faces, 5.0, 1500)
        supports = box((300, 300, 20), (0, 0, -20))
        supports_flat = supports[0][supports[1]]
        pinned = vertices[:, 0] < vertices[:, 0].min() + 1e-6
        report = cloth.simulate(vertices, faces, supports_flat,
                                gravity=cloth.parse_gravity("z-"), thickness=0.4,
                                steps=25, iterations=10, pinned=pinned,
                                self_collision=False)
        moved = report["vertices"]
        # Закрепление относится к исходным координатам, а не к искусственной
        # постановке детали у опоры. Свободные узлы при этом должны опускаться.
        np.testing.assert_array_equal(moved[pinned], vertices[pinned])
        self.assertLess(float(moved[~pinned][:, 2].min()),
                        float(vertices[~pinned][:, 2].min()) - 0.1)
        self.assertGreater(float(moved[~pinned][:, 2].min()),
                           float(moved[pinned][:, 2].min()) - 30.0)

    def test_result_is_deterministic(self):
        script = ("лист = box size=[70,70,0.4] at=[0,0,50]\n"
                  "пол = box size=[300,300,20] at=[0,0,-20]\n"
                  "d = drape лист on=пол mesh=5\n")
        first = build_ok(script).scene.objects["d"].manifold
        second = build_ok(script).scene.objects["d"].manifold
        np.testing.assert_allclose(first.bounding_box(), second.bounding_box(), atol=1e-9)
        self.assertAlmostEqual(first.volume(), second.volume(), places=6)


class WireAndChainTest(unittest.TestCase):
    """Тонкая проволока — не ткань: толщина считается ещё и относительно размера."""

    def test_relative_thickness_separates_wire_from_sheet(self):
        sheet = box((200, 200, 0.4))
        self.assertLess(cloth.auto_rigid(*sheet), 0.1)          # скатерть гнётся
        cube = box((30, 30, 30))
        self.assertGreater(cloth.auto_rigid(*cube), 0.9)        # кубик держит форму

    def test_chain_lies_on_table_and_keeps_its_links(self):
        result = build_ok("""
стол = box size=[120,120,10]
звенья = цепь links=4 size=26 wire=3.2 at=[0,0,60]
лежит = drape [звенья] on=[стол]
""")
        before = result.scene.objects["звенья"].manifold.bounding_box()
        solid = result.scene.objects["лежит"]
        meta = solid.meta["cloth"]
        bounds = solid.manifold.bounding_box()
        length_before = float(before[3] - before[0])
        self.assertGreater(meta["rigid"], 0.8)                  # звено — тело
        self.assertLess(meta["strain_p90"], 0.2)                # проволока не растянута
        self.assertAlmostEqual(bounds[2], 10.0, delta=0.6)      # лежит на столе
        self.assertGreater(float(bounds[3] - bounds[0]), 0.8 * length_before)
        self.assertLess(float(bounds[5] - bounds[2]), 0.5 * length_before)

    def test_thin_wire_is_not_squashed_by_self_collision(self):
        """Толщина самоколлизии — «2V/A», а не габарит: иначе цепь раздувает."""
        result = build_ok("""
стол = box size=[120,120,10]
звенья = цепь links=3 size=20 wire=2.5 at=[0,0,50]
лежит = drape [звенья] on=[стол] mesh=2.5
""")
        meta = result.scene.objects["лежит"].meta["cloth"]
        self.assertLess(meta["penetration"], 1.0)
        self.assertLess(meta["strain_p90"], 0.25)


class HeightMapRemovedTest(unittest.TestCase):
    def test_old_height_map_helpers_are_gone(self):
        for name in ("_HeightMap", "_top_surface", "_subdivide_surface",
                     "_edge_graph", "_edge_colors"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(ops_interior, name))

    def test_cloth_engine_is_used_by_the_command(self):
        self.assertTrue(hasattr(cloth, "simulate"))
        self.assertTrue(hasattr(cloth, "SupportField"))
        self.assertTrue(hasattr(cloth, "shell_pairs"))


if __name__ == "__main__":
    unittest.main()
