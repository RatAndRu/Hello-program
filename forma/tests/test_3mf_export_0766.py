"""3MF interoperability, indexed topology, color and the printable test model.

lib3mf is an optional independent test dependency, not an application dependency.
These tests do not claim a Bambu Studio import, slicing, or physical print.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forma.errors import GeometryError  # noqa: E402
from forma.geometry import _indexed_3mf_arrays, export_3mf, manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402

try:
    import lib3mf
except ImportError:
    lib3mf = None

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
NS = {"c": CORE, "m": MATERIAL}
CLOVER = ROOT / "examples" / "clover_keychain_3mf"
CLOVER_COLORS = {
    "основа": "#185B3AFF",
    "вставка_верх": "#66D976FF",
    "вставка_право": "#F5C84CFF",
    "вставка_низ": "#EB6B83FF",
    "вставка_лево": "#41BFD0FF",
}


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def unpack(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        assert set(zf.namelist()) == {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        return ET.fromstring(zf.read("3D/3dmodel.model"))


def mesh_objects(root):
    return [obj for obj in root.findall("./c:resources/c:object", NS)
            if obj.find("c:mesh", NS) is not None]


def arrays(obj):
    vertices = np.array([[float(v.get(a)) for a in "xyz"]
                         for v in obj.findall("./c:mesh/c:vertices/c:vertex", NS)], dtype=np.float64)
    triangles = obj.findall("./c:mesh/c:triangles/c:triangle", NS)
    faces = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")]
                      for t in triangles], dtype=np.int64)
    return vertices, faces, triangles


def palette(root):
    group = root.find("./c:resources/m:colorgroup", NS)
    return group.get("id"), [c.get("color").upper() for c in group.findall("m:color", NS)]


def indexed_edge_errors(vertices, faces):
    """Count actual serialized indices, without any diagnostic vertex welding."""
    edges = Counter()
    for a, b, c in faces.tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(u, v)] += 1
    return sum(1 for (a, b), count in edges.items()
               if a == b or count != 1 or edges[(b, a)] != 1)


def as_manifold(obj):
    vertices, faces, _ = arrays(obj)
    result = mf.Manifold(mf.Mesh(
        vert_properties=np.ascontiguousarray(vertices, dtype=np.float32),
        tri_verts=np.ascontiguousarray(faces, dtype=np.uint32),
    ))
    assert result.status() == mf.Error.NoError
    return result


class ThreeMFExportTests(unittest.TestCase):
    def test_box_is_closed_by_index_and_keeps_z_up_and_precision(self):
        b = built("box = box size=[20,30,40] at=[1.234567,-7.654321,2.123456]")
        box = b.visible_solids()[0]
        box.color = "#123456"
        box.name = 'Клевер & <деталь> "один"'
        root = unpack(export_3mf([box]))
        self.assertEqual(root.get("unit"), "millimeter")
        self.assertEqual(root.find("c:metadata", NS).text, box.name)
        objs = mesh_objects(root)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].get("name"), box.name)
        self.assertEqual(root.find("./c:build/c:item", NS).get("objectid"), objs[0].get("id"))
        self.assertIsNone(objs[0].find("c:components", NS))
        vertices, faces, tris = arrays(objs[0])
        self.assertEqual((len(vertices), len(faces)), (8, 12))
        self.assertEqual(indexed_edge_errors(vertices, faces), 0)
        source, _ = manifold_mesh(box.manifold)
        np.testing.assert_allclose(vertices.min(axis=0), source.min(axis=0), atol=1e-9)
        np.testing.assert_allclose(vertices.max(axis=0), source.max(axis=0), atol=1e-9)
        self.assertTrue(np.any(np.abs(vertices - np.round(vertices, 4)) > 1e-7))
        areas2 = np.linalg.norm(np.cross(vertices[faces][:, 1] - vertices[faces][:, 0],
                                         vertices[faces][:, 2] - vertices[faces][:, 0]), axis=1)
        self.assertTrue(np.all(areas2 > 0))
        signed_volume = np.einsum("ij,ij->i", vertices[faces][:, 0],
                                  np.cross(vertices[faces][:, 1], vertices[faces][:, 2])).sum() / 6
        self.assertGreater(signed_volume, 0)
        group_id, colors = palette(root)
        self.assertEqual(colors, ["#123456FF"])
        self.assertEqual(objs[0].get("pid"), group_id)
        self.assertEqual(objs[0].get("pindex"), "0")
        self.assertTrue(all(t.get("pid") == group_id and t.get("p1") == "0" for t in tris))

    def test_multiple_visible_solids_are_named_colored_components(self):
        b = built("a = box size=[20,30,40]\ncolor a #ff0000\n"
                  "б = box size=[10,15,20] at=[50,0,4]\ncolor б #0000ff\n"
                  "скрыто = box size=[10,10,10] at=[100,0,0] visible=нет")
        objs = b.visible_solids()
        self.assertEqual(len(objs), 2)
        root = unpack(export_3mf(iter(objs)))
        meshes = mesh_objects(root)
        self.assertEqual([o.get("name") for o in meshes], ["a", "б"])
        assembly = root.find("./c:resources/c:object[c:components]", NS)
        self.assertIsNotNone(assembly)
        self.assertIsNone(assembly.get("pid"))
        self.assertIsNone(assembly.get("pindex"))
        components = assembly.findall("./c:components/c:component", NS)
        self.assertEqual([c.get("objectid") for c in components], [m.get("id") for m in meshes])
        self.assertTrue(all(c.get("transform") is None for c in components))
        items = root.findall("./c:build/c:item", NS)
        self.assertEqual([x.get("objectid") for x in items], [assembly.get("id")])
        group_id, colors = palette(root)
        self.assertEqual(colors, ["#FF0000FF", "#0000FFFF"])
        for mesh, solid, expected in zip(meshes, objs, colors):
            vertices, faces, tris = arrays(mesh)
            self.assertEqual(indexed_edge_errors(vertices, faces), 0)
            bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
            np.testing.assert_allclose(bounds.reshape(-1), solid.manifold.bounding_box(), atol=1e-6)
            self.assertEqual(colors[int(mesh.get("pindex"))], expected)
            self.assertTrue(all(t.get("pid") == group_id and
                                colors[int(t.get("p1"))] == expected for t in tris))
        with self.assertRaises(GeometryError):
            export_3mf([])

    def test_region_brush_and_eraser_use_original_model_coordinates(self):
        b = built("a = box size=[20,30,40] at=[11,-7,3]")
        solid = b.visible_solids()[0]
        solid.color = "#cc0011"
        solid.paint = [{"side": "верх", "color": "#00ff00"}]
        vertices, faces = manifold_mesh(solid.manifold)
        triangles = vertices[faces]
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        centers = triangles.mean(axis=1)
        top = centers[normals[:, 2] > 0]
        self.assertEqual(len(top), 2)
        solid.brush = [
            {"color": "#0000ff", "radius": 0.25, "path": [top[0].tolist()]},
            {"erase": True, "radius": 0.25, "path": [top[0].tolist()]},
            {"color": "#0000ff", "radius": 0.25, "path": [top[1].tolist()]},
        ]
        root = unpack(export_3mf([solid]))
        obj = mesh_objects(root)[0]
        group_id, colors = palette(root)
        # Readers without per-face properties get the original object color.
        self.assertEqual(colors[int(obj.get("pindex"))], "#CC0011FF")
        vertices, faces, tris = arrays(obj)
        actual = []
        for face, triangle in zip(faces, tris):
            xyz = vertices[face]
            n = np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0])
            center = xyz.mean(axis=0)
            color = colors[int(triangle.get("p1"))]
            self.assertEqual(triangle.get("pid"), group_id)
            if n[2] > 0:
                expected = "#0000FFFF" if np.linalg.norm(center - top[1]) < 0.25 else "#00FF00FF"
            else:
                expected = "#CC0011FF"
            self.assertEqual(color, expected)
            actual.append(color)
        self.assertEqual(set(actual), {"#CC0011FF", "#00FF00FF", "#0000FFFF"})

    def test_index_repair_is_exact_and_does_not_merge_valid_touching_shells(self):
        solid = built("a = box size=[20,30,40]").visible_solids()[0]
        verts, faces = manifold_mesh(solid.manifold)
        split = verts[faces].reshape(-1, 3)
        split_faces = np.arange(len(split), dtype=np.int64).reshape(-1, 3)
        self.assertGreater(indexed_edge_errors(split, split_faces), 0)
        with patch("forma.geometry._clean_manifold_arrays", return_value=(split, split_faces)):
            joined, joined_faces = _indexed_3mf_arrays(solid.manifold, "cube")
        self.assertEqual(len(joined), 8)
        self.assertEqual(indexed_edge_errors(joined, joined_faces), 0)

        # A nearby, non-identical point is not automatically joined by the new
        # index repair, even though the old diagnostic weld would hide the gap.
        gap = split.copy()
        gap[0, 0] += 2e-6
        with patch("forma.geometry._clean_manifold_arrays", return_value=(gap, split_faces)):
            with self.assertRaises(GeometryError):
                _indexed_3mf_arrays(solid.manifold, "cube")

        # Two already closed cubes sharing a point retain separate indices.
        touching = np.vstack((verts, verts + [20, 30, 40]))
        touching_faces = np.vstack((faces, faces + len(verts)))
        with patch("forma.geometry._clean_manifold_arrays", return_value=(touching, touching_faces)):
            unchanged, unchanged_faces = _indexed_3mf_arrays(solid.manifold, "touching")
        self.assertEqual(len(unchanged), 16)
        np.testing.assert_array_equal(unchanged_faces, touching_faces)

    def test_clover_source_and_provided_3mf_have_real_fitted_parts(self):
        source = built(CLOVER.with_suffix(".forma").read_text(encoding="utf-8"))
        solids = source.visible_solids()
        self.assertEqual({s.name for s in solids}, set(CLOVER_COLORS))
        for solid in solids:
            self.assertEqual(len(solid.manifold.decompose()), 1, solid.name)
        base = source.scene.objects["основа"].manifold
        original = source.scene.objects["с_ушком"].manifold
        self.assertEqual(base.genus(), 1)
        self.assertEqual(len(base.decompose()), 1)
        full = mf.Manifold.batch_boolean([s.manifold for s in solids], mf.OpType.Add)
        self.assertEqual(len(full.decompose()), 1)
        self.assertLess(abs((original - full).volume()), 0.01)
        self.assertLess(abs((full - original).volume()), 0.01)
        for insert in solids[1:]:
            bb = insert.manifold.bounding_box()
            self.assertAlmostEqual(bb[2], 1.8, places=5)
            self.assertAlmostEqual(bb[5], 3.0, places=5)
            self.assertGreater(insert.manifold.volume(), 100)

        # Verify the actual, checked-in file as well as a fresh export. This
        # compares geometry rather than ZIP bytes or triangulation order.
        stored = unpack(CLOVER.with_suffix(".3mf").read_bytes())
        fresh = unpack(export_3mf(solids))
        for root in (stored, fresh):
            self.assertEqual(root.get("unit"), "millimeter")
            objs = mesh_objects(root)
            self.assertEqual({o.get("name") for o in objs}, set(CLOVER_COLORS))
            assembly = root.find("./c:resources/c:object[c:components]", NS)
            components = assembly.findall("./c:components/c:component", NS)
            self.assertEqual([c.get("objectid") for c in components], [o.get("id") for o in objs])
            self.assertEqual(root.find("./c:build/c:item", NS).get("objectid"), assembly.get("id"))
            group_id, colors = palette(root)
            actual = {}
            all_vertices = []
            for obj in objs:
                name = obj.get("name")
                vertices, faces, tris = arrays(obj)
                self.assertEqual(indexed_edge_errors(vertices, faces), 0, name)
                self.assertEqual(colors[int(obj.get("pindex"))], CLOVER_COLORS[name])
                self.assertTrue(all(t.get("pid") == group_id and
                                    colors[int(t.get("p1"))] == CLOVER_COLORS[name] for t in tris))
                actual[name] = as_manifold(obj)
                self.assertEqual(len(actual[name].decompose()), 1, name)
                self.assertLess(abs((actual[name] - source.scene.objects[name].manifold).volume()), 0.01)
                self.assertLess(abs((source.scene.objects[name].manifold - actual[name]).volume()), 0.01)
                all_vertices.append(vertices)
            verts = np.vstack(all_vertices)
            np.testing.assert_allclose(verts.max(axis=0) - verts.min(axis=0),
                                       [39.884224, 48.942112, 3.0], atol=1e-3)
            self.assertAlmostEqual(verts[:, 2].min(), 0.0, places=6)
            self.assertEqual(actual["основа"].genus(), 1)
            parts = list(actual.values())
            for i, a in enumerate(parts):
                for b in parts[i + 1:]:
                    self.assertLess(abs((a ^ b).volume()), 1e-4)
            # A test pin fits all the way through, and the annulus is solid:
            # this is a real hole, not a painted black circle or an open notch.
            pin = mf.Manifold.cylinder(5, 2.4, 2.4, 64).translate((0, 24, -1))
            self.assertLess(abs((actual["основа"] ^ pin).volume()), 1e-6)
            # Stay just inside the polygonal ring's nominal radii 2.5 and 5.
            ring = (mf.Manifold.cylinder(3, 4.8, 4.8, 64)
                    - mf.Manifold.cylinder(5, 2.55, 2.55, 64).translate((0, 0, -1)))
            ring = ring.translate((0, 24, 0))
            self.assertLess(abs((ring - actual["основа"]).volume()), 1e-3)

    def test_existing_brush_vase_exports_closed_colored_mesh(self):
        script = (ROOT / "examples" / "vase_flower_demo.forma").read_text(encoding="utf-8")
        solid = built(script).visible_solids()[0]
        root = unpack(export_3mf([solid]))
        obj = mesh_objects(root)[0]
        vertices, faces, tris = arrays(obj)
        self.assertEqual(indexed_edge_errors(vertices, faces), 0)
        group_id, colors = palette(root)
        face_colors = {colors[int(t.get("p1"))] for t in tris if t.get("pid") == group_id}
        self.assertGreaterEqual(len(face_colors), 2)
        np.testing.assert_allclose(vertices.max(axis=0) - vertices.min(axis=0),
                                   [84, 84, 148], atol=1e-3)

    @unittest.skipIf(lib3mf is None, "install lib3mf for an independent 3MF check")
    def test_independent_lib3mf_reads_face_paint(self):
        b = built("a = box size=[20,30,40] at=[5,-4,2]\n"
                  "color a #cc0011\npaint a #00ff00 side=верх")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "paint.3mf"
            path.write_bytes(export_3mf(b.visible_solids()))
            model = lib3mf.get_wrapper().CreateModel()
            reader = model.QueryReader("3mf")
            reader.SetStrictModeActive(True)
            reader.ReadFromFile(str(path))
            self.assertEqual(reader.GetWarningCount(), 0)
            groups = model.GetColorGroups()
            self.assertTrue(groups.MoveNext())
            group = groups.GetCurrentColorGroup()
            colors = {}
            for prop_id in group.GetAllPropertyIDs():
                c = group.GetColor(prop_id)
                colors[prop_id] = f"#{c.Red:02X}{c.Green:02X}{c.Blue:02X}{c.Alpha:02X}"
            objects = model.GetMeshObjects()
            self.assertTrue(objects.MoveNext())
            obj = objects.GetCurrentMeshObject()
            self.assertTrue(obj.IsManifoldAndOriented())
            vertices = np.array([list(v.Coordinates) for v in obj.GetVertices()])
            faces = np.array([list(t.Indices) for t in obj.GetTriangleIndices()])
            tri = vertices[faces]
            normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            props = obj.GetAllTriangleProperties()
            actual = [colors[p.PropertyIDs[0]] for p in props]
            expected = ["#00FF00FF" if n[2] > 0 else "#CC0011FF" for n in normals]
            self.assertEqual(actual, expected)
            self.assertEqual(set(actual), {"#00FF00FF", "#CC0011FF"})
            self.assertTrue(all(len(set(p.PropertyIDs)) == 1 for p in props))

    @unittest.skipIf(lib3mf is None, "install lib3mf for an independent 3MF check")
    def test_independent_lib3mf_reads_clover_colors_assembly_and_closed_meshes(self):
        wrapper = lib3mf.get_wrapper()
        model = wrapper.CreateModel()
        reader = model.QueryReader("3mf")
        reader.SetStrictModeActive(True)
        reader.ReadFromFile(str(CLOVER.with_suffix(".3mf")))
        self.assertEqual(reader.GetWarningCount(), 0)
        self.assertEqual(model.GetUnit(), lib3mf.ModelUnit.MilliMeter)
        groups = model.GetColorGroups()
        self.assertTrue(groups.MoveNext())
        group = groups.GetCurrentColorGroup()
        colors = {}
        for prop_id in group.GetAllPropertyIDs():
            c = group.GetColor(prop_id)
            colors[prop_id] = f"#{c.Red:02X}{c.Green:02X}{c.Blue:02X}{c.Alpha:02X}"
        self.assertEqual(set(colors.values()), set(CLOVER_COLORS.values()))
        self.assertFalse(groups.MoveNext())
        mesh_iter = model.GetMeshObjects()
        mesh_ids = []
        names = []
        while mesh_iter.MoveNext():
            obj = mesh_iter.GetCurrentMeshObject()
            names.append(obj.GetName())
            mesh_ids.append(obj.GetResourceID())
            self.assertTrue(obj.IsManifoldAndOriented(), obj.GetName())
            self.assertEqual(len(obj.GetVertices()), obj.GetVertexCount())
            self.assertEqual(len(obj.GetTriangleIndices()), obj.GetTriangleCount())
            for p in obj.GetAllTriangleProperties():
                self.assertEqual(p.ResourceID, group.GetResourceID())
                self.assertEqual([colors[i] for i in p.PropertyIDs], [CLOVER_COLORS[obj.GetName()]] * 3)
        self.assertEqual(set(names), set(CLOVER_COLORS))
        build_items = model.GetBuildItems()
        self.assertTrue(build_items.MoveNext())
        assembly = build_items.GetCurrent().GetObjectResource()
        self.assertTrue(assembly.IsComponentsObject())
        self.assertEqual(assembly.GetComponentCount(), len(mesh_ids))
        self.assertEqual([assembly.GetComponent(i).GetObjectResourceID() for i in range(len(mesh_ids))],
                         mesh_ids)
        self.assertFalse(build_items.MoveNext())


if __name__ == "__main__":
    unittest.main()
