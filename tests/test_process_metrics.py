"""The fast reserve check must treat invalid/missing samples as unavailable."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "process_metrics", Path(__file__).resolve().parents[1] / "backend/process_metrics.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AvailableMemoryTests(unittest.TestCase):
    def test_memavailable_and_invalid_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            self.assertIsNone(MODULE.available_memory_kib(path))
            for raw, expected in [("MemFree: 20 kB\nMemAvailable: 12345 kB\n", 12345),
                                  ("MemAvailable: 0 kB\n", 0),
                                  ("MemFree: 20 kB\n", None),
                                  ("MemAvailable: -1 kB\n", None),
                                  ("MemAvailable: nope kB\n", None),
                                  ("MemAvailable: 45 bytes\n", None)]:
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    self.assertEqual(MODULE.available_memory_kib(path), expected)
