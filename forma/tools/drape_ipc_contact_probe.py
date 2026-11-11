"""Ограниченный исследовательский опыт IPC-контакта со штатным drape.

НЕ часть приложения и НЕ подтверждение сохранения всей толщины/размеров.
Использует ipctk только в отдельном тестовом окружении. Откат относится к
линейному переходу между концами шага; внутренние проекции не проверяются.
Запускать через drape_bounded_probe.py, чтобы вычисления имели предел времени.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import cloth  # noqa: E402
import drape_six_probe as six  # noqa: E402
from drape_support_probe import SupportContactProbe  # noqa: E402
from drape_triangle_probe import TriangleSupportProbe  # noqa: E402


class IPCContactProbe:
    """Пробный двусторонний контакт + консервативный откат IPC.

    Локальные поправки перемещают найденные пары стенки совместно. Не все
    столкновения разрешимы локально: тогда весь шаг уменьшается. Это может
    остановить далёкие от контакта части и не доказывает равновесия.
    """

    def __init__(self, vertices, faces, shell, supports, *, friction=0.0, rounds=3):
        import ipctk

        ipctk.set_num_threads(1)
        self.ipctk = ipctk
        vertices = np.asarray(vertices, dtype=float)
        faces = np.asarray(faces, dtype=np.int64)
        shell = np.asarray(shell, dtype=np.int64).reshape(-1, 2)
        supports = np.asarray(supports, dtype=float).reshape(-1, 3, 3)
        self.n = len(vertices)
        if not self.n or not len(faces) or not len(supports):
            raise ValueError('IPC-опыт: нужны вершины, грани и опоры')
        if not np.all(np.isfinite(vertices)) or not np.all(np.isfinite(supports)):
            raise ValueError('IPC-опыт: координаты должны быть конечными')
        if np.any(shell < 0) or np.any(shell >= self.n) or len(np.unique(shell)) != shell.size:
            raise ValueError('IPC-опыт: пары стенки должны быть непересекающимися')
        self.friction = float(friction)
        self.rounds = int(rounds)
        if not 0 <= self.friction <= 1 or not 1 <= self.rounds <= 8:
            raise ValueError('IPC-опыт: неверное трение или число проходов')
        self.static, inverse = np.unique(supports.reshape(-1, 3), axis=0, return_inverse=True)
        self.faces = np.vstack((faces, inverse.reshape(-1, 3) + self.n)).astype(np.int32)
        self.edges = cloth._edge_arrays(self.faces).astype(np.int32)
        combined = np.vstack((vertices, self.static))
        self.mesh = ipctk.CollisionMesh(combined, self.edges, self.faces)
        self.mesh.can_collide = ipctk.make_static_obstacle_filter(self.n)
        self.mesh.init_adjacencies()
        if ipctk.has_intersections(self.mesh, combined):
            raise ValueError('IPC-опыт: исходная сетка после размещения пересекается')
        # Вершины пары получают одинаковое перемещение от контактной поправки.
        parent = np.arange(self.n)
        if len(shell):
            parent[shell[:, 1]] = shell[:, 0]
        _roots, self.groups = np.unique(parent, return_inverse=True)
        self.members = [np.flatnonzero(self.groups == i) for i in range(len(_roots))]
        self.calls = self.local_hits = self.fallbacks = self.blocked = 0
        self.minimum_alpha = 1.0

    def _local_correct(self, old, new, free, candidates, alpha):
        """Обработать кандидатов около первого момента столкновения."""
        at_time = min(1., alpha * 1.01 + 1e-4)
        at = old + (new - old) * at_time
        movement = new - old
        dt = max(0., at_time - alpha)
        fv, ee = candidates.fv_candidates, candidates.ee_candidates
        fa = np.asarray([(c.face_id, c.vertex_id) for c in fv], dtype=int).reshape(-1, 2)
        ea = np.asarray([(c.edge0_id, c.edge1_id) for c in ee], dtype=int).reshape(-1, 2)
        selected = []
        if len(fa):
            ids = self.faces[fa[:, 0]]
            tri, points = at[ids], at[fa[:, 1]]
            pad = .002 + dt * (np.linalg.norm(movement[fa[:, 1]], axis=1)
                                 + np.linalg.norm(movement[ids], axis=2).max(axis=1))
            mask = np.all((points >= tri.min(axis=1) - pad[:, None])
                          & (points <= tri.max(axis=1) + pad[:, None]), axis=1)
            selected.extend(fv[i] for i in np.flatnonzero(mask))
        if len(ea):
            ids_a, ids_b = self.edges[ea[:, 0]], self.edges[ea[:, 1]]
            aa, bb = at[ids_a], at[ids_b]
            pad = .002 + dt * (np.linalg.norm(movement[ids_a], axis=2).max(axis=1)
                                 + np.linalg.norm(movement[ids_b], axis=2).max(axis=1))
            mask = np.all((aa.max(axis=1) + pad[:, None] >= bb.min(axis=1))
                          & (bb.max(axis=1) + pad[:, None] >= aa.min(axis=1)), axis=1)
            selected.extend(ee[i] for i in np.flatnonzero(mask))
        hits = 0
        for candidate in selected:
            ids = np.asarray(candidate.vertex_ids(self.edges, self.faces)[:candidate.num_vertices()], dtype=int)
            x0, x1 = old[ids].ravel().copy(), new[ids].ravel().copy()
            hit, toi = candidate.ccd(x0, x1, 0.)
            if not hit or toi > min(1., alpha + .05):
                continue
            hits += 1
            t = max(0., min(1., toi - .0001))
            xt = x0 + (x1 - x0) * t
            coeff = np.asarray(candidate.compute_coefficients(xt)).reshape(-1)
            vec = np.asarray(candidate.compute_distance_vector(xt)).reshape(-1)
            norm = np.linalg.norm(vec)
            if norm < 1e-10:
                xt = x0 + (x1 - x0) * max(0., toi * .5)
                coeff = np.asarray(candidate.compute_coefficients(xt)).reshape(-1)
                vec = np.asarray(candidate.compute_distance_vector(xt)).reshape(-1)
                norm = np.linalg.norm(vec)
            if norm < 1e-12:
                self.blocked += 1
                continue
            normal = vec / norm
            start = float(np.dot(coeff @ old[ids], normal))
            target = min(.001, max(0., start) * .2)
            depth = target - float(np.dot(coeff @ new[ids], normal))
            if depth <= 0:
                continue
            active = ids < self.n
            dynamic, weights = ids[active], coeff[active]
            groups = self.groups[dynamic]
            unique = np.unique(groups)
            local = np.asarray([weights[groups == group].sum() for group in unique])
            invmass = np.asarray([float(np.all(free[self.members[g]])) / len(self.members[g])
                                  for g in unique])
            denominator = float(np.dot(local * local, invmass))
            if denominator < 1e-12:
                self.blocked += 1
                continue
            correction = normal * (depth * 1.01 / denominator)
            if self.friction > 0 and np.any(~active):
                relative = coeff @ (new[ids] - old[ids])
                tangent = relative - normal * np.dot(relative, normal)
                length = np.linalg.norm(tangent)
                if length > 1e-12:
                    correction -= tangent / denominator * min(1., self.friction * depth / length)
            for group, weight, inverse in zip(unique, local, invmass):
                if inverse:
                    new[self.members[group]] += correction * (weight * inverse)
        self.local_hits += hits
        return hits

    def project(self, previous, position, free):
        """Изменяет свободные узлы пробного шага; закрепления не двигаются."""
        previous = np.asarray(previous, dtype=float)
        free = np.asarray(free, dtype=bool)
        if previous.shape != (self.n, 3) or position.shape != previous.shape or free.shape != (self.n,):
            raise ValueError('IPC-опыт: несовместимая форма входа')
        self.calls += 1
        old = np.vstack((previous, self.static))
        new = np.vstack((position, self.static))
        new[:self.n][~free] = previous[~free]
        for _ in range(self.rounds):
            candidates = self.ipctk.Candidates()
            candidates.build(self.mesh, old, new, 0.)
            alpha = float(candidates.compute_collision_free_stepsize(self.mesh, old, new, 0.))
            if alpha >= 1.:
                position[:] = new[:self.n]
                return
            if not self._local_correct(old, new, free, candidates, alpha):
                break
        alpha = float(self.ipctk.compute_collision_free_stepsize(self.mesh, old, new, 0.))
        self.minimum_alpha = min(self.minimum_alpha, alpha)
        if alpha < 1.:
            new = old + (new - old) * max(0., alpha * .95)
            self.fallbacks += 1
        position[:] = new[:self.n]

    def stats(self):
        return {'calls': self.calls, 'local_hits': self.local_hits, 'fallbacks': self.fallbacks,
                'blocked': self.blocked, 'minimum_fallback_alpha': self.minimum_alpha}


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('Пробный решатель нужно адаптировать к изменившемуся исходнику')
    return source.replace(old, new, 1)


def run_case(name, *, gravity_scale=1., iterations_scale=1., steps_scale=1., rounds=3):
    original_factory = six._instrumented_solver
    experiment = {}

    def factory(mode, state, with_ccd):
        code = inspect.getsource(cloth.simulate)
        code = _replace_once(code, '    started = time.perf_counter()\n    vertices = np.asarray(vertices, dtype=np.float64)',
                             f'    g *= {gravity_scale!r}\n    iterations = max(1, int(iterations * {iterations_scale!r}))\n'
                             f'    steps = max(1, int(steps * {steps_scale!r}))\n'
                             '    started = time.perf_counter()\n    vertices = np.asarray(vertices, dtype=np.float64)')
        code = _replace_once(code, '    previous = position.copy()\n    contacts = 0',
                             '    _ipc_setup(position, vertices, faces, shell, components, gravity, supports, field, offset, friction)\n'
                             '    previous = position.copy()\n    contacts = 0')
        code = _replace_once(code, '        if not np.all(np.isfinite(position)) or',
                             '        _ipc_project(previous, position, free, support_contact)\n'
                             '        if not np.all(np.isfinite(position)) or')
        # Штатная диагностика независимо проверит отрезок после нашей поправки.
        get_source = inspect.getsource
        inspect.getsource = lambda item: code if item is cloth.simulate else get_source(item)
        try:
            solver = original_factory(mode, state, with_ccd)
        finally:
            inspect.getsource = get_source

        def setup(position, vertices, faces, shell, components, gravity, supports, field, offset, friction):
            experiment['ipc'] = IPCContactProbe(position, faces, shell, supports,
                                                friction=friction, rounds=rounds)
            experiment['direct'] = TriangleSupportProbe(field, faces, shell)
            experiment['both'] = SupportContactProbe(vertices, faces, shell, components, gravity, supports, offset)
            experiment['shell'] = shell
            experiment['faces'] = faces
            normals = cloth.vertex_normals(vertices, faces)
            a, b = shell[:, 0], shell[:, 1]
            direction = normals[a] - normals[b]
            direction /= np.maximum(np.linalg.norm(direction, axis=1), 1e-12)[:, None]
            delta = vertices[b] - vertices[a]
            height = np.einsum('ij,ij->i', delta, direction)
            tangent = np.linalg.norm(delta - height[:, None] * direction, axis=1)
            experiment['wall'] = (height, tangent)

        def project(previous, position, free, anchored):
            experiment['both'].project(previous, position, free, anchored, rounds=2)
            experiment['direct'].project(position, free, rounds=2)
            shell, faces = experiment['shell'], experiment['faces']
            height, tangent_length = experiment['wall']
            a, b = shell[:, 0], shell[:, 1]
            for _ in range(3):
                normals = cloth.vertex_normals(position, faces)
                direction = normals[a] - normals[b]
                norm = np.linalg.norm(direction, axis=1)
                direction /= np.maximum(norm, 1e-12)[:, None]
                delta = position[b] - position[a]
                along = np.einsum('ij,ij->i', delta, direction)
                tangent = delta - along[:, None] * direction
                length = np.linalg.norm(tangent, axis=1)
                target = direction * height[:, None] + tangent * (tangent_length / np.maximum(length, 1e-12))[:, None]
                bad = (norm < 1e-12) | ((length < 1e-12) & (tangent_length > 1e-12))
                target[bad] = delta[bad]
                correction = delta - target
                wa = (free[a] & ~anchored[a]).astype(float)
                wb = (free[b] & ~anchored[b]).astype(float)
                # Безопаснее не двигать закреплённые контактные пары, чем
                # произвольно выталкивать одну сторону через опору.
                total = np.maximum(wa + wb, 1.)
                position[a] += correction * (wa / total)[:, None]
                position[b] -= correction * (wb / total)[:, None]
            experiment['direct'].project(position, free, rounds=2)
            experiment['ipc'].project(previous, position, free)
            if state['frames'] and state['frames'] % 10 == 0:
                print(f"{name}: шаг {state['frames']}, откатов {experiment['ipc'].fallbacks}", file=sys.stderr, flush=True)

        solver.__globals__.update(_ipc_setup=setup, _ipc_project=project)
        return solver

    six._instrumented_solver = factory
    try:
        report = six.run_case(name, with_fcl=True, with_ccd=True, check_glb=True)
    finally:
        six._instrumented_solver = original_factory
    report['ipc_contact_experiment'] = {
        'gravity_scale': gravity_scale, 'iterations_scale': iterations_scale, 'steps_scale': steps_scale,
        'rounds': rounds, 'stats': experiment['ipc'].stats(),
        'note': 'Исследовательский контакт: не приложение, не гарантия толщины и равновесия.',
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=list(six.CASES))
    parser.add_argument('--gravity-scale', type=float, default=1.)
    parser.add_argument('--iterations-scale', type=float, default=1.)
    parser.add_argument('--steps-scale', type=float, default=1.)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not (0 < args.gravity_scale <= 2 and 0 < args.iterations_scale <= 4 and
            0 < args.steps_scale <= 2 and 1 <= args.rounds <= 8):
        parser.error('Параметры опыта вне ограниченного диапазона')
    report = run_case(args.case, gravity_scale=args.gravity_scale, iterations_scale=args.iterations_scale,
                      steps_scale=args.steps_scale, rounds=args.rounds)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
