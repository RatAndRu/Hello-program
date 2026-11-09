"""0.80: примитивы — параметры и собранные сетки.

Проверяется то, что видит пользователь: каждый примитив собирается из своего
примера и **пишется** в STL и GLB. До 0.80 пять примитивов строили картинку,
но экспорт останавливался на «схлопнувшихся гранях» и non-manifold рёбрах:
`bracket`, `lightning`, `скоба`, `cloud`, `drive` (внутри — саморез).

Вторая половина — параметры: у примитивов есть типы, у имён с понятным
окончанием (`*_height`, `*_count`, `*_color`) тип выводится из окончания, а
спорные имена (`size`, `points`, `sections`, `factor`, `start`, `top`) остаются
свободным вводом: угадывание здесь дороже отсутствия ползунка.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forma.geometry import (_clean_manifold_arrays, export_glb, export_stl,
                            manifold_mesh, rebuild_manifold, snap_manifold,
                            solid_parts)
from forma.ops import OPS, lookup
from forma.param_spec import spec_for
from forma.param_types import generic_spec
from forma.run import build
from forma.topology import analyze_topology

ROOT = Path(__file__).resolve().parent.parent
DISPUTED = {"size", "points", "sections", "factor", "start", "top"}

# Кэш: 123 примера строятся один раз на весь модуль.
_CACHE: dict[str, dict] = {}


def primitive_names() -> list[str]:
    return sorted(spec.name for spec in OPS.values() if spec.category == "Примитивы")


def measured(name: str) -> dict:
    """Собирает пример примитива один раз: тела, метрики, размеры экспорта."""
    if name in _CACHE:
        return _CACHE[name]
    spec = lookup(name)
    result = build(spec.example, analyze_model=False)
    entry: dict = {"ok": result.ok, "error": result.error}
    if result.ok:
        solids = result.scene.visible_solids()
        entry["solids"] = []
        for solid in solids:
            verts, faces = _clean_manifold_arrays(solid.manifold)
            report = analyze_topology(verts, faces, include_quality=False)
            entry["solids"].append({
                "name": solid.name,
                "parts": int(solid_parts(solid.manifold)),
                "triangles": len(faces),
                "gate": bool(report["ok"]),
                "degenerate": int(report["degenerate_index"]),
                "non_manifold": int(report["non_manifold_edges"]),
                "boundary": int(report["boundary_edges"]),
                "duplicate": int(report["duplicate_faces"]),
                "volume": float(solid.manifold.volume()),
            })
        entry["export_error"] = ""
        try:
            entry["stl"] = len(export_stl(solids))
            entry["glb"] = len(export_glb(solids))
        except Exception as exc:  # экспорт — часть результата, а не отдельная опция
            entry["stl"] = entry["glb"] = 0
            entry["export_error"] = str(exc)
    _CACHE[name] = entry
    return entry


class PrimitiveMeshesTest(unittest.TestCase):
    def test_every_primitive_builds(self):
        for name in primitive_names():
            entry = measured(name)
            self.assertTrue(entry["ok"], f"{name}: {(entry['error'] or {}).get('message')}")
            self.assertTrue(entry["solids"], f"{name}: нет тел")

    def test_every_primitive_exports(self):
        for name in primitive_names():
            entry = measured(name)
            self.assertEqual(entry.get("export_error"), "", f"{name}: {entry.get('export_error')}")
            self.assertGreater(entry.get("stl", 0), 0, f"{name}: пустой STL")
            self.assertGreater(entry.get("glb", 0), 0, f"{name}: пустой GLB")

    def test_export_mesh_is_clean(self):
        for name in primitive_names():
            for solid in measured(name).get("solids", []):
                where = f"{name} / {solid['name']}"
                self.assertTrue(solid["gate"], f"{where}: сетка не проходит контроль")
                self.assertEqual(solid["degenerate"], 0, f"{where}: схлопнувшиеся грани")
                self.assertEqual(solid["non_manifold"], 0, f"{where}: non-manifold рёбра")
                self.assertEqual(solid["boundary"], 0, f"{where}: граничные рёбра")
                self.assertEqual(solid["duplicate"], 0, f"{where}: дубли граней")
                self.assertGreater(solid["volume"], 0, f"{where}: объём не положителен")

    def test_previously_broken_primitives_stay_fixed(self):
        # До 0.80 эти шесть случаев останавливали экспорт.
        for name in ("bracket", "lightning", "скоба", "cloud", "screw", "drive"):
            entry = measured(name)
            self.assertTrue(entry["ok"], name)
            self.assertEqual(entry.get("export_error"), "", name)


class ScrewDetailTest(unittest.TestCase):
    """Потайная головка — один профиль вращения, а не конус с отдельным поясом."""

    def test_head_variants_export_and_stay_one_body(self):
        variants = ("head=потай", "head=полукруг", "head=шестигранник",
                    "head=потай head_only=да", "head=нет")
        for variant in variants:
            result = build(f"с = screw d=4 length=25 {variant}\n", analyze_model=False)
            self.assertTrue(result.ok, f"{variant}: {(result.error or {}).get('message')}")
            solids = result.scene.visible_solids()
            self.assertEqual(len(solids), 1, variant)
            self.assertEqual(int(solid_parts(solids[0].manifold)), 1, variant)
            self.assertGreater(len(export_stl(solids)), 0, variant)

    def test_drive_example_exports(self):
        spec = lookup("drive")
        result = build(spec.example, analyze_model=False)
        self.assertTrue(result.ok, (result.error or {}).get("message"))
        self.assertGreater(len(export_glb(result.scene.visible_solids())), 0)

    def test_cloud_pinch_is_repaired(self):
        for script in ('о = cloud size=[180,90,70] puffs=9 seed=3',
                       'о = cloud size=[120,120,90] puffs=12 seed=7 flat=нет'):
            result = build(script + "\n", analyze_model=False)
            self.assertTrue(result.ok, script)
            self.assertGreater(len(export_stl(result.scene.visible_solids())), 0, script)


class RepairGuardsTest(unittest.TestCase):
    def test_clean_body_is_left_alone(self):
        result = build("к = box size=[20,20,20]\n", analyze_model=False)
        manifold = result.scene.visible_solids()[0].manifold
        self.assertIsNone(rebuild_manifold(manifold))
        self.assertIsNone(snap_manifold(manifold))

    def test_snap_preserves_shape(self):
        # Кривое по микрокромкам тело: посадка на сетку меняет объём на сотые.
        result = build(lookup("bracket").example, analyze_model=False)
        manifold = result.scene.visible_solids()[-1].manifold
        snapped = snap_manifold(manifold)
        self.assertIsNotNone(snapped)
        self.assertLess(abs(snapped.volume() / manifold.volume() - 1.0), 2e-4)
        verts, faces = manifold_mesh(snapped)
        self.assertEqual(analyze_topology(verts, faces, include_quality=False)["ok"], True)

    def test_snap_refuses_coarse_quantum(self):
        result = build(lookup("bracket").example, analyze_model=False)
        manifold = result.scene.visible_solids()[-1].manifold
        self.assertIsNone(snap_manifold(manifold, quantum=5.0))


class PrimitiveParamsTest(unittest.TestCase):
    def test_types_cover_primitives(self):
        primitives = [spec for spec in OPS.values() if spec.category == "Примитивы"]
        total = sum(len(spec.params) for spec in primitives)
        typed = sum(len(spec_for(spec.name, list(spec.params))) for spec in primitives)
        self.assertGreater(typed / total, 0.7, f"типы только у {typed} из {total}")
        for spec in primitives:
            self.assertTrue(spec_for(spec.name, list(spec.params)), spec.name)

    def test_suffix_rules(self):
        height = generic_spec("head_height")
        self.assertEqual(height["type"], "num")
        self.assertEqual(height["unit"], "мм")
        self.assertIn("head", height["label"])
        self.assertEqual(generic_spec("fringe_count")["type"], "int")
        self.assertEqual(generic_spec("plate_color")["type"], "str")
        self.assertEqual(generic_spec("groove_angle")["unit"], "°")
        self.assertEqual(generic_spec("eye_d")["type"], "num")

    def test_disputed_names_stay_free(self):
        for name in DISPUTED:
            self.assertIsNone(generic_spec(name), name)

    def test_suffix_needs_a_prefix(self):
        # Односложные имена не должны получать тип по окончанию.
        self.assertIsNone(generic_spec("_d"))
        self.assertIsNone(generic_spec("d_x"))
        self.assertIsNone(generic_spec("_color"))

    def test_every_parameter_is_described(self):
        for spec in OPS.values():
            if spec.category != "Примитивы":
                continue
            for name, text in spec.params.items():
                self.assertGreaterEqual(len(text.strip()), 4, f"{spec.name}.{name}")

    def test_hull_has_labels_not_wrong_controls(self):
        specs = spec_for("hull", ["objects", "points"])
        for name in ("objects", "points"):
            self.assertEqual(specs[name]["type"], "str", name)
            self.assertTrue(specs[name]["label"], name)


if __name__ == "__main__":
    unittest.main()
