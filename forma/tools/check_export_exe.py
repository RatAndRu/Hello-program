"""Проверка внешнего GLB, обратного импорта и материалов через API EXE.

Это проверка данных; визуальная идентичность разных рендереров не проверяется.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.request import Request, urlopen

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forma.geometry import _glb_read
from forma.version import __version__


def extents(data):
    scene = trimesh.load(io.BytesIO(data), file_type='glb', force='scene', process=False)
    return np.asarray(scene.bounds[1] - scene.bounds[0])


def run(exe: Path | None):
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = 'export-check-local'
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, FORMA_DATA=temp, FORMA_DOWNLOADS=str(Path(temp) / 'downloads'),
                   FORMA_TOKEN=token, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        command = [str(exe.resolve())] if exe else [sys.executable, str(ROOT / 'run_forma.py')]
        process = subprocess.Popen(command + ['--no-open', '--port', str(port)], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            def get(path):
                with urlopen(base + path + ('&' if '?' in path else '?') + 'token=' + token, timeout=120) as response:
                    return response.read()

            def post(path, body):
                req = Request(base + path + '?token=' + token,
                              data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                              headers={'Content-Type': 'application/json'})
                with urlopen(req, timeout=180) as response:
                    return json.load(response)

            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f'EXE завершился до запуска API: {process.returncode}')
                try:
                    state = json.loads(get('/api/state'))
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('API не запустился за 120 секунд')
                    time.sleep(.5)
            if state.get('version') != __version__:
                raise RuntimeError('Версия EXE не совпадает с исходниками')

            licenses = post('/api/licenses', {})
            with zipfile.ZipFile(Path(temp) / 'exports' / licenses['name']) as zf:
                names = set(zf.namelist())
                required = {'manifest.json', 'vendor/THREE_LICENSE.txt', 'vendor/NVIDIA-FXAA-BSD.txt',
                            'vendor/Microsoft-WebView2-SDK.txt', 'vendor/human_skeleton.LICENSE.txt',
                            'vendor/FastNoiseLite-MIT.txt', 'vendor/proxy-tools-BSD.txt'}
                if not required <= names:
                    raise RuntimeError(f'В EXE отсутствуют уведомления: {required - names}')
                manifest = json.loads(zf.read('manifest.json'))
                installed = {p['name'].lower().replace('_', '-'): p for p in manifest['packages']}
                for package in ('numpy', 'manifold3d', 'trimesh', 'pywebview', 'pyinstaller', 'pyfastnoiselite'):
                    if package not in installed or not installed[package]['license_files']:
                        raise RuntimeError(f'В EXE нет файлов лицензии {package}')
                if 'CC BY-SA 4.0' not in zf.read('vendor/human_skeleton.LICENSE.txt').decode('utf-8'):
                    raise RuntimeError('Нет авторства и лицензии скелета в EXE')

            payload = post('/api/build', {'script': 'a = box size=[200,100,60]', 'auto': False})
            if not payload.get('ok'):
                raise RuntimeError(f"Ошибка сборки: {payload.get('error')}")
            preview = get(payload['glb_url'])
            exported = post('/api/export', {'format': 'glb'})
            path = Path(temp) / 'exports' / exported['name']
            standard = path.read_bytes()
            doc, _ = _glb_read(standard)
            root = doc['nodes'][doc['scenes'][0]['nodes'][0]]
            if root.get('scale') != [.001, .001, .001]:
                raise RuntimeError('У внешнего GLB неверный масштаб')
            np.testing.assert_allclose(extents(preview), [200., 60., 100.], atol=.0001)
            np.testing.assert_allclose(extents(standard), [.2, .06, .1], atol=1e-7)
            back = post('/api/build', {'script': f'imported = import file={path.name} unit=auto', 'auto': False})
            if not back.get('ok'):
                raise RuntimeError(f"Ошибка обратного импорта: {back.get('error')}")
            item = next(obj for obj in back['objects'] if obj['name'] == 'imported')
            np.testing.assert_allclose(item['size'], [200., 100., 60.], atol=1e-4)

            script = ('thin = box size=[40,40,0.5]\n'
                      'glass = box size=[20,30,40] at=[80,0,0] transmission=0.85\n'
                      'glow = sphere radius=10 at=[0,80,0] emissive=#ff8833 emissive_strength=4\n'
                      'tex = cylinder radius=25 height=80 segments=24 at=[100,120,0]\n'
                      'texture tex kind=своя pattern=камень color1=#8a5a2b '
                      'color2=#d9c9a8 scale=2 seed=7 relief=0.6\n')
            result = post('/api/build', {'script': script, 'auto': False})
            if not result.get('ok'):
                raise RuntimeError(f"Ошибка материалов: {result.get('error')}")
            exported = post('/api/export', {'format': 'glb'})
            standard = (Path(temp) / 'exports' / exported['name']).read_bytes()
            doc, _ = _glb_read(standard)
            materials = {m['name']: m for m in doc['materials']}
            if not materials['mat_thin'].get('doubleSided'):
                raise RuntimeError('Тонкая стенка не двусторонняя')
            glass = materials['mat_glass']
            if ('KHR_materials_transmission' not in glass.get('extensions', {})
                    or glass.get('alphaMode', 'OPAQUE') != 'OPAQUE'):
                raise RuntimeError('Обычный GLB неверно описывает стекло')
            if 'KHR_materials_emissive_strength' not in materials['mat_glow'].get('extensions', {}):
                raise RuntimeError('Не экспортирована яркость свечения')
            texture = materials['mat_tex']
            if texture.get('normalTexture', {}).get('scale') != 1.0:
                raise RuntimeError('Карта нормалей или её масштаб отсутствуют')
            tex_mesh = next(m for m in doc['meshes'] if m.get('name') == 'tex')
            if 'TANGENT' not in tex_mesh['primitives'][0]['attributes']:
                raise RuntimeError('Не экспортированы тангенты текстурированной детали')
            compat = post('/api/export', {'format': 'glb-alpha'})
            compat_data = (Path(temp) / 'exports' / compat['name']).read_bytes()
            compat_doc, _ = _glb_read(compat_data)
            fallback = next(m for m in compat_doc['materials'] if m['name'] == 'mat_glass')
            if (fallback.get('alphaMode') != 'BLEND'
                    or 'KHR_materials_transmission' in fallback.get('extensions', {})
                    or not 0 < fallback['pbrMetallicRoughness']['baseColorFactor'][3] < 1):
                raise RuntimeError('Неверная совместимая прозрачность')
            obj = post('/api/export', {'format': 'obj'})
            obj_data = (Path(temp) / 'exports' / obj['name']).read_bytes()
            if b'mtllib ' in obj_data or b'(mm, Z-up)' not in obj_data:
                raise RuntimeError('OBJ неожиданно изменил формат')
            example = (ROOT / 'examples' / 'noise_scatter_0764.forma').read_text(encoding='utf-8')
            result = post('/api/build', {'script': example, 'auto': False})
            if not result.get('ok'):
                raise RuntimeError(f"Пример FastNoiseLite/Poisson не собран: {result.get('error')}")
            exported = post('/api/export', {'format': 'glb'})
            example_data = (Path(temp) / 'exports' / exported['name']).read_bytes()
            sample_doc, _ = _glb_read(example_data)
            meshes = [m for m in sample_doc['meshes'] if m.get('name', '').startswith('камешки_')]
            if len(meshes) != 18:
                raise RuntimeError(f'В примере ожидалось 18 камешков, получено {len(meshes)}')
            centers = []
            for mesh in meshes:
                acc = sample_doc['accessors'][mesh['primitives'][0]['attributes']['POSITION']]
                centers.append([(acc['min'][axis] + acc['max'][axis]) / 2 for axis in (0, 2)])
            centers = np.asarray(centers)
            distances = np.linalg.norm(centers[:, None] - centers[None, :], axis=2)
            distances += np.eye(len(centers)) * 1e9
            if float(distances.min()) < 11 - 1e-4:
                raise RuntimeError('Poisson-disk нарушил минимальное расстояние между центрами')
            mats = {m.get('name'): m for m in sample_doc['materials']}
            if mats.get('mat_пластина', {}).get('normalTexture', {}).get('scale') != 1.0:
                raise RuntimeError('Клеточная карта нормалей не экспортирована')

            passport_script = 'a = box size=[20,30,40] at=[0,0,0]\nb = box size=[20,30,40] at=[40,0,0]\n'
            result = post('/api/build', {'script': passport_script, 'auto': False})
            if not result.get('ok'):
                raise RuntimeError(f"Сцена паспорта не построена: {result.get('error')}")
            for mode, expected in (('fast', 6), ('detail', 18)):
                exported = post('/api/export', {'format': 'passport-' + mode})
                with zipfile.ZipFile(Path(temp) / 'exports' / exported['name']) as zf:
                    data = json.loads(zf.read('passport.json'))
                    if zf.read('source.forma').decode('utf-8') != passport_script:
                        raise RuntimeError('Сценарий в паспорте отличается от построенного')
                    if data['mode'] != mode or len(data['facts']['sections']) != expected:
                        raise RuntimeError('Неверные режимы и количество сечений паспорта')
                    a = data['facts']['objects'][0]
                    if a['size_mm'] != [20, 30, 40] or a['bbox_center_mm'] != [0, 0, 20]:
                        raise RuntimeError('Неверные габариты в паспорте')
                    pair = data['facts']['bbox_relations']['pairs'][0]
                    if pair['axes']['x']['bbox_gap_mm'] != 20 or data['hypotheses']:
                        raise RuntimeError('Неверное отношение коробок или выдана недоказанная гипотеза')
                    if any(s['status'] != 'ok' for s in data['facts']['sections']):
                        raise RuntimeError('Ошибка контрольных сечений')
                    if 'Ограничения' not in zf.read('ПАСПОРТ.md').decode('utf-8'):
                        raise RuntimeError('Не указаны ограничения паспорта')
            return {'version': __version__, 'standard_extents_m': [.2, .06, .1],
                    'preview_extents_mm': [200, 60, 100], 'roundtrip_mm': [200, 100, 60],
                    'thin_double_sided': True, 'physical_glass': True,
                    'alpha_fallback': True, 'emissive': True, 'normal_map_tangent': True,
                    'obj_geometry_only': True, 'fastnoise_and_poisson': True,
                    'spatial_passport_fast_and_detail': True, 'embedded_license_bundle': True,
                    'poisson_min_center_mm': float(distances.min()),
                    'note': 'Проверены данные EXE, не визуальная идентичность рендереров.'}
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
    result = run(args.exe)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
