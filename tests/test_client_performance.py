"""Validated device-only A/B knobs without any game files or Android device."""

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

    def test_topology_uses_capacity_then_max_frequency_and_excludes_disallowed_cpus(self):
        for cpu, capacity in ((0, 300), (1, 700), (2, 1000), (3, 3000)):
            folder = self.root / ("cpu" + str(cpu))
            folder.mkdir()
            (folder / "cpu_capacity").write_text(str(capacity))
        result = MODULE.topology(self.root, {0, 1, 2})
        self.assertEqual(result, {"allowed": [0, 1, 2], "performance": [1, 2], "source": "cpu_capacity"})
        for cpu, frequency in ((0, 1800000), (1, 2800000), (2, 3200000)):
            folder = self.root / ("cpu" + str(cpu))
            (folder / "cpu_capacity").unlink()
            (folder / "cpufreq").mkdir()
            (folder / "cpufreq/cpuinfo_max_freq").write_text(str(frequency))
        result = MODULE.topology(self.root, {0, 1, 2})
        self.assertEqual(result["performance"], [1, 2])
        self.assertEqual(result["source"], "cpufreq/cpuinfo_max_freq")
        (self.root / "cpu1/cpufreq/cpuinfo_max_freq").unlink()
        self.assertEqual(MODULE.topology(self.root, {0, 1, 2})["source"], "available-cpus")

    def test_missing_profile_has_safe_defaults(self):
        with mock.patch.object(MODULE, "topology", return_value={"allowed": list(range(8)), "performance": [3, 4, 5, 6, 7], "source": "cpu_capacity"}):
            value = MODULE.load(self.path)
        self.assertEqual(value["frameRate"], 60)
        self.assertEqual(value["resolution"], "1280x720")
        self.assertEqual(value["lpNumThreads"], 5)
        self.assertTrue(value["wineEsync"])
        self.assertEqual(value["wineDebug"], "-all")
        self.assertEqual(value["displayPixels"], "direct")
        self.assertEqual(value["displayPresentation"], "surface")
        self.assertTrue(value["pipelineRequests"])
        self.assertTrue(value["networkFastSendto"])
        self.assertFalse(value["networkTraceStats"])
        self.assertEqual(value["fex"], {})
        self.assertEqual(value["cpuAffinity"], [])
        self.assertGreater(value["wineServerNice"], 0)
        self.assertGreater(value["serverNice"], 0)

    def test_valid_knobs_are_accepted_without_arbitrary_environment_passthrough(self):
        cpu = min(os.sched_getaffinity(0))
        self.path.write_text(json.dumps({"frameRate": 30, "resolution": "960x540", "wineEsync": False,
            "wineDebug": "-all,err+all", "lpNumThreads": 2, "wineServerNice": 0, "serverNice": 0,
            "cpuAffinity": [cpu, cpu], "networkFastSendto": True, "networkTraceStats": True, "fex": {"multiblock": True, "x87ReducedPrecision": True,
                                                "tsoEnabled": False, "vectorTsoEnabled": False}}))
        value = MODULE.load(self.path)
        self.assertEqual(value["warnings"], [])
        self.assertEqual(value["cpuAffinity"], [cpu])
        self.assertEqual(value["resolution"], "960x540")
        self.assertFalse(value["wineEsync"])
        self.assertTrue(value["networkFastSendto"])
        self.assertTrue(value["networkTraceStats"])
        self.assertEqual(MODULE.fex_environment(value), {"FEX_MULTIBLOCK": "1", "FEX_X87REDUCEDPRECISION": "1",
                                                       "FEX_TSOENABLED": "0", "FEX_VECTORTSOENABLED": "0"})

    def test_bad_types_ranges_unknown_environment_and_schema_use_defaults(self):
        cases = ({"frameRate": True, "lpNumThreads": 0, "resolution": "4096x4096", "wineEsync": "1",
                  "wineDebug": "+all;unsafe", "serverNice": -1, "cpuAffinity": [-1], "FEX_DISABLETELEMETRY": "0"},
                 {"fex": {"multiblock": "1"}}, {"fex": {"FEX_DANGEROUS": True}},
                 {"schemaVersion": 2, "frameRate": 1})
        for value in cases:
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value))
                profile = MODULE.load(self.path)
                self.assertEqual(profile["frameRate"], 60)
                self.assertEqual(profile["resolution"], "1280x720")
                self.assertEqual(profile["fex"], {})
                self.assertTrue(profile["warnings"])

    def test_malformed_or_oversized_profile_uses_defaults(self):
        for raw in ("[]", "false", "{broken", " " * (MODULE.LIMIT + 1), "\udcff"):
            with self.subTest(raw=raw[:20]):
                self.path.write_bytes(raw.encode("utf-8", errors="surrogateescape"))
                profile = MODULE.load(self.path)
                self.assertEqual(profile["frameRate"], 60)
                self.assertTrue(profile["warnings"])

    def test_symlink_and_fifo_profiles_are_rejected_without_blocking(self):
        target = self.root / "target.json"
        target.write_text('{"frameRate":1}')
        self.path.symlink_to(target)
        profile = MODULE.load(self.path)
        self.assertEqual(profile["frameRate"], 60)
        self.assertTrue(profile["warnings"])
        self.path.unlink()
        os.mkfifo(self.path)
        profile = MODULE.load(self.path)
        self.assertEqual(profile["frameRate"], 60)
        self.assertIn("regular file", " ".join(profile["warnings"]))

    def test_esync_raises_fd_limit_and_checks_eventfd_before_wine(self):
        limits = [(1024, 1048576), (65536, 1048576)]
        profile = MODULE.defaults()
        with mock.patch.object(MODULE.resource, "getrlimit", side_effect=limits), \
             mock.patch.object(MODULE.resource, "setrlimit") as setlimit, \
             mock.patch.object(MODULE.os, "eventfd", return_value=123) as eventfd, \
             mock.patch.object(MODULE.os, "close") as close:
            effective = MODULE.prepare(profile)
        setlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (65536, 1048576))
        eventfd.assert_called_once_with(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
        close.assert_called_once_with(123)
        self.assertTrue(effective["wineEsync"])
        self.assertEqual(effective["fdSoftLimit"], 65536)

    def test_esync_eventfd_or_fd_limit_failure_cleanly_disables_it(self):
        for failure in (PermissionError(errno.EPERM, "eventfd blocked"), OSError(errno.EMFILE, "fd exhausted")):
            with self.subTest(failure=failure):
                with mock.patch.object(MODULE.resource, "getrlimit", return_value=(65536, 1048576)), \
                     mock.patch.object(MODULE.os, "eventfd", side_effect=failure):
                    profile = MODULE.prepare(MODULE.defaults())
                self.assertFalse(profile["wineEsync"])
                self.assertIn("Esync disabled", profile["warnings"][-1])
        with mock.patch.object(MODULE.resource, "getrlimit", return_value=(1024, 1024)), \
             mock.patch.object(MODULE.os, "eventfd") as eventfd:
            self.assertFalse(MODULE.prepare(MODULE.defaults())["wineEsync"])
            eventfd.assert_not_called()
        profile = MODULE.defaults()
        profile["wineEsync"] = False
        with mock.patch.object(MODULE.resource, "setrlimit") as setlimit, \
             mock.patch.object(MODULE.os, "eventfd") as eventfd:
            self.assertFalse(MODULE.prepare(profile)["wineEsync"])
        setlimit.assert_not_called()
        eventfd.assert_not_called()

    def test_optional_scheduling_and_diagnostic_denials_still_exec_the_client(self):
        denied = PermissionError(errno.EPERM, "scheduler operation unavailable")
        arguments = ["client_performance.py", "exec", "3", "0", sys.executable, "-c", "pass"]
        with mock.patch.object(MODULE.os, "nice", side_effect=denied), \
             mock.patch.object(MODULE.os, "sched_setaffinity", side_effect=denied), \
             mock.patch.object(MODULE.os, "getpriority", side_effect=denied), \
             mock.patch.object(MODULE.os, "sched_getaffinity", side_effect=denied), \
             mock.patch.object(MODULE.os, "execvpe") as execute, \
             mock.patch("builtins.print") as output:
            MODULE.main(arguments)
        execute.assert_called_once_with(sys.executable, [sys.executable, "-c", "pass"], os.environ)
        messages = [call.args[0] for call in output.call_args_list]
        self.assertTrue(any("retaining current priority" in message for message in messages))
        self.assertTrue(any("retaining available CPUs" in message for message in messages))
        diagnostic = next(message for message in messages if message.startswith("Performance scheduling: "))
        self.assertEqual(json.loads(diagnostic.split(": ", 1)[1]), {"nice": "unavailable", "cpuAffinity": "unavailable"})

    def test_scheduling_wrapper_exec_preserves_journal_pid_and_applies_priority_and_affinity(self):
        profile = MODULE.defaults()
        profile["cpuAffinity"] = [min(os.sched_getaffinity(0))]
        payload = 'import json,os; print(json.dumps({"pid":os.getpid(),"nice":os.getpriority(os.PRIO_PROCESS,0),"cpus":sorted(os.sched_getaffinity(0))}))'
        for role in ("wineServer", "server", "market", "client"):
            with self.subTest(role=role):
                arguments = MODULE.command(role, (sys.executable, "-c", payload), profile)
                process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error)
                result = json.loads(output.splitlines()[-1])
                self.assertEqual(result["pid"], process.pid)
                if role == "client":
                    self.assertEqual(result["cpus"], profile["cpuAffinity"])
                else:
                    increase = profile["wineServerNice" if role == "wineServer" else "serverNice"]
                    self.assertEqual(result["nice"], os.getpriority(os.PRIO_PROCESS, 0) + increase)
        self.assertEqual(MODULE.command("display", ("unchanged",), profile), ("unchanged",))


if __name__ == "__main__":
    unittest.main()
