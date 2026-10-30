"""Геометрическая приёмка обновлённых половин, значков и фурнитуры."""

from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

from forma.ops import OPS, lookup
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


def obj(script: str, name: str = "о"):
    return ok(script).scene.objects[name]


def valid(m: mf.Manifold, one: bool = True):
    if m.status() != mf.Error.NoError or m.is_empty() or m.volume() <= 1e-7:
        raise AssertionError((m.status(), m.volume(), m.bounding_box()))
    positive = [p for p in m.decompose() if p.volume() > 1e-6]
    if one and len(positive) != 1:
        raise AssertionError([(p.volume(), p.bounding_box()) for p in positive])
    return m


def size(m: mf.Manifold) -> np.ndarray:
    bb = m.bounding_box()
    return np.asarray(bb[3:]) - np.asarray(bb[:3])


def glb_json(data: bytes) -> dict:
    magic, version, total = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or total != len(data):
        raise AssertionError("некорректный GLB-контейнер")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A:
        raise AssertionError("первый GLB chunk не JSON")
    return json.loads(data[20:20 + length])


class InflatedGlyphGeometryTest(unittest.TestCase):
    def test_front_surface_is_curved_and_extrema_survive(self):
        cases = (
            ("heart", "width=60 depth=18", (0, -200, 27), (0, 200, 27), 1, 18),
            ("lightning", "height=100 width=44 depth=10", (0, -200, 50),
             (0, 200, 50), 1, 10),
            ("crescent", "radius=50 thickness=18 depth=12", (-20, -200, 50),
             (-20, 200, 50), 1, 12),
            ("star", "outer=60 inner=25 depth=12 plane=плашмя", (20, 0, 200),
             (20, 0, -200), 2, 12),
        )
        for op, params, start, end, axis, depth in cases:
            with self.subTest(op=op):
                m = valid(obj(f"о = {op} {params} volume=да").manifold)
                hits = m.ray_cast(start, end)
                self.assertTrue(hits, "центральный луч не нашёл выпуклую сторону")
                coordinate = float(hits[0].position[axis])
                self.assertGreater(abs(coordinate), depth * 0.15,
                                   "середина осталась плоской крышкой")
                self.assertAlmostEqual(float(size(m)[axis]), depth, delta=2e-4)
                self.assertEqual(m.genus(), 0)

    def test_lightning_has_flat_top_central_zigzag_and_one_bottom_point(self):
        bolt = obj("о = lightning height=110 width=55 depth=12")
        flat = valid(bolt.manifold)
        vertices = np.asarray(flat.to_mesh().vert_properties)[:, :3]
        top = np.unique(np.round(vertices[vertices[:, 2] == vertices[:, 2].max()][:, [0, 2]], 5), axis=0)
        bottom = np.unique(np.round(vertices[vertices[:, 2] == vertices[:, 2].min()][:, [0, 2]], 5), axis=0)
        self.assertEqual(len(top), 2, "верх обязан быть отрезком, а не остриём")
        self.assertGreater(np.ptp(top[:, 0]), 20)
        self.assertEqual(len(bottom), 1, "остриё должно быть только одно и только снизу")
        self.assertEqual(bolt.meta.get("silhouette"), "flat_top_single_bottom_point")
        self.assertNotIn("zigzags", bolt.meta)
        volumetric = valid(obj("о = lightning height=110 width=55 depth=12 volume=да").manifold)
        np.testing.assert_allclose(size(volumetric), size(flat), atol=2e-4)
        self.assertFalse(build("о = lightning zigzags=4").ok)
        self.assertNotIn("zigzags", OPS["lightning"].params)

    def test_faceted_star_keeps_requested_bounds(self):
        plain = valid(obj("о = star outer=60 inner=25 depth=20 volume_style=фасеточный").manifold)
        rounded = valid(obj(
            "о = star outer=60 inner=25 depth=20 bevel=3 volume_style=фасеточный").manifold)
        np.testing.assert_allclose(size(rounded), size(plain), atol=2e-4)
        self.assertNotAlmostEqual(rounded.volume(), plain.volume(), places=3)


class ExpansionJointMatrixTest(unittest.TestCase):
    def test_all_halves_joints_and_transitions_are_closed(self):
        cases = (("sphere", "radius=24 segments=32"),
                 ("ellipsoid", "x=30 y=20 z=24 segments=32"),
                 ("capsule", "radius=10 height=60 segments=32"),
                 ("box", "size=[45,35,50]"))
        for op, dims in cases:
            for side in ("верх", "низ"):
                for joint in ("посадка", "стык"):
                    for smooth in (0, 1):
                        with self.subTest(op=op, side=side, joint=joint, smooth=smooth):
                            item = obj(f"о = {op} {dims} expand=.2 expand_side={side} "
                                       f"expand_joint={joint} expand_smooth={smooth}")
                            valid(item.manifold)
                            self.assertEqual(item.meta["expand_joint"], joint)
                            self.assertEqual(item.meta["expanded_half"], side)
                            if joint == "посадка":
                                self.assertGreater(item.meta["expand_seat"], 0.0)
                            if smooth:
                                self.assertGreater(item.meta["expand_transition_mm"], 0.0)


class TrackGeometryTest(unittest.TestCase):
    def test_default_parts_fit_without_intersections(self):
        result = ok("путь = track length=240 sleeper_count=4 sleeper_step=65")
        expected = ({"путь", "путь.rail_right"}
                    | {f"путь.sleeper_{i:02d}" for i in range(1, 5)}
                    | {f"путь.fastener_{side}_{i:02d}"
                       for side in ("left", "right") for i in range(1, 5)})
        self.assertEqual(set(result.scene.objects), expected)
        # Ни одна видимая деталь не спрятана в compound: каждая имеет своё
        # имя для pick/highlight и ровно одно замкнутое тело.
        for solid in result.visible_solids():
            valid(solid.manifold)
        rails = mf.Manifold.batch_boolean(
            [result.scene.objects[n].manifold for n in ("путь", "путь.rail_right")], mf.OpType.Add)
        sleepers = mf.Manifold.batch_boolean(
            [result.scene.objects[f"путь.sleeper_{i:02d}"].manifold for i in range(1, 5)], mf.OpType.Add)
        fasteners = mf.Manifold.batch_boolean(
            [result.scene.objects[f"путь.fastener_{side}_{i:02d}"].manifold
             for side in ("left", "right") for i in range(1, 5)], mf.OpType.Add)
        self.assertEqual(len(rails.decompose()), 2)
        self.assertEqual(len(sleepers.decompose()), 4)
        self.assertEqual(len(fasteners.decompose()), 8)
        for left, right in ((rails, sleepers), (rails, fasteners), (sleepers, fasteners)):
            self.assertLess(abs((left ^ right).volume()), 1e-6)
        params = result.scene.objects["путь"].meta["primitive_params"]
        self.assertEqual(params["sleeper_count"], 4)
        self.assertAlmostEqual(params["sleeper_step"], 65.0)
        self.assertTrue(params["fasteners"])

    def test_profiles_sleepers_and_switches_change_geometry(self):
        volumes = []
        for profile in ("рельса", "двутавр", "т", "брусок"):
            with self.subTest(profile=profile):
                m = valid(obj(f"о = track length=200 rails=1 sleepers=нет "
                              f"rail_profile={profile}").manifold)
                self.assertEqual(len(m.decompose()), 1)
                self.assertAlmostEqual(float(size(m)[2]), 28.0, delta=1e-5)
                volumes.append(m.volume())
        self.assertEqual(len({round(v, 3) for v in volumes}), 4)

        no_sleepers = ok("о = track length=200 rails=1 sleepers=нет")
        self.assertEqual(set(no_sleepers.scene.objects), {"о"})
        no_fasteners = ok("о = track length=200 rails=1 sleepers=да fasteners=нет")
        self.assertEqual(set(no_fasteners.scene.objects),
                         {"о"} | {f"о.sleeper_{i:02d}" for i in range(1, 5)})
        sleeper_volumes = []
        for shape in ("скошенная", "бетонная", "брусок"):
            with self.subTest(sleeper=shape):
                result = ok(f"о = track length=200 rails=1 sleeper_count=3 "
                            f"sleeper_step=60 sleeper_shape={shape}")
                sleepers = [valid(result.scene.objects[f"о.sleeper_{i:02d}"].manifold)
                            for i in range(1, 4)]
                sleeper_volumes.append(sum(m.volume() for m in sleepers))
        self.assertEqual(len({round(v, 3) for v in sleeper_volumes}), 3)

    def test_overlapping_sleepers_are_rejected(self):
        result = build("о = track length=100 sleeper_count=8 sleeper_width=32",
                       analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("перекрываются", result.error["message"])


class HingeAndHandleGeometryTest(unittest.TestCase):
    def test_hinge_is_two_editable_solids_through_whole_angle_range(self):
        for angle in (0, 10, 45, 90, 135, 170, 180):
            with self.subTest(angle=angle):
                result = ok(f"петля = hinge height=70 leaf_width=36 open_angle={angle}")
                self.assertEqual(set(result.scene.objects), {"петля", "петля.right"})
                left = valid(result.scene.objects["петля"].manifold)
                right = valid(result.scene.objects["петля.right"].manifold)
                self.assertLess(abs((left ^ right).volume()), 1e-6)
                self.assertGreater(left.genus(), 0)
                self.assertGreater(right.genus(), 0)
                params = result.scene.objects["петля"].meta["primitive_params"]
                self.assertEqual(params["objects"], 2)
                self.assertEqual(params["open_angle"], angle)

    def test_hinge_screw_holes_are_really_open(self):
        result = ok("петля = hinge height=70 leaf_width=36 holes=3 countersink=да")
        for name, x in (("петля", -21.025), ("петля.right", 21.025)):
            m = result.scene.objects[name].manifold
            for z in (17.5, 35.0, 52.5):
                self.assertEqual(m.ray_cast([x, -50, z], [x, 50, z]), [])

    def test_five_handle_forms_and_relief_are_real_geometry(self):
        forms = ("изогнутая", "рельефная", "прямоугольная", "сферическая", "дисковая")
        signatures = []
        for form in forms:
            with self.subTest(form=form):
                item = obj(f"о = door_handle form={form}")
                m = valid(item.manifold)
                params = item.meta["primitive_params"]
                self.assertEqual(params["form"], form)
                self.assertTrue(params["sdf"])
                self.assertEqual(params["blend"], 3.0)
                self.assertGreater(params["resolution"], 0.0)
                self.assertGreater(m.num_tri(), 2_500 if form == "прямоугольная" else 10_000)
                self.assertAlmostEqual(m.bounding_box()[4], 0.0, delta=1e-5)
                signatures.append((tuple(np.round(size(m), 4)), round(m.volume(), 3)))
        self.assertEqual(len(set(signatures)), 5)
        plain = valid(obj("о = door_handle form=рельефная relief=0").manifold)
        relief = valid(obj("о = door_handle form=рельефная relief=.9").manifold)
        self.assertGreater(relief.volume(), plain.volume())
        right = valid(obj("о = door_handle form=изогнутая hand=право").manifold)
        left = valid(obj("о = door_handle form=изогнутая hand=лево").manifold)
        self.assertAlmostEqual(right.bounding_box()[0], -left.bounding_box()[3], delta=1e-5)
        self.assertAlmostEqual(right.bounding_box()[3], -left.bounding_box()[0], delta=1e-5)

    def test_rosettes_real_keyhole_plug_and_no_rosette(self):
        integrated = obj("о = door_handle form=прямоугольная rosette=овальная "
                         "lock=да resolution=.7")
        valid(integrated.manifold)
        params = integrated.meta["primitive_params"]
        self.assertEqual(params["rosette"], "овальная")
        self.assertTrue(params["lock"])
        lock_z = params["rosette_h"] / 2 - params["lock_offset"] + params["lock_d"] * 0.12
        self.assertEqual(integrated.manifold.ray_cast([0, -100, lock_z], [0, 100, lock_z]), [])

        plugged = ok("о = door_handle form=рельефная rosette=прямоугольная "
                     "lock=да lock_plug=да resolution=.7")
        self.assertIn("о.lock_plug", plugged.scene.objects)
        valid(plugged.scene.objects["о.lock_plug"].manifold)
        self.assertEqual(plugged.scene.objects["о"].meta["primitive_params"]["objects"], 2)

        separate = ok("о = door_handle rosette=круглая lock=да resolution=.7")
        self.assertIn("о.lock_plate", separate.scene.objects)
        plate = valid(separate.scene.objects["о.lock_plate"].manifold)
        bb = plate.bounding_box()
        z = (bb[2] + bb[5]) / 2 + 18.0 * 0.12
        self.assertEqual(plate.ray_cast([0, -100, z], [0, 100, z]), [])

        plain = ok("о = door_handle form=сферическая rosette=нет lock=нет")
        self.assertEqual(set(plain.scene.objects), {"о"})
        self.assertEqual(plain.scene.objects["о"].meta["primitive_params"]["rosette"], "нет")
        with self.assertRaises(AssertionError):
            obj("о = door_handle lock=нет lock_plug=да")


class PrimitiveExportAndHelpTest(unittest.TestCase):
    SCRIPT = ("петля = hinge height=70 leaf_width=36 open_angle=45\n"
              "ручка = door_handle form=рельефная relief=.7 at=[100,0,0]\n"
              "звезда = star outer=35 inner=15 depth=16 volume=да at=[0,100,0]\n"
              "молния = lightning height=80 width=40 depth=12 volume=да at=[80,100,0]\n")

    def test_glb_and_forma_roundtrip(self):
        result = ok(self.SCRIPT)
        data = result.glb()
        doc = glb_json(data)
        names = {node.get("name") for node in doc.get("nodes", [])}
        self.assertTrue({"петля", "петля.right", "ручка", "звезда", "молния"} <= names)
        for node in doc.get("nodes", []):
            if node.get("name") in names:
                self.assertEqual((node.get("extras") or {}).get("formaName"), node.get("name"))
        import trimesh
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=True)
        self.assertEqual(len(scene.geometry), 5)
        for name, mesh in scene.geometry.items():
            # glTF законно дублирует координаты ради разных нормалей/UV.
            # Blender сшивает их по «Merge by Distance»; проверяем именно
            # геометрическую замкнутость, а не раскрой нормалей.
            mesh.merge_vertices(merge_norm=True, merge_tex=True, digits_vertex=6)
            self.assertTrue(mesh.is_watertight, name)
            self.assertTrue(mesh.is_winding_consistent, name)
            self.assertTrue(np.isfinite(mesh.vertices).all(), name)
            self.assertGreater(abs(mesh.volume), 1e-7, name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "primitives.forma"
            path.write_text(self.SCRIPT, encoding="utf-8")
            restored = ok(path.read_text(encoding="utf-8"))
            self.assertEqual(set(restored.scene.objects), set(result.scene.objects))
            self.assertAlmostEqual(sum(s.manifold.volume() for s in restored.visible_solids()),
                                   sum(s.manifold.volume() for s in result.visible_solids()), places=5)

    def test_new_commands_have_complete_help(self):
        for name in ("track", "hinge", "door_handle", "door", "window"):
            spec = lookup(name)
            self.assertIsNotNone(spec, name)
            self.assertGreater(len(spec.summary), 80, name)
            self.assertGreater(len(spec.params), 10, name)
            self.assertIn("\n", spec.example, name)
            self.assertEqual(spec.category, "Примитивы")


if __name__ == "__main__":
    unittest.main()
