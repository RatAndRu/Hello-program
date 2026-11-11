"""Найти начало дефекта в стресс-сцене рукава, не изменяя решатель.

Для опытной диагностики строится призменная объёмная сетка именно этого
рукава. Некоторые диагонали его торцов отличаются от исходных, поэтому
инверсия тетраэдра означает нарушение данной дискретной карты, но сама по себе
не доказывает самопересечение исходной граничной поверхности.

Запуск из корня: PYTHONPATH=forma python forma/tools/audit_drape_evolution.py
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import cloth  # noqa: E402
from forma.cloth_check import self_intersections  # noqa: E402
from forma.run import build  # noqa: E402
from drape_mujoco_probe import tetrahedral_shell  # noqa: E402


def _signed_tetra_volumes(vertices, tets):
    p = np.asarray(vertices, dtype=float)[tets]
    return np.einsum('ij,ij->i', p[:, 1] - p[:, 0],
                     np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0])) / 6.


def capture(source, base_dir):
    """Копии положения в конце каждого шага штатного simulate через trace."""
    lines, first_line = inspect.getsourcelines(cloth.simulate)
    matches = [i for i, line in enumerate(lines)
               if line.strip().startswith('if not np.all(np.isfinite(position)) or ')]
    if len(matches) != 1:
        raise RuntimeError('Не найден единственный конец шага решателя')
    target = first_line + matches[0]
    history = []
    reference = {}
    original_trace = sys.gettrace()

    def trace(frame, event, _arg):
        if frame.f_code is cloth.simulate.__code__:
            if event == 'line' and frame.f_lineno == target:
                local = frame.f_locals
                if not reference:
                    reference['vertices'] = local['vertices'].copy()
                    reference['faces'] = local['faces'].copy()
                history.append(local['position'].copy())
            return trace
        return None

    try:
        sys.settrace(trace)
        result = build(source, analyze_model=False, base_dir=base_dir)
    finally:
        sys.settrace(original_trace)
    if not result.ok:
        raise RuntimeError(f'Сцена не собралась: {result.error}')
    if not history:
        raise RuntimeError('Решатель не выполнил ни одного шага')
    return reference['vertices'], reference['faces'], history


def audit(vertices, faces, history):
    _surface, tets, changed = tetrahedral_shell('sleeve', vertices, faces)
    base = _signed_tetra_volumes(vertices, tets)
    if np.any(base <= 0):
        raise RuntimeError('Исходные тетраэдры не ориентированы положительно')
    edges = cloth._edge_arrays(faces)
    lengths = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    first_inversion = first_crossing = None
    for index, position in enumerate(history, start=1):
        ratios = _signed_tetra_volumes(position, tets) / base
        if first_inversion is None and np.any(ratios <= 0):
            current = np.linalg.norm(position[edges[:, 1]] - position[edges[:, 0]], axis=1)
            first_inversion = {'step': index, 'count': int(np.count_nonzero(ratios <= 0)),
                               'min_jacobian': float(ratios.min()),
                               'max_edge_strain': float(np.max(np.abs(current / lengths - 1.)))}
        if first_crossing is None:
            check = self_intersections(position, faces)
            if not check['complete']:
                raise RuntimeError(f'Проверка поверхности не завершена на шаге {index}: {check}')
            if check['pairs'] or check['adjacent_pairs']:
                first_crossing = {'step': index, 'nonadjacent_pairs': check['pairs'],
                                  'adjacent_pairs_after_inset': check['adjacent_pairs']}
        if first_inversion is not None and first_crossing is not None:
            break
    return {'vertices': len(vertices), 'faces': len(faces), 'steps_captured': len(history),
            'diagnostic_tetrahedra': len(tets), 'retriangulated_boundary_faces': changed,
            'first_tet_inversion': first_inversion, 'first_surface_crossing': first_crossing,
            'note': 'Инверсия относится к специальной призменной дискретизации, '
                    'а не является прямым тестом произвольной детали.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save-history', type=Path,
                        help='необязательно сохранить позиции в NPZ вне репозитория')
    args = parser.parse_args()
    path = ROOT / 'benchmarks' / 'drape_sleeve_stress_077.forma'
    started = time.perf_counter()
    vertices, faces, history = capture(path.read_text(encoding='utf-8'), path.parent)
    if args.save_history:
        np.savez_compressed(args.save_history, original=vertices, faces=faces, positions=np.asarray(history))
    summary = audit(vertices, faces, history)
    summary['elapsed_seconds'] = round(time.perf_counter() - started, 3)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
