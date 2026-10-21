"""Real owned helper processes qualify renderer selection and fallback ordering."""

from dataclasses import replace
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

import test_client_runtime as base_tests

BACKEND, FIXTURE, MODULE = base_tests.BACKEND, base_tests.FIXTURE, base_tests.MODULE


GPU_FIXTURE = r'''
import json, os, pathlib, signal, subprocess, sys, time
mode, state, port, behavior = sys.argv[1:]
state=pathlib.Path(state)
with (state/'events.jsonl').open('a') as stream:
    stream.write(json.dumps({'role':mode,'pid':os.getpid(),'environment':dict(os.environ)})+'\n')
if mode=='rendererProbe':
    (state/'rendererProbe.pid').write_text(str(os.getpid()))
    def done(*args): sys.exit(0)
    signal.signal(signal.SIGTERM,done)
    if behavior=='success':
        print('EVE_DXVK_TURNIP_OK D3D11 device and X11 software swapchain presented',flush=True)
        sys.exit(0)
    if behavior=='no-marker': sys.exit(0)
    if behavior=='crash-orphan':
        subprocess.Popen([sys.executable,__file__,'rendererOrphan',str(state),port,behavior])
        time.sleep(.2)
        os._exit(23)
    if behavior=='fail':
        print('EVE_DXVK_TURNIP_FAILED',flush=True)
        sys.exit(23)
    while True: time.sleep(.02)
if mode=='rendererOrphan':
    (state/'rendererOrphan.pid').write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    while True: time.sleep(.02)
'''


class RendererRuntimeTests(unittest.TestCase):
    setUp = base_tests.ClientRuntimeTests.setUp
    wait_status = base_tests.ClientRuntimeTests.wait_status

    def cleanup_processes(self):
        base_tests.ClientRuntimeTests.cleanup_processes(self)
        for role in ('rendererProbe', 'rendererOrphan'):
            path = self.state/(role+'.pid')
            if path.exists():
                with contextlib.suppress(ProcessLookupError):
                    os.kill(int(path.read_text()), signal.SIGKILL)

    def launch_gpu(self, behavior='success', fail_prepare=False, reserve_failure=False, probe_timeout=.45):
        (self.state/'performance.json').write_text(
            json.dumps({'renderer': 'dxvk-turnip', 'wineEsync': False}))
        self.fixture.write_text(GPU_FIXTURE+'\n'+FIXTURE)
        settings = base_tests.ClientRuntimeTests.settings(self, 'normal')
        probe = (sys.executable, str(self.fixture), 'rendererProbe',
                 str(self.state), str(self.port), behavior)
        settings = replace(settings, renderer_probe_command=probe,
                           renderer_probe_timeout=probe_timeout)
        values = {key: str(value) if hasattr(value, 'as_posix')
                  else value for key, value in settings.__dict__.items()}
        runner = self.root/'gpu-runner.py'
        runner.write_text(
            'import json,pathlib,signal,sys\n'
            f'sys.path.insert(0,{str(BACKEND.parent)!r})\n'
            'import client_runtime as module\n'
            f'values=json.loads({json.dumps(values)!r})\n'
            "for key in ('content','state','server_state','marker','gate'): values[key]=pathlib.Path(values[key])\n"
            'class FixtureRuntime(module.Runtime):\n'
            " def preflight(self): return {'contentBuild':3396210}\n"
            ' def require_server(self): pass\n'
            ' def prepare_renderer(self):\n'
            + ("  raise module.client_renderer.RendererUnavailable('fixture package missing')\n" if fail_prepare else
               "  return module.client_renderer.PreparedRenderer(env={'WINEDLLOVERRIDES':'winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n','VK_ICD_FILENAMES':'fixture-turnip.json'},report={'requested':'dxvk-turnip','active':'checking','deviceProbePassed':False},probe=pathlib.Path('unused.exe'))\n")
            + (' def memory_check(self):\n'
               "  if 'rendererProbe' in self.children: raise module.RuntimeErrorDetail('fixture memory reserve')\n" if reserve_failure else '')
            + 'runtime=FixtureRuntime(module.Settings(**values))\n'
            'for number in (signal.SIGTERM,signal.SIGINT): signal.signal(number,runtime.request_stop)\n'
            'try: runtime.start()\n'
            'except Exception as error: print(str(error),flush=True); sys.exit(1)\n')
        output = (self.root/'supervisor.log').open('ab')
        self.addCleanup(output.close)
        process = subprocess.Popen((sys.executable, str(
            runner)), stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def events(self):
        return [json.loads(line) for line in (self.state/'events.jsonl').read_text().splitlines()]

    def stop(self, process):
        (self.state/'run/stop').write_text('stop')
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertFalse((self.state/'run/processes.json').exists())

    def assert_software(self, env):
        self.assertEqual(env['LIBGL_ALWAYS_SOFTWARE'], '1')
        self.assertEqual(env['GALLIUM_DRIVER'], 'llvmpipe')
        self.assertIn('LP_NUM_THREADS', env)
        self.assertTrue(env['WINEDLLOVERRIDES'].endswith('d3d11,dxgi=b'))
        self.assertNotIn('VK_ICD_FILENAMES', env)

    def test_success_gates_native_environment_and_records_actual_renderer(self):
        process = self.launch_gpu()
        running = self.wait_status('running')
        self.assertEqual(running['performance']['renderer'], 'dxvk-turnip')
        self.assertTrue(running['rendererReport']['deviceProbePassed'])
        journal = json.loads((self.state/'run/processes.json').read_text())
        self.assertIn('rendererProbeIdentity', journal)
        self.assertFalse(MODULE.identity_alive(
            journal['rendererProbeIdentity']))
        events = self.events()
        self.assertEqual(sorted(row['role'] for row in events), sorted(
            ['display', 'wineServer', 'gate', 'rendererProbe', 'client']))
        self.assertLess(next(i for i, row in enumerate(events) if row['role'] == 'gate'),
                        next(i for i, row in enumerate(events) if row['role'] == 'rendererProbe'))
        for row in events:
            if row['role'] in ('display', 'wineServer', 'gate'):
                self.assert_software(row['environment'])
                continue
            for key in MODULE.client_renderer.SOFTWARE_VARIABLES:
                self.assertNotIn(key, row['environment'])
            self.assertEqual(row['environment']
                             ['VK_ICD_FILENAMES'], 'fixture-turnip.json')
            self.assertTrue(row['environment']
                            ['WINEDLLOVERRIDES'].endswith('d3d11,dxgi=n'))
        observation = json.loads(
            (self.state/'launch-observation.json').read_text())
        self.assertEqual(
            observation['rendererReport'], running['rendererReport'])
        self.assertEqual(observation['renderer'], 'dxvk-turnip')
        self.stop(process)

    def test_failure_timeout_zero_without_marker_and_crash_fall_back_after_cleanup(self):
        for behavior in ('fail', 'hang', 'no-marker', 'crash-orphan'):
            with self.subTest(behavior=behavior):
                for path in ('run/stop', 'run/status.json', 'events.jsonl'):
                    (self.state/path).unlink(missing_ok=True)
                process = self.launch_gpu(behavior)
                running = self.wait_status('running', timeout=8)
                self.assertEqual(running['performance']['renderer'], 'wined3d')
                self.assertFalse(
                    running['rendererReport']['deviceProbePassed'])
                self.assertIn('using WineD3D', running['message'])
                self.assertIn('fallbackReason', running['rendererReport'])
                self.assertFalse(MODULE.identity_alive(
                    running['rendererProbeIdentity']))
                self.assertEqual(MODULE.group_members(
                    running['rendererProbeIdentity']['pid']), [])
                events = self.events()
                self.assertEqual(
                    sum(row['role'] == 'client' for row in events), 1)
                self.assertLess(next(i for i, row in enumerate(events) if row['role'] == 'rendererProbe'),
                                next(i for i, row in enumerate(events) if row['role'] == 'client'))
                self.assert_software(
                    next(row['environment'] for row in events if row['role'] == 'client'))
                self.stop(process)

    def test_unavailable_package_skips_probe_and_launches_software(self):
        process = self.launch_gpu(fail_prepare=True)
        running = self.wait_status('running')
        self.assertIn('fixture package missing', running['message'])
        self.assertNotIn('rendererProbeIdentity', running)
        self.assert_software(
            next(row['environment'] for row in self.events() if row['role'] == 'client'))
        self.stop(process)

    def test_cancel_and_memory_pressure_stop_probe_without_launching_eve(self):
        for reserve_failure in (False, True):
            with self.subTest(reserve_failure=reserve_failure):
                for path in ('run/stop', 'run/status.json', 'events.jsonl', 'rendererProbe.pid'):
                    (self.state/path).unlink(missing_ok=True)
                process = self.launch_gpu(
                    'hang', reserve_failure=reserve_failure)
                if not reserve_failure:
                    deadline = time.monotonic()+4
                    while not (self.state/'rendererProbe.pid').exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue((self.state/'rendererProbe.pid').exists())
                    (self.state/'run/stop').write_text('stop')
                self.assertEqual(process.wait(timeout=6),
                                 1 if reserve_failure else 0)
                report = self.wait_status(
                    'failed' if reserve_failure else 'stopped')
                self.assertEqual(MODULE.group_members(
                    report['rendererProbeIdentity']['pid']), [])
                self.assertFalse(
                    any(row['role'] == 'client' for row in self.events()))
                self.assertFalse((self.state/'run/processes.json').exists())

    def test_killed_supervisor_recovers_owned_renderer_probe(self):
        process = self.launch_gpu('hang', probe_timeout=5)
        deadline = time.monotonic()+4
        while not (self.state/'rendererProbe.pid').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue((self.state/'rendererProbe.pid').exists())
        journal = json.loads((self.state/'run/processes.json').read_text())
        self.assertTrue(MODULE.identity_alive(
            journal['rendererProbeIdentity']))
        process.kill()
        process.wait(timeout=3)
        runtime = MODULE.Runtime(base_tests.ClientRuntimeTests.settings(self))
        with runtime.exclusive():
            runtime.recover()
        self.assertFalse(MODULE.identity_alive(
            journal['rendererProbeIdentity']))
        self.assertFalse((self.state/'run/processes.json').exists())
        self.assertFalse(any(row['role'] == 'client' for row in self.events()))

    def test_reused_runtime_resets_gpu_candidate_before_any_wine_role(self):
        (self.state / 'performance.json').write_text('{"renderer":"dxvk-turnip"}')
        runtime = MODULE.Runtime(base_tests.ClientRuntimeTests.settings(self))
        runtime.renderer_env = {'VK_ICD_FILENAMES': 'stale-candidate.json'}
        runtime.renderer_fallback = 'stale failure'

        def preflight():
            self.assert_software(runtime.environment())
            self.assertEqual(runtime.renderer_fallback, '')
            self.assertEqual(runtime.renderer_report['requested'], 'dxvk-turnip')
            raise InterruptedError('fixture ends before Wine startup')

        with mock.patch.object(runtime, 'preflight', side_effect=preflight):
            runtime.start()


if __name__ == '__main__':
    unittest.main()
