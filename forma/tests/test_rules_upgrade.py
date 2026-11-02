"""Точные пересечения, дискретный свободный ход и автоматические предупреждения.

Тесты намеренно проверяют не только ``NoError``: касание, реальный объём,
разрешённые пары, исходную и промежуточную позы, точный конечный угол и
сохранение старого отчёта ``interference``.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import manifold3d as mf

from forma.collide import root, scan_pairs
from forma.run import build


CLEAN = """
bladeA = box size=[110,14,3] center=да at=[-55,4,1.5]
gripA  = box size=[60,12,3] center=да at=[40,20,1.5]
armA = union [bladeA] [gripA]
bladeB = box size=[110,14,3] center=да at=[-55,-4,-1.5]
gripB  = box size=[60,12,3] center=да at=[40,-20,-1.5]
armB = union [bladeB] [gripB]
"""

BROKEN = CLEAN.replace("at=[-55,-4,-1.5]", "at=[-55,-4,1.5]").replace(
    "at=[40,-20,-1.5]", "at=[40,-20,1.5]")


def _build(script: str, analyze: bool = True):
    result = build(script, analyze_model=analyze)
    if not result.ok:
        raise AssertionError(f"build failed: {result.error}\n{result.log}")
    return result


def _checks(result) -> dict[str, dict]:
    return {c["rule"]: c for c in (result.analysis or {}).get("checks", [])}


def _check(result, target: str, rule: str) -> dict:
    return next(c for c in result.analysis["checks"]
                if c["target"] == target and c["rule"] == rule)


class CollisionRuleTest(unittest.TestCase):
    def test_clean_assembly_has_no_collision(self):
        r = _build(CLEAN + "\ncheck armA collision\n")
        check = _checks(r)["collision"]
        self.assertTrue(check["ok"], check["text"])
        self.assertEqual(check["actual"], 0.0)

    def test_overlapping_parts_are_caught_with_exact_volume(self):
        r = _build(BROKEN + "\ncheck armA collision\n")
        check = _checks(r)["collision"]
        self.assertFalse(check["ok"])
        self.assertIn("armB", check["text"])
        self.assertEqual(check["actual"], 0.0)
        self.assertAlmostEqual(check["pairs"][0]["volume_mm3"], 1980.0, delta=1.0)

    def test_tolerance_can_forgive_small_overlap(self):
        r = _build(BROKEN + "\ncheck armA collision 5000\n")
        self.assertTrue(_checks(r)["collision"]["ok"])

    def test_allow_pair_silences_collision(self):
        r = _build(BROKEN + '\ncheck armA collision allow="armA:armB"\n')
        self.assertTrue(_checks(r)["collision"]["ok"])

    def test_exact_volume_matches_kernel(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
check a collision
""")
        self.assertEqual(_checks(r)["collision"]["actual"], 0.0)
        self.assertAlmostEqual(_checks(r)["collision"]["pairs"][0]["volume_mm3"], 500.0, delta=1.0)

    def test_all_collision_pairs_are_retained_without_fake_scalar(self):
        r = _build("""
a = box size=[10,10,10] center=да
left = box size=[10,10,10] center=да at=[-5,0,0]
right = box size=[10,10,10] center=да at=[5,0,0]
check a collision
""")
        check = _checks(r)["collision"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["actual"], 0.0)
        self.assertEqual(len(check["pairs"]), 2)
        self.assertIn("left", check["text"])
        self.assertIn("right", check["text"])

    def test_aabb_overlap_alone_is_not_a_collision(self):
        r = _build("""
a = sphere radius=5 at=[0,0,0]
b = sphere radius=5 at=[7,7,7]
check a collision
""")
        self.assertTrue(_checks(r)["collision"]["ok"])
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_containment_uses_the_inner_volume(self):
        r = _build("""
outer = box size=[20,20,20] center=да
inner = box size=[10,10,10] center=да
check outer collision
""")
        self.assertEqual(_checks(r)["collision"]["actual"], 0.0)
        self.assertAlmostEqual(_checks(r)["collision"]["pairs"][0]["volume_mm3"], 1000.0, delta=1.0)

    def test_target_filter_is_applied_before_limit(self):
        # Пять больших чужих пар не должны вытеснить маленькую пару target
        # из топ-5: старый порядок «limit → filter» давал ложный PASS.
        lines = [
            "target = box size=[10,10,10] center=да at=[0,0,0]",
            "near = box size=[10,10,10] center=да at=[5,0,0]",
        ]
        for i in range(6):
            x = 100 + i * 50
            lines.append(f"bigA{i} = box size=[20,20,20] center=да at=[{x},0,0]")
            lines.append(f"bigB{i} = box size=[20,20,20] center=да at=[{x + 10},0,0]")
        r = _build("\n".join(lines) + "\ncheck target collision\n")
        check = _check(r, "target", "collision")
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["actual"], 0.0)
        self.assertAlmostEqual(check["pairs"][0]["volume_mm3"], 500.0, delta=1.0)
        self.assertTrue(all("target" in (p["a"], p["b"]) for p in check["pairs"]))

    def test_touching_parts_have_zero_volume(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[10,0,0]
check a collision
""")
        self.assertTrue(_checks(r)["collision"]["ok"])
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_malformed_allow_is_reported(self):
        r = _build("""
a = box size=[10,10,10] center=да
b = box size=[10,10,10] center=да at=[5,0,0]
check a collision allow="not-a-pair"
""")
        check = _checks(r)["collision"]
        self.assertFalse(check["ok"])
        self.assertIn("allow", check["text"])

    def test_assembly_parts_can_be_skipped_or_forced(self):
        a = SimpleNamespace(name="корпус.дно", manifold=mf.Manifold.cube([40, 40, 4], True))
        b = SimpleNamespace(name="корпус.стенка",
                            manifold=mf.Manifold.cube([40, 4, 30], True).translate([0, 18, 15]))
        self.assertEqual(root("корпус.дно"), "корпус")
        pairs, stats = scan_pairs([a, b], tolerance=0.01)
        self.assertEqual(pairs, [])
        self.assertEqual(stats["skipped_parts"], 1)
        forced, _ = scan_pairs([a, b], tolerance=0.01, skip_parts=False)
        self.assertEqual(len(forced), 1)

    def test_generator_input_keeps_object_count(self):
        a = SimpleNamespace(name="a", manifold=mf.Manifold.cube([2, 2, 2], True))
        b = SimpleNamespace(name="b", manifold=mf.Manifold.cube([2, 2, 2], True).translate([3, 0, 0]))
        _, stats = scan_pairs((item for item in [a, b]))
        self.assertEqual(stats["objects"], 2)


class MotionRuleTest(unittest.TestCase):
    def test_free_motion_to_ninety_degrees(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=90 step=10\n")
        check = _checks(r)["motion"]
        self.assertTrue(check["ok"], check["text"])
        self.assertEqual(check["actual"], 90.0)
        self.assertEqual(check["positions_checked"], 10)  # исходная + 9 поз
        self.assertIsNone(check["blocked_at"])

    def test_initial_overlap_is_blocked_at_zero(self):
        r = _build(BROKEN + "\ncheck armB ход axis=z до=90 step=5\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["blocked_at"], 0.0)
        self.assertEqual(check["blocked_by"], ["armA"])
        self.assertGreater(check["blocked_mm3"][0], 1000.0)
        self.assertEqual(check["blocked_pair"]["b"], "armA")

    def test_all_obstacles_in_blocking_pose_are_reported(self):
        r = _build("""
moving = box size=[10,10,10] center=да
left = box size=[10,10,10] center=да at=[-5,0,0]
right = box size=[10,10,10] center=да at=[5,0,0]
check moving ход axis=z до=10 step=5 against=[left,right]
""")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["blocked_at"], 0.0)
        self.assertCountEqual(check["blocked_by"], ["left", "right"])
        self.assertEqual(len(check["blocked_mm3"]), 2)
        self.assertEqual(len(check["blocked_pairs"]), 2)
        self.assertIn("left", check["text"])
        self.assertIn("right", check["text"])

    def test_intermediate_collision_reports_sampled_angle(self):
        r = _build("""
moving = box size=[10,2,2] center=да at=[5,0,1]
obstacle = box size=[2,2,2] center=да at=[3,2.5,1]
check moving ход axis=z до=30 step=5 against=[obstacle]
""")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"], check["text"])
        self.assertEqual(check["blocked_at"], 15.0)
        self.assertEqual(check["blocked_by"], ["obstacle"])
        self.assertGreater(check["blocked_mm3"][0], 0.5)

    def test_non_divisible_and_short_ranges_include_exact_endpoint(self):
        r = _build("""
moving = box size=[10,2,2] center=да at=[5,0,1]
obstacle = box size=[2,2,2] center=да at=[30,30,1]
check moving ход axis=z до=18 step=5 against=[obstacle]
check moving ход axis=z до=2 step=5 against=[obstacle]
""")
        checks = [c for c in r.analysis["checks"] if c["rule"] == "motion"]
        self.assertEqual([c["actual"] for c in checks], [18.0, 2.0])
        self.assertEqual([c["positions_checked"] for c in checks], [5, 2])

    def test_negative_angle_is_a_real_direction(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=-90 step=30\n")
        check = _checks(r)["motion"]
        self.assertTrue(check["ok"], check["text"])
        self.assertEqual(check["actual"], -90.0)

    def test_arbitrary_axis_is_axis_angle_not_euler_xyz(self):
        # Поворот [5,0,0] вокруг нормированной [1,1,1] на 120° даёт [0,5,0].
        # Euler XYZ с такими же тремя углами в эту точку не попадает.
        r = _build("""
moving = box size=[2,4,6] center=да at=[5,0,0]
obstacle = box size=[1,1,1] center=да at=[0,5,0]
check moving ход axis=[1,1,1] до=120 step=60 against=[obstacle]
""")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"], check["text"])
        self.assertEqual(check["blocked_at"], 120.0)
        self.assertEqual(check["blocked_by"], ["obstacle"])
        self.assertEqual(check["blocked_mm3"], [1.0])

    def test_bad_axis_is_reported_in_the_check(self):
        r = _build(CLEAN + "\ncheck armB ход axis=w до=90\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertIn("Ось", check["text"])

    def test_too_fine_step_is_refused(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=360 step=1\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertIn("72", check["text"])

    def test_zero_step_is_refused(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=90 step=0\n")
        self.assertFalse(_checks(r)["motion"]["ok"])


class AutomaticWarningTest(unittest.TestCase):
    def test_overlap_is_warned_without_any_command(self):
        r = _build(BROKEN)
        text = " ".join(r.analysis["warnings"])
        self.assertIn("Детали пересекаются", text)
        self.assertIn("armA", text)
        self.assertIn("armB", text)

    def test_clean_assembly_stays_quiet_about_overlap(self):
        r = _build(CLEAN)
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_two_overlapping_objects_are_warned_even_if_one_connected_part(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
""")
        self.assertIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_union_of_overlapping_bodies_is_not_a_defect(self):
        r = _build("""
a = box size=[10,10,10] center=да
b = box size=[10,10,10] center=да at=[5,0,0]
c = union [a] [b]
""")
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_interference_allow_is_used_by_automatic_warning(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
interference allow="a:b"
""")
        self.assertEqual(r.scene.collision_allow, ["a:b"])
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))

    def test_absolute_threshold_suppresses_tiny_overlap(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[9.999,0,0]
""")
        self.assertNotIn("Детали пересекаются", " ".join(r.analysis["warnings"]))


class InterferenceRegressionTest(unittest.TestCase):
    def test_report_fields_and_volume(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
interference tolerance=0.01
""")
        report = r.scene.interferences[-1]
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["objects"], 2)
        self.assertEqual(report["candidates"], 1)
        self.assertAlmostEqual(report["pairs"][0]["volume_mm3"], 500.0, delta=1.0)
        self.assertEqual(report["truncated"], 0)

    def test_allow_and_parts_are_counted(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
interference allow="a:b"
""")
        report = r.scene.interferences[-1]
        self.assertEqual(report["count"], 0)
        self.assertEqual(report["allowed"], 1)

    def test_malformed_interference_allow_remains_an_error(self):
        r = build("""
a = box size=[10,10,10] center=да
b = box size=[10,10,10] center=да at=[5,0,0]
interference allow="bad"
""")
        self.assertFalse(r.ok)
        self.assertIn("allow", r.error["message"])


if __name__ == "__main__":
    unittest.main()
