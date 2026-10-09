"""Client receipt gates and real process/display ownership without retail assets."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from test_client_graphics import (a740_identity, d3d_success, display_success, linear_identity,
                                  mesa262_identity, mesa262_vulkan, shm_report, vulkan_success)

BACKEND = Path(__file__).resolve().parents[1] / "backend/client_runtime.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("eve_client_runtime", BACKEND)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CA_PEM = "-----BEGIN CERTIFICATE-----\nZmFrZS1jZXJ0\n-----END CERTIFICATE-----\n"
OFFLINE_HEALTH = {"status": "ok", "service": "express-secondary", "gatewayMode": "local",
                  "offlinePolicy": {"version": 2, "proxyForwarding": "disabled", "clientFeatureFlags": "defaults"}}
# Mesa262 plus linear runs six real qualification helpers. Joining the two
# deliberately live display/Wine log pumps consumes 3.6s across those helpers;
# TLS adds 0.6s before process scheduling, status sampling and final cleanup.
# Bound the whole fixture session separately from its unchanged 0.5s per-helper
# graphics timeout so a loaded CI runner can finish every asserted gate.
MESA262_SESSION_TIMEOUT = 15

FIXTURE = r'''
import hashlib, json, os, pathlib, signal, socket, subprocess, sys, threading, time
mode, state, port, behavior = sys.argv[1:]
state = pathlib.Path(state)
port = int(port)
(state / (mode + '.pid')).write_text(str(os.getpid()))
environment = {key: os.environ.get(key) for key in ('DXVK_HUD', 'DXVK_CONFIG_FILE', 'TU_DEBUG', 'FEX_HOSTFEATURES', 'FEX_TSOENABLED', 'MESA_VK_WSI_DEBUG', 'MESA_SHADER_CACHE_DIR', 'EVE_X11_SHM_STAGING')}
icd = os.environ.get('VK_DRIVER_FILES')
environment['driverLibrary'] = json.loads(pathlib.Path(icd).read_text())['ICD']['library_path'] if icd and pathlib.Path(icd).exists() else None
environment['processId'] = os.getpid()
(state / (mode + '.environment.json')).write_text(json.dumps(environment))
history_file = state / (mode + '.environment-history.json')
history = json.loads(history_file.read_text()) if history_file.exists() else []
history_file.write_text(json.dumps(history + [environment]))
if mode in ('graphicsVulkan', 'graphicsD3d', 'graphicsIdentity'):
    mesa262 = bool(environment['driverLibrary'] and environment['driverLibrary'].endswith('turnip-26.2.4.so'))
    if (behavior == mode + '-hangs'
            or (mode == 'graphicsVulkan' and behavior == 'shm-selected-hangs' and environment['EVE_X11_SHM_STAGING'] == '1')
            or (mesa262 and behavior == 'mesa262-selected-' + mode + '-hangs')):
        def finish_graphics(*args):
            (state / (mode + '.stopped')).write_text('graceful')
            sys.exit(0)
        signal.signal(signal.SIGTERM, finish_graphics)
        while True: time.sleep(.03)
    if behavior == mode + '-orphan':
        subprocess.Popen([sys.executable, __file__, 'orphan', str(state), str(port), behavior])
        time.sleep(.15)
    report = json.loads((state / ('fixture-' + mode + '.json')).read_text())
    if mesa262 and mode in ('graphicsVulkan', 'graphicsIdentity'):
        report = json.loads((state / ('fixture-mesa262-' + mode + '.json')).read_text())
        if behavior == 'mesa262-wrong-version': report['driver_version'] = 26 << 22
        if behavior == 'mesa262-wrong-device': report['device'] += ' other adapter'
        if behavior == 'mesa262-software': report['software'] = True
        if mode == 'graphicsIdentity':
            if behavior == 'mesa262-wrong-chip': report['device_id'] = 0x740
            if behavior == 'mesa262-fixture': report['mode'] = 'fixture'
            if behavior == 'mesa262-old-probe': report['helper'] = 'eve-a740-driver-probe-1'
            if behavior == 'mesa262-wrong-info': report['driver_info'] = 'Mesa 26.2.40'
            if behavior == 'mesa262-linear-unsupported': report['linear_presentation']['supported'] = False
        if mode == 'graphicsVulkan' and behavior == 'mesa262-final-bad' and os.environ.get('MESA_VK_WSI_DEBUG') == 'sw,linear': report['software'] = True
    if behavior == mode + '-bad':
        if mode == 'graphicsVulkan': report['software'] = True
        elif mode == 'graphicsIdentity': report['device_id'] = 0x740
        else: report['passed'] = False
    if mode == 'graphicsIdentity':
        if behavior == 'identity-unavailable':
            print('native identity unavailable', flush=True)
            sys.exit(0)
        if behavior == 'identity-software': report['software'] = True
        if behavior == 'identity-fixture': report['mode'] = 'fixture'
        if behavior == 'identity-variant-device': report['device'] += ' alternate adapter'
        if behavior == 'linear-missing': report.pop('linear_presentation')
        if behavior == 'linear-unsupported': report['linear_presentation']['supported'] = False
        if behavior == 'linear-format-invalid': report['linear_presentation']['rgba8_unorm'] = 1
    if mode == 'graphicsVulkan' and behavior == 'linear-vulkan-bad' and os.environ.get('MESA_VK_WSI_DEBUG') == 'sw,linear':
        report['software'] = True
    selected_sysmem = mode == 'graphicsVulkan' and 'sysmem' in os.environ.get('TU_DEBUG', '').split(',')
    if selected_sysmem and behavior == 'sysmem-vulkan-bad': report['software'] = True
    if selected_sysmem and behavior == 'sysmem-vulkan-device': report['device'] += ' alternate adapter'
    shm_driver = mode == 'graphicsVulkan' and environment['driverLibrary'] and environment['driverLibrary'].endswith('turnip-26.0.0-x11-shm.so')
    if shm_driver and behavior == 'shm-driver-vulkan-bad' and environment['EVE_X11_SHM_STAGING'] is None: report['software'] = True
    if shm_driver and behavior == 'shm-selected-vulkan-bad' and environment['EVE_X11_SHM_STAGING'] == '1': report['software'] = True
    if shm_driver and behavior == 'shm-vulkan-device': report['device'] += ' alternate adapter'
    if shm_driver and behavior == 'shm-receipts-only-vulkan':
        for receipt in json.loads((state / 'fixture-shm.json').read_text()): print('EVE_X11_SHM ' + json.dumps(receipt), flush=True)
    if mode == 'graphicsD3d':
        if behavior == 'graphics-server-lost': (state / 'server-lost').touch()
        display = json.loads((state / 'fixture-display.json').read_text())
        if behavior == 'graphicsD3d-display-bad': display['matched_frames'] = [0, 1]
        (state / 'run/graphics-display.json').write_text(json.dumps(display, indent=2) + '\n')
        (state / 'logs/client-graphicsD3d-helper.log').write_text(json.dumps(report) + '\n')
        mode_line = 'VK_PRESENT_MODE_FIFO_KHR' if behavior == 'graphicsD3d-policy-fifo' else 'VK_PRESENT_MODE_IMMEDIATE_KHR'
        performance = json.loads((state / 'fixture-performance.json').read_text())
        policy_log = ('info:  dxgi.maxFrameRate = ' + str(performance['targetFrameRate']) + '\n'
                      + 'info:  dxgi.maxFrameLatency = ' + str(performance['maxFrameLatency']) + '\n'
                      + 'info:  dxgi.syncInterval = 0\ninfo:  Present mode: ' + mode_line + '\n')
        if behavior == 'graphicsD3d-profile-wrong': policy_log = policy_log.replace('maxFrameRate = ' + str(performance['targetFrameRate']), 'maxFrameRate = 10')
        if behavior == 'graphicsD3d-profile-missing': policy_log = policy_log.replace('info:  dxgi.maxFrameLatency = ' + str(performance['maxFrameLatency']) + '\n', '')
        if behavior == 'graphicsD3d-policy-missing': policy_log = ''
        if environment['EVE_X11_SHM_STAGING'] == '1':
            receipts = json.loads((state / 'fixture-shm.json').read_text())
            if behavior in ('shm-receipt-missing', 'shm-receipts-only-vulkan'): receipts = []
            if behavior == 'shm-receipt-short': receipts = receipts[:2]
            if behavior == 'shm-receipt-duplicate': receipts = [receipts[0]] * 3
            if behavior == 'shm-receipt-fallback': receipts.insert(0, {'format':'eve-x11-shm-1', 'mode':'fallback', 'reason':'attach-failed'})
            policy_log += ''.join('EVE_X11_SHM ' + json.dumps(receipt) + '\n' for receipt in receipts)
            if behavior == 'shm-receipt-malformed': policy_log += 'EVE_X11_SHM unavailable\n'
        (state / 'logs/client-graphicsD3d-helper-errors.log').write_text(policy_log)
    print(json.dumps(report), flush=True)
    sys.exit(5 if behavior in (mode + '-exit', mode + '-orphan') or (selected_sysmem and behavior == 'sysmem-vulkan-exit') else 0)
if mode == 'gate':
    health = {'status':'ok','service':'express-secondary','gatewayMode':'local',
              'offlinePolicy':{'version':2,'proxyForwarding':'disabled','clientFeatureFlags':'defaults'}}
    value = {'format':1,'helper':'eve-client-gate-1','success':True,'phase':'client_tls_qualified',
             'wine_cryptoapi_trust':True,'localhost443_tls':True,'root_store':'CurrentUser\\ROOT',
             'ca_der_sha256':hashlib.sha256(b'fake-cert').hexdigest(),
             'tls_url':'https://localhost/health','tls_proxy':'none','tls_certificate_checks':'default',
             'http_status':200,'response_body':json.dumps(health),'stage':'complete','win32_error':0}
    if behavior == 'unsafe-tls': value['tls_certificate_checks'] = 'ignored'
    if behavior == 'wrong-ca': value['ca_der_sha256'] = '0' * 64
    if behavior == 'unsafe-gateway':
        health['offlinePolicy']['proxyForwarding'] = 'enabled'
        value['response_body'] = json.dumps(health)
    if behavior == 'gate-fails':
        value['success'] = False
        value['stage'] = 'tls-send'
        value['win32_error'] = 12175
        print(json.dumps(value), flush=True)
        sys.exit(1)
    print(json.dumps(value), flush=True)
    sys.exit(0)
if mode == 'display':
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(5)
    def serve():
        while True:
            connection, _ = listener.accept()
            connection.sendall(b'RFB 003.008\n')
            connection.close()
    threading.Thread(target=serve, daemon=True).start()
if mode == 'orphan':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == 'client' and behavior == 'crash-orphan':
    child = subprocess.Popen([sys.executable, __file__, 'orphan', str(state), str(port), behavior])
    time.sleep(.45)
    os._exit(23)
if mode == 'client' and behavior == 'early-zero': sys.exit(0)
if mode == 'client' and behavior == 'chatty':
    for number in range(400):
        print('X' * 4096, flush=True)
def finish(*args):
    (state / (mode + '.stopped')).write_text('graceful')
    sys.exit(0)
if mode != 'orphan': signal.signal(signal.SIGTERM, finish)
while True: time.sleep(.03)
'''


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ClientRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="eve-client-runtime-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "client-state"
        self.state.mkdir()
        self.content = self.root / "client"
        (self.content / "tq/bin64").mkdir(parents=True)
        (self.content / "keep-client-files").write_text("unchanged")
        self.server = self.root / "server-state"
        (self.server / "certs").mkdir(parents=True)
        (self.server / "certs/xmpp-ca-cert.pem").write_text(CA_PEM)
        self.fixture = self.root / "fixture.py"
        self.fixture.write_text(FIXTURE)
        self.port = free_port()
        self.processes = []
        self.addCleanup(self.cleanup_processes)
        (self.state / 'fixture-graphicsVulkan.json').write_text(json.dumps(vulkan_success()))
        (self.state / 'fixture-graphicsIdentity.json').write_text(json.dumps(linear_identity()))
        (self.state / 'fixture-mesa262-graphicsVulkan.json').write_text(json.dumps(mesa262_vulkan()))
        (self.state / 'fixture-mesa262-graphicsIdentity.json').write_text(json.dumps(mesa262_identity()))
        (self.state / 'fixture-graphicsD3d.json').write_text(json.dumps(d3d_success()))
        (self.state / 'fixture-display.json').write_text(json.dumps(display_success()))
        (self.state / 'fixture-shm.json').write_text(json.dumps([shm_report(stage_id=n) for n in (1, 2, 3)]))
        (self.state / 'fixture-graphics.json').write_text(json.dumps({'files': {
            'dxvk-d3d11-arm64ec.dll': {'sha256': '1' * 64},
            'dxvk-dxgi-arm64ec.dll': {'sha256': '2' * 64},
            'turnip-26.0.0.so': {'sha256': '3' * 64},
            'turnip-26.0.0-x11-shm.so': {'sha256': '4' * 64},
            'turnip-26.2.4.so': {'sha256': '5' * 64}},
            'shmPresentationExperiment': MODULE.client_graphics.SHM_EXPERIMENT,
            'mesa262DriverExperiment': MODULE.client_graphics.MESA262_EXPERIMENT}))

    def settings(self, behavior="normal", graphics=False, performance_profile="responsive", diagnostic_hud=False,
                 disable_concurrent_binning=False, disable_lrcpc2=False, linear_presentation=False, sysmem_rendering=False,
                 shm_presentation=False, mesa262_driver=False):
        def command(role):
            return (sys.executable, str(self.fixture), role, str(self.state), str(self.port), behavior)
        return MODULE.Settings(content=self.content, state=self.state, server_state=self.server,
                               display_port=self.port, display_command=command("display"),
                               wineserver_command=command("wineServer"), gate_command=command("gate"),
                               client_command=command("client"), tick=.025, startup_timeout=2,
                               gate_timeout=2, observe_seconds=.15, shutdown_timeout=.15,
                               graphics_mode="turnip-dxvk" if graphics else "software",
                               performance_profile=performance_profile, diagnostic_hud=diagnostic_hud,
                               disable_concurrent_binning=disable_concurrent_binning, disable_lrcpc2=disable_lrcpc2,
                               linear_presentation=linear_presentation, sysmem_rendering=sysmem_rendering,
                               shm_presentation=shm_presentation, mesa262_driver=mesa262_driver,
                               vulkan_command=command("graphicsVulkan") if graphics else None,
                               d3d_command=command("graphicsD3d") if graphics else None,
                               graphics_timeout=.5,
                               minimum_available_kib=0)

    def launch(self, behavior="normal", clear_stop=True, graphics=False, performance_profile="responsive", diagnostic_hud=False,
               disable_concurrent_binning=False, disable_lrcpc2=False, linear_presentation=False, sysmem_rendering=False,
               shm_presentation=False, mesa262_driver=False):
        if clear_stop:
            (self.state / "run/stop").unlink(missing_ok=True)
        selected = self.settings(behavior, graphics, performance_profile, diagnostic_hud,
                                 disable_concurrent_binning, disable_lrcpc2, linear_presentation, sysmem_rendering,
                                 shm_presentation, mesa262_driver)
        (self.state / 'fixture-performance.json').write_text(json.dumps(MODULE.client_graphics.performance_settings(
            "turnip-dxvk", performance_profile)))
        values = {key: str(value) if isinstance(value, Path) else value for key, value in selected.__dict__.items()}
        runner = self.root / "runner.py"
        runner.write_text(
            "import json,pathlib,signal,sys\n"
            f"sys.path.insert(0,{str(BACKEND.parent)!r})\n"
            "import client_runtime as module\n"
            f"values=json.loads({json.dumps(values)!r})\n"
            "for key in ('content','state','server_state','marker','gate','trust_overlay','trust_overlay_root','graphics_folder'): values[key]=pathlib.Path(values[key])\n"
            "class FixtureRuntime(module.Runtime):\n"
            " def preflight(self):\n"
            "  self.graphics_bundle=json.loads((self.s.state/'fixture-graphics.json').read_text()) if self.s.graphics_mode=='turnip-dxvk' else {}\n"
            "  if self.s.graphics_mode=='turnip-dxvk': module.client_graphics.verify_mapped=lambda folder,state: self.graphics_bundle\n"
            "  if self.s.graphics_mode=='turnip-dxvk': module.client_graphics.verify_bundle=lambda folder: self.graphics_bundle\n"
            "  if self.s.graphics_mode=='turnip-dxvk': (self.s.state/'cache').mkdir(exist_ok=True)\n"
            "  if self.s.graphics_mode=='turnip-dxvk': module.client_graphics.select_driver(self.s.graphics_folder,self.s.state,False)\n"
            "  if self.s.graphics_mode=='turnip-dxvk': module.client_graphics.a740_identity_command=lambda folder: (*self.s.vulkan_command[:2],'graphicsIdentity',*self.s.vulkan_command[3:])\n"
            "  if self.s.graphics_mode=='turnip-dxvk': module.client_graphics.mesa262_identity_command=lambda folder: (*self.s.vulkan_command[:2],'graphicsIdentity',*self.s.vulkan_command[3:])\n"
            "  return {'contentBuild':3396210}\n"
            " def require_server(self):\n"
            "  if (self.s.state/'server-lost').exists(): raise module.RuntimeErrorDetail('server session exited')\n"
            "module.LOG_LIMIT=65536\n"
            "runtime=FixtureRuntime(module.Settings(**values))\n"
            "for number in (signal.SIGTERM,signal.SIGINT): signal.signal(number,runtime.request_stop)\n"
            "try: runtime.start()\n"
            "except Exception as error: print(str(error),flush=True); sys.exit(1)\n"
        )
        output = (self.root / "supervisor.log").open("ab")
        self.addCleanup(output.close)
        process = subprocess.Popen((sys.executable, str(runner)), stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def cleanup_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for role in ("display", "wineServer", "gate", "graphicsVulkan", "graphicsIdentity", "graphicsD3d", "client", "orphan"):
            pidfile = self.state / (role + ".pid")
            if pidfile.is_file():
                pid = int(pidfile.read_text())
                if MODULE.process_record(pid):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)

    @contextlib.contextmanager
    def cleanup_failed_fixture_session(self):
        # subTest continues its loop after a timeout/assertion failure. Reap
        # the current supervisor and its fixture helpers before another case
        # can reuse this directory and overwrite its status/identity receipts.
        try:
            yield
        except BaseException:
            self.cleanup_processes()
            raise

    def wait_status(self, phase, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = json.loads((self.state / "run/status.json").read_text())
                if value.get("phase") == phase:
                    return value
            except (OSError, ValueError):
                pass
            time.sleep(.025)
        self.fail("Missing client phase " + phase + ": " + (self.root / "supervisor.log").read_text())

    def wait_role(self, role, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                journal = json.loads((self.state / "run/processes.json").read_text())
                identity = journal.get(role + "Identity")
                if MODULE.identity_alive(identity):
                    return journal
            except (OSError, ValueError):
                pass
            time.sleep(.01)
        self.fail("Missing owned " + role + ": " + (self.root / "supervisor.log").read_text())

    def test_start_stop_and_restart_preserve_content_and_never_claim_login(self):
        first = self.launch()
        running = self.wait_status("running")
        self.assertTrue(running["ready"])
        self.assertTrue(running["processStartupObserved"])
        self.assertFalse(running["login_qualified"])
        self.assertFalse(running["graphics_qualified"])
        self.assertTrue(MODULE.identity_alive(running["supervisorIdentity"]))
        self.assertTrue(running["displayMembers"])
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(first.wait(timeout=4), 0)
        stopped = self.wait_status("stopped")
        self.assertTrue(stopped["cleanShutdown"])
        self.assertFalse(MODULE.identity_alive(stopped["clientIdentity"]))
        self.assertFalse((self.state / "run/processes.json").exists())
        self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")
        second = self.launch()
        self.wait_status("running")
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(second.wait(timeout=4), 0)

    def test_immediate_stop_is_not_erased_by_new_supervisor(self):
        (self.state / "run").mkdir()
        (self.state / "run/stop").write_text("immediate-stop")
        process = self.launch(clear_stop=False)
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertTrue(self.wait_status("stopped")["cleanShutdown"])
        self.assertFalse((self.state / "client.pid").exists())

    def test_gpu_helpers_qualify_before_eve_and_software_restart_ignores_stale_proof(self):
        process = self.launch(graphics=True)
        running = self.wait_status("running")
        self.assertEqual(running["graphicsMode"], "turnip-dxvk")
        self.assertEqual(running["performance"], MODULE.client_graphics.performance_settings("turnip-dxvk"))
        self.assertEqual(running["graphicsPreflight"]["performance"], running["performance"])
        self.assertTrue(running["graphicsPreflight"]["hardwarePreflightPassed"])
        self.assertTrue(running["graphicsPreflight"]["display"]["display_pixels_verified"])
        self.assertEqual(running["graphicsPreflight"]["presentation"]["requestedSyncInterval"], 1)
        self.assertEqual(running["graphicsPreflight"]["presentation"]["forcedSyncInterval"], 0)
        self.assertEqual(running["graphicsPreflight"]["presentation"]["observedPresentModes"],
                         ["VK_PRESENT_MODE_IMMEDIATE_KHR"])
        self.assertFalse(running["graphics_qualified"])
        self.assertFalse(running["login_qualified"])
        for role in ("gate", "graphicsVulkan", "graphicsD3d"):
            self.assertIn(role + "Identity", running)
            self.assertTrue((self.state / (role + ".pid")).is_file())
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertTrue((self.state / "graphics-preflight.json").is_file())
        fallback = self.launch()
        software = self.wait_status("running")
        self.assertEqual(software["graphicsMode"], "software")
        self.assertEqual(software["performance"]["displayFrameRate"], 15)
        self.assertEqual(software["performance"]["performanceProfile"], "software")
        self.assertFalse(software["graphicsPreflight"]["hardwarePreflightPassed"])
        self.assertNotIn("graphicsD3dIdentity", software)
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(fallback.wait(timeout=4), 0)

    def test_graphics_negative_reports_and_nonzero_exits_prevent_eve(self):
        for behavior in ("graphicsVulkan-bad", "graphicsVulkan-exit", "graphicsD3d-bad",
                         "graphicsD3d-display-bad", "graphicsD3d-exit", "graphicsD3d-policy-fifo",
                         "graphicsD3d-policy-missing", "graphicsD3d-profile-wrong", "graphicsD3d-profile-missing"):
            with self.subTest(behavior=behavior):
                process = self.launch(behavior, graphics=True)
                self.assertEqual(process.wait(timeout=5), 1)
                failed = self.wait_status("failed")
                self.assertFalse(failed["ready"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())
                self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")

    def test_tls_remains_mandatory_before_gpu_helpers(self):
        process = self.launch("gate-fails", graphics=True)
        self.assertEqual(process.wait(timeout=4), 1)
        self.assertFalse((self.state / "graphicsVulkan.pid").exists())
        self.assertFalse((self.state / "graphicsD3d.pid").exists())
        self.assertFalse((self.state / "client.pid").exists())

    def test_accepted_early_failure_clears_old_graphics_receipt_but_rejected_start_preserves_it(self):
        receipt = self.state / "graphics-preflight.json"
        old = json.dumps({"hardwarePreflightPassed": True, "sysmemRenderingQualification": {
            "hardwareIdentityGatePassed": True, "selectedVulkanPresentationPassed": True}})
        receipt.write_text(old)
        runtime = MODULE.Runtime(self.settings(graphics=True, sysmem_rendering=True))
        with mock.patch.object(runtime, "recover", side_effect=MODULE.BusyError("Prior client still alive")), \
                self.assertRaises(MODULE.BusyError):
            runtime.start()
        self.assertEqual(receipt.read_text(), old)
        process = self.launch("gate-fails", graphics=True, sysmem_rendering=True)
        self.assertEqual(process.wait(timeout=5), 1)
        failed = self.wait_status("failed")
        self.assertEqual(failed["graphicsPreflight"], {})
        self.assertFalse(receipt.exists())
        for role in ("graphicsVulkan", "graphicsIdentity", "graphicsD3d", "client"):
            self.assertFalse((self.state / (role + ".pid")).exists())

    def test_a740_session_requires_current_identity_and_selected_driver_presentation(self):
        for fault in (None, "wrong-chip", "variant-device", "stop"):
            with self.subTest(fault=fault):
                selected = self.settings(graphics=True)
                runtime = MODULE.Runtime(MODULE.Settings(**{**selected.__dict__, "a740_pc_mode": True}))
                runtime.run.mkdir(exist_ok=True)
                runtime.logs.mkdir(exist_ok=True)
                runtime.graphics_bundle = json.loads((self.state / "fixture-graphics.json").read_text())
                stages = []
                switched = False

                def driver_gate(folder, state, enabled, baseline, identity):
                    nonlocal switched
                    self.assertEqual(identity, a740_identity())
                    self.assertEqual(baseline, vulkan_success())
                    self.assertTrue(enabled)
                    switched = True
                    if fault == "stop": runtime.request_stop()
                    return {"a740PcMode": True, "driver": MODULE.client_graphics.A740_DRIVER}

                def qualification(role, command, env, timeout):
                    stages.append(role)
                    if role == "graphicsVulkan":
                        result = vulkan_success()
                        if switched and fault == "variant-device": result["device"] += " other device"
                        (runtime.logs / "client-graphicsVulkan.log").write_text(json.dumps(result))
                    elif role == "graphicsIdentity":
                        result = a740_identity()
                        if fault == "wrong-chip": result["device_id"] = 0x740
                        (runtime.logs / "client-graphicsIdentity.log").write_text(json.dumps(result))
                    elif role == "graphicsD3d":
                        (runtime.logs / "client-graphicsD3d-helper.log").write_text(json.dumps(d3d_success()))
                        (runtime.run / "graphics-display.json").write_text(json.dumps(display_success()))
                        (runtime.logs / "client-graphicsD3d-helper-errors.log").write_text(
                            "info: dxgi.maxFrameRate = 30\ninfo: dxgi.maxFrameLatency = 1\n"
                            "info: dxgi.syncInterval = 0\ninfo: Present mode: VK_PRESENT_MODE_IMMEDIATE_KHR\n")

                with mock.patch.object(runtime, "wait_graphics", side_effect=qualification), \
                        mock.patch.object(runtime, "status"), \
                        mock.patch.object(MODULE.client_graphics, "verify_mapped"), \
                        mock.patch.object(MODULE.client_graphics, "select_driver", side_effect=driver_gate) as gate:
                    if fault:
                        with self.assertRaises((ValueError, MODULE.RuntimeErrorDetail, InterruptedError)):
                            runtime.run_graphics()
                        self.assertNotIn("graphicsD3d", stages)
                        self.assertEqual(gate.call_count, 0 if fault == "wrong-chip" else 1)
                    else:
                        report = runtime.run_graphics()
                        self.assertTrue(report["driverSelection"]["a740PcMode"])
                        self.assertTrue(report["hardwarePreflightPassed"])
                        self.assertTrue(report["display"]["display_pixels_verified"])
                        self.assertEqual(stages, ["graphicsVulkan", "graphicsIdentity", "graphicsVulkan", "graphicsD3d"])

    def test_a740_cli_boolean_is_independent_and_software_cannot_select_driver(self):
        with mock.patch.object(MODULE, "Runtime") as constructor, mock.patch.object(MODULE.signal, "signal"):
            self.assertEqual(MODULE.main(["start", "--a740-pc-mode"]), 0)
            selected = constructor.call_args.args[0]
            self.assertTrue(selected.a740_pc_mode)
            self.assertFalse(selected.disable_concurrent_binning)
            self.assertFalse(selected.disable_lrcpc2)
        with mock.patch.object(MODULE, "Runtime") as constructor, \
                mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            MODULE.main(["start", "--a740-pc-mode", "0x1f1f"])
        constructor.assert_not_called()
        runtime = MODULE.Runtime(MODULE.Settings(graphics_mode="software", a740_pc_mode=True))
        with mock.patch.object(MODULE.client_graphics, "select_driver") as gate:
            self.assertFalse(runtime.run_graphics()["optimizations"]["a740PcMode"])
            gate.assert_not_called()

    def test_linear_cli_is_boolean_default_off_and_software_records_ignored_request(self):
        for arguments, enabled in (([], False), (["--linear-presentation"], True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                selected = constructor.call_args.args[0]
                self.assertEqual(selected.linear_presentation, enabled)
                self.assertFalse(selected.a740_pc_mode)
                self.assertEqual(selected.performance_profile, "responsive")
        with mock.patch.object(MODULE, "Runtime") as constructor, \
                mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            MODULE.main(["start", "--linear-presentation", "sw,linear"])
        constructor.assert_not_called()
        runtime = MODULE.Runtime(self.settings(linear_presentation=True))
        with mock.patch.object(runtime, "wait_graphics") as helper:
            report = runtime.run_graphics()
        helper.assert_not_called()
        self.assertTrue(report["optimizations"]["requestedLinearPresentation"])
        self.assertFalse(report["optimizations"]["linearPresentation"])
        self.assertIsNone(report["optimizations"]["mesaWsiDebug"])
        self.assertNotIn("MESA_VK_WSI_DEBUG", runtime.environment())

    def test_linear_uses_current_original_capability_then_render_gates_and_resets_on_restart(self):
        process = self.launch(graphics=True, linear_presentation=True)
        running = self.wait_status("running")
        self.assertEqual(running["performance"], MODULE.client_graphics.performance_settings("turnip-dxvk"))
        self.assertTrue(running["optimizations"]["linearPresentation"])
        self.assertEqual(running["optimizations"]["mesaWsiDebug"], "sw,linear")
        self.assertFalse(running["optimizations"]["a740PcMode"])
        self.assertFalse(running["optimizations"]["nativeEffectVerified"])
        preflight = running["graphicsPreflight"]
        linear = preflight["linearPresentationQualification"]
        self.assertTrue(linear["hardwareCapabilityGatePassed"])
        self.assertTrue(linear["vulkanPresentationPassed"])
        self.assertFalse(linear["nativeEffectVerified"])
        self.assertEqual(linear["originalDriver"], "turnip-26.0.0.so")
        self.assertTrue(preflight["display"]["display_pixels_verified"])
        self.assertEqual(preflight["driverSelection"]["driver"], "turnip-26.0.0.so")
        self.assertEqual(preflight["presentation"]["observedPresentModes"], ["VK_PRESENT_MODE_IMMEDIATE_KHR"])
        history = json.loads((self.state / "graphicsVulkan.environment-history.json").read_text())
        self.assertEqual([environment["MESA_VK_WSI_DEBUG"] for environment in history], ["sw", "sw,linear"])
        identity_env = json.loads((self.state / "graphicsIdentity.environment.json").read_text())
        self.assertEqual(identity_env["MESA_VK_WSI_DEBUG"], "sw")
        for role in ("graphicsD3d", "client"):
            environment = json.loads((self.state / (role + ".environment.json")).read_text())
            self.assertEqual(environment["MESA_VK_WSI_DEBUG"], "sw,linear")
            self.assertEqual(environment["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0"))
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(process.wait(timeout=4), 0)
        baseline = self.launch(graphics=True)
        restarted = self.wait_status("running")
        self.assertFalse(restarted["optimizations"]["linearPresentation"])
        self.assertFalse(restarted["graphicsPreflight"]["linearPresentationQualification"]["hardwareCapabilityGatePassed"])
        self.assertEqual(json.loads((self.state / "client.environment.json").read_text())["MESA_VK_WSI_DEBUG"], "sw")
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(baseline.wait(timeout=4), 0)

    def test_linear_failed_capability_or_rendering_does_not_reuse_old_receipt_or_launch_eve(self):
        for behavior in ("graphicsIdentity-bad", "graphicsIdentity-exit", "linear-missing",
                         "linear-unsupported", "linear-format-invalid", "linear-vulkan-bad",
                         "graphicsD3d-bad", "graphicsD3d-display-bad", "graphicsD3d-policy-fifo"):
            with self.subTest(behavior=behavior):
                (self.state / "graphics-preflight.json").write_text(json.dumps({
                    "hardwarePreflightPassed": True,
                    "linearPresentationQualification": {"hardwareCapabilityGatePassed": True}}))
                process = self.launch(behavior, graphics=True, linear_presentation=True)
                self.assertEqual(process.wait(timeout=5), 1)
                failed = self.wait_status("failed")
                self.assertFalse(failed["ready"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())
                self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")

    def test_stop_and_timeout_during_linear_capability_clean_helpers_without_game(self):
        for stop in (True, False):
            with self.subTest(stop=stop):
                process = self.launch("graphicsIdentity-hangs", graphics=True, linear_presentation=True)
                self.wait_role("graphicsIdentity")
                if stop:
                    (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=5), 0 if stop else 1)
                finished = self.wait_status("stopped" if stop else "failed")
                self.assertTrue(finished["cleanShutdown"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_sysmem_cli_is_strict_default_off_and_software_scrubs_inherited_flags(self):
        for arguments, enabled in (([], False), (["--sysmem-rendering"], True),
                                   (["--sysmem-rendering", "--linear-presentation"], True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                selected = constructor.call_args.args[0]
                self.assertEqual(selected.sysmem_rendering, enabled)
                self.assertEqual(selected.linear_presentation, "--linear-presentation" in arguments)
                self.assertFalse(selected.a740_pc_mode)
                self.assertEqual(selected.performance_profile, "responsive")
        for argument in ("sysmem", "nocb,sysmem", "false"):
            with self.subTest(argument=argument), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
                MODULE.main(["start", "--sysmem-rendering", argument])
            constructor.assert_not_called()
        for invalid in (1, "sysmem", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.Runtime(MODULE.Settings(sysmem_rendering=invalid))
        runtime = MODULE.Runtime(self.settings(sysmem_rendering=True, linear_presentation=True,
                                              disable_concurrent_binning=True))
        (self.state / "graphics-preflight.json").write_text('{"hardwarePreflightPassed":true}')
        with mock.patch.dict(os.environ, TU_DEBUG="forcecb,sysmem", TU_DEBUG_FILE="/outside/options"), \
                mock.patch.object(runtime, "wait_graphics") as helper:
            report = runtime.run_graphics()
            self.assertFalse(any(key.startswith("TU_") for key in runtime.environment()))
        helper.assert_not_called()
        self.assertTrue(report["optimizations"]["requestedSysmemRendering"])
        self.assertFalse(report["optimizations"]["sysmemRendering"])
        self.assertFalse(report["sysmemRenderingQualification"]["hardwareIdentityGatePassed"])
        self.assertFalse((self.state / "graphics-preflight.json").exists())

    def test_sysmem_current_identity_and_selected_environment_reach_helper_game_and_reset(self):
        for linear, binning, lrcpc2 in ((False, False, False), (True, True, True)):
            with self.subTest(linear=linear, binning=binning):
                # SYS-only accepts exact native identity without linear-format metadata.
                (self.state / "fixture-graphicsIdentity.json").write_text(json.dumps(
                    linear_identity() if linear else a740_identity()))
                with mock.patch.dict(os.environ, TU_DEBUG="gmem,forcecb", TU_DEBUG_FILE="/outside/options"):
                    process = self.launch(graphics=True, sysmem_rendering=True, linear_presentation=linear,
                                          disable_concurrent_binning=binning, disable_lrcpc2=lrcpc2)
                running = self.wait_status("running")
                selected_debug = "nocb,sysmem" if binning else "sysmem"
                baseline_debug = "nocb" if binning else None
                wsi = "sw,linear" if linear else "sw"
                qualification = running["graphicsPreflight"]["sysmemRenderingQualification"]
                for field in ("hardwareIdentityGatePassed", "selectedVulkanPresentationPassed",
                              "nativeD3d11ShaderReadbackPassed", "visibleRfbFramesPassed"):
                    self.assertTrue(qualification[field])
                self.assertFalse(qualification["nativeEffectVerified"])
                self.assertEqual(qualification["turnipDebug"], selected_debug)
                self.assertEqual(qualification["originalDriver"], "turnip-26.0.0.so")
                self.assertEqual(qualification["baselineVulkan"], vulkan_success())
                self.assertTrue(running["optimizations"]["sysmemRendering"])
                self.assertFalse(running["optimizations"]["a740PcMode"])
                history = json.loads((self.state / "graphicsVulkan.environment-history.json").read_text())[-2:]
                self.assertEqual([env["TU_DEBUG"] for env in history], [baseline_debug, selected_debug])
                self.assertEqual([env["MESA_VK_WSI_DEBUG"] for env in history], ["sw", wsi])
                identity_env = json.loads((self.state / "graphicsIdentity.environment.json").read_text())
                self.assertEqual(identity_env["TU_DEBUG"], baseline_debug)
                self.assertEqual(identity_env["MESA_VK_WSI_DEBUG"], "sw")
                for role in ("graphicsD3d", "client"):
                    env = json.loads((self.state / (role + ".environment.json")).read_text())
                    self.assertEqual(env["TU_DEBUG"], selected_debug)
                    self.assertEqual(env["MESA_VK_WSI_DEBUG"], wsi)
                    self.assertEqual(env["FEX_HOSTFEATURES"], "disablelrcpc2" if lrcpc2 else None)
                    self.assertEqual(env["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0"))
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=4), 0)
                baseline = self.launch(graphics=True)
                restarted = self.wait_status("running")
                self.assertFalse(restarted["optimizations"]["requestedSysmemRendering"])
                self.assertFalse(restarted["optimizations"]["sysmemRendering"])
                fresh = restarted["graphicsPreflight"]["sysmemRenderingQualification"]
                self.assertFalse(fresh["hardwareIdentityGatePassed"])
                self.assertFalse(fresh["selectedVulkanPresentationPassed"])
                self.assertFalse(fresh["nativeEffectVerified"])
                self.assertNotIn("identity", fresh)
                self.assertIsNone(json.loads((self.state / "client.environment.json").read_text())["TU_DEBUG"])
                self.assertEqual(json.loads((self.state / "graphics-preflight.json").read_text())
                                 ["sysmemRenderingQualification"], fresh)
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(baseline.wait(timeout=4), 0)

    def test_sysmem_failed_or_unknown_gates_discard_old_preflight_and_never_launch_game(self):
        for behavior in ("graphicsVulkan-bad", "graphicsIdentity-bad", "graphicsIdentity-exit",
                         "identity-unavailable", "identity-software", "identity-fixture", "identity-variant-device",
                         "sysmem-vulkan-bad", "sysmem-vulkan-device", "sysmem-vulkan-exit",
                         "graphicsD3d-bad", "graphicsD3d-display-bad", "graphicsD3d-policy-fifo"):
            with self.subTest(behavior=behavior):
                (self.state / "graphics-preflight.json").write_text(json.dumps({
                    "hardwarePreflightPassed": True,
                    "sysmemRenderingQualification": {"hardwareIdentityGatePassed": True,
                                                     "selectedVulkanPresentationPassed": True}}))
                process = self.launch(behavior, graphics=True, sysmem_rendering=True)
                self.assertEqual(process.wait(timeout=5), 1)
                failed = self.wait_status("failed")
                self.assertFalse(failed["ready"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "graphics-preflight.json").exists())
                self.assertFalse((self.state / "run/processes.json").exists())
                self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")

    def test_stop_and_timeout_during_sysmem_identity_clean_helpers_without_game(self):
        for stop in (True, False):
            with self.subTest(stop=stop):
                process = self.launch("graphicsIdentity-hangs", graphics=True, sysmem_rendering=True)
                self.wait_role("graphicsIdentity")
                if stop:
                    (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=5), 0 if stop else 1)
                finished = self.wait_status("stopped" if stop else "failed")
                self.assertTrue(finished["cleanShutdown"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "graphics-preflight.json").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_sysmem_a740_and_linear_combination_separates_original_driver_and_final_checks(self):
        for a740, linear in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(a740=a740, linear=linear):
                selected = self.settings(graphics=True, sysmem_rendering=True, linear_presentation=linear,
                                         disable_concurrent_binning=True)
                runtime = MODULE.Runtime(MODULE.Settings(**{**selected.__dict__, "a740_pc_mode": a740}))
                runtime.run.mkdir(exist_ok=True)
                runtime.logs.mkdir(exist_ok=True)
                runtime.graphics_bundle = json.loads((self.state / "fixture-graphics.json").read_text())
                stages = []

                def qualification(role, command, env, timeout):
                    stages.append((role, env.get("TU_DEBUG"), env["MESA_VK_WSI_DEBUG"]))
                    if role == "graphicsVulkan":
                        (runtime.logs / "client-graphicsVulkan.log").write_text(json.dumps(vulkan_success()))
                    elif role == "graphicsIdentity":
                        (runtime.logs / "client-graphicsIdentity.log").write_text(json.dumps(linear_identity()))
                    else:
                        (runtime.logs / "client-graphicsD3d-helper.log").write_text(json.dumps(d3d_success()))
                        (runtime.run / "graphics-display.json").write_text(json.dumps(display_success()))
                        (runtime.logs / "client-graphicsD3d-helper-errors.log").write_text(
                            "info: dxgi.maxFrameRate = 30\ninfo: dxgi.maxFrameLatency = 1\n"
                            "info: dxgi.syncInterval = 0\ninfo: Present mode: VK_PRESENT_MODE_IMMEDIATE_KHR\n")

                with mock.patch.object(runtime, "wait_graphics", side_effect=qualification), \
                        mock.patch.object(runtime, "status"), mock.patch.object(MODULE.client_graphics, "verify_mapped"), \
                        mock.patch.object(MODULE.client_graphics, "select_driver", return_value={
                            "a740PcMode": a740, "driver": MODULE.client_graphics.A740_DRIVER}) as driver:
                    report = runtime.run_graphics()
                wsi = "sw,linear" if linear else "sw"
                expected = [("graphicsVulkan", "nocb", "sw"), ("graphicsIdentity", "nocb", "sw")]
                if a740:
                    expected.append(("graphicsVulkan", "nocb", "sw"))
                expected.extend((("graphicsVulkan", "nocb,sysmem", wsi), ("graphicsD3d", "nocb,sysmem", wsi)))
                self.assertEqual(stages, expected)
                self.assertEqual(driver.call_count, 1 if a740 else 0)
                self.assertTrue(report["sysmemRenderingQualification"]["selectedVulkanPresentationPassed"])
                self.assertFalse(report["sysmemRenderingQualification"]["nativeEffectVerified"])
                self.assertEqual(report["linearPresentationQualification"]["hardwareCapabilityGatePassed"], linear)

    def test_sysmem_plus_linear_failed_capability_stops_before_selected_rendering(self):
        for capability in (None, {"supported": False, "bgra8_unorm": True, "rgba8_unorm": True},
                           {"supported": True, "bgra8_unorm": True, "rgba8_unorm": 1}):
            with self.subTest(capability=capability):
                runtime = MODULE.Runtime(self.settings(graphics=True, sysmem_rendering=True, linear_presentation=True))
                runtime.run.mkdir(exist_ok=True)
                runtime.logs.mkdir(exist_ok=True)
                stages = []
                (self.state / "graphics-preflight.json").write_text('{"hardwarePreflightPassed":true}')

                def qualification(role, command, env, timeout):
                    stages.append(role)
                    self.assertNotIn("TU_DEBUG", env)
                    self.assertEqual(env["MESA_VK_WSI_DEBUG"], "sw")
                    report = vulkan_success() if role == "graphicsVulkan" else a740_identity()
                    if role == "graphicsIdentity" and capability is not None:
                        report["linear_presentation"] = capability
                    (runtime.logs / ("client-" + role + ".log")).write_text(json.dumps(report))

                with mock.patch.object(runtime, "wait_graphics", side_effect=qualification), \
                        mock.patch.object(runtime, "status"), mock.patch.object(MODULE.client_graphics, "verify_mapped"), \
                        mock.patch.object(MODULE.client_graphics, "select_driver") as driver, self.assertRaises(ValueError):
                    runtime.run_graphics()
                driver.assert_not_called()
                self.assertEqual(stages, ["graphicsVulkan", "graphicsIdentity"])
                self.assertFalse((self.state / "graphics-preflight.json").exists())

    def test_mesa262_cli_is_strict_default_off_exclusive_and_software_records_ignored_request(self):
        for arguments, enabled in (([], False), (["--mesa262-driver"], True),
                                   (["--mesa262-driver", "--linear-presentation"], True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                settings = constructor.call_args.args[0]
                self.assertEqual(settings.mesa262_driver, enabled)
                self.assertFalse(settings.a740_pc_mode)
                self.assertFalse(settings.shm_presentation)
                self.assertEqual(settings.linear_presentation, "--linear-presentation" in arguments)
        for arguments in (["--mesa262-driver", "1"], ["--mesa262-driver", "26.2.4"],
                          ["--mesa262-driver", "--a740-pc-mode"], ["--mesa262-driver", "--shm-presentation"]):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
                MODULE.main(["start", *arguments])
            constructor.assert_not_called()
        for invalid in (1, "1", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.Runtime(MODULE.Settings(mesa262_driver=invalid))
        for mode in MODULE.client_graphics.MODES:
            for flag in ("a740_pc_mode", "shm_presentation"):
                with self.subTest(mode=mode, flag=flag), self.assertRaises(ValueError):
                    MODULE.Runtime(MODULE.Settings(**{"graphics_mode": mode, "mesa262_driver": True, flag: True}))
        runtime = MODULE.Runtime(self.settings(mesa262_driver=True, linear_presentation=True))
        with mock.patch.object(runtime, "wait_graphics") as helper:
            report = runtime.run_graphics()
        helper.assert_not_called()
        self.assertTrue(report["optimizations"]["requestedMesa262Driver"])
        self.assertFalse(report["optimizations"]["mesa262Driver"])
        self.assertFalse(report["mesa262DriverQualification"]["selectedIdentityGatePassed"])
        self.assertFalse(any(key.startswith(("MESA_", "VK_", "TU_", "DXVK_")) for key in runtime.environment()))

    def test_mesa262_fresh_old_and_selected_chip_gates_then_render_and_reset_preserve_cache(self):
        for linear in (False, True):
            with self.subTest(linear=linear), self.cleanup_failed_fixture_session():
                process = self.launch(graphics=True, mesa262_driver=True, linear_presentation=linear)
                running = self.wait_status("running", timeout=MESA262_SESSION_TIMEOUT)
                report = running["graphicsPreflight"]
                qualification = report["mesa262DriverQualification"]
                for field in ("hardwareIdentityGatePassed", "selectedIdentityGatePassed", "selectedDriverVulkanPresentationPassed",
                              "nativeD3d11ShaderReadbackPassed", "visibleRfbFramesPassed", "immediatePresentationPassed"):
                    self.assertTrue(qualification[field])
                self.assertEqual(qualification["mesaVersion"], "26.2.4")
                self.assertEqual(qualification["driverSha256"], "5" * 64)
                self.assertEqual(qualification["mesaSourceSha256"], MODULE.client_graphics.MESA262_EXPERIMENT["mesaSourceSha256"])
                self.assertEqual(qualification["identity"]["device_id"], 0x43050a01)
                self.assertFalse(qualification["physicalBenefitVerified"])
                self.assertTrue(running["optimizations"]["mesa262Driver"])
                self.assertEqual(report["vulkan"]["driver_version"], (26 << 22) | (2 << 12) | 4)
                identity_history = json.loads((self.state / "graphicsIdentity.environment-history.json").read_text())[-2:]
                self.assertEqual([Path(item["driverLibrary"]).name for item in identity_history],
                                 ["turnip-26.0.0.so", "turnip-26.2.4.so"])
                self.assertEqual([item["MESA_VK_WSI_DEBUG"] for item in identity_history], ["sw", "sw"])
                vulkan_history = json.loads((self.state / "graphicsVulkan.environment-history.json").read_text())[-(3 if linear else 2):]
                self.assertEqual([item["MESA_VK_WSI_DEBUG"] for item in vulkan_history],
                                 ["sw", "sw", "sw,linear"] if linear else ["sw", "sw"])
                for role in ("graphicsD3d", "client"):
                    environment = json.loads((self.state / (role + ".environment.json")).read_text())
                    self.assertEqual(Path(environment["driverLibrary"]).name, "turnip-26.2.4.so")
                    self.assertEqual(environment["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.2.4"))
                    self.assertEqual(environment["MESA_VK_WSI_DEBUG"], "sw,linear" if linear else "sw")
                    self.assertIsNone(environment["EVE_X11_SHM_STAGING"])
                if linear:
                    self.assertEqual(report["linearPresentationQualification"]["identity"]["helper"], "eve-mesa262-driver-probe-1")
                    self.assertEqual(report["linearPresentationQualification"]["originalDriver"], "turnip-26.2.4.so")
                warm = self.state / "cache/mesa-26.2.4/warm"
                warm.write_bytes(b"preserved new cache")
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=4), 0)
                baseline = self.launch(graphics=True)
                restarted = self.wait_status("running", timeout=MESA262_SESSION_TIMEOUT)
                self.assertFalse(restarted["optimizations"]["mesa262Driver"])
                self.assertFalse(restarted["graphicsPreflight"]["mesa262DriverQualification"]["selectedIdentityGatePassed"])
                environment = json.loads((self.state / "client.environment.json").read_text())
                self.assertEqual(Path(environment["driverLibrary"]).name, "turnip-26.0.0.so")
                self.assertEqual(environment["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0"))
                self.assertEqual(warm.read_bytes(), b"preserved new cache")
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(baseline.wait(timeout=4), 0)

    def test_mesa262_failed_selected_hardware_formats_or_render_never_reuses_receipt_or_launches_game(self):
        for behavior in ("mesa262-wrong-version", "mesa262-wrong-device", "mesa262-software", "mesa262-wrong-chip",
                         "mesa262-fixture", "mesa262-old-probe", "mesa262-wrong-info", "mesa262-linear-unsupported",
                         "mesa262-final-bad", "graphicsD3d-bad", "graphicsD3d-display-bad", "graphicsD3d-policy-fifo"):
            with self.subTest(behavior=behavior), self.cleanup_failed_fixture_session():
                (self.state / "graphics-preflight.json").write_text(json.dumps({"hardwarePreflightPassed": True,
                    "mesa262DriverQualification": {"selectedIdentityGatePassed": True}}))
                process = self.launch(behavior, graphics=True, mesa262_driver=True, linear_presentation=True)
                self.assertEqual(process.wait(timeout=MESA262_SESSION_TIMEOUT), 1)
                self.assertEqual(self.wait_status("failed")["graphicsPreflight"], {})
                self.assertFalse((self.state / "graphics-preflight.json").exists())
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_mesa262_software_and_early_tls_failure_discard_prior_qualification(self):
        receipt = self.state / "graphics-preflight.json"
        receipt.write_text('{"mesa262DriverQualification":{"selectedIdentityGatePassed":true}}')
        failed = self.launch("gate-fails", graphics=True, mesa262_driver=True)
        self.assertEqual(failed.wait(timeout=5), 1)
        self.assertEqual(self.wait_status("failed")["graphicsPreflight"], {})
        self.assertFalse(receipt.exists())
        self.assertFalse((self.state / "graphicsIdentity.pid").exists())
        receipt.write_text('{"mesa262DriverQualification":{"selectedIdentityGatePassed":true}}')
        software = self.launch(mesa262_driver=True)
        running = self.wait_status("running")
        self.assertTrue(running["optimizations"]["requestedMesa262Driver"])
        self.assertFalse(running["optimizations"]["mesa262Driver"])
        self.assertFalse(running["graphicsPreflight"]["mesa262DriverQualification"]["selectedIdentityGatePassed"])
        self.assertFalse(receipt.exists())
        environment = json.loads((self.state / "client.environment.json").read_text())
        self.assertIsNone(environment["driverLibrary"])
        self.assertIsNone(environment["MESA_SHADER_CACHE_DIR"])
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(software.wait(timeout=4), 0)

    def test_stop_and_timeout_during_selected_mesa262_vulkan_or_chip_identity_clean_helpers_without_game(self):
        for role in ("graphicsVulkan", "graphicsIdentity"):
            behavior = "mesa262-selected-" + role + "-hangs"
            for stop in (True, False):
                with self.subTest(role=role, stop=stop):
                    process = self.launch(behavior, graphics=True, mesa262_driver=True)
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        try:
                            environment = json.loads((self.state / (role + ".environment.json")).read_text())
                            journal = json.loads((self.state / "run/processes.json").read_text())
                            identity = journal.get(role + "Identity", {})
                            if (Path(environment["driverLibrary"]).name == "turnip-26.2.4.so"
                                    and identity.get("pid") == environment["processId"] and MODULE.identity_alive(identity)):
                                break
                        except (OSError, ValueError, KeyError, TypeError):
                            pass
                        time.sleep(.01)
                    else: self.fail("Selected Mesa 26.2.4 stage did not start")
                    if stop: (self.state / "run/stop").write_text("stop")
                    self.assertEqual(process.wait(timeout=5), 0 if stop else 1)
                    self.assertEqual(self.wait_status("stopped" if stop else "failed")["graphicsPreflight"], {})
                    self.assertFalse((self.state / "graphics-preflight.json").exists())
                    self.assertFalse((self.state / "client.pid").exists())
                    self.assertFalse((self.state / "run/processes.json").exists())

    def test_shm_cli_is_strict_default_off_mutually_exclusive_and_software_ignores_it(self):
        for arguments, enabled in (([], False), (["--shm-presentation"], True),
                                   (["--shm-presentation", "--linear-presentation"], True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                settings = constructor.call_args.args[0]
                self.assertEqual(settings.shm_presentation, enabled)
                self.assertFalse(settings.a740_pc_mode)
                self.assertFalse(settings.sysmem_rendering)
        for arguments in (["--shm-presentation", "1"], ["--shm-presentation", "arbitrary"],
                          ["--shm-presentation", "--a740-pc-mode"]):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
                MODULE.main(["start", *arguments])
            constructor.assert_not_called()
        for invalid in (1, "1", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.Runtime(MODULE.Settings(shm_presentation=invalid))
        for mode in MODULE.client_graphics.MODES:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                MODULE.Runtime(MODULE.Settings(graphics_mode=mode, a740_pc_mode=True, shm_presentation=True))
        runtime = MODULE.Runtime(self.settings(shm_presentation=True))
        with mock.patch.dict(os.environ, EVE_X11_SHM_STAGING="1"), mock.patch.object(runtime, "wait_graphics") as helper:
            self.assertNotIn("EVE_X11_SHM_STAGING", runtime.environment())
            report = runtime.run_graphics()
        helper.assert_not_called()
        self.assertTrue(report["optimizations"]["requestedShmPresentation"])
        self.assertFalse(report["optimizations"]["shmPresentation"])
        self.assertFalse(report["shmPresentationQualification"]["transportActivationVerified"])

    def test_shm_fresh_driver_completed_transfers_and_final_environment_reset_on_restart(self):
        for linear, sysmem, binning in ((True, False, False), (False, False, False), (True, True, True)):
            with self.subTest(linear=linear, sysmem=sysmem):
                (self.state / "fixture-graphicsIdentity.json").write_text(json.dumps(
                    linear_identity() if linear else a740_identity()))
                with mock.patch.dict(os.environ, EVE_X11_SHM_STAGING="arbitrary"):
                    process = self.launch(graphics=True, shm_presentation=True, linear_presentation=linear,
                                          sysmem_rendering=sysmem, disable_concurrent_binning=binning)
                running = self.wait_status("running")
                report = running["graphicsPreflight"]
                qualification = report["shmPresentationQualification"]
                for field in ("hardwareIdentityGatePassed", "selectedDriverVulkanPresentationPassed",
                              "selectedVulkanPresentationPassed", "nativeD3d11ShaderReadbackPassed",
                              "visibleRfbFramesPassed", "transportActivationVerified"):
                    self.assertTrue(qualification[field])
                self.assertEqual(qualification["completedPresents"], 3)
                self.assertFalse(qualification["nativeEffectVerified"])
                self.assertFalse(qualification["physicalBenefitVerified"])
                self.assertEqual(report["driverSelection"]["driver"], MODULE.client_graphics.SHM_DRIVER)
                self.assertTrue(running["optimizations"]["shmPresentation"])
                history = json.loads((self.state / "graphicsVulkan.environment-history.json").read_text())[-3:]
                self.assertEqual([env["EVE_X11_SHM_STAGING"] for env in history], [None, None, "1"])
                self.assertEqual([Path(env["driverLibrary"]).name for env in history],
                                 ["turnip-26.0.0.so", MODULE.client_graphics.SHM_DRIVER, MODULE.client_graphics.SHM_DRIVER])
                self.assertEqual(history[1]["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0-x11-shm"))
                identity = json.loads((self.state / "graphicsIdentity.environment.json").read_text())
                self.assertIsNone(identity["EVE_X11_SHM_STAGING"])
                self.assertEqual(Path(identity["driverLibrary"]).name, "turnip-26.0.0.so")
                for role in ("graphicsD3d", "client"):
                    env = json.loads((self.state / (role + ".environment.json")).read_text())
                    self.assertEqual(env["EVE_X11_SHM_STAGING"], "1")
                    self.assertEqual(env["MESA_VK_WSI_DEBUG"], "sw,linear" if linear else "sw")
                    self.assertEqual(env["TU_DEBUG"], "nocb,sysmem" if sysmem else None)
                    self.assertEqual(env["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0-x11-shm"))
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=4), 0)
                with mock.patch.dict(os.environ, EVE_X11_SHM_STAGING="1"):
                    baseline = self.launch(graphics=True)
                restarted = self.wait_status("running")
                self.assertFalse(restarted["optimizations"]["shmPresentation"])
                self.assertFalse(restarted["graphicsPreflight"]["shmPresentationQualification"]["transportActivationVerified"])
                env = json.loads((self.state / "client.environment.json").read_text())
                self.assertIsNone(env["EVE_X11_SHM_STAGING"])
                self.assertEqual(Path(env["driverLibrary"]).name, "turnip-26.0.0.so")
                self.assertEqual(env["MESA_SHADER_CACHE_DIR"], str(self.state / "cache/mesa-26.0.0"))
                self.assertNotIn("activeReports", restarted["graphicsPreflight"]["shmPresentationQualification"])
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(baseline.wait(timeout=4), 0)

    def test_shm_failed_identity_driver_rendering_or_transport_never_reuses_old_receipts_or_launches_game(self):
        for behavior in ("identity-unavailable", "graphicsIdentity-bad", "identity-variant-device",
                         "shm-driver-vulkan-bad", "shm-selected-vulkan-bad", "shm-vulkan-device",
                         "graphicsD3d-bad", "graphicsD3d-display-bad", "graphicsD3d-policy-fifo",
                         "shm-receipt-missing", "shm-receipt-short", "shm-receipt-duplicate",
                         "shm-receipt-fallback", "shm-receipt-malformed", "shm-receipts-only-vulkan"):
            with self.subTest(behavior=behavior):
                (self.state / "graphics-preflight.json").write_text(json.dumps({"hardwarePreflightPassed": True,
                    "shmPresentationQualification": {"transportActivationVerified": True}}))
                process = self.launch(behavior, graphics=True, shm_presentation=True)
                self.assertEqual(process.wait(timeout=5), 1)
                failed = self.wait_status("failed")
                self.assertEqual(failed["graphicsPreflight"], {})
                self.assertFalse((self.state / "graphics-preflight.json").exists())
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_shm_early_tls_failure_discards_previous_transport_receipt(self):
        receipt = self.state / "graphics-preflight.json"
        receipt.write_text('{"shmPresentationQualification":{"transportActivationVerified":true}}')
        process = self.launch("gate-fails", graphics=True, shm_presentation=True, linear_presentation=True)
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertEqual(self.wait_status("failed")["graphicsPreflight"], {})
        self.assertFalse(receipt.exists())
        self.assertFalse((self.state / "graphicsIdentity.pid").exists())
        self.assertFalse((self.state / "client.pid").exists())

    def test_shm_software_recovery_scrubs_inherited_staging_and_previous_qualification(self):
        (self.state / "graphics-preflight.json").write_text('{"shmPresentationQualification":{"transportActivationVerified":true}}')
        with mock.patch.dict(os.environ, EVE_X11_SHM_STAGING="1"):
            process = self.launch(shm_presentation=True)
        running = self.wait_status("running")
        self.assertEqual(running["graphicsMode"], "software")
        self.assertTrue(running["optimizations"]["requestedShmPresentation"])
        self.assertFalse(running["optimizations"]["shmPresentation"])
        self.assertFalse(running["graphicsPreflight"]["shmPresentationQualification"]["transportActivationVerified"])
        env = json.loads((self.state / "client.environment.json").read_text())
        self.assertIsNone(env["EVE_X11_SHM_STAGING"])
        self.assertIsNone(env["driverLibrary"])
        self.assertIsNone(env["MESA_SHADER_CACHE_DIR"])
        self.assertFalse((self.state / "graphics-preflight.json").exists())
        self.assertNotIn("graphicsVulkanIdentity", running)
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(process.wait(timeout=4), 0)

    def test_stop_and_timeout_during_shm_identity_or_selected_vulkan_clean_helpers_without_game(self):
        for behavior, role in (("graphicsIdentity-hangs", "graphicsIdentity"), ("shm-selected-hangs", "graphicsVulkan")):
            for stop in (True, False):
                with self.subTest(behavior=behavior, stop=stop):
                    process = self.launch(behavior, graphics=True, shm_presentation=True)
                    if behavior == "shm-selected-hangs":
                        deadline = time.monotonic() + 4
                        while time.monotonic() < deadline:
                            path = self.state / "graphicsVulkan.environment.json"
                            try:
                                env = json.loads(path.read_text())
                                journal = json.loads((self.state / "run/processes.json").read_text())
                                identity = journal.get("graphicsVulkanIdentity", {})
                                if (env["EVE_X11_SHM_STAGING"] == "1" and identity.get("pid") == env["processId"]
                                        and MODULE.identity_alive(identity)):
                                    break
                            except (OSError, ValueError):
                                pass
                            time.sleep(.01)
                        else: self.fail("Selected SHM Vulkan stage did not start")
                    self.wait_role(role)
                    if stop: (self.state / "run/stop").write_text("stop")
                    self.assertEqual(process.wait(timeout=5), 0 if stop else 1)
                    self.assertTrue(self.wait_status("stopped" if stop else "failed")["cleanShutdown"])
                    self.assertFalse((self.state / "client.pid").exists())
                    self.assertFalse((self.state / "graphics-preflight.json").exists())
                    self.assertFalse((self.state / "run/processes.json").exists())

    def test_server_loss_after_graphics_prevents_eve(self):
        process = self.launch("graphics-server-lost", graphics=True)
        self.assertEqual(process.wait(timeout=5), 1)
        failed = self.wait_status("failed")
        self.assertIn("server session exited", failed["error"])
        self.assertTrue((self.state / "graphicsD3d.pid").exists())
        self.assertFalse((self.state / "client.pid").exists())
        self.assertFalse((self.state / "run/processes.json").exists())

    def test_stop_and_timeout_during_each_graphics_helper_clean_all_roles(self):
        for role in ("graphicsVulkan", "graphicsD3d"):
            with self.subTest(role=role, action="stop"):
                process = self.launch(role + "-hangs", graphics=True)
                self.wait_role(role)
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=4), 0)
                self.assertTrue(self.wait_status("stopped")["cleanShutdown"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())
            with self.subTest(role=role, action="timeout"):
                process = self.launch(role + "-hangs", graphics=True)
                self.assertEqual(process.wait(timeout=5), 1)
                failed = self.wait_status("failed")
                self.assertIn(role, failed["error"])
                self.assertIn("timed out", failed["error"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_killed_supervisor_during_each_graphics_helper_recovers_owned_groups(self):
        for role in ("graphicsVulkan", "graphicsD3d"):
            with self.subTest(role=role):
                process = self.launch(role + "-hangs", graphics=True)
                journal = self.wait_role(role)
                process.kill()
                process.wait(timeout=2)
                self.assertTrue(MODULE.identity_alive(journal[role + "Identity"]))
                runtime = MODULE.Runtime(self.settings(graphics=True))
                with runtime.exclusive():
                    runtime.recover()
                stopped = self.wait_status("stopped")
                self.assertTrue(stopped["cleanShutdown"])
                for owned in MODULE.OWNED_ROLES:
                    self.assertFalse(MODULE.identity_alive(journal.get(owned + "Identity")))
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_graphics_failure_reaps_inherited_helper_orphans(self):
        for role in ("graphicsVulkan", "graphicsD3d"):
            with self.subTest(role=role):
                process = self.launch(role + "-orphan", graphics=True)
                self.assertEqual(process.wait(timeout=5), 1)
                self.wait_status("failed")
                orphan = int((self.state / "orphan.pid").read_text())
                record = MODULE.process_record(orphan)
                self.assertTrue(record is None or record["state"] == "Z")
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_display_or_wineserver_loss_during_graphics_prevents_eve(self):
        for role in ("display", "wineServer"):
            with self.subTest(role=role):
                process = self.launch("graphicsD3d-hangs", graphics=True)
                journal = self.wait_role("graphicsD3d")
                os.kill(journal[role + "Identity"]["pid"], signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 1)
                self.assertIn(role, self.wait_status("failed")["error"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())

    def test_retail_cli_cannot_substitute_graphics_commands_or_accept_fixture_mode(self):
        for flags in (("--graphics-mode", "fixture"), ("--vulkan-command", "/bin/true"),
                      ("--d3d-command", "/bin/true"), ("--allow-software-qualification",),
                      ("--performance-profile", "unlimited"), ("--diagnostic-hud", "full")):
            with self.subTest(flags=flags), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                MODULE.main(["start", *flags])
            self.assertEqual(error.exception.code, 2)
            constructor.assert_not_called()

    def test_cli_routes_only_selected_profiles_and_boolean_hud(self):
        for arguments, profile, hud in (([], "responsive", False),
                                        (["--performance-profile", "responsive", "--diagnostic-hud"], "responsive", True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                selected = constructor.call_args.args[0]
                self.assertEqual(selected.performance_profile, profile)
                self.assertEqual(selected.diagnostic_hud, hud)
                constructor.return_value.start.assert_called_once_with()

    def test_cli_routes_only_boolean_native_optimization_switches(self):
        for arguments, binning, lrcpc2 in (([], False, False), (["--disable-concurrent-binning"], True, False),
                                           (["--disable-lrcpc2"], False, True),
                                           (["--disable-concurrent-binning", "--disable-lrcpc2"], True, True)):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch.object(MODULE.signal, "signal"):
                self.assertEqual(MODULE.main(["start", *arguments]), 0)
                selected = constructor.call_args.args[0]
                self.assertEqual(selected.disable_concurrent_binning, binning)
                self.assertEqual(selected.disable_lrcpc2, lrcpc2)
        for arguments in (["--disable-lrcpc2", "enablelrcpc2"], ["--disable-concurrent-binning", "forcecb"]):
            with self.subTest(arguments=arguments), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                MODULE.main(["start", *arguments])
            self.assertEqual(error.exception.code, 2)
            constructor.assert_not_called()

    def test_native_optimization_switches_strip_inherited_fex_and_reach_helpers_and_game(self):
        with mock.patch.dict(os.environ, FEX_TSOENABLED="0", FEX_HOSTFEATURES="enablelrcpc2", TU_DEBUG="forcecb"):
            runtime = MODULE.Runtime(self.settings(graphics=True))
            self.assertNotIn("FEX_TSOENABLED", runtime.environment())
            self.assertNotIn("FEX_HOSTFEATURES", runtime.environment())
            self.assertNotIn("TU_DEBUG", runtime.environment())
            for binning, lrcpc2 in ((True, False), (False, True)):
                process = self.launch(graphics=True, disable_concurrent_binning=binning, disable_lrcpc2=lrcpc2)
                running = self.wait_status("running")
                receipt = running["optimizations"]
                self.assertEqual(receipt, MODULE.client_graphics.optimization_settings("turnip-dxvk", binning, lrcpc2))
                self.assertEqual(running["graphicsPreflight"]["optimizations"], receipt)
                self.assertFalse(running["cpuTopology"]["effectiveFexFeaturesObserved"])
                for role in ("graphicsVulkan", "graphicsD3d", "client"):
                    environment = json.loads((self.state / (role + ".environment.json")).read_text())
                    self.assertEqual(environment["TU_DEBUG"], "nocb" if binning else None)
                    self.assertEqual(environment["FEX_HOSTFEATURES"], "disablelrcpc2" if lrcpc2 else None)
                    self.assertIsNone(environment["FEX_TSOENABLED"])
                (self.state / "run/stop").write_text("stop")
                self.assertEqual(process.wait(timeout=4), 0)
                (self.state / "run/status.json").unlink()
            software = MODULE.Runtime(self.settings(disable_concurrent_binning=True, disable_lrcpc2=True))
            self.assertFalse(software.optimizations["disableConcurrentBinning"])
            self.assertFalse(software.optimizations["disableLrcpc2"])
            self.assertNotIn("TU_DEBUG", software.environment())
            self.assertNotIn("FEX_HOSTFEATURES", software.environment())

    def test_selected_profile_controls_display_rate_and_gpu_environment(self):
        for mode, profile, rate in (("turnip-dxvk", "throughput", 60),
                                    ("turnip-dxvk", "responsive", 30),
                                    ("turnip-dxvk", "render60", 30), ("turnip-dxvk", "queue2", 30),
                                    ("turnip-dxvk", "display60", 60),
                                    ("software", "throughput", 15), ("software", "responsive", 15)):
            with self.subTest(mode=mode, profile=profile):
                runtime = MODULE.Runtime(MODULE.Settings(state=self.state, graphics_mode=mode,
                                                         performance_profile=profile, diagnostic_hud=True))
                command = runtime.default_display_command()
                self.assertEqual(command[command.index("-FrameRate") + 1], str(rate))
                self.assertEqual(command[command.index("-geometry") + 1], "1280x720")
                env = runtime.environment()
                self.assertEqual(env["WINEESYNC"], "0")
                self.assertEqual(env["WINEFSYNC"], "0")
                if mode == "turnip-dxvk":
                    self.assertEqual(env["DXVK_HUD"], "devinfo,fps,frametimes,gpuload,cs,compiler")
                else:
                    self.assertFalse(any(key.startswith(("DXVK_", "VK_", "MESA_")) for key in env))

    def test_responsive_profile_round_trips_status_and_keeps_hud_out_of_pixel_qualification(self):
        process = self.launch(graphics=True, performance_profile="responsive", diagnostic_hud=True)
        running = self.wait_status("running")
        expected = MODULE.client_graphics.performance_settings("turnip-dxvk", "responsive", True)
        self.assertEqual(running["performance"], expected)
        self.assertEqual(running["graphicsPreflight"]["performance"], expected)
        helper = json.loads((self.state / "graphicsD3d.environment.json").read_text())
        self.assertIsNone(helper["DXVK_HUD"])
        client = json.loads((self.state / "client.environment.json").read_text())
        self.assertEqual(client["DXVK_HUD"], "devinfo,fps,frametimes,gpuload,cs,compiler")
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(process.wait(timeout=4), 0)

    def test_strict_tls_gate_failure_prevents_any_eve_process(self):
        for behavior in ("unsafe-tls", "wrong-ca", "unsafe-gateway", "gate-fails"):
            with self.subTest(behavior=behavior):
                (self.state / "run/status.json").unlink(missing_ok=True)
                process = self.launch(behavior)
                self.assertEqual(process.wait(timeout=4), 1)
                failed = self.wait_status("failed")
                self.assertFalse(failed["ready"])
                self.assertFalse((self.state / "client.pid").exists())
                self.assertFalse((self.state / "run/processes.json").exists())
                if behavior == "gate-fails":
                    self.assertIn("stage=tls-send, win32_error=12175", failed["error"])

    def test_eve_early_exit_zero_is_not_startup_success(self):
        process = self.launch("early-zero")
        self.assertEqual(process.wait(timeout=4), 1)
        failed = self.wait_status("failed")
        self.assertIn("client exited unexpectedly with code 0", failed["error"])
        self.assertFalse((self.state / "launch-observation.json").exists())

    def test_observed_client_exit_zero_cleans_session_without_reporting_failure(self):
        process = self.launch()
        running = self.wait_status("running")
        os.kill(running["clientIdentity"]["pid"], signal.SIGTERM)
        self.assertEqual(process.wait(timeout=4), 0)
        stopped = self.wait_status("stopped")
        self.assertTrue(stopped["cleanShutdown"])
        self.assertEqual(stopped["exitReason"], "client-exit")
        self.assertEqual(stopped["clientExitCode"], 0)
        self.assertNotIn("error", stopped)
        for role in ("client", "display", "wineServer"):
            self.assertFalse(MODULE.identity_alive(running[role + "Identity"]))
        self.assertFalse((self.state / "run/processes.json").exists())
        self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")

    def test_unexpected_client_exit_reaps_inherited_orphan_group(self):
        process = self.launch("crash-orphan")
        self.wait_status("running")
        self.assertEqual(process.wait(timeout=5), 1)
        failed = self.wait_status("failed")
        self.assertFalse(failed["ready"])
        orphan = int((self.state / "orphan.pid").read_text())
        record = MODULE.process_record(orphan)
        self.assertTrue(record is None or record["state"] == "Z")
        self.assertFalse((self.state / "run/processes.json").exists())

    def test_server_session_loss_stops_owned_client(self):
        process = self.launch()
        self.wait_status("running")
        (self.state / "server-lost").write_text("lost")
        self.assertEqual(process.wait(timeout=8), 1)
        failed = self.wait_status("failed")
        self.assertIn("server session exited", failed["error"])
        self.assertFalse(MODULE.identity_alive(failed["clientIdentity"]))

    def test_wineserver_loss_stops_client_before_an_unowned_daemon_can_replace_it(self):
        process = self.launch()
        running = self.wait_status("running")
        os.kill(running["wineServerIdentity"]["pid"], signal.SIGTERM)
        self.assertEqual(process.wait(timeout=4), 1)
        failed = self.wait_status("failed")
        self.assertIn("wineServer exited unexpectedly", failed["error"])
        self.assertFalse(MODULE.identity_alive(failed["clientIdentity"]))

    def test_killed_supervisor_journal_recovers_only_its_owned_processes(self):
        process = self.launch()
        running = self.wait_status("running")
        process.kill()
        process.wait(timeout=2)
        self.assertTrue(MODULE.identity_alive(running["clientIdentity"]))
        runtime = MODULE.Runtime(self.settings())
        with runtime.exclusive():
            runtime.recover()
        stopped = self.wait_status("stopped")
        self.assertTrue(stopped["cleanShutdown"])
        for role in ("client", "wineServer", "display"):
            self.assertFalse(MODULE.identity_alive(running[role + "Identity"]))
        self.assertFalse((self.state / "run/processes.json").exists())
        self.assertEqual((self.content / "keep-client-files").read_text(), "unchanged")

    def test_native_logs_remain_bounded_with_high_volume_output(self):
        process = self.launch("chatty")
        self.wait_status("running")
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(process.wait(timeout=4), 0)
        logs = sorted((self.state / "logs").glob("client-client.log*"))
        self.assertLessEqual(len(logs), MODULE.LOG_HISTORY + 1)
        self.assertTrue(logs)
        self.assertTrue(all(path.stat().st_size <= 65536 for path in logs))

    def test_stale_journal_never_signals_unverified_reused_process_group(self):
        runtime = MODULE.Runtime(self.settings())
        identity = {"pid": 12345, "startTicks": "old"}
        with mock.patch.object(MODULE, "group_members", return_value=[{"pid": 12345, "startTicks": "new"}]), \
                mock.patch.object(MODULE, "identity_alive", return_value=False), \
                mock.patch.object(MODULE.os, "killpg") as kill:
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "Unverified"):
                runtime.signal_group(identity, [], signal.SIGTERM)
            kill.assert_not_called()

    def test_exited_graphics_leader_cannot_adopt_a_reused_group_into_journal(self):
        runtime = MODULE.Runtime(self.settings())
        runtime.children["graphicsVulkan"] = mock.Mock(pid=40001)
        old = {"pid": 40001, "startTicks": "old-leader"}
        runtime.identities = {"graphicsVulkanIdentity": old, "graphicsVulkanMembers": []}
        unrelated = [{"pid": 40001, "startTicks": "new-leader", "group": 40001, "session": 40001},
                     {"pid": 40002, "startTicks": "new-child", "group": 40001, "session": 40001}]
        snapshot = MODULE.server_runtime.ProcessSnapshot(1, {40001: unrelated})
        alive = lambda identity: isinstance(identity, dict) and identity.get("startTicks", "").startswith("new")
        with mock.patch.object(MODULE.server_runtime.ProcessSnapshot, "capture", return_value=snapshot), \
                mock.patch.object(MODULE, "identity_alive", side_effect=alive), \
                mock.patch.object(MODULE, "group_members", return_value=unrelated), \
                mock.patch.object(MODULE.os, "killpg") as kill:
            runtime.refresh_owned_processes()
            self.assertEqual(runtime.identities["graphicsVulkanMembers"], [])
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "Unverified"):
                runtime.signal_group(old, runtime.identities["graphicsVulkanMembers"], signal.SIGTERM)
            kill.assert_not_called()

    def test_exited_helper_keeps_only_previously_owned_descendant_identities(self):
        runtime = MODULE.Runtime(self.settings())
        runtime.children["graphicsD3d"] = mock.Mock(pid=40001)
        known = {"pid": 40002, "startTicks": "known-child"}
        runtime.identities = {"graphicsD3dIdentity": {"pid": 40001, "startTicks": "old-leader"},
                              "graphicsD3dMembers": [known]}
        members = [{**known, "group": 40001, "session": 40001},
                   {"pid": 40003, "startTicks": "unrecorded", "group": 40001, "session": 40001}]
        snapshot = MODULE.server_runtime.ProcessSnapshot(1, {40001: members})
        with mock.patch.object(MODULE.server_runtime.ProcessSnapshot, "capture", return_value=snapshot), \
                mock.patch.object(MODULE, "identity_alive", side_effect=lambda value: value == known):
            runtime.refresh_owned_processes()
        self.assertEqual(runtime.identities["graphicsD3dMembers"], [known])

    def test_network_gate_requires_immediate_tcp_and_udp_eacces(self):
        denied = mock.MagicMock()
        denied.__enter__.return_value = denied
        denied.connect.side_effect = PermissionError(errno.EACCES, "blocked by native gate")
        denied.sendto.side_effect = PermissionError(errno.EACCES, "blocked by native gate")
        with mock.patch.object(MODULE.socket, "socket", return_value=denied):
            MODULE.Runtime.verify_network_gate()
        self.assertEqual(denied.connect.call_count, 1)
        self.assertEqual(denied.sendto.call_count, 1)
        denied.connect.side_effect = TimeoutError("ordinary network timeout")
        with mock.patch.object(MODULE.socket, "socket", return_value=denied):
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "did not reject"):
                MODULE.Runtime.verify_network_gate()

    def test_wineserver_readiness_waits_for_delayed_private_unix_socket(self):
        runtime = MODULE.Runtime(MODULE.Settings(state=self.state, tick=.01, startup_timeout=1))
        path = self.root / "private-wine.sock"
        runtime.identities["wineServerIdentity"] = {"pid": 34567, "startTicks": "recorded"}
        ready = threading.Event()
        finish = threading.Event()

        def own_server():
            # The executor disallows creating AF_UNIX sockets. Simulate the
            # observed inode and peer credentials of a delayed private daemon.
            time.sleep(.1)
            ready.set()
            finish.wait(timeout=2)

        owner = threading.Thread(target=own_server)
        owner.start()
        peer = mock.MagicMock()
        peer.__enter__.return_value = peer
        peer.getsockopt.return_value = struct.pack("3i", 34567, os.getuid(), os.getgid())
        started = time.monotonic()
        try:
            with mock.patch.object(runtime, "wine_socket", return_value=path), \
                    mock.patch.object(runtime, "check_child") as child, \
                    mock.patch.object(Path, "is_socket", side_effect=lambda: ready.is_set()), \
                    mock.patch.object(MODULE.socket, "socket", return_value=peer):
                runtime.wait_wineserver()
            self.assertTrue(ready.is_set())
            self.assertGreaterEqual(time.monotonic() - started, .09)
            self.assertTrue(any(call.args == ("wineServer",) for call in child.call_args_list))
        finally:
            finish.set()
            owner.join(timeout=2)
        peer.connect.assert_called_once_with(str(path))

    def test_wineserver_socket_name_matches_pinned_prefix_device_and_inode(self):
        prefix = self.state / "prefix"
        prefix.mkdir()
        record = prefix.stat()
        runtime = MODULE.Runtime(MODULE.Settings(state=self.state))
        expected = Path("/tmp") / (".wine-" + str(os.getuid())) / (
            "server-" + format(record.st_dev, "x") + "-" + format(record.st_ino, "x")) / "socket"
        self.assertEqual(runtime.wine_socket(), expected)

    def test_wineserver_socket_left_after_owner_exit_is_not_ready(self):
        runtime = MODULE.Runtime(MODULE.Settings(state=self.state, startup_timeout=.2, tick=.01))
        path = self.root / "stale-wine.sock"
        with mock.patch.object(runtime, "wine_socket", return_value=path), \
                mock.patch.object(Path, "is_socket", return_value=True), \
                mock.patch.object(runtime, "check_child", side_effect=MODULE.RuntimeErrorDetail("owned Wine server exited")):
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "owned Wine server exited"):
                runtime.wait_wineserver()

    def test_wineserver_socket_peer_identity_rejects_another_daemon_and_refused_socket(self):
        runtime = MODULE.Runtime(MODULE.Settings(state=self.state))
        runtime.identities["wineServerIdentity"] = {"pid": 34567, "startTicks": "recorded"}
        peer = mock.MagicMock()
        peer.__enter__.return_value = peer
        peer.getsockopt.return_value = struct.pack("3i", 45678, os.getuid(), os.getgid())
        with mock.patch.object(MODULE.socket, "socket", return_value=peer):
            self.assertFalse(runtime.wine_socket_owned(self.root / "stale-wine.sock"))
            peer.getsockopt.return_value = struct.pack("3i", 34567, os.getuid(), os.getgid())
            self.assertTrue(runtime.wine_socket_owned(self.root / "owned-wine.sock"))
            peer.connect.side_effect = ConnectionRefusedError(errno.ECONNREFUSED, "stale socket")
            self.assertFalse(runtime.wine_socket_owned(self.root / "stale-wine.sock"))

    def preflight_runtime(self):
        marker = self.root / "marker.json"
        marker.write_text(json.dumps({"format": 2, "runtime": "fex-arm64ec-1", "architecture": "arm64",
                                      "wine_commit": MODULE.wine_trust_overlay.WINE_COMMIT}))
        overlay = self.root / "wine-trust-overlay.json"
        bound_root = self.root / "bound-runtime"
        files = []
        for target, (asset, machines) in MODULE.wine_trust_overlay.TARGETS.items():
            machine = next(iter(machines))
            pe = bytearray(70)
            pe[:2] = b"MZ"
            struct.pack_into("<I", pe, 60, 64)
            pe[64:68] = b"PE\0\0"
            struct.pack_into("<H", pe, 68, machine)
            (self.root / asset).write_bytes(pe)
            bound = bound_root / target
            bound.parent.mkdir(parents=True, exist_ok=True)
            bound.write_bytes(pe)
            files.append({"target": target, "asset": asset, "machine": machine,
                          "sha256": hashlib.sha256(pe).hexdigest(), "baselineSha256": "a" * 64})
        overlay.write_text(json.dumps({"format": 1, "runtime": "fex-arm64ec-1", "overlay": "wine-empty-subject-1",
                                       "wine_commit": MODULE.wine_trust_overlay.WINE_COMMIT, "files": files}))
        fake_elf = b"\x7fELF\x02" + b"\0" * 13 + b"\xb7\0"
        wine = self.root / "wine"
        wine.write_bytes(fake_elf)
        wineserver = self.root / "wineserver"
        wineserver.write_bytes(fake_elf)
        gate = self.root / "gate.exe"
        gate.write_bytes(b"original fixture helper")
        window = bytearray(192)
        window[:2] = b"MZ"
        window[60:64] = (64).to_bytes(4, "little")
        window[64:68] = b"PE\0\0"
        window[68:70] = (0x8664).to_bytes(2, "little")
        window[88:90] = (0x20b).to_bytes(2, "little")
        window[156:158] = (3).to_bytes(2, "little")
        gate.with_name("eve-client-window.exe").write_bytes(window)
        (self.state / "prefix").mkdir()
        (self.state / "prefix/system.reg").write_text("existing qualified prefix")
        (self.state / "probe.json").write_text(json.dumps({"translated_x64_probe_passed": True, "exit_code": 37}))
        rows = [{"file": "exefile.exe", "sha256": "exact-hash"}]
        (self.content / "eve-client-content.json").write_text(json.dumps({
            "format": 1, "build": 3396210, "resources": {"complete": True, "indexed_entries": 125116}, "binaries": rows}))
        (self.content / "tq/start.ini").write_text("build=3396210\nserver=127.0.0.1\ncryptoPack=Placebo\n")
        (self.state / "trust").mkdir()
        (self.state / "trust/evejs-ca.pem").write_text(CA_PEM)
        (self.state / "status.json").write_text(json.dumps({"phase": "content_prepared", "trust": {
            "bundles_prepared": True, "ca_sha256": hashlib.sha256(CA_PEM.encode()).hexdigest()}}))
        runtime = MODULE.Runtime(MODULE.Settings(content=self.content, state=self.state, server_state=self.server,
                                               marker=marker, wine=str(wine), wineserver=str(wineserver), gate=gate,
                                               trust_overlay=overlay, trust_overlay_root=bound_root,
                                               graphics_mode="software",
                                               minimum_available_kib=0))
        return runtime, rows

    def window_runtime(self):
        runtime = MODULE.Runtime(MODULE.Settings(content=self.content, state=self.state, server_state=self.server,
                                               graphics_mode="software", tick=.001, window_start_timeout=.04,
                                               minimum_available_kib=0))
        runtime.run.mkdir(exist_ok=True)
        runtime.window_session = "a" * 32
        return runtime

    def write_window_receipt(self, runtime, **changes):
        value = {"format": 1, "helper": "eve-client-window-1", "session": runtime.window_session,
                 "phase": "child_created", "wrapperWindowsPid": 100, "childWindowsPid": 104,
                 "childExitCode": None, "elapsedMs": 10}
        value.update(changes)
        runtime.window_receipt.write_text(json.dumps(value))
        return value

    def test_normal_window_exit_requires_observed_session_bound_zero_receipt(self):
        runtime = self.window_runtime()
        self.write_window_receipt(runtime)
        runtime.check_window_receipt()
        self.write_window_receipt(runtime, phase="child_exited", childExitCode=0)
        with self.assertRaises(MODULE.RuntimeErrorDetail):
            runtime.check_window_receipt()
        with self.assertRaises(MODULE.ClientClosed):
            runtime.check_window_receipt(allow_normal_exit=True)
        self.assertEqual(runtime.window_report["childExitCode"], 0)
        for change in ({"childExitCode": 23}, {"childExitCode": None},
                       {"session": "b" * 32}, {"childWindowsPid": 108}):
            with self.subTest(change=change):
                self.write_window_receipt(runtime, phase="child_exited", **{"childExitCode": 0, **change})
                with self.assertRaises(MODULE.RuntimeErrorDetail):
                    runtime.check_window_receipt(allow_normal_exit=True)
        runtime.children["client"] = mock.Mock(poll=mock.Mock(return_value=0), returncode=0)
        self.write_window_receipt(runtime)
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "without EVE's final exit receipt"):
            runtime.check_child("client", allow_normal_exit=True)

    def test_production_wrapper_launch_clears_stale_receipt_and_scopes_nonce(self):
        runtime = self.window_runtime()
        runtime.window_receipt.write_text("stale receipt")
        with mock.patch.dict(os.environ, EVE_WINDOW_SESSION="stale-parent-secret"), \
                mock.patch.object(runtime, "spawn") as spawn:
            self.assertNotIn("EVE_WINDOW_SESSION", runtime.environment())
            runtime.launch_client()
        command = spawn.call_args.args[1]
        self.assertEqual(command, (runtime.s.wine, "Z:\\opt\\eve-android\\eve-client-window.exe"))
        self.assertFalse(runtime.window_receipt.exists())
        self.assertEqual(runtime.window_receipt.with_name(runtime.window_receipt.name + ".1").read_text(), "stale receipt")
        self.assertRegex(runtime.window_session, r"^[0-9a-f]{32}$")
        self.assertNotEqual(runtime.window_session, "a" * 32)
        self.assertEqual(spawn.call_args.kwargs["env"]["EVE_WINDOW_SESSION"], runtime.window_session)
        self.assertNotIn("exefile.exe", command)

    def test_new_wrapper_launch_rotates_once_and_unlinks_linked_current_receipt(self):
        runtime = self.window_runtime()
        previous = runtime.window_receipt.with_name(runtime.window_receipt.name + ".1")
        previous.write_text("older receipt")
        runtime.window_receipt.write_text("latest receipt")
        with mock.patch.object(runtime, "spawn"):
            runtime.launch_client()
        self.assertEqual(previous.read_text(), "latest receipt")
        outside = self.root / "private-outside-file"
        outside.write_text("untouched")
        runtime.window_receipt.symlink_to(outside)
        with mock.patch.object(runtime, "spawn"):
            runtime.launch_client()
        self.assertEqual(outside.read_text(), "untouched")
        self.assertEqual(previous.read_text(), "latest receipt")
        self.assertFalse(runtime.window_receipt.exists())
        runtime.window_receipt.write_text("X" * (MODULE.WINDOW_RECEIPT_LIMIT + 1))
        with mock.patch.object(runtime, "spawn"):
            runtime.launch_client()
        self.assertEqual(previous.read_text(), "latest receipt")
        self.assertFalse(runtime.window_receipt.exists())

    def test_fixture_client_command_retains_direct_launch_without_receipt_gate(self):
        runtime = MODULE.Runtime(self.settings())
        with mock.patch.object(runtime, "spawn") as spawn, mock.patch.object(runtime, "check_window_receipt") as receipt:
            runtime.launch_client()
            runtime.wait_window_child()
        self.assertIsNone(runtime.window_session)
        self.assertEqual(spawn.call_args.args[1], runtime.s.client_command)
        receipt.assert_not_called()

    def test_created_receipt_confirms_only_child_creation_and_filters_unknown_metadata(self):
        runtime = self.window_runtime()
        self.write_window_receipt(runtime, responsive=False, windowVisible=False, focusSucceeded=False,
                                  selectedWindow=0, rect=None, privatePassword="must-not-copy")
        with mock.patch.object(runtime, "require_server"), mock.patch.object(runtime, "refresh_owned_processes") as refresh:
            runtime.wait_window_child()
        self.assertEqual(refresh.call_count, 2)
        self.assertTrue(all(call == mock.call(persist=True) for call in refresh.call_args_list))
        self.assertEqual(runtime.window_report["phase"], "child_created")
        self.assertFalse(runtime.window_report["responsive"])
        self.assertNotIn("privatePassword", runtime.window_report)
        self.assertNotIn("ready", runtime.window_report)
        self.assertNotIn("graphics_qualified", runtime.window_report)
        self.write_window_receipt(runtime, phase="window_observed", responsive=False, focusSucceeded=False,
                                  probeTimeoutMs=50, rect={"left": -10, "top": 0, "right": 1270, "bottom": 720})
        observed = runtime.check_window_receipt()
        self.assertEqual(observed["phase"], "window_observed")
        self.assertFalse(observed["responsive"])
        self.assertFalse(observed["focusSucceeded"])
        self.assertEqual(observed["probeTimeoutMs"], 50)

    def test_window_receipt_rejects_stale_identity_terminal_phases_and_invalid_numbers(self):
        cases = ({"session": "b" * 32}, {"format": True}, {"wrapperWindowsPid": True},
                 {"childWindowsPid": 0}, {"childWindowsPid": 100}, {"elapsedMs": float("nan")},
                 {"childExitCode": 5}, {"phase": "unknown"}, {"selectedWindow": -1},
                 {"windowsOwned": 257}, {"responsive": 1}, {"windowVisible": "false"}, {"probeTimeoutMs": 51},
                 {"rect": {"left": 0, "top": 0, "right": 10, "bottom": True}},
                 {"phase": "failed"}, {"phase": "child_exited", "childExitCode": 0})
        for change in cases:
            with self.subTest(change=change):
                runtime = self.window_runtime()
                self.write_window_receipt(runtime, **change)
                with self.assertRaises(MODULE.RuntimeErrorDetail):
                    runtime.check_window_receipt()
        runtime = self.window_runtime()
        self.write_window_receipt(runtime)
        runtime.check_window_receipt()
        self.write_window_receipt(runtime, childWindowsPid=108)
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "invalid"):
            runtime.check_window_receipt()
        runtime.window_receipt.unlink()
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "disappeared"):
            runtime.check_window_receipt()

    def test_receipt_bound_malformed_and_symlink_rejection(self):
        runtime = self.window_runtime()
        for data in ("[]", "{", "X" * (MODULE.WINDOW_RECEIPT_LIMIT + 1)):
            runtime.window_receipt.write_text(data)
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "invalid"):
                runtime.check_window_receipt()
        runtime.window_receipt.unlink()
        outside = self.root / "outside-receipt"
        outside.write_text("private data")
        runtime.window_receipt.symlink_to(outside)
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "invalid"):
            runtime.check_window_receipt()

    def test_receipt_wait_timeout_stop_and_wrapper_exit_do_not_qualify_startup(self):
        runtime = self.window_runtime()
        with mock.patch.object(runtime, "require_server"), mock.patch.object(runtime, "refresh_owned_processes") as refresh:
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "did not confirm"):
                runtime.wait_window_child()
        self.assertGreater(refresh.call_count, 0)
        (runtime.run / "stop").write_text("stop")
        with self.assertRaises(InterruptedError):
            runtime.wait_window_child()
        (runtime.run / "stop").unlink()
        runtime.children["client"] = mock.Mock()
        runtime.children["client"].poll.return_value = 0
        runtime.children["client"].returncode = 0
        with mock.patch.object(runtime, "refresh_owned_processes"), \
                self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "exited unexpectedly"):
            runtime.wait_window_child()

    def test_window_helper_requires_nonlinked_original_x64_pe(self):
        runtime, _ = self.preflight_runtime()
        original = runtime.window_helper.read_bytes()
        runtime.verify_window_helper()
        for data in (b"", b"MZ", original[:68] + b"\xb7\xaa" + original[70:],
                     original[:156] + b"\x02\0" + original[158:]):
            runtime.window_helper.write_bytes(data)
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "original x64"):
                runtime.verify_window_helper()
        runtime.window_helper.unlink()
        outside = self.root / "linked-helper"
        outside.write_bytes(original)
        runtime.window_helper.symlink_to(outside)
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "original x64"):
            runtime.verify_window_helper()

    def test_receipt_confirmation_persists_real_owned_descendant_before_cleanup(self):
        runtime = self.window_runtime()
        wrapper = self.root / "wrapper-fixture.py"
        wrapper.write_text(
            "import json,os,pathlib,subprocess,sys,time\n"
            "state=pathlib.Path(sys.argv[1])\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            "(state/'child-native.pid').write_text(str(child.pid))\n"
            "value={'format':1,'helper':'eve-client-window-1','session':os.environ['EVE_WINDOW_SESSION'],"
            "'phase':'child_created','wrapperWindowsPid':100,'childWindowsPid':104,'childExitCode':None,'elapsedMs':10}\n"
            "temporary=state/'run/client-window-fixture.tmp'\n"
            "temporary.write_text(json.dumps(value))\n"
            "temporary.replace(state/'run/client-window.json')\n"
            "child.wait()\n")
        runtime.spawn("client", (sys.executable, str(wrapper), str(self.state)),
                      env={"PATH": "/usr/bin:/bin", "EVE_WINDOW_SESSION": runtime.window_session}, cwd=self.state)
        self.processes.append(runtime.children["client"])
        runtime.s = MODULE.Settings(content=self.content, state=self.state, server_state=self.server,
                                    graphics_mode="software", tick=.01, window_start_timeout=2,
                                    shutdown_timeout=.5, minimum_available_kib=0)
        try:
            with mock.patch.object(runtime, "require_server"):
                runtime.wait_window_child()
            child = int((self.state / "child-native.pid").read_text())
            journal = json.loads(runtime.journal.read_text())
            self.assertIn(child, {member["pid"] for member in journal["clientMembers"]})
            self.assertNotIn(104, {member["pid"] for member in journal["clientMembers"]})
            self.assertTrue(runtime.shutdown())
            self.assertFalse(MODULE.process_record(child) and MODULE.process_record(child)["state"] != "Z")
        finally:
            with contextlib.suppress(Exception):
                runtime.shutdown()

    def test_no_receipt_zombie_wrapper_journals_new_child_before_poll_and_cleans_it(self):
        runtime = self.window_runtime()
        wrapper = self.root / "wrapper-exit-fixture.py"
        wrapper.write_text(
            "import os,pathlib,subprocess,sys,time\n"
            "state=pathlib.Path(sys.argv[1])\n"
            "while not (state/'create-child').exists(): time.sleep(.002)\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            "(state/'child-native.pid').write_text(str(child.pid))\n"
            "os._exit(23)\n")
        process = runtime.spawn("client", (sys.executable, str(wrapper), str(self.state)),
                                env={"PATH": "/usr/bin:/bin", "EVE_WINDOW_SESSION": runtime.window_session}, cwd=self.state)
        self.processes.append(process)
        child = None
        try:
            before = json.loads(runtime.journal.read_text())["clientMembers"]
            self.assertEqual({member["pid"] for member in before}, {process.pid})
            (self.state / "create-child").write_text("go")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                leader = MODULE.process_record(process.pid)
                if leader and leader["state"] == "Z":
                    break
                time.sleep(.01)
            else:
                self.fail("Fixture wrapper did not become an unreaped zombie")
            child = int((self.state / "child-native.pid").read_text())
            self.assertIsNone(process.returncode)
            self.assertFalse(runtime.window_receipt.exists())
            with mock.patch.object(runtime, "require_server"), \
                    self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "exited unexpectedly with code 23"):
                runtime.wait_window_child()
            journal = json.loads(runtime.journal.read_text())
            self.assertIn(child, {member["pid"] for member in journal["clientMembers"]})
            self.assertEqual(process.returncode, 23)
            self.assertIsNone(runtime.window_child_ids)
            self.assertEqual(runtime.window_report, {})
            self.assertTrue(runtime.shutdown())
            record = MODULE.process_record(child)
            self.assertFalse(record and record["state"] != "Z")
        finally:
            with contextlib.suppress(Exception):
                runtime.shutdown()
            if child is not None:
                record = MODULE.process_record(child)
                if record and record["state"] != "Z":
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(child, signal.SIGKILL)

    def test_zombie_leader_fallback_rejects_reaped_or_mismatched_identity_group_and_session(self):
        member = {"pid": 40002, "startTicks": "20", "group": 40001, "session": 40001, "state": "S"}
        record = {"pid": 40001, "startTicks": "10", "group": 40001, "session": 40001, "state": "Z"}
        for changes in ({"pid": 123}, {"startTicks": "11"}, {"group": 123}, {"session": 123}, {"state": "S"}):
            with self.subTest(changes=changes):
                runtime = self.window_runtime()
                runtime.children["client"] = mock.Mock(pid=40001, returncode=None)
                runtime.identities["clientIdentity"] = {"pid": 40001, "startTicks": "10"}
                snapshot = MODULE.server_runtime.ProcessSnapshot(1, {40001: [member]})
                with mock.patch.object(MODULE.server_runtime.ProcessSnapshot, "capture", return_value=snapshot), \
                        mock.patch.object(MODULE, "process_record", return_value={**record, **changes}):
                    self.assertEqual(runtime.refresh_owned_processes().members(40001), [])
        runtime.children["client"].returncode = 23
        with mock.patch.object(MODULE.server_runtime.ProcessSnapshot, "capture", return_value=snapshot), \
                mock.patch.object(MODULE, "process_record", return_value=record) as read:
            self.assertEqual(runtime.refresh_owned_processes().members(40001), [])
        read.assert_not_called()

    def test_preflight_preserves_accepted_cache_and_rejects_rotated_ca(self):
        runtime, rows = self.preflight_runtime()
        with mock.patch.dict(os.environ, EVE_CLIENT_NETWORK_POLICY="loopback-v1"), \
                mock.patch.object(runtime, "verify_network_gate"), \
                mock.patch.object(runtime, "require_server"), \
                mock.patch.object(MODULE.client_prepare, "validate_binaries", return_value=rows), \
                mock.patch.object(MODULE.client_prepare, "check_resources", side_effect=AssertionError("repeat full cache validation")):
            value = runtime.preflight()
            self.assertEqual(value["contentBuild"], 3396210)
            self.assertEqual((self.state / "prefix/system.reg").read_text(), "existing qualified prefix")
            (self.server / "certs/xmpp-ca-cert.pem").write_text(CA_PEM + "\n")
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "CA changed"):
                runtime.preflight()

    def test_preflight_accepts_legacy_crlf_ca_receipt_without_repreparation(self):
        runtime, rows = self.preflight_runtime()
        source = self.server / "certs/xmpp-ca-cert.pem"
        source.write_bytes(CA_PEM.replace("\n", "\r\n").encode("ascii"))
        prepared = self.state / "status.json"
        value = json.loads(prepared.read_text())
        value["trust"]["ca_sha256"] = MODULE.client_prepare.digest(source)
        prepared.write_text(json.dumps(value))
        # Model the exact 0.1.2 state: original Forge PEM receipt and LF copy.
        before = {path: path.read_bytes() for path in
                  (prepared, self.state / "trust/evejs-ca.pem", self.state / "prefix/system.reg")}
        with mock.patch.dict(os.environ, EVE_CLIENT_NETWORK_POLICY="loopback-v1"), \
                mock.patch.object(runtime, "verify_network_gate"), \
                mock.patch.object(runtime, "require_server"), \
                mock.patch.object(MODULE.client_prepare, "validate_binaries", return_value=rows), \
                mock.patch.object(MODULE.client_prepare, "prepare_trust", side_effect=AssertionError("repeat preparation")), \
                mock.patch.object(MODULE.client_prepare, "check_resources", side_effect=AssertionError("repeat cache scan")):
            value = runtime.preflight()
        self.assertEqual(value["caDerSha256"], hashlib.sha256(b"fake-cert").hexdigest())
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original)

    def test_prepared_crlf_ca_launches_and_new_receipt_rejects_other_certificates(self):
        runtime, rows = self.preflight_runtime()
        source = self.server / "certs/xmpp-ca-cert.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=EveJS Forge PEM regression", "-keyout", str(self.root / "key.pem"),
                        "-out", str(source)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
        bundle = self.content / "tq/lib/certifi/cacert.pem"
        bundle.parent.mkdir(parents=True)
        bundle.write_text("# original client trust\n")
        trust = MODULE.client_prepare.prepare_trust(self.content, self.state, source)
        (self.state / "status.json").write_text(json.dumps({"phase": "content_prepared", "trust": trust}))
        imported = self.state / "trust/evejs-ca.pem"
        self.assertNotEqual(MODULE.client_prepare.digest(source), MODULE.client_prepare.digest(imported))
        with mock.patch.dict(os.environ, EVE_CLIENT_NETWORK_POLICY="loopback-v1"), \
                mock.patch.object(runtime, "verify_network_gate"), \
                mock.patch.object(runtime, "require_server"), \
                mock.patch.object(MODULE.client_prepare, "validate_binaries", return_value=rows):
            runtime.preflight()
            # Formatting changes preserve the same DER-bound receipt.
            source.write_bytes(imported.read_bytes() + b"\n")
            runtime.preflight()
            valid_imported = imported.read_bytes()
            imported.write_text(CA_PEM)
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "CA changed"):
                runtime.preflight()
            imported.write_bytes(valid_imported)
            source.write_text(CA_PEM)
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "CA changed"):
                runtime.preflight()
            imported.write_text(CA_PEM)
            # Replacing both copies still cannot bypass the preparation receipt.
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "CA changed"):
                runtime.preflight()

    def test_preflight_explains_missing_malformed_and_multiple_ca_copies(self):
        runtime, rows = self.preflight_runtime()
        imported = self.state / "trust/evejs-ca.pem"
        with mock.patch.dict(os.environ, EVE_CLIENT_NETWORK_POLICY="loopback-v1"), \
                mock.patch.object(runtime, "verify_network_gate"), \
                mock.patch.object(MODULE.client_prepare, "validate_binaries", return_value=rows):
            for data in (None, b"not a certificate", CA_PEM.encode() * 2, b"-----BEGIN CERTIFICATE-----\nA===\n-----END CERTIFICATE-----\n"):
                with self.subTest(data=data):
                    if data is None:
                        imported.unlink()
                    else:
                        imported.write_bytes(data)
                    with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "CA copy is missing or invalid"):
                        runtime.preflight()

    def test_preflight_rejects_receipt_hash_and_missing_native_network_opt_in(self):
        runtime, rows = self.preflight_runtime()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "native per-session"):
                runtime.preflight()
        with mock.patch.dict(os.environ, EVE_CLIENT_NETWORK_POLICY="loopback-v1"), \
                mock.patch.object(runtime, "verify_network_gate"), \
                mock.patch.object(MODULE.client_prepare, "validate_binaries", return_value=[{"file": "exefile.exe", "sha256": "changed"}]):
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "binary receipt"):
                runtime.preflight()

    def test_memory_reserve_failure_does_not_apply_preparation_address_space_limit(self):
        runtime = MODULE.Runtime(MODULE.Settings(minimum_available_kib=1024**2))
        with mock.patch.object(MODULE, "available_memory_kib", return_value=1024), \
                mock.patch.object(MODULE.client_prepare, "limit_preparation_memory", side_effect=AssertionError("client must not inherit preparation cap")):
            with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "before exhausting Android memory"):
                runtime.memory_check()


if __name__ == "__main__":
    unittest.main()
