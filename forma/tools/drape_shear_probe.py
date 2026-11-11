"""Эксперимент межслойных сдвиговых связей в отдельном процессе.

Связи создаются по найденным парным поверхностям конкретного стресс-рукава.
Их незаметная настройка не гарантирует отсутствие растяжения, пересечений или
равновесие; этот скрипт не меняет решатель приложения и не создаёт детали.

PYTHONPATH=forma python forma/tools/drape_shear_probe.py --steps 160
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


def build_shear_links(vertices, faces, shell):
    """Диагонали между двумя локально парными слоями; существующие рёбра не дублируются."""
    other = np.full(len(vertices), -1, dtype=np.int64)
    shell = np.asarray(shell, dtype=np.int64).reshape(-1, 2)
    if len(shell):
        if (np.any(shell < 0) or np.any(shell >= len(vertices)) or
                len(np.unique(shell)) != shell.size):
            raise ValueError('Сдвиговые связи требуют однозначных пар вершин стенки')
        other[shell[:, 0]] = shell[:, 1]
        other[shell[:, 1]] = shell[:, 0]
    edges = cloth._edge_arrays(faces)
    existing = {tuple(edge) for edge in edges.tolist()}
    links = set()
    for a, b in edges:
        if other[a] < 0 or other[b] < 0:
            continue
        for c, d in ((a, other[b]), (b, other[a])):
            link = tuple(sorted((int(c), int(d))))
            if c != d and link not in existing:
                links.add(link)
    return np.asarray(sorted(links), dtype=np.int64).reshape(-1, 2)


class ShearProjector:
    def __init__(self, vertices, links, strength=1., rounds=1):
        self.links = np.asarray(links, dtype=np.int64).reshape(-1, 2)
        self.rest = np.linalg.norm(vertices[self.links[:, 1]] - vertices[self.links[:, 0]], axis=1)
        self.colors = cloth._edge_colors(self.links, len(vertices)) if len(self.links) else []
        if not 0 < strength <= 1 or rounds < 1 or np.any(self.rest < 1e-12):
            raise ValueError('Некорректные параметры сдвиговых связей')
        self.strength, self.rounds = float(strength), int(rounds)

    def project(self, position, free):
        for turn in range(self.rounds):
            colors = self.colors if turn % 2 == 0 else reversed(self.colors)
            for group in colors:
                a, b = self.links[group, 0], self.links[group, 1]
                delta = position[b] - position[a]
                length = np.linalg.norm(delta, axis=1)
                wa, wb = free[a].astype(float), free[b].astype(float)
                ratio = ((length - self.rest[group]) * self.strength /
                         (np.maximum(length, 1e-12) * np.maximum(wa + wb, 1.)))[:, None]
                correction = delta * ratio
                position[a] += correction * wa[:, None]
                position[b] -= correction * wb[:, None]
        return position


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Контрольная точка в решателе не найдена однозначно: {old}')
    return text.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps', type=int, default=160)
    parser.add_argument('--strength', type=float, default=1.)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--g', type=float, default=.04)
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000:
        raise SystemExit('Число шагов должно быть от 1 до 1000')
    state = {}

    def setup(vertices, faces, shell):
        links = build_shear_links(vertices, faces, shell)
        state['projector'] = ShearProjector(vertices, links, args.strength, args.rounds)
        _surface, state['tets'], state['changed_faces'] = tetrahedral_shell('sleeve', vertices, faces)
        state['rest_volume'] = _signed_tetra_volumes(vertices, state['tets'])

    def project(position, free):
        return state['projector'].project(position, free)

    def record(position):
        ratio = _signed_tetra_volumes(position, state['tets']) / state['rest_volume']
        state['tetra'] = {'count': len(ratio), 'inverted': int(np.count_nonzero(ratio <= 0)),
                          'min_jacobian': float(ratio.min()), 'max_jacobian': float(ratio.max())}

    code = inspect.getsource(cloth.simulate)
    code = _replace_once(code, '    # --- степени частиц и индексы для общей поправки (метод Якоби) ---',
                         '    _probe_setup(vertices, faces, shell)\n'
                         '    # --- степени частиц и индексы для общей поправки (метод Якоби) ---')
    code = _replace_once(code, '            position[pinned] = fixed\n\n        if friction > 0',
                         '            position = _probe_project(position, free)\n'
                         '            position[pinned] = fixed\n\n        if friction > 0')
    code = _replace_once(code, '    final_lengths = np.linalg.norm',
                         '    _probe_record(position)\n    final_lengths = np.linalg.norm')
    original = cloth.simulate
    cloth._probe_setup, cloth._probe_project, cloth._probe_record = setup, project, record
    try:
        exec(compile(code, '<drape shear probe>', 'exec'), cloth.__dict__)
        path = ROOT / 'benchmarks' / 'drape_sleeve_stress_077.forma'
        source = _replace_once(path.read_text(encoding='utf-8'), 'steps=160', f'steps={args.steps}')
        source = _replace_once(source, 'g=0.04', f'g={args.g}')
        started = time.perf_counter()
        result = build(source, analyze_model=False, base_dir=path.parent)
    finally:
        cloth.simulate = original
        del cloth._probe_setup, cloth._probe_project, cloth._probe_record
    if not result.ok:
        raise RuntimeError(f'Стресс-сцена не собралась: {result.error}')
    body, initial = result.scene.objects['проверка'], result.scene.objects['рукав']
    vertices, faces = manifold_mesh(body.manifold)
    support = manifold_mesh(result.scene.objects['пол'].manifold)
    report = {'arguments': vars(args), 'elapsed_seconds': round(time.perf_counter() - started, 3),
              'shear_links': len(state['projector'].links), 'tetra': state['tetra'],
              'retriangulated_boundary_faces': state['changed_faces'],
              'bbox': list(body.manifold.bounding_box()),
              'volume_ratio': body.manifold.volume() / initial.manifold.volume(),
              'metadata': body.meta['cloth'], 'fcl': _fcl_audit(vertices, faces, support),
              'note': 'Эксперимент, не проверенное равновесие и не готовая деталь.'}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
