"""Bounded client performance history; never read input, argv, stacks or caches.

Process ownership is supplied by the supervisor's fresh filtered snapshot. This
module reports observations only and never adopts or signals any process.
"""

from __future__ import annotations

from collections import Counter, deque
import errno
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from typing import Any

import server_runtime


FILE_LIMIT = 256 * 1024
SAMPLE_LIMIT = 120
SAMPLE_SECONDS = 5
CACHE_SECONDS = 30
HARDWARE_SECONDS = 10
CPU_LIMIT = 8
THERMAL_ZONE_LIMIT = 32
TASK_LIMIT = 256
THREAD_ROWS = 16
MAIN_ROWS = 4
CACHE_ENTRY_LIMIT = 4096
STAT_LIMIT = 4096
ROLES = ("client", "graphicsD3d", "graphicsVulkan", "gate", "wineServer", "display")
PHASES = ("starting", "running", "stopping", "stopped", "failed")
THREAD_CLASSES = {
    "dxvk-shader-h": "shader-high",
    "dxvk-shader-n": "shader-normal",
    "dxvk-shader-l": "shader-low",
    "dxvk-submit": "submission",
    "dxvk-queue": "completion",
    "dxvk-frame": "presentation",
}


def _bounded_text(path: Path, limit: int) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Oversized proc record")
    return value


def _sysfs_text(path: Path, limit: int) -> tuple[str | None, str | None]:
    try:
        return _bounded_text(path, limit).strip(), None
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR):
            return None, "missing"
        if isinstance(error, PermissionError) or error.errno in (errno.EACCES, errno.EPERM):
            return None, "permission-denied"
        return None, "unavailable"
    except ValueError:
        return None, "malformed"


def _sysfs_number(path: Path, minimum: int, maximum: int) -> tuple[int | None, str | None]:
    raw, error = _sysfs_text(path, 32)
    if error is not None:
        return None, error
    if not re.fullmatch(r"[+-]?[0-9]{1,12}", raw or ""):
        return None, "malformed"
    value = int(raw)
    return (value, None) if minimum <= value <= maximum else (None, "malformed")


def hardware_metrics(sysfs: Path) -> dict[str, Any]:
    """Read only fixed, bounded kernel attributes; unavailable is not zero.

    CPUFreq scaling frequencies are kHz: cur is often the requested P-state,
    and max is the policy ceiling, not the hardware's maximum frequency.
    https://www.kernel.org/doc/html/latest/admin-guide/pm/cpufreq.html
    Devfreq and KGSL gpuclk report Hz; gpuclk can be the active power-level
    setting rather than a measured hardware clock. Neither measures load.
    Thermal-zone temp is millidegree Celsius; type is the driver's identifier.
    https://docs.kernel.org/driver-api/thermal/sysfs-api.html
    Class/policy symlinks are normal sysfs ABI; no directory traversal is used.
    """
    gpu: dict[str, Any] = {}
    gpu_path = sysfs / "class/kgsl/kgsl-3d0"
    for label, suffix in (("curFreqHz", "devfreq/cur_freq"),
                          ("maxFreqHz", "devfreq/max_freq"), ("gpuclkHz", "gpuclk")):
        value, error = _sysfs_number(gpu_path / suffix, 0, 100_000_000_000)
        if error is None:
            gpu[label] = value
        else:
            gpu.setdefault("unavailable", {})[label] = error
    cores = []
    missing_cores = []
    for cpu in range(CPU_LIMIT):
        path = sysfs / "devices/system/cpu" / f"cpu{cpu}" / "cpufreq"
        row: dict[str, Any] = {"cpu": cpu}
        for label, suffix in (("scalingCurFreqKHz", "scaling_cur_freq"),
                              ("scalingMaxFreqKHz", "scaling_max_freq")):
            value, error = _sysfs_number(path / suffix, 0, 100_000_000)
            if error is None:
                row[label] = value
            else:
                row.setdefault("unavailable", {})[label] = error
        # Compact entirely absent devices; partial and denied reads stay explicit.
        if row.get("unavailable") == {"scalingCurFreqKHz": "missing", "scalingMaxFreqKHz": "missing"}:
            missing_cores.append(cpu)
        else:
            cores.append(row)
    zones = []
    missing_zones = []
    for zone in range(THERMAL_ZONE_LIMIT):
        path = sysfs / "class/thermal" / f"thermal_zone{zone}"
        row = {"zone": zone}
        label, error = _sysfs_text(path / "type", 64)
        if error is None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", label or ""):
            error = "malformed"
        if error is None:
            row["type"] = label
        else:
            row.setdefault("unavailable", {})["type"] = error
        value, error = _sysfs_number(path / "temp", -273_150, 1_000_000)
        if error is None:
            row["tempMilliC"] = value
        else:
            row.setdefault("unavailable", {})["tempMilliC"] = error
        if row.get("unavailable") == {"type": "missing", "tempMilliC": "missing"}:
            missing_zones.append(zone)
        else:
            zones.append(row)
    return {"gpu": gpu, "cpu": {"cores": cores, "missingCores": missing_cores},
            "thermal": {"zones": zones, "missingZones": missing_zones}}


def _stat(path: Path) -> tuple[str, dict[str, Any]]:
    raw = _bounded_text(path / "stat", STAT_LIMIT)
    first, last = raw.index("("), raw.rindex(")")
    fields = raw[last + 2:].split()
    record = {"pid": int(raw[:first].strip()), "startTicks": fields[19], "state": fields[0],
              "cpuTicks": int(fields[11]) + int(fields[12])}
    if record["state"] not in "RSDZTWtXxKPI" or len(record["state"]) != 1 or record["cpuTicks"] < 0:
        raise ValueError("Invalid proc counters")
    if int(record["startTicks"]) < 0:
        raise ValueError("Invalid proc identity")
    return raw[first + 1:last], record


def _wait_channel(path: Path) -> str:
    try:
        value = _bounded_text(path / "wchan", 64).strip()
    except (OSError, ValueError):
        return "unavailable"
    # Kernel identifiers only. Never retain arbitrary text if a proc mount or
    # fixture supplies unexpected data; zero does not prove that a task is idle.
    return value if value != "0" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value) else "unavailable"


def _open_directory(path: Path) -> int:
    """Reject symlinks in every component, including replaced cache parents."""
    path = path.absolute()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def cache_metadata(path: Path) -> dict[str, Any]:
    """Count bounded metadata only, without following links or reading files."""
    result: dict[str, Any] = {"present": False, "files": 0, "directories": 0,
                              "bytes": 0, "newestMtime": None, "entries": 0,
                              "truncated": False, "unavailable": False}
    try:
        root = _open_directory(path)
    except FileNotFoundError:
        return result
    except OSError:
        result["unavailable"] = True
        return result
    result["present"] = True
    deadline = time.monotonic() + .1
    def walk(descriptor: int, depth: int) -> None:
        try:
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    if result["entries"] >= CACHE_ENTRY_LIMIT or time.monotonic() >= deadline:
                        result["truncated"] = True
                        break
                    result["entries"] += 1
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(metadata.st_mode):
                            result["files"] += 1
                            result["bytes"] += metadata.st_size
                            result["newestMtime"] = max(result["newestMtime"] or 0, metadata.st_mtime)
                        elif stat.S_ISDIR(metadata.st_mode):
                            result["directories"] += 1
                            if depth >= 4:
                                result["truncated"] = True
                            else:
                                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                                dir_fd=descriptor)
                                walk(child, depth + 1)
                    except OSError:
                        result["unavailable"] = True
        except OSError:
            result["unavailable"] = True
        finally:
            os.close(descriptor)
    walk(root, 0)
    return result


class PerformanceHistory:
    def __init__(self, state: Path, caches: tuple[Path, ...], *, proc: Path = Path("/proc"),
                 sysfs: Path = Path("/sys"), file_limit: int = FILE_LIMIT):
        self.path = state / "client-performance.json"
        self.caches = caches
        self.proc = proc
        self.sysfs = sysfs
        self.file_limit = file_limit
        self.active = False
        self.wrapper_pid: int | None = None
        self.previous_snapshot = None
        self.previous_threads: dict[tuple[int, str, int, str], int] = {}
        self.previous_thread_time: float | None = None
        self.cache_time: float | None = None
        self.cache_report: dict[str, Any] = {}
        self.hardware_time: float | None = None
        self.hardware_report: dict[str, Any] = {}
        self.samples: deque[dict[str, Any]] = deque(maxlen=SAMPLE_LIMIT)
        self.report: dict[str, Any] = {}

    def begin(self) -> None:
        """Rotate only when a new EVE process has successfully been spawned."""
        self.active = True
        self.wrapper_pid = None
        self.samples.clear()
        self.previous_snapshot = None
        self.previous_threads.clear()
        self.previous_thread_time = None
        self.cache_time = None
        self.cache_report = {}
        self.hardware_time = None
        self.hardware_report = {}
        self.report = {"format": 1, "startedAt": time.time(), "sampleIntervalSeconds": SAMPLE_SECONDS,
                       "sampleLimit": SAMPLE_LIMIT, "taskLimit": TASK_LIMIT,
                       "threadRowLimit": THREAD_ROWS, "cacheIntervalSeconds": CACHE_SECONDS,
                       "mainThreadRowLimit": MAIN_ROWS,
                       "hardwareIntervalSeconds": HARDWARE_SECONDS,
                       "hardwareCpuLimit": CPU_LIMIT, "hardwareThermalZoneLimit": THERMAL_ZONE_LIMIT,
                       "fileLimitBytes": self.file_limit,
                       "cpuPercentMeaning": "100 percent is one logical CPU", "phase": "starting"}
        try:
            if self.path.is_symlink():
                self.active = False
                return
            if self.path.is_file():
                previous = self.path.with_name(self.path.name + ".1")
                previous.unlink(missing_ok=True)
                if self.path.stat().st_size <= self.file_limit:
                    self.path.replace(previous)
                else:
                    self.path.unlink()
        except OSError:
            self.active = False

    def _threads(self, members: list[dict[str, Any]], captured_at: float) -> dict[str, Any]:
        rows = []
        states: Counter[str] = Counter()
        classes: dict[str, dict[str, Any]] = {}
        counters = {}
        observed = 0
        unavailable = 0
        identity_changes = 0
        truncated = False
        elapsed = captured_at - self.previous_thread_time if self.previous_thread_time is not None else None
        deadline = time.monotonic() + .1
        for member in members:
            if observed >= TASK_LIMIT or time.monotonic() >= deadline:
                truncated = True
                break
            pid = member["pid"]
            proc_pid = server_runtime.PROC_PID_CACHE.get(pid, pid) if server_runtime.NAMESPACE_MAPPING else pid
            path = self.proc / str(proc_pid)
            try:
                _, leader = _stat(path)
                if leader["pid"] != proc_pid or leader["startTicks"] != member["startTicks"] or leader["state"] == "Z":
                    unavailable += 1
                    continue
                member_rows = []
                member_counters = {}
                with os.scandir(path / "task") as entries:
                    for entry in entries:
                        if not entry.name.isdigit():
                            continue
                        if observed >= TASK_LIMIT or time.monotonic() >= deadline:
                            truncated = True
                            break
                        observed += 1
                        try:
                            task_path = Path(entry.path)
                            name, task = _stat(task_path)
                            if task["pid"] != int(entry.name):
                                raise ValueError("Invalid task identity")
                            key = (pid, member["startTicks"], int(entry.name), task["startTicks"])
                            before = self.previous_threads.get(key)
                            after = task["cpuTicks"]
                            percent = None
                            if before is not None and after >= before and elapsed is not None and elapsed > 0:
                                percent = 100 * (after - before) / elapsed / server_runtime.CLOCK_TICKS
                            member_counters[key] = after
                            label = THREAD_CLASSES.get(name, "other")
                            state = task["state"]
                            wait = _wait_channel(task_path)
                            member_rows.append({"pid": pid, "tid": int(entry.name), "class": label, "state": state,
                                         "main": task["pid"] == proc_pid,
                                         "processClass": ("wrapper" if pid == self.wrapper_pid else "child")
                                                         if self.wrapper_pid is not None else "client",
                                         "wchan": wait, "cpuTicks": after, "cpuCorePercent": percent})
                        except (OSError, ValueError, IndexError):
                            unavailable += 1
                _, current = _stat(path)
                if current["pid"] != proc_pid or current["startTicks"] != leader["startTicks"] or current["state"] == "Z":
                    identity_changes += 1
                    unavailable += 1
                    continue
                rows.extend(member_rows)
                counters.update(member_counters)
            except (OSError, ValueError, IndexError):
                unavailable += 1
        self.previous_threads = counters
        self.previous_thread_time = captured_at
        for row in rows:
            label, state, wait, percent = row["class"], row["state"], row["wchan"], row["cpuCorePercent"]
            states[state] += 1
            aggregate = classes.setdefault(label, {"threads": 0, "states": Counter(), "waits": Counter(),
                                                  "cpuCorePercent": None, "cpuSampledThreads": 0})
            aggregate["threads"] += 1
            aggregate["states"][state] += 1
            aggregate["waits"][wait] += 1
            if percent is not None:
                aggregate["cpuSampledThreads"] += 1
                aggregate["cpuCorePercent"] = (aggregate["cpuCorePercent"] or 0) + percent
        # Reserve a row for every recognized class, including blocked GPU
        # completion; fill the remaining rows with the highest measured CPU.
        rows.sort(key=lambda row: row["cpuCorePercent"] or 0, reverse=True)
        main_rows = [row for row in rows if row["main"]]
        main_rows.sort(key=lambda row: row["processClass"] != "wrapper")
        selected = main_rows[:MAIN_ROWS]
        for label in THREAD_CLASSES.values():
            candidate = next((row for row in rows if row["class"] == label), None)
            if candidate is not None and candidate not in selected:
                selected.append(candidate)
        selected.extend(row for row in rows if row not in selected and not row["main"])
        return {"processes": len(members), "tasksObserved": observed, "tasksRead": len(rows),
                "unavailable": unavailable, "identityChanges": identity_changes,
                "truncated": truncated, "states": dict(states),
                "classes": classes, "sampleSeconds": elapsed if elapsed is not None and elapsed > 0 else None,
                "rows": selected[:THREAD_ROWS]}

    def sample(self, snapshot: server_runtime.ProcessSnapshot, groups: dict[str, int], phase: str,
               *, force: bool = False) -> None:
        if not self.active or phase not in PHASES:
            return
        elapsed = snapshot.captured_at - self.previous_snapshot.captured_at if self.previous_snapshot else None
        if not force and elapsed is not None and elapsed < SAMPLE_SECONDS:
            return
        try:
            cpu = snapshot.cpu_usage(self.previous_snapshot)
            roles = {}
            for role in ROLES:
                if role in groups:
                    members = snapshot.members(groups[role])
                    roles[role] = {**cpu.get(groups[role], {}), "processes": len(members),
                                   "rssKiB": sum(item.get("rssKiB", 0) for item in members)}
            client = snapshot.members(groups["client"]) if "client" in groups else []
            threads = self._threads(client, snapshot.captured_at)
            if self.cache_time is None or snapshot.captured_at - self.cache_time >= CACHE_SECONDS:
                self.cache_report = {label: cache_metadata(path) for label, path in zip(("dxvk", "mesa"), self.caches)}
                self.cache_time = snapshot.captured_at
            hardware_sample = None
            if self.hardware_time is None or snapshot.captured_at - self.hardware_time >= HARDWARE_SECONDS:
                self.hardware_report = {"at": time.time(), **hardware_metrics(self.sysfs)}
                self.hardware_time = snapshot.captured_at
                self.report["latestHardware"] = self.hardware_report
                hardware_sample = self.hardware_report
            sample = {"at": time.time(), "phase": phase, "roles": roles, "clientThreads": threads,
                      "cache": self.cache_report, "cacheSampleAgeSeconds": snapshot.captured_at - self.cache_time,
                      "hardwareSampleAt": self.hardware_report["at"],
                      "hardwareSampleAgeSeconds": snapshot.captured_at - self.hardware_time}
            # Retain each hardware reading once, rather than duplicate it in
            # intervening 5-second process samples. Latest remains readable even
            # when the byte budget has evicted the sample containing that read.
            if hardware_sample is not None:
                sample["hardware"] = hardware_sample
            self.samples.append(sample)
            self.previous_snapshot = snapshot
            self.report["phase"] = phase
            self._write()
        except (OSError, ValueError, IndexError, KeyError, TypeError):
            # A partial or inaccessible proc observation must not change gameplay.
            self.report["observationFailures"] = self.report.get("observationFailures", 0) + 1

    def finish(self, phase: str) -> None:
        if self.active and phase in ("stopped", "failed"):
            self.report.update(phase=phase, endedAt=time.time())
            self._write()
            self.active = False

    def _write(self) -> None:
        temporary = self.path.with_name("." + self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            if self.path.is_symlink():
                return
            while True:
                payload = json.dumps({**self.report, "samples": list(self.samples)}, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8") + b"\n"
                if len(payload) <= self.file_limit:
                    break
                if not self.samples:
                    if "latestHardware" in self.report:
                        # Keep terminal markers writable even under a smaller
                        # injected budget that cannot fit one hardware read.
                        self.report.pop("latestHardware")
                        self.report["latestHardwareDroppedForBytes"] = True
                        continue
                    return
                self.samples.popleft()
                self.report["samplesDroppedForBytes"] = self.report.get("samplesDroppedForBytes", 0) + 1
            with temporary.open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, TypeError):
            self.report["writeFailures"] = self.report.get("writeFailures", 0) + 1
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
