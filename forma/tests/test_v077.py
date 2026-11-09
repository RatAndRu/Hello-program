"""0.77: кэш операций и плитки на все примитивы.

Кэш обещает ровно одно: та же деталь не строится дважды, а сцена получается
такая же, как без кэша. Поэтому проверяется не «стало быстрее», а совпадение:
имена, цвета, подсборки и зависимость от входной геометрии. Плитки проверяются
на полноту — в реестре нет примитива без картинки.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from forma.cache import OpCache, references_object, scene_digest
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent
THUMBS = ROOT / "web" / "thumbs"
MANIFEST = THUMBS / "tiles.json"


def volumes(result) -> dict[str, float]:
    return {solid.name: round(solid.stats()["volume"], 4) for solid in result.visible_solids()}


def build_both(script: str):
    """Сборка с кэшем и без: второй прогон — эталон."""
    import os

    os.environ.pop("FORMA_CACHE", None)
    with_cache = build(script, analyze_model=False)
    os.environ["FORMA_CACHE"] = "0"
    try:
        without = build(script, analyze_model=False)
    finally:
        os.environ.pop("FORMA_CACHE", None)
    return with_cache, without


class CacheTest(unittest.TestCase):
    def test_repeated_primitives_are_cached(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10]\n"
                       "c = box size=[10, 10, 10]\n", analyze_model=False)
        self.assertTrue(result.ok)
        stats = result.scene.op_cache.stats()
        self.assertTrue(stats["enabled"])
        self.assertGreaterEqual(stats["hits"], 2)
        # Имя принадлежит строке, а не кэшу: все три объекта на месте.
        self.assertEqual(sorted(volumes(result)), ["a", "b", "c"])
        self.assertEqual(len(set(volumes(result).values())), 1)

    def test_cached_tile_keeps_own_color(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10] color=#ff0000\n", analyze_model=False)
        self.assertTrue(result.ok)
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

    def test_env_switches_cache_off(self):
        import os

        os.environ["FORMA_CACHE"] = "0"
        try:
            result = build("a = box size=[10, 10, 10]\n"
                           "b = box size=[10, 10, 10]\n", analyze_model=False)
        finally:
            os.environ.pop("FORMA_CACHE", None)
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

    def test_payload_reports_cache_stats(self):
        result = build("a = box size=[10, 10, 10]\n"
                       "b = box size=[10, 10, 10]\n", analyze_model=False)
        payload = result.payload(light=True)
        self.assertIn("cache", payload)
        self.assertGreaterEqual(payload["cache"]["hits"], 1)
        self.assertEqual(payload["cache"]["limit"], OpCache().limit)

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


class TileCatalogTest(unittest.TestCase):
    """Плитки: каждый примитив реестра, своя строка параметров и 128 px."""

    @classmethod
    def setUpClass(cls):
        import forma.run  # noqa: F401  — регистрирует операции
        from forma.ops import OPS

        cls.primitives = {spec.name for spec in OPS.values()
                          if spec.category == "Примитивы"} - {"drive"}
        cls.tiles = json.loads(MANIFEST.read_text(encoding="utf-8"))["tiles"]

    def test_every_primitive_has_a_tile(self):
        have = {row["op"] for row in self.tiles}
        self.assertEqual(sorted(self.primitives - have), [])
        self.assertGreaterEqual(len(self.tiles), 100)

    def test_rows_are_complete(self):
        for row in self.tiles:
            file = THUMBS / f"{row['op']}.png"
            self.assertTrue(file.is_file(), row["op"])
            data = file.read_bytes()
            self.assertEqual((int.from_bytes(data[16:20], "big"),
                              int.from_bytes(data[20:24], "big")), (128, 128), row["op"])
            self.assertTrue(row["title"].strip(), row["op"])
            self.assertNotIn("\n", row["params"], row["op"])

    def test_factory_lines_build(self):
        # Клик по плитке вставляет ровно эту строку — значит она обязана
        # собираться и давать тело. Проверяются все плитки, не выборка.
        for row in self.tiles:
            tail = f" {row['params']}" if row["params"] else ""
            result = build(f"плитка = {row['op']}{tail}\n", analyze_model=False)
            self.assertTrue(result.ok, f"{row['op']}: {(result.error or {}).get('message')}")
            self.assertTrue(result.scene.visible_solids(), row["op"])

    def test_ui_uses_manifest(self):
        app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        webui = (ROOT / "forma" / "webui.py").read_text(encoding="utf-8")
        self.assertIn("tileList", app)
        self.assertIn("insertTileOp", app)
        self.assertIn("tiles-search", app)
        self.assertIn("tiles.json", webui)
        self.assertIn('"params"', webui)


if __name__ == "__main__":
    unittest.main()
