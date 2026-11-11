"""Облегчённые сцены: полный путь сборки UI, GLB и проверки геометрии.

Это регрессии конкретных примеров, а не доказательство равновесия или
непроницаемости для всех возможных сцен. python-fcl необязателен для CI.
"""
from __future__ import annotations

import io
from itertools import combinations
import os
from pathlib import Path
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

from forma.cloth_check import _ADJACENT_INSET
from forma.geometry import manifold_mesh
from forma.webui import AppState

try:
    import fcl
except ImportError:
    fcl = None


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SUPPORTS = ("столешница", "ножка_левая_передняя", "ножка_правая_передняя",
            "ножка_левая_задняя", "ножка_правая_задняя", "пол")
SCENES = {
    "table": ("drape_tablecloth_fast_076.forma", {"скатерть"} | set(SUPPORTS), 5000),
    "atelier": ("drape_atelier_fast_076.forma",
                {"слои", "слои.02", "упавший_рукав", "упавший_шар", "скатерть"}
                | set(SUPPORTS), 10000),
}


def _fcl_object(vertices, faces):
    model = fcl.BVHModel()
    model.beginModel(len(vertices), len(faces))
    model.addSubModel(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


def _self_pairs(vertices, faces, adjacent):
    """Возвращает пары FCL и признак, что контактный лимит не исчерпан."""
    if adjacent:
        triangles = vertices[faces]
        inset = triangles + (triangles.mean(axis=1)[:, None, :] - triangles) * _ADJACENT_INSET
        mesh = _fcl_object(inset.reshape(-1, 3), np.arange(3 * len(faces)).reshape(-1, 3))
    else:
        mesh = _fcl_object(vertices, faces)
    result = fcl.CollisionResult()
    limit = 300_000
    fcl.collide(mesh, mesh, fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), result)
    pairs = set()
    for contact in result.contacts:
        a, b = int(contact.b1), int(contact.b2)
        if not (0 <= a < len(faces) and 0 <= b < len(faces)) or a == b:
            continue
        share_vertex = bool(set(faces[a]).intersection(faces[b]))
        if share_vertex == adjacent:
            pairs.add(tuple(sorted((a, b))))
    return pairs, len(result.contacts) < limit


class FastDrapeExamplesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tempdir.cleanup)
        cls.built = {}
        for key, (filename, _expected, _limit) in SCENES.items():
            with patch.dict(os.environ, {"FORMA_DATA": cls.tempdir.name}):
                state = AppState()
            script = (EXAMPLES / filename).read_text(encoding="utf-8")
            # Тот же AppState.build, что обслуживает /api/build, с полным анализом.
            started = perf_counter()
            payload = state.build(script, auto=False)
            elapsed = perf_counter() - started
            if not payload.get("ok") or payload.get("paused"):
                raise AssertionError(f"{filename}: сценарий не собрался: {payload.get('error')}")
            print(f"\n{filename}: полный AppState.build {elapsed:.2f} с")
            cls.built[key] = (state, payload)

    def test_visible_and_exported_triangle_budgets(self):
        for key, (_filename, expected, lightweight_limit) in SCENES.items():
            with self.subTest(scene=key):
                state, payload = self.built[key]
                solids = state.last_build.visible_solids()
                self.assertEqual({solid.name for solid in solids}, expected)
                visible_tris = sum(len(manifold_mesh(solid.manifold)[1]) for solid in solids)
                started = perf_counter()
                glb = state.glb()
                glb_seconds = perf_counter() - started
                loaded = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene", process=False)
                glb_tris = sum(len(mesh.faces) for mesh in loaded.geometry.values())
                print(f"\n{key}: видимых трис {visible_tris}, в GLB {glb_tris}; "
                      f"GLB {len(glb)} байт за {glb_seconds:.2f} с")
                self.assertGreater(visible_tris, 0)
                self.assertEqual(glb_tris, visible_tris)
                self.assertLessEqual(visible_tris, 100_000)
                self.assertLessEqual(int(payload["analysis"]["metrics"]["tris"]), 100_000)
                # Более строгий потолок защищает именно облегчённость примеров.
                self.assertLess(visible_tris, lightweight_limit)

    def test_hanging_cloth_and_bounded_builtin_checks(self):
        for key in SCENES:
            with self.subTest(scene=key):
                state, _payload = self.built[key]
                scene = state.last_build.scene
                cloth = scene.objects["скатерть"]
                vertices, _faces = manifold_mesh(cloth.manifold)
                offset = 150 if key == "atelier" else 0
                x = vertices[:, 0] - offset
                y = vertices[:, 1]
                center = (np.abs(x) < 25) & (np.abs(y) < 25)
                self.assertGreater(int(center.sum()), 10)
                height = float(np.median(vertices[center, 2]))
                for side, edge in (("left", x < -50), ("right", x > 50),
                                   ("front", y < -50), ("back", y > 50)):
                    with self.subTest(side=side):
                        self.assertGreater(int(edge.sum()), 10)
                        self.assertGreater(height - float(np.median(vertices[edge, 2])), 10.0)
                meta = cloth.meta["cloth"]
                self.assertEqual(meta["supports"], 6)
                self.assertTrue(meta["mesh_complete"])
                self.assertTrue(meta["self_intersections_complete"])
                self.assertEqual(meta["self_intersections"], 0)
                self.assertEqual(meta["self_intersections_adjacent"], 0)
                self.assertTrue(meta["support_surface_complete"])
                self.assertEqual(meta["support_surface_pairs"], 0)
                self.assertTrue(meta["support_overlap_complete"])
                self.assertEqual(meta["support_overlap_volume"], 0.0)
                if not meta["converged"]:
                    self.assertFalse(meta["equilibrium_verified"])
                    self.assertTrue(any("равновесие не подтверждено" in item["message"]
                                        for item in scene.logs))

    def test_atelier_keeps_separate_layers_a_hollow_sleeve_and_ball(self):
        scene = self.built["atelier"][0].last_build.scene
        lower = scene.objects["слои"].manifold
        upper = scene.objects["слои.02"].manifold
        self.assertLess(abs(float((lower ^ upper).volume())), 1e-4)
        sleeve = scene.objects["упавший_рукав"].manifold
        bounds = sleeve.bounding_box()
        self.assertLess(bounds[5] - bounds[2], 18.0)  # исходный диаметр 22 мм
        vertices, faces = manifold_mesh(sleeve)
        sleeve_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        self.assertTrue(sleeve_mesh.is_watertight)
        self.assertEqual(sleeve_mesh.euler_number, 0)  # замкнутая поверхность с отверстием
        ball = scene.objects["упавший_шар"].manifold
        ball_bounds = ball.bounding_box()
        self.assertGreater(ball_bounds[3] - ball_bounds[0], 30.0)
        self.assertGreater(ball_bounds[5] - ball_bounds[2], 30.0)

    @unittest.skipIf(fcl is None, "python-fcl — необязательная независимая проверка")
    def test_fcl_surfaces_of_both_scenes(self):
        for key in SCENES:
            with self.subTest(scene=key):
                scene = self.built[key][0].last_build.scene
                names = (["скатерть"] if key == "table" else
                         ["слои", "слои.02", "упавший_рукав", "упавший_шар", "скатерть"])
                meshes = {name: manifold_mesh(scene.objects[name].manifold) for name in names}
                objects = {name: _fcl_object(*mesh) for name, mesh in meshes.items()}
                for name, (vertices, faces) in meshes.items():
                    for adjacent in (False, True):
                        with self.subTest(object=name, adjacent=adjacent):
                            pairs, complete = _self_pairs(vertices, faces, adjacent)
                            self.assertTrue(complete, "проверка FCL не завершена")
                            self.assertFalse(pairs)
                support_objects = {name: _fcl_object(*manifold_mesh(scene.objects[name].manifold))
                                   for name in SUPPORTS}
                # Проверяем не только пол для каждого объекта, но и все остальные
                # опоры, а также поверхности самих падающих объектов друг с другом.
                pairs = list(combinations(names, 2)) + [(name, support) for name in names
                                                        for support in SUPPORTS]
                for first, second in pairs:
                    with self.subTest(first=first, second=second):
                        target = objects[second] if second in objects else support_objects[second]
                        result = fcl.CollisionResult()
                        self.assertEqual(fcl.collide(objects[first], target,
                                                    fcl.CollisionRequest(num_max_contacts=1), result), 0)


if __name__ == "__main__":
    unittest.main()
