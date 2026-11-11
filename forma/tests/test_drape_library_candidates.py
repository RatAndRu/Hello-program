"""Небольшие тесты исследовательских сценариев библиотек, не приёмка drape."""
from pathlib import Path
import importlib.util
import sys
import unittest

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))
from forma import cloth  # noqa: E402
import drape_six_probe as six  # noqa: E402
import drape_ipc_first_impact_probe as impact  # noqa: E402
import drape_pbd_constraints_probe as pbd  # noqa: E402

HAS_IPC = importlib.util.find_spec('ipctk') is not None
HAS_FCL = importlib.util.find_spec('fcl') is not None
HAS_PBD = importlib.util.find_spec('pypbd') is not None


class LibraryCandidatesTest(unittest.TestCase):
    @unittest.skipUnless(HAS_IPC and HAS_FCL, 'Для независимой проверки нужны ipctk и python-fcl')
    def test_first_real_impact_is_corrected_without_changing_original_solver(self):
        original_solver, original_factory = cloth.simulate, six._instrumented_solver
        report = impact.inspect_impact('01_sheet_over_ball')
        self.assertIs(cloth.simulate, original_solver)
        self.assertIs(six._instrumented_solver, original_factory)
        self.assertEqual(report['first_unsafe_step'], 2)
        self.assertFalse(report['ccd_before'])
        self.assertTrue(report['ccd_after'])
        self.assertGreater(report['support_fcl_before']['pairs'], 0)
        self.assertEqual(report['support_fcl_after']['pairs'], 0)
        self.assertGreater(report['contact_stats']['local_hits'] + report['contact_stats']['fallbacks'], 0)
        self.assertGreater(report['correction_max_mm'], 0.)
        self.assertLess(report['corrected']['max_edge_change_percent'], 1.)

    @unittest.skipUnless(HAS_PBD, 'pypbd устанавливается только для исследовательского теста')
    def test_pbd_simple_distance_and_volume_with_pins(self):
        initial_meta_path = list(sys.meta_path)
        report = pbd.inspect_constraints()
        self.assertEqual(initial_meta_path, sys.meta_path)
        self.assertEqual(report['rendering_imports_blocked'], ['pygame', 'OpenGL'])
        self.assertTrue(report['distance']['solved'])
        np.testing.assert_allclose(report['distance']['after'], [[0, 0, 0], [1, 0, 0]])
        tet = report['tetrahedron']
        np.testing.assert_allclose(tet['fixed_vertices_after'], [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        self.assertGreater(tet['compressed_vertex_by_iteration']['20'][2],
                           tet['compressed_vertex_by_iteration']['1'][2])
        self.assertLess(tet['compressed_vertex_by_iteration']['20'][2], 1.)


if __name__ == '__main__':
    unittest.main()
