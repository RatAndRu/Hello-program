"""Короткие тесты эксперимента: это не сертификация drape или ткани."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))

import drape_bounded_probe as bounded  # noqa: E402
from drape_ipc_contact_probe import IPCContactProbe  # noqa: E402
from drape_mujoco_probe import TrajectoryAudit  # noqa: E402

try:
    import ipctk  # noqa: F401
except ImportError:
    ipctk = None


@unittest.skipIf(ipctk is None, 'ipctk устанавливается только для исследовательских проверок')
class IPCContactProbeTest(unittest.TestCase):
    def setUp(self):
        self.moving = np.asarray([[.1, .1, 1.], [.8, .1, 1.], [.1, .8, 1.]])
        self.faces = np.asarray([[0, 1, 2]], dtype=np.int64)
        self.support = np.asarray([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]])

    def audit(self, positions, faces=None):
        faces = self.faces if faces is None else faces
        return TrajectoryAudit(positions, faces,
                               {'опора': (self.support.reshape(-1, 3), self.faces)})

    def test_crossing_is_prevented_and_safe_motion_is_unchanged(self):
        solver = IPCContactProbe(self.moving, self.faces, [], self.support, rounds=3)
        free = np.ones(3, dtype=bool)
        safe = self.moving + [0., 0., .2]
        desired = safe.copy()
        solver.project(self.moving, safe, free)
        np.testing.assert_array_equal(safe, desired)
        crossing = self.moving - [0., 0., 2.]
        self.assertFalse(self.audit(self.moving).check(crossing))
        solver.project(self.moving, crossing, free)
        self.assertTrue(self.audit(self.moving).check(crossing))
        self.assertGreater(float(np.min(crossing[:, 2])), 0.)
        self.assertGreater(solver.stats()['local_hits'] + solver.stats()['fallbacks'], 0)

    def test_pinned_vertices_and_static_support_are_unchanged(self):
        before_support = self.support.copy()
        solver = IPCContactProbe(self.moving, self.faces, [], self.support, rounds=3)
        free = np.array([False, True, True])
        crossing = self.moving - [0., 0., 2.]
        solver.project(self.moving, crossing, free)
        np.testing.assert_array_equal(crossing[0], self.moving[0])
        np.testing.assert_array_equal(self.support, before_support)
        self.assertTrue(self.audit(self.moving).check(crossing))

    def test_contact_translates_paired_sides_without_changing_pair_vectors(self):
        old = np.vstack((self.moving, self.moving + [0., 0., .4]))
        faces = np.asarray([[0, 1, 2], [3, 5, 4]], dtype=np.int64)
        shell = np.asarray([[0, 3], [1, 4], [2, 5]], dtype=np.int64)
        solver = IPCContactProbe(old, faces, shell, self.support, rounds=3)
        crossing = old - [0., 0., 2.]
        solver.project(old, crossing, np.ones(6, dtype=bool))
        np.testing.assert_allclose(crossing[shell[:, 1]] - crossing[shell[:, 0]],
                                   old[shell[:, 1]] - old[shell[:, 0]], atol=1e-12)
        self.assertTrue(self.audit(old, faces).check(crossing))

    def test_friction_changes_tangential_motion_in_a_simple_contact(self):
        moving = np.asarray([[.1, .1, 1.], [.4, .1, 1.], [.1, .4, 1.]])
        support = self.support * 2
        desired = moving + [.2, 0., -2.]
        outcomes = []
        for friction in (0., .2):
            solver = IPCContactProbe(moving, self.faces, [], support, friction=friction, rounds=2)
            position = desired.copy()
            solver.project(moving, position, np.ones(3, dtype=bool))
            outcomes.append(position)
        self.assertLess(float(np.mean(outcomes[1][:, 0] - moving[:, 0])),
                        float(np.mean(outcomes[0][:, 0] - moving[:, 0])))
        # Это только проверка направления поправки, не калибровка закона трения.

    def test_rejects_overlapping_pairs_and_initial_intersection(self):
        bad_shell = np.asarray([[0, 1], [0, 2]])
        with self.assertRaises(ValueError):
            IPCContactProbe(self.moving, self.faces, bad_shell, self.support)
        touching = self.moving.copy()
        touching[:, 2] = 0.
        with self.assertRaises(ValueError):
            IPCContactProbe(touching, self.faces, [], self.support)

    def test_self_crossing_is_detected_and_prevented(self):
        old = np.vstack((self.moving, self.moving - [0., 0., 1.5]))
        faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
        # Отдельная опора вдали от обеих поверхностей.
        support = self.support - [0., 0., 10.]
        solver = IPCContactProbe(old, faces, [], support, rounds=3)
        desired = old.copy()
        desired[:3, 2] -= 2.
        initial_audit = TrajectoryAudit(old, faces, {'опора': (support.reshape(-1, 3), self.faces)})
        self.assertFalse(initial_audit.check(desired))
        solver.project(old, desired, np.ones(6, dtype=bool))
        final_audit = TrajectoryAudit(old, faces, {'опора': (support.reshape(-1, 3), self.faces)})
        self.assertTrue(final_audit.check(desired))


class BoundedProbeTest(unittest.TestCase):
    def test_timeout_preserves_completed_results_and_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'

            def runner(name, timeout, **_kwargs):
                if name == 'quick':
                    return {'name': name, 'value': 123}
                subprocess.run([sys.executable, '-c',
                                "import sys,time; print('шаг 10', file=sys.stderr, flush=True); time.sleep(3)"],
                               timeout=timeout, check=True, capture_output=True)
                raise AssertionError('Подпроцесс должен быть остановлен')

            started = time.monotonic()
            result = bounded.run_bounded(['quick', 'slow'], output, mode='current', budget=4.,
                                         case_limit=.8, runner=runner)
            self.assertLess(time.monotonic() - started, 3.)
            self.assertEqual([x['status'] for x in result['cases']], ['completed', 'timeout'])
            self.assertFalse(result['all_completed'])
            import json
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['cases'][0]['result']['value'], 123)
            self.assertEqual(saved['cases'][1]['status'], 'timeout')
            self.assertIn('шаг 10', saved['cases'][1]['progress'])
            self.assertFalse((Path(directory) / 'result.json.tmp').exists())

    def test_global_budget_leaves_unstarted_scenes_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'

            def runner(_name, timeout, **_kwargs):
                subprocess.run([sys.executable, '-c', 'import time; time.sleep(3)'],
                               timeout=timeout, check=True)

            result = bounded.run_bounded(['slow', 'later'], output, mode='current', budget=.12,
                                         case_limit=.5, runner=runner)
            self.assertEqual([x['status'] for x in result['cases']], ['timeout', 'not_started'])
            self.assertFalse(result['all_completed'])

    def test_current_mode_rejects_ignored_ipc_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            run = subprocess.run([sys.executable, str(TOOLS / 'drape_bounded_probe.py'),
                                  '--mode', 'current', '--gravity-scale', '.5', '--output', str(output)],
                                 capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('только к --mode ipc', run.stderr)
            self.assertFalse(output.exists())

    def test_failed_scene_does_not_discard_successful_neighbours(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'

            def runner(name, _timeout, **_kwargs):
                if name == 'broken':
                    raise RuntimeError('ошибка тестовой сцены')
                return {'name': name}

            result = bounded.run_bounded(['first', 'broken', 'last'], output, mode='ipc', budget=2.,
                                         case_limit=1., runner=runner)
            self.assertEqual([x['status'] for x in result['cases']], ['completed', 'error', 'completed'])
            self.assertIn('ошибка тестовой сцены', result['cases'][1]['reason'])
            self.assertFalse(result['all_completed'])


if __name__ == '__main__':
    unittest.main()
