"""Проверки, которых не хватало: пересечения деталей, свободный ход, авто-отчёт.

Мотив — сборка из подвижных деталей (ножницы, дверца, петля). В покое такая
сборка может быть «чистой»: замкнутой, без тонких стенок и без нависаний, —
и при этом не двигаться, потому что детали врезались друг в друга. Раньше
это выяснялось только командой `interference`, то есть по просьбе. Теперь:

* `check деталь пересечения` — утверждение в сценарии;
* `check деталь ход axis=z до=90` — крутим и ищем первое столкновение;
* автоматическое предупреждение в `analyze` — без всякой просьбы.

Тесты держат три вещи: правила ловят реальный дефект, не срабатывают на
чистой сборке и не ломают прежний отчёт `interference`.
"""
from __future__ import annotations

import unittest

from forma.run import build

#: два плеча ножниц в разных слоях по Z: в покое не пересекаются и могут
#: поворачиваться друг относительно друга — правильная сборка
CLEAN = """
bladeA = box size=[110,14,3] center=да at=[-55,4,1.5]
gripA  = box size=[60,12,3] center=да at=[40,20,1.5]
armA = union [bladeA] [gripA]
bladeB = box size=[110,14,3] center=да at=[-55,-4,-1.5]
gripB  = box size=[60,12,3] center=да at=[40,-20,-1.5]
armB = union [bladeB] [gripB]
"""

#: те же плечи в одном слое: 1980 мм³ общего объёма — двигаться не могут
BROKEN = CLEAN.replace("at=[-55,-4,-1.5]", "at=[-55,-4,1.5]").replace(
    "at=[40,-20,-1.5]", "at=[40,-20,1.5]")


def _build(script: str, analyze: bool = True):
    result = build(script, analyze_model=analyze)
    if not result.ok:
        raise AssertionError(f"build failed: {result.error}\n{result.log}")
    return result


def _checks(result) -> dict[str, dict]:
    return {c["rule"]: c for c in (result.analysis or {}).get("checks", [])}


class CollisionRuleTest(unittest.TestCase):
    def test_clean_assembly_has_no_collision(self):
        r = _build(CLEAN + "\ncheck armA collision\n")
        check = _checks(r)["collision"]
        self.assertTrue(check["ok"], check["text"])
        self.assertIn("пересечения: нет", check["text"])

    def test_overlapping_parts_are_caught(self):
        r = _build(BROKEN + "\ncheck armA collision\n")
        check = _checks(r)["collision"]
        self.assertFalse(check["ok"])
        self.assertIn("armB", check["text"])
        self.assertGreater(check["actual"], 1000.0)   # порядка 1980 мм³

    def test_tolerance_can_forgive_small_overlap(self):
        r = _build(BROKEN + "\ncheck armA collision 5000\n")
        self.assertTrue(_checks(r)["collision"]["ok"])

    def test_allow_pair_silences_collision(self):
        r = _build(BROKEN + '\ncheck armA collision allow="armA:armB"\n')
        self.assertTrue(_checks(r)["collision"]["ok"])

    def test_exact_volume_matches_kernel(self):
        # два куба 10×10×10, сдвинутые на 5 мм: общий объём 5·10·10 = 500 мм³
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
check a collision
""")
        check = _checks(r)["collision"]
        self.assertFalse(check["ok"])
        self.assertAlmostEqual(check["actual"], 500.0, delta=1.0)


class MotionRuleTest(unittest.TestCase):
    def test_free_motion_to_ninety_degrees(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=90 step=10\n")
        check = _checks(r)["motion"]
        self.assertTrue(check["ok"], check["text"])
        self.assertEqual(check["actual"], 90.0)

    def test_blocked_motion_reports_angle_and_part(self):
        r = _build(BROKEN + "\ncheck armB ход axis=z до=90 step=5\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["blocked_at"], 5.0)
        self.assertIn("armA", check["blocked_by"])
        self.assertGreater(check["blocked_mm3"], 1.0)

    def test_bad_axis_is_reported_in_the_check(self):
        r = _build(CLEAN + "\ncheck armB ход axis=w до=90\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertIn("Ось хода", check["text"])

    def test_too_fine_step_is_refused(self):
        r = _build(CLEAN + "\ncheck armB ход axis=z до=360 step=1\n")
        check = _checks(r)["motion"]
        self.assertFalse(check["ok"])
        self.assertIn("72", check["text"])


class AutomaticWarningTest(unittest.TestCase):
    def test_overlap_is_warned_without_any_command(self):
        r = _build(BROKEN)
        text = " ".join(r.analysis["warnings"])
        self.assertIn("Детали пересекаются", text)
        self.assertIn("armA", text)
        self.assertIn("armB", text)

    def test_clean_assembly_stays_quiet_about_overlap(self):
        r = _build(CLEAN)
        text = " ".join(r.analysis["warnings"])
        self.assertNotIn("Детали пересекаются", text)

    def test_two_overlapping_objects_are_warned_even_if_merged_into_one_part(self):
        # две слипшиеся детали дают parts=1 (тело одно), но объекты-то разные:
        # пропускать такой случай нельзя — именно так выглядит «не двигается»
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

    def test_parts_of_one_assembly_are_skipped(self):
        # Детали составной сборки называются `корпус.дно`, `корпус.стенка` и по
        # построению касаются друг друга — это не дефект. Проверяем сам отбор,
        # не завися от того, какая команда создала имена с точкой.
        from types import SimpleNamespace

        import manifold3d as mf

        from forma.collide import root, scan_pairs
        a = SimpleNamespace(name="корпус.дно", manifold=mf.Manifold.cube([40, 40, 4], True))
        b = SimpleNamespace(name="корпус.стенка", manifold=mf.Manifold.cube([40, 4, 30], True)
                            .translate([0, 18, 15]))
        self.assertEqual(root("корпус.дно"), "корпус")
        pairs, stats = scan_pairs([a, b], tolerance=0.01)
        self.assertEqual(pairs, [])
        self.assertEqual(stats["skipped_parts"], 1)
        pairs_forced, _ = scan_pairs([a, b], tolerance=0.01, skip_parts=False)
        self.assertEqual(len(pairs_forced), 1)


class InterferenceRegressionTest(unittest.TestCase):
    """Старый отчёт `interference` должен считать то же, что и раньше."""

    def test_report_fields_and_volume(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
interference tolerance=0.01
""")
        report = r.scene.interferences[-1]
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["objects"], 2)
        self.assertAlmostEqual(report["pairs"][0]["volume_mm3"], 500.0, delta=1.0)

    def test_allow_and_parts_are_counted(self):
        r = _build("""
a = box size=[10,10,10] center=да at=[0,0,0]
b = box size=[10,10,10] center=да at=[5,0,0]
interference allow="a:b"
""")
        report = r.scene.interferences[-1]
        self.assertEqual(report["count"], 0)
        self.assertEqual(report["allowed"], 1)


if __name__ == "__main__":
    unittest.main()
