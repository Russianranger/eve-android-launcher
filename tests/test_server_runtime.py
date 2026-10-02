"""Exercise durable setup and actual supervisor child lifecycles, without Eve assets."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


BACKEND = Path(__file__).resolve().parents[1] / "backend/server_runtime.py"
SPEC = importlib.util.spec_from_file_location("server_runtime", BACKEND)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


FIXTURE = r'''
import http.server, json, os, pathlib, signal, socket, sqlite3, subprocess, sys, threading, time
mode, state, market_port, gateway_port, game_port, behavior = sys.argv[1:]
state = pathlib.Path(state)
market_port, gateway_port, game_port = map(int, (market_port, gateway_port, game_port))
if mode == "orphan":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (state / "orphan.pid").write_text(str(os.getpid()))
    while True: time.sleep(.05)
if mode == "greeting":
    with socket.create_connection(("127.0.0.1", game_port), timeout=.5) as connection:
        payload = connection.recv(100)
    sys.exit(0 if payload == b"fixture-macho-build3396210" else 7)
if mode == "world" and behavior == "crash-orphan":
    orphan = subprocess.Popen([sys.executable, __file__, "orphan", str(state), str(market_port), str(gateway_port), str(game_port), behavior])

class Health(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if mode == "market":
            value = {"ok": behavior != "unhealthy-market", "data": {"status": "ok", "schema_version": 1}}
        else:
            value = {"status": "ok", "service": "express-secondary", "gatewayMode": "local", "offlinePolicy": {"version": 2, "proxyForwarding": "enabled" if behavior == "unsafe-policy" else "disabled", "clientFeatureFlags": "defaults"}}
        raw = json.dumps(value).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)

server = http.server.ThreadingHTTPServer(("127.0.0.1", market_port if mode == "market" else gateway_port), Health)
threading.Thread(target=server.serve_forever, daemon=True).start()
def accept():
    listener = socket.socket(); listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", game_port)); listener.listen(10)
    while True:
        connection, _ = listener.accept()
        connection.sendall(b"fixture-macho-build3396210"); connection.close()
if mode == "world": threading.Thread(target=accept, daemon=True).start()

def finish(*args):
    if mode == "world":
        # This write occurs only on graceful stop, exercising durability and order.
        with sqlite3.connect(state / "gameStore/gamestore.sqlite") as db:
            db.execute("CREATE TABLE IF NOT EXISTS player (name TEXT)")
            db.execute("INSERT INTO player VALUES ('THORPILOT')")
        with (state / "shutdown-order").open("a") as stream: stream.write("world-flushed\n")
    else:
        with (state / "shutdown-order").open("a") as stream: stream.write("market-stopped\n")
    sys.exit(0)
signal.signal(signal.SIGTERM, finish)
(state / (mode + ".pid")).write_text(str(os.getpid()))
if mode == "world" and behavior == "crash-orphan":
    time.sleep(.6)
    os._exit(31)
while True: time.sleep(.05)
'''


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ServerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="eve-runtime-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "state"
        self.source = self.root / "source"
        self.seed = self.root / "seed"
        self.marker = self.root / "marker.json"
        self.fixture = self.root / "fixture.py"
        self.fixture.write_text(FIXTURE)
        for name in ("server/index.js", "server/src/utils/deploymentHealthcheck.js"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// fixture source; never executed\n")
        (self.seed / "gameStore/data/itemTypes").mkdir(parents=True)
        (self.seed / "gameStore/data/itemTypes/data.json").write_text('{"entries": []}')
        (self.seed / "gameStore/manifest.json").write_text(json.dumps({"build": 3396210, "generatedTables": ["itemTypes"]}))
        (self.seed / "market").mkdir()
        with sqlite3.connect(self.seed / "market/market.sqlite") as connection:
            connection.execute("CREATE TABLE saved_order (value TEXT)")
            connection.execute("INSERT INTO saved_order VALUES ('seed')")
        (self.seed / "config").mkdir()
        (self.seed / "config/server.json").write_text('{"seedDefault": true}')
        self.marker.write_text(json.dumps({"schemaVersion": 1, "architecture": "arm64", "evejsVersion": "0.12.9", "clientBuild": 3396210}))
        self.ports = [free_port(), free_port(), free_port()]
        self.settings = self.make_settings()
        self.runtime = MODULE.Runtime(self.settings)
        self.processes = []
        self.addCleanup(self.stop_processes)

    def make_settings(self, behavior="normal"):
        parameters = [str(self.state), *(str(port) for port in self.ports), behavior]
        return MODULE.Settings(
            state=self.state, source=self.source, seed=self.seed, marker=self.marker,
            node=sys.executable, market=sys.executable,
            market_port=self.ports[0], gateway_port=self.ports[1], game_port=self.ports[2],
            market_rpc_port=free_port(), additional_ports=(),
            market_timeout=1.5, startup_timeout=1.5, probe_interval=.25, tick=.03,
            node_shutdown_timeout=.5, market_shutdown_timeout=.5, residual_shutdown_timeout=.15,
            node_command=tuple([sys.executable, str(self.fixture), "world", *parameters]),
            market_command=tuple([sys.executable, str(self.fixture), "market", *parameters]),
            greeting_command=tuple([sys.executable, str(self.fixture), "greeting", *parameters]),
        )

    def launch(self, behavior="normal", clear_stop=True):
        if clear_stop:
            # Mirrors the launcher clearing a previous stop before process spawn.
            (self.state / "run/stop").unlink(missing_ok=True)
        self.settings = self.make_settings(behavior)
        values = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in self.settings.__dict__.items()
        }
        runner = self.root / "runner.py"
        runner.write_text(
            "import importlib.util,json,pathlib,signal,sys\n"
            f"spec=importlib.util.spec_from_file_location('server_runtime',{str(BACKEND)!r})\n"
            "module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)\n"
            f"values=json.loads({json.dumps(values)!r})\n"
            "for name in ('state','source','seed','marker'):values[name]=pathlib.Path(values[name])\n"
            "runtime=module.Runtime(module.Settings(**values))\n"
            "for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,runtime.request_stop)\n"
            "runtime.start()\n"
        )
        output = (self.root / "supervisor.log").open("wb")
        self.addCleanup(output.close)
        process = subprocess.Popen([sys.executable, str(runner)], stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def stop_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
        # A failed assertion must still clean fixture groups.
        for name in ("world", "market", "orphan"):
            path = self.state / (name + ".pid")
            if path.exists():
                with contextlib.suppress(ProcessLookupError):
                    pid = int(path.read_text())
                    if MODULE.process_record(pid):
                        os.kill(pid, signal.SIGKILL)

    def wait_status(self, phase, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = MODULE.load_json(self.state / "run/status.json")
                if status.get("phase") == phase:
                    return status
            except (OSError, ValueError):
                pass
            time.sleep(.03)
        log = (self.root / "supervisor.log").read_text() if (self.root / "supervisor.log").exists() else ""
        self.fail(f"status did not reach {phase}: {log}")

    def assert_child_gone(self, name):
        pid = int((self.state / (name + ".pid")).read_text())
        record = MODULE.process_record(pid)
        self.assertTrue(record is None or record["state"] == "Z", f"{name} still running")

    def test_prepare_preserves_player_state_and_configuration(self):
        self.runtime.prepare()
        first_receipt = self.runtime.receipt.read_bytes()
        with sqlite3.connect(self.state / "gameStore/gamestore.sqlite") as db:
            db.execute("CREATE TABLE player (name TEXT)")
            db.execute("INSERT INTO player VALUES ('existing-character')")
        with sqlite3.connect(self.state / "market/market.sqlite") as db:
            db.execute("INSERT INTO saved_order VALUES ('player-order')")
        (self.state / "config/server.json").write_text('{"userChange": true}')
        self.runtime.prepare()
        with sqlite3.connect(self.state / "gameStore/gamestore.sqlite") as db:
            self.assertEqual(db.execute("SELECT name FROM player").fetchall(), [("existing-character",)])
        with sqlite3.connect(self.state / "market/market.sqlite") as db:
            self.assertEqual(db.execute("SELECT value FROM saved_order").fetchall(), [("seed",), ("player-order",)])
        self.assertEqual(MODULE.load_json(self.state / "config/server.json"), {"userChange": True})
        self.assertEqual(MODULE.load_json(self.runtime.receipt)["clientBuild"], 3396210)
        self.assertEqual(self.runtime.receipt.read_bytes(), first_receipt)

    def test_missing_seed_is_never_published_as_prepared(self):
        (self.seed / "market/market.sqlite").unlink()
        with self.assertRaises(MODULE.RuntimeErrorDetail):
            self.runtime.prepare()
        self.assertFalse(self.runtime.receipt.exists())
        self.assertFalse((self.state / "gameStore").exists())
        self.assertEqual(MODULE.load_json(self.runtime.status_file)["phase"], "failed")

    def test_cancellation_during_copy_leaves_no_receipt_or_half_tree(self):
        original = self.runtime.copy_file
        calls = 0
        def cancel_mid_copy(source, target):
            nonlocal calls
            calls += 1
            original(source, target)
            if calls == 1:
                self.runtime.request_stop()
        self.runtime.copy_file = cancel_mid_copy
        with self.assertRaises(MODULE.Cancelled):
            self.runtime.prepare()
        self.assertFalse(self.runtime.receipt.exists())
        self.assertFalse((self.state / "gameStore").exists())
        self.assertEqual(list(self.state.glob(".prepare-*")), [])

    def test_start_ready_stop_flushes_world_before_market_and_rejects_stale_status(self):
        self.runtime.prepare()
        (self.state / "run/stop").touch()  # A stop from yesterday cannot cancel today's start.
        process = self.launch()
        status = self.wait_status("running")
        self.assertTrue(status["ready"])
        self.assertTrue(self.runtime.check()["health"]["machoNetGreeting"])
        (self.state / "run/stop").touch()
        self.assertEqual(process.wait(timeout=5), 0)
        final = self.wait_status("stopped")
        self.assertTrue(final["cleanShutdown"])
        self.assertFalse(final["ready"])
        self.assertEqual((self.state / "shutdown-order").read_text().splitlines(), ["world-flushed", "market-stopped"])
        with sqlite3.connect(self.state / "gameStore/gamestore.sqlite") as db:
            self.assertEqual(db.execute("SELECT name FROM player").fetchall(), [("THORPILOT",)])
        self.assert_child_gone("world"); self.assert_child_gone("market")
        # Even a stale copy of a once-valid running report must fail its PID checks.
        MODULE.atomic_json(self.runtime.status_file, status)
        with self.assertRaisesRegex(MODULE.RuntimeErrorDetail, "stale readiness"):
            self.runtime.check()

    def test_prepare_and_duplicate_start_cannot_overlap_supervisor(self):
        self.runtime.prepare()
        process = self.launch()
        self.wait_status("running")
        with self.assertRaises(MODULE.BusyError): self.runtime.prepare()
        with self.assertRaises(MODULE.BusyError): self.runtime.start()
        self.assertEqual(MODULE.load_json(self.runtime.status_file)["phase"], "running")
        (self.state / "run/stop").touch()
        self.assertEqual(process.wait(timeout=5), 0)

    def test_open_ports_with_unsafe_offline_policy_never_become_ready(self):
        self.runtime.prepare()
        process = self.launch("unsafe-policy")
        self.assertNotEqual(process.wait(timeout=6), 0)
        status = self.wait_status("failed")
        self.assertFalse(status["ready"])
        self.assertIn("offline policy v2", status["error"])
        self.assert_child_gone("world"); self.assert_child_gone("market")

    def test_existing_foreign_listener_cannot_be_used_as_runtime_readiness(self):
        self.runtime.prepare()
        with socket.socket() as foreign:
            foreign.bind(("127.0.0.1", self.ports[2]))
            foreign.listen()
            process = self.launch()
            self.assertNotEqual(process.wait(timeout=4), 0)
        status = self.wait_status("failed")
        self.assertFalse(status["ready"])
        self.assertIn("already in use", status["error"])
        self.assertFalse((self.state / "world.pid").exists())
        self.assertFalse((self.state / "market.pid").exists())

    def test_world_crash_cleans_orphan_service_and_market(self):
        self.runtime.prepare()
        process = self.launch("crash-orphan")
        self.assertNotEqual(process.wait(timeout=6), 0)
        status = self.wait_status("failed")
        self.assertFalse(status["ready"])
        self.assertIn("exited unexpectedly", status["error"])
        self.assertFalse(status["cleanShutdown"])
        for name in ("world", "market", "orphan"): self.assert_child_gone(name)

    def test_killed_supervisor_recovers_old_writers_before_preparing_again(self):
        self.runtime.prepare()
        process = self.launch()
        self.wait_status("running")
        process.kill()
        self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        # App UI may replace status.json on launch; the separate process journal
        # still retains identities needed to recover old DB writers safely.
        MODULE.atomic_json(self.runtime.status_file, {"phase": "starting", "ready": False})
        self.runtime.prepare()
        self.assertEqual((self.state / "shutdown-order").read_text().splitlines(), ["world-flushed", "market-stopped"])
        for name in ("world", "market"): self.assert_child_gone(name)
        self.assertFalse(self.runtime.process_journal.exists())
        with sqlite3.connect(self.state / "gameStore/gamestore.sqlite") as db:
            self.assertEqual(db.execute("SELECT name FROM player").fetchall(), [("THORPILOT",)])

    def test_signal_during_market_startup_cancels_and_reaps_child(self):
        self.runtime.prepare()
        process = self.launch("unhealthy-market")
        deadline = time.monotonic() + 3
        while not (self.state / "market.pid").exists() and time.monotonic() < deadline:
            time.sleep(.03)
        process.terminate()
        self.assertEqual(process.wait(timeout=5), 0)
        status = self.wait_status("stopped")
        self.assertFalse(status["ready"])
        self.assertTrue(status["cleanShutdown"])
        self.assertFalse((self.state / "world.pid").exists())
        self.assert_child_gone("market")

    def test_immediate_stop_is_preserved_before_supervisor_initializes(self):
        self.runtime.prepare()
        # Fresh Stop arrives after the launcher reset, before Python starts.
        (self.state / "run/stop").touch()
        process = self.launch(clear_stop=False)
        self.assertEqual(process.wait(timeout=4), 0)
        status = self.wait_status("stopped")
        self.assertFalse(status["ready"])
        self.assertTrue(status["cleanShutdown"])
        self.assertFalse((self.state / "market.pid").exists())
        self.assertFalse((self.state / "world.pid").exists())


if __name__ == "__main__":
    unittest.main()
