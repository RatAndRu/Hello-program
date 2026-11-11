"""Проверить пробный IPC-проектор на первом небезопасном шаге реальной сцены.

Это исследовательский инструмент, не новый drape. Он не продолжает симуляцию
после исправленного шага и не доказывает пригодность результата для экспорта.
Обязательно ограничивайте длительность внешним таймаутом, например:

  timeout 75s env OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python \
    forma/tools/drape_ipc_first_impact_probe.py --case 01_sheet_over_ball --output impact-ball.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forma import cloth  # noqa: E402
import drape_six_probe as six  # noqa: E402
from drape_ipc_contact_probe import IPCContactProbe  # noqa: E402
from drape_mujoco_probe import TrajectoryAudit  # noqa: E402
from audit_drape_sleeve import _fcl_object  # noqa: E402


class _Captured(BaseException):
    pass


def first_unsafe_segment(name):
    """Получить настоящий шаг неизменённого решателя, закончив расчёт на нём."""
    original_factory = six._instrumented_solver
    saved = {}

    def factory(mode, state, with_ccd):
        solver = original_factory(mode, state, with_ccd)
        begin = solver.__globals__['_six_begin']
        end = solver.__globals__['_six_end']

        def intercept_begin(position, faces, supports, shell):
            begin(position, faces, supports, shell)
            saved['faces'] = np.array(faces, copy=True)
            saved['supports'] = np.array(supports, copy=True)
            saved['shell'] = np.array(shell, copy=True)

        def intercept_end(position):
            end(position)
            if 'ccd_failure_step' not in state:
                return
            ccd = state['ccd']
            saved['boundary'] = ccd.boundary.copy()
            saved['start'], saved['candidate'] = (x.copy() for x in ccd.failed_segment)
            saved['step'] = state['ccd_failure_step']
            saved['reference'] = state['reference'].copy()
            saved['parameters'] = state['parameters'].copy()
            raise _Captured()

        solver.__globals__.update(_six_begin=intercept_begin, _six_end=intercept_end)
        return solver

    six._instrumented_solver = factory
    try:
        try:
            six.run_case(name, mode='current', with_ccd=True)
        except _Captured:
            pass
    finally:
        six._instrumented_solver = original_factory
    if 'start' not in saved:
        raise RuntimeError(f'{name}: не найден небезопасный шаг, либо CCD не смогла запуститься')
    ids = saved['boundary']
    remap = np.full(len(saved['reference']), -1, dtype=np.int64)
    remap[ids] = np.arange(len(ids))
    faces = remap[saved['faces']]
    shell = remap[saved['shell']]
    if np.any(faces < 0) or np.any(shell < 0):
        raise RuntimeError('В диагностической сетке отсутствуют частицы граней или стенки')
    pinned = saved['parameters']['pinned']
    free = np.ones(len(ids), dtype=bool) if pinned is None else ~np.asarray(pinned, dtype=bool)[ids]
    return dict(name=name, step=saved['step'], old=saved['start'][:len(ids)],
                candidate=saved['candidate'][:len(ids)], reference=saved['reference'][ids],
                faces=faces, shell=shell, supports=saved['supports'], free=free,
                friction=float(saved['parameters']['friction']))


def _surface_pairs(vertices, faces, supports):
    """Независимая FCL конечного положения; касание и пересечение не различаются."""
    import fcl
    static, inverse = np.unique(supports.reshape(-1, 3), axis=0, return_inverse=True)
    body = _fcl_object(fcl, vertices, faces)
    obstacle = _fcl_object(fcl, static, inverse.reshape(-1, 3))
    result = fcl.CollisionResult()
    fcl.collide(body, obstacle, fcl.CollisionRequest(num_max_contacts=300_000, enable_contact=True), result)
    return {'pairs': len({(int(c.b1), int(c.b2)) for c in result.contacts}),
            'complete': len(result.contacts) < 300_000}


def _metrics(reference, vertices, faces, shell):
    edges = cloth._edge_arrays(faces)
    rest = np.linalg.norm(reference[edges[:, 1]] - reference[edges[:, 0]], axis=1)
    now = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    strain = np.abs(now / np.maximum(rest, 1e-12) - 1.) * 100.
    return {'max_edge_change_percent': float(np.max(strain)),
            'wall_normal_projections': cloth.wall_normal_projections(reference, vertices, faces, shell)}


def inspect_impact(name):
    started = time.perf_counter()
    segment = first_unsafe_segment(name)
    old, proposed = segment['old'], segment['candidate']
    faces, shell, supports, free = segment['faces'], segment['shell'], segment['supports'], segment['free']
    static, inverse = np.unique(supports.reshape(-1, 3), axis=0, return_inverse=True)

    def check(vertices):
        audit = TrajectoryAudit(old, faces, {'опоры': (static, inverse.reshape(-1, 3))})
        return audit.check(vertices)

    before = check(proposed)
    projector = IPCContactProbe(old, faces, shell, supports, friction=segment['friction'], rounds=3)
    corrected = proposed.copy()
    start_contact = time.perf_counter()
    projector.project(old, corrected, free)
    projection_seconds = time.perf_counter() - start_contact
    after = check(corrected)
    movement = np.linalg.norm(corrected - proposed, axis=1)
    source_path = ROOT / six.CASES[name][0]
    versions = {package: importlib.metadata.version(package)
                for package in ('numpy', 'scipy', 'manifold3d', 'trimesh', 'ipctk', 'python-fcl')}
    files = ('forma/cloth.py', 'forma/cloth_collision.py', 'forma/cloth_check.py',
             'forma/cloth_remesh.py', 'forma/ops_interior.py', 'tools/drape_six_probe.py',
             'tools/drape_ipc_contact_probe.py', 'tools/drape_ipc_first_impact_probe.py',
             'tools/drape_mujoco_probe.py', 'tools/audit_drape_sleeve.py')
    return {
        'scenario': name, 'scenario_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'first_unsafe_step': segment['step'], 'dynamic_vertices': len(old), 'triangles': len(faces),
        'pinned_vertices': int(np.sum(~free)), 'friction': segment['friction'],
        'ccd_before': bool(before), 'ccd_after': bool(after), 'ccd_min_distance_mm': 0.,
        'support_fcl_before': _surface_pairs(proposed, faces, supports),
        'support_fcl_after': _surface_pairs(corrected, faces, supports),
        'proposed': _metrics(segment['reference'], proposed, faces, shell),
        'corrected': _metrics(segment['reference'], corrected, faces, shell),
        'contact_stats': projector.stats(),
        'correction_max_mm': float(np.max(movement)),
        'corrected_vertex_count': int(np.count_nonzero(movement > 1e-9)),
        'projection_seconds': projection_seconds, 'elapsed_seconds': time.perf_counter() - started,
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'dependencies': versions,
                        'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                          for path in files}},
        'note': ('Только один линейный шаг штатного решателя после размещения. '
                 'Повторная CCD и проектор используют одну библиотеку IPC; FCL проверяет лишь конец. '
                 'Дальнейшее падение, все внутренние проекции и равновесие не проверены.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=('01_sheet_over_ball', '06_sleeve_around_rod'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix.lower() != '.json':
        parser.error('Укажите путь .json')
    report = inspect_impact(args.case)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
