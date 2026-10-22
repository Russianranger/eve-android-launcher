"""Optional guest knobs preserve accepted graphics defaults and process ownership."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
import client_performance as MODULE


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="eve-performance-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "performance.json"

    def test_missing_profile_preserves_accepted_guest_defaults(self):
        profile = MODULE.load(self.path)
        self.assertFalse(profile["wineEsync"])
        self.assertEqual(profile["wineDebug"], "-all,err+all")
        self.assertEqual(profile["lpNumThreads"], 4)
        self.assertEqual(profile["wineServerNice"], 0)
        self.assertEqual(profile["serverNice"], 0)
        self.assertEqual(profile["cpuAffinity"], [])
        self.assertEqual(profile["fex"], {})
        self.assertEqual(profile["displayPixels"], "legacy")
        self.assertFalse(profile["networkFastConnectedSends"])
        self.assertFalse(profile["networkTrapStatistics"])
        self.assertIsNone(profile["xvncFrameRate"])
        self.assertEqual(profile["resolution"], "1280x720")
        self.assertEqual(profile["warnings"], [])

    def test_valid_knobs_and_fex_allowlist(self):
        self.path.write_text(json.dumps({"wineEsync": True, "wineDebug": "-all", "lpNumThreads": "auto",
            "wineServerNice": 3, "serverNice": 5, "cpuAffinity": [3, 3, 5], "xvncFrameRate": 60,
            "resolution": "960x540", "displayPixels": "direct", "networkFastConnectedSends": True,
            "networkTrapStatistics": True, "fex": {"multiblock": True, "x87ReducedPrecision": True,
                                                    "tsoEnabled": False}}))
        profile = MODULE.load(self.path)
        self.assertEqual(profile["warnings"], [])
        self.assertEqual(profile["cpuAffinity"], [3, 5])
        self.assertEqual(profile["lpNumThreads"], "auto")
        self.assertEqual(MODULE.fex_environment(profile), {"FEX_MULTIBLOCK": "1", "FEX_X87REDUCEDPRECISION": "1",
                                                         "FEX_TSOENABLED": "0"})

    def test_bad_types_ranges_unknown_names_and_schema_default_safely(self):
        cases = ({"wineEsync": "1", "wineDebug": "+all;unsafe", "lpNumThreads": True,
                  "wineServerNice": -1, "serverNice": 20, "cpuAffinity": [-1], "resolution": "4096x4096",
                  "xvncFrameRate": True, "networkFastConnectedSends": "true", "FEX_DANGEROUS": True},
                 {"fex": {"multiblock": "1"}}, {"fex": {"FEX_UNKNOWN": True}},
                 {"schemaVersion": 2, "wineEsync": True}, {"schemaVersion": 1.0, "wineEsync": True})
        for value in cases:
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value))
                profile = MODULE.load(self.path)
                self.assertFalse(profile["wineEsync"])
                self.assertEqual(profile["wineDebug"], "-all,err+all")
                self.assertEqual(profile["lpNumThreads"], 4)
                self.assertEqual(profile["resolution"], "1280x720")
                self.assertEqual(profile["fex"], {})
                self.assertTrue(profile["warnings"])

    def test_malformed_oversized_recursive_and_nonregular_config_never_blocks(self):
        for raw in (b"[]", b"{broken", b" " * (MODULE.LIMIT + 1), b"\xff", b"[" * 1200 + b"]" * 1200):
            with self.subTest(raw=raw[:16]):
                self.path.write_bytes(raw)
                self.assertTrue(MODULE.load(self.path)["warnings"])
        self.path.unlink()
        target = self.root / "target.json"
        target.write_text('{"wineEsync":true}')
        self.path.symlink_to(target)
        self.assertFalse(MODULE.load(self.path)["wineEsync"])
        self.path.unlink()
        os.mkfifo(self.path)
        self.assertIn("regular file", " ".join(MODULE.load(self.path)["warnings"]))

    def test_resolution_does_not_override_existing_display_profile_unless_requested(self):
        requested = MODULE.load(self.path)
        for rate in (15, 30, 60):
            effective = MODULE.resolve(requested, graphics_mode="turnip-dxvk", display_rate=rate)
            self.assertEqual(effective["xvncFrameRate"], rate)
            self.assertIsNone(effective["lpNumThreads"])
        requested["xvncFrameRate"] = 45
        self.assertEqual(MODULE.resolve(requested, graphics_mode="turnip-dxvk", display_rate=30)["xvncFrameRate"], 45)

    def test_auto_workers_and_existing_performance_core_experiment_remain_separate(self):
        requested = MODULE.load(self.path)
        requested.update(lpNumThreads="auto", cpuAffinity=[3, 4])
        with mock.patch.object(MODULE, "topology", return_value={"performance": [3, 4, 5, 6, 7], "source": "fixture"}), \
             mock.patch.object(MODULE.os, "sched_getaffinity", return_value={3, 4, 5, 6, 7}):
            software = MODULE.resolve(requested, graphics_mode="software", display_rate=15)
            dedicated = MODULE.resolve(requested, graphics_mode="turnip-dxvk", display_rate=30, performance_cores=True)
        self.assertEqual(software["lpNumThreads"], 5)
        self.assertEqual(software["cpuAffinity"], [3, 4])
        self.assertEqual(dedicated["cpuAffinity"], [])
        self.assertIn("experiment owns", " ".join(dedicated["warnings"]))
        with mock.patch.object(MODULE.os, "sched_getaffinity", return_value={0, 1}):
            unavailable = MODULE.resolve(requested, graphics_mode="turnip-dxvk", display_rate=30)
        self.assertEqual(unavailable["cpuAffinity"], [])
        self.assertIn("cpuset", " ".join(unavailable["warnings"]))

    def test_topology_detects_performance_capacity_then_maximum_frequency(self):
        for cpu, capacity in ((0, 300), (1, 700), (2, 1000)):
            folder = self.root / ("cpu" + str(cpu))
            folder.mkdir()
            (folder / "cpu_capacity").write_text(str(capacity))
        self.assertEqual(MODULE.topology(self.root, {0, 1, 2})["performance"], [1, 2])
        for cpu, frequency in ((0, 1800000), (1, 2800000), (2, 3200000)):
            folder = self.root / ("cpu" + str(cpu))
            (folder / "cpu_capacity").unlink()
            (folder / "cpufreq").mkdir()
            (folder / "cpufreq/cpuinfo_max_freq").write_text(str(frequency))
        self.assertEqual(MODULE.topology(self.root, {0, 1, 2})["source"], "cpufreq/cpuinfo_max_freq")

    def test_esync_raises_fd_limit_and_falls_back_before_wine_on_failure(self):
        profile = MODULE.load(self.path)
        profile["wineEsync"] = True
        with mock.patch.object(MODULE.resource, "getrlimit", side_effect=[(1024, 1048576), (65536, 1048576)]), \
             mock.patch.object(MODULE.resource, "setrlimit") as setlimit, \
             mock.patch.object(MODULE.os, "eventfd", return_value=123) as eventfd, \
             mock.patch.object(MODULE.os, "close") as close:
            effective = MODULE.prepare(profile)
        setlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (65536, 1048576))
        eventfd.assert_called_once_with(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
        close.assert_called_once_with(123)
        self.assertTrue(effective["wineEsync"])
        self.assertEqual(effective["fdSoftLimit"], 65536)
        for failure in (PermissionError(errno.EPERM, "eventfd blocked"), OSError(errno.EMFILE, "fd exhausted")):
            with mock.patch.object(MODULE.resource, "getrlimit", return_value=(65536, 1048576)), \
                 mock.patch.object(MODULE.os, "eventfd", side_effect=failure):
                effective = MODULE.prepare(profile)
            self.assertFalse(effective["wineEsync"])
            self.assertIn("Esync disabled", " ".join(effective["warnings"]))
        with mock.patch.object(MODULE.resource, "getrlimit", return_value=(1024, 1024)), \
             mock.patch.object(MODULE.os, "eventfd") as eventfd:
            self.assertFalse(MODULE.prepare(profile)["wineEsync"])
            eventfd.assert_not_called()
        with mock.patch.object(MODULE.os, "eventfd") as eventfd:
            MODULE.prepare(MODULE.load(self.path))
            eventfd.assert_not_called()

    def test_scheduling_exec_preserves_journal_pid_and_real_priority_affinity(self):
        profile = MODULE.load(self.path)
        profile.update(wineServerNice=3, serverNice=5, cpuAffinity=[min(os.sched_getaffinity(0))])
        payload = 'import json,os; print(json.dumps({"pid":os.getpid(),"nice":os.getpriority(os.PRIO_PROCESS,0),"cpus":sorted(os.sched_getaffinity(0))}))'
        for role in ("wineServer", "server", "market", "client"):
            process = subprocess.Popen(MODULE.command(role, (sys.executable, "-c", payload), profile),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, error)
            result = json.loads(output.splitlines()[-1])
            self.assertEqual(result["pid"], process.pid)
            if role == "client":
                self.assertEqual(result["cpus"], profile["cpuAffinity"])
            else:
                delta = profile["wineServerNice" if role == "wineServer" else "serverNice"]
                self.assertEqual(result["nice"], os.getpriority(os.PRIO_PROCESS, 0) + delta)
        self.assertEqual(MODULE.command("client", ("unchanged",), MODULE.load(self.path)), ("unchanged",))

    def test_optional_scheduler_denials_do_not_prevent_exec(self):
        denied = PermissionError(errno.EPERM, "scheduler unavailable")
        with mock.patch.object(MODULE.os, "nice", side_effect=denied), \
             mock.patch.object(MODULE.os, "sched_setaffinity", side_effect=denied), \
             mock.patch.object(MODULE.os, "getpriority", side_effect=denied), \
             mock.patch.object(MODULE.os, "sched_getaffinity", side_effect=denied), \
             mock.patch.object(MODULE.os, "execvpe") as execute, mock.patch("builtins.print"):
            MODULE.main(["client_performance.py", "exec", "3", "0", sys.executable, "-c", "pass"])
        execute.assert_called_once_with(sys.executable, [sys.executable, "-c", "pass"], os.environ)


if __name__ == "__main__":
    unittest.main()
