"""Необязательный опыт локального объёма для штатного PBD-решателя.

Только стресс-рукав с парными слоями. Призменная тетраэдрализация меняет
некоторые граничные диагонали, а этот скрипт подключает её лишь на время
отдельного процесса. Это не исправление drape и не геометрия для экспорта.

PYTHONPATH=forma python forma/tools/drape_tet_pbd_probe.py --steps 90 --mode lower
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
from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402
from audit_drape_evolution import _signed_tetra_volumes  # noqa: E402
from audit_drape_sleeve import _fcl_audit  # noqa: E402
from drape_mujoco_probe import tetrahedral_shell  # noqa: E402


class VolumeProjector:
    """Приближённые ограничения тетраэдров; не гарантируют невырождение."""

    def __init__(self, vertices, tets, *, mode='lower', minimum=.3,
                 strength=1., rounds=1, lock_support=False):
        self.tets = np.asarray(tets, dtype=np.int64)
        self.rest = _signed_tetra_volumes(vertices, self.tets)
        if not len(self.tets) or np.any(self.rest <= 1e-12):
            raise ValueError('Ожидаются невырожденные ориентированные тетраэдры')
        if mode not in ('lower', 'equal') or not 0 < minimum <= 1 or not 0 < strength <= 2 or rounds < 1:
            raise ValueError('Некорректные параметры экспериментального ограничения')
        self.mode, self.minimum, self.strength = mode, minimum, strength
        self.rounds, self.lock_support = int(rounds), bool(lock_support)
        masks = [0] * len(vertices)
        groups = []
        for index, tet in enumerate(self.tets):
            used = 0
            for node in tet:
                used |= masks[int(node)]
            color = 0
            while used & (1 << color):
                color += 1
            for node in tet:
                masks[int(node)] |= 1 << color
            while len(groups) <= color:
                groups.append([])
            groups[color].append(index)
        self.groups = [np.asarray(group, dtype=np.int64) for group in groups]

    def project(self, position, free, support):
        eligible = np.asarray(free, dtype=bool)
        if self.lock_support:
            eligible = eligible & ~support
        for _ in range(self.rounds):
            groups = self.groups if self.mode == 'lower' else [np.arange(len(self.tets))]
            for group in groups:
                tets = self.tets[group]
                p = position[tets]
                x, y, z = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]
                volume = np.einsum('ij,ij->i', x, np.cross(y, z)) / 6.
                target = self.rest[group] * (self.minimum if self.mode == 'lower' else 1.)
                active = volume < target if self.mode == 'lower' else np.ones(len(group), dtype=bool)
                if not np.any(active):
                    continue
                tets, x, y, z = tets[active], x[active], y[active], z[active]
                delta = target[active] - volume[active]
                g1, g2, g3 = np.cross(y, z) / 6., np.cross(z, x) / 6., np.cross(x, y) / 6.
                grad = np.stack((-g1 - g2 - g3, g1, g2, g3), axis=1)
                weights = eligible[tets]
                grad *= weights[:, :, None]
                denom = np.sum(grad * grad, axis=(1, 2))
                move = grad * (self.strength * delta / np.maximum(denom, 1e-12))[:, None, None]
                norm = np.linalg.norm(move, axis=2)
                move *= np.minimum(1., .2 / np.maximum(norm, 1e-12))[:, :, None]
                if self.mode == 'lower':
                    # В одной цветовой группе узлы не повторяются.
                    position[tets] += move
                else:
                    degree = np.bincount(tets.ravel(), weights=weights.ravel().astype(float),
                                         minlength=len(position))
                    for axis in range(3):
                        position[:, axis] += np.bincount(
                            tets.ravel(), weights=move[:, :, axis].ravel(),
                            minlength=len(position)) / np.maximum(degree, 1.)
        return position

    def measure(self, position):
        jacobian = _signed_tetra_volumes(position, self.tets) / self.rest
        return {'tetrahedra': len(self.tets), 'inverted': int(np.count_nonzero(jacobian <= 0)),
                'min_jacobian': float(jacobian.min()), 'max_jacobian': float(jacobian.max())}


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Контрольная точка в решателе не найдена однозначно: {old}')
    return text.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('lower', 'equal'), default='lower')
    parser.add_argument('--steps', type=int, default=90)
    parser.add_argument('--minimum', type=float, default=.3)
    parser.add_argument('--strength', type=float, default=1.)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--lock-support', action='store_true')
    parser.add_argument('--project-last', action='store_true',
                        help='ограничение после общего объёма и после самоконтакта')
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000:
        raise SystemExit('Число шагов должно быть от 1 до 1000')
    state = {}

    def setup(vertices, faces):
        _surface, tets, changed = tetrahedral_shell('sleeve', vertices, faces)
        state['projector'] = VolumeProjector(vertices, tets, mode=args.mode, minimum=args.minimum,
                                             strength=args.strength, rounds=args.rounds,
                                             lock_support=args.lock_support)
        state['changed_faces'] = changed

    def project(position, free, support):
        return state['projector'].project(position, free, support)

    def record(position):
        state['tetra'] = state['projector'].measure(position)

    # Только локальная копия функции для этого процесса; исходный модуль на
    # диске не редактируется. Если структура решателя изменится, опыт завершится
    # ошибкой вместо выполнения в неожиданном месте.
    code = inspect.getsource(cloth.simulate)
    code = _replace_once(code, '    # --- степени частиц и индексы для общей поправки (метод Якоби) ---',
                         '    _probe_setup(vertices, faces)\n'
                         '    # --- степени частиц и индексы для общей поправки (метод Якоби) ---')
    if args.project_last:
        code = _replace_once(code, '            position[pinned] = fixed\n\n        if friction > 0',
                             '            position = _probe_project(position, free, support_contact)\n'
                             '            position[pinned] = fixed\n\n        if friction > 0')
        code = _replace_once(code, '        if not np.all(np.isfinite(position)) or',
                             '        position = _probe_project(position, free, support_contact)\n'
                             '        if field is not None:\n'
                             '            distance, _point, normal = field.closest(position)\n'
                             '            near = np.isfinite(distance) & (distance < offset)\n'
                             '            position[near] += normal[near] * (offset - distance[near])[:, None]\n'
                             '        position[pinned] = fixed\n'
                             '        if not np.all(np.isfinite(position)) or')
    else:
        code = _replace_once(code, '            # Приближённо удерживаем объём материала каждой замкнутой гибкой',
                             '            position = _probe_project(position, free, support_contact)\n'
                             '            # Приближённо удерживаем объём материала каждой замкнутой гибкой')
    code = _replace_once(code, '    final_lengths = np.linalg.norm',
                         '    _probe_record(position)\n    final_lengths = np.linalg.norm')
    original = cloth.simulate
    cloth._probe_setup, cloth._probe_project, cloth._probe_record = setup, project, record
    try:
        exec(compile(code, '<drape tet probe>', 'exec'), cloth.__dict__)
        path = ROOT / 'benchmarks' / 'drape_sleeve_stress_077.forma'
        source = path.read_text(encoding='utf-8')
        source = _replace_once(source, 'steps=160', f'steps={args.steps}')
        started = time.perf_counter()
        result = build(source, analyze_model=False, base_dir=path.parent)
    finally:
        cloth.simulate = original
        del cloth._probe_setup, cloth._probe_project, cloth._probe_record
    if not result.ok:
        raise RuntimeError(f'Стресс-сцена не собралась: {result.error}')
    body = result.scene.objects['проверка']
    vertices, faces = manifold_mesh(body.manifold)
    support = manifold_mesh(result.scene.objects['пол'].manifold)
    report = {'arguments': vars(args), 'elapsed_seconds': round(time.perf_counter() - started, 3),
              'tetra': state['tetra'], 'retriangulated_boundary_faces': state['changed_faces'],
              'metadata': body.meta['cloth'], 'fcl': _fcl_audit(vertices, faces, support),
              'note': 'Это эксперимент, а не проверенное равновесие и не готовая геометрия.'}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
