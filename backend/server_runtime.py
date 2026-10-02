#!/usr/bin/env python3
"""Persistent, loopback-only EveJS server supervisor for the Android guest.

The runtime image supplies pinned ARM64 executables, dependencies and seed data.
This module never downloads, builds, or recreates a live game database. The Android
service binds its private state at /state and invokes prepare/check/start.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterator
import urllib.error
import urllib.request
import uuid


CLIENT_BUILD = 3396210
EVEJS_VERSION = "0.12.9"
SCHEMA_VERSION = 1


class RuntimeErrorDetail(RuntimeError):
    pass


class BusyError(RuntimeErrorDetail):
    pass


class Cancelled(RuntimeErrorDetail):
    pass


@dataclass(frozen=True)
class Settings:
    state: Path = Path("/state")
    source: Path = Path("/opt/evejs")
    seed: Path = Path("/opt/evejs-seed")
    marker: Path = Path("/etc/eve-server-runtime.json")
    node: str = "/usr/local/bin/node"
    market: str = "/usr/local/bin/market-server"
    market_port: int = 40110
    market_rpc_port: int = 40111
    game_port: int = 26000
    gateway_port: int = 26002
    additional_ports: tuple[int, ...] = (26001, 26003, 5222, 26400)
    node_heap_mb: int = 2048
    market_timeout: float = 120
    startup_timeout: float = 300
    probe_interval: float = 15
    tick: float = 0.25
    node_shutdown_timeout: float = 45
    market_shutdown_timeout: float = 15
    residual_shutdown_timeout: float = 5
    # Only constructor-injected by subprocess fixtures; no guest CLI overrides.
    node_command: tuple[str, ...] | None = None
    market_command: tuple[str, ...] | None = None
    greeting_command: tuple[str, ...] | None = None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _namespace_mapping_needed() -> bool:
    return int(Path("/proc/self/stat").read_text().split(" ", 1)[0]) != os.getpid()


# Some container smoke/test runners mount the parent namespace's /proc. Android
# PRoot normally shares host PIDs, but never treat /proc/<inner pid> as the same
# process when the proc mount comes from another namespace.
NAMESPACE_MAPPING = _namespace_mapping_needed()
PROC_PID_CACHE: dict[int, int] = {}


def _read_process(path: Path) -> dict[str, Any] | None:
    try:
        raw = (path / "stat").read_text(encoding="utf-8")
        fields = raw[raw.rfind(")") + 2:].split()
        pid = int(path.name)
        group = int(fields[2])
        session = int(fields[3])
        if NAMESPACE_MAPPING:
            if os.readlink(path / "ns/pid") != os.readlink("/proc/self/ns/pid"):
                return None
            status = (path / "status").read_text(encoding="utf-8")
            names = {}
            for line in status.splitlines():
                if line.startswith(("NSpid:", "NSpgid:", "NSsid:")):
                    name, values = line.split(":", 1)
                    names[name] = int(values.split()[-1])
            pid, group, session = names["NSpid"], names["NSpgid"], names["NSsid"]
        return {
            "pid": pid, "state": fields[0], "parent": int(fields[1]),
            "group": group, "session": session,
            "startTicks": fields[19],
        }
    except (OSError, ValueError, IndexError, KeyError):
        return None


def process_record(pid: int) -> dict[str, Any] | None:
    """Read identity as well as liveness; a reused PID never passes a check."""
    if not NAMESPACE_MAPPING:
        return _read_process(Path(f"/proc/{pid}"))
    candidate = _read_process(Path(f"/proc/{PROC_PID_CACHE.get(pid, pid)}"))
    if candidate and candidate["pid"] == pid:
        return candidate
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            record = _read_process(path)
            if record:
                PROC_PID_CACHE[record["pid"]] = int(path.name)
                if record["pid"] == pid:
                    return record
    return None


def process_identity(pid: int) -> dict[str, Any]:
    record = process_record(pid)
    if record is None:
        raise RuntimeErrorDetail(f"process {pid} exited before identity was recorded")
    return {"pid": pid, "startTicks": record["startTicks"]}


def identity_alive(identity: Any) -> bool:
    if not isinstance(identity, dict):
        return False
    try:
        record = process_record(int(identity["pid"]))
        return bool(record and record["state"] != "Z" and
                    record["startTicks"] == identity.get("startTicks"))
    except (KeyError, TypeError, ValueError):
        return False


def group_members(group: int) -> list[dict[str, Any]]:
    members = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        record = _read_process(path)
        if record and record["group"] == group and record["state"] != "Z":
            members.append(record)
    return members


def fetch_health(url: str) -> dict[str, Any]:
    # Avoid proxy environment variables and never redirect a local probe off-device.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=1.5) as response:
        if response.status != 200:
            raise RuntimeErrorDetail(f"health endpoint returned HTTP {response.status}")
        raw = response.read(65537)
    if len(raw) > 65536:
        raise RuntimeErrorDetail("health response exceeded 64 KiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeErrorDetail("health response must be a JSON object")
    return value


class Runtime:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.run = self.s.state / "run"
        self.logs = self.s.state / "logs"
        self.status_file = self.run / "status.json"
        self.process_journal = self.run / "processes.json"
        self.receipt = self.s.state / "prepared.json"
        self.cancelled = False
        self.previous_status: dict[str, Any] = {}
        self.identities: dict[str, Any] = {}

    def request_stop(self, *_: Any) -> None:
        self.cancelled = True

    def cancellation_point(self) -> None:
        if self.stop_requested():
            raise Cancelled("server operation cancelled")

    def status(self, phase: str, message: str, ready: bool = False, **details: Any) -> None:
        for role in ("server", "market"):
            identity = self.identities.get(role + "Identity")
            if identity:
                self.identities[role + "Members"] = [
                    {"pid": member["pid"], "startTicks": member["startTicks"]}
                    for member in group_members(identity["pid"])
                ]
        self.previous_status = {
            "schemaVersion": SCHEMA_VERSION, "phase": phase, "message": message,
            "ready": ready, "updatedAt": time.time(), **self.identities, **details,
        }
        atomic_json(self.status_file, self.previous_status)
        if self.identities.get("marketIdentity") or self.identities.get("serverIdentity"):
            atomic_json(self.process_journal, self.identities)
        print(message, flush=True)

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        self.run.mkdir(parents=True, exist_ok=True)
        with (self.run / "operation.lock").open("a+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BusyError("another server setup or supervisor is already active") from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def validate_image(self) -> dict[str, Any]:
        marker = load_json(self.s.marker)
        if (marker.get("schemaVersion") != SCHEMA_VERSION or
                marker.get("architecture") != "arm64" or
                marker.get("evejsVersion") != EVEJS_VERSION or
                marker.get("clientBuild") != CLIENT_BUILD):
            raise RuntimeErrorDetail("server runtime image does not match ARM64 EveJS 0.12.9 / build3396210")
        for executable in (self.s.node, self.s.market):
            if not Path(executable).is_file() or not os.access(executable, os.X_OK):
                raise RuntimeErrorDetail(f"packaged executable missing: {executable}")
        for path in (self.s.source / "server/index.js",
                     self.s.source / "server/src/utils/deploymentHealthcheck.js"):
            if not path.is_file():
                raise RuntimeErrorDetail(f"packaged server source missing: {path}")
        return marker

    def validate_world(self, root: Path) -> None:
        manifest = load_json(root / "manifest.json")
        if str(manifest.get("build")) != str(CLIENT_BUILD):
            raise RuntimeErrorDetail("world seed manifest is for an incompatible EVE build")
        data = root / "data"
        if not (data / "itemTypes/data.json").is_file():
            raise RuntimeErrorDetail("world static data is incomplete (itemTypes missing)")
        # The creator manifest enumerates the tables written before publication.
        # Check every listed table, including empty placeholder tables.
        for key in ("generatedTables", "staticTables", "placeholderTables"):
            values = manifest.get(key, [])
            if not isinstance(values, list):
                raise RuntimeErrorDetail(f"invalid world manifest {key}")
            for table in values:
                if not isinstance(table, str) or table in ("", ".", "..") or Path(table).name != table:
                    raise RuntimeErrorDetail("unsafe world table name in manifest")
                # DatabaseCreator emits authored-space placeholder metadata as
                # Manifest.json. Its generated/static branches and every other
                # placeholder use writeTable(), which emits data.json.
                filename = "Manifest.json" if key == "placeholderTables" and table == "authoredSpaceProps" else "data.json"
                artifact = data / table / filename
                if not artifact.is_file():
                    raise RuntimeErrorDetail(f"world static data is incomplete ({table}/{filename} missing)")
                if filename == "Manifest.json":
                    metadata = load_json(artifact)
                    if not isinstance(metadata, dict) or not isinstance(metadata.get("props"), list):
                        raise RuntimeErrorDetail("authoredSpaceProps/Manifest.json has invalid props metadata")

    def validate_market(self, path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeErrorDetail("prepared market database is missing")
        # Read-only validation cannot create an empty SQLite DB over a missing seed.
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise RuntimeErrorDetail(f"market SQLite integrity check failed: {result}")
        finally:
            connection.close()

    def copy_file(self, source: Path, destination: Path) -> None:
        if source.is_symlink():
            raise RuntimeErrorDetail(f"seed contains a symlink: {source}")
        with source.open("rb") as reader, destination.open("xb") as writer:
            while True:
                self.cancellation_point()
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copymode(source, destination)

    def copy_tree(self, source: Path, destination: Path) -> None:
        if source.is_symlink() or not source.is_dir():
            raise RuntimeErrorDetail(f"seed directory missing or unsafe: {source}")
        destination.mkdir()
        for child in sorted(source.iterdir()):
            self.cancellation_point()
            target = destination / child.name
            if child.is_symlink():
                raise RuntimeErrorDetail(f"seed contains a symlink: {child}")
            if child.is_dir():
                self.copy_tree(child, target)
            elif child.is_file():
                self.copy_file(child, target)
            else:
                raise RuntimeErrorDetail(f"seed contains a special file: {child}")
        fsync_directory(destination)

    def market_config(self) -> str:
        return f'''# Android preview profile: Jita seed, native ARM64 market, loopback only.
[network]
port = {self.s.market_port}
[rpc]
enabled = true
port = {self.s.market_rpc_port}
[storage]
database_path = "{self.s.state / 'market/market.sqlite'}"
[runtime]
cache_station_summaries = true
cache_system_summaries = true
preload_system_seed_summaries = false
station_summary_cache_capacity = 32
system_summary_cache_capacity = 32
order_book_cache_capacity = 256
read_connection_pool_size = 2
sqlite_read_cache_size_kib = 16384
sqlite_mmap_size_mb = 256
sqlite_statement_cache_capacity = 64
[logging]
log_level = "info"
'''

    def prepare_locked(self) -> dict[str, Any]:
        self.status("preparing", "Validating the packaged ARM64 server and persistent data")
        marker = self.validate_image()
        self.cancellation_point()
        # Abandoned first-run copies never became live data. A kill cannot make
        # them authoritative merely by leaving them behind on disk.
        for abandoned in self.s.state.glob(".prepare-*"):
            if abandoned.is_dir() and not abandoned.is_symlink():
                shutil.rmtree(abandoned)
        world = self.s.state / "gameStore"
        market = self.s.state / "market"
        # Validate both before making any publication. Existing data is never replaced.
        self.validate_world(world if world.exists() else self.s.seed / "gameStore")
        self.validate_market((market if market.exists() else self.s.seed / "market") / "market.sqlite")
        seed_config = self.s.seed / "config"
        if not seed_config.is_dir():
            raise RuntimeErrorDetail("packaged default configuration is missing")
        staging = self.s.state / f".prepare-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            for name, destination in (("gameStore", world), ("market", market)):
                if not destination.exists():
                    self.status("preparing", f"Copying initial {name} data; existing saves remain preserved")
                    self.copy_tree(self.s.seed / name, staging / name)
            config = self.s.state / "config"
            config.mkdir(exist_ok=True)
            for source in sorted(seed_config.iterdir()):
                if not source.is_file() or source.is_symlink() or source.suffix != ".json":
                    raise RuntimeErrorDetail(f"invalid packaged config entry: {source.name}")
                if not (config / source.name).exists():
                    self.copy_file(source, staging / source.name)
            self.cancellation_point()
            # Each directory is atomically published. An interrupted partial first
            # setup may resume its absent directory; a published directory is kept.
            for name, destination in (("gameStore", world), ("market", market)):
                if (staging / name).exists():
                    os.rename(staging / name, destination)
                    fsync_directory(self.s.state)
            for source in sorted(staging.glob("*.json")):
                # Setup and start share a lock. Never replace a user configuration.
                destination = config / source.name
                if not destination.exists():
                    os.rename(source, destination)
            fsync_directory(config)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        for name in ("certs", "chat", "images", "logs/node-reports", "gameStore/images"):
            (self.s.state / name).mkdir(parents=True, exist_ok=True)
        # This is launcher-owned runtime configuration, separate from player data.
        config_path = market / "server.toml"
        temporary = market / f".server-{uuid.uuid4().hex}.toml"
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(self.market_config())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, config_path)
        fsync_directory(market)
        receipt = {
            "schemaVersion": SCHEMA_VERSION, "evejsVersion": EVEJS_VERSION,
            "clientBuild": CLIENT_BUILD, "architecture": "arm64",
            "preparedAt": time.time(), "profile": "android-jita-preview",
            "nodeHeapMiB": self.s.node_heap_mb, "marketReadPool": 2,
            "sourceSha256": marker.get("sourceSha256"),
        }
        self.cancellation_point()
        if self.receipt.exists():
            previous = load_json(self.receipt)
            if {key: value for key, value in previous.items() if key != "preparedAt"} == {
                    key: value for key, value in receipt.items() if key != "preparedAt"}:
                receipt = previous
            else:
                atomic_json(self.receipt, receipt)
        else:
            atomic_json(self.receipt, receipt)
        self.status("stopped", "Server prepared; ready to start", prepared=True)
        return receipt

    def prepare(self) -> dict[str, Any]:
        with self.exclusive():
            try:
                # Preparation is an explicit new operation. Its old stop request
                # is consumed before status/progress begins; subsequent requests
                # cancel each copy chunk and publication boundary.
                (self.run / "stop").unlink(missing_ok=True)
                self.recover_stale_children()
                self.identities = {"supervisorIdentity": process_identity(os.getpid())}
                return self.prepare_locked()
            except Cancelled:
                self.status("stopped", "Server setup cancelled; published saves preserved", prepared=self.receipt.exists())
                raise
            except Exception as error:
                self.status("failed", "Server setup failed", error=str(error))
                raise

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "NODE_ENV": "production", "EVEJS_DATA_ROOT": str(self.s.state),
            "EVEJS_GAMESTORE_DATA_DIR": str(self.s.state / "gameStore/data"),
            "EVEJS_GAME_SERVER_BIND_HOST": "127.0.0.1",
            "EVEJS_SERVER_PORT": str(self.s.game_port),
            "EVEJS_IMAGE_SERVER_BIND_HOST": "127.0.0.1",
            "EVEJS_IMAGE_SERVER_URL": "http://127.0.0.1:26001/",
            "EVEJS_MARKET_DAEMON_HOST": "127.0.0.1",
            "EVEJS_MARKET_DAEMON_PORT": str(self.s.market_rpc_port),
            "EVEJS_MICROSERVICES_BIND_HOST": "127.0.0.1",
            "EVEJS_MICROSERVICES_PORT": str(self.s.gateway_port),
            "EVEJS_MICROSERVICES_PUBLIC_URL": f"http://127.0.0.1:{self.s.gateway_port}/",
            "EVEJS_PROXY_LOCAL_INTERCEPT": "1",
            "EVEJS_PROXY_LOOPBACK_CDN_LISTEN_PORT": "26003",
            "EVEJS_REDSHIFT_MONITOR_HOST": "127.0.0.1",
            "EVEJS_REDSHIFT_MONITOR_PORT": "26400",
            "EVEJS_XMPP_CONNECT_HOST": "localhost",
            "EVEJS_XMPP_SERVER_BIND_HOST": "127.0.0.1",
        })
        return env

    def market_health(self) -> dict[str, Any]:
        value = fetch_health(f"http://127.0.0.1:{self.s.market_port}/health")
        if value.get("ok") is not True or value.get("data", {}).get("status") != "ok":
            raise RuntimeErrorDetail("market health response did not confirm initialized database")
        return value

    def offline_health(self) -> dict[str, Any]:
        value = fetch_health(f"http://127.0.0.1:{self.s.gateway_port}/health")
        policy = value.get("offlinePolicy", {})
        if (value.get("status") != "ok" or value.get("service") != "express-secondary" or
                value.get("gatewayMode") != "local" or
                type(policy.get("version")) is not int or policy.get("version") != 2 or
                policy.get("proxyForwarding") != "disabled" or
                policy.get("clientFeatureFlags") != "defaults"):
            raise RuntimeErrorDetail("gateway did not confirm offline policy v2 with forwarding disabled and default feature flags")
        return value

    def game_greeting(self) -> None:
        command = self.s.greeting_command or (
            self.s.node, str(self.s.source / "server/src/utils/deploymentHealthcheck.js"),
        )
        try:
            result = subprocess.run(command, env=self.environment(), cwd=self.s.source / "server",
                                    capture_output=True, timeout=8, text=True)
        except subprocess.TimeoutExpired as error:
            raise RuntimeErrorDetail("MachoNet greeting probe timed out") from error
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()[-1500:]
            raise RuntimeErrorDetail(f"MachoNet greeting probe failed: {message}")

    def probe(self) -> dict[str, Any]:
        market = self.market_health()
        offline = self.offline_health()
        self.game_greeting()
        return {
            "market": True, "offlinePolicyVersion": offline["offlinePolicy"]["version"],
            "machoNetGreeting": True, "marketSchemaVersion": market["data"].get("schema_version"),
            "checkedAt": time.time(),
        }

    def check(self) -> dict[str, Any]:
        value = load_json(self.status_file)
        if value.get("phase") != "running" or value.get("ready") is not True:
            raise RuntimeErrorDetail(value.get("message", "server is not running"))
        for name in ("supervisorIdentity", "serverIdentity", "marketIdentity"):
            if not identity_alive(value.get(name)):
                raise RuntimeErrorDetail(f"{name} is no longer alive; stale readiness rejected")
        return {"ready": True, "phase": "running", "health": self.probe()}

    def stop_requested(self) -> bool:
        return self.cancelled or (self.run / "stop").exists()

    def preflight_ports(self) -> None:
        # Reject another local install before its healthy listeners can be
        # mistaken for ours while a newly spawned world is still loading.
        ports = {self.s.market_port, self.s.market_rpc_port, self.s.game_port,
                 self.s.gateway_port, *self.s.additional_ports}
        for port in sorted(ports):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    listener.bind(("127.0.0.1", port))
                except OSError as error:
                    raise RuntimeErrorDetail(f"local server port {port} is already in use; stop the other runtime before starting EveJS") from error

    def spawn(self, command: tuple[str, ...], name: str, cwd: Path) -> subprocess.Popen:
        self.logs.mkdir(parents=True, exist_ok=True)
        with (self.logs / f"{name}-console.log").open("ab", buffering=0) as stream:
            stream.write(f"\n=== {name} start {time.time():.3f} ===\n".encode("utf-8"))
            return subprocess.Popen(command, cwd=cwd, env=self.environment(), stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)

    def child_running(self, process: subprocess.Popen | None, name: str) -> None:
        if process is not None and process.poll() is not None:
            raise RuntimeErrorDetail(f"{name} process exited unexpectedly with code {process.returncode}")

    def wait_health(self, children: dict[str, subprocess.Popen], market_only: bool, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_error = "waiting for listeners"
        last_probe = 0.0
        while time.monotonic() < deadline:
            if self.stop_requested():
                raise Cancelled("server startup cancelled")
            for name, process in children.items():
                self.child_running(process, name)
            if time.monotonic() - last_probe >= 1:
                last_probe = time.monotonic()
                try:
                    if market_only:
                        self.market_health()
                        return {"market": True}
                    return self.probe()
                except (OSError, ValueError, RuntimeErrorDetail, urllib.error.URLError) as error:
                    last_error = str(error)
                    self.status("starting", "Waiting for market database" if market_only else "Waiting for world, offline gateway and MachoNet greeting", healthError=last_error)
            time.sleep(self.s.tick)
        raise RuntimeErrorDetail(f"{'market' if market_only else 'world'} readiness timed out: {last_error}")

    def shutdown_child(self, process: subprocess.Popen | None, grace: float) -> bool:
        if process is None:
            return True
        clean = True
        # World gets its own SIGTERM first: its registered owner shutdown hooks
        # flush gameStore and stop its authorities while market remains available.
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            deadline = time.monotonic() + grace
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(self.s.tick)
            if process.poll() is None:
                clean = False
        elif process.returncode != 0:
            clean = False
        # Node forks multiple authorities/services. Reap every live member of the
        # isolated session even after an unexpected root exit.
        if group_members(process.pid):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + self.s.residual_shutdown_timeout
            while group_members(process.pid) and time.monotonic() < deadline:
                process.poll()
                time.sleep(self.s.tick)
            if group_members(process.pid):
                clean = False
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                while group_members(process.pid) and time.monotonic() < deadline:
                    process.poll()
                    time.sleep(self.s.tick)
        process.wait(timeout=5)
        if process.returncode not in (0, -signal.SIGTERM):
            clean = False
        return clean

    def recover_stale_children(self) -> None:
        """Recover services left alive by a killed supervisor before any DB use."""
        if not self.process_journal.exists():
            return
        journal = load_json(self.process_journal)
        if identity_alive(journal.get("supervisorIdentity")):
            raise BusyError("recorded server supervisor is still alive")
        recovered = False
        clean = True
        # The world still gets a chance to flush before stopping the market.
        for role, grace in (("server", self.s.node_shutdown_timeout), ("market", self.s.market_shutdown_timeout)):
            identity = journal.get(role + "Identity")
            if not isinstance(identity, dict):
                continue
            pid = identity.get("pid")
            if not isinstance(pid, int) or pid <= 1:
                raise RuntimeErrorDetail("invalid stale child identity; refusing process cleanup")
            members = group_members(pid)
            if not members:
                continue
            root_alive = identity_alive(identity)
            root_record = process_record(pid) if root_alive else None
            known = any(identity_alive(member) for member in journal.get(role + "Members", [])
                        if isinstance(member, dict) and member.get("pid") in {item["pid"] for item in members})
            if root_alive and (not root_record or root_record["group"] != pid or root_record["session"] != pid):
                raise RuntimeErrorDetail("stale process no longer has its recorded isolated session")
            if not root_alive and not known:
                raise RuntimeErrorDetail("unverified process group remains after a crash; refusing to signal unrelated processes")
            recovered = True
            self.status("stopping", f"Recovering {role} services after the previous supervisor exited")
            if root_alive:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + grace
                while identity_alive(identity) and time.monotonic() < deadline:
                    time.sleep(self.s.tick)
            if group_members(pid):
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + self.s.residual_shutdown_timeout
                while group_members(pid) and time.monotonic() < deadline:
                    time.sleep(self.s.tick)
                if group_members(pid):
                    clean = False
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 3
                    while group_members(pid) and time.monotonic() < deadline:
                        time.sleep(self.s.tick)
                    if group_members(pid):
                        raise RuntimeErrorDetail("stale runtime processes remain after forced cleanup")
        self.process_journal.unlink(missing_ok=True)
        if recovered:
            self.status("stopped", "Previous runtime services recovered; world data preserved", cleanShutdown=clean)
        if not clean:
            raise RuntimeErrorDetail("previous runtime required forced cleanup; inspect logs before restarting")

    def start(self) -> None:
        with self.exclusive():
            market_process = server_process = None
            failure: BaseException | None = None
            clean = True
            self.recover_stale_children()
            self.identities = {"supervisorIdentity": process_identity(os.getpid())}
            # The Android caller clears a prior stop before spawning this process.
            # A sentinel already present here may be a fresh immediate Stop and
            # must never be erased by the newly launched supervisor.
            try:
                if not self.receipt.exists():
                    raise RuntimeErrorDetail("prepare the server before starting it")
                receipt = load_json(self.receipt)
                if receipt.get("clientBuild") != CLIENT_BUILD or receipt.get("schemaVersion") != SCHEMA_VERSION:
                    raise RuntimeErrorDetail("server preparation receipt is incompatible")
                self.validate_image()
                self.validate_world(self.s.state / "gameStore")
                self.validate_market(self.s.state / "market/market.sqlite")
                self.cancellation_point()
                self.preflight_ports()
                self.status("starting", "Starting native ARM64 market daemon")
                market_command = self.s.market_command or (
                    self.s.market, "--config", str(self.s.state / "market/server.toml"), "serve",
                )
                market_process = self.spawn(market_command, "market", self.s.source)
                self.identities["marketIdentity"] = process_identity(market_process.pid)
                self.wait_health({"market": market_process}, True, self.s.market_timeout)
                self.status("starting", "Starting EveJS world and persistent authorities")
                node_command = self.s.node_command or (
                    self.s.node, "--report-on-fatalerror", "--report-uncaught-exception",
                    f"--report-dir={self.logs / 'node-reports'}",
                    f"--max-old-space-size={self.s.node_heap_mb}", ".",
                )
                server_process = self.spawn(node_command, "server", self.s.source / "server")
                self.identities["serverIdentity"] = process_identity(server_process.pid)
                health = self.wait_health({"market": market_process, "server": server_process}, False, self.s.startup_timeout)
                # A child may have exited during the probes; never publish stale success.
                self.child_running(market_process, "market")
                self.child_running(server_process, "server")
                self.status("running", "Server ready: market, offline gateway and game handshake verified", True, health=health)
                last_probe = time.monotonic()
                while not self.stop_requested():
                    self.child_running(market_process, "market")
                    self.child_running(server_process, "server")
                    if time.monotonic() - last_probe >= self.s.probe_interval:
                        health = self.probe()
                        self.child_running(market_process, "market")
                        self.child_running(server_process, "server")
                        self.status("running", "Server ready: market, offline gateway and game handshake verified", True, health=health)
                        last_probe = time.monotonic()
                    time.sleep(self.s.tick)
            except Cancelled:
                pass
            except BaseException as error:
                failure = error
            finally:
                self.status("stopping", "Saving the world and stopping its services before the market")
                try:
                    clean = self.shutdown_child(server_process, self.s.node_shutdown_timeout)
                except BaseException as error:
                    clean = False
                    failure = failure or error
                try:
                    clean = self.shutdown_child(market_process, self.s.market_shutdown_timeout) and clean
                except BaseException as error:
                    clean = False
                    failure = failure or error
                if failure or not clean:
                    error = str(failure) if failure else "a process required forced shutdown; inspect logs before restarting"
                    self.status("failed", "Server stopped after a runtime failure", error=error, cleanShutdown=clean)
                else:
                    self.status("stopped", "Server stopped; world data saved", cleanShutdown=True, prepared=True)
                # A separate journal survives Java resetting its display report.
                # Clear it only when every owned process group has been reaped.
                if not any(group_members(process.pid) for process in (server_process, market_process) if process):
                    self.process_journal.unlink(missing_ok=True)
            if failure:
                raise RuntimeErrorDetail(str(failure)) from failure
            if not clean:
                raise RuntimeErrorDetail("server shutdown required forced process cleanup")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("prepare", "check", "start"):
        print("usage: server_runtime.py {prepare,check,start}", file=sys.stderr)
        return 2
    runtime = Runtime()
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, runtime.request_stop)
    try:
        if args[0] == "prepare":
            runtime.prepare()
        elif args[0] == "check":
            print(json.dumps(runtime.check(), sort_keys=True), flush=True)
        else:
            runtime.start()
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"server runtime: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
