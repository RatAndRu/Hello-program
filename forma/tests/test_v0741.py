"""0.74.1: лечение экспорта из 0.80 и кэш операций из 0.77 — на дереве 0.74.

Две вещи, обе проверяются по результату, а не по факту подключения:

1. **Экспорт.** Шесть примитивов раньше строились и рисовались, но не
   записывались в STL/GLB: `bracket` и `lightning` при скруглении (микрокромки
   после Minkowski), `скоба`, `cloud` (касание поверхности самой себя в седловой
   точке SDF), `screw` с потайной головкой — а вместе с ним `drive`. Лечение:
   пересборка из своей сетки, посадка вершин на сетку 0.001…0.005 мм и профиль
   вращения для головки; для здоровых тел этот путь не включается.
2. **Кэш.** Обещает ровно одно: та же деталь не строится дважды, а сцена
   получается такая же, как без кэша. Поэтому проверяется совпадение — имена,
   цвета, подсборки, зависимость от входной геометрии и от параметров сцены.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import numpy as np

from forma import cache as cache_module
from forma.cache import OpCache, references_object, scene_digest
from forma.geometry import (export_glb, export_stl, manifold_mesh,
                            _clean_manifold_arrays, snap_manifold)
from forma.ops import lookup
from forma.run import build
from forma.topology import analyze_topology

ROOT = Path(__file__).resolve().parent.parent
BROKEN_UNTIL_080 = ("bracket", "lightning", "скоба", "cloud", "screw", "drive")


def volumes(result) -> dict[str, float]:
    return {solid.name: round(solid.stats()["volume"], 4) for solid in result.visible_solids()}


def build_both(script: str):
    """Сборка с кэшем и без: второй прогон — эталон."""
    os.environ.pop("FORMA_CACHE", None)
    with_cache = build(script, analyze_model=False)
    os.environ["FORMA_CACHE"] = "0"
    try:
        without = build(script, analyze_model=False)
    finally:
        os.environ.pop("FORMA_CACHE", None)
    return with_cache, without


class ExportRepairTest(unittest.TestCase):
    """То, что 0.80 вылечила в записи сетки, работает и здесь."""

    def test_previously_broken_primitives_export(self):
        for name in BROKEN_UNTIL_080:
            with self.subTest(primitive=name):
                spec = lookup(name)
                result = build(spec.example, analyze_model=False)
                self.assertTrue(result.ok, (result.error or {}).get("message"))
                solids = result.scene.visible_solids()
                self.assertTrue(solids, name)
                self.assertGreater(len(export_stl(solids)), 0, f"{name}: пустой STL")
                self.assertGreater(len(export_glb(solids)), 0, f"{name}: пустой GLB")

    def test_export_copy_passes_topology_gate(self):
        for name in ("bracket", "cloud", "screw"):
            with self.subTest(primitive=name):
                result = build(lookup(name).example, analyze_model=False)
                for solid in result.scene.visible_solids():
                    verts, faces = _clean_manifold_arrays(solid.manifold)
                    report = analyze_topology(verts, faces, include_quality=False)
                    self.assertTrue(report["ok"], f"{name}: {report}")
                    self.assertEqual(report["non_manifold_edges"], 0)

    def test_healthy_body_is_not_snapped(self):
        # Посадка сетки — последняя мера. Для чистого тела она обязана молчать,
        # иначе каждый экспорт молча сдвигал бы вершины.
        result = build("к = box size=[40,30,20]\n", analyze_model=False)
        solid = result.scene.visible_solids()[0]
        before = manifold_mesh(solid.manifold)[0].copy()
        for step in (1e-3, 2e-3, 3e-3, 5e-3):
            self.assertIsNone(snap_manifold(solid.manifold, step), f"шаг {step}")
        after = manifold_mesh(solid.manifold)[0]
        self.assertTrue(np.array_equal(before, after))

    def test_snap_keeps_volume_and_size(self):
        # Посаженное тело отличается только «пылью»: объём и габарит — те же.
        result = build("с = cloud\n", analyze_model=False)
        solid = result.scene.visible_solids()[0]
        snapped = snap_manifold(solid.manifold, 1e-3)
        if snapped is None:  # тело чистое — тогда и сажать нечего
            return
        self.assertLess(abs(float(snapped.volume() / solid.manifold.volume() - 1.0)), 0.0002)
        delta = np.abs(np.asarray(snapped.bounding_box()) - np.asarray(solid.manifold.bounding_box()))
        self.assertLessEqual(float(delta.max()), 1.5e-3)


class OpCacheTest(unittest.TestCase):
    def setUp(self):
        cache_module._SHARED = None

    def tearDown(self):
        cache_module._SHARED = None
        os.environ.pop("FORMA_CACHE", None)

    def test_repeated_primitives_are_cached(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10]\n"
                       "c = box size=[10, 10, 10]\n", analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))
        stats = result.scene.op_cache.stats()
        self.assertTrue(stats["enabled"])
        self.assertGreaterEqual(stats["hits"], 2)
        # Имя принадлежит строке, а не кэшу: все три объекта на месте.
        self.assertEqual(sorted(volumes(result)), ["a", "b", "c"])
        self.assertEqual(len(set(volumes(result).values())), 1)

    def test_cached_part_keeps_own_color(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10] color=#ff0000\n", analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))
        colors = {solid.name: solid.color for solid in result.visible_solids()}
        self.assertNotEqual(colors["a"], colors["b"])
        self.assertEqual(colors["b"], "#ff0000")

    def test_scene_is_identical_with_cache_and_without(self):
        script = (ROOT / "examples" / "clock.forma").read_text(encoding="utf-8")
        with_cache, without = build_both(script)
        self.assertTrue(with_cache.ok, (with_cache.error or {}).get("message"))
        self.assertTrue(without.ok, (without.error or {}).get("message"))
        self.assertEqual(volumes(with_cache), volumes(without))
        self.assertGreater(with_cache.scene.op_cache.stats()["hits"], 0)

    def test_warm_rebuild_reuses_geometry(self):
        cache_module._SHARED = None
        script = (ROOT / "examples" / "clock.forma").read_text(encoding="utf-8")
        cold = build(script, analyze_model=False)
        warm = build(script, analyze_model=False)
        self.assertTrue(cold.ok and warm.ok)
        stats = warm.scene.op_cache.stats()
        self.assertGreater(stats["hits"], 10)
        self.assertGreater(stats["size"], 0)
        self.assertEqual(volumes(warm), volumes(cold))

    def test_triangle_budget_is_respected(self):
        cache = OpCache(limit=100, max_tris=10_000)

        class Heavy:
            def num_tri(self):
                return 50_000

        class Light:
            def num_tri(self):
                return 100

        cache.put(("box", 1), Heavy())
        self.assertEqual(len(cache.items), 0, "слишком тяжёлая геометрия не кэшируется")
        cache.put(("box", 2), Light())
        self.assertEqual(cache.stats()["tris"], 100)

    def test_env_switches_cache_off(self):
        os.environ["FORMA_CACHE"] = "0"
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10]\n", analyze_model=False)
        stats = result.scene.op_cache.stats()
        self.assertFalse(stats["enabled"])
        self.assertEqual((stats["hits"], stats["size"]), (0, 0))

    def test_parameter_change_invalidates_geometry(self):
        result = build("R = 10\n"
                       "a = cylinder radius=R height=20\n"
                       "R = 25\n"
                       "b = cylinder radius=R height=20\n", analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))
        sizes = volumes(result)
        self.assertNotAlmostEqual(sizes["a"], sizes["b"], places=2)
        self.assertGreater(sizes["b"], sizes["a"] * 4)

    def test_composite_operation_keeps_its_parts(self):
        script = "s1 = socket\ns2 = socket\n"
        with_cache, without = build_both(script)
        self.assertTrue(without.ok, (without.error or {}).get("message"))
        self.assertTrue(with_cache.ok, (with_cache.error or {}).get("message"))
        self.assertGreater(len(without.scene.objects), 4)
        self.assertEqual(sorted(with_cache.scene.objects), sorted(without.scene.objects))

    def test_operation_on_existing_object_is_not_cached(self):
        script = ("hole = box size=[10, 10, 80] at=[0, 0, 0]\n"
                  "wall = box size=[60, 60, 80]\n"
                  "wall = difference [wall, hole]\n")
        with_cache, without = build_both(script)
        self.assertTrue(with_cache.ok, (with_cache.error or {}).get("message"))
        self.assertEqual(volumes(with_cache), volumes(without))
        self.assertLess(volumes(with_cache)["wall"], 60 * 60 * 80)

    def test_two_unions_with_same_params_differ(self):
        # Ключ не должен «слепнуть» к входным объектам: одинаковая строка с
        # разными деталями обязана дать разную геометрию.
        script = ("a = box size=[10, 10, 10]\n"
                  "b = box size=[20, 20, 20]\n"
                  "c = box size=[5, 5, 5]\n"
                  "u = union [a, b]\n"
                  "v = union [a, c]\n")
        result = build(script, analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))
        first, second = volumes(result)["u"], volumes(result)["v"]
        self.assertNotAlmostEqual(first, second, places=1)

    def test_payload_reports_cache_stats(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10]\n", analyze_model=False)
        payload = result.payload(light=True)
        self.assertIn("cache", payload)
        self.assertGreaterEqual(payload["cache"]["hits"], 1)
        self.assertEqual(payload["cache"]["limit"], OpCache().limit)
        self.assertIn("tris", payload["cache"])

    def test_lru_drops_oldest(self):
        cache = OpCache(limit=4)
        for index in range(6):
            cache.put(("box", index), f"m{index}")
        self.assertEqual(len(cache.items), 4)
        self.assertNotIn(("box", 0), cache.items)
        cache.get(("box", 5))
        self.assertEqual(cache.stats()["hits"], 1)

    def test_reference_detection_and_digest(self):
        self.assertTrue(references_object(["wall"], {"wall": object()}))
        self.assertTrue(references_object(["[wall, hole]"], {"wall": object(), "hole": object()}))
        self.assertFalse(references_object(["[10, 10]"], {"wall": object()}))

        class FakeScene:
            params = {"R": 10}
            settings = {"precision": {"segments": 32}}

        first = scene_digest(FakeScene())
        FakeScene.params = {"R": 12}
        self.assertNotEqual(first, scene_digest(FakeScene()))


if __name__ == "__main__":
    unittest.main()
