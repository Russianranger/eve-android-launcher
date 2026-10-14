"""Reversible D3D policy and real owned-process affinity inheritance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import client_graphics as graphics
import client_runtime as runtime

POLICY = ('info:    dxgi.maxFrameRate = 30\ninfo:    dxgi.maxFrameLatency = 1\n'
          'info:    dxgi.syncInterval = 0\ninfo:    Present mode: VK_PRESENT_MODE_IMMEDIATE_KHR\n')

class Experiments(unittest.TestCase):
    def test_selected_config_requires_actual_dxvk_readback_and_retains_fences(self):
        baseline = graphics.dxvk_config()
        for cached, immediate in ((True, False), (False, True), (True, True)):
            config = graphics.dxvk_config(cached_dynamic_buffers=cached, immediate_context=immediate)
            self.assertTrue(config.startswith(baseline))
            log = POLICY
            if cached: log += 'info:    d3d11.cachedDynamicResources = vi\n'
            if immediate: log += 'info:    d3d11.exposeDriverCommandLists = False\n'
            graphics.parse_performance_policy(log, 'responsive', cached, immediate)
            graphics.parse_performance_policy(log.replace('\n', '\r\n'), 'responsive', cached, immediate)
            for bad in (POLICY, log.replace('vi\n', 'a\n').replace('False', 'True'),
                        log.replace('IMMEDIATE', 'FIFO')):
                with self.assertRaises(ValueError):
                    graphics.parse_performance_policy(bad, 'responsive', cached, immediate)
        self.assertEqual(graphics.dxvk_config(), baseline)
        for invalid in (1, 'true', None, []):
            with self.assertRaises(ValueError): graphics.dxvk_config(cached_dynamic_buffers=invalid)

    def test_software_ignores_saved_guest_experiments(self):
        r = runtime.Runtime(runtime.Settings(graphics_mode='software', performance_cores=True,
                                            immediate_context=True, cached_dynamic_buffers=True))
        self.assertFalse(r.experiments['performanceCores'])
        self.assertFalse(r.experiments['immediateContext'])
        self.assertFalse(r.experiments['cachedDynamicBuffers'])
        self.assertNotIn('DXVK_CONFIG_FILE', r.environment())

    def test_mask_uses_capacity_and_respects_allowed_online_cores(self):
        topology = {'cpus': [{'cpu': n, 'capacity': c} for n, c in enumerate([280,280,280,855,855,855,855,1024])]}
        self.assertEqual(runtime.performance_cpu_mask(topology, set(range(8))), {3,4,5,6,7})
        self.assertEqual(runtime.performance_cpu_mask(topology, {0,3,4}), {3,4})
        for allowed in ({0,1,2}, {3,4,5}, {0,3}, {0,3,8}):
            with self.assertRaises(runtime.RuntimeErrorDetail): runtime.performance_cpu_mask(topology, allowed)
        for data in ({'cpus': []}, {'cpus': [{'cpu': n, 'capacity': 280} for n in range(8)]}):
            with self.assertRaises(runtime.RuntimeErrorDetail): runtime.performance_cpu_mask(data, set(range(8)))

    @unittest.skipUnless(hasattr(os, 'sched_getaffinity'), 'Linux scheduler required')
    def test_exec_and_new_threads_inherit_mask_without_changing_parent(self):
        allowed = sorted(os.sched_getaffinity(0))
        if len(allowed) < 3: self.skipTest('need three allowed host cores')
        # Keep the bounded topology fixture on the same <=32 CPU range as Android.
        chosen = [cpu for cpu in allowed if cpu < 32][:3]
        if len(chosen) < 3: self.skipTest('need three allowed CPU IDs below 32')
        selected = chosen[1:]
        with tempfile.TemporaryDirectory() as td:
            receipt, observation = Path(td)/'receipt.json', Path(td)/'child.json'
            topology = {'cpus': [{'cpu': n, 'capacity': 280 if n == chosen[0] else 855} for n in chosen]}
            child = ('import json,os,sys,threading; m=[]; t=threading.Thread(target=lambda:m.append(sorted(os.sched_getaffinity(0))));'
                     't.start();t.join();open(sys.argv[1],"w").write(json.dumps({"pid":os.getpid(),"mask":sorted(os.sched_getaffinity(0)),"thread":m[0]}))')
            launcher = ('import client_runtime as r,os,sys; '
                        'os.sched_setaffinity(0,'+repr(chosen)+'); '
                        'r.client_graphics.cpu_topology=lambda:'+repr(topology)+'; '
                        'sys.exit(r.affinity_exec(sys.argv[1:]))')
            env = {**os.environ, 'PYTHONPATH': str(Path(runtime.__file__).parent)}
            p = subprocess.Popen([sys.executable,'-c',launcher,str(receipt),sys.executable,'-c',child,str(observation)],env=env)
            self.assertEqual(p.wait(timeout=10), 0)
            self.assertEqual(json.loads(observation.read_text()), {'pid':p.pid,'mask':selected,'thread':selected})
            self.assertTrue(json.loads(receipt.read_text())['applied'])
        self.assertEqual(sorted(os.sched_getaffinity(0)), allowed)

    def test_denied_affinity_never_executes_or_claims_activation(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(runtime, 'performance_cpu_mask', return_value={3,4}), \
                mock.patch.object(os, 'sched_getaffinity', return_value={0,3,4}), \
                mock.patch.object(os, 'sched_setaffinity', side_effect=PermissionError('denied')), \
                mock.patch.object(os, 'execvpe') as execute:
            receipt = Path(td)/'receipt.json'
            self.assertEqual(runtime.affinity_exec([str(receipt),'/no-client']),1)
            self.assertFalse(json.loads(receipt.read_text())['applied'])
            execute.assert_not_called()

if __name__ == '__main__': unittest.main()
