#!/usr/bin/env python3
"""Actual-syscall integration proof and AF_UNIX benchmark for two PRoot builds.

Run in a Linux container with --network none --cap-add=SYS_PTRACE
--security-opt seccomp=unconfined. Only the loopback interface may be visible.
No credentials, retail EVE assets, Wine prefix, or server database are used.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import socket
import statistics
import subprocess
import tempfile
import threading
import time


class Fixtures:
    def __init__(self):
        self.stop = threading.Event()
        self.tcp = socket.socket()
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("127.0.0.1", 26003))
        self.tcp.listen(16)
        self.tcp.settimeout(.05)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(.05)
        self.port = self.udp.getsockname()[1]
        self.received = Counter()
        self.redirected = 0
        self.errors = []
        self.threads = [threading.Thread(target=self.serve_tcp, daemon=True),
                        threading.Thread(target=self.serve_udp, daemon=True)]

    def serve_tcp(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.tcp.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(2)
                try:
                    data = b""
                    while len(data) < 4:
                        piece = connection.recv(4 - len(data))
                        if not piece:
                            break
                        data += piece
                    if data != b"ping":
                        self.errors.append("redirect fixture received unexpected bytes")
                    else:
                        connection.sendall(b"ok")
                        self.redirected += 1
                except OSError as error:
                    self.errors.append(str(error))

    def serve_udp(self):
        while not self.stop.is_set():
            try:
                payload, peer = self.udp.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if peer[0] != "127.0.0.1":
                self.errors.append("UDP peer is not IPv4 loopback")
            self.received[payload] += 1

    def __enter__(self):
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.tcp.close()
        self.udp.close()
        for thread in self.threads:
            thread.join(timeout=3)

    def verify(self, expected_policy_runs):
        deadline = time.monotonic() + 1
        expected = [b"sendmmsg-first", b"sendmmsg-second", b"sendmmsg-third",
                    b"sendmsg-local", b"connected-sendmmsg"]
        while time.monotonic() < deadline and any(self.received[x] < expected_policy_runs for x in expected):
            time.sleep(.01)
        if self.errors:
            raise RuntimeError("; ".join(self.errors))
        if self.redirected != expected_policy_runs * 3:
            raise RuntimeError("TLS-port redirect fixture count differs")
        for payload in expected:
            if self.received[payload] != expected_policy_runs:
                raise RuntimeError(f"UDP fixture mismatch for {payload!r}")
        if any(payload not in expected and payload != b"R" for payload in self.received):
            raise RuntimeError("blocked or unknown datagram reached the loopback fixture")


def isolated_network():
    interfaces = {path.name for path in Path("/sys/class/net").iterdir()}
    if interfaces != {"lo"}:
        raise RuntimeError("Run in a container with --network none; only loopback may be visible")
    # Require the protection independently of any PRoot filter being evaluated.
    for row in Path("/proc/net/route").read_text().splitlines()[1:]:
        fields = row.split()
        if fields and fields[0] != "lo":
            raise RuntimeError("The proof container has a non-loopback route")
    ipv6_routes = Path("/proc/net/ipv6_route")
    if ipv6_routes.exists():
        for row in ipv6_routes.read_text().splitlines():
            if row.split()[-1] != "lo":
                raise RuntimeError("The proof container has a non-loopback IPv6 route")
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError as error:
        raise RuntimeError("The proof container must enable IPv6 loopback (::1); "
                           "this kernel prerequisite is checked before either PRoot build") from error


def invoke(binary, probe, loader, temporary, port, arguments, mode, acceleration):
    environment = dict(os.environ)
    for key in ("PROOT_NO_SECCOMP", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        environment.pop(key, None)
    if not acceleration:
        environment["PROOT_NO_SECCOMP"] = "1"
    environment["PROOT_TMP_DIR"] = str(temporary)
    environment["TRASC_PROOT_REPORT"] = "1"
    if loader:
        environment["PROOT_LOADER"] = str(loader)
    command = [str(binary), "--kill-on-exit", "--eve-client-network", "--sysvipc", "-0", "-r", "/",
               str(probe), str(port), str(arguments.race_iterations), str(arguments.iterations), mode]
    process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        # PRoot's --kill-on-exit handles TERM; subprocess.run's immediate KILL
        # would bypass its cleanup handler. The fixture's descendants inherit
        # this fresh process group and never create a separate session.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"{binary.name} {mode} acceleration={acceleration}: "
                           "timed out; owned fixture group terminated\n" + stderr[-8000:])
    if process.returncode != 0:
        # The last messages include assertion diagnostics without flooding CI logs
        # with intentional denied-race notices.
        raise RuntimeError(f"{binary.name} {mode} acceleration={acceleration}: "
                           f"exit {process.returncode}\n" + stderr[-8000:])
    observed = "TRASC PRoot: seccomp acceleration observed" in stderr
    if acceleration and not observed:
        raise RuntimeError("The accelerated proof did not observe active PRoot acceleration")
    if not acceleration and observed:
        raise RuntimeError("The fallback proof unexpectedly enabled PRoot acceleration")
    if "EVE client network: loopback gate active; localhost:443 -> 26003" not in stderr:
        raise RuntimeError("The proof did not observe active EVE network policy")
    rows = [row for row in stdout.splitlines() if row.startswith("{")]
    if len(rows) != 1:
        raise RuntimeError("Native probe did not return one JSON report")
    value = json.loads(rows[0])
    value["accelerationObserved"] = observed
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--race-iterations", type=int, default=2000)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.iterations, args.race_iterations, args.runs) < 1:
        parser.error("Iteration counts and runs must be positive")
    for path in (args.baseline, args.candidate, args.loader):
        if path is not None and not path.resolve().is_file():
            parser.error(f"Missing executable: {path}")
    args.baseline = args.baseline.resolve()
    args.candidate = args.candidate.resolve()
    if args.loader:
        args.loader = args.loader.resolve()
    isolated_network()
    with tempfile.TemporaryDirectory(prefix="eve-proot-policy-") as raw:
        temporary = Path(raw)
        probe = temporary / "network-policy-probe"
        source = Path(__file__).with_name("network-policy-probe.c")
        subprocess.run(["cc", "-O2", "-std=c11", "-pthread", "-Wall", "-Wextra",
                        str(source), "-o", str(probe)], check=True)
        report = {"format": 1, "scope": "native PRoot actual-syscall isolated-network fixture",
                  "architecture": os.uname().machine, "network": "loopback only",
                  "iterations": args.iterations, "policyRuns": [], "benchmark": {},
                  "limitations": "No EVE, Wine, FEX, Android GPU, or input-latency measurements."}
        with Fixtures() as fixtures:
            policy_runs = 0
            for name, binary in (("baseline", args.baseline), ("candidate", args.candidate)):
                for acceleration in (True, False):
                    policy = invoke(binary, probe, args.loader, temporary, fixtures.port,
                                    args, "policy", acceleration)
                    report["policyRuns"].append({"variant": name, "acceleration": acceleration, **policy})
                    policy_runs += 1
                values = []
                # Warmup exercises startup and the fixture but does not enter the reported sample.
                invoke(binary, probe, args.loader, temporary, fixtures.port, args, "benchmark", True)
                for _ in range(args.runs):
                    sample = invoke(binary, probe, args.loader, temporary, fixtures.port,
                                    args, "benchmark", True)
                    values.append(sample["sendmsgMilliseconds"])
                report["benchmark"][name] = {"samplesMilliseconds": values,
                                             "medianMilliseconds": statistics.median(values)}
            fixtures.verify(policy_runs)
            report["fixtureRedirectedConnections"] = fixtures.redirected
            report["fixtureRaceDatagrams"] = fixtures.received[b"R"]
        baseline = report["benchmark"]["baseline"]["medianMilliseconds"]
        candidate = report["benchmark"]["candidate"]["medianMilliseconds"]
        report["benchmark"]["candidateChangePercent"] = 100 * (candidate - baseline) / baseline
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered)
        print(rendered, end="")


if __name__ == "__main__":
    main()
