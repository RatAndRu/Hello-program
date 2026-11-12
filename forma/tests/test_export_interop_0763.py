"""Экспорт и обратный импорт без внешних 3D-приложений.

GLB проверяется по структуре и независимо читается trimesh; это не сравнение
визуального результата разных рендереров.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

import numpy as np
import trimesh

from forma.geometry import (_glb_read, _gltf_tangents, export_3mf, export_glb,
                            export_obj, export_stl)
from forma.ops_io import _forma_meter_gltf
from forma.run import build
from forma.webui import AppState


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def bounds(data):
    return np.asarray(trimesh.load(io.BytesIO(data), file_type='glb', force='scene').bounds)


def accessor(doc, binary, index):
    acc = doc['accessors'][index]
    view = doc['bufferViews'][acc['bufferView']]
    dims = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[acc['type']]
    assert acc['componentType'] == 5126
    offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
    return np.frombuffer(binary, dtype='<f4', count=acc['count'] * dims,
                         offset=offset).reshape(-1, dims)


class ExportInteropTest(unittest.TestCase):
    def test_external_meters_and_preview_mm(self):
        b = built('a = box size=[200,100,60]')
        preview, external = b.glb(), b.export_glb()
        doc, _ = _glb_read(external)
        root = doc['nodes'][doc['scenes'][0]['nodes'][0]]
        self.assertEqual(root['scale'], [0.001] * 3)
        self.assertEqual(doc['asset']['extras']['formaUnits']['world'], 'meter')
        pdoc, _ = _glb_read(preview)
        self.assertEqual(pdoc['asset']['extras']['formaUnits']['world'], 'millimeter')
        np.testing.assert_allclose(bounds(preview) * .001, bounds(external), atol=1e-7)
        np.testing.assert_allclose(bounds(external)[1] - bounds(external)[0], [.2, .06, .1], atol=1e-7)
        # Геометрия и точность вершин остаются исходными — масштаб на корне.
        pa = [a for a in pdoc['accessors'] if a.get('type') == 'VEC3' and a.get('max')]
        ea = [a for a in doc['accessors'] if a.get('type') == 'VEC3' and a.get('max')]
        self.assertEqual(pa, ea)
        np.testing.assert_allclose(bounds(export_glb(b.visible_solids())), bounds(external), atol=1e-8)

    def test_auto_roundtrip_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as td:
            b = built('a = box size=[200,100,60]')
            path = Path(td) / 'external.glb'
            path.write_bytes(b.export_glb())
            legacy = Path(td) / 'legacy.glb'
            legacy.write_bytes(b.glb())
            self.assertTrue(_forma_meter_gltf(path))
            self.assertFalse(_forma_meter_gltf(legacy))
            for file, unit, want in ((path, 'auto', [200,100,60]),
                                     (path, 'm', [200,100,60]),
                                     (path, 'mm', [.2,.1,.06]),
                                     (legacy, 'auto', [200,100,60])):
                with self.subTest(file=file, unit=unit):
                    result = built(f'imported = import file="{file.as_posix()}" unit={unit}')
                    bnd = result.scene.objects['imported'].bbox
                    np.testing.assert_allclose(np.array(bnd[3:]) - bnd[:3], want, atol=1e-4)
            # Именованный узел также должен учитывать масштаб корня.
            result = built(f'imported = import file="{path.as_posix()}" node=a unit=auto')
            bb = result.scene.objects['imported'].bbox
            np.testing.assert_allclose(np.array(bb[3:]) - bb[:3], [200,100,60], atol=1e-4)

    def test_thin_rotated_shell_and_explicit_override(self):
        b = built('thin = box size=[100,80,0.5]\n'
                  'tilted = rotate thin axis=x angle=45\n'
                  'thick = box size=[20,20,20] two_sided=да\n'
                  'flat = box size=[40,40,0.5] two_sided=нет')
        d, _ = _glb_read(b.export_glb())
        materials = {m['name']: m for m in d['materials']}
        self.assertTrue(materials['mat_tilted']['doubleSided'])
        self.assertTrue(materials['mat_thick']['doubleSided'])
        self.assertFalse(materials['mat_flat']['doubleSided'])
        b = built('a = box size=[20,20,20]\ncolor a двусторонний=да')
        self.assertTrue(_glb_read(b.export_glb())[0]['materials'][0]['doubleSided'])

    def test_transmission_is_not_doubled_with_alpha(self):
        b = built('glass = box size=[20,30,40] transmission=0.85')
        d, _ = _glb_read(b.export_glb())
        m = d['materials'][0]
        self.assertEqual(m['extensions']['KHR_materials_transmission']['transmissionFactor'], .85)
        self.assertEqual(m.get('alphaMode', 'OPAQUE'), 'OPAQUE')
        self.assertEqual(m['pbrMetallicRoughness']['baseColorFactor'][3], 1.0)
        fallback, _ = _glb_read(b.export_glb(glass_fallback=True))
        m = fallback['materials'][0]
        self.assertEqual(m['alphaMode'], 'BLEND')
        self.assertAlmostEqual(m['pbrMetallicRoughness']['baseColorFactor'][3], .32)
        self.assertNotIn('KHR_materials_transmission', m.get('extensions', {}))
        self.assertNotIn('KHR_materials_transmission', fallback.get('extensionsUsed', []))
        np.testing.assert_allclose(bounds(b.export_glb()), bounds(b.export_glb(glass_fallback=True)))

    def test_normal_texture_tangents_and_scale(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'FORMA_DATA': td}):
            b = built('a = cylinder radius=30 height=60 segments=24\n'
                      'texture a kind=своя pattern=камень color1=#8a5a2b '
                      'color2=#d9c9a8 scale=2 seed=7 relief=0.6')
            d, binary = _glb_read(b.export_glb())
            p = d['meshes'][0]['primitives'][0]
            self.assertIn('TANGENT', p['attributes'])
            self.assertEqual(d['materials'][0]['normalTexture']['scale'], 1.0)
            normal = accessor(d, binary, p['attributes']['NORMAL'])
            tangent = accessor(d, binary, p['attributes']['TANGENT'])
            np.testing.assert_allclose(np.linalg.norm(tangent[:, :3], axis=1), 1, atol=1e-5)
            np.testing.assert_allclose(np.sum(normal * tangent[:, :3], axis=1), 0, atol=1e-5)
            self.assertTrue(set(tangent[:, 3]).issubset({-1., 1.}))
            self.assertTrue(np.all(tangent.reshape(-1, 3, 4)[:, :, 3] == tangent.reshape(-1, 3, 4)[:, :1, 3]))

    def test_tangent_handedness_and_degenerate_uv(self):
        verts = np.array([[0.,0.,0.], [1.,0.,0.], [0.,1.,0.]])
        norms = np.tile([0.,0.,1.], (3,1))
        faces = np.array([[0,1,2]])
        uv = np.array([[0.,1.],[1.,1.],[0.,0.]])
        tang = _gltf_tangents(verts, norms, faces, uv)
        np.testing.assert_allclose(tang, np.tile([1.,0.,0.,1.], (3,1)), atol=1e-7)
        uv[:,0] *= -1
        mirrored = _gltf_tangents(verts, norms, faces, uv)
        np.testing.assert_allclose(mirrored, np.tile([-1.,0.,0.,-1.], (3,1)), atol=1e-7)
        self.assertIsNone(_gltf_tangents(verts, norms, faces, np.zeros((3,2))))

    def test_animation_stays_under_unit_root(self):
        b = built('a = box size=[40,20,10]\nb = sphere radius=10 at=[60,0,0]\n'
                  'animate kind=explode seconds=2 amount=20')
        p, pb = _glb_read(b.glb())
        e, eb = _glb_read(b.export_glb())
        self.assertEqual(p['animations'], e['animations'])
        self.assertEqual(pb, eb)
        root = e['nodes'][e['scenes'][0]['nodes'][0]]
        self.assertEqual(root['scale'], [.001,.001,.001])
        self.assertTrue(e['animations'][0]['channels'])
        self.assertNotIn(e['scenes'][0]['nodes'][0],
                         [c['target']['node'] for c in e['animations'][0]['channels']])

    def test_other_formats_remain_mm_and_obj_labeled(self):
        b = built('a = box size=[200,100,60]')
        solids = b.visible_solids()
        stl = trimesh.load(io.BytesIO(export_stl(solids)), file_type='stl')
        np.testing.assert_allclose(stl.extents, [200,100,60], atol=1e-5)
        with zipfile.ZipFile(io.BytesIO(export_3mf(solids))) as zf:
            xml = zf.read('3D/3dmodel.model').decode('utf-8')
            self.assertIn('unit="millimeter"', xml)
        obj = export_obj(solids).decode('utf-8')
        self.assertIn('mm, Z-up', obj)
        self.assertNotIn('mtllib ', obj)
        page = (Path(__file__).resolve().parents[1] / 'web/index.html').read_text(encoding='utf-8')
        self.assertIn('OBJ — только геометрия (мм)', page)
        self.assertIn('GLB — совместимая прозрачность', page)

    def test_appstate_export_and_preview_are_distinct(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'FORMA_DATA': td, 'FORMA_DOWNLOADS': td}):
            state = AppState()
            self.assertTrue(state.build('a = box size=[200,100,60]')['ok'])
            pre = state.glb()
            result = state.export('glb')
            external = (state.data_dir / 'exports' / result['name']).read_bytes()
            np.testing.assert_allclose(bounds(pre) * .001, bounds(external), atol=1e-7)
            fallback = state.export('glb-alpha')
            self.assertTrue(fallback['name'].endswith('_alpha.glb'))
            self.assertTrue(_forma_meter_gltf(state.data_dir / 'exports' / fallback['name']))


if __name__ == '__main__':
    unittest.main()
