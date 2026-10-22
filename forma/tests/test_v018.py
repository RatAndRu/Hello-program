"""0.18: регионная покраска, сборка примеров, крепёж и снимки.

Проверяем то, что просили в этой итерации:
* кисть/покраска красятся регионами, а не по одному полигону;
* цвет уходит и в снимок PNG, и в GLB (COLOR_0);
* в примерах-витринах ничего не висит: каждая деталь касается сборки;
* винт с полукруглой головкой собирается (раньше падал с внутренней ошибкой).
"""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

import numpy as np

from forma.geometry import (export_glb, manifold_mesh, region_mask,
                            region_triangle_colors, paint_point_colors)
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent


def scene(script: str):
    res = build(script)
    if res.error:
        raise AssertionError(res.error)
    return res


def glb_json(data: bytes) -> dict:
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


class PaintRegionTest(unittest.TestCase):
    """Регион покраски: одна команда — целая полоса, а не треугольник."""

    MUG = ("корпус = cylinder radius=34 height=95 r2=40 segments=128\n"
           "полость = cylinder radius=30 height=89 r2=36 segments=128\n"
           "полость = translate [полость] offset=[0,0,6]\n"
           "кружка = difference [корпус, полость]\n"
           "paint кружка #2f6fb0 side=верх\n"
           "paint кружка #d94f3d height=18..34\n"
           "color кружка #efe9df")

    def test_paint_saved_in_payload(self):
        res = scene(self.MUG)
        obj = next(o for o in res.payload()["objects"] if o["name"] == "кружка")
        self.assertEqual(len(obj["paint"]), 2)
        self.assertEqual(obj["paint"][0]["side"], "верх")

    def test_region_mask_geometry(self):
        pts = np.array([[0, 0, 5], [0, 0, 25], [60, 0, 50]], dtype=float)
        mask = region_mask({"height": [10, 30]}, pts)
        self.assertEqual(mask.tolist(), [False, True, False])
        mask = region_mask({"box": [-10, -10, -10, 10, 10, 10]}, pts)
        self.assertEqual(mask.tolist(), [True, False, False])
        mask = region_mask({"radius": [0, 20]}, pts)
        self.assertEqual(mask.tolist(), [True, True, False])

    def test_side_uses_normals(self):
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=float)
        faces = np.array([[0, 1, 2]])
        colors = region_triangle_colors([{"color": "#ff0000", "side": "верх"}],
                                        verts, faces)
        self.assertTrue(np.allclose(colors[0], [1, 0, 0]))
        colors = region_triangle_colors([{"color": "#00ff00", "side": "низ"}],
                                        verts, faces)
        self.assertTrue(np.allclose(colors[0], [1, 1, 1]))

    def test_point_colors_follow_regions(self):
        pts = np.array([[0, 0, 90], [0, 0, 20]], dtype=float)
        rgb = paint_point_colors([{"color": "#2f6fb0", "height": [80, 100]}], pts)
        self.assertGreater(rgb[0][2], rgb[0][0])
        self.assertTrue(np.allclose(rgb[1], [1, 1, 1]))

    def test_glb_has_vertex_colors(self):
        res = scene(self.MUG)
        doc = glb_json(export_glb(res.visible_solids()))
        attrs = doc["meshes"][0]["primitives"][0]["attributes"]
        self.assertIn("COLOR_0", attrs)

    def test_glb_color_count_matches_vertices(self):
        res = scene(self.MUG)
        data = export_glb(res.visible_solids())
        doc = glb_json(data)
        prim = doc["meshes"][0]["primitives"][0]
        pos = doc["accessors"][prim["attributes"]["POSITION"]]
        col = doc["accessors"][prim["attributes"]["COLOR_0"]]
        self.assertEqual(pos["count"], col["count"])


class ScrewHeadTest(unittest.TestCase):
    """Винт с полукруглой головкой: раньше падал на умножении тел."""

    def test_pan_head(self):
        for head in ("потай", "полукруг", "шестигранник"):
            with self.subTest(head=head):
                res = scene(f"в = screw d=5 length=9 head={head} head_d=11")
                self.assertEqual(len(res.visible_solids()), 1)


class AssemblyTest(unittest.TestCase):
    """В витринах нет висящих деталей: каждая касается основной сборки."""

    MODELS = ("clock.forma", "motorcycle.forma", "wardrobe.forma")

    @staticmethod
    def loose_parts(solids) -> list[str]:
        from forma.geometry import solid_parts
        n = len(solids)
        if n < 2:
            return []
        boxes = [np.asarray(s.bbox, dtype=float) for s in solids]
        parts = [solid_parts(s.manifold) for s in solids]
        near = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                a, b = boxes[i], boxes[j]
                gap = max(a[0] - b[3], b[0] - a[3], a[1] - b[4], b[1] - a[4],
                          a[2] - b[5], b[2] - a[5], 0.0)
                if gap > 1.0:
                    continue
                merged = solid_parts(solids[i].manifold + solids[j].manifold)
                if merged < parts[i] + parts[j] or gap <= 0.5:
                    near[i].append(j)
                    near[j].append(i)
        seen = {0}
        stack = [0]
        while stack:
            k = stack.pop()
            for m in near[k]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return [solids[i].name for i in range(n) if i not in seen]

    def test_examples_are_assembled(self):
        for filename in self.MODELS:
            with self.subTest(model=filename):
                res = scene((ROOT / "examples" / filename).read_text(encoding="utf-8"))
                loose = self.loose_parts(res.visible_solids())
                self.assertEqual(loose, [], f"{filename}: висят {loose}")

    def test_clock_animation_moves_every_wheel(self):
        res = scene((ROOT / "examples" / "clock.forma").read_text(encoding="utf-8"))
        clips = res.payload()["timeline"]["clips"]
        moved = {c.get("object") for c in clips}
        for wheel in ("барабан", "минутное", "промежуточное", "секундное",
                      "анкерное", "мотор_шестерня", "баланс", "вилка"):
            self.assertIn(wheel, moved)

    def test_clock_meshing_distances(self):
        """Межосевые расстояния = m·(z1+z2)/2, иначе зубья не входят в зацепление."""
        res = scene((ROOT / "examples" / "clock.forma").read_text(encoding="utf-8"))
        objects = {o["name"]: o for o in res.payload()["objects"]}
        pairs = [("барабан", "минутное", 48, 30), ("мотор_шестерня", "барабан", 12, 48),
                 ("минутное", "промежуточное", 30, 36),
                 ("промежуточное", "секундное", 36, 24),
                 ("секундное", "анкерное", 24, 20)]
        for a, b, za, zb in pairs:
            with self.subTest(pair=(a, b)):
                ba, bb_ = objects[a]["bbox"], objects[b]["bbox"]
                ca = ((ba[0] + ba[3]) / 2, (ba[2] + ba[5]) / 2)
                cb = ((bb_[0] + bb_[3]) / 2, (bb_[2] + bb_[5]) / 2)
                dist = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
                # модуль передачи в примере — 2.6: a = m·(z1+z2)/2
                self.assertAlmostEqual(dist, 2.6 * (za + zb) / 2.0, delta=0.8)
