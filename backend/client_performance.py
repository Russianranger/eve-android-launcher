#!/usr/bin/env python3
"""Bounded device A/B settings; never accept arbitrary executable/environment text."""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import stat
import sys
from typing import Any

LIMIT = 16 * 1024
# FEX-2510 / pinned 320c5f1: ARM64EC ProcessInit consumes _environ via
# LoadConfig's EnvLoader. No arbitrary passthrough and no default TSO override.
FEX_ENV = {"multiblock": "FEX_MULTIBLOCK", "x87ReducedPrecision": "FEX_X87REDUCEDPRECISION",
           "tsoEnabled": "FEX_TSOENABLED", "vectorTsoEnabled": "FEX_VECTORTSOENABLED",
           "memcpySetTsoEnabled": "FEX_MEMCPYSETTSOENABLED", "halfBarrierTsoEnabled": "FEX_HALFBARRIERTSOENABLED"}


def topology(sysfs: Path = Path("/sys/devices/system/cpu"), allowed: set[int] | None = None) -> dict[str, Any]:
    if allowed is None:
        try:
            allowed = set(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            allowed = set(range(os.cpu_count() or 1))
    # Do not pin to offline/disallowed CPUs. Capacity is preferable to transient
    # scaling frequency; cpuinfo_max_freq is only the fallback on vendor kernels.
    allowed = {cpu for cpu in allowed if 0 <= cpu <= 1023} or {0}
    for field in ("cpu_capacity", "cpufreq/cpuinfo_max_freq"):
        values = {}
        for cpu in sorted(allowed):
            try:
                value = int((sysfs / ("cpu" + str(cpu)) / field).read_text().strip())
                if value > 0:
                    values[cpu] = value
            except (OSError, ValueError):
                pass
        if len(values) == len(allowed) and len(set(values.values())) > 1:
            small = min(values.values())
            return {"allowed": sorted(allowed), "performance": [cpu for cpu, value in values.items() if value > small],
                    "source": field}
    return {"allowed": sorted(allowed), "performance": sorted(allowed), "source": "available-cpus"}


def defaults() -> dict[str, Any]:
    # Preserve the accepted 0.1.22 environment. Each additional trial is opt-in;
    # graphics profiles and existing experiment preferences remain authoritative.
    return {"schemaVersion": 1, "wineEsync": False, "wineDebug": "-all,err+all",
            "lpNumThreads": 4, "wineServerNice": 0, "serverNice": 0, "cpuAffinity": [],
            "fex": {}, "displayPixels": "legacy", "networkFastConnectedSends": False,
            "networkTrapStatistics": False, "resolution": "1280x720", "xvncFrameRate": None}


def load(path: Path) -> dict[str, Any]:
    """Return validated settings and warnings; invalid fields use safe defaults."""
    profile = defaults()
    warnings = []
    try:
        # O_NONBLOCK prevents a replaced FIFO from hanging startup; NOFOLLOW
        # rejects symlinks and fstat verifies the opened descriptor itself.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("must be a regular file")
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("exceeds 16 KiB")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("must be an object")
    except FileNotFoundError:
        value = {}
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        value = {}
        warnings.append("performance.json ignored: " + str(error)[:160])
    rules = {
        "schemaVersion": lambda x: type(x) is int and x == 1,
        "wineEsync": lambda x: type(x) is bool,
        "wineDebug": lambda x: x in ("-all", "-all,err+all") if isinstance(x, str) else False,
        "lpNumThreads": lambda x: (type(x) is int and 1 <= x <= 16) or x == "auto",
        "wineServerNice": lambda x: type(x) is int and 0 <= x <= 19,
        "serverNice": lambda x: type(x) is int and 0 <= x <= 19,
        "cpuAffinity": lambda x: isinstance(x, list) and len(x) <= 64 and all(type(cpu) is int and 0 <= cpu <= 1023 for cpu in x),
        "fex": lambda x: isinstance(x, dict) and all(key in FEX_ENV and type(item) is bool for key, item in x.items()),
        "displayPixels": lambda x: x in ("legacy", "direct") if isinstance(x, str) else False,
        "networkFastConnectedSends": lambda x: type(x) is bool,
        "networkTrapStatistics": lambda x: type(x) is bool,
        "resolution": lambda x: x in ("1280x720", "960x540") if isinstance(x, str) else False,
        "xvncFrameRate": lambda x: type(x) is int and 1 <= x <= 120,
    }
    if "schemaVersion" in value and not rules["schemaVersion"](value["schemaVersion"]):
        warnings.append("Unsupported performance schema; all settings use defaults")
        value = {}
    for key, item in value.items():
        if key not in rules:
            warnings.append("Unknown performance setting ignored: " + str(key)[:80])
        elif rules[key](item):
            profile[key] = sorted(set(item)) if key == "cpuAffinity" else item
        else:
            warnings.append("Invalid performance setting uses default: " + key)
    profile["warnings"] = warnings[:32]
    return profile


def resolve(profile: dict[str, Any], *, graphics_mode: str, display_rate: int,
            performance_cores: bool = False) -> dict[str, Any]:
    """Resolve conditional knobs without changing graphics or memory policy."""
    result = {**profile, "warnings": list(profile.get("warnings", []))}
    result["xvncFrameRate"] = profile["xvncFrameRate"] or display_rate
    if graphics_mode == "software":
        if profile["lpNumThreads"] == "auto":
            cpus = topology()
            result["lpNumThreads"] = max(1, min(16, len(cpus["performance"])))
            result["workerCpuTopology"] = cpus
    else:
        result["lpNumThreads"] = None  # llvmpipe is inactive in the accepted GPU path.
    if result["cpuAffinity"]:
        if performance_cores:
            result["cpuAffinity"] = []
            result["warnings"].append("JSON cpuAffinity ignored: the existing performance-core experiment owns the client mask")
        else:
            try:
                allowed = os.sched_getaffinity(0)
                if not set(result["cpuAffinity"]).issubset(allowed):
                    raise ValueError("requested CPUs are outside the current Android cpuset")
            except (AttributeError, OSError, ValueError) as error:
                result["cpuAffinity"] = []
                result["warnings"].append("JSON cpuAffinity disabled: " + str(error)[:160])
    result["warnings"] = result["warnings"][:32]
    return result


def prepare(profile: dict[str, Any]) -> dict[str, Any]:
    """Resolve esync before wineserver starts. The memory reserve is untouched."""
    profile = {**profile, "warnings": list(profile.get("warnings", []))}
    if profile["wineEsync"]:
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            target = 65536 if hard == resource.RLIM_INFINITY else min(65536, hard)
            if soft != resource.RLIM_INFINITY and soft < target:
                resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            actual = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            profile["fdSoftLimit"] = actual
            if actual != resource.RLIM_INFINITY and actual < 4096:
                raise OSError("fd soft limit below 4096")
            descriptor = os.eventfd(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
            os.close(descriptor)
        except (OSError, AttributeError, ValueError) as error:
            profile["wineEsync"] = False
            profile["warnings"].append("Esync disabled before Wine startup: " + str(error)[:160])
    profile["warnings"] = profile["warnings"][:32]
    return profile


def fex_environment(profile: dict[str, Any]) -> dict[str, str]:
    return {FEX_ENV[key]: "1" if value else "0" for key, value in profile["fex"].items()}


def command(role: str, arguments: tuple[str, ...], profile: dict[str, Any]) -> tuple[str, ...]:
    """Exec wrapper avoids preexec_fn in the threaded supervisor and shell text."""
    nice = profile["wineServerNice"] if role == "wineServer" else profile["serverNice"] if role in ("server", "market") else 0
    affinity = profile["cpuAffinity"] if role == "client" else []
    if not nice and not affinity:
        return arguments
    return (sys.executable, str(Path(__file__).resolve()), "exec", str(nice),
            ",".join(map(str, affinity)), *arguments)


def main(argv: list[str]) -> int:
    if len(argv) < 5 or argv[1] != "exec":
        raise ValueError("Expected scheduling exec wrapper")
    nice = int(argv[2])
    cpus = {int(cpu) for cpu in argv[3].split(",") if cpu}
    if not 0 <= nice <= 19 or len(cpus) > 64 or any(not 0 <= cpu <= 1023 for cpu in cpus):
        raise ValueError("Invalid scheduling settings")
    if nice:
        try:
            os.nice(nice)
        except OSError as error:
            print("Performance priority unavailable; retaining current priority: " + str(error), flush=True)
    if cpus:
        try:
            os.sched_setaffinity(0, cpus)
        except (AttributeError, OSError) as error:
            print("Performance CPU affinity unavailable; retaining available CPUs: " + str(error), flush=True)
    # Diagnostics must not turn an unavailable optional scheduler operation
    # into a startup failure on vendor kernels or under PRoot.
    actual: dict[str, Any] = {"nice": "unavailable", "cpuAffinity": "unavailable"}
    try:
        actual["nice"] = os.getpriority(os.PRIO_PROCESS, 0)
    except (AttributeError, OSError):
        pass
    try:
        actual["cpuAffinity"] = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    print("Performance scheduling: " + json.dumps(actual), flush=True)
    os.execvpe(argv[4], argv[4:], os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
