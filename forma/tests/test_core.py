"""Тесты ядра ФОРМА 3D. Запуск: python -m unittest discover -s tests"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.errors import DslError  # noqa: E402
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


class TestPrimitives(unittest.TestCase):
    def test_box_size(self):
        b = ok("б = box size=[50,60,70]")
        self.assertEqual(len(b.scene.objects), 1)
        m = b.analysis["metrics"]
        self.assertAlmostEqual(m["size"][0], 50, places=3)
        self.assertAlmostEqual(m["size"][1], 60, places=3)
        self.assertAlmostEqual(m["size"][2], 70, places=3)
        self.assertAlmostEqual(m["volume_cm3"], 210.0, places=2)

    def test_box_on_floor(self):
        b = ok("б = box size=[10,10,10]")
        self.assertAlmostEqual(b.analysis["metrics"]["bbox"][2], 0.0, places=4)

    def test_sphere_center(self):
        b = ok("ш = sphere radius=10 at=[0,0,50]")
        bbox = b.analysis["metrics"]["bbox"]
        self.assertAlmostEqual(bbox[2], 40, delta=0.5)
        self.assertAlmostEqual(bbox[5], 60, delta=0.5)

    def test_rounded_box(self):
        b = ok("б = box size=[40,40,40] round=5")
        m = b.analysis["metrics"]
        self.assertLess(m["volume_cm3"], 64.0)
        self.assertGreater(m["volume_cm3"], 61.0)

    def test_cylinder_cone(self):
        b = ok("ц = cylinder radius=20 height=40\nк = cone radius=10 height=20")
        self.assertEqual(len(b.scene.objects), 2)

    def test_parameters_and_expressions(self):
        b = ok("ш = 2\nб = box size=[10*ш, 20, 30]")
        self.assertAlmostEqual(b.analysis["metrics"]["size"][0], 20, places=3)

    def test_functions_in_expressions(self):
        b = ok("б = box size=[2*pi*10, 10, 10]")
        self.assertAlmostEqual(b.analysis["metrics"]["size"][0], 62.83, delta=0.1)


class TestBooleans(unittest.TestCase):
    def test_union_parts(self):
        b = ok("a = box size=[10,10,10]\nb = box size=[10,10,10] at=[20,0,0]\nc = union [a,b]")
        self.assertEqual(b.analysis["metrics"]["parts"], 2)

    def test_difference_hole(self):
        b = ok("""
к = box size=[40,40,40]
о = cylinder radius=8 height=100 at=[0,0,-10]
д = difference [к, о]
check д genus 1
""")
        self.assertEqual(b.analysis["checks_passed"], 1)

    def test_intersect(self):
        b = ok("""
a = sphere radius=20
b = sphere radius=20 at=[20,0,0]
c = intersect [a,b]
""")
        self.assertLess(b.analysis["metrics"]["volume_cm3"], 20)

    def test_difference_empty_error(self):
        err = fails("""
a = box size=[10,10,10]
b = box size=[100,100,100]
c = difference [a,b]
""")
        self.assertIn("ничего не осталось", err["message"].lower())


class TestLatheAndShell(unittest.TestCase):
    def test_lathe_volume(self):
        b = ok("ц = lathe points=[[0,0],[10,0],[10,20],[0,20]] segments=128")
        expected = 3.14159265 * 100 * 20 / 1000
        self.assertAlmostEqual(b.analysis["metrics"]["volume_cm3"], expected, delta=1.0)

    def test_lathe_thickness_wall(self):
        b = ok("""
к = lathe points=[[0,0],[40,0],[40,90],[0,90]] segments=128 thickness=4 open=top
check к watertight
check к wall 3..5
""")
        self.assertEqual(b.analysis["checks_passed"], 2)
        wall = b.analysis["metrics"]["wall"]
        self.assertIsNotNone(wall)
        self.assertAlmostEqual(wall["median"], 4.0, delta=0.5)

    def test_lathe_closed_is_solid(self):
        b = ok("к = lathe points=[[0,0],[40,0],[40,90],[0,90]] segments=96")
        self.assertIsNone(b.analysis["metrics"]["wall"])

    def test_sweep_handle(self):
        b = ok("""
р = sweep path=[[40,0,30],[60,0,30],[60,0,70],[40,0,70]] radius=5 smooth=6
check р watertight
""")
        self.assertEqual(b.analysis["checks_passed"], 1)

    def test_loft_axis_x(self):
        b = ok("""
с1 = [[-20,0],[20,0],[20,20],[-20,20]]
с2 = [[-30,0],[30,0],[30,30],[-30,30]]
к = loft sections=[с1,с2] positions=[0,100] axis=x
""")
        size = b.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 100, places=2)
        self.assertAlmostEqual(size[1], 60, places=2)

    def test_loft_mismatched_sections(self):
        err = fails("""
с1 = [[-20,0],[20,0],[20,20]]
с2 = [[-30,0],[30,0],[30,30],[-30,30]]
к = loft sections=[с1,с2] positions=[0,100]
""")
        self.assertIn("разное количество точек", err["message"])

    def test_extrude_with_hole(self):
        b = ok("""
д = extrude profile=[[-20,-20],[20,-20],[20,20],[-20,20]] holes=[[[-8,-8],[8,-8],[8,8],[-8,8]]] height=10
check д genus 1
""")
        self.assertEqual(b.analysis["checks_passed"], 1)


class TestTransforms(unittest.TestCase):
    def test_translate(self):
        b = ok("""
a = box size=[10,10,10]
b = translate [a] offset=[100,0,0]
""")
        self.assertAlmostEqual(b.analysis["metrics"]["size"][0], 10)

    def test_rotate_box(self):
        b = ok("""
a = box size=[100,20,10]
b = rotate [a] angle=90 axis=z
""")
        size = b.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 20, places=2)
        self.assertAlmostEqual(size[1], 100, places=2)

    def test_array_radial(self):
        b = ok("""
с = box size=[30,30,10]
м = array [с] count=8 mode=radial around=z center=[20,0,0]
""")
        self.assertEqual(b.analysis["metrics"]["parts"], 1)
        self.assertEqual(len(b.scene.objects["м"].manifold.decompose()), 1)

    def test_mirror_keep(self):
        b = ok("""
a = box size=[10,10,10] at=[20,0,0]
b = mirror [a] plane=x keep=true
""")
        self.assertAlmostEqual(b.analysis["metrics"]["size"][0], 50, delta=1.0)

    def test_twist_keeps_solid(self):
        b = ok("""
a = box size=[20,20,100]
b = twist [a] angle=90 axis=z
check b watertight
""")
        self.assertEqual(b.analysis["checks_passed"], 1)


class TestSdf(unittest.TestCase):
    def test_from_sdf_sphere(self):
        b = ok("""
ш = from_sdf expression="sqrt(x*x+y*y+z*z)-20" bounds=[-25,-25,-25,25,25,25] resolution=2
check ш volume 28..38
""")
        self.assertEqual(b.analysis["checks_passed"], 1)

    def test_blob_merges(self):
        b = ok("""
к = blob spheres=[[0,0,30,20],[0,0,65,15]] blend=8 resolution=2
check к parts 1
""")
        self.assertEqual(b.analysis["metrics"]["parts"], 1)

    def test_sdf_rejects_dangerous_code(self):
        err = fails('x = from_sdf expression="__import__(\'os\').system(\'echo 1\')" bounds=[-1,-1,-1,1,1,1]')
        self.assertIn("встроенные функции", err["message"])


class TestChecks(unittest.TestCase):
    def test_check_pass_and_fail(self):
        b = ok("""
б = box size=[50,50,50]
check б height 45..55
check б height 60..70
check б watertight
check б parts 1
check б volume 120..130
""")
        checks = b.analysis["checks"]
        self.assertEqual(len(checks), 5)
        self.assertEqual([c["ok"] for c in checks], [True, False, True, True, True])

    def test_symmetric_check(self):
        b = ok("""
ш = sphere radius=20 at=[0,0,20]
check ш symmetric x
check ш symmetric y
""")
        self.assertTrue(all(c["ok"] for c in b.analysis["checks"]))

    def test_gap_check(self):
        b = ok("""
a = box size=[10,10,10]
b = box size=[10,10,10] at=[20,0,0]
check a gap b 5..20
""")
        self.assertTrue(b.analysis["checks"][0]["ok"])

    def test_inside_check(self):
        b = ok("""
a = box size=[10,10,10] at=[0,0,20]
b = box size=[100,100,100]
check a inside b
""")
        self.assertTrue(b.analysis["checks"][0]["ok"])

    def test_unknown_rule(self):
        b = ok("""
a = box size=[10,10,10]
check a красота 10
""")
        self.assertFalse(b.analysis["checks"][0]["ok"])


class TestErrors(unittest.TestCase):
    def test_unknown_command_hint(self):
        err = fails("кружка = lathee points=[[0,0],[10,0],[10,10],[0,10]]")
        self.assertIn("Неизвестная команда", err["message"])
        self.assertIn("lathe", (err.get("hint") or "").lower())

    def test_unknown_param_hint(self):
        err = fails("a = box size=[10,10,10] radus=5")
        self.assertIn("Неизвестный параметр", err["message"])

    def test_error_has_line_number(self):
        err = fails("a = box size=[10,10,10]\nb = sphere radius=-5")
        self.assertEqual(err["line"], 2)

    def test_missing_object(self):
        err = fails("a = box size=[10,10,10]\nb = union [a, чужой]")
        self.assertIn("Не найден", err["message"])

    def test_bad_points(self):
        err = fails("a = lathe points=[[0,0],[10,0]]")
        self.assertIn("3 точки", err["message"])

    def test_empty_script(self):
        err = fails("# только комментарий")
        self.assertIn("пуст", err["message"].lower())


class TestExamples(unittest.TestCase):
    def test_all_examples_build(self):
        for path in sorted((ROOT / "examples").glob("*.forma")):
            with self.subTest(example=path.name):
                b = build(path.read_text(encoding="utf-8"))
                self.assertTrue(b.ok, f"{path.name}: {b.error}")
                self.assertIsNotNone(b.analysis)
                self.assertEqual(b.analysis["checks_passed"], b.analysis["checks_total"],
                                 f"{path.name}: не все проверки пройдены")


class TestExport(unittest.TestCase):
    def test_glb_roundtrip(self):
        b = ok("ш = sphere radius=20 segments=48")
        data = b.glb()
        self.assertEqual(data[:4], b"glTF")
        import io
        import trimesh
        scene = trimesh.load(io.BytesIO(data), file_type="glb")
        self.assertGreaterEqual(len(scene.geometry), 1)

    def test_stl_and_obj(self):
        from forma.geometry import export_obj, export_stl
        b = ok("б = box size=[10,20,30]")
        solids = b.visible_solids()
        self.assertGreater(len(export_stl(solids)), 84)
        self.assertIn(b"v ", export_obj(solids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
