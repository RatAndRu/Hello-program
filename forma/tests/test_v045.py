"""0.45: материалы, топология сот и локальная геометрия кромок/деталей."""

from __future__ import annotations

import json
import math
import struct
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401
from forma.geometry import manifold_mesh
from forma.ops import lookup
from forma.ops_blade import _arc_path, _section
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def ok(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def fail(script: str) -> str:
    result = build(script, analyze_model=False)
    assert not result.ok, script
    return (result.error or {}).get("message", "")


def solid(result, name="о"):
    return result.scene.objects[name].manifold


def size(result, name="о"):
    bb = solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m, point, edge=0.08) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-9)


def one(m):
    assert m.status() == mf.Error.NoError, m.status()
    parts = [p for p in m.decompose() if p.volume() > 1e-6]
    assert len(parts) == 1, len(parts)


class MaterialMirrorTest(unittest.TestCase):
    def test_continuous_mirror_reaches_model_payload_and_glb(self):
        b = ok("о = box size=[20,30,10]\nцвет о #b8c6d8 mirror=0.35")
        self.assertAlmostEqual(b.scene.objects["о"].mirror, 0.35)
        self.assertAlmostEqual(b.payload()["objects"][0]["mirror"], 0.35)
        data = b.glb()
        chunk_len = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20:20 + chunk_len].decode("utf-8"))
        materials = [m for m in document["materials"]
                     if m.get("name", "").startswith("mat_mirror0.35__")]
        self.assertEqual(len(materials), 1)
        pbr = materials[0]["pbrMetallicRoughness"]
        self.assertAlmostEqual(pbr["metallicFactor"], 0.35)
        self.assertLess(pbr["roughnessFactor"], 0.5)
        self.assertGreater(pbr["roughnessFactor"], 0.02)

    def test_full_and_boolean_mirror_remain_compatible(self):
        for raw, expected in (("0", 0.0), ("1", 1.0), ("да", 1.0), ("нет", 0.0)):
            with self.subTest(raw=raw):
                b = ok(f"о = sphere radius=10\nцвет о mirror={raw}")
                self.assertAlmostEqual(b.scene.objects["о"].mirror, expected)
        data = ok("о = sphere radius=10\nцвет о mirror=1").glb()
        chunk_len = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20:20 + chunk_len].decode("utf-8"))
        material = next(m for m in document["materials"]
                        if m.get("name", "").startswith("mat_mirror__"))
        self.assertEqual(material["pbrMetallicRoughness"]["metallicFactor"], 1.0)

    def test_material_slider_is_continuous_and_saved(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        self.assertIn('id="mat-mirror"', html)
        self.assertIn('min="0" max="1" step="0.01"', html)
        self.assertIn("mirror=", js)
        self.assertIn("envMapIntensity", viewer)


class TopologyTest(unittest.TestCase):
    def test_honeycomb_has_real_pentagons_and_hexagons(self):
        for divisions, panels, hexagons, triangles in (
                (0, 32, 20, 116), (1, 122, 110, 476)):
            with self.subTest(divisions=divisions):
                b = ok(f"о = icosphere radius=40 mode=сота divisions={divisions}")
                topology = b.scene.objects["о"].meta["topology"]
                self.assertEqual(topology["panels"], panels)
                self.assertEqual(topology["pentagons"], 12)
                self.assertEqual(topology["hexagons"], hexagons)
                self.assertEqual(solid(b).num_tri(), triangles)
                one(solid(b))

    def test_octa_faces_and_divisions_are_independent(self):
        for faces in (6, 8, 10):
            with self.subTest(faces=faces):
                b = ok(f"о = octa radius=30 height=80 faces={faces} divisions=0")
                np.testing.assert_allclose(size(b), (60, 60, 80), atol=1e-5)
                self.assertEqual(solid(b).num_tri(), faces)
                self.assertEqual(b.scene.objects["о"].meta["faces"], faces)
                divided = ok(f"о = octa radius=30 height=80 faces={faces} divisions=1")
                self.assertEqual(solid(divided).num_tri(), faces * 4)
                np.testing.assert_allclose(size(divided), (60, 60, 80), atol=1e-5)
        self.assertIn("faces", fail("о = octa radius=30 faces=7"))

    def test_sphere_sector_has_actual_smoothing(self):
        sharp = ok("о = sector radius=40 angle=130 smooth=0")
        smooth = ok("о = sector radius=40 angle=130 smooth=1")
        self.assertGreater(solid(smooth).num_tri(), solid(sharp).num_tri() * 3)
        one(solid(smooth))


class TransitionEdgeTest(unittest.TestCase):
    def test_semioval_rounds_outside_but_keeps_faces_and_hole(self):
        b = ok("о = полуовал width=60 height=40 thickness=6 hole=8 smooth=2")
        m = solid(b)
        one(m)
        self.assertEqual(m.genus(), 1)
        self.assertAlmostEqual(size(b)[1], 6.0, delta=1e-5)
        verts, _ = manifold_mesh(m)
        self.assertGreater(np.count_nonzero(np.isclose(verts[:, 1], -3.0, atol=1e-6)), 12)
        self.assertGreater(np.count_nonzero(np.isclose(verts[:, 1], 3.0, atol=1e-6)), 12)

    def test_pie_ingot_and_u_bracket_keep_broad_planes(self):
        for script in (
                "о = pie diameter=100 angle=100 thickness=8 smooth=2",
                "о = ingot length=60 width=30 height=20 top_size=[70,40] smooth=2",
                "о = скоба length=80 width=60 height=30 wall=4 open=вниз smooth=2"):
            with self.subTest(script=script):
                b = ok(script)
                m = solid(b)
                one(m)
                bb = m.bounding_box()
                verts, _ = manifold_mesh(m)
                self.assertGreaterEqual(np.count_nonzero(np.isclose(verts[:, 2], bb[2], atol=1e-6)), 4)
                self.assertGreaterEqual(np.count_nonzero(np.isclose(verts[:, 2], bb[5], atol=1e-6)), 4)

    def test_button_remains_two_separate_objects(self):
        b = ok("кнопка = button diameter=30 height=10 smooth=1")
        self.assertEqual(len(b.scene.objects), 2)
        for obj in b.scene.objects.values():
            one(obj.manifold)
            self.assertGreater(obj.manifold.volume(), 100.0)

    def test_filled_bracket_adds_corner_without_losing_holes(self):
        regular = ok("о = bracket width=80 depth=60 height=40 thickness=5 holes=2 smooth=1")
        filled = ok("о = bracket width=80 depth=60 height=40 thickness=5 holes=2 "
                    "corner=заполненный smooth=1")
        one(solid(regular))
        one(solid(filled))
        self.assertEqual(solid(filled).genus(), 4)
        self.assertGreater(solid(filled).volume(), solid(regular).volume() + 100.0)


class VesselAndGlyphTest(unittest.TestCase):
    def test_vertical_rim_does_not_need_radial_lip(self):
        low = ok("о = воронка top=80 bottom=12 height=50 lip=0 rim=0 rim_height=0")
        high = ok("о = воронка top=80 bottom=12 height=50 lip=0 rim=0 rim_height=5")
        self.assertAlmostEqual(size(high)[2] - size(low)[2], 5.0, delta=1e-5)
        self.assertEqual(solid(high).genus(), 1)
        plate0 = ok("о = plate diameter=100 depth=15 rim=0 rim_height=0")
        plate4 = ok("о = plate diameter=100 depth=15 rim=0 rim_height=4")
        self.assertGreater(solid(plate4).volume(), solid(plate0).volume() + 500.0)
        one(solid(plate4))

    def test_crescent_and_yin_yang_walls_make_cutters(self):
        for script in ("о = crescent radius=50 thickness=40 depth=8 wall=2",
                       "о = yin_yang diameter=80 thick=8 wall=2"):
            with self.subTest(script=script):
                m = solid(ok(script))
                one(m)
                self.assertEqual(m.genus(), 1)
        self.assertIn("mode", fail("о = yin_yang mode=рамка wall=2"))
        self.assertNotIn("mode", lookup("yin_yang").params)

    def test_cloud_is_connected_exact_size_and_has_flat_floor(self):
        flat = ok("о = cloud size=[80,45,35] puffs=6 segments=16 seed=3")
        open_ = ok("о = cloud size=[80,45,35] puffs=6 segments=16 seed=3 flat=нет")
        for b in (flat, open_):
            one(solid(b))
            np.testing.assert_allclose(size(b), (80, 45, 35), atol=1e-5)
        fv, _ = manifold_mesh(solid(flat))
        ov, _ = manifold_mesh(solid(open_))
        self.assertGreater(np.count_nonzero(np.isclose(fv[:, 2], 0.0, atol=1e-6)), 20)
        self.assertLess(np.count_nonzero(np.isclose(ov[:, 2], 0.0, atol=1e-6)), 20)

    def test_maple_has_palmate_lobes_and_a_narrow_petiole(self):
        maple = solid(ok("о = leaf kind=клен length=90 width=45 thickness=2 curl=0"))
        oak = solid(ok("о = leaf kind=дуб length=90 width=45 thickness=2 curl=0"))
        one(maple)
        self.assertLess(maple.volume(), oak.volume() * 0.9)
        self.assertGreaterEqual(maple.num_vert(), 40)
        # У −X именно узкий черенок, а не заострённый конец радиальной звезды.
        for dz in (-1.0, 0.0, 1.0):
            self.assertTrue(inside(maple, (-44.0, -1.0, 22.5 + dz)))
        for dz in (-2.2, 2.2):
            self.assertFalse(inside(maple, (-44.0, -1.0, 22.5 + dz)))


class HardwareAndHandleTest(unittest.TestCase):
    def test_pulley_accepts_solid_shaft_zero(self):
        solid_pulley = solid(ok("о = pulley diameter=80 width=20 bore=0"))
        bored = solid(ok("о = pulley diameter=80 width=20 bore=10"))
        one(solid_pulley)
        self.assertEqual(solid_pulley.genus(), 0)
        self.assertEqual(bored.genus(), 1)
        self.assertGreater(solid_pulley.volume(), bored.volume())

    def test_torx_has_six_lobes_not_twelve_rectangular_rays(self):
        b = ok("о = screw d=5 length=30 head=шестигранник drive=звезда "
               "drive_depth=2 thread=нет")
        m = solid(b)
        one(m)
        top = m.bounding_box()[5]
        z = top - 0.5
        drive_size = 0.42 * 2.05 * 5.0
        radius = drive_size * 0.5 * 0.85
        for degrees in range(0, 360, 60):
            angle = math.radians(degrees)
            point = (radius * math.cos(angle), radius * math.sin(angle), z)
            self.assertFalse(inside(m, point), f"лопасть {degrees}° должна быть пустой")
        for degrees in range(30, 360, 60):
            angle = math.radians(degrees)
            point = (radius * math.cos(angle), radius * math.sin(angle), z)
            self.assertTrue(inside(m, point), f"между лопастями {degrees}° должен быть металл")

    def test_zero_neck_brings_full_thread_to_head(self):
        direct = ok("о = screw d=5 length=30 head=шестигранник drive=нет neck=0")
        necked = ok("о = screw d=5 length=30 head=шестигранник drive=нет neck=4")
        dm = direct.scene.objects["о"].meta
        nm = necked.scene.objects["о"].meta
        self.assertEqual(dm["neck"], 0.0)
        self.assertGreater(dm["thread_length"], nm["thread_length"])
        body_len = 30.0
        tip = dm["tip"]
        thread_len = dm["thread_length"]
        z = body_len - 0.5
        t = (z - tip) / thread_len
        theta = 2.0 * math.pi * thread_len / (0.45 * 5.0) * t
        point = (2.4 * math.cos(theta), 2.4 * math.sin(theta), z)
        self.assertTrue(inside(solid(direct), point, edge=0.04))
        self.assertFalse(inside(solid(necked), point, edge=0.04))

    def test_through_posts_work_for_one_and_two_posts(self):
        for posts in (1, 2):
            with self.subTest(posts=posts):
                joint = ok(f"о = handle length=100 height=30 diameter=8 posts={posts} "
                           "post_mode=стык post_top=15 plates=нет")
                through = ok(f"о = handle length=100 height=30 diameter=8 posts={posts} "
                             "post_mode=сквозь post_top=15 plates=нет")
                one(solid(through))
                self.assertAlmostEqual(size(through)[2], 49.0, delta=1e-5)
                self.assertAlmostEqual(size(joint)[2], 34.0, delta=1e-5)
                self.assertGreater(solid(through).volume(), solid(joint).volume())


class SpiralGussetBladeTest(unittest.TestCase):
    def test_swirl_merge_allows_contact_and_base_hides_start(self):
        merged = ok("о = swirl radius=30 height=70 coils=3 wire=24 merge=да")
        one(solid(merged))
        self.assertEqual(solid(merged).genus(), 0)
        self.assertIn("сольются", fail("о = swirl radius=30 height=70 coils=3 wire=24"))
        base = ok("о = swirl radius=30 height=70 coils=3 wire=8 base=да")
        one(solid(base))
        np.testing.assert_allclose(size(base)[:2], (60, 60), atol=1e-5)
        verts, _ = manifold_mesh(solid(base))
        self.assertGreater(np.count_nonzero(np.isclose(verts[:, 2], 0.0, atol=1e-6)), 30)

    def test_gusset_hill_has_one_adjustable_rectangular_recess(self):
        straight = solid(ok("о = gusset leg=70 height=55 thickness=6"))
        hill = solid(ok("о = gusset leg=70 height=55 thickness=6 shape=горка notch=0"))
        recessed = solid(ok("о = gusset leg=70 height=55 thickness=6 shape=горка "
                            "notch=8 notch_width=24"))
        one(recessed)
        self.assertGreater(hill.volume(), straight.volume())
        self.assertAlmostEqual(hill.volume() - recessed.volume(), 8 * 24 * 6, delta=1.0)

    def test_blade_bends_in_width_plane_with_signed_direction(self):
        for sign in (-1, 1):
            path = _arc_path(180.0, sign * 15.0, 24)
            self.assertAlmostEqual(float(np.max(sign * path[:, 1])), 15.0, delta=0.05)
            np.testing.assert_allclose(path[:, 2], 0.0, atol=1e-9)
        positive = solid(ok("о = blade length=180 width=24 thick=5 kind=катана curve=15"))
        negative = solid(ok("о = blade length=180 width=24 thick=5 kind=катана curve=-15"))
        one(positive)
        one(negative)
        self.assertAlmostEqual(positive.volume(), negative.volume(), delta=1.0)

    def test_kind_changes_single_double_and_hook_geometry(self):
        common = "length=180 width=24 thick=5 curve=15 profile=прямой section=клин tip=острое"
        katana = solid(ok(f"о = blade {common} kind=катана"))
        stiletto = solid(ok(f"о = blade {common} kind=стилет"))
        sickle = solid(ok("о = blade length=180 width=24 thick=5 kind=серп curve=0"))
        for m in (katana, stiletto, sickle):
            one(m)
        self.assertNotAlmostEqual(katana.volume(), stiletto.volume(), delta=500.0)
        sickle_bb = sickle.bounding_box()
        self.assertGreater(sickle_bb[5] - sickle_bb[2], 100.0)
        self.assertLess(sickle_bb[3] - sickle_bb[0], 130.0)
        single = _section(24, 5, "одна", 0.62, 0.0, profile="клин")
        double = _section(24, 5, "две", 0.5, 0.0, profile="клин")
        left_single = single[np.isclose(single[:, 0], -12.0), 1]
        right_single = single[np.isclose(single[:, 0], 12.0), 1]
        self.assertLess(left_single.max() - left_single.min(), 0.1)
        self.assertGreater(right_single.max() - right_single.min(), 4.9)
        for x in (-12.0, 12.0):
            edge = double[np.isclose(double[:, 0], x), 1]
            self.assertLess(edge.max() - edge.min(), 0.1)


class CardContractTest(unittest.TestCase):
    def test_new_controls_are_in_cards_and_specs(self):
        js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for key in ("faces", "corner", "post_mode", "post_top", "merge", "base",
                    "notch_width", "neck"):
            with self.subTest(key=key):
                self.assertIn(f"k: '{key}'", js)
        for op, key in (("sector", "smooth"), ("crescent", "wall"),
                        ("swirl", "merge"), ("handle", "post_mode"),
                        ("gusset", "notch"), ("bracket", "corner")):
            with self.subTest(op=op, key=key):
                self.assertIn(key, lookup(op).params)
        self.assertNotIn("k: 'mode', label: 'режим', v: 'фигура'", js)


if __name__ == "__main__":
    unittest.main()
