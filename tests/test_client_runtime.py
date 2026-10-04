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
from test_client_graphics import d3d_success, display_success, vulkan_success

BACKEND = Path(__file__).resolve().parents[1] / "backend/client_runtime.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("eve_client_runtime", BACKEND)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CA_PEM = "-----BEGIN CERTIFICATE-----\nZmFrZS1jZXJ0\n-----END CERTIFICATE-----\n"
OFFLINE_HEALTH = {"status": "ok", "service": "express-secondary", "gatewayMode": "local",
                  "offlinePolicy": {"version": 2, "proxyForwarding": "disabled", "clientFeatureFlags": "defaults"}}

FIXTURE = r'''
import hashlib, json, os, pathlib, signal, socket, subprocess, sys, threading, time
mode, state, port, behavior = sys.argv[1:]
state = pathlib.Path(state)
port = int(port)
(state / (mode + '.pid')).write_text(str(os.getpid()))
if mode in ('graphicsVulkan', 'graphicsD3d'):
    if behavior == mode + '-hangs':
        def finish_graphics(*args):
            (state / (mode + '.stopped')).write_text('graceful')
            sys.exit(0)
        signal.signal(signal.SIGTERM, finish_graphics)
        while True: time.sleep(.03)
    if behavior == mode + '-orphan':
        subprocess.Popen([sys.executable, __file__, 'orphan', str(state), str(port), behavior])
        time.sleep(.15)
    report = json.loads((state / ('fixture-' + mode + '.json')).read_text())
    if behavior == mode + '-bad':
        if mode == 'graphicsVulkan': report['software'] = True
        else: report['passed'] = False
    if mode == 'graphicsD3d':
        if behavior == 'graphics-server-lost': (state / 'server-lost').touch()
        display = json.loads((state / 'fixture-display.json').read_text())
        if behavior == 'graphicsD3d-display-bad': display['matched_frames'] = [0, 1]
        (state / 'run/graphics-display.json').write_text(json.dumps(display, indent=2) + '\n')
        (state / 'logs/client-graphicsD3d-helper.log').write_text(json.dumps(report) + '\n')
        mode_line = 'VK_PRESENT_MODE_FIFO_KHR' if behavior == 'graphicsD3d-policy-fifo' else 'VK_PRESENT_MODE_IMMEDIATE_KHR'
        policy_log = 'info:  dxgi.syncInterval = 0\ninfo:  Present mode: ' + mode_line + '\n'
        if behavior == 'graphicsD3d-policy-missing': policy_log = ''
        (state / 'logs/client-graphicsD3d-helper-errors.log').write_text(policy_log)
    print(json.dumps(report), flush=True)
    sys.exit(5 if behavior in (mode + '-exit', mode + '-orphan') else 0)
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
        (self.state / 'fixture-graphicsD3d.json').write_text(json.dumps(d3d_success()))
        (self.state / 'fixture-display.json').write_text(json.dumps(display_success()))
        (self.state / 'fixture-graphics.json').write_text(json.dumps({'files': {
            'dxvk-d3d11-arm64ec.dll': {'sha256': '1' * 64},
            'dxvk-dxgi-arm64ec.dll': {'sha256': '2' * 64}}}))

    def settings(self, behavior="normal", graphics=False):
        def command(role):
            return (sys.executable, str(self.fixture), role, str(self.state), str(self.port), behavior)
        return MODULE.Settings(content=self.content, state=self.state, server_state=self.server,
                               display_port=self.port, display_command=command("display"),
                               wineserver_command=command("wineServer"), gate_command=command("gate"),
                               client_command=command("client"), tick=.025, startup_timeout=2,
                               gate_timeout=2, observe_seconds=.15, shutdown_timeout=.15,
                               graphics_mode="turnip-dxvk" if graphics else "software",
                               vulkan_command=command("graphicsVulkan") if graphics else None,
                               d3d_command=command("graphicsD3d") if graphics else None,
                               graphics_timeout=.5,
                               minimum_available_kib=0)

    def launch(self, behavior="normal", clear_stop=True, graphics=False):
        if clear_stop:
            (self.state / "run/stop").unlink(missing_ok=True)
        values = {key: str(value) if isinstance(value, Path) else value
                  for key, value in self.settings(behavior, graphics).__dict__.items()}
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
        for role in ("display", "wineServer", "gate", "graphicsVulkan", "graphicsD3d", "client", "orphan"):
            pidfile = self.state / (role + ".pid")
            if pidfile.is_file():
                pid = int(pidfile.read_text())
                if MODULE.process_record(pid):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)

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
        self.assertFalse(software["graphicsPreflight"]["hardwarePreflightPassed"])
        self.assertNotIn("graphicsD3dIdentity", software)
        (self.state / "run/stop").write_text("stop")
        self.assertEqual(fallback.wait(timeout=4), 0)

    def test_graphics_negative_reports_and_nonzero_exits_prevent_eve(self):
        for behavior in ("graphicsVulkan-bad", "graphicsVulkan-exit", "graphicsD3d-bad",
                         "graphicsD3d-display-bad", "graphicsD3d-exit", "graphicsD3d-policy-fifo",
                         "graphicsD3d-policy-missing"):
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
                      ("--d3d-command", "/bin/true"), ("--allow-software-qualification",)):
            with self.subTest(flags=flags), mock.patch.object(MODULE, "Runtime") as constructor, \
                    mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                MODULE.main(["start", *flags])
            self.assertEqual(error.exception.code, 2)
            constructor.assert_not_called()

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
