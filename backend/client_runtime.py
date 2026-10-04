#!/usr/bin/env python3
"""Supervise the pinned EVE client on a private, loopback-only Wine display.

Readiness here means that the display and an EVE process have started. It never
claims a successful login, renderer qualification, audio or controller support.
The Android caller must enable PRoot's per-session native network restriction.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import errno
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import stat
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

import client_prepare
import client_graphics
import client_diagnostics
from process_metrics import available_memory_kib
import wine_trust_overlay
import server_runtime
from server_runtime import (BusyError, RuntimeErrorDetail, atomic_json, fetch_health,
                            group_members, identity_alive, process_identity,
                            process_record)


NETWORK_POLICY = "loopback-v1"
LOG_LIMIT = 8 * 1024**2
LOG_HISTORY = 2
OWNED_ROLES = ("client", "graphicsD3d", "graphicsVulkan", "gate", "wineServer", "display")
WINDOW_HELPER_LIMIT = 8 * 1024**2
WINDOW_RECEIPT_LIMIT = 4096


@dataclass(frozen=True)
class Settings:
    content: Path = Path("/client")
    state: Path = Path("/client-state")
    server_state: Path = Path("/server-state")
    marker: Path = Path("/etc/memento-client-runtime.json")
    wine: str = "/opt/wine/bin/wine"
    wineserver: str = "/opt/wine/bin/wineserver"
    display: str = "/usr/bin/Xtigervnc"
    gate: Path = Path("/opt/eve-android/eve-client-gate.exe")
    trust_overlay: Path = Path("/opt/eve-android/wine-trust-overlay.json")
    trust_overlay_root: Path = Path("/")
    display_number: int = 7
    display_port: int = 5907
    gateway_port: int = 26002
    startup_timeout: float = 150
    gate_timeout: float = 60
    observe_seconds: float = 5
    shutdown_timeout: float = 15
    tick: float = .25
    minimum_available_kib: int = 1024**2
    graphics_mode: str = "turnip-dxvk"
    graphics_folder: Path = Path("/opt/eve-android")
    graphics_timeout: float = 90
    window_start_timeout: float = 20
    hosts_file: Path = Path("/etc/hosts")
    # Constructor-only fixture injection. Retail CLI cannot substitute commands.
    display_command: tuple[str, ...] | None = None
    wineserver_command: tuple[str, ...] | None = None
    gate_command: tuple[str, ...] | None = None
    client_command: tuple[str, ...] | None = None
    vulkan_command: tuple[str, ...] | None = None
    d3d_command: tuple[str, ...] | None = None


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(client_prepare.bounded_text(path, limit=128 * 1024))
    if not isinstance(value, dict):
        raise RuntimeErrorDetail("Invalid client receipt: " + path.name)
    return value


def rotate_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_name(path.name + "." + str(LOG_HISTORY)).unlink(missing_ok=True)
    for number in range(LOG_HISTORY - 1, 0, -1):
        old = path.with_name(path.name + "." + str(number))
        if old.exists():
            old.replace(path.with_name(path.name + "." + str(number + 1)))
    if path.exists():
        path.replace(path.with_name(path.name + ".1"))


def memory_metrics() -> dict[str, int]:
    result = client_prepare.memory_snapshot()
    try:
        with Path("/proc/meminfo").open() as source:
            for line in source:
                if line.startswith("MemAvailable:"):
                    result["memAvailableKiB"] = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pass
    return result


class Runtime:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.run = self.s.state / "run"
        self.logs = self.s.state / "logs"
        self.status_file = self.run / "status.json"
        self.journal = self.run / "processes.json"
        self.window_helper = self.s.gate.with_name("eve-client-window.exe")
        self.window_receipt = self.run / "client-window.json"
        self.window_session: str | None = None
        self.window_child_ids: tuple[int, int] | None = None
        self.window_report: dict[str, Any] = {}
        self.identities: dict[str, Any] = {}
        self.children: dict[str, subprocess.Popen] = {}
        self.pumps: list[threading.Thread] = []
        self.cancelled = False
        self.server_identities: dict[str, Any] = {}
        self.tls_report: dict[str, Any] = {}
        self.graphics_bundle: dict[str, Any] = {}
        self.graphics_reports: dict[str, Any] = {}
        self.previous_snapshot = None
        self.diagnostics = client_diagnostics.PerformanceHistory(
            self.s.state, client_graphics.cache_directories(self.s.state))

    def request_stop(self, *_: Any) -> None:
        self.cancelled = True

    def stopping(self) -> bool:
        return self.cancelled or (self.run / "stop").exists()

    def cancellation_point(self) -> None:
        if self.stopping():
            raise InterruptedError("Client startup cancelled")

    @contextlib.contextmanager
    def exclusive(self):
        self.run.mkdir(parents=True, exist_ok=True)
        with (self.run / "operation.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BusyError("Another EVE client session is already active") from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def refresh_owned_processes(self, persist: bool = False):
        snapshot = server_runtime.ProcessSnapshot.capture(process.pid for process in self.children.values())
        changed = False
        owned = {}
        for role, process in self.children.items():
            members = snapshot.members(process.pid)
            identity = self.identities.get(role + "Identity", {})
            leader_matches = any(item["pid"] == process.pid and item["startTicks"] == identity.get("startTicks")
                                 and item["session"] == process.pid for item in members)
            if not leader_matches and process.returncode is None:
                # A fresh, unreaped zombie still reserves the owned PID and
                # private group/session. Capture its children before poll()
                # reaps that final identity; snapshots omit zombies for metrics.
                leader = process_record(process.pid)
                leader_matches = bool(leader and leader.get("state") == "Z"
                                      and leader.get("pid") == process.pid
                                      and leader.get("startTicks") == identity.get("startTicks")
                                      and leader.get("group") == process.pid
                                      and leader.get("session") == process.pid)
            if not leader_matches:
                known = {(item["pid"], item["startTicks"]) for item in self.identities.get(role + "Members", [])}
                members = [item for item in members if (item["pid"], item["startTicks"]) in known]
            owned[process.pid] = members
            identities = [
                {"pid": item["pid"], "startTicks": item["startTicks"]}
                for item in members
            ]
            changed = changed or identities != self.identities.get(role + "Members")
            self.identities[role + "Members"] = identities
        if persist and changed and self.children:
            atomic_json(self.journal, self.identities)
        return server_runtime.ProcessSnapshot(captured_at=snapshot.captured_at, groups=owned)

    def status(self, phase: str, message: str, ready: bool = False, **details: Any) -> None:
        memory = memory_metrics()
        snapshot = self.refresh_owned_processes()
        cpu = snapshot.cpu_usage(self.previous_snapshot)
        self.previous_snapshot = snapshot
        process_cpu = {}
        for role, process in self.children.items():
            memory[role + "GroupRssKiB"] = sum(item.get("rssKiB", 0) for item in snapshot.members(process.pid))
            process_cpu[role] = cpu.get(process.pid, {})
        groups = {role: process.pid for role, process in self.children.items()}
        if phase in ("stopped", "failed"):
            self.diagnostics.finish(phase)
        else:
            self.diagnostics.sample(snapshot, groups, phase, force=phase == "stopping")
        report = {"schemaVersion": 1, "phase": phase, "message": message,
                  "ready": ready, "client_launch_qualified": False,
                  "login_qualified": False, "graphics_qualified": False,
                  "networkPolicy": NETWORK_POLICY, "displayPort": self.s.display_port,
                  "resolution": "1280x720", "updatedAt": time.time(),
                  "graphicsMode": self.s.graphics_mode,
                  "renderer": "DXVK / Turnip (Adreno)" if self.s.graphics_mode == "turnip-dxvk" else "WineD3D / llvmpipe",
                  "graphicsPreflight": self.graphics_reports, "processCpu": process_cpu,
                  "clientWindow": self.window_report,
                  "memory": memory, **self.identities, **details}
        atomic_json(self.status_file, report)
        if self.children:
            atomic_json(self.journal, self.identities)
        print(message, flush=True)

    def environment(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("BOX64_", "FEX_", "DOTNET_", "COMPlus_"))
               and key not in ("DISPLAY", "LD_PRELOAD", "LD_LIBRARY_PATH", "HTTP_PROXY",
                               "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                               "EVE_WINDOW_SESSION")}
        env.update({"HOME": "/root", "PATH": "/opt/wine/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                    "DISPLAY": ":" + str(self.s.display_number),
                    "WINEPREFIX": str(self.s.state / "prefix"), "WINEARCH": "win64",
                    "WINEDEBUG": "-all,err+all", "WINEDLLOVERRIDES": "winemenubuilder,mshtml,mscoree=;d3d11,dxgi,crypt32=b",
                    "WINEESYNC": "0", "WINEFSYNC": "0", "FEX_DISABLETELEMETRY": "1",
                    "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe", "LP_NUM_THREADS": "4",
                    "EO_REMOTEFILECACHEFOLDER": "Z:\\client\\ResFiles",
                    "EVE_CLIENT_SENTRY_DSN": "http://evejs@127.0.0.1:26002/1",
                    "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1",
                    "SSL_CERT_FILE": "Z:\\client-state\\trust\\evejs-ca.pem"})
        return client_graphics.configure_environment(env, self.s.graphics_mode, self.s.graphics_folder, self.s.state)

    def require_server(self) -> None:
        value = read_json(self.s.server_state / "run/status.json")
        if value.get("phase") != "running" or value.get("ready") is not True:
            raise RuntimeErrorDetail("Start the local server and wait for SERVER READY first")
        identities = {key: value.get(key) for key in ("supervisorIdentity", "serverIdentity", "marketIdentity")}
        if not all(identity_alive(item) for item in identities.values()):
            raise RuntimeErrorDetail("The server readiness receipt is stale; start the server first")
        if self.server_identities and identities != self.server_identities:
            raise RuntimeErrorDetail("The owned server session changed while the client was running")
        self.server_identities = identities
        health = fetch_health("http://127.0.0.1:" + str(self.s.gateway_port) + "/health")
        self.verify_offline_health(health)

    @staticmethod
    def verify_offline_health(health: dict[str, Any]) -> None:
        policy = health.get("offlinePolicy", {})
        if (health.get("status") != "ok" or health.get("service") != "express-secondary"
                or health.get("gatewayMode") != "local" or policy.get("version") != 2
                or policy.get("proxyForwarding") != "disabled" or policy.get("clientFeatureFlags") != "defaults"):
            raise RuntimeErrorDetail("The local gateway did not confirm its offline policy")

    def preflight(self) -> dict[str, Any]:
        if os.environ.get("EVE_CLIENT_NETWORK_POLICY") != NETWORK_POLICY:
            raise RuntimeErrorDetail("The launcher must enable the native per-session loopback network restriction")
        self.verify_network_gate()
        marker = read_json(self.s.marker)
        if (marker.get("format"), marker.get("runtime"), marker.get("architecture")) != (2, "fex-arm64ec-1", "arm64"):
            raise RuntimeErrorDetail("Install the pinned Wine/FEX runtime first")
        if marker.get("wine_commit") != wine_trust_overlay.WINE_COMMIT:
            raise RuntimeErrorDetail("The private Wine trust fix requires the existing pinned Wine build")
        try:
            overlay = wine_trust_overlay.verify(self.s.trust_overlay, bound_root=self.s.trust_overlay_root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeErrorDetail("The private Wine trust fix could not be verified; export support logs") from error
        atomic_json(self.s.state / "wine-trust-overlay.json", {**overlay, "sessionBindingsVerified": True})
        for command in (self.s.wine, self.s.wineserver):
            with Path(command).open("rb") as source:
                header = source.read(20)
            if len(header) != 20 or header[:5] != b"\x7fELF\x02" or int.from_bytes(header[18:20], "little") != 183:
                raise RuntimeErrorDetail("Wine and wineserver must remain the pinned native ARM64 executables")
        if not self.s.gate.is_file() or self.s.gate.is_symlink():
            raise RuntimeErrorDetail("The APK is missing its Wine certificate and localhost TLS helper")
        self.verify_window_helper()
        probe = read_json(self.s.state / "probe.json")
        if probe.get("translated_x64_probe_passed") is not True or probe.get("exit_code") != 37:
            raise RuntimeErrorDetail("Pass Probe Wine / FEX before launching EVE")
        if not (self.s.state / "prefix/system.reg").is_file():
            raise RuntimeErrorDetail("The existing Wine prefix is missing; run the Wine/FEX probe first")
        try:
            self.graphics_bundle = client_graphics.prepare(self.s.graphics_folder, self.s.state, self.s.content, self.s.graphics_mode)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise RuntimeErrorDetail("Client graphics bundle could not be prepared: " + str(error)) from error
        if self.s.graphics_mode == "turnip-dxvk":
            atomic_json(self.s.state / "client-graphics-bundle.json", self.graphics_bundle)
        receipt = read_json(client_prepare.contained_file(self.s.content, "eve-client-content.json"))
        if (receipt.get("format") != 1 or receipt.get("build") != client_prepare.BUILD
                or receipt.get("resources", {}).get("complete") is not True
                or receipt.get("resources", {}).get("indexed_entries", 0) < 1):
            raise RuntimeErrorDetail("Validate and prepare the exact imported EVE client first")
        actual = client_prepare.validate_binaries(self.s.content, apply=False)
        expected_hashes = {row.get("file"): row.get("sha256") for row in receipt.get("binaries", [])}
        if len(expected_hashes) != len(actual) or any(expected_hashes.get(row["file"]) != row["sha256"] for row in actual):
            raise RuntimeErrorDetail("The prepared client binary receipt no longer matches its exact files")
        ini = client_prepare.ini_values(client_prepare.contained_file(self.s.content, "tq/start.ini"))
        if (ini.get("build"), ini.get("server"), ini.get("cryptopack")) != (str(client_prepare.BUILD), "127.0.0.1", "Placebo"):
            raise RuntimeErrorDetail("Validate and prepare the local client configuration again")
        prepared = read_json(self.s.state / "status.json")
        trust = prepared.get("trust", {})
        ca = self.s.server_state / "certs/xmpp-ca-cert.pem"
        imported_ca = self.s.state / "trust/evejs-ca.pem"
        try:
            current_sha = client_prepare.digest(ca)
            current_der_sha = client_prepare.certificate_sha256(ca)
            imported_der_sha = client_prepare.certificate_sha256(imported_ca)
        except (OSError, ValueError) as error:
            raise RuntimeErrorDetail("The local server CA copy is missing or invalid; Validate and prepare client again") from error
        # Old receipts bind the original server PEM bytes. Preparation wrote an
        # LF copy of Forge's CRLF PEM; compare certificate identity for that copy.
        # New receipts bind DER so harmless PEM formatting changes also work.
        receipt_matches = (trust.get("ca_der_sha256") == current_der_sha if "ca_der_sha256" in trust
                           else trust.get("ca_sha256") == current_sha)
        if (prepared.get("phase") != "content_prepared" or trust.get("bundles_prepared") is not True
                or not receipt_matches or imported_der_sha != current_der_sha):
            raise RuntimeErrorDetail("The local server CA changed; Validate and prepare client again")
        self.require_server()
        self.memory_check()
        return {"contentBuild": client_prepare.BUILD, "binarySha256": expected_hashes,
                "caPemSha256": current_sha, "caDerSha256": current_der_sha,
                "wineTrustOverlay": overlay["overlay"], "graphicsMode": self.s.graphics_mode}

    def verify_window_helper(self) -> None:
        try:
            if (not self.window_helper.is_file() or self.window_helper.is_symlink()
                    or not 0 < self.window_helper.stat().st_size <= WINDOW_HELPER_LIMIT):
                raise ValueError("Invalid helper file")
            with self.window_helper.open("rb") as source:
                header = source.read(4096)
            offset = int.from_bytes(header[60:64], "little")
            if (len(header) < 64 or header[:2] != b"MZ" or offset < 64 or offset + 94 > len(header)
                    or header[offset:offset + 4] != b"PE\0\0"
                    or int.from_bytes(header[offset + 4:offset + 6], "little") != 0x8664
                    or int.from_bytes(header[offset + 24:offset + 26], "little") != 0x20b
                    or int.from_bytes(header[offset + 92:offset + 94], "little") != 3):
                raise ValueError("Helper is not original x64 PE")
        except (OSError, ValueError) as error:
            raise RuntimeErrorDetail("The APK is missing its original x64 client window helper") from error

    def launch_client(self) -> None:
        if self.s.client_command is not None:
            # Constructor-only process fixtures retain their direct launch path.
            self.spawn("client", self.s.client_command, cwd=self.s.content / "tq")
            return
        self.window_session = uuid.uuid4().hex
        self.window_child_ids = None
        self.window_report = {}
        try:
            previous = self.window_receipt.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISREG(previous.st_mode) and previous.st_size <= WINDOW_RECEIPT_LIMIT:
                self.window_receipt.replace(self.window_receipt.with_name(self.window_receipt.name + ".1"))
            elif stat.S_ISREG(previous.st_mode) or stat.S_ISLNK(previous.st_mode):
                self.window_receipt.unlink()
            else:
                raise RuntimeErrorDetail("The previous client window receipt is invalid; export support logs")
        environment = self.environment()
        environment["EVE_WINDOW_SESSION"] = self.window_session
        command = (self.s.wine, "Z:" + str(self.window_helper).replace("/", "\\"))
        self.spawn("client", command, env=environment, cwd=self.s.content / "tq")

    def check_window_receipt(self) -> dict[str, Any] | None:
        if self.window_session is None:
            return None
        try:
            if self.window_receipt.is_symlink():
                raise ValueError("Linked receipt")
            value = json.loads(client_prepare.bounded_text(self.window_receipt, limit=WINDOW_RECEIPT_LIMIT))
        except FileNotFoundError:
            if self.window_child_ids is not None:
                raise RuntimeErrorDetail("The owned client window receipt disappeared; export support logs")
            return None
        except (OSError, ValueError, TypeError, RecursionError) as error:
            raise RuntimeErrorDetail("The owned client window receipt is invalid; export support logs") from error
        try:
            if (not isinstance(value, dict) or type(value.get("format")) is not int or value["format"] != 1
                    or value.get("helper") != "eve-client-window-1" or value.get("session") != self.window_session
                    or not re.fullmatch(r"[0-9a-f]{32}", self.window_session)
                    or value.get("phase") not in ("child_created", "window_observed", "child_exited", "failed")):
                raise ValueError("Wrong receipt identity")
            elapsed = value.get("elapsedMs")
            if type(elapsed) is not int or not 0 <= elapsed <= 2**63 - 1:
                raise ValueError("Invalid elapsed time")
            if value["phase"] == "failed":
                raise RuntimeErrorDetail("The owned client window helper failed; export support logs")
            pids = (value.get("wrapperWindowsPid"), value.get("childWindowsPid"))
            if any(type(pid) is not int or not 0 < pid <= 0xffffffff for pid in pids) or pids[0] == pids[1]:
                raise ValueError("Invalid Windows process identities")
            exit_code = value.get("childExitCode")
            if exit_code is not None and (type(exit_code) is not int or not 0 <= exit_code <= 0xffffffff):
                raise ValueError("Invalid exit code")
            if self.window_child_ids is not None and pids != self.window_child_ids:
                raise ValueError("Changed Windows process identities")
            if value["phase"] == "child_exited":
                raise RuntimeErrorDetail("EVE exited while its owned client window helper was running")
            if exit_code is not None:
                raise ValueError("Live child has an exit code")
            safe = {key: value[key] for key in ("format", "helper", "session", "phase", "wrapperWindowsPid",
                                               "childWindowsPid", "elapsedMs", "childExitCode") if key in value}
            for key in ("windowsOwned", "visibleWindows", "unownedWindows", "iconicWindows"):
                if key in value:
                    if type(value[key]) is not int or not 0 <= value[key] <= 256:
                        raise ValueError("Invalid window count")
                    safe[key] = value[key]
            for key, limit in (("selectedWindow", 2**64 - 1), ("focusAttemptWindow", 2**64 - 1),
                               ("windowThreadId", 0xffffffff), ("probeWin32Error", 0xffffffff),
                               ("win32Error", 0xffffffff), ("probeTimeoutMs", 50)):
                if key in value:
                    if type(value[key]) is not int or not 0 <= value[key] <= limit:
                        raise ValueError("Invalid window integer")
                    safe[key] = value[key]
            for key in ("windowScanTruncated", "windowVisible", "windowIconic", "foregroundOwned", "focusOwned",
                        "guiInfoAvailable", "focusAttempted", "focusCallSucceeded", "focusSucceeded", "restoreQueued",
                        "raiseQueued", "observationComplete", "startupWindowTimedOut"):
                if key in value:
                    if type(value[key]) is not bool:
                        raise ValueError("Invalid window flag")
                    safe[key] = value[key]
            for key in ("focusAttemptElapsedMs", "responsive", "rect"):
                if key not in value:
                    continue
                item = value[key]
                if item is not None:
                    if key == "responsive" and type(item) is not bool:
                        raise ValueError("Invalid responsiveness flag")
                    if key == "focusAttemptElapsedMs" and (type(item) is not int or not 0 <= item <= 2**63 - 1):
                        raise ValueError("Invalid focus time")
                    if key == "rect":
                        if (not isinstance(item, dict) or set(item) != {"left", "top", "right", "bottom"}
                                or any(type(coordinate) is not int or not -(2**31) <= coordinate < 2**31
                                       for coordinate in item.values())):
                            raise ValueError("Invalid window rectangle")
                safe[key] = item
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeErrorDetail("The owned client window receipt is invalid; export support logs") from error
        self.window_child_ids = pids
        # Receipt metadata cannot alter process ownership or readiness claims.
        self.window_report = safe
        return self.window_report

    def wait_window_child(self) -> None:
        if self.window_session is None:
            return
        deadline = time.monotonic() + self.s.window_start_timeout
        last_health = 0.0
        while time.monotonic() < deadline:
            self.cancellation_point()
            self.refresh_owned_processes(persist=True)
            self.check_child("display")
            self.check_child("wineServer")
            self.check_child("client")
            self.memory_check()
            if time.monotonic() - last_health >= 5:
                self.require_server()
                last_health = time.monotonic()
            if self.check_window_receipt() is not None:
                self.refresh_owned_processes(persist=True)
                return
            time.sleep(self.s.tick)
        raise RuntimeErrorDetail("The client window helper did not confirm EVE process creation within 20 seconds")

    @staticmethod
    def verify_network_gate() -> None:
        # PRoot cancels these syscalls before any packet is sent. Require its
        # immediate denial instead of mistaking a connection timeout for policy.
        for protocol in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(socket.AF_INET, protocol) as probe:
                probe.settimeout(1)
                try:
                    if protocol == socket.SOCK_STREAM:
                        probe.connect(("192.0.2.1", 443))
                    else:
                        probe.sendto(b"eve-network-policy-probe", ("192.0.2.1", 443))
                except OSError as error:
                    if error.errno == errno.EACCES:
                        continue
                    raise RuntimeErrorDetail("The native client network gate did not reject outbound traffic") from error
                raise RuntimeErrorDetail("The native client network gate permitted outbound traffic")

    def memory_check(self) -> None:
        available = available_memory_kib()
        if available is not None and available < self.s.minimum_available_kib:
            raise RuntimeErrorDetail("EVE startup stopped before exhausting Android memory; export support logs")

    def spawn(self, role: str, command: tuple[str, ...], env: dict[str, str] | None = None,
              cwd: Path | None = None) -> subprocess.Popen:
        self.cancellation_point()
        self.logs.mkdir(parents=True, exist_ok=True)
        path = self.logs / ("client-" + role + ".log")
        rotate_log(path)
        process = subprocess.Popen(command, env=env or self.environment(), cwd=cwd or self.s.state,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        self.children[role] = process
        self.identities[role + "Identity"] = process_identity(process.pid)
        atomic_json(self.journal, self.identities)

        def pump():
            stream = path.open("wb")
            size = 0
            try:
                while chunk := process.stdout.read1(16384):
                    if size + len(chunk) > LOG_LIMIT:
                        stream.close()
                        rotate_log(path)
                        stream = path.open("wb")
                        size = 0
                    stream.write(chunk)
                    stream.flush()
                    size += len(chunk)
            finally:
                stream.close()
                process.stdout.close()

        thread = threading.Thread(target=pump, daemon=True)
        self.pumps.append(thread)
        thread.start()
        snapshot = self.refresh_owned_processes(persist=True)
        if role == "client":
            self.diagnostics.begin()
            self.diagnostics.wrapper_pid = process.pid if self.window_session is not None else None
            self.diagnostics.report.update(
                wrappedClient=self.window_session is not None,
                graphicsMode=self.s.graphics_mode if self.s.graphics_mode in client_graphics.MODES else "unknown",
                dxvkVersion=client_graphics.DXVK_VERSION, mesaVersion=client_graphics.MESA_VERSION)
            for name in ("supervisorIdentity", "clientIdentity"):
                identity = self.identities.get(name, {})
                if isinstance(identity.get("pid"), int) and str(identity.get("startTicks", "")).isdigit():
                    self.diagnostics.report[name] = {"pid": identity["pid"], "startTicks": identity["startTicks"]}
            self.diagnostics.sample(snapshot, {name: child.pid for name, child in self.children.items()}, "starting")
        return process

    def wait_graphics(self, role: str, command: tuple[str, ...], env: dict[str, str], timeout: float) -> None:
        process = self.spawn(role, command, env=env)
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            self.cancellation_point()
            self.check_child("display")
            self.check_child("wineServer")
            self.memory_check()
            self.refresh_owned_processes(persist=True)
            if time.monotonic() >= deadline:
                raise RuntimeErrorDetail(role + " qualification timed out; export support logs or use software recovery")
            time.sleep(self.s.tick)
        self.refresh_owned_processes(persist=True)
        for pump in self.pumps:
            pump.join(timeout=.3)
        if process.returncode != 0:
            raise RuntimeErrorDetail(role + " qualification failed; inspect client-" + role + ".log or use software recovery")

    def run_graphics(self) -> dict[str, Any]:
        if self.s.graphics_mode == "software":
            return {"mode": "software", "hardwarePreflightPassed": False}
        env = self.environment()
        # The initialized, accepted prefix is required before these session-only
        # file binds. Recheck after Wine bootstrap/TLS so a refresh cannot corrupt
        # an asset and then be mistaken for a working native renderer.
        client_graphics.verify_mapped(self.s.graphics_folder, self.s.state)
        self.status("starting", "Checking the Adreno GPU and Turnip Vulkan display", displayReady=True)
        native = self.s.vulkan_command or client_graphics.native_command(self.s.graphics_folder)
        self.wait_graphics("graphicsVulkan", native, env, min(30, self.s.graphics_timeout))
        vulkan = client_graphics.parse_vulkan(client_prepare.bounded_text(self.logs / "client-graphicsVulkan.log", limit=65536))
        self.status("starting", "Checking native D3D11 shaders and their visible display frames", displayReady=True)
        display_report = self.run / "graphics-display.json"
        helper_log = self.logs / "client-graphicsD3d-helper.log"
        helper_errors = self.logs / "client-graphicsD3d-helper-errors.log"
        display_report.unlink(missing_ok=True)
        for path in (helper_log, helper_errors):
            rotate_log(path)
        helper_env = dict(env)
        helper_env.pop("DXVK_HUD", None)
        helper_env["WINEDLLOVERRIDES"] += ";d3dcompiler_47=b"
        helper = client_graphics.d3d_command(self.s.graphics_folder, self.graphics_bundle, self.s.wine)
        command = self.s.d3d_command or (
            sys.executable, str(self.s.graphics_folder / "graphics_present.py"),
            "--port", str(self.s.display_port), "--timeout", str(max(1, self.s.graphics_timeout-10)),
            "--report", str(display_report), "--stdout", str(helper_log), "--stderr", str(helper_errors), "--", *helper)
        self.wait_graphics("graphicsD3d", command, helper_env, self.s.graphics_timeout)
        d3d = client_graphics.parse_d3d(client_prepare.bounded_text(helper_log, limit=65536), self.graphics_bundle)
        visible = client_graphics.parse_display(client_prepare.bounded_text(display_report, limit=65536))
        client_graphics.verify_mapped(self.s.graphics_folder, self.s.state)
        report = {"mode": "turnip-dxvk", "observedAt": time.time(), "supervisorIdentity": self.identities.get("supervisorIdentity"), "hardwarePreflightPassed": True,
                  "vulkan": vulkan, "d3d11": d3d, "display": visible,
                  "qualificationScope": "native hardware D3D11 helper and local display; EVE performance requires observation"}
        atomic_json(self.s.state / "graphics-preflight.json", report)
        return report

    def update_local_hosts(self) -> None:
        aliases = set()
        for value in (socket.gethostname(), self.tls_report.get("computer_name_dns_fqdn", "")):
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}", value):
                aliases.update((value, value.split(".", 1)[0]))
        aliases = {item for item in aliases if item.casefold() != "localhost"}
        suffix = " " + " ".join(sorted(aliases)) if aliases else ""
        # Private guest hosts only; preserve localhost as the canonical name.
        self.s.hosts_file.write_text("127.0.0.1 localhost" + suffix + "\n::1 localhost" + suffix + "\n")

    def run_gate(self) -> dict[str, Any]:
        command = self.s.gate_command or (self.s.wine, str(self.s.gate), "Z:\\client-state\\trust\\evejs-ca.pem")
        env = self.environment()
        env["WINEDEBUG"] = "-all,err+all,warn+winhttp,warn+crypt,warn+chain,warn+secur32"
        process = self.spawn("gate", command, env=env)
        deadline = time.monotonic() + self.s.gate_timeout
        while process.poll() is None:
            self.cancellation_point()
            self.check_child("display")
            self.check_child("wineServer")
            self.memory_check()
            self.refresh_owned_processes(persist=True)
            if time.monotonic() >= deadline:
                raise RuntimeErrorDetail("Wine certificate / localhost TLS qualification timed out; inspect client-gate.log")
            time.sleep(self.s.tick)
        for pump in self.pumps:
            pump.join(timeout=.3)
        path = self.logs / "client-gate.log"
        with path.open("rb") as source:
            source.seek(max(0, path.stat().st_size - 65536))
            tail = source.read(65536).decode("utf-8", errors="replace")
        result = None
        for line in reversed(tail.splitlines()):
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict) and candidate.get("helper") == "eve-client-gate-1":
                result = candidate
                break
        if (process.returncode != 0 or result is None or result.get("format") != 1
                or result.get("success") is not True or result.get("wine_cryptoapi_trust") is not True
                or result.get("localhost443_tls") is not True
                or result.get("root_store") != "CurrentUser\\ROOT"
                or result.get("tls_url") != "https://localhost/health" or result.get("tls_proxy") != "none"
                or result.get("tls_certificate_checks") != "default" or result.get("http_status") != 200):
            details = (" (stage=" + str(result.get("stage", "unknown"))[:80]
                       + ", win32_error=" + str(result.get("win32_error", "unknown"))[:20] + ")") if result else ""
            raise RuntimeErrorDetail("Wine certificate / localhost TLS qualification failed" + details + "; inspect client-gate.log")
        der_sha = client_prepare.certificate_sha256(self.s.server_state / "certs/xmpp-ca-cert.pem")
        if result.get("ca_der_sha256") != der_sha:
            raise RuntimeErrorDetail("Wine TLS helper used a different local server CA")
        self.verify_offline_health(json.loads(result.get("response_body", "")))
        atomic_json(self.s.state / "client-gate.json", result)
        return result

    def check_child(self, role: str) -> None:
        process = self.children.get(role)
        if process is not None and process.poll() is not None:
            raise RuntimeErrorDetail(role + " exited unexpectedly with code " + str(process.returncode))

    def wait_display(self) -> None:
        deadline = time.monotonic() + min(30, self.s.startup_timeout)
        while time.monotonic() < deadline:
            self.cancellation_point()
            self.check_child("display")
            try:
                with socket.create_connection(("127.0.0.1", self.s.display_port), timeout=.5) as connection:
                    if connection.recv(12).startswith(b"RFB "):
                        return
            except OSError:
                pass
            time.sleep(self.s.tick)
        raise RuntimeErrorDetail("The private client display did not start; inspect client-display.log")

    def wine_socket(self) -> Path:
        # This is the pinned Wine Unix server.c socket naming convention. Wait
        # for our foreground server before any Wine client can auto-start a
        # competing daemon outside the recorded process group.
        prefix = (self.s.state / "prefix").stat()
        directory = "server-" + format(prefix.st_dev, "x") + "-" + format(prefix.st_ino, "x")
        return Path("/tmp") / (".wine-" + str(os.getuid())) / directory / "socket"

    def wait_wineserver(self) -> None:
        if self.s.wineserver_command is not None:
            # Constructor-only process fixtures have no Wine protocol socket.
            self.check_child("wineServer")
            return
        path = self.wine_socket()
        deadline = time.monotonic() + min(15, self.s.startup_timeout)
        while time.monotonic() < deadline:
            self.cancellation_point()
            self.check_child("display")
            self.check_child("wineServer")
            if path.is_socket() and self.wine_socket_owned(path):
                # Never treat a socket left by an exited owned server as ready.
                self.check_child("wineServer")
                return
            time.sleep(self.s.tick)
        raise RuntimeErrorDetail("The owned Wine server did not create its private socket; inspect client-wineServer.log")

    def wine_socket_owned(self, path: Path) -> bool:
        # A leftover pathname can predate this foreground server. Linux peer
        # credentials distinguish our owned server from a stale socket or a
        # different prefix daemon without sending any Wine protocol message.
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(.25)
                probe.connect(str(path))
                peer_pid, _, _ = struct.unpack("3i", probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                return peer_pid == self.identities.get("wineServerIdentity", {}).get("pid")
        except (OSError, ValueError):
            return False

    def preflight_display(self) -> None:
        with socket.socket() as listener:
            # RFB probes can leave TIME_WAIT after a clean stop. Reuse those
            # closed sockets while still rejecting a live listener.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", self.s.display_port))
            except OSError as error:
                raise RuntimeErrorDetail("The private client display port is already in use") from error

    def signal_group(self, identity: dict[str, Any], members: list[dict[str, Any]], signum: int) -> None:
        pid = identity.get("pid")
        if not isinstance(pid, int) or pid <= 1:
            raise RuntimeErrorDetail("Invalid owned client process identity")
        current = group_members(pid)
        if not current:
            return
        root = process_record(pid) if identity_alive(identity) else None
        known = any(identity_alive(member) and member.get("pid") in {item["pid"] for item in current}
                    for member in members)
        if root and (root["group"] != pid or root["session"] != pid):
            raise RuntimeErrorDetail("Owned client process no longer has its isolated session")
        if root is None and not known:
            raise RuntimeErrorDetail("Unverified client process group remains; refusing unrelated process cleanup")
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signum)

    def cleanup_identity(self, identity: dict[str, Any], members: list[dict[str, Any]]) -> bool:
        pid = identity["pid"]
        self.signal_group(identity, members, signal.SIGTERM)
        deadline = time.monotonic() + self.s.shutdown_timeout
        while group_members(pid) and time.monotonic() < deadline:
            for process in self.children.values():
                process.poll()
            time.sleep(self.s.tick)
        forced = bool(group_members(pid))
        if forced:
            self.signal_group(identity, members, signal.SIGKILL)
            deadline = time.monotonic() + 3
            while group_members(pid) and time.monotonic() < deadline:
                for process in self.children.values():
                    process.poll()
                time.sleep(self.s.tick)
        if group_members(pid):
            raise RuntimeErrorDetail("Owned client processes remain after cleanup")
        return not forced

    def recover(self) -> None:
        if not self.journal.is_file():
            return
        journal = read_json(self.journal)
        if identity_alive(journal.get("supervisorIdentity")):
            raise BusyError("The recorded EVE client supervisor is still alive")
        clean = True
        for role in OWNED_ROLES:
            identity = journal.get(role + "Identity")
            if isinstance(identity, dict):
                clean = self.cleanup_identity(identity, journal.get(role + "Members", [])) and clean
        self.journal.unlink(missing_ok=True)
        self.status("stopped", "Previous EVE client processes recovered; imported content preserved", cleanShutdown=clean)
        if not clean:
            raise RuntimeErrorDetail("Previous EVE client required forced cleanup; export support logs before retrying")

    def shutdown(self) -> bool:
        clean = True
        # This targets only our dedicated Wine prefix, never another launcher.
        if "wineServer" in self.children and self.s.wineserver_command is None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run((self.s.wineserver, "-k"), env=self.environment(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        for role in OWNED_ROLES:
            process = self.children.get(role)
            if process is None:
                continue
            identity = self.identities[role + "Identity"]
            members = self.identities.get(role + "Members", [])
            clean = self.cleanup_identity(identity, members) and clean
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
        for pump in self.pumps:
            pump.join(timeout=1)
        return clean

    def start(self) -> None:
        with self.exclusive():
            self.recover()
            self.identities = {"supervisorIdentity": process_identity(os.getpid())}
            failure = None
            clean = True
            try:
                self.cancellation_point()
                self.status("starting", "Checking the prepared client and local server")
                qualification = self.preflight()
                self.preflight_display()
                self.cancellation_point()
                display_command = self.s.display_command or (
                    self.s.display, ":" + str(self.s.display_number), "-geometry", "1280x720", "-depth", "24",
                    "-rfbport", str(self.s.display_port), "-localhost", "yes", "-SecurityTypes", "None",
                    "-nolisten", "tcp", "-ac", "-AlwaysShared", "-FrameRate",
                    "30" if self.s.graphics_mode == "turnip-dxvk" else "15", "-desktop", "EVE Local Preview")
                self.status("starting", "Starting the private client display")
                self.spawn("display", display_command)
                self.wait_display()
                self.status("starting", "Checking Wine certificate trust and localhost TLS", displayReady=True)
                self.spawn("wineServer", self.s.wineserver_command or (self.s.wineserver, "-f", "-p"))
                self.wait_wineserver()
                self.tls_report = self.run_gate()
                if self.s.gate_command is None:
                    self.update_local_hosts()
                self.graphics_reports = self.run_graphics()
                self.cancellation_point()
                self.status("starting", "Launching EVE build 3396210 through the existing Wine/FEX runtime", displayReady=True,
                            wineTrustQualified=True, localhostTlsQualified=True)
                if self.s.graphics_mode == "turnip-dxvk":
                    client_graphics.verify_mapped(self.s.graphics_folder, self.s.state)
                    for name in ("exefile_d3d11.log", "exefile_dxgi.log"):
                        rotate_log(self.logs / name)
                # GPU qualification can take minutes; the previously accepted
                # server session must still be alive before starting EVE.
                self.require_server()
                self.launch_client()
                self.wait_window_child()
                deadline = time.monotonic() + self.s.observe_seconds
                while time.monotonic() < deadline:
                    self.cancellation_point()
                    self.check_child("display")
                    self.check_child("wineServer")
                    self.check_child("client")
                    self.check_window_receipt()
                    self.memory_check()
                    time.sleep(self.s.tick)
                self.check_child("client")
                self.check_window_receipt()
                atomic_json(self.s.state / "launch-observation.json", {
                    "format": 1, "observedAt": time.time(), **qualification,
                    "processStartupObserved": True, "login_qualified": False,
                    "graphics_qualified": False, "wine_cryptoapi_trust": True, "localhost443_tls": True,
                    "networkPolicy": NETWORK_POLICY, "renderer": "DXVK / Turnip (Adreno)" if self.s.graphics_mode == "turnip-dxvk" else "WineD3D / llvmpipe",
                    "graphicsPreflight": self.graphics_reports, "clientWindow": self.window_report,
                    "displayPort": self.s.display_port})
                last_health = 0.0
                while not self.stopping():
                    self.check_child("display")
                    self.check_child("wineServer")
                    self.check_child("client")
                    self.memory_check()
                    if time.monotonic() - last_health >= 5:
                        self.require_server()
                        self.check_window_receipt()
                        self.status("running", "EVE process and display started; check the client login screen", True,
                                    displayReady=True, processStartupObserved=True,
                                    wineTrustQualified=True, localhostTlsQualified=True)
                        last_health = time.monotonic()
                    time.sleep(self.s.tick)
            except InterruptedError:
                pass
            except BaseException as error:
                failure = error
            finally:
                self.status("stopping", "Stopping the EVE client and its private display")
                try:
                    clean = self.shutdown()
                except BaseException as error:
                    failure = failure or error
                    clean = False
                if failure or not clean:
                    self.status("failed", "EVE client stopped after a startup or session failure", cleanShutdown=clean,
                                error=str(failure) if failure else "EVE processes required forced cleanup")
                else:
                    self.status("stopped", "EVE client and display stopped; imported content preserved", cleanShutdown=True)
                if not any(group_members(process.pid) for process in self.children.values()):
                    self.journal.unlink(missing_ok=True)
            if failure:
                raise RuntimeErrorDetail(str(failure)) from failure
            if not clean:
                raise RuntimeErrorDetail("EVE client required forced cleanup")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "recover"))
    parser.add_argument("--content", type=Path, default=Path("/client"))
    parser.add_argument("--state", type=Path, default=Path("/client-state"))
    parser.add_argument("--server-state", type=Path, default=Path("/server-state"))
    parser.add_argument("--graphics-mode", choices=client_graphics.MODES, default="turnip-dxvk")
    options = parser.parse_args(argv)
    runtime = Runtime(Settings(content=options.content, state=options.state, server_state=options.server_state,
                               graphics_mode=options.graphics_mode))
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, runtime.request_stop)
    try:
        if options.action == "start":
            runtime.start()
        else:
            with runtime.exclusive():
                runtime.recover()
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print("EVE client runtime: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
