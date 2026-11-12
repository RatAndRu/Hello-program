"""Опыт чередования контактных и геометрических ограничений drape.

НЕ часть приложения и НЕ готовый инструмент: IPC здесь проверяет только
линейный отрезок от начала к концу временного шага после размещения. Внутренние
проекции, полное сохранение толщины, силы, трение и равновесие не доказаны.
В приложении никаких зависимостей или параметров этот файл не меняет.

Пример (из корня репозитория; окружение с ipctk и python-fcl):

  timeout 180s env OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python \
    forma/tools/drape_ipc_relaxation_probe.py --case 01_sheet_over_ball \
    --rounds 4 --passes 2 --sweeps 12 --output ball.json
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import cloth  # noqa: E402
import drape_six_probe as six  # noqa: E402
from drape_bounded_probe import _environment  # noqa: E402
from drape_ipc_contact_probe import IPCContactProbe, _replace_once  # noqa: E402


class AlternatingProjector:
    """Пробная контактная защита + проходы длины рёбер и найденных пар стенки.

    Сначала делает предложенный штатным решателем шаг допустимым для IPC,
    затем чередует фиксированное число геометрических и контактных проходов.
    Последним всегда выполняется IPC. В примере штатное трение остаётся без
    изменений; дополнительное приближённое IPC-трение выключено.
    """

    def __init__(self, position, reference, faces, shell, supports, *,
                 rounds=4, passes=2, sweeps=12):
        position = np.asarray(position, dtype=float)
        reference = np.asarray(reference, dtype=float)
        faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
        shell = np.asarray(shell, dtype=np.int64).reshape(-1, 2)
        if position.shape != reference.shape or reference.ndim != 2 or reference.shape[1] != 3:
            raise ValueError('Исходные и текущие вершины должны иметь форму (N, 3)')
        if not (1 <= int(rounds) <= 8 and 0 <= int(passes) <= 3 and 1 <= int(sweeps) <= 64):
            raise ValueError('Число проходов опыта вне диапазона')
        self.ipc = IPCContactProbe(position, faces, shell, supports, friction=0., rounds=rounds)
        self.passes, self.sweeps = int(passes), int(sweeps)
        self.reference = reference.copy()
        self.faces, self.shell = faces.copy(), shell.copy()
        self.edges = cloth._edge_arrays(faces)
        self.colors = cloth._edge_colors(self.edges, len(reference))
        self.rest = np.linalg.norm(reference[self.edges[:, 1]] - reference[self.edges[:, 0]], axis=1)
        if np.any(self.rest <= 1e-12):
            raise ValueError('Опыт не поддерживает исходные рёбра нулевой длины')
        normals = cloth.vertex_normals(reference, faces)
        a, b = shell[:, 0], shell[:, 1]
        direction = normals[a] - normals[b]
        direction /= np.maximum(np.linalg.norm(direction, axis=1), 1e-12)[:, None]
        delta = reference[b] - reference[a]
        self.wall_height = np.einsum('ij,ij->i', delta, direction)
        tangent = delta - self.wall_height[:, None] * direction
        self.wall_tangent = np.linalg.norm(tangent, axis=1)
        self.shape_passes = 0

    def _shape_pass(self, position, free):
        """Частичная геометрическая проекция; отдельно НЕ обеспечивает контакт."""
        for iteration in range(self.sweeps):
            groups = self.colors if iteration % 2 == 0 else reversed(self.colors)
            for group in groups:
                a, b = self.edges[group, 0], self.edges[group, 1]
                delta = position[b] - position[a]
                length = np.maximum(np.linalg.norm(delta, axis=1), 1e-12)
                wa, wb = free[a].astype(float), free[b].astype(float)
                share = ((length - self.rest[group]) /
                         (length * np.maximum(wa + wb, 1.)))[:, None]
                correction = delta * share
                position[a] += correction * wa[:, None]
                position[b] -= correction * wb[:, None]
            if not len(self.shell):
                continue
            a, b = self.shell[:, 0], self.shell[:, 1]
            normals = cloth.vertex_normals(position, self.faces)
            direction = normals[a] - normals[b]
            norm = np.linalg.norm(direction, axis=1)
            direction /= np.maximum(norm, 1e-12)[:, None]
            delta = position[b] - position[a]
            height = np.einsum('ij,ij->i', delta, direction)
            tangent = delta - height[:, None] * direction
            tangent_length = np.linalg.norm(tangent, axis=1)
            target = (direction * self.wall_height[:, None]
                      + tangent * (self.wall_tangent / np.maximum(tangent_length, 1e-12))[:, None])
            correction = delta - target
            correction[norm < 1e-12] = 0.
            ambiguous = (tangent_length < 1e-12) & (self.wall_tangent > 1e-12)
            correction[ambiguous] = ((height[ambiguous] - self.wall_height[ambiguous])[:, None]
                                     * direction[ambiguous])
            wa, wb = free[a].astype(float), free[b].astype(float)
            total = np.maximum(wa + wb, 1.)
            # IPCContactProbe уже проверил непересечение пар, поэтому каждая
            # вершина попадает в этот векторный проход не более одного раза.
            position[a] += correction * (wa / total)[:, None]
            position[b] -= correction * (wb / total)[:, None]
        self.shape_passes += 1

    def project(self, previous, position, free):
        if position.shape != self.reference.shape or np.shape(previous) != position.shape:
            raise ValueError('Неверная форма положения в опыте')
        free = np.asarray(free, dtype=bool)
        if free.shape != (len(position),):
            raise ValueError('Неверная форма признака закрепления')
        self.ipc.project(previous, position, free)
        for _ in range(self.passes):
            self._shape_pass(position, free)
            self.ipc.project(previous, position, free)

    def stats(self):
        return {'rounds': self.ipc.rounds, 'passes': self.passes, 'sweeps': self.sweeps,
                'shape_passes': self.shape_passes, 'extra_ipc_friction': 0.,
                'ipc': self.ipc.stats()}


def run_case(name, *, rounds=4, passes=2, sweeps=12, bend_scale=1., steps_scale=1.):
    """Запустить копию штатного решателя с исследовательской поправкой."""
    if not (0. <= bend_scale <= 1. and 1. <= steps_scale <= 2.):
        raise ValueError('Масштаб изгиба должен быть 0…1, числа шагов — 1…2')
    original_factory = six._instrumented_solver
    experiment = {}

    def factory(mode, state, with_ccd):
        code = inspect.getsource(cloth.simulate)
        code = _replace_once(code, '    started = time.perf_counter()\n',
                             f'    bend *= {bend_scale!r}\n'
                             f'    steps = max(1, int(steps * {steps_scale!r}))\n'
                             '    started = time.perf_counter()\n')
        code = _replace_once(code, '    previous = position.copy()\n    contacts = 0',
                             '    _alternating_setup(position, vertices, faces, shell, supports)\n'
                             '    previous = position.copy()\n    contacts = 0')
        code = _replace_once(code, '        if not np.all(np.isfinite(position)) or',
                             '        _alternating_project(previous, position, free)\n'
                             '        if not np.all(np.isfinite(position)) or')
        get_source = inspect.getsource
        inspect.getsource = lambda item: code if item is cloth.simulate else get_source(item)
        try:
            solver = original_factory(mode, state, with_ccd)
        finally:
            inspect.getsource = get_source

        def setup(position, vertices, faces, shell, supports):
            experiment['projector'] = AlternatingProjector(
                position, vertices, faces, shell, supports, rounds=rounds, passes=passes, sweeps=sweeps)

        def project(previous, position, free):
            probe = experiment['projector']
            probe.project(previous, position, free)
            calls = probe.ipc.calls
            if calls % (10 * (probe.passes + 1)) == 0:
                print(f'{name}: шаг {calls // (probe.passes + 1)}, '
                      f'общих откатов {probe.ipc.fallbacks}', file=sys.stderr, flush=True)

        solver.__globals__.update(_alternating_setup=setup, _alternating_project=project)
        return solver

    six._instrumented_solver = factory
    try:
        report = six.run_case(name, with_fcl=True, with_ccd=True, check_glb=True)
    finally:
        six._instrumented_solver = original_factory
    report['alternating_experiment'] = {
        'bend_scale': float(bend_scale), 'steps_scale': float(steps_scale),
        'stats': experiment['projector'].stats(),
        'note': ('Исследование, не приложение. Дополнительное IPC-трение выключено; '
                 'штатное трение сцены остаётся. CCD не проверяет внутренние проекции.')}
    environment = _environment()
    path = Path(__file__).resolve()
    environment['source_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['environment'] = environment
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=list(six.CASES), required=True)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--passes', type=int, default=2)
    parser.add_argument('--sweeps', type=int, default=12)
    parser.add_argument('--bend-scale', type=float, default=1.)
    parser.add_argument('--steps-scale', type=float, default=1.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not (1 <= args.rounds <= 8 and 0 <= args.passes <= 3 and 1 <= args.sweeps <= 64
            and 0. <= args.bend_scale <= 1. and 1. <= args.steps_scale <= 2.):
        parser.error('Параметры опыта вне ограниченного диапазона')
    if args.output.suffix.lower() != '.json':
        parser.error('Для результатов нужен файл .json')
    report = run_case(args.case, rounds=args.rounds, passes=args.passes, sweeps=args.sweeps,
                      bend_scale=args.bend_scale, steps_scale=args.steps_scale)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                           encoding='utf-8')
    print(f'{args.case}: опыт завершён, результат не является подтверждением готовности.', flush=True)


if __name__ == '__main__':
    main()
