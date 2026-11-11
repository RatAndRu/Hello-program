"""Маленькая изолированная проверка ограничений pypbd, не решатель Формы.

Проверяются одно ребро с закреплённой вершиной и один тетраэдр с тремя
закреплёнными вершинами. Нет ткани, опор, трения, самоконтакта или проверки
Windows EXE. Пример: timeout 20s python tools/drape_pbd_constraints_probe.py
--output pbd-constraints.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.metadata
import json
from pathlib import Path
import platform
import sys


class _BlockRendering(importlib.abc.MetaPathFinder):
    """Проверить эти две операции без импортов pygame и PyOpenGL."""
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('pygame', 'OpenGL') or fullname.startswith(('pygame.', 'OpenGL.')):
            raise ModuleNotFoundError('Тест заблокировал импорт ' + fullname)
        return None


def inspect_constraints():
    blocker = _BlockRendering()
    sys.meta_path.insert(0, blocker)
    try:
        import pypbd as pbd
        model = pbd.SimulationModel()
        model.init()
        particles = model.getParticles()
        particles.addVertex([0., 0., 0.])
        particles.addVertex([1., 0., 0.])
        particles.setMass(0, 0.)
        particles.setMass(1, 1.)
        added = bool(model.addDistanceConstraint(0, 1, 1.))
        particles.setPosition(1, [2., 0., 0.])
        before = [particles.getPosition(i).tolist() for i in range(2)]
        result = bool(model.getConstraints()[0].solvePositionConstraint(model, 0))
        after = [particles.getPosition(i).tolist() for i in range(2)]

        solid = pbd.SimulationModel()
        solid.init()
        vertices = solid.getParticles()
        for point in ([0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]):
            vertices.addVertex(point)
        for i in range(3):
            vertices.setMass(i, 0.)
        vertices.setMass(3, 1.)
        volume_added = bool(solid.addVolumeConstraint(0, 1, 2, 3, 1.))
        vertices.setPosition(3, [0., 0., .2])
        volume_constraint = solid.getConstraints()[0]
        rest_volume = float(volume_constraint.restVolume)
        samples = {}
        for step in range(20):
            if not volume_constraint.solvePositionConstraint(solid, step):
                raise RuntimeError('PBD не решил объёмное ограничение')
            if step in (0, 1, 4, 9, 19):
                samples[str(step + 1)] = vertices.getPosition(3).tolist()
        fixed = [vertices.getPosition(i).tolist() for i in range(3)]
        return {
            'python': platform.python_version(), 'platform': platform.platform(),
            'pypbd_version': importlib.metadata.version('pypbd'),
            'numpy_version': importlib.metadata.version('numpy'),
            'rendering_imports_blocked': ['pygame', 'OpenGL'],
            'distance': {'constraint_added': added, 'solved': result,
                         'before': before, 'after': after},
            'tetrahedron': {'constraint_added': volume_added, 'rest_volume': rest_volume,
                            'compressed_vertex_initial': [0., 0., .2],
                            'compressed_vertex_by_iteration': samples, 'fixed_vertices_after': fixed},
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'note': ('Только две операции над двумя узлами и одним тетраэдром. '
                     'Реальная ткань, столкновения, сохранение толщины, трение и EXE не проверены.'),
        }
    finally:
        sys.meta_path.remove(blocker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix.lower() != '.json':
        parser.error('Укажите путь .json')
    result = inspect_constraints()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')


if __name__ == '__main__':
    main()
