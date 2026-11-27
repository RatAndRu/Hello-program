"""Проверка внешнего GLB, обратного импорта и материалов через API EXE.

Это проверка данных; визуальная идентичность разных рендереров не проверяется.
"""
from __future__ import annotations

import argparse
from collections import Counter
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
from xml.etree import ElementTree as ET

import manifold3d as mf
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forma.geometry import _glb_read
from forma.version import __version__


def extents(data):
    scene = trimesh.load(io.BytesIO(data), file_type='glb', force='scene', process=False)
    return np.asarray(scene.bounds[1] - scene.bounds[0])


def parse_3mf(data):
    """Inspect the file produced by the running app, without welding its edges."""
    ns = {'c': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
          'm': 'http://schemas.microsoft.com/3dmanufacturing/material/2015/02'}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if zf.testzip() is not None:
            raise RuntimeError('Повреждён ZIP 3MF')
        root = ET.fromstring(zf.read('3D/3dmodel.model'))
    if root.get('unit') != 'millimeter':
        raise RuntimeError('В 3MF не указаны миллиметры')
    group = root.find('./c:resources/m:colorgroup', ns)
    if group is None:
        raise RuntimeError('В 3MF отсутствует стандартная палитра цветов')
    colors = [c.get('color').upper() for c in group.findall('m:color', ns)]
    resources = root.findall('./c:resources/c:object', ns)
    meshes = [obj for obj in resources if obj.find('c:mesh', ns) is not None]
    parts = {}
    for obj in meshes:
        vertices = np.asarray([[float(v.get(k)) for k in ('x', 'y', 'z')]
                               for v in obj.findall('./c:mesh/c:vertices/c:vertex', ns)])
        triangle_nodes = obj.findall('./c:mesh/c:triangles/c:triangle', ns)
        faces = np.asarray([[int(t.get(k)) for k in ('v1', 'v2', 'v3')] for t in triangle_nodes])
        if not len(faces) or faces.min() < 0 or faces.max() >= len(vertices):
            raise RuntimeError(f'В 3MF неверные индексы: {obj.get("name")}')
        edges = Counter((a, b) for face in faces.tolist()
                        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])))
        if any(a == b or count != 1 or edges[(b, a)] != 1 for (a, b), count in edges.items()):
            raise RuntimeError(f'В 3MF незамкнутая сетка: {obj.get("name")}')
        if obj.get('pid') != group.get('id'):
            raise RuntimeError(f'В 3MF отсутствует цвет объекта: {obj.get("name")}')
        if any(t.get('pid') != group.get('id') or t.get('p1') is None for t in triangle_nodes):
            raise RuntimeError(f'В 3MF отсутствует цвет грани: {obj.get("name")}')
        parts[obj.get('name')] = (obj, vertices, faces,
                                  [colors[int(t.get('p1'))] for t in triangle_nodes])
    return root, ns, meshes, parts, colors


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

            if 'clover_keychain_3mf' not in {e['key'] for e in state['examples']}:
                raise RuntimeError('Пример цветного брелока отсутствует в меню EXE')
            clover = json.loads(get('/api/example?key=clover_keychain_3mf'))['script']
            if clover != (ROOT / 'examples' / 'clover_keychain_3mf.forma').read_text(encoding='utf-8'):
                raise RuntimeError('Встроенный пример брелока отличается от исходника')
            result = post('/api/build', {'script': clover, 'auto': False})
            if not result.get('ok'):
                raise RuntimeError(f"Пример брелока не собран: {result.get('error')}")
            exported = post('/api/export', {'format': '3mf'})
            data = (Path(temp) / 'exports' / exported['name']).read_bytes()
            root, ns, meshes, parts, colors = parse_3mf(data)
            expected_colors = {'основа': '#185B3AFF', 'вставка_верх': '#66D976FF',
                               'вставка_право': '#F5C84CFF', 'вставка_низ': '#EB6B83FF',
                               'вставка_лево': '#41BFD0FF'}
            if set(parts) != set(expected_colors) or set(colors) != set(expected_colors.values()):
                raise RuntimeError('В 3MF брелока отсутствуют отдельные детали или цвета')
            for name, (obj, vertices, faces, face_colors) in parts.items():
                if colors[int(obj.get('pindex'))] != expected_colors[name] or set(face_colors) != {expected_colors[name]}:
                    raise RuntimeError(f'Неверный цвет 3MF: {name}')
            assembly = root.find('./c:resources/c:object[c:components]', ns)
            if assembly is None or root.find('./c:build/c:item', ns).get('objectid') != assembly.get('id'):
                raise RuntimeError('3MF брелока не сохранён одной сборкой')
            if [c.get('objectid') for c in assembly.findall('./c:components/c:component', ns)] != [m.get('id') for m in meshes]:
                raise RuntimeError('В сборке 3MF нет всех деталей')
            vertices = np.vstack([p[1] for p in parts.values()])
            np.testing.assert_allclose(vertices.max(axis=0) - vertices.min(axis=0),
                                       [39.884224, 48.942112, 3.0], atol=1e-3)
            bodies = {}
            for name, (_, vertices, faces, _) in parts.items():
                body = mf.Manifold(mf.Mesh(vert_properties=np.ascontiguousarray(vertices, dtype=np.float32),
                                           tri_verts=np.ascontiguousarray(faces, dtype=np.uint32)))
                if body.status() != mf.Error.NoError or len(body.decompose()) != 1:
                    raise RuntimeError(f'Деталь 3MF не является единым телом: {name}')
                bodies[name] = body
            base_body = bodies['основа']
            pin = mf.Manifold.cylinder(5, 2.4, 2.4, 64).translate((0, 24, -1))
            if base_body.genus() != 1 or abs((base_body ^ pin).volume()) > 1e-6:
                raise RuntimeError('В 3MF брелока нет сквозного отверстия')
            bodies_list = list(bodies.values())
            if any(abs((a ^ b).volume()) > 1e-4 for i, a in enumerate(bodies_list) for b in bodies_list[i + 1:]):
                raise RuntimeError('Цветные детали 3MF пересекаются по объёму')

            painted = 'a = box size=[20,30,40] at=[5,-4,2]\ncolor a #cc0011\npaint a #00ff00 side=верх'
            result = post('/api/build', {'script': painted, 'auto': False})
            if not result.get('ok'):
                raise RuntimeError(f"Окрашенный короб не построен: {result.get('error')}")
            exported = post('/api/export', {'format': '3mf'})
            data = (Path(temp) / 'exports' / exported['name']).read_bytes()
            _, _, _, painted_parts, _ = parse_3mf(data)
            _, vertices, faces, face_colors = painted_parts['a']
            tri = vertices[faces]
            normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            expected = ['#00FF00FF' if n[2] > 0 else '#CC0011FF' for n in normals]
            if face_colors != expected or len(set(face_colors)) != 2:
                raise RuntimeError('Роспись граней 3MF потерялась или повернулась')

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
                    '3mf_components_colors_and_topology': True, '3mf_face_paint': True,
                    '3mf_keychain_hole_and_inserts': True,
                    'poisson_min_center_mm': float(distances.min()),
                    'note': 'Проверены данные запущенной сборки, не импорт в Studio и не физическая печать.'}
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
