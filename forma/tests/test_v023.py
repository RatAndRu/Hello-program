"""0.23: слияние деталей, свечение/прозрачность, новые примитивы, индикатор."""

from __future__ import annotations

import json
import struct
import unittest

import manifold3d as mf

from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError((result.error or {}).get("message", result.error))
    return result


def fails(script: str) -> str:
    result = build(script, analyze_model=False)
    if result.ok:
        raise AssertionError("ожидалась ошибка")
    return (result.error or {}).get("message", "")


def last(result):
    return list(result.scene.objects.values())[-1]


def gltf_json(data: bytes) -> dict:
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length].decode("utf-8"))


class TestFuse(unittest.TestCase):
    def test_fuse_merges_and_rounds_joint(self):
        raw = ok("а = box size=[40,40,40] round=2 center=да\n"
                 "б = cylinder radius=10 height=60 center=да at=[0,0,20]\n"
                 "б = rotate [б] angle=90 axis=y\n"
                 "в = union [а,б]")
        fused = ok("а = box size=[40,40,40] round=2 center=да\n"
                   "б = cylinder radius=10 height=60 center=да at=[0,0,20]\n"
                   "б = rotate [б] angle=90 axis=y\n"
                   "в = fuse [а,б] radius=6")
        base = last(raw)
        solid = last(fused)
        self.assertTrue(raw.ok and fused.ok)
        # детали вошли в одно тело, исходники спрятаны
        self.assertEqual([o.name for o in fused.scene.objects.values() if o.visible], ["в"])
        self.assertEqual(len(solid.manifold.decompose()), 1)
        self.assertGreater(solid.manifold.num_tri(), base.manifold.num_tri())
        # объём почти сохраняется: слияние скругляет стык, а не раздувает тело
        self.assertLess(abs(solid.volume_cm3 - base.volume_cm3) / base.volume_cm3, 0.15)

    def test_fuse_keeps_watertight(self):
        b = ok("а = box size=[50,30,30] round=3 center=да\n"
               "б = sphere radius=16 at=[0,0,15]\n"
               "в = fuse [а,б] radius=5 edges=все")
        m = last(b).manifold
        self.assertEqual(m.genus(), 0)
        self.assertEqual(len(m.decompose()), 1)

    def test_fuse_bad_radius_is_reported(self):
        """Огромный радиус не должен давать «внутреннюю ошибку»."""
        res = build("а = box size=[30,30,30]\nб = cylinder radius=8 height=40 "
                    "center=да at=[0,0,10]\nв = fuse [а,б] radius=400", analyze_model=False)
        # важно: даже на абсурдном радиусе не должно быть «внутренней ошибки»
        self.assertFalse((res.error or {}).get("internal", False))
        if res.ok:
            m = last(res).manifold
            self.assertEqual(len(m.decompose()), 1)


class TestStyles(unittest.TestCase):
    def test_emissive_material_preset(self):
        b = ok("лампа = sphere radius=10 material=led")
        o = last(b)
        self.assertEqual(o.emissive, "#25f06a")
        self.assertGreater(o.emissive_strength, 1.0)

    def test_emissive_explicit(self):
        b = ok("ц = box size=[10,2,10] emissive=#ff0000 emissive_strength=3.5")
        o = last(b)
        self.assertEqual(o.emissive, "#ff0000")
        self.assertEqual(o.emissive_strength, 3.5)

    def test_transmission_from_preset(self):
        b = ok("с = box size=[20,20,3] material=glass")
        self.assertGreater(last(b).transmission, 0.5)

    def test_bad_transmission_rejected(self):
        msg = fails("с = box size=[20,20,3] transmission=2")
        self.assertIn("0", msg)

    def test_glb_has_emissive_and_transmission(self):
        b = ok("л = box size=[20,2,10] material=led\n"
               "с = box size=[24,1,12] at=[0,-3,0] material=glass")
        doc = gltf_json(b.glb())
        used = set(doc.get("extensionsUsed") or [])
        self.assertIn("KHR_materials_emissive_strength", used)
        self.assertIn("KHR_materials_transmission", used)
        mats = {m["name"]: m for m in doc["materials"]}
        led = mats["mat_л"]
        self.assertIn("emissiveFactor", led)
        self.assertIn("KHR_materials_emissive_strength", led["extensions"])
        glass = mats["mat_с"]
        self.assertIn("KHR_materials_transmission", glass["extensions"])

    def test_glb_preserves_dim_emissive_strength(self):
        for strength in (0.18, 0.0):
            with self.subTest(strength=strength):
                b = ok(f"экран = box size=[20,2,10] emissive=#020817 emissive_strength={strength}")
                doc = gltf_json(b.glb())
                self.assertIn("KHR_materials_emissive_strength", set(doc.get("extensionsUsed") or []))
                material = {m["name"]: m for m in doc["materials"]}["mat_экран"]
                self.assertEqual(material["extensions"]["KHR_materials_emissive_strength"],
                                 {"emissiveStrength": strength})

    def test_payload_carries_style(self):
        b = build("л = box size=[20,2,10] material=led", analyze_model=False)
        payload = b.payload()
        obj = payload["objects"][0]
        self.assertEqual(obj["emissive"], "#25f06a")
        self.assertIn("transmission", obj)


class TestNewPrimitives(unittest.TestCase):
    def test_heart(self):
        b = ok("сердце = heart width=60 depth=18 round=3")
        o = last(b)
        bb = o.stats()["bbox"]
        self.assertAlmostEqual(bb[3] - bb[0], 60.0, delta=0.6)
        self.assertEqual(len(o.manifold.decompose()), 1)

    def test_heart_height(self):
        # с 0.41 сердце стоит: высота по Z, толщина по Y
        b = ok("сердце = heart width=80 depth=20 height=40")
        bb = last(b).stats()["bbox"]
        self.assertAlmostEqual(bb[5] - bb[2], 40.0, delta=0.6)
        self.assertAlmostEqual(bb[4] - bb[1], 20.0, delta=0.3)
        self.assertAlmostEqual(bb[2], 0.0, delta=0.01)

    def test_plus_has_four_arms(self):
        b = ok("плюс = plus arm=60 thick=18 depth=14")
        o = last(b)
        bb = o.stats()["bbox"]
        self.assertAlmostEqual(bb[3] - bb[0], 60.0, delta=0.3)
        self.assertAlmostEqual(bb[5] - bb[2], 60.0, delta=0.3)
        # объём ≈ два бруса минус пересечение
        expect = (60 * 18 + 60 * 18 - 18 * 18) * 14 / 1000.0
        self.assertAlmostEqual(o.volume_cm3, expect, delta=expect * 0.03)

    def test_plus_too_thick(self):
        self.assertIn("олщина", fails("п = plus arm=20 thick=30"))

    def test_sector_angles(self):
        quarter = last(ok("д = sector radius=40 angle=90"))
        half = last(ok("д = sector radius=40 angle=180"))
        self.assertAlmostEqual(quarter.volume_cm3, half.volume_cm3 / 2, delta=0.5)
        bb = quarter.stats()["bbox"]
        self.assertAlmostEqual(bb[5] - bb[2], 40.0, delta=0.4)

    def test_sector_shell_is_closed(self):
        b = ok("д = sector radius=40 angle=120 thickness=4")
        m = last(b).manifold
        self.assertEqual(m.genus(), 0)
        self.assertAlmostEqual(last(b).volume_cm3,
                               2 * 3.14159 * 40 * 40 * (120 / 360) * 4 / 1000, delta=2.0)

    def test_sector_bad_angle(self):
        self.assertIn("angle", fails("д = sector radius=40 angle=0"))

    def test_spiral(self):
        b = ok("с = spiral radius=60 turns=3 wire=6 height=6")
        o = last(b)
        self.assertEqual(len(o.manifold.decompose()), 1)
        self.assertGreater(o.stats()["bbox"][3] - o.stats()["bbox"][0], 100)

    def test_spiral_overlap_reported(self):
        self.assertIn("налезут", fails("с = spiral radius=20 turns=8 wire=6"))

    def test_rope_is_braided(self):
        b = ok("к = rope length=200 diameter=20 strands=3")
        o = last(b)
        self.assertEqual(len(o.manifold.decompose()), 1)
        bb = o.stats()["bbox"]
        self.assertAlmostEqual(bb[5] - bb[2], 200.0, delta=6.0)
        self.assertAlmostEqual(bb[3] - bb[0], 20.0, delta=2.0)

    def test_rope_strands_fit(self):
        msg = fails("к = rope length=100 diameter=10 strands=6 wire=8")
        self.assertIn("не проход", msg.lower())


class TestSevenSeg(unittest.TestCase):
    def test_digits(self):
        b = ok('д = seven_seg text="21:38" height=54')
        o = last(b)
        # штрихи внутри цифры сварены в одно тело, а цифры разделены зазором
        self.assertGreaterEqual(len(o.manifold.decompose()), 5)
        bb = o.stats()["bbox"]
        self.assertAlmostEqual(bb[5] - bb[2], 54.0, delta=0.3)   # высота по Z
        self.assertEqual(o.emissive, "")

    def test_unknown_char(self):
        self.assertIn("показывать", fails('д = seven_seg text="2#3"'))

    def test_led_clock_example(self):
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "examples" / "clock_led.forma"
        if not path.exists():
            self.skipTest("примера нет")
        result = build(path.read_text(encoding="utf-8"), analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))


if __name__ == "__main__":
    unittest.main()
