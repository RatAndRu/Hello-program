"""Приёмочные регрессии дополнительного пакета 0.48.

Проверяется геометрия, а не только успешный возврат команды: связность,
отсутствие скрытых отрицательных оболочек, габариты, полости, tessellation и
статический resource-preflight до входа в run_build.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manifold3d as mf
import numpy as np

from forma.geometry import manifold_mesh
from forma.ops_surface import _scale_tile
from forma.resources import RESOURCE_TRI_LIMIT, estimate_script_tris
from forma.run import build
from forma.webui import AppState

ROOT = Path(__file__).resolve().parents[1]


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


def obj(script: str, name: str = "о"):
    return ok(script).scene.objects[name]


def solid(script: str, name: str = "о") -> mf.Manifold:
    return obj(script, name).manifold


def valid(m: mf.Manifold, one: bool = True):
    assert m.status() == mf.Error.NoError, m.status()
    assert not m.is_empty() and m.volume() > 1e-7
    if one:
        positive = [p for p in m.decompose() if p.volume() > 1e-6]
        assert len(positive) == 1, [(p.volume(), p.bounding_box()) for p in m.decompose()]
    return m


def vertices(m: mf.Manifold) -> np.ndarray:
    return np.asarray(manifold_mesh(m)[0], dtype=np.float64)[:, :3]


def size(m: mf.Manifold) -> np.ndarray:
    bb = m.bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m: mf.Manifold, point, edge=0.08) -> bool:
    probe = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return bool((m ^ probe).volume() > 1e-9)


class ViewOrientationTest(unittest.TestCase):
    def test_front_and_iso_cameras_look_from_script_minus_y(self):
        source = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")

        def direction(name):
            match = re.search(rf"\b{name}: new THREE\.Vector3\(([^)]+)\)", source)
            self.assertIsNotNone(match, name)
            return [float(value.strip()) for value in match.group(1).split(",")]

        # GLB: script (X,Y,Z) -> view (X,Z,−Y). Вид «спереди» обязан
        # стоять со стороны script −Y == view +Z, иначе стрелка +X зеркалится.
        self.assertGreater(direction("front")[2], 0.0)
        self.assertLess(direction("back")[2], 0.0)
        self.assertGreater(direction("iso")[2], 0.0)


class RingRimStripTest(unittest.TestCase):
    def test_ring_cavity_and_independent_grooves(self):
        base = valid(solid("о = ring diameter=30 width=10 thickness=6"))
        closed = valid(solid("о = ring diameter=30 width=10 thickness=6 cavity=1.2"))
        opened = valid(solid("о = ring diameter=30 width=10 thickness=6 cavity=1.2 cavity_side=верх"))
        self.assertLess(closed.volume(), base.volume())
        self.assertLess(opened.volume(), closed.volume())
        volumes = []
        for profile in ("круглая", "прямоугольная", "треугольная", "трапециевидная"):
            with self.subTest(profile=profile):
                m = valid(solid(
                    "о = ring diameter=30 width=10 thickness=6 "
                    f"groove={profile} groove_width=2 groove_depth=1.2 "
                    "groove_side=обе groove_count=2"))
                self.assertLess(m.volume(), base.volume())
                volumes.append(m.volume())
        self.assertEqual(len({round(v, 3) for v in volumes}), 4)

    def test_disc_and_oval_have_continuous_rims(self):
        for op, dimensions in (("disc", "diameter=120"), ("oval", "width=200 length=120")):
            with self.subTest(op=op):
                base = valid(solid(f"о = {op} {dimensions} thickness=8"))
                concave = obj(f"о = {op} {dimensions} thickness=8 rim_profile=вогнутый "
                              "rim_height=2 rim_width=12 rim_offset=2 rim_side=обе")
                convex = obj(f"о = {op} {dimensions} thickness=8 rim_profile=выпуклый "
                             "rim_height=2 rim_width=12 rim_offset=2")
                valid(concave.manifold)
                valid(convex.manifold)
                self.assertLess(concave.manifold.volume(), base.volume())
                self.assertGreater(convex.manifold.volume(), base.volume())
                self.assertNotAlmostEqual(concave.manifold.volume(), convex.manifold.volume(), places=3)
                self.assertEqual(concave.meta["rim_profile"], "вогнутый")
                self.assertEqual(convex.meta["rim_profile"], "выпуклый")

    def test_strip_horseshoe_and_j_work_in_xz(self):
        for path in ("подкова", "J"):
            with self.subTest(path=path):
                m = valid(solid(f"о = strip length=180 width=12 thickness=4 path_z={path} curve_z=35"))
                self.assertGreater(size(m)[2], 45.0)
                self.assertAlmostEqual(m.volume(), 180 * 12 * 4, delta=180.0)
                short = valid(solid(f"о = strip length=180 width=12 thickness=4 path={path} plane=XZ curve=35"))
                self.assertAlmostEqual(m.volume(), short.volume(), delta=1e-4)


class VolumeGlyphsTest(unittest.TestCase):
    def test_volume_star_honours_twist_smooth_blade_and_bevel(self):
        prefix = "о = star points=5 outer=60 inner=25 depth=12 plane=плашмя volume=да "
        base = valid(solid(prefix + "bevel=0"))
        smooth = valid(solid(prefix + "bevel=0 smooth=1"))
        blade = valid(solid(prefix + "bevel=0 blade=.7"))
        bevel = valid(solid(prefix + "bevel=8"))
        twist = valid(solid(prefix + "bevel=0 twist=45"))
        vb, vs, vbl, vbe = map(vertices, (base, smooth, blade, bevel))
        self.assertEqual(vb.shape, vs.shape)
        self.assertEqual(vb.shape, vbl.shape)
        self.assertEqual(vb.shape, vbe.shape)
        self.assertGreater(float(np.max(np.abs(vs - vb))), 1e-3)
        self.assertGreater(float(np.max(np.abs(vbl[:, 2] - vb[:, 2]))), 1e-3)
        self.assertGreater(float(np.max(np.abs(vbe - vb))), 1e-3)
        self.assertGreater(twist.num_tri(), base.num_tri())
        self.assertNotAlmostEqual(twist.volume(), base.volume(), places=3)
        # Закрутка видна на торцевом кольце, а не только в числе треугольников.
        def bottom_angles(m):
            v = vertices(m)
            ring = v[np.abs(v[:, 2] - v[:, 2].min()) < 1e-5]
            xy = ring[:, :2] - ring[:, :2].mean(axis=0)
            radii = np.linalg.norm(xy, axis=1)
            tips = xy[radii > radii.max() - 1e-4]
            return np.sort(np.arctan2(tips[:, 1], tips[:, 0]))
        a0, a1 = bottom_angles(base), bottom_angles(twist)
        distances = np.abs((a1[:, None] - a0[None, :] + np.pi) % (2 * np.pi) - np.pi)
        self.assertGreater(float(np.min(np.min(distances, axis=1))), 0.05)
        combined = obj(prefix + "bevel=3 smooth=.8 twist=65 blade=.65 hole=12")
        valid(combined.manifold)
        self.assertTrue(combined.meta["volume_mode"])
        self.assertEqual(combined.manifold.genus(), 1)

    def test_heart_and_lightning_have_real_volume_modes(self):
        for op, dims in (("heart", "width=60 depth=18"), ("lightning", "height=100 width=44 depth=10")):
            with self.subTest(op=op):
                flat = valid(solid(f"о = {op} {dims} volume=нет"))
                volume = valid(solid(f"о = {op} {dims} volume=да"))
                self.assertGreater(volume.num_tri(), flat.num_tri())
                self.assertNotAlmostEqual(volume.volume(), flat.volume(), places=3)
                np.testing.assert_allclose(size(volume), size(flat), atol=1e-4)

    def test_volume_crescent_keeps_the_open_c_silhouette(self):
        flat = valid(solid("о = crescent radius=50 thickness=18 depth=12 volume=нет"))
        volume = valid(solid("о = crescent radius=50 thickness=18 depth=12 volume=да"))
        self.assertGreater(volume.num_tri(), flat.num_tri())
        self.assertGreater(volume.volume(), flat.volume())
        np.testing.assert_allclose(size(volume), size(flat), atol=1e-4)
        # Лучи через раскрытие справа не должны попадать в переднюю или
        # заднюю стенку: объём не разрешено получать заполнением вогнутости.
        for x in (15.0, 20.0, 25.0):
            self.assertEqual(volume.ray_cast([x, -200, 50], [x, 200, 50]), [])
        self.assertTrue(volume.ray_cast([-20, -200, 50], [-20, 200, 50]))
        deeper = valid(solid("о = crescent radius=50 thickness=18 depth=24 volume=да"))
        self.assertAlmostEqual(size(deeper)[1], 24.0, delta=1e-4)
        self.assertNotAlmostEqual(deeper.volume(), volume.volume(), places=3)

    def test_fireball_is_one_mesh_and_straightens_to_cone(self):
        curved = obj("о = yin_yang diameter=60 tail_length=90 tail_angle=65 straighten=0 plane=плашмя")
        straight = obj("о = yin_yang diameter=60 tail_length=90 tail_angle=65 straighten=1 plane=плашмя")
        valid(curved.manifold)
        valid(straight.manifold)
        self.assertTrue(curved.meta["fireball"])
        self.assertGreater(curved.manifold.bounding_box()[4], straight.manifold.bounding_box()[4] + 5.0)
        self.assertNotAlmostEqual(curved.manifold.volume(), straight.manifold.volume(), places=3)
        # Крайняя точка выпрямленного хвоста лежит на его оси Y=0.
        tip = vertices(straight.manifold)[np.argmax(vertices(straight.manifold)[:, 0])]
        self.assertAlmostEqual(float(tip[1]), 0.0, delta=1e-5)

    def test_tee_and_yoke_capsules_are_volumetric(self):
        for op, dims, extra in (("tee", [90, 14, 80], "stem=22"),
                                ("yoke", [80, 14, 110], "smooth=0")):
            with self.subTest(op=op):
                capsule = obj(f"о = {op} shape=капсулы {extra} round=0")
                oval = valid(solid(f"о = {op} shape=овалы {extra} round=0"))
                valid(capsule.manifold)
                self.assertTrue(capsule.meta["solid_capsules"])
                self.assertLess(capsule.manifold.volume(), oval.volume() * 0.95)
                self.assertGreater(capsule.manifold.num_tri(), oval.num_tri())
                np.testing.assert_allclose(size(capsule.manifold), dims, atol=1e-5)
        plain = solid("о = yoke shape=капсулы smooth=0")
        joint = solid("о = yoke shape=капсулы smooth=4")
        self.assertGreater(joint.volume(), plain.volume())


class HardwareAndGrooveTest(unittest.TestCase):
    def test_screw_head_only(self):
        full = valid(solid("о = screw d=12 length=70 head=полукруг"))
        head = obj("о = screw d=12 length=70 head=полукруг head_only=да")
        valid(head.manifold)
        self.assertTrue(head.meta["head_only"])
        self.assertEqual(head.meta["length"], 0.0)
        self.assertLess(size(head.manifold)[2], size(full)[2] * 0.5)

    def test_cube_hole_all_axes_and_hexagon(self):
        result = obj("о = cube_hole size=[40,40,40] hole=12 all_axes=да hole_shape=шестигранник")
        valid(result.manifold)
        self.assertEqual(result.meta["hole_shape"], ["шестигранник"] * 3)
        for start, end in (((-100, 0, 20), (100, 0, 20)),
                           ((0, -100, 20), (0, 100, 20)),
                           ((0, 0, -100), (0, 0, 100))):
            self.assertEqual(result.manifold.ray_cast(start, end), [])

    def test_shave_rejects_hidden_cavity_instead_of_returning_one(self):
        result = build("ц = cylinder radius=20 height=60 segments=96\n"
                       "ц = shave [ц] depth=10 radius=8", analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("скрытую полость", result.error["message"])
        opened = valid(solid("ц = cylinder radius=20 height=60 segments=96\n"
                             "ц = shave [ц] depth=0 radius=8 groove=овальная", "ц"))
        self.assertFalse(any(p.volume() < -1e-6 for p in opened.decompose()))

    def test_cut_plane_has_two_sides(self):
        lower = valid(solid("о = box size=[60,40,100]\nо = cut_plane [о] at=[0,0,50]"))
        upper = valid(solid("о = box size=[60,40,100]\nо = cut_plane [о] at=[0,0,50] keep=обратная"))
        self.assertAlmostEqual(lower.volume(), 60 * 40 * 50, delta=1e-5)
        self.assertAlmostEqual(upper.volume(), 60 * 40 * 50, delta=1e-5)
        self.assertAlmostEqual(lower.bounding_box()[5], 50.0, delta=1e-6)
        self.assertAlmostEqual(upper.bounding_box()[2], 50.0, delta=1e-6)


class IngotTriPrismCavityTest(unittest.TestCase):
    def test_ingot_blind_cavities_and_shifted_taper(self):
        base = "о = ingot length=100 width=50 height=30 taper=8"
        full = valid(solid(base))
        for side in ("верх", "низ"):
            with self.subTest(op="ingot", side=side):
                hollow = obj(base + f" wall=3 cavity={side} cavity_depth=20")
                valid(hollow.manifold)
                self.assertLess(hollow.manifold.volume(), full.volume())
                np.testing.assert_allclose(size(hollow.manifold), size(full), atol=1e-6)
                self.assertEqual(hollow.meta["cavity"], side)
                self.assertEqual(hollow.meta["cavity_depth"], 20.0)
                if side == "верх":
                    self.assertTrue(inside(hollow.manifold, (0, 0, 5)))
                    self.assertFalse(inside(hollow.manifold, (0, 0, 15)))
                    self.assertFalse(inside(hollow.manifold, (0, 0, 28)))
                else:
                    self.assertFalse(inside(hollow.manifold, (0, 0, 15)))
                    self.assertTrue(inside(hollow.manifold, (0, 0, 25)))
        custom = ("о = ingot length=100 width=50 height=30 top_size=[70,35] "
                  "top_offset=[6,3] round=2 smooth=1")
        custom_full = valid(solid(custom))
        hollow = valid(solid(custom + " wall=2.5 cavity=верх cavity_depth=20"))
        np.testing.assert_allclose(size(hollow), size(custom_full), atol=1e-5)
        self.assertFalse(inside(hollow, (5, 2.5, 25)))
        self.assertTrue(inside(hollow, (0, 0, 5)))

    def test_tri_prism_blind_cavities_and_rounded_contour(self):
        base = "о = tri_prism a=100 b=90 c=80 height=60"
        full = valid(solid(base))
        for side in ("верх", "низ"):
            with self.subTest(op="tri_prism", side=side):
                hollow = obj(base + f" wall=3 cavity={side} cavity_depth=40")
                valid(hollow.manifold)
                self.assertLess(hollow.manifold.volume(), full.volume())
                np.testing.assert_allclose(size(hollow.manifold), size(full), atol=1e-6)
                self.assertEqual(hollow.meta["cavity"], side)
                if side == "верх":
                    self.assertTrue(inside(hollow.manifold, (0, 0, 10)))
                    self.assertFalse(inside(hollow.manifold, (0, 0, 30)))
                    self.assertFalse(inside(hollow.manifold, (0, 0, 55)))
                else:
                    self.assertFalse(inside(hollow.manifold, (0, 0, 30)))
                    self.assertTrue(inside(hollow.manifold, (0, 0, 50)))
        rounded = valid(solid(base + " round=4 wall=3 cavity=верх cavity_depth=40"))
        self.assertFalse(inside(rounded, (0, 0, 50)))
        self.assertTrue(inside(rounded, (0, 0, 10)))

    def test_cavity_parameters_validate_wall(self):
        for command in ("о = ingot height=30 cavity_depth=10",
                        "о = tri_prism a=100 height=60 cavity_depth=20"):
            with self.subTest(command=command):
                result = build(command, analyze_model=False)
                self.assertFalse(result.ok)
                self.assertIn("wall>0", result.error["message"])
        for command in ("о = ingot height=30 wall=30",
                        "о = tri_prism a=100 height=60 wall=60"):
            with self.subTest(command=command):
                self.assertFalse(build(command, analyze_model=False).ok)


class BarrelTilesExpansionTest(unittest.TestCase):
    def test_barrel_profile_dashes_and_independent_rims(self):
        base = valid(solid("о = barrel radius=60 height=120 end_radius=46 segments=48 rings=24"))
        v = vertices(base)
        self.assertAlmostEqual(size(base)[2], 120.0, delta=1e-6)
        end = np.linalg.norm(v[np.isclose(v[:, 2], 0.0)][:, :2], axis=1).max()
        mid = np.linalg.norm(v[np.isclose(v[:, 2], 60.0)][:, :2], axis=1).max()
        self.assertGreater(mid, end + 5.0)
        volumes = {}
        for profile in ("круглые", "прямоугольные", "треугольные", "трапециевидные"):
            m = valid(solid("о = barrel radius=60 height=120 segments=48 rings=24 relief=борозды "
                            f"shape={profile} groove_count=12 groove_depth=2"))
            volumes[profile] = m.volume()
            self.assertLess(m.volume(), base.volume())
        self.assertEqual(len({round(v, 3) for v in volumes.values()}), 4)
        bumps = valid(solid("о = barrel radius=60 height=120 relief=холмики groove_depth=2"))
        dashed = valid(solid("о = barrel radius=60 height=120 relief=холмики groove_depth=2 "
                             "dashed=да dash_count=5 dash_duty=.45"))
        self.assertGreater(bumps.volume(), base.volume())
        self.assertNotAlmostEqual(dashed.volume(), bumps.volume(), places=3)
        top = valid(solid("о = barrel radius=60 height=120 rim_top=5 rim_bottom=0"))
        bottom = valid(solid("о = barrel radius=60 height=120 rim_top=0 rim_bottom=5"))
        # Симметрия сохраняет объём, поэтому проверяем именно независимые
        # радиусы верхнего и нижнего плоского торца.
        def end_radii(m):
            v = vertices(m)
            lo = np.linalg.norm(v[np.isclose(v[:, 2], 0.0)][:, :2], axis=1).max()
            hi = np.linalg.norm(v[np.isclose(v[:, 2], 120.0)][:, :2], axis=1).max()
            return lo, hi
        top_lo, top_hi = end_radii(top)
        bottom_lo, bottom_hi = end_radii(bottom)
        self.assertGreater(top_hi, top_lo + 4.0)
        self.assertGreater(bottom_lo, bottom_hi + 4.0)
        self.assertAlmostEqual(top_lo, bottom_hi, delta=1e-5)
        self.assertAlmostEqual(top_hi, bottom_lo, delta=1e-5)

    def test_barrel_continuous_groove_has_constant_depth_and_dash_breaks(self):
        prefix = ("о = barrel radius=60 height=120 end_radius=46 segments=48 rings=64 "
                  "relief=борозды shape=прямоугольные groove_count=4 groove_depth=2 ")
        continuous = valid(solid(prefix + "dashed=нет"))
        dashed = valid(solid(prefix + "dashed=да dash_count=4 dash_duty=.5"))
        plain = valid(solid("о = barrel radius=60 height=120 end_radius=46 segments=48 rings=64"))

        def groove_depth_at(m, z):
            hit = m.ray_cast([200, 0, z], [-200, 0, z])[0]
            base_hit = plain.ray_cast([200, 0, z], [-200, 0, z])[0]
            return base_hit.position[0] - hit.position[0]

        # В сплошном режиме каждая внутренняя высота имеет одну и ту же
        # канавку; это проверка профиля, а не только объёма или числа граней.
        for z in (20, 40, 60, 80, 100):
            self.assertAlmostEqual(groove_depth_at(continuous, z), 2.0, delta=1e-4)
        self.assertAlmostEqual(groove_depth_at(dashed, 20), 0.0, delta=1e-4)
        self.assertAlmostEqual(groove_depth_at(dashed, 40), 2.0, delta=1e-4)

    def test_four_roof_tile_variants(self):
        tiles = [_scale_tile(9, 14, 1.1, "черепица", 12, variant)
                 for variant in ("плоская", "волна", "ромб", "испанская")]
        for tile in tiles:
            valid(tile)
        self.assertEqual(len({round(tile.volume(), 4) for tile in tiles}), 4)
        for variant in ("плоская", "волна", "ромб", "испанская"):
            with self.subTest(variant=variant):
                result = obj("о = sphere radius=30\n"
                             f"scales о kind=черепица tile={variant} rows=6 per_row=12 length=6")
                valid(result.manifold)
                self.assertEqual(result.meta["tile_variant"], variant)
                self.assertEqual(result.meta["tiles"], 72)

    def test_expanded_half_preserves_the_other_half(self):
        cases = (("sphere", "radius=30 segments=32"),
                 ("ellipsoid", "x=35 y=25 z=30 segments=32"),
                 ("capsule", "radius=12 height=70 segments=32"))
        for op, dims in cases:
            with self.subTest(op=op):
                base = valid(solid(f"о = {op} {dims}"))
                for side in ("верх", "низ"):
                    expanded = valid(solid(f"о = {op} {dims} expand=.5 expand_side={side}"))
                    self.assertGreater(expanded.volume(), base.volume())
                    vb, ve = vertices(base), vertices(expanded)
                    self.assertEqual(vb.shape, ve.shape)
                    mid = (base.bounding_box()[2] + base.bounding_box()[5]) / 2.0
                    # Manifold волен перенумеровать вершины: сравниваем
                    # отсортированные геометрические множества, не индексы.
                    def unchanged_half(v):
                        mask = v[:, 2] < mid - 1e-5 if side == "верх" else v[:, 2] > mid + 1e-5
                        selected = v[mask]
                        order = np.lexsort((selected[:, 2], selected[:, 1], selected[:, 0]))
                        return selected[order]
                    np.testing.assert_allclose(unchanged_half(ve), unchanged_half(vb), atol=2e-5)
        sharp = vertices(solid("о = sphere radius=30 segments=32 expand=.5 expand_smooth=0"))
        smooth = vertices(solid("о = sphere radius=30 segments=32 expand=.5 expand_smooth=1"))
        self.assertGreater(float(np.max(np.abs(sharp - smooth))), 1e-3)


class HyperbolicTessellationTest(unittest.TestCase):
    def test_hourglass_hole_waist_and_wall(self):
        branch = valid(solid("о = hyperboloid radius=70 height=100 center_radius=24 segments=32 rings=12"))
        hourglass = valid(solid("о = hyperboloid radius=70 height=160 center_radius=24 "
                                "hourglass=да segments=32 rings=12"))
        solid_double = valid(solid("о = hyperboloid radius=70 height=160 center_radius=24 "
                                   "hourglass=да center_hole=0 segments=32 rings=12"))
        wall = valid(solid("о = hyperboloid radius=70 height=160 center_radius=24 "
                           "hourglass=да wall=3 segments=32 rings=12"))
        self.assertEqual(branch.genus(), 0)
        self.assertEqual(hourglass.genus(), 1)
        self.assertEqual(solid_double.genus(), 0)
        self.assertEqual(wall.genus(), 1)
        self.assertGreater(hourglass.volume(), 0.0)
        for radius in (20.0, 30.0):
            m = valid(solid(f"о = hyperboloid radius=70 height=160 center_radius={radius} "
                            "hourglass=да center_hole=0 segments=48 rings=12"))
            hit = m.ray_cast([0, 0, 80], [100, 0, 80])[0]
            self.assertAlmostEqual(float(hit.position[0]), radius, delta=0.05)

    def test_saddle_nu_nv_change_actual_tessellation(self):
        low = obj("о = saddle length=160 width=120 rise=40 thickness=4 nu=20 nv=12")
        high = obj("о = saddle length=160 width=120 rise=40 thickness=4 nu=40 nv=24")
        valid(low.manifold)
        valid(high.manifold)
        self.assertEqual((low.meta["nu"], low.meta["nv"]), (20, 12))
        self.assertEqual((high.meta["nu"], high.meta["nv"]), (40, 24))
        self.assertGreater(high.manifold.num_tri(), low.manifold.num_tri() * 3.5)
        np.testing.assert_allclose(size(low.manifold), size(high.manifold), atol=1e-5)


class SakuraFlowerLayoutTest(unittest.TestCase):
    def test_sakura_is_a_real_notched_leaf_not_an_alias(self):
        oval = valid(solid("о = leaf kind=овал length=42 width=30 thickness=2 curl=0 segments=48"))
        sakura = valid(solid("о = leaf kind=сакура length=42 width=30 thickness=2 curl=0 segments=48"))
        self.assertLess(sakura.volume(), oval.volume())
        self.assertNotEqual(sakura.num_tri(), oval.num_tri())
        np.testing.assert_allclose(size(sakura), size(oval), atol=1e-5)
        repeated = valid(solid("о = leaf kind=сакура length=42 width=30 thickness=2 curl=0 segments=48"))
        self.assertAlmostEqual(sakura.volume(), repeated.volume(), delta=1e-6)
        np.testing.assert_allclose(vertices(sakura), vertices(repeated), atol=0)

    def test_flower_golden_layout_and_openness_change_real_copies(self):
        def arranged(openness, layout="золотой"):
            result = ok(
                "л = leaf kind=сакура length=42 width=30 curl=.12\n"
                f"б = flower [л] mode=бутон count=5 rows=3 layout={layout} openness={openness}")
            visible = [o for o in result.scene.objects.values() if o.visible]
            self.assertEqual(len(visible), 15)
            for item in visible:
                valid(item.manifold)
            return result, visible

        closed, closed_parts = arranged(0)
        opened, opened_parts = arranged(1)
        angles = [o.meta["flower"]["angle_deg"] for o in opened_parts]
        self.assertAlmostEqual((angles[1] - angles[0]) % 360, 137.50776405003785, places=7)
        self.assertAlmostEqual((angles[5] - angles[4]) % 360, 137.50776405003785, places=7)
        self.assertFalse(np.allclose(vertices(closed_parts[0].manifold),
                                     vertices(opened_parts[0].manifold)))
        self.assertAlmostEqual(closed_parts[0].manifold.volume(),
                               opened_parts[0].manifold.volume(), delta=1e-4)

        _, ring_parts = arranged(1, layout="кольца")
        ring_angles = [o.meta["flower"]["angle_deg"] for o in ring_parts[:5]]
        self.assertAlmostEqual((ring_angles[1] - ring_angles[0]) % 360, 72.0, places=7)


class ResourcePreflightTest(unittest.TestCase):
    heavy = "N = 2048\nо = sphere segments=N"
    morph = "N = 4\nо = sphere segments=N"

    def test_estimator_understands_assignments_overrides_and_frames(self):
        self.assertLess(estimate_script_tris(self.morph), RESOURCE_TRI_LIMIT)
        self.assertGreater(estimate_script_tris(self.morph, overrides={"N": 2048}), RESOURCE_TRI_LIMIT)
        script = "а = box\nб = sphere detail=12"
        self.assertLess(estimate_script_tris(script, upto=1), RESOURCE_TRI_LIMIT)
        self.assertGreater(estimate_script_tris(script, upto=2), RESOURCE_TRI_LIMIT)
        self.assertEqual(estimate_script_tris(script, upto=0), 0)

    def test_all_four_entry_points_pause_before_run_build(self):
        state = AppState()
        calls = (
            lambda: state.build(self.heavy),
            lambda: state.preview(self.heavy),
            lambda: state.frame(self.heavy, 2),
            lambda: state.morph(self.morph, "N", 2048),
        )
        with patch("forma.webui.run_build") as mocked:
            for call in calls:
                with self.subTest(call=call):
                    response = call()
                    self.assertTrue(response["resource_warning"])
                    self.assertTrue(response["paused"])
                    self.assertGreater(response["estimated_tris"], RESOURCE_TRI_LIMIT)
                    mocked.assert_not_called()
        self.assertIsNone(state.last_build)
        self.assertEqual(state.frame_cache, {})

    def test_allow_heavy_flag_reaches_light_operations(self):
        state = AppState()
        with tempfile.TemporaryDirectory() as tmp:
            state.preview_dir = Path(tmp)
            with patch("forma.webui.resource_warning", side_effect=AssertionError("не должен вызываться")):
                self.assertTrue(state.build("о = box size=[10,10,10]", allow_heavy=True)["ok"])
                self.assertTrue(state.preview("о = box size=[10,10,10]", allow_heavy=True)["ok"])
                self.assertTrue(state.frame("о = box size=[10,10,10]", 1, allow_heavy=True)["ok"])
                self.assertTrue(state.morph("N = 4\nо = box size=[N,N,N]", "N", 5,
                                            allow_heavy=True)["ok"])

    def test_javascript_has_shared_cancelable_frame_and_morph_preflight(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("async function apiWithResourcePause", app)
        self.assertGreaterEqual(app.count("apiWithResourcePause('/api/frame'"), 2)
        self.assertGreaterEqual(app.count("apiWithResourcePause('/api/morph'"), 2)
        self.assertIn("error.resourceCancelled", app)
        self.assertIn("allow_heavy: state.heavyApproved.has(approvalKey)", app)


if __name__ == "__main__":
    unittest.main()
