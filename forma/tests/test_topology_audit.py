"""Тесты аудита топологии (forma/tools/topology_audit.py).

Запуск из папки forma:
    python -m unittest tests.test_topology_audit -v

Скрипт аудита не зависит от numpy/trimesh, поэтому тесты тоже: они собирают
OBJ и GLB вручную и проверяют, что дефекты находятся, а здоровая сетка —
нет.
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import topology_audit as ta  # noqa: E402


CUBE_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
]

# грани против часовой стрелки, если смотреть снаружи
CUBE_QUADS = [
    (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]


def cube_obj(path: Path, drop_face: int | None = None,
             flip_face: int | None = None, extra: str = "") -> Path:
    lines = [f"v {x} {y} {z}" for x, y, z in CUBE_VERTS]
    for i, q in enumerate(CUBE_QUADS):
        if drop_face is not None and i == drop_face:
            continue
        face = tuple(reversed(q)) if flip_face == i else q
        lines.append("f " + " ".join(str(v + 1) for v in face))
    lines.append(extra)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cube_glb(path: Path, split: bool = True, normals: bool = True) -> Path:
    """Собирает минимальный валидный GLB с кубом.

    split=True повторяет вершины для каждой грани — так ведут себя настоящие
    экспортёры, разводя вершины по швам нормалей.
    """
    verts: list[tuple] = []
    norms: list[tuple] = []
    idx: list[int] = []
    for q in CUBE_QUADS:
        if split:
            base = len(verts)
            poly = [CUBE_VERTS[i] for i in q]
            # нормаль грани
            u = [poly[1][k] - poly[0][k] for k in range(3)]
            v = [poly[2][k] - poly[0][k] for k in range(3)]
            n = (u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
            ln = sum(c * c for c in n) ** 0.5
            n = tuple(c / ln for c in n)
            verts.extend(poly)
            norms.extend([n] * 4)
            idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])
        else:
            idx.extend([q[0], q[1], q[2], q[0], q[2], q[3]])
    if not split:
        verts = [tuple(float(c) for c in v) for v in CUBE_VERTS]

    blob = b""
    views = []
    accessors = []
    attrs = {}

    def add_vec3(data: list[tuple]) -> int:
        nonlocal blob
        while len(blob) % 4:
            blob += b"\0"
        off = len(blob)
        for v in data:
            blob += struct.pack("<3f", *v)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data) * 12})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126,
                          "count": len(data), "type": "VEC3",
                          "min": [min(v[i] for v in data) for i in range(3)],
                          "max": [max(v[i] for v in data) for i in range(3)]})
        return len(accessors) - 1

    attrs["POSITION"] = add_vec3(verts)
    if normals:
        attrs["NORMAL"] = add_vec3(norms)
    while len(blob) % 4:
        blob += b"\0"
    off = len(blob)
    for i in idx:
        blob += struct.pack("<I", i)
    views.append({"buffer": 0, "byteOffset": off, "byteLength": len(idx) * 4})
    accessors.append({"bufferView": len(views) - 1, "componentType": 5125,
                      "count": len(idx), "type": "SCALAR",
                      "min": [min(idx)], "max": [max(idx)]})
    index_acc = len(accessors) - 1

    js = {
        "asset": {"version": "2.0", "generator": "test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "cube"}],
        "meshes": [{"name": "cube", "primitives": [
            {"attributes": attrs, "indices": index_acc, "mode": 4}]}],
        "bufferViews": views,
        "accessors": accessors,
        "buffers": [{"byteLength": len(blob)}],
    }
    jb = json.dumps(js).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    while len(blob) % 4:
        blob += b"\0"
    total = 12 + 8 + len(jb) + 8 + len(blob)
    out = struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(jb), 0x4E4F534A) + jb
    out += struct.pack("<II", len(blob), 0x004E4942) + blob
    path.write_bytes(out)
    return path


class AuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def audit(self, path: Path) -> dict:
        return ta.run(path, 1e-4, 3.0, 10.0)

    def codes(self, rep: dict) -> set[str]:
        return {g["код"] for g in rep["коды"]}

    def test_cube_obj_is_clean(self) -> None:
        rep = self.audit(cube_obj(self.dir / "cube.obj"))
        self.assertEqual(rep["сводка"]["ошибок"], 0)
        self.assertEqual(rep["сводка"]["треугольников"], 12)
        obj = rep["объекты"][0]
        self.assertEqual(obj["вершин"], 8)
        self.assertEqual(obj["проверки"]["граничные_рёбра"], 0)
        self.assertEqual(obj["проверки"]["non_manifold_рёбра"], 0)
        shell = obj["оболочки_детали"][0]
        self.assertEqual((shell["euler"], shell["genus"]), (2, 0))
        self.assertAlmostEqual(shell["volume"], 8.0, places=5)

    def test_hole_is_found(self) -> None:
        rep = self.audit(cube_obj(self.dir / "hole.obj", drop_face=3))
        obj = rep["объекты"][0]
        self.assertEqual(obj["проверки"]["граничные_рёбра"], 4)
        self.assertIn("boundary", self.codes(rep))
        self.assertEqual(rep["сводка"]["ошибок"] > 0, True)

    def test_flipped_face_breaks_winding(self) -> None:
        rep = self.audit(cube_obj(self.dir / "flip.obj", flip_face=4))
        obj = rep["объекты"][0]
        self.assertGreater(obj["проверки"]["несогласованный_обход"], 0)
        self.assertIn("winding", self.codes(rep))

    def test_duplicate_vertices_weld_back(self) -> None:
        # куб, у которого каждая грань — свои 4 вершины
        path = self.dir / "split.obj"
        lines = []
        for q in CUBE_QUADS:
            for i in q:
                lines.append("v %g %g %g" % CUBE_VERTS[i])
        for f in range(6):
            base = f * 4 + 1
            lines.append(f"f {base} {base + 1} {base + 2} {base + 3}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rep = self.audit(path)
        obj = rep["объекты"][0]
        self.assertEqual(obj["вершин"], 8)
        self.assertEqual(obj["слито_вершин"], 16)
        # после сварки сетка замкнута: дубли вершин не считаются дыркой
        self.assertEqual(obj["проверки"]["граничные_рёбра"], 0)
        self.assertIn("doubles", self.codes(rep))

    def test_degenerate_triangle_is_found(self) -> None:
        path = self.dir / "deg.obj"
        cube_obj(path, extra="f 1 2 2")
        rep = self.audit(path)
        obj = rep["объекты"][0]
        self.assertEqual(obj["проверки"]["вырожденные_по_индексам"], 1)

    def test_glb_split_normals_is_clean(self) -> None:
        path = cube_glb(self.dir / "cube.glb", split=True, normals=True)
        rep = self.audit(path)
        obj = rep["объекты"][0]
        self.assertEqual(obj["вершин"], 8)          # 24 разведённых слились
        self.assertEqual(obj["слито_вершин"], 16)
        self.assertEqual(obj["проверки"]["граничные_рёбра"], 0)
        self.assertEqual(obj["проверки"]["non_manifold_рёбра"], 0)
        self.assertEqual(rep["сводка"]["ошибок"], 0)
        self.assertTrue(obj["нормали"]["есть"])
        self.assertGreater(obj["нормали"]["средний_dot"], 0.99)

    def test_glb_shared_vertices(self) -> None:
        path = cube_glb(self.dir / "cube2.glb", split=False, normals=False)
        rep = self.audit(path)
        obj = rep["объекты"][0]
        self.assertEqual(obj["вершин"], 8)
        self.assertEqual(obj["слито_вершин"], 0)
        self.assertFalse(obj["нормали"]["есть"])
        self.assertEqual(rep["сводка"]["ошибок"], 0)

    def test_sliver_is_reported(self) -> None:
        path = self.dir / "sliver.obj"
        path.write_text(
            "v 0 0 0\nv 10 0 0\nv 1 0.05 0\n"
            "v 0 1 0\nv 10 0 1\nv 0 0 1\n"
            "f 1 2 3\nf 1 4 6\nf 2 5 3\n", encoding="utf-8")
        rep = self.audit(path)
        obj = rep["объекты"][0]
        self.assertEqual(obj["качество"]["иглы"], 1)
        self.assertLess(obj["качество"]["мин_угол"], 3.0)

    def test_bad_file_returns_code_2(self) -> None:
        path = self.dir / "broken.glb"
        path.write_bytes(b"not a glb at all")
        self.assertEqual(ta.main([str(path), "--quiet"]), 2)

    def test_json_report_is_serialisable(self) -> None:
        rep = self.audit(cube_glb(self.dir / "c.glb"))
        text = json.dumps(rep, ensure_ascii=False)
        self.assertIn("сводка", json.loads(text))
        out = self.dir / "rep.json"
        self.assertEqual(ta.main([str(self.dir / "c.glb"), "--quiet",
                                  "--json", str(out)]), 0)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
