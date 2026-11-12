"""Открыть шесть .forma через API указанного EXE и повторно прочитать GLB.

Проверяется загрузка и полигонаж, а не отсутствие физических дефектов ткани.
Без --exe можно проверить тот же путь на исходниках (требуются зависимости).
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

import trimesh

ROOT = Path(__file__).resolve().parent.parent
SUPPORTS = {'пол', 'столешница', 'ножка_левая_передняя', 'ножка_правая_передняя',
            'ножка_левая_задняя', 'ножка_правая_задняя'}
CASES = [
    ('01_sheet_over_ball', ROOT / 'benchmarks/drape_six/01_sheet_over_ball.forma', {'площадка', 'шар', 'результат'}),
    ('02_sheet_over_sheet', ROOT / 'benchmarks/drape_six/02_sheet_over_sheet.forma', {'площадка', 'результат'}),
    ('03_soft_sphere', ROOT / 'benchmarks/drape_six/03_soft_sphere.forma', {'площадка', 'результат'}),
    ('04_tablecloth', ROOT / 'examples/drape_tablecloth_fast_076.forma', SUPPORTS | {'скатерть'}),
    ('05_sleeve', ROOT / 'benchmarks/drape_six/05_sleeve.forma', {'площадка', 'результат'}),
    ('06_sleeve_around_rod', ROOT / 'benchmarks/drape_six/06_sleeve_around_rod.forma', {'площадка', 'стержень', 'результат'}),
]


def run(exe: Path | None):
    from forma.version import __version__

    with tempfile.TemporaryDirectory() as temp:
        projects = Path(temp) / 'projects'
        projects.mkdir()
        for name, source, _expected in CASES:
            shutil.copyfile(source, projects / (name + '.forma'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = 'drape-six-local-check'
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, FORMA_DATA=temp, FORMA_DOWNLOADS=str(Path(temp) / 'downloads'),
                   FORMA_TOKEN=token, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        command = [str(exe.resolve())] if exe else [sys.executable, str(ROOT / 'run_forma.py')]
        process = subprocess.Popen(command + ['--no-open', '--port', str(port)], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f'Приложение завершилось до запуска API: {process.returncode}')
                try:
                    with urlopen(base + '/api/state?token=' + token, timeout=2) as response:
                        state = json.load(response)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Приложение не запустило API за 120 секунд')
                    time.sleep(.5)
            if state.get('version') != __version__:
                raise RuntimeError(f"Версия приложения {state.get('version')} вместо {__version__}")
            measurements = []
            for name, source, expected in CASES:
                with urlopen(base + '/api/project?name=' + name + '&token=' + token, timeout=20) as response:
                    project = json.load(response)
                script = source.read_text(encoding='utf-8')
                if project.get('script') != script:
                    raise RuntimeError(f'{name}: проект загрузился с другим содержимым')
                data = json.dumps({'script': script, 'auto': False}, ensure_ascii=False).encode('utf-8')
                request = Request(base + '/api/build?token=' + token, data=data,
                                  headers={'Content-Type': 'application/json'})
                started = time.perf_counter()
                with urlopen(request, timeout=300) as response:
                    payload = json.load(response)
                if not payload.get('ok') or payload.get('paused'):
                    raise RuntimeError(f"{name}: ошибка сборки: {payload.get('error')}")
                visible = {item['name'] for item in payload['objects'] if item['visible']}
                if visible != expected:
                    raise RuntimeError(f'{name}: объекты {visible}, ожидались {expected}')
                triangles = sum(item['tris'] for item in payload['objects'] if item['visible'])
                with urlopen(base + payload['glb_url'] + '&token=' + token, timeout=120) as response:
                    glb = response.read()
                scene = trimesh.load(io.BytesIO(glb), file_type='glb', force='scene', process=False)
                glb_tris = sum(len(mesh.faces) for mesh in scene.geometry.values())
                if triangles != glb_tris or not 0 < triangles <= 100_000:
                    raise RuntimeError(f'{name}: треугольники UI {triangles}, GLB {glb_tris}')
                result = {'name': name, 'triangles': triangles, 'glb_bytes': len(glb),
                          'seconds': round(time.perf_counter() - started, 2)}
                measurements.append(result)
                print(f"{name}: проект и GLB, {triangles} трис, {result['seconds']} с", flush=True)
            return measurements
        finally:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    measurements = run(args.exe)
    args.output.write_text(json.dumps(measurements, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
