"""Тесты детекторов качества сетки (forma/mesh_quality.py).

Проверяем не «красиво ли», а что детекторы срабатывают на синтетических
дефектах и молчат на чистых примитивах. Дефекты собираются вручную, чтобы
тест не зависел от поведения ядра.
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from forma.mesh_quality import (
    Rules, analyze, format_report, link_cycles, mesh_of, short_warnings,
    vertex_links,
)


def tetra(offset=(0.0, 0.0, 0.0), size=10.0):
    ox, oy, oz = offset
    verts = np.array([[ox, oy, oz], [ox + size, oy, oz],
                      [ox, oy + size, oz], [ox, oy, oz + size]], dtype=float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
    return verts, faces


def fan_disc(rings=24, radius=30.0, centre=(0.0, 0.0, 0.0)):
    """Плоский веер: центр + кольцо, все треугольники сходятся в центр."""
    cx, cy, cz = centre
    verts = [[cx, cy, cz]]
    for i in range(rings):
        a = 2 * math.pi * i / rings
        verts.append([cx + radius * math.cos(a), cy + radius * math.sin(a), cz])
    faces = [[0, i + 1, (i + 1) % rings + 1] for i in range(rings)]
    return np.array(verts, float), np.array(faces, np.int64)


class TopologyTest(unittest.TestCase):
    def test_clean_tetrahedron_has_no_problems(self):
        rep = analyze(tetra())
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertEqual(rep["boundary_edges"], 0)
        self.assertEqual(rep["nonmanifold_edges"], 0)
        self.assertEqual(rep["nonmanifold_vertices"], 0)

    def test_open_mesh_reports_boundary(self):
        verts, faces = tetra()
        rep = analyze((verts, faces[:-1]))          # одну грань убрали
        self.assertEqual(rep["boundary_edges"], 3)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("граничных" in p for p in rep["problems"]))

    def test_two_tetrahedra_in_one_point_is_a_bowtie(self):
        """Две поверхности, касающиеся одной вершиной, — «песочные часы»."""
        v1, f1 = tetra()
        # второй тетраэдр стоит на вершине (10, 0, 0) первого и смотрит вниз
        v2 = np.array([[10, 0, 0], [20, 0, 0], [10, 10, 0], [10, 0, -10]], float)
        verts = np.vstack([v1, v2[1:]])            # 0..3, затем 4,5,6
        f2 = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], np.int64)
        remap = {0: 1, 1: 4, 2: 5, 3: 6}           # 0 второго -> вершина 1 первого
        faces = np.vstack([f1, np.vectorize(remap.get)(f2)])
        links = vertex_links(faces)
        self.assertEqual(link_cycles(faces, 1, links), 2)
        rep = analyze((verts, faces))
        self.assertEqual(rep["nonmanifold_vertices"], 1)
        self.assertTrue(any("песошниц" in p for p in rep["problems"]))

    def test_nonmanifold_edge(self):
        """Три треугольника на одном ребре — non-manifold."""
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0],
                          [0, -10, 0], [0, 0, 10]], float)
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]], np.int64)
        rep = analyze((verts, faces))
        self.assertEqual(rep["nonmanifold_edges"], 1)

    def test_duplicate_face(self):
        verts, faces = tetra()
        rep = analyze((verts, np.vstack([faces, faces[:1]])))
        self.assertEqual(rep["duplicate_faces"], 1)
        self.assertFalse(rep["ok"])

    def test_empty_mesh_has_a_printable_report(self):
        rep = analyze((np.empty((0, 3)), np.empty((0, 3), dtype=np.int64)))
        self.assertFalse(rep["ok"])
        self.assertIn("сетка пуста", format_report(rep))


class ShapeTest(unittest.TestCase):
    def test_needle_is_detected_and_cap_two(self):
        """Игла (угол 1°) и она же, но тупая (угол 178°) — разные классы."""
        needle = np.array([[0, 0, 0], [100, 0, 0], [50, 0.9, 0]], float)
        v = np.vstack([needle, [[0, 0, 5], [100, 0, 5], [50, 0.9, 5]]])
        f = np.array([[0, 1, 2], [3, 5, 4], [0, 1, 3], [1, 4, 3], [1, 2, 4],
                      [2, 5, 4], [2, 0, 5], [0, 3, 5]], np.int64)
        rep = analyze((v, f), Rules(sliver_area_pct=0.0))
        self.assertGreaterEqual(rep["needle_count"], 1)
        self.assertLess(rep["min_angle_deg"], 5.0)

    def test_flat_fan_is_pole_but_not_a_shading_problem(self):
        """Веер на плоскости: полюс есть, «видимых» игл нет.

        У плоского веера все нормали одинаковы, экран ничего не показывает —
        это косметика, и детектор обязан отличать её от игл на кривизне.
        """
        verts, faces = fan_disc()
        rep = analyze((verts, faces), Rules(sliver_area_pct=0.0))
        self.assertGreaterEqual(rep["valence_max"], 24)
        self.assertEqual(rep["hub_count"], 1)
        self.assertEqual(rep["needle_curved_count"], 0)

class CleanPrimitiveTest(unittest.TestCase):
    """На чистых телах детектор не должен ничего выдумывать."""

    def test_cube_and_cylinder_are_clean(self):
        import manifold3d as m3

        cube = analyze(m3.Manifold.cube((50, 50, 50), True))
        self.assertEqual(cube["strut_count"], 0)
        self.assertEqual(cube["hub_count"], 0)
        self.assertEqual(cube["density_hotspot_count"], 0)
        self.assertTrue(cube["ok"])

        cyl = analyze(m3.Manifold.cylinder(30, 20, 128))
        self.assertEqual(cyl["strut_count"], 0)
        self.assertEqual(cyl["needle_curved_count"], 0)

    def test_cylinder_through_plate_makes_visible_slivers(self):
        """Булева операция «цилиндр × плоскость» — источник игл на кривизне.

        Это и есть тот класс дефекта, который видно на скруглениях: длинные
        тонкие треугольники вдоль линии пересечения.
        """
        import manifold3d as m3

        body = (m3.Manifold.cylinder(30, 20, 128)
                ^ m3.Manifold.cube((70, 70, 10), True).translate((0, 0, 5)))
        rep = analyze(body, Rules(sliver_area_pct=0.0))
        self.assertGreater(rep["needle_curved_count"], 0)
        self.assertGreater(rep["needle_curved_area_pct"], 0.5)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("иглы на кривизне" in p for p in rep["problems"]))


class ReportTest(unittest.TestCase):
    def test_report_and_warnings(self):
        verts, faces = fan_disc()
        rep = analyze((verts, faces))
        text = format_report(rep)
        self.assertIn("КАЧЕСТВО СЕТКИ", text)
        self.assertIn("полюс", text)
        self.assertIsInstance(short_warnings(rep), list)

    def test_mesh_of_accepts_tuple_and_manifold(self):
        import manifold3d as m3

        v, f = mesh_of((np.zeros((3, 3)), np.array([[0, 1, 2]])))
        self.assertEqual(len(f), 1)
        v, f = mesh_of(m3.Manifold.cube((10, 10, 10)))
        self.assertEqual(len(v), 8)

    def test_mesh_of_accepts_pyvista_cells_and_report_is_json_ready(self):
        import json

        class FakePyvista:
            points = np.zeros((3, 3))
            faces = np.array([3, 0, 1, 2], dtype=np.int64)

        v, f = mesh_of(FakePyvista())
        self.assertEqual(f.shape, (1, 3))
        json.dumps(analyze(tetra()), ensure_ascii=False)


class CliTest(unittest.TestCase):
    def test_cli_json_covers_every_visible_forma_object(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from forma.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.forma"
            path.write_text(
                "а = box size=[10,10,10]\n"
                "б = box size=[10,10,10]\n"
                "б = place [б] at=[30,0,0] align=center\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["mesh", str(path), "--json"])
            report = json.loads(out.getvalue())
            self.assertEqual(code, 0, report)
            self.assertGreater(report["vertices"], 8)
            self.assertNotIn("_artifacts_obj", report)

    def test_cli_returns_one_for_dirty_mesh(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from forma.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dirty.forma"
            path.write_text(
                "ц = cylinder radius=30 height=20 segments=128\n"
                "п = box size=[70,70,10]\n"
                "п = place [п] at=[0,0,5] align=center\n"
                "т = union [ц, п]\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["mesh", str(path), "--json", "--sliver", "0"])
            report = json.loads(out.getvalue())
            self.assertEqual(code, 1, report.get("problems"))
            self.assertFalse(report["ok"])


class SimplifyLogTest(unittest.TestCase):
    def test_simplify_logs_before_and_after_mesh_quality(self):
        from forma.run import build

        script = ("ц = cylinder radius=30 height=20 segments=128\n"
                  "п = box size=[70,70,10]\n"
                  "п = place [п] at=[0,0,5] align=center\n"
                  "т = union [ц, п]\n"
                  "т = simplify [т] tolerance=0.02\n")
        result = build(script)
        self.assertTrue(result.ok, result.error)
        messages = [item["message"] for item in result.log]
        effect = [m for m in messages if m.startswith("simplify т: иглы на кривизне")]
        self.assertEqual(len(effect), 1, messages)
        self.assertIn("стяжек", effect[0])
        self.assertIn("→", effect[0])


class CheckRuleTest(unittest.TestCase):
    """Правило `check … сетка` в языке сценария."""

    def test_cube_passes_mesh_check(self):
        from forma.run import build

        script = "к = box size=[40,40,40]\ncheck к сетка\n"
        b = build(script)
        self.assertTrue(b.ok, b.error)
        rule = [c for c in b.analysis["checks"] if c["rule"] == "mesh"]
        self.assertEqual(len(rule), 1)
        self.assertTrue(rule[0]["ok"], rule[0]["text"])

    def test_rule_text_contains_the_metrics(self):
        from forma.run import build

        b = build("к = box size=[40,40,40]\ncheck к сетка 0.5\n")
        rule = [c for c in b.analysis["checks"] if c["rule"] == "mesh"][0]
        for word in ("стяжек", "полюсов", "игл на кривизне", "сгустков"):
            self.assertIn(word, rule["text"])

    def test_build_report_mentions_mesh_defects(self):
        """Отчёт сборки сам предупреждает о стяжках — без строки check."""
        from forma.run import build

        script = ("ц = cylinder radius=30 height=20 segments=128\n"
                  "п = box size=[70,70,10]\n"
                  "п = place [п] at=[0,0,5] align=center\n"
                  "т = union [ц, п]\n")
        b = build(script)
        metrics = b.analysis["metrics"]
        self.assertIn("mesh_quality", metrics)
        self.assertIn("faces", metrics["mesh_quality"])
        self.assertTrue(any("Стяжка" in w for w in b.analysis["warnings"]),
                        b.analysis["warnings"])


if __name__ == "__main__":
    unittest.main()
