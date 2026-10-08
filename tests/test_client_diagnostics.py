"""Bounded retained observations without credentials or ownership changes."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import client_diagnostics as diagnostics
import client_graphics
import client_runtime
import server_runtime


def proc_stat(pid, name, ticks=0, start="10", state="S"):
    fields = ["0"] * 22
    fields[0] = state
    fields[11] = str(ticks)
    fields[19] = str(start)
    return f"{pid} ({name}) " + " ".join(fields)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="client-diagnostics-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.sysfs = self.root / "sys"
        self.sysfs.mkdir()
        self.cache = self.state / "cache"
        self.cache.mkdir()
        self.caches = (self.cache / "dxvk", self.cache / "mesa")
        self.history = diagnostics.PerformanceHistory(self.state, self.caches, proc=self.proc, sysfs=self.sysfs)
        self.namespace = mock.patch.object(server_runtime, "NAMESPACE_MAPPING", False)
        self.namespace.start()
        self.addCleanup(self.namespace.stop)

    def task(self, tid=21, name="dxvk-shader-n", ticks=0, start="100", state="S", wait="futex_wait_queue"):
        path = self.proc / "20/task" / str(tid)
        path.mkdir(parents=True, exist_ok=True)
        (path / "stat").write_text(proc_stat(tid, name, ticks, start, state))
        (path / "wchan").write_text(wait)
        return path

    def snapshot(self, at, *, pid=20, ticks=0, start="10", rss=123):
        path = self.proc / str(pid)
        path.mkdir(exist_ok=True)
        (path / "stat").write_text(proc_stat(pid, "private-password", ticks, start))
        return server_runtime.ProcessSnapshot(at, {pid: [{"pid": pid, "startTicks": start,
                                                         "cpuTicks": ticks, "rssKiB": rss}]})

    def read(self):
        return json.loads(self.history.path.read_bytes())

    def sysfs_file(self, name, value):
        path = self.sysfs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_hardware_frequencies_and_thermal_units_are_preserved(self):
        self.sysfs_file("class/kgsl/kgsl-3d0/devfreq/cur_freq", "599000000\n")
        self.sysfs_file("class/kgsl/kgsl-3d0/devfreq/max_freq", "1000000000\n")
        self.sysfs_file("class/kgsl/kgsl-3d0/gpuclk", "0\n")
        self.sysfs_file("devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "1200000\n")
        self.sysfs_file("devices/system/cpu/cpu0/cpufreq/scaling_max_freq", "3000000\n")
        self.sysfs_file("class/thermal/thermal_zone0/type", "cpu-0-0\n")
        self.sysfs_file("class/thermal/thermal_zone0/temp", "72000\n")
        self.sysfs_file("class/thermal/thermal_zone1/type", "battery\n")
        self.sysfs_file("class/thermal/thermal_zone1/temp", "-500\n")
        report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(report["gpu"], {"curFreqHz": 599000000, "maxFreqHz": 1000000000, "gpuclkHz": 0})
        self.assertEqual(report["cpu"]["cores"],
                         [{"cpu": 0, "scalingCurFreqKHz": 1200000, "scalingMaxFreqKHz": 3000000}])
        self.assertEqual(report["thermal"]["zones"],
                         [{"zone": 0, "type": "cpu-0-0", "tempMilliC": 72000},
                          {"zone": 1, "type": "battery", "tempMilliC": -500}])
        self.assertNotIn("utilization", json.dumps(report))
        self.assertNotIn(str(self.sysfs), json.dumps(report))

    def test_absent_hardware_is_explicit_without_invented_zero_values(self):
        report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(report["gpu"], {"unavailable": {"curFreqHz": "missing", "maxFreqHz": "missing", "gpuclkHz": "missing"}})
        self.assertEqual(report["cpu"], {"cores": [], "missingCores": list(range(8))})
        self.assertEqual(report["thermal"], {"zones": [], "missingZones": list(range(32))})

    def test_hardware_permission_io_and_partial_missing_statuses_are_truthful(self):
        self.sysfs_file("devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "500000\n")
        self.sysfs_file("class/thermal/thermal_zone0/type", "gpu-0\n")
        original = diagnostics._bounded_text
        def readable(path, limit):
            if path == self.sysfs / "class/kgsl/kgsl-3d0/devfreq/cur_freq":
                raise PermissionError(errno.EACCES, "private path should never be retained")
            if path == self.sysfs / "class/kgsl/kgsl-3d0/gpuclk":
                raise OSError(errno.EIO, "private path should never be retained")
            if path == self.sysfs / "class/thermal/thermal_zone0/temp":
                raise PermissionError(errno.EPERM, "private path should never be retained")
            return original(path, limit)
        with mock.patch.object(diagnostics, "_bounded_text", side_effect=readable):
            report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(report["gpu"]["unavailable"],
                         {"curFreqHz": "permission-denied", "maxFreqHz": "missing", "gpuclkHz": "unavailable"})
        self.assertEqual(report["cpu"]["cores"],
                         [{"cpu": 0, "scalingCurFreqKHz": 500000, "unavailable": {"scalingMaxFreqKHz": "missing"}}])
        self.assertEqual(report["thermal"]["zones"],
                         [{"zone": 0, "type": "gpu-0", "unavailable": {"tempMilliC": "permission-denied"}}])
        self.assertNotIn("private", json.dumps(report))

    def test_hardware_numeric_reads_and_driver_identifiers_are_bounded(self):
        for invalid in ("", "not-a-number", "12.5", "NaN", "-1", "9" * 33, "100000000001"):
            with self.subTest(value=invalid):
                self.sysfs_file("class/kgsl/kgsl-3d0/devfreq/cur_freq", invalid)
                self.assertEqual(diagnostics.hardware_metrics(self.sysfs)["gpu"]["unavailable"]["curFreqHz"], "malformed")
        self.sysfs_file("devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "100000001")
        self.sysfs_file("class/thermal/thermal_zone0/type", "private secret\nstack")
        self.sysfs_file("class/thermal/thermal_zone0/temp", "2147483647")
        self.sysfs_file("class/thermal/thermal_zone1/type", "a" * 65)
        self.sysfs_file("class/thermal/thermal_zone1/temp", "-273151")
        report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(report["cpu"]["cores"][0]["unavailable"]["scalingCurFreqKHz"], "malformed")
        for zone in report["thermal"]["zones"]:
            self.assertEqual(zone["unavailable"], {"type": "malformed", "tempMilliC": "malformed"})
        self.assertNotIn("private", json.dumps(report))

    def test_hardware_only_fixed_eight_cpus_and_thirty_two_zones_are_read(self):
        for cpu in range(9):
            for attribute in ("scaling_cur_freq", "scaling_max_freq"):
                self.sysfs_file(f"devices/system/cpu/cpu{cpu}/cpufreq/{attribute}", "1000000")
        for zone in range(33):
            self.sysfs_file(f"class/thermal/thermal_zone{zone}/type", "tsens_tz_sensor")
            self.sysfs_file(f"class/thermal/thermal_zone{zone}/temp", "70000")
        with mock.patch.object(diagnostics, "_bounded_text", wraps=diagnostics._bounded_text) as reads, \
                mock.patch.object(os, "scandir", side_effect=AssertionError("hardware directory walk")):
            report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(len(report["cpu"]["cores"]), 8)
        self.assertEqual(len(report["thermal"]["zones"]), 32)
        self.assertEqual(reads.call_count, 3 + 2 * 8 + 2 * 32)
        self.assertFalse(any("cpu8/" in str(call.args[0]) or "thermal_zone32/" in str(call.args[0])
                             for call in reads.call_args_list))
        self.assertLess(len(json.dumps(report, separators=(",", ":"))), 3500)

    def test_hardware_sysfs_class_and_policy_symlinks_are_readable(self):
        policy = self.sysfs / "devices/system/cpu/cpufreq/policy0"
        policy.mkdir(parents=True)
        (policy / "scaling_cur_freq").write_text("1200000")
        (policy / "scaling_max_freq").write_text("3000000")
        cpu = self.sysfs / "devices/system/cpu/cpu0"
        cpu.mkdir()
        (cpu / "cpufreq").symlink_to(policy, target_is_directory=True)
        sensor = self.sysfs / "devices/virtual/thermal/thermal_zone0"
        sensor.mkdir(parents=True)
        (sensor / "type").write_text("tsens_tz_sensor0")
        (sensor / "temp").write_text("72000")
        thermal = self.sysfs / "class/thermal"
        thermal.mkdir(parents=True)
        (thermal / "thermal_zone0").symlink_to(sensor, target_is_directory=True)
        report = diagnostics.hardware_metrics(self.sysfs)
        self.assertEqual(report["cpu"]["cores"][0]["scalingCurFreqKHz"], 1200000)
        self.assertEqual(report["thermal"]["zones"][0]["tempMilliC"], 72000)

    def test_hardware_cached_ten_seconds_not_duplicated_and_reset_per_session(self):
        self.task()
        self.history.begin()
        with mock.patch.object(diagnostics, "hardware_metrics", wraps=diagnostics.hardware_metrics) as hardware:
            self.history.sample(self.snapshot(1), {"client": 20}, "starting")
            self.history.sample(self.snapshot(6), {"client": 20}, "running")
            report = self.read()
            self.assertEqual(hardware.call_count, 1)
            self.assertNotIn("hardware", report["samples"][-1])
            self.assertEqual(report["samples"][-1]["hardwareSampleAgeSeconds"], 5)
            self.assertEqual(report["samples"][-1]["hardwareSampleAt"], report["latestHardware"]["at"])
            self.history.sample(self.snapshot(11), {"client": 20}, "running")
            self.assertEqual(hardware.call_count, 2)
            report = self.read()
            self.assertEqual(report["samples"][-1]["hardwareSampleAgeSeconds"], 0)
            self.assertEqual(report["samples"][-1]["hardware"], report["latestHardware"])
            self.history.finish("stopped")
            self.history.sample(self.snapshot(21), {"client": 20}, "running")
            self.assertEqual(hardware.call_count, 2)
            self.history.begin()
            self.history.sample(self.snapshot(22), {"client": 20}, "starting")
            self.assertEqual(hardware.call_count, 3)
            self.assertEqual(self.read()["samples"][0]["hardwareSampleAgeSeconds"], 0)

    def test_hardware_live_and_terminal_history_remain_within_existing_byte_budget(self):
        for cpu in range(8):
            for attribute in ("scaling_cur_freq", "scaling_max_freq"):
                self.sysfs_file(f"devices/system/cpu/cpu{cpu}/cpufreq/{attribute}", "3000000")
        for zone in range(32):
            self.sysfs_file(f"class/thermal/thermal_zone{zone}/type", "tsens_tz_sensor" + str(zone))
            self.sysfs_file(f"class/thermal/thermal_zone{zone}/temp", "72000")
        for tid in range(30, 46):
            self.task(tid=tid)
        self.history.begin()
        for at in range(1, 651, 5):
            self.history.sample(self.snapshot(at), {"client": 20}, "running")
        self.assertLessEqual(self.history.path.stat().st_size, diagnostics.FILE_LIMIT)
        self.assertGreater(self.read().get("samplesDroppedForBytes", 0), 0)
        self.history.finish("stopped")
        report = self.read()
        self.assertLessEqual(self.history.path.stat().st_size, diagnostics.FILE_LIMIT)
        self.assertLessEqual(len(report["samples"]), diagnostics.SAMPLE_LIMIT)
        self.assertEqual(report["phase"], "stopped")
        self.assertEqual(len(report["latestHardware"]["thermal"]["zones"]), 32)
        self.assertNotIn("permission-denied", json.dumps(report["latestHardware"]["thermal"]))
        self.history.begin()
        with mock.patch.object(diagnostics, "_sysfs_text", return_value=(None, "permission-denied")):
            for at in range(1, 651, 5):
                self.history.sample(self.snapshot(at), {"client": 20}, "running")
            self.history.finish("failed")
        report = self.read()
        self.assertLessEqual(self.history.path.stat().st_size, diagnostics.FILE_LIMIT)
        self.assertEqual(report["phase"], "failed")
        self.assertEqual(len(report["latestHardware"]["thermal"]["zones"]), 32)
        self.assertTrue(all(zone["unavailable"]["tempMilliC"] == "permission-denied"
                            for zone in report["latestHardware"]["thermal"]["zones"]))

    def test_tiny_budget_drops_latest_hardware_without_losing_terminal_update(self):
        self.task()
        self.history.file_limit = 1400
        self.history.begin()
        with mock.patch.object(diagnostics, "_sysfs_text", return_value=(None, "permission-denied")):
            self.history.sample(self.snapshot(1), {"client": 20}, "running")
        self.history.finish("failed")
        report = self.read()
        self.assertLessEqual(self.history.path.stat().st_size, 1400)
        self.assertEqual(report["phase"], "failed")
        self.assertIn("endedAt", report)
        self.assertTrue(report["latestHardwareDroppedForBytes"])
        self.assertNotIn("latestHardware", report)

    def test_cpu_thread_identity_and_compiler_waits_survive_stop(self):
        self.task(ticks=10)
        self.history.begin()
        self.history.sample(self.snapshot(1, ticks=20), {"client": 20}, "starting")
        self.task(ticks=35, state="R", wait="0")
        self.history.sample(self.snapshot(6, ticks=70), {"client": 20}, "running")
        self.history.finish("stopped")
        report = self.read()
        self.assertEqual(report["phase"], "stopped")
        self.assertEqual(len(report["samples"]), 2)
        live = report["samples"][-1]
        self.assertEqual(live["roles"]["client"]["rssKiB"], 123)
        self.assertAlmostEqual(live["roles"]["client"]["cpuCorePercent"], 100 * 50 / 5 / server_runtime.CLOCK_TICKS)
        worker = live["clientThreads"]["rows"][0]
        self.assertEqual(worker["class"], "shader-normal")
        self.assertEqual(worker["state"], "R")
        self.assertEqual(worker["wchan"], "unavailable")
        self.assertAlmostEqual(worker["cpuCorePercent"], 100 * 25 / 5 / server_runtime.CLOCK_TICKS)
        before = self.history.path.read_bytes()
        self.history.sample(server_runtime.ProcessSnapshot(11, {20: []}), {"client": 20}, "stopped")
        self.assertEqual(self.history.path.read_bytes(), before)

    def test_recycled_process_is_not_read_and_recycled_thread_has_no_cpu_delta(self):
        path = self.task(ticks=100)
        self.history.begin()
        self.history.sample(self.snapshot(1), {"client": 20}, "starting")
        self.task(ticks=1000, start="101")
        self.history.sample(self.snapshot(6), {"client": 20}, "running")
        row = self.read()["samples"][-1]["clientThreads"]["rows"][0]
        self.assertIsNone(row["cpuCorePercent"])
        snapshot = self.snapshot(11)
        (self.proc / "20/stat").write_text(proc_stat(20, "recycled", 0, "new"))
        with mock.patch.object(diagnostics, "_wait_channel", side_effect=AssertionError("recycled process task read")):
            self.history.sample(snapshot, {"client": 20}, "running")
        summary = self.read()["samples"][-1]["clientThreads"]
        self.assertEqual(summary["tasksRead"], 0)
        self.assertEqual(summary["unavailable"], 1)

    def test_arbitrary_names_stat_content_and_invalid_wchan_are_not_exported(self):
        self.task(name="password=(super-secret)", wait="private secret\nstack")
        other = self.task(tid=22, name="dxvk-shader-high", wait="futex_wait_queue")
        self.history.begin()
        self.history.sample(self.snapshot(1), {"client": 20}, "starting")
        report = self.history.path.read_text()
        self.assertNotIn("super-secret", report)
        self.assertNotIn("private", report)
        self.assertNotIn("dxvk-shader-high", report)
        self.assertNotIn(str(self.root), report)
        classes = self.read()["samples"][0]["clientThreads"]["classes"]
        self.assertEqual(classes["other"]["threads"], 2)
        self.assertEqual(classes["other"]["waits"]["unavailable"], 1)
        (other / "stat").write_text("X" * (diagnostics.STAT_LIMIT + 1))
        self.history.sample(self.snapshot(6), {"client": 20}, "running")
        self.assertEqual(self.read()["samples"][-1]["clientThreads"]["unavailable"], 1)

    def test_exact_submission_names_are_classified_without_other_names(self):
        self.task(tid=21, name="dxvk-submit")
        self.task(tid=22, name="dxvk-queue")
        self.task(tid=23, name="dxvk-submit-secret")
        self.task(tid=24, name="dxvk-frame")
        self.task(tid=25, name="dxvk-frame-secret")
        self.history.begin()
        self.history.sample(self.snapshot(1), {"client": 20}, "running")
        classes = self.read()["samples"][0]["clientThreads"]["classes"]
        self.assertEqual({label: item["threads"] for label, item in classes.items()},
                         {"submission": 1, "completion": 1, "presentation": 1, "other": 2})
        self.assertEqual(classes["submission"]["cpuSampledThreads"], 0)

    def test_presentation_wait_row_is_retained_beside_main_and_compilers(self):
        self.task(tid=20, name="private-main", wait="futex_wait_queue")
        for tid in range(30, 50):
            self.task(tid=tid, name="dxvk-shader-n")
        self.task(tid=50, name="dxvk-frame", wait="futex_wait_queue")
        self.history.begin()
        self.history.sample(self.snapshot(1), {"client": 20}, "running")
        summary = self.read()["samples"][0]["clientThreads"]
        self.assertTrue(summary["rows"][0]["main"])
        frame = next(row for row in summary["rows"] if row["class"] == "presentation")
        self.assertEqual(frame["wchan"], "futex_wait_queue")
        self.assertEqual(len(summary["rows"]), diagnostics.THREAD_ROWS)

    def test_process_reused_during_task_read_discards_all_rows_and_counters(self):
        self.task()
        self.history.begin()
        snapshot = self.snapshot(1)
        original = diagnostics._stat
        reads = 0
        def replaced(path):
            nonlocal reads
            name, record = original(path)
            if path == self.proc / "20":
                reads += 1
                if reads == 2:
                    record["startTicks"] = "999"
            return name, record
        with mock.patch.object(diagnostics, "_stat", side_effect=replaced):
            self.history.sample(snapshot, {"client": 20}, "running")
        summary = self.read()["samples"][0]["clientThreads"]
        self.assertEqual(summary["tasksRead"], 0)
        self.assertEqual(summary["identityChanges"], 1)
        self.assertEqual(self.history.previous_threads, {})

    def test_blocked_completion_row_is_reserved_with_many_shader_threads(self):
        for tid in range(30, 50):
            self.task(tid=tid, name="dxvk-shader-n")
        self.task(tid=50, name="dxvk-queue", wait="dma_fence_wait")
        self.history.begin()
        self.history.sample(self.snapshot(1), {"client": 20}, "running")
        summary = self.read()["samples"][0]["clientThreads"]
        completion = next(row for row in summary["rows"] if row["class"] == "completion")
        self.assertEqual(completion["wchan"], "dma_fence_wait")
        self.assertEqual(len(summary["rows"]), diagnostics.THREAD_ROWS)

    def test_main_thread_is_retained_beside_compilers_and_busy_support_threads(self):
        self.task(tid=20, name="private-main-name", wait="futex_wait_queue")
        for tid in range(30, 50):
            self.task(tid=tid, name="other", ticks=100)
        self.task(tid=50, name="dxvk-shader-h")
        self.task(tid=51, name="dxvk-queue")
        self.history.begin()
        self.history.wrapper_pid = 20
        self.history.sample(self.snapshot(1), {"client": 20}, "running")
        summary = self.read()["samples"][0]["clientThreads"]
        self.assertEqual(summary["rows"][0]["tid"], 20)
        self.assertTrue(summary["rows"][0]["main"])
        self.assertEqual(summary["rows"][0]["processClass"], "wrapper")
        self.assertIn("completion", {row["class"] for row in summary["rows"]})
        self.assertNotIn("private-main-name", self.history.path.read_text())

    def test_per_member_main_rows_are_bounded_and_wrapper_child_classes_are_safe(self):
        members = []
        for pid in range(20, 26):
            path = self.proc / str(pid)
            (path / "task" / str(pid)).mkdir(parents=True)
            raw = proc_stat(pid, "private-name")
            (path / "stat").write_text(raw)
            (path / "task" / str(pid) / "stat").write_text(raw)
            (path / "task" / str(pid) / "wchan").write_text("futex_wait_queue")
            members.append({"pid": pid, "startTicks": "10", "cpuTicks": 0, "rssKiB": 123})
        self.history.begin()
        self.history.wrapper_pid = 20
        self.history.sample(server_runtime.ProcessSnapshot(1, {20: members}), {"client": 20}, "running")
        rows = self.read()["samples"][0]["clientThreads"]["rows"]
        self.assertEqual([row["processClass"] for row in rows[:diagnostics.MAIN_ROWS]],
                         ["wrapper", "child", "child", "child"])
        self.assertEqual(len(rows), diagnostics.MAIN_ROWS)

    def test_task_bound_and_blocked_compiler_aggregates_are_visible(self):
        for tid in range(30, 50):
            self.task(tid=tid, name="other", state="R", ticks=100)
        self.task(tid=50, name="dxvk-shader-h", wait="futex_wait_queue")
        self.history.begin()
        with mock.patch.object(diagnostics, "TASK_LIMIT", 21):
            self.history.sample(self.snapshot(1), {"client": 20}, "starting")
        summary = self.read()["samples"][0]["clientThreads"]
        self.assertEqual(summary["tasksRead"], 21)
        self.assertEqual(summary["rows"][0]["class"], "shader-high")
        self.assertEqual(len(summary["rows"]), diagnostics.THREAD_ROWS)
        self.assertEqual(summary["classes"]["shader-high"]["states"], {"S": 1})
        with mock.patch.object(diagnostics, "TASK_LIMIT", 3):
            self.history.sample(self.snapshot(6), {"client": 20}, "running")
        summary = self.read()["samples"][-1]["clientThreads"]
        self.assertEqual(summary["tasksObserved"], 3)
        self.assertTrue(summary["truncated"])

    def test_cache_counts_only_regular_metadata_and_rejects_linked_parents(self):
        self.caches[0].mkdir()
        (self.caches[0] / "secret-filename").write_bytes(b"private secret content")
        nested = self.caches[0] / "nested"
        nested.mkdir()
        (nested / "another-secret").write_bytes(b"123")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret").write_bytes(b"x" * 9999)
        (nested / "escape").symlink_to(outside, target_is_directory=True)
        result = diagnostics.cache_metadata(self.caches[0])
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["bytes"], len(b"private secret content") + 3)
        self.assertEqual(result["directories"], 1)
        self.assertNotIn("secret", json.dumps(result))
        parent = self.state / "linked"
        parent.symlink_to(outside, target_is_directory=True)
        rejected = diagnostics.cache_metadata(parent / "cache")
        self.assertTrue(rejected["unavailable"])
        self.assertEqual(rejected["files"], 0)
        with mock.patch.object(diagnostics, "CACHE_ENTRY_LIMIT", 1):
            self.assertTrue(diagnostics.cache_metadata(self.caches[0])["truncated"])

    def test_sampling_cadence_cache_cadence_ring_and_prior_session_are_bounded(self):
        self.task()
        self.history.begin()
        with mock.patch.object(diagnostics, "cache_metadata", wraps=diagnostics.cache_metadata) as cache:
            self.history.sample(self.snapshot(1), {"client": 20}, "starting")
            self.history.sample(self.snapshot(2), {"client": 20}, "running")
            self.assertEqual(len(self.history.samples), 1)
            self.assertEqual(cache.call_count, 2)
            for at in range(6, 631, 5):
                self.history.sample(self.snapshot(at), {"client": 20}, "running")
            self.assertEqual(len(self.history.samples), diagnostics.SAMPLE_LIMIT)
            self.assertEqual(cache.call_count, 2 * 21)
        self.history.finish("failed")
        self.assertLessEqual(self.history.path.stat().st_size, diagnostics.FILE_LIMIT)
        prior = self.history.path.read_bytes()
        self.history.begin()
        self.history.sample(self.snapshot(640), {"client": 20}, "starting")
        self.assertEqual(self.history.path.with_name(self.history.path.name + ".1").read_bytes(), prior)
        self.assertEqual(len(self.read()["samples"]), 1)

    def test_serialized_byte_limit_applies_after_finish_markers(self):
        self.task()
        self.history.file_limit = 1400
        self.history.begin()
        for at in range(1, 61, 5):
            self.history.sample(self.snapshot(at), {"client": 20}, "running")
        self.history.finish("failed")
        self.assertLessEqual(self.history.path.stat().st_size, 1400)
        self.assertEqual(self.read()["phase"], "failed")
        self.assertIn("endedAt", self.read())
        self.assertGreater(self.read()["samplesDroppedForBytes"], 0)

    def test_inaccessible_proc_and_failed_writes_do_not_fail_client(self):
        self.history.begin()
        with mock.patch.object(diagnostics, "_stat", side_effect=PermissionError), \
                mock.patch.object(os, "fsync", side_effect=OSError):
            self.history.sample(self.snapshot(1), {"client": 20}, "running")
            self.history.finish("failed")
        self.assertEqual(self.history.samples[-1]["clientThreads"]["unavailable"], 1)
        self.assertGreater(self.history.report["writeFailures"], 0)

    def test_runtime_status_reuses_filtered_snapshot_and_terminal_keeps_live_history(self):
        runtime = client_runtime.Runtime(client_runtime.Settings(state=self.state))
        process = mock.Mock(pid=20)
        runtime.children = {"client": process}
        snapshot = self.snapshot(1, ticks=40)
        self.task()
        runtime.diagnostics = self.history
        self.history.begin()
        with mock.patch.object(runtime, "refresh_owned_processes", return_value=snapshot), \
                mock.patch.object(client_runtime, "memory_metrics", return_value={}):
            runtime.status("running", "fixture")
        with mock.patch.object(runtime, "refresh_owned_processes", return_value=server_runtime.ProcessSnapshot(6, {20: []})), \
                mock.patch.object(client_runtime, "memory_metrics", return_value={}):
            runtime.status("stopped", "fixture")
        retained = self.read()["samples"][-1]
        self.assertEqual(retained["roles"]["client"]["cpuTicks"], 40)
        self.assertEqual(retained["clientThreads"]["tasksRead"], 1)

    def test_actual_process_cpu_and_rss_are_retained_after_exit(self):
        self.namespace.stop()
        runtime = client_runtime.Runtime(client_runtime.Settings(state=self.state))
        runtime.diagnostics.sysfs = self.sysfs
        runtime.identities = {"supervisorIdentity": server_runtime.process_identity(os.getpid())}
        process = runtime.spawn("client", (sys.executable, "-c", "while True: sum(range(2000))"),
                                env={"PATH": "/usr/bin:/bin"}, cwd=self.state)
        try:
            with mock.patch.object(diagnostics, "SAMPLE_SECONDS", 0), \
                    mock.patch.object(client_runtime, "memory_metrics", return_value={}):
                runtime.status("running", "fixture")
                initial = runtime.diagnostics.samples[-1]["roles"]["client"]["cpuTicks"]
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    record = server_runtime.process_record(process.pid)
                    if record and record.get("cpuTicks", 0) > initial:
                        break
                    time.sleep(.01)
                runtime.status("running", "fixture")
                self.assertTrue(runtime.shutdown())
                runtime.status("stopped", "fixture")
            report = json.loads((self.state / "client-performance.json").read_bytes())
            live = report["samples"][-1]
            self.assertEqual(report["phase"], "stopped")
            self.assertEqual(report["graphicsMode"], "turnip-dxvk")
            self.assertEqual(report["dxvkVersion"], client_graphics.DXVK_VERSION)
            self.assertEqual(report["mesaVersion"], client_graphics.MESA_VERSION)
            self.assertEqual(report["clientIdentity"]["pid"], process.pid)
            self.assertEqual(report["supervisorIdentity"]["pid"], os.getpid())
            self.assertGreater(live["roles"]["client"]["cpuCorePercent"], 0)
            self.assertGreater(live["roles"]["client"]["rssKiB"], 0)
            self.assertGreater(live["clientThreads"]["tasksRead"], 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
