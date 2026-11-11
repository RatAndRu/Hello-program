"""Шесть воспроизводимых проверок драпировки и два отдельных опыта.

Запуск из корня репозитория:
    OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python forma/tools/drape_six_probe.py --fcl --ccd
    OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python forma/tools/drape_six_probe.py --mode stop-xy --fcl

Никакие опытные поправки не включаются в приложение. --fcl и --ccd требуют
отдельно установленные python-fcl и ipctk. CCD проверяет линейные отрезки
между концами шагов после предварительного размещения, а не внутренние
проекции решателя или соседние примитивы. Результаты — измерения, не гарантия
физического равновесия и не рекомендация экспортировать дефектную сетку.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import io
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import cloth  # noqa: E402
from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402
from audit_drape_sleeve import _fcl_audit, _fcl_object  # noqa: E402
from drape_mujoco_probe import TrajectoryAudit, tetrahedral_shell  # noqa: E402
from drape_triangle_probe import TriangleSupportProbe  # noqa: E402

CASES = {
    "01_sheet_over_ball": ("benchmarks/drape_six/01_sheet_over_ball.forma", "лист", "результат",
                           ("площадка", "шар")),
    "02_sheet_over_sheet": ("benchmarks/drape_six/02_sheet_over_sheet.forma", "лист", "результат",
                            ("площадка",)),
    "03_soft_sphere": ("benchmarks/drape_six/03_soft_sphere.forma", "шар", "результат",
                       ("площадка",)),
    "04_tablecloth": ("examples/drape_tablecloth_fast_076.forma", "лист_скатерти", "скатерть",
                      ("столешница", "ножка_левая_передняя", "ножка_правая_передняя",
                       "ножка_левая_задняя", "ножка_правая_задняя", "пол")),
    "05_sleeve": ("benchmarks/drape_six/05_sleeve.forma", "рукав", "результат", ("площадка",)),
    "06_sleeve_around_rod": ("benchmarks/drape_six/06_sleeve_around_rod.forma", "рукав", "результат",
                             ("площадка", "стержень")),
}


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("Исходный решатель изменился: опыт нужно адаптировать перед запуском")
    return source.replace(old, new, 1)


class FreezeXYProbe:
    """Откат точки на шаг и постоянная остановка + ограниченные XY-поправки.

    Это конкретная исследовательская реализация идеи, а не единственно
    возможная. Сохранены обычные 3D-ограничения и самоконтакт решателя. Только
    дополнительная поправка ниже не двигает высоту; другие части решателя
    могут её изменять. Считаются только вершины, попавшие в существующее поле
    опор. Никакой гарантии контакта по граням или точной длины всех рёбер нет.
    """

    def __init__(self, strength=0.2):
        self.strength = float(strength)
        self.frozen = None
        self.frozen_position = None
        self.infeasible_observations = 0

    def setup(self, count):
        self.frozen = np.zeros(count, dtype=bool)
        self.frozen_position = np.zeros((count, 3), dtype=float)

    def rollback(self, previous, position, free, field, offset):
        if field is None:
            return
        distance, _, _ = field.closest(position)
        hit = free & np.isfinite(distance) & (distance < offset)
        self.frozen |= hit
        self.frozen_position[hit] = previous[hit]
        position[hit] = previous[hit]
        free[hit] = False

    def planar(self, position, a, b, rest, free, gravity):
        gravity = np.asarray(gravity, dtype=float)
        norm = float(np.linalg.norm(gravity))
        if norm < 1e-12:
            return
        up = -gravity / norm
        delta = position[b] - position[a]
        height = delta @ up
        horizontal = delta - height[:, None] * up
        length = np.linalg.norm(horizontal, axis=1)
        target = np.sqrt(np.maximum(rest * rest - height * height, 0.0))
        self.infeasible_observations += int(np.count_nonzero(np.abs(height) > rest + 1e-9))
        possible = (np.abs(height) < rest) & (length > 1e-9)
        amount = np.where(possible, np.maximum(length - target, 0.0) /
                          np.maximum(length, 1e-12) * self.strength, 0.0)
        # При равной высоте направление «следующая ниже предыдущей» не задано.
        lower_a = (height > 1e-6) & free[a]
        lower_b = (height < -1e-6) & free[b]
        position[a] += horizontal * (amount * lower_a)[:, None]
        position[b] -= horizontal * (amount * lower_b)[:, None]

    def restore(self, position):
        position[self.frozen] = self.frozen_position[self.frozen]


def _instrumented_solver(mode, state, with_ccd):
    """Отдельная копия штатной функции. Реальная функция не переписывается."""
    if mode not in ("current", "stop-xy", "surface", "stop-xy-surface"):
        raise ValueError(f"Неизвестный опыт: {mode}")
    xy = FreezeXYProbe()
    state["xy"] = xy
    source = inspect.getsource(cloth.simulate)
    use_xy = mode in ("stop-xy", "stop-xy-surface")
    use_surface = mode in ("surface", "stop-xy-surface")
    setup = "    _six_begin(position, faces, supports, shell)\n"
    if use_xy:
        setup += "    _six_xy_setup(count)\n"
        source = _replace_once(
            source, "        position[free] += velocity[free] + gravity * float(g)\n"
                    "        position[pinned] = fixed\n",
            "        position[free] += velocity[free] + gravity * float(g)\n"
            "        position[pinned] = fixed\n"
            "        _six_xy_rollback(previous, position, free, field, offset)\n")
        source = _replace_once(
            source, "                position[b] -= correction * wb[:, None]\n            # --- длины",
            "                position[b] -= correction * wb[:, None]\n"
            "                _six_xy_planar(position, a, b, rest[group], free, gravity)\n"
            "            # --- длины")
        source = _replace_once(
            source, "                if np.any(near):\n"
                    "                    ids = np.nonzero(near)[0]\n"
                    "                    position[ids] += normal[ids] * (offset - distance[ids])[:, None]\n"
                    "                    contacts = max(contacts, int(len(ids)))",
            "                if np.any(near):\n"
            "                    ids = np.nonzero(near & free)[0]\n"
            "                    _six_xy_rollback(previous, position, free, field, offset)\n"
            "                    contacts = max(contacts, int(len(ids)))")
    if use_surface:
        setup += "    _six_surface_setup(field, faces, shell)\n"
    source = _replace_once(source, "    previous = position.copy()\n    contacts = 0",
                           setup + "    previous = position.copy()\n    contacts = 0")
    if use_xy or use_surface:
        iteration = ""
        if use_surface:
            iteration += ("            if (it + 1) % 4 == 0 or it == iterations - 1:\n"
                          "                _six_surface_project(position, free)\n")
        iteration += "            position[pinned] = fixed\n"
        if use_xy:
            iteration += "            _six_xy_restore(position)\n"
        source = _replace_once(source, "            position[pinned] = fixed\n\n        if friction > 0",
                               iteration + "\n        if friction > 0")
    ending = ""
    if use_xy:
        ending += ("        _six_xy_rollback(previous, position, free, field, offset)\n"
                   "        _six_xy_restore(position)\n")
    if use_surface:
        ending += "        _six_surface_project(position, free)\n"
    ending += "        _six_end(position)\n"
    source = _replace_once(source, "        if not np.all(np.isfinite(position)) or",
                           ending + "        if not np.all(np.isfinite(position)) or")

    def begin(position, faces, supports, shell):
        state["placed"] = position.copy()
        state["shell"] = shell.copy()
        state["frames"] = 0
        if with_ccd:
            static, inverse = np.unique(supports.reshape(-1, 3), axis=0, return_inverse=True)
            try:
                state["ccd"] = TrajectoryAudit(
                    position, faces, {"опоры": (static, inverse.reshape(-1, 3))}, min_distance=0.0)
            except RuntimeError as exc:
                state["ccd_initial_error"] = str(exc)

    def end(position):
        state["frames"] += 1
        if with_ccd and "ccd" in state and "ccd_failure_step" not in state:
            if not state["ccd"].check(position):
                state["ccd_failure_step"] = state["ccd"].steps

    def surface_setup(field, faces, shell):
        if field is None:
            raise RuntimeError("Для опыта поверхностного контакта нужна опора")
        state["surface"] = TriangleSupportProbe(field, faces, shell)

    def surface_project(position, free):
        state["surface"].project(position, free, rounds=4)

    namespace = dict(cloth.__dict__)
    namespace.update(_six_begin=begin, _six_end=end, _six_xy_setup=xy.setup,
                     _six_xy_rollback=xy.rollback, _six_xy_planar=xy.planar,
                     _six_xy_restore=xy.restore, _six_surface_setup=surface_setup,
                     _six_surface_project=surface_project)
    exec(compile(source, "<drape six diagnostic>", "exec"), namespace)
    return namespace["simulate"]


def _ratios(reference, current, pairs):
    if not len(pairs):
        return None
    initial = np.linalg.norm(reference[pairs[:, 1]] - reference[pairs[:, 0]], axis=1)
    final = np.linalg.norm(current[pairs[:, 1]] - current[pairs[:, 0]], axis=1)
    if np.any(initial <= 1e-12):
        return {"count": len(pairs), "complete": False, "reason": "нулевая исходная длина"}
    change = final / initial - 1.0
    return {"count": len(pairs), "complete": True,
            "max_compression_percent": float(max(0.0, -np.min(change)) * 100.0),
            "max_extension_percent": float(max(0.0, np.max(change)) * 100.0),
            "max_abs_percent": float(np.max(np.abs(change)) * 100.0),
            "p90_abs_percent": float(np.percentile(np.abs(change), 90) * 100.0)}


def _wall_normal_projections(reference, current, faces, shell):
    """Проекция найденных пар стенки; не полная карта толщины."""
    return cloth.wall_normal_projections(reference, current, faces, shell)


def _tetra_probe(name, reference, current, faces):
    """Диагностическая призменная сетка; часть торцевых граней заменена."""
    if name == "03_soft_sphere":
        return {"available": False, "reason": "для сплошного шара нет этой призменной модели"}
    kind = "sleeve" if name in ("05_sleeve", "06_sleeve_around_rod") else "table"
    try:
        _surface, tets, changed = tetrahedral_shell(kind, reference, faces)
    except (ValueError, KeyError) as exc:
        return {"available": False, "reason": str(exc)}

    def signed(position):
        points = position[tets]
        return np.einsum("ij,ij->i", points[:, 1] - points[:, 0],
                         np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0])) / 6.0

    initial, final = signed(reference), signed(current)
    if np.any(initial <= 1e-12):
        return {"available": False, "reason": "вырожденные исходные призмы"}
    ratio = final / initial
    return {"available": True, "count": int(len(tets)), "inverted": int(np.count_nonzero(ratio <= 0)),
            "min_jacobian": float(np.min(ratio)), "max_jacobian": float(np.max(ratio)),
            "retriangulated_boundary_faces": int(changed)}


def _table_edges(reference, current):
    center = np.median(current[(np.abs(reference[:, 0]) < 10) & (np.abs(reference[:, 1]) < 10), 2])
    result = []
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        x, other = reference[:, axis] * sign, reference[:, 1 - axis]
        edge = (x > 59.99) & (np.abs(other) < 1)
        tail = (x > 49) & (x < 50) & (np.abs(other) < 1)
        if not np.any(edge) or not np.any(tail):
            raise RuntimeError("В исходной сетке не найдены контрольные узлы края скатерти")
        hem = np.median(current[edge], axis=0)
        upper = np.median(current[tail], axis=0)
        result.append({"axis": ("+x", "-x", "+y", "-y")[len(result)],
                       "hem_from_center_mm": float(hem[axis] * sign),
                       "drop_from_center_mm": float(center - hem[2]),
                       "angle_from_vertical_deg": float(np.degrees(np.arctan2(
                           abs(hem[axis] - upper[axis]), abs(hem[2] - upper[2]))))})
    return result


def _fcl_supports(body_vertices, body_faces, supports):
    import fcl
    body = _fcl_object(fcl, body_vertices, body_faces)
    answer = {}
    for name, (vertices, faces) in supports.items():
        collision = fcl.CollisionResult()
        limit = 300_000
        fcl.collide(body, _fcl_object(fcl, vertices, faces),
                    fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), collision)
        pairs = {(int(contact.b1), int(contact.b2)) for contact in collision.contacts}
        answer[name] = {"contact_or_crossing": bool(pairs), "pairs": len(pairs),
                        "complete": len(collision.contacts) < limit}
    return answer


def run_case(name, *, mode="current", with_fcl=False, with_ccd=False, check_glb=False):
    if name not in CASES:
        raise ValueError(f"Неизвестный сценарий: {name}")
    if with_fcl:
        import fcl  # noqa: F401
    if with_ccd:
        import ipctk  # noqa: F401

    relative, initial_name, output_name, target_names = CASES[name]
    path = ROOT / relative
    script = path.read_text(encoding="utf-8")
    state = {}
    original = cloth.simulate
    instrumented = _instrumented_solver(mode, state, with_ccd)

    def run(vertices, faces, supports, **kwargs):
        if "reference" in state:
            raise RuntimeError("Диагностический сценарий должен содержать один drape")
        state["reference"] = np.asarray(vertices).copy()
        state["faces"] = np.asarray(faces).copy()
        state["support_triangles"] = np.asarray(supports).copy()
        state["parameters"] = dict(kwargs)
        report = instrumented(vertices, faces, supports, **kwargs)
        state["simulation"] = report
        return report

    cloth.simulate = run
    try:
        started = time.perf_counter()
        result = build(script, analyze_model=False, base_dir=path.parent)
        seconds = time.perf_counter() - started
    finally:
        cloth.simulate = original
    if not result.ok:
        raise RuntimeError(f"{name}: {result.error}")
    if "simulation" not in state:
        raise RuntimeError(f"{name}: команда drape не выполнилась")

    scene = result.scene
    original_body = scene.objects[initial_name].manifold
    body = scene.objects[output_name]
    vertices, faces = manifold_mesh(body.manifold)
    supports = {target: manifold_mesh(scene.objects[target].manifold) for target in target_names}
    combined_vertices, combined_faces, shift = [], [], 0
    for v, f in supports.values():
        combined_vertices.append(v)
        combined_faces.append(f + shift)
        shift += len(v)
    combined = np.vstack(combined_vertices), np.vstack(combined_faces)
    initial_bbox = np.asarray(original_body.bounding_box(), dtype=float)
    bbox = np.asarray(body.manifold.bounding_box(), dtype=float)
    import trimesh
    final_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    reference = state["reference"]
    current = state["simulation"]["vertices"]
    original_faces = state["faces"]
    metadata = body.meta["cloth"]
    boolean = {}
    for target in target_names:
        intersection = body.manifold ^ scene.objects[target].manifold
        boolean[target] = {"volume_mm3": float(intersection.volume()),
                           "status": str(intersection.status())}
    analysis = {
        "name": name, "scenario": relative,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": mode, "elapsed_seconds": round(seconds, 3),
        "visible_triangles": sum(len(manifold_mesh(item.manifold)[1]) for item in result.visible_solids()),
        "body_triangles": len(faces), "bbox_initial": initial_bbox.tolist(), "bbox_final": bbox.tolist(),
        "watertight": bool(final_mesh.is_watertight), "euler_number": int(final_mesh.euler_number),
        "height_initial_mm": float(initial_bbox[5] - initial_bbox[2]),
        "height_final_mm": float(bbox[5] - bbox[2]),
        "volume_ratio": float(body.manifold.volume() / original_body.volume()),
        "edges": _ratios(reference, current, cloth._edge_arrays(original_faces)),
        "shell_pair_lengths": _ratios(reference, current, state["shell"]),
        "shell_normal_projections": _wall_normal_projections(reference, current, original_faces,
                                                               state["shell"]),
        "tetra_probe": _tetra_probe(name, reference, current, original_faces),
        "boolean_by_support": boolean,
        "boolean_reliable": bool(metadata["self_intersections_complete"]
                                 and not metadata["self_intersections"]
                                 and not metadata["self_intersections_adjacent"]),
        "metadata": {key: metadata[key] for key in (
            "supports", "rigid", "steps", "converged", "last_motion", "movement_tolerance",
            "max_strain_all", "strain_all_p90", "penetration", "support_surface_pairs",
            "support_overlap_volume", "support_overlap_complete", "self_intersections",
            "self_intersections_adjacent", "self_intersections_complete", "equilibrium_verified",
            "geometry_checks_passed")},
        "warnings": [item["message"] for item in scene.logs if item["level"] == "warn"],
    }
    if with_fcl:
        analysis["fcl"] = _fcl_audit(vertices, faces, combined)
        analysis["fcl_by_support"] = _fcl_supports(vertices, faces, supports)
    if with_ccd:
        ccd = state.get("ccd")
        analysis["ccd"] = {"initial_error": state.get("ccd_initial_error"),
                           "checked_segments": ccd.steps if ccd else 0,
                           "first_unsafe_segment": state.get("ccd_failure_step"),
                           "total_frames": state["frames"], "minimum_distance_mm": 0.0,
                           "completed": bool(ccd and ccd.steps == state["frames"]
                                             and "ccd_failure_step" not in state),
                           "after_placement_only": True}
    if check_glb:
        glb = result.glb()
        loaded = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene", process=False)
        analysis["glb"] = {"bytes": len(glb),
                           "triangles": sum(len(mesh.faces) for mesh in loaded.geometry.values())}
    if mode in ("stop-xy", "stop-xy-surface"):
        analysis["stop_xy"] = {"frozen_vertices": int(state["xy"].frozen.sum()),
                               "infeasible_edge_observations": state["xy"].infeasible_observations,
                               "strength": state["xy"].strength}
    if mode in ("surface", "stop-xy-surface"):
        probe = state["surface"]
        analysis["surface_probe"] = {"correction_rounds": probe.applied_rounds,
                                     "max_intersecting_pairs": probe.max_pairs,
                                     "budget_exceeded": probe.budget_exceeded}
    if name == "04_tablecloth":
        analysis["material_edges"] = _table_edges(reference, current)
    if name == "06_sleeve_around_rod":
        rod = scene.objects["стержень"].manifold
        initial = {"sleeve_bbox": initial_bbox.tolist(), "rod_bbox": list(rod.bounding_box()),
                   "intersection_volume_mm3": float((original_body ^ rod).volume())}
        if with_fcl:
            import fcl
            sleeve_object = _fcl_object(fcl, *manifold_mesh(original_body))
            rod_object = _fcl_object(fcl, *manifold_mesh(rod))
            collision = fcl.CollisionResult()
            hits = fcl.collide(sleeve_object, rod_object,
                               fcl.CollisionRequest(num_max_contacts=1), collision)
            distance = fcl.distance(sleeve_object, rod_object,
                                    fcl.DistanceRequest(enable_nearest_points=True), fcl.DistanceResult())
            initial.update(fcl_contact_or_crossing=bool(hits), fcl_distance_mm=float(distance))
        analysis["initial_setup"] = initial
    return analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["all", *CASES], default="all")
    parser.add_argument("--mode", choices=["current", "stop-xy", "surface", "stop-xy-surface"],
                        default="current")
    parser.add_argument("--fcl", action="store_true", help="обязательная независимая FCL")
    parser.add_argument("--ccd", action="store_true", help="независимая CCD концов шагов")
    parser.add_argument("--glb", action="store_true", help="прочитать полученный GLB и пересчитать грани")
    parser.add_argument("--output", type=Path, help="сохранить JSON в указанный файл")
    args = parser.parse_args()
    names = list(CASES) if args.case == "all" else [args.case]
    results = [run_case(name, mode=args.mode, with_fcl=args.fcl, with_ccd=args.ccd,
                        check_glb=args.glb) for name in names]
    versions = {}
    for distribution in ("numpy", "manifold3d", "trimesh", "python-fcl", "ipctk"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    source_hashes = {name: hashlib.sha256((ROOT / "forma" / name).read_bytes()).hexdigest()
                     for name in ("cloth.py", "cloth_collision.py", "cloth_check.py",
                                  "cloth_remesh.py", "ops_interior.py")}
    payload = {"python": platform.python_version(), "platform": platform.platform(),
               "dependencies": versions, "implementation_sha256": source_hashes,
               "mode": args.mode, "cases": results,
               "note": "Диагностика, не подтверждение готовности. CCD не проверяет внутренние "
                       "проекции, соседние примитивы или перенос до начала расчёта."}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
