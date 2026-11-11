"""Опыт двустороннего контакта ткани с опорой; не часть решателя приложения.

В существующей сцене проверяет также вершины опоры против граней движущихся
деталей. Это не полный контакт ребро—ребро, не гарантия безопасности и не
проверка равновесия. Обычная команда drape не изменяется.

Из корня репозитория:
OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python forma/tools/drape_support_probe.py --ccd
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
from forma.cloth_collision import SurfaceContacts  # noqa: E402
from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402
from audit_drape_sleeve import _fcl_audit, _fcl_object  # noqa: E402
from drape_mujoco_probe import TrajectoryAudit  # noqa: E402
from drape_shear_probe import _check_ccd, _replace_once  # noqa: E402


class _SupportPairs(SurfaceContacts):
    """Кандидаты только между динамической сеткой и неподвижной опорой."""

    def candidates(self, previous, current):
        owners, faces = super().candidates(previous, current)
        face_vertices = self.faces[faces, 0]
        keep = (owners < self.dynamic_count) != (face_vertices < self.dynamic_count)
        return owners[keep], faces[keep]


class SupportContactProbe:
    """Исследовательская коррекция вершина—грань в обоих направлениях."""

    def __init__(self, vertices, faces, shell, components, gravity, supports, offset):
        vertices = np.asarray(vertices, dtype=float)
        faces = np.asarray(faces, dtype=np.int64)
        triangles = np.asarray(supports, dtype=float).reshape(-1, 3, 3)
        if not len(vertices) or not len(faces) or not len(triangles):
            raise ValueError('Для опыта нужны детали и треугольники опор')
        if not np.all(np.isfinite(vertices)) or not np.all(np.isfinite(triangles)):
            raise ValueError('Координаты опыта должны быть конечными')
        static, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
        self.static = static
        self.static_faces = inverse.reshape(-1, 3).astype(np.int64)
        self.count = len(vertices)
        combined_vertices = np.vstack((vertices, static))
        combined_faces = np.vstack((faces, self.static_faces + self.count))
        labels = np.r_[components, np.full(len(static), int(np.max(components)) + 1)]
        self.collider = _SupportPairs(combined_vertices, combined_faces, shell,
                                      max(float(offset), .02), labels, -np.asarray(gravity))
        self.collider.dynamic_count = self.count
        self.passes = 0
        self.max_contacts = 0

    def project(self, previous, position, free, anchored, rounds=6):
        """Изменить только свободные вершины детали, но не вершины опор."""
        old = np.vstack((previous, self.static))
        current = np.vstack((position, self.static))
        movable = np.r_[free, np.zeros(len(self.static), dtype=bool)]
        fixed = np.r_[anchored, np.ones(len(self.static), dtype=bool)]
        count, depth = self.collider.project(old, current, movable, fixed, rounds=rounds)
        position[:] = current[:self.count]
        self.passes += 1
        self.max_contacts = max(self.max_contacts, count)
        return count, depth


def _fcl_checks(first, second, supports):
    """Независимый конечный тест поверхностей; касание тоже считается контактом."""
    try:
        import fcl
    except ImportError:
        return {'available': False}

    def obj(solid):
        return _fcl_object(fcl, *manifold_mesh(solid))

    def hit(a, b):
        result = fcl.CollisionResult()
        return bool(fcl.collide(a, b, fcl.CollisionRequest(num_max_contacts=1), result))

    low, high = obj(first), obj(second)
    models = [(name, obj(solid)) for name, solid in supports]
    vertices, faces, offset = [], [], 0
    for _name, solid in supports:
        v, f = manifold_mesh(solid)
        vertices.append(v)
        faces.append(f + offset)
        offset += len(v)
    combined = np.vstack(vertices), np.vstack(faces)
    return {'available': True, 'between_layers': hit(low, high),
            'against_supports': {'first': {name: hit(low, model) for name, model in models},
                                 'second': {name: hit(high, model) for name, model in models}},
            'self': {'first': _fcl_audit(*manifold_mesh(first), combined),
                     'second': _fcl_audit(*manifold_mesh(second), combined)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps', type=int, default=55)
    parser.add_argument('--interval', type=int, default=7,
                        help='дополнительный проход каждые N итераций, 0 — только в конце шага')
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--g', type=float, help='переопределить нагрузку сцены')
    parser.add_argument('--constraints', type=int, help='переопределить итерации ограничений сцены')
    parser.add_argument('--damping', type=float, help='переопределить сохранение скорости сцены')
    parser.add_argument('--ccd', action='store_true', help='независимая CCD линейных отрезков')
    parser.add_argument('--ccd-min-distance', type=float, default=.005, help='проверяемый зазор, мм')
    parser.add_argument('--ccd-failure', help='сохранить нарушенный отрезок в NPZ')
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000 or args.interval < 0 or args.rounds < 1:
        raise SystemExit('Некорректные шаги, интервал или число проходов')
    if args.g is not None and (not np.isfinite(args.g) or not 0 <= args.g <= 20):
        raise SystemExit('Нагрузка должна быть конечной и в диапазоне 0…20')
    if args.constraints is not None and not 1 <= args.constraints <= 64:
        raise SystemExit('Число итераций ограничений должно быть от 1 до 64')
    if args.damping is not None and (not np.isfinite(args.damping) or not 0 <= args.damping <= 1):
        raise SystemExit('Сохранение скорости должно быть конечным и в диапазоне 0…1')
    if not np.isfinite(args.ccd_min_distance) or args.ccd_min_distance < 0:
        raise SystemExit('Зазор CCD должен быть конечным и неотрицательным')
    if args.ccd_failure and (not args.ccd or not args.ccd_failure.endswith('.npz')):
        raise SystemExit('Файл отказа CCD требует --ccd и расширение .npz')

    state = {}

    def setup(vertices, faces, shell, components, gravity, supports, offset):
        state['probe'] = SupportContactProbe(vertices, faces, shell, components, gravity, supports, offset)

    def project(previous, position, free, anchored):
        state['probe'].project(previous, position, free, anchored, rounds=args.rounds)

    def ccd_init(position, faces):
        probe = state['probe']
        state['ccd'] = TrajectoryAudit(position, faces, {'опоры': (probe.static, probe.static_faces)},
                                       min_distance=args.ccd_min_distance)

    def ccd_step(position):
        _check_ccd(state['ccd'], position, args.ccd_failure)

    code = inspect.getsource(cloth.simulate)
    code = _replace_once(code, '    previous = position.copy()\n    contacts = 0',
                         '    _support_probe_setup(vertices, faces, shell, components, gravity, supports, offset)\n'
                         + ('    _support_probe_ccd_init(position, faces)\n' if args.ccd else '')
                         + '    previous = position.copy()\n    contacts = 0')
    if args.interval:
        code = _replace_once(code, '            position[pinned] = fixed\n\n        if friction > 0',
                             f'            if (it + 1) % {args.interval} == 0:\n'
                             '                _support_probe_project(previous, position, free, support_contact)\n'
                             '            position[pinned] = fixed\n\n        if friction > 0')
    code = _replace_once(code, '        if not np.all(np.isfinite(position)) or',
                         '        _support_probe_project(previous, position, free, support_contact)\n'
                         + ('        _support_probe_ccd_step(position)\n' if args.ccd else '')
                         + '        if not np.all(np.isfinite(position)) or')
    original = cloth.simulate
    cloth._support_probe_setup, cloth._support_probe_project = setup, project
    cloth._support_probe_ccd_init, cloth._support_probe_ccd_step = ccd_init, ccd_step
    try:
        exec(compile(code, '<drape support probe>', 'exec'), cloth.__dict__)
        path = ROOT / 'examples' / 'drape_layers_076.forma'
        text = path.read_text(encoding='utf-8')
        marker = '# Полая трубка'
        if text.count(marker) != 1:
            raise RuntimeError('В примере не найдено начало отдельного случая рукава')
        source = text.split(marker)[0]
        source = _replace_once(source, 'steps=55', f'steps={args.steps}')
        overrides = []
        if args.g is not None:
            overrides.append(f'g={args.g}')
        if args.constraints is not None:
            overrides.append(f'constraints={args.constraints}')
        if args.damping is not None:
            overrides.append(f'damping={args.damping}')
        if overrides:
            source = _replace_once(source, 'bend=0.15 self=да',
                                   'bend=0.15 ' + ' '.join(overrides) + ' self=да')
        started = time.perf_counter()
        result = build(source, analyze_model=False, base_dir=path.parent)
    finally:
        cloth.simulate = original
        del cloth._support_probe_setup, cloth._support_probe_project
        del cloth._support_probe_ccd_init, cloth._support_probe_ccd_step
    if not result.ok:
        raise RuntimeError(f'Сцена не собралась: {result.error}')
    scene = result.scene
    first, second = scene.objects['слои'].manifold, scene.objects['слои.02'].manifold
    supports = [(name, scene.objects[name].manifold) for name in ('площадка', 'бугор')]
    probe = state['probe']
    report = {'arguments': vars(args), 'elapsed_seconds': round(time.perf_counter() - started, 3),
              'passes': probe.passes, 'max_contacts': probe.max_contacts,
              'parts_overlap_volume': float((first ^ second).volume()),
              'support_overlap_volumes': {name: float((first ^ support).volume())
                                          for name, support in supports},
              'fcl': _fcl_checks(first, second, supports),
              'trajectory_ccd': ({'steps': state['ccd'].steps, 'min_distance_mm': state['ccd'].min_distance,
                                  'seconds': round(state['ccd'].seconds, 3),
                                  'note': 'Только линейные отрезки после размещения; внутренние '
                                          'проекции и соседние примитивы не проверяются.'}
                                 if args.ccd else None),
              'metadata': scene.objects['слои'].meta['cloth'],
              'note': 'Эксперимент, не проверенное равновесие и не готовые детали.'}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
