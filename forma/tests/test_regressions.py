"""Регрессионные тесты: метрики, безопасность инструментов, отчёт 0.5.0.

Эти тесты фиксируют то, что раньше «молча» ломалось: раздувание при
сглаживании, неверный масштаб импорта, падение from_sdf, повтор имён и т.п.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import export_3mf  # noqa: E402
from forma.run import build  # noqa: E402


def ok(script: str):
    b = build(script)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


def fails(script: str) -> dict:
    b = build(script)
    if b.ok:
        raise AssertionError(f"Ожидалась ошибка, но модель построилась: {script}")
    return b.error


class TestMetricsRegression(unittest.TestCase):
    """Объём и габарит не должны «плыть» больше чем на 0,1 %."""

    def test_cube_is_twelve_triangles(self):
        b = ok("куб = box size=[60,60,60]")
        m = b.analysis["metrics"]
        self.assertEqual(m["tris"], 12, "куб обязан оставаться 12 треугольников")
        self.assertAlmostEqual(m["volume_cm3"], 216.0, places=4)

    def test_bevel_keeps_size(self):
        b = ok("куб = box size=[60,60,60]\nкуб = bevel [куб] radius=3")
        m = b.analysis["metrics"]
        for axis, value in zip("xyz", m["size"]):
            self.assertAlmostEqual(value, 60.0, delta=0.2, msg=f"габарит {axis} уехал")
        self.assertGreater(m["volume_cm3"], 216.0 * 0.95, "фаска не должна съедать объём")

    def test_smooth_keeps_size(self):
        b = ok("куб = box size=[40,40,40]\nкуб = smooth [куб] soft=0.25 levels=2")
        m = b.analysis["metrics"]
        for value in m["size"]:
            self.assertAlmostEqual(value, 40.0, delta=1.0)

    def test_twist_keeps_volume(self):
        b = ok("брусок = box size=[20,20,60]\nбрусок = twist [брусок] angle=30")
        m = b.analysis["metrics"]
        self.assertAlmostEqual(m["volume_cm3"], 24.0, delta=0.25)

    def test_bend_keeps_volume(self):
        b = ok("брусок = box size=[20,20,60]\nбрусок = bend [брусок] angle=30")
        m = b.analysis["metrics"]
        self.assertAlmostEqual(m["volume_cm3"], 24.0, delta=0.25)

    def test_round_half_thickness_allowed(self):
        b = ok("плита = box size=[150,75,10] round=5")
        m = b.analysis["metrics"]
        self.assertAlmostEqual(m["size"][2], 10.0, places=2)
        self.assertGreater(m["volume_cm3"], 100.0)


class TestTessellation(unittest.TestCase):
    def test_small_sphere_is_light(self):
        b = ok("ш = sphere radius=10")
        self.assertLess(b.analysis["metrics"]["tris"], 1200)

    def test_big_sphere_is_smooth_but_not_huge(self):
        b = ok("ш = sphere radius=200")
        tris = b.analysis["metrics"]["tris"]
        self.assertLess(tris, 20000, "сфера Ø400 не должна стоить десятки тысяч треугольников")
        # отклонение объёма от идеальной сферы — не больше 0,6 %
        ideal = 4.0 / 3.0 * 3.141592653589793 * 200 ** 3 / 1000.0
        self.assertAlmostEqual(b.analysis["metrics"]["volume_cm3"], ideal, delta=ideal * 0.006)


class TestSafety(unittest.TestCase):
    def test_duplicate_name_is_error(self):
        err = fails("куб = box size=[10,10,10]\nкуб = sphere radius=20")
        self.assertIn("уже занято", err["message"])

    def test_division_by_zero_message(self):
        err = fails("R = 10/0")
        self.assertIn("деление на ноль", err["message"])

    def test_fillet_with_no_object(self):
        err = fails("куб = box size=[10,10,10]\nкуб = fillet [нет] radius=2")
        self.assertIn("имя объекта", err["message"])

    def test_sdf_bad_point_does_not_crash(self):
        # sqrt от отрицательного числа внутри формулы не должен ронять процесс
        b = ok("дет = from_sdf expression=\"sqrt(x) + y\" "
               "bounds=[-30,-30,-30,30,30,30] resolution=3")
        self.assertTrue(b.ok)


class TestImportUnits(unittest.TestCase):
    def test_auto_keeps_millimetres(self):
        from forma.geometry import export_stl

        b = ok("к = box size=[8,8,8]")
        data = export_stl(b.visible_solids())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cube8.stl"
            path.write_bytes(data)
            b2 = ok(f"дет = import file={path} unit=auto")
        size = b2.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 8.0, delta=0.2,
                               msg="unit=auto не должен угадывать масштаб")

    def test_repair_is_off_by_default(self):
        from forma.ops_io import load_any

        # маленький «дырявый» тетраэдр без нижней грани
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hole.stl"
            verts = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)]
            faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2)]
            lines = []
            for tri in faces:
                lines.append("facet normal 0 0 0")
                lines.append("outer loop")
                for idx in tri:
                    lines.append(f"vertex {verts[idx][0]} {verts[idx][1]} {verts[idx][2]}")
                lines.append("endloop")
                lines.append("endfacet")
            ascii_stl = "solid hole\n" + "\n".join(lines) + "\nendsolid hole\n"
            path.write_text(ascii_stl, encoding="utf-8")
            v_before, f_before = load_any(path, repair=False)
            v_after, f_after = load_any(path, repair=True)
        self.assertEqual(len(f_before), 3)
        self.assertGreaterEqual(len(f_after), 3)


class TestNewChecks(unittest.TestCase):
    def test_sharp_edge(self):
        b = ok("куб = box size=[20,20,20]\ncheck куб sharp_edge 90\ncheck куб sharp_edge 45")
        checks = b.analysis["checks"]
        self.assertTrue(checks[0]["ok"])
        self.assertFalse(checks[1]["ok"])

    def test_tri_quality(self):
        b = ok("ш = sphere radius=40\ncheck ш tri_quality 1")
        self.assertTrue(b.analysis["checks"][0]["ok"])

    def test_wall_min(self):
        src = Path(ROOT, "examples", "mug.forma").read_text(encoding="utf-8")
        b = ok(src + "\ncheck кружка wall_min 2..6")
        self.assertTrue(b.analysis["checks"][-1]["ok"], b.analysis["checks"][-1]["text"])


class TestEdgeRounding(unittest.TestCase):
    """Скругление и фаска: размер не «плывёт», объём меняется в разумную сторону."""

    def test_fillet_convex_keeps_size(self):
        b = ok("к = box size=[60,60,60]\nк = fillet [к] radius=6 edges=convex")
        size = b.analysis["metrics"]["size"]
        for v in size:
            self.assertAlmostEqual(v, 60.0, delta=0.25)
        self.assertLess(b.analysis["metrics"]["volume_cm3"], 216.0)
        self.assertGreater(b.analysis["metrics"]["volume_cm3"], 200.0)

    def test_fillet_adds_material_on_concave_edge(self):
        base = ok("а = box size=[90,30,30] at=[-30,0,0]\n"
                  "б = box size=[30,30,80] at=[15,0,0]\nс = union [а, б]")
        rounded = ok("а = box size=[90,30,30] at=[-30,0,0]\n"
                     "б = box size=[30,30,80] at=[15,0,0]\nс = union [а, б]\n"
                     "с = fillet [с] radius=6 edges=concave")
        self.assertGreater(rounded.analysis["metrics"]["volume_cm3"],
                           base.analysis["metrics"]["volume_cm3"])

    def test_chamfer_cuts_corner_at_45(self):
        b = ok("п = box size=[150,75,10]\nп = chamfer [п] width=2 edges=convex")
        m = b.analysis["metrics"]
        for v in m["size"]:
            self.assertAlmostEqual(v, {"x": 150, "y": 75, "z": 10}[
                ["x", "y", "z"][list(m["size"]).index(v)]], delta=0.3)
        self.assertLess(m["volume_cm3"], 112.5)
        self.assertGreater(m["volume_cm3"], 100.0)

    def test_edges_value_is_validated(self):
        err = fails("к = box size=[20,20,20]\nк = fillet [к] radius=2 edges=рёбра")
        self.assertIn("convex", err["message"])


class TestExport(unittest.TestCase):
    def test_3mf_is_valid_zip(self):
        b = ok("куб = box size=[20,20,20]")
        data = export_3mf(b.visible_solids())
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            self.assertIn("3D/3dmodel.model", names)
            model = zf.read("3D/3dmodel.model").decode("utf-8")
        self.assertIn("<vertex", model)
        self.assertIn("<triangle", model)


class TestLeanBuild(unittest.TestCase):
    """Сборка без scipy/skimage/Pillow: свой мешер и свой PNG-кодек."""

    def test_mesher_matches_sphere_volume(self):
        import numpy as np
        from forma.geometry import manifold_from_arrays
        from forma.mesher import mesh_field

        R, h = 20.0, 1.0
        xs = np.arange(-R - 2 * h, R + 2 * h + 1e-9, h, dtype=np.float32)
        X, Y, Z = np.meshgrid(xs, xs, xs, indexing="ij")
        field = (np.sqrt(X * X + Y * Y + Z * Z) - R).astype(np.float32)
        verts, faces = mesh_field(field, origin=(float(xs[0]),) * 3, spacing=h)
        solid = manifold_from_arrays(verts, faces, what="сфера")
        true_volume = 4 / 3 * np.pi * R ** 3 / 1000.0
        self.assertAlmostEqual(solid.volume() / 1000.0 / true_volume, 1.0, delta=0.01)

    def test_png_roundtrip(self):
        import numpy as np
        from forma.geometry import png_bytes, read_png

        arr = (np.random.default_rng(7).random((23, 31, 3)) * 255).astype(np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            path.write_bytes(png_bytes(arr))
            back = read_png(path)
        self.assertEqual(back.shape, arr.shape)
        self.assertTrue((back == arr).all())

    def test_no_heavy_science_stack(self):
        # сборка from_sdf/blob в отдельном процессе не должна тянуть scipy,
        # scikit-image или Pillow (в тестах trimesh может импортировать их сам)
        import subprocess
        code = (
            "import sys; sys.path.insert(0, r'%s');\n"
            "from forma.run import build;\n"
            "build('ш = from_sdf expression=\"sd_sphere(x,y,z,10)\" "
            "bounds=[-12,-12,-12,12,12,12] resolution=2');\n"
            "build('к = blob spheres=[[0,0,20,15],[0,0,45,12]] blend=6 resolution=2');\n"
            "bad = [n for n in ('scipy', 'skimage', 'PIL') if n in sys.modules];\n"
            "print(','.join(bad))"
        ) % str(ROOT)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             timeout=180)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(out.stdout.strip(), "", "лишние зависимости в сборке")

    def test_symmetry_only_when_asked(self):
        # без проверки симметрии дорогая метрика не считается на большой сетке
        b = ok("т = human height=1500 detail=низкий")
        self.assertEqual(b.analysis["metrics"]["symmetry"], {})
        b2 = ok("т = human height=1500 detail=низкий\ncheck т symmetric x 5")
        self.assertIn("x", b2.analysis["metrics"]["symmetry"])


if __name__ == "__main__":
    unittest.main()
