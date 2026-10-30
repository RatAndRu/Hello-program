"""0.58: цельные petaloid-дна, самостоятельные силуэты и готовые проекты."""

from __future__ import annotations

import itertools
import math
import unittest
from collections import defaultdict

import manifold3d as mf
import numpy as np

from forma.geometry import MATERIAL_PRESETS, solid_parts
from forma.run import build
from forma.webui import EXAMPLES, load_example


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


def body(script: str, name: str = "б"):
    result = ok(script)
    obj = result.scene.objects[name]
    assert obj.manifold.status() == mf.Error.NoError
    assert solid_parts(obj.manifold) == 1
    assert obj.manifold.volume() > 0
    assert np.isfinite(obj.manifold.bounding_box()).all()
    return obj


def vertices(manifold: mf.Manifold) -> np.ndarray:
    return np.asarray(manifold.to_mesh().vert_properties, dtype=np.float64)[:, :3]


def slice_volumes(manifold: mf.Manifold, z: float) -> list[float]:
    band = mf.Manifold.cube((200, 200, 0.3), True).translate((0, 0, z))
    cut = manifold ^ band
    assert cut.status() == mf.Error.NoError
    return [float(piece.volume()) for piece in cut.decompose()]


def max_bottom_dihedral(manifold: mf.Manifold) -> float:
    """Угол на рёбрах дна: ранняя версия имела видимые стыки 70…120°."""
    mesh = manifold.to_mesh()
    v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    f = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
    edges = defaultdict(list)
    for index, tri in enumerate(f):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges[tuple(sorted((int(a), int(b))))].append(index)
    normals = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-15)
    result = 0.0
    for (a, b), adjacent in edges.items():
        if len(adjacent) != 2 or (v[a, 2] + v[b, 2]) * 0.5 >= 20.0:
            continue
        cosine = float(np.clip(normals[adjacent[0]] @ normals[adjacent[1]], -1.0, 1.0))
        result = max(result, math.degrees(math.acos(cosine)))
    return result


class BottleSilhouette058Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.styles = ("универсальная", "винная", "бургундская", "пивная", "спортивная")
        cls.bottles = {style: body(f"б = bottle style={style} thread=нет").manifold
                       for style in cls.styles}

    def test_named_styles_are_substantially_different_not_tiny_tweaks(self):
        for first, second in itertools.combinations(self.styles, 2):
            with self.subTest(first=first, second=second):
                a, b = self.bottles[first], self.bottles[second]
                relative = abs(a.volume() - b.volume()) / max(a.volume(), b.volume())
                self.assertGreater(relative, 0.02)
        # Радиусы на нескольких высотах подтверждают именно другой силуэт,
        # а не только другое число треугольников или объём резьбы.
        profiles = set()
        for style, manifold in self.bottles.items():
            profile = []
            for z in (45.0, 80.0, 110.0, 145.0):
                hit = manifold.ray_cast([200, 0, z], [-1, 0, 0])
                self.assertTrue(hit, (style, z))
                profile.append(round(float(hit[0].position[0]), 1))
            profiles.add(tuple(profile))
        self.assertEqual(len(profiles), len(self.styles))

    def test_material_never_changes_geometry_or_locks_bottom_choice(self):
        for bottom in ("плоское", "углубление", "ножки"):
            with self.subTest(bottom=bottom):
                glass = body(f"б = bottle kind=стекло bottom={bottom}").manifold
                plastic = body(f"б = bottle kind=пластик bottom={bottom}").manifold
                self.assertTrue(np.array_equal(vertices(glass), vertices(plastic)))
                self.assertEqual(glass.num_tri(), plastic.num_tri())
                preset_glass = body(f"б = bottle material=стекло bottom={bottom}").manifold
                preset_plastic = body(f"б = bottle material=пластик bottom={bottom}").manifold
                self.assertTrue(np.array_equal(vertices(glass), vertices(preset_glass)))
                self.assertTrue(np.array_equal(vertices(glass), vertices(preset_plastic)))

    def test_explicit_material_and_overrides_are_not_overwritten(self):
        plastic = body("б = bottle material=пластик bottom=ножки")
        self.assertEqual(plastic.density, MATERIAL_PRESETS["пластик"]["density"])
        self.assertEqual(plastic.rough, MATERIAL_PRESETS["пластик"]["rough"])
        custom = body("б = bottle material=пластик transmission=.4 rough=.6 density=1.3")
        self.assertAlmostEqual(custom.transmission, 0.4)
        self.assertAlmostEqual(custom.rough, 0.6)
        self.assertAlmostEqual(custom.density, 1.3)
        jar = body("б = jar material=пластик")
        self.assertEqual(jar.density, MATERIAL_PRESETS["пластик"]["density"])

    def test_petaloid_bottom_is_dense_single_mesh_with_positive_sections(self):
        result = ok("б = bottle style=спортивная kind=пластик bottom=ножки thread=нет")
        self.assertEqual(set(result.scene.objects), {"б"})
        manifold = result.scene.objects["б"].manifold
        self.assertGreater(manifold.num_tri(), 30000)
        self.assertAlmostEqual(manifold.bounding_box()[2], 0.0, delta=1e-5)
        for z in np.arange(0.5, 14.01, 0.5):
            with self.subTest(z=float(z)):
                volumes = slice_volumes(manifold, float(z))
                self.assertTrue(volumes)
                self.assertTrue(all(value > 1e-7 for value in volumes), volumes)
        self.assertEqual(len(slice_volumes(manifold, 0.5)), 5)
        self.assertEqual(len(slice_volumes(manifold, 5.0)), 5)

    def test_feet_count_controls_real_continuous_lobes(self):
        for count in range(3, 9):
            with self.subTest(count=count):
                manifold = body(f"б = bottle bottom=ножки feet_count={count} thread=нет").manifold
                self.assertEqual(len(slice_volumes(manifold, 0.5)), count)
                self.assertEqual(solid_parts(manifold), 1)
                self.assertLess(max_bottom_dihedral(manifold), 30.0)


class JarSilhouette058Test(unittest.TestCase):
    def test_jar_styles_have_distinct_volumes_and_profiles(self):
        styles = ("классическая", "коническая", "амфора")
        jars = {style: body(f"б = jar style={style} thread=нет").manifold for style in styles}
        for first, second in itertools.combinations(styles, 2):
            with self.subTest(first=first, second=second):
                a, b = jars[first], jars[second]
                self.assertGreater(abs(a.volume() - b.volume()) / max(a.volume(), b.volume()), 0.05)
        radii = set()
        for style, manifold in jars.items():
            values = []
            for z in (35.0, 60.0, 80.0):
                hit = manifold.ray_cast([200, 0, z], [-1, 0, 0])
                self.assertTrue(hit, (style, z))
                values.append(round(float(hit[0].position[0]), 1))
            radii.add(tuple(values))
        self.assertEqual(len(radii), 3)

    def test_threaded_styles_export_clean_watertight_glb(self):
        import io
        import trimesh
        from forma.geometry import export_glb

        for style in ("классическая", "коническая", "амфора"):
            with self.subTest(style=style):
                obj = body(f"б = jar style={style} thread=да")
                data = export_glb([obj])
                scene = trimesh.load(io.BytesIO(data), file_type="glb",
                                     force="scene", process=False)
                self.assertEqual(len(scene.geometry), 1)
                mesh = next(iter(scene.geometry.values()))
                mesh.merge_vertices(merge_tex=True, merge_norm=True)
                self.assertTrue(np.all(mesh.area_faces > 1e-12))
                self.assertTrue(mesh.is_watertight)
                self.assertTrue(mesh.is_winding_consistent)
                self.assertGreater(mesh.volume, 0.0)


class LidMaterial058Test(unittest.TestCase):
    def test_legacy_card_material_is_valid_for_small_lids(self):
        for kind in ("банка", "бутылка"):
            with self.subTest(kind=kind):
                obj = body(f"б = lid kind={kind} material=металл handle=кнопка vent=да", "б")
                self.assertEqual(obj.metal, 1.0)
                self.assertEqual(obj.rough, MATERIAL_PRESETS["металл"]["rough"])
                self.assertEqual(obj.density, MATERIAL_PRESETS["металл"]["density"])


class ReadyProjects058Test(unittest.TestCase):
    def test_room_and_train_are_listed_as_ready_projects(self):
        expected = {
            "living_room_diorama": "Комната: гостиная 1:20",
            "train_carriage": "Поезд: плацкартный вагон 61-4194",
        }
        catalog = dict((key, title) for title, key in EXAMPLES)
        self.assertEqual(len(EXAMPLES), 20)
        for key, title in expected.items():
            with self.subTest(project=key):
                self.assertEqual(catalog.get(key), title)
                script = load_example(key)
                self.assertGreater(len(script), 10000)
                self.assertNotIn("import", script.lower())
        # Детальные геометрические приёмки этих сцен остаются в
        # test_living_room_052.py и test_train_carriage.py.


if __name__ == "__main__":
    unittest.main()
