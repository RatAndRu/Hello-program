"""Шестисценная диагностика с жёстким лимитом времени и частичным отчётом.

Каждая сцена выполняется в отдельном процессе. При превышении лимита процесс
убивается, результат помечается timeout, уже готовые измерения сохраняются.
Это исследовательская проверка, не исправление drape и не доказательство
готовности модели. Пример:

  OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python forma/tools/drape_bounded_probe.py \
    --mode ipc --cases 04_tablecloth 01_sheet_over_ball --budget 180 --case-limit 85 \
    --gravity-scale .5 --iterations-scale 2 --output ipc-quick.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from drape_six_probe import CASES

TOOLS = Path(__file__).resolve().parent


def _environment():
    versions = {}
    for package in ('numpy', 'scipy', 'ipctk', 'manifold3d', 'trimesh', 'python-fcl'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    files = [TOOLS.parent / 'forma' / name for name in
             ('cloth.py', 'cloth_collision.py', 'cloth_check.py', 'cloth_remesh.py', 'ops_interior.py')]
    files += [TOOLS / name for name in ('drape_bounded_probe.py', 'drape_ipc_contact_probe.py',
                                        'drape_six_probe.py', 'drape_triangle_probe.py',
                                        'drape_support_probe.py', 'drape_mujoco_probe.py',
                                        'audit_drape_sleeve.py')]
    hashes = {str(path.relative_to(TOOLS.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in files}
    return {'python': platform.python_version(), 'platform': platform.platform(),
            'dependencies': versions, 'source_sha256': hashes}


def _save(output, report):
    temporary = output.with_name(output.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                         encoding='utf-8')
    temporary.replace(output)


def _invoke(name, timeout, *, mode, gravity_scale, iterations_scale, rounds):
    """Запустить процесс, дождаться либо завершения, либо принудительного таймаута."""
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    with tempfile.TemporaryDirectory(prefix='forma-drape-') as temp:
        result_path = Path(temp) / 'result.json'
        if mode == 'ipc':
            command = [sys.executable, str(TOOLS / 'drape_ipc_contact_probe.py'), '--case', name,
                       '--gravity-scale', str(gravity_scale), '--iterations-scale', str(iterations_scale),
                       '--rounds', str(rounds), '--output', str(result_path)]
        else:
            command = [sys.executable, str(TOOLS / 'drape_six_probe.py'), '--case', name,
                       '--mode', 'current', '--fcl', '--ccd', '--glb', '--output', str(result_path)]
        run = subprocess.run(command, cwd=TOOLS.parent, env=env, capture_output=True,
                             text=True, encoding='utf-8', errors='replace', timeout=timeout)
        if run.returncode:
            raise RuntimeError(f'код {run.returncode}: {(run.stderr or run.stdout)[-2500:]}')
        data = json.loads(result_path.read_text(encoding='utf-8'))
        if mode == 'current':
            data = data['cases'][0]
        if data['name'] != name:
            raise RuntimeError('Получен результат другого сценария')
        return data


def run_bounded(names, output, *, mode, budget, case_limit, gravity_scale=1.,
                iterations_scale=1., rounds=3, runner=_invoke):
    """Сохраняет статусы даже при таймауте отдельной сцены или общего бюджета."""
    report = {
        'mode': mode, 'budget_seconds': budget, 'case_limit_seconds': case_limit,
        'environment': _environment(),
        'parameters': {'gravity_scale': gravity_scale, 'iterations_scale': iterations_scale, 'rounds': rounds},
        'cases': [{'name': name, 'status': 'not_started'} for name in names],
        'note': ('completed означает только завершение расчёта, не прохождение критериев. '
                 'IPC-опыт не является частью приложения; CCD не проверяет внутренние проекции.'),
    }
    started = time.monotonic()
    _save(output, report)
    for slot, entry in enumerate(report['cases']):
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            break
        limit = min(case_limit, remaining)
        entry['status'] = 'running'
        entry['timeout_seconds'] = round(limit, 3)
        _save(output, report)
        print(f"{entry['name']}: запуск, лимит {limit:.1f} с", file=sys.stderr, flush=True)
        case_start = time.monotonic()
        try:
            result = runner(entry['name'], limit, mode=mode, gravity_scale=gravity_scale,
                            iterations_scale=iterations_scale, rounds=rounds)
            entry['status'] = 'completed'
            entry['result'] = result
        except subprocess.TimeoutExpired as exc:
            entry['status'] = 'timeout'
            entry['reason'] = 'Процесс остановлен по лимиту времени; итоги сцены отсутствуют.'
            tail = exc.stderr or exc.stdout or ''
            if isinstance(tail, bytes):
                tail = tail.decode('utf-8', errors='replace')
            if tail:
                entry['progress'] = tail[-2500:]
        except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            entry['status'] = 'error'
            entry['reason'] = str(exc)[-2500:]
        entry['elapsed_seconds'] = round(time.monotonic() - case_start, 3)
        print(f"{entry['name']}: {entry['status']} ({entry['elapsed_seconds']:.1f} с)",
              file=sys.stderr, flush=True)
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        _save(output, report)
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    report['all_completed'] = all(item['status'] == 'completed' for item in report['cases'])
    _save(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['current', 'ipc'], default='current')
    parser.add_argument('--cases', nargs='+', choices=list(CASES), default=list(CASES))
    parser.add_argument('--budget', type=float, default=300., help='общий лимит секунд, не больше 600')
    parser.add_argument('--case-limit', type=float, default=90., help='лимит секунд на сцену, не больше 180')
    parser.add_argument('--gravity-scale', type=float, default=1.)
    parser.add_argument('--iterations-scale', type=float, default=1.)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not (0 < args.budget <= 600 and 0 < args.case_limit <= 180):
        parser.error('Лимиты должны быть положительными: общий не более 600 с, на сцену не более 180 с')
    if not (0 < args.gravity_scale <= 2 and 0 < args.iterations_scale <= 4 and 1 <= args.rounds <= 8):
        parser.error('Параметры опыта вне допустимого диапазона')
    if args.mode == 'current' and (args.gravity_scale != 1. or args.iterations_scale != 1. or args.rounds != 3):
        parser.error('Масштаб нагрузки, итераций и rounds применимы только к --mode ipc')
    if args.output.suffix.lower() != '.json':
        parser.error('Для отчёта нужен файл .json')
    if len(args.cases) != len(set(args.cases)):
        parser.error('Каждый сценарий можно указать только один раз')
    report = run_bounded(args.cases, args.output, mode=args.mode, budget=args.budget,
                         case_limit=args.case_limit, gravity_scale=args.gravity_scale,
                         iterations_scale=args.iterations_scale, rounds=args.rounds)
    if not report['all_completed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
