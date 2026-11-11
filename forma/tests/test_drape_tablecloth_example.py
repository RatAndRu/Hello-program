"""Проверки двух готовых сцен; они не доказывают равновесие ткани."""
from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from forma.geometry import manifold_mesh
from forma.run import build

try:
    import fcl
except ImportError:
    fcl = None


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE = EXAMPLES / "drape_tablecloth_dense_076.forma"
DETAIL = EXAMPLES / "drape_atelier_detail_076.forma"
SUPPORTS = ("столешница", "ножка_левая_передняя", "ножка_правая_передняя",
            "ножка_левая_задняя", "ножка_правая_задняя", "пол")


def _fcl_object(vertices, faces):
    model = fcl.BVHModel()
    model.beginModel(len(vertices), len(faces))
    model.addSubModel(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


class TableclothExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(EXAMPLE.read_text(encoding="utf-8"),
                           analyze_model=False, base_dir=EXAMPLE.parent)
        if not cls.result.ok:
            raise AssertionError(f"Сценарий не собрался: {cls.result.error}")
        cls.tablecloth = cls.result.scene.objects["скатерть"]
        cls.vertices, cls.faces = manifold_mesh(cls.tablecloth.manifold)

    def test_standalone_scene_has_dense_mesh_and_six_supports(self):
        visible = {solid.name for solid in self.result.visible_solids()}
        self.assertEqual(visible, set(SUPPORTS) | {"скатерть"})
        meta = self.tablecloth.meta["cloth"]
        self.assertEqual(meta["supports"], 6)
        self.assertTrue(meta["mesh_complete"])
        self.assertGreaterEqual(len(self.vertices), 2000)
        self.assertGreaterEqual(len(self.faces), 4000)
        self.assertIsInstance(meta["equilibrium_verified"], bool)
        if not meta["converged"]:
            self.assertFalse(meta["equilibrium_verified"])
            self.assertTrue(any("равновесие не подтверждено" in item["message"]
                                for item in self.result.scene.logs))

    def test_all_four_edges_hang_and_bounded_checks_find_no_intersections(self):
        v = self.vertices
        center = (np.abs(v[:, 0]) < 25) & (np.abs(v[:, 1]) < 25)
        self.assertGreater(int(center.sum()), 10)
        center_height = float(np.median(v[center, 2]))
        edges = (("left", v[:, 0] < -50), ("right", v[:, 0] > 50),
                 ("front", v[:, 1] < -50), ("back", v[:, 1] > 50))
        for name, edge in edges:
            with self.subTest(side=name):
                self.assertGreater(int(edge.sum()), 10)
                self.assertGreater(center_height - float(np.median(v[edge, 2])), 5.0)
        meta = self.tablecloth.meta["cloth"]
        self.assertTrue(meta["self_intersections_complete"])
        self.assertEqual(meta["self_intersections"], 0)
        self.assertEqual(meta["self_intersections_adjacent"], 0)
        self.assertTrue(meta["support_surface_complete"])
        self.assertEqual(meta["support_surface_pairs"], 0)
        self.assertTrue(meta["support_overlap_complete"])
        self.assertEqual(meta["support_overlap_volume"], 0.0)

    @unittest.skipIf(fcl is None, "python-fcl — необязательная независимая проверка")
    def test_fcl_finds_no_nonadjacent_contacts_or_support_crossings(self):
        body = _fcl_object(self.vertices, self.faces)
        result = fcl.CollisionResult()
        limit = 300_000
        fcl.collide(body, body, fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), result)
        self.assertLess(len(result.contacts), limit, "проверка FCL не завершена")
        crossed = {tuple(sorted((int(contact.b1), int(contact.b2))))
                   for contact in result.contacts
                   if 0 <= contact.b1 < len(self.faces) and 0 <= contact.b2 < len(self.faces)
                   and contact.b1 != contact.b2
                   and not set(self.faces[contact.b1]).intersection(self.faces[contact.b2])}
        self.assertFalse(crossed)
        for name in SUPPORTS:
            with self.subTest(support=name):
                support = _fcl_object(*manifold_mesh(self.result.scene.objects[name].manifold))
                contacts = fcl.CollisionResult()
                self.assertEqual(fcl.collide(body, support, fcl.CollisionRequest(num_max_contacts=1), contacts), 0)


class DetailedAtelierExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(DETAIL.read_text(encoding="utf-8"),
                           analyze_model=False, base_dir=DETAIL.parent)
        if not cls.result.ok:
            raise AssertionError(f"Сценарий не собрался: {cls.result.error}")

    def test_same_objects_use_a_finer_mesh_and_sleeve_deforms(self):
        visible = {solid.name for solid in self.result.visible_solids()}
        required = {"слои", "слои.02", "упавший_рукав", "упавший_шар", "скатерть"} | set(SUPPORTS)
        self.assertEqual(visible, required)
        # Нижние границы выше числа вершин для обычной сцены 077 на этой версии.
        minimum = {"слои": 1000, "слои.02": 700, "упавший_рукав": 1000,
                   "упавший_шар": 1500, "скатерть": 2000}
        for name, count in minimum.items():
            with self.subTest(object=name):
                vertices, _faces = manifold_mesh(self.result.scene.objects[name].manifold)
                self.assertGreater(len(vertices), count)
        sleeve = self.result.scene.objects["упавший_рукав"]
        bounds = sleeve.manifold.bounding_box()
        self.assertLess(bounds[5] - bounds[2], 18.0)  # исходная высота 22 мм
        low = self.result.scene.objects["слои"].manifold
        high = self.result.scene.objects["слои.02"].manifold
        self.assertLess(abs(float((low ^ high).volume())), 1e-4)
        for name in ("слои", "упавший_рукав", "упавший_шар", "скатерть"):
            with self.subTest(drape=name):
                meta = self.result.scene.objects[name].meta["cloth"]
                self.assertTrue(meta["mesh_complete"])
                self.assertTrue(meta["self_intersections_complete"])
                self.assertEqual(meta["self_intersections"], 0)
                self.assertEqual(meta["self_intersections_adjacent"], 0)
                self.assertTrue(meta["support_overlap_complete"])
                self.assertEqual(meta["support_overlap_volume"], 0.0)

    def test_tablecloth_edges_hang_on_every_side(self):
        vertices, _faces = manifold_mesh(self.result.scene.objects["скатерть"].manifold)
        center = (np.abs(vertices[:, 0] - 150) < 25) & (np.abs(vertices[:, 1]) < 25)
        height = float(np.median(vertices[center, 2]))
        edges = (("left", vertices[:, 0] - 150 < -50), ("right", vertices[:, 0] - 150 > 50),
                 ("front", vertices[:, 1] < -50), ("back", vertices[:, 1] > 50))
        for name, edge in edges:
            with self.subTest(side=name):
                self.assertGreater(int(edge.sum()), 10)
                self.assertGreater(height - float(np.median(vertices[edge, 2])), 5.0)

    @unittest.skipIf(fcl is None, "python-fcl — необязательная независимая проверка")
    def test_fcl_checks_surfaces_and_opposite_layers(self):
        solids = self.result.scene.objects
        meshes = {name: manifold_mesh(solids[name].manifold)
                  for name in ("слои", "слои.02", "упавший_рукав", "упавший_шар", "скатерть")}
        objects = {name: _fcl_object(*mesh) for name, mesh in meshes.items()}
        limit = 300_000
        for name, obj in objects.items():
            with self.subTest(object=name):
                faces = meshes[name][1]
                result = fcl.CollisionResult()
                fcl.collide(obj, obj, fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), result)
                self.assertLess(len(result.contacts), limit, "проверка FCL не завершена")
                crossed = {tuple(sorted((int(c.b1), int(c.b2)))) for c in result.contacts
                           if 0 <= c.b1 < len(faces) and 0 <= c.b2 < len(faces)
                           and c.b1 != c.b2 and not set(faces[c.b1]).intersection(faces[c.b2])}
                self.assertFalse(crossed)
        for first, second in (("слои", "слои.02"), ("слои", "пол"), ("слои.02", "пол"),
                              ("упавший_рукав", "пол"), ("упавший_шар", "пол"),
                              *(("скатерть", name) for name in SUPPORTS)):
            with self.subTest(first=first, second=second):
                target = objects[second] if second in objects else _fcl_object(*manifold_mesh(solids[second].manifold))
                contact = fcl.CollisionResult()
                self.assertEqual(fcl.collide(objects[first], target, fcl.CollisionRequest(num_max_contacts=1), contact), 0)


if __name__ == "__main__":
    unittest.main()
