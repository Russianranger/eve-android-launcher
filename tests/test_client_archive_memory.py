"""Bounded ZIP directory parsing, ZIP64 and unchanged extraction safeguards."""
import io
import json
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import client_prepare as client


def large_zip(path, count):
    """Generate original tiny fixtures without ZipFile writer's resident index."""
    with path.open("wb") as output, tempfile.TemporaryFile() as central:
        for number in range(count):
            name = ("ResFiles/aa/%032x_%032x" % (number, number)).encode()
            offset = output.tell()
            crc = zlib.crc32(b"x")
            output.write(struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, 0, 0, 33,
                                     crc, 1, 1, len(name), 0) + name + b"x")
            central.write(struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 20, 20, 0, 0, 0, 33,
                                      crc, 1, 1, len(name), 0, 0, 0, 0, 0, offset) + name)
        start = output.tell()
        size = central.tell()
        central.seek(0)
        shutil.copyfileobj(central, output, 64 * 1024)
        end64 = output.tell()
        output.write(struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, start))
        output.write(struct.pack("<4sIQI", b"PK\x06\x07", 0, end64, 1))
        output.write(struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 65535, 65535, size, start, 0))


class ClientArchiveMemoryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "client.zip"

    def write(self, entries, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.path, "w", compression) as archive:
            archive.comment = b"archive comment"
            for name, value in entries:
                archive.writestr(name, value)

    def test_formats_unicode_comments_and_forced_zip64_local_header(self):
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(compression=compression):
                self.write([("SharedCache/tq/bin64/exefile.exe", b"original fixture"),
                            ("SharedCache/unicodé", b"content" * 100)], compression)
                with client.DiskZipFile(self.path) as archive:
                    self.assertEqual(client.archive_cache_root(archive), Path("SharedCache"))
                    self.assertEqual([archive.read(item) for item in archive], [b"original fixture", b"content" * 100])
                    self.assertEqual(archive.filelist, [])
                    self.assertEqual(archive.NameToInfo, {})
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as archive:
            with archive.open("zip64", "w", force_zip64=True) as stream:
                stream.write(b"payload")
        with client.DiskZipFile(self.path) as archive:
            self.assertEqual(archive.read(next(iter(archive))), b"payload")

    def test_zip64_directory_and_older_python_boundary_convention(self):
        large_zip(self.path, 3)
        original = zipfile._EndRecData
        def old_boundary(fp):
            result = original(fp)
            fp.seek(result[zipfile._ECD_LOCATION])
            if fp.read(4) == zipfile.stringEndArchive64:
                result[zipfile._ECD_LOCATION] += 76
            return result
        for legacy in (False, True):
            with mock.patch.object(zipfile, "_EndRecData", old_boundary if legacy else original):
                with client.DiskZipFile(self.path) as archive:
                    self.assertEqual([archive.read(item) for item in archive], [b"x"] * 3)

    def test_data_descriptors_and_prepended_archive_bytes(self):
        class Pipe(io.BytesIO):
            def seek(self, *args):
                raise OSError("unseekable output")
        output = Pipe()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("descriptor", b"payload" * 100)
        self.path.write_bytes(b"original self-extracting stub" + output.getvalue())
        with client.DiskZipFile(self.path) as archive:
            item = next(iter(archive))
            self.assertTrue(item.flag_bits & 8)
            self.assertEqual(archive.read(item), b"payload" * 100)
        large_zip(self.path, 3)
        self.path.write_bytes(b"stub" + self.path.read_bytes())
        with client.DiskZipFile(self.path) as archive:
            self.assertEqual([archive.read(item) for item in archive], [b"x"] * 3)

    def test_file_and_expanded_byte_limits_apply_during_indexing(self):
        self.write([("a", b"xx"), ("b", b"xx")])
        for field, limit in (("MAX_FILES", 1), ("MAX_BYTES", 3)):
            with mock.patch.object(client, field, limit):
                with self.assertRaisesRegex(ValueError, "file count or size limits"):
                    client.DiskZipFile(self.path)

    def test_unsafe_paths_duplicates_links_encryption_rejected_before_extraction(self):
        for name in ("../escape", "/absolute", "C:/drive", "a\\b", "./a", "a/../b"):
            self.write([(name, b"x")])
            with self.assertRaisesRegex(ValueError, "Unsafe ZIP"):
                client.DiskZipFile(self.path)
        self.write([("A", b"x"), ("a", b"y")])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            client.DiskZipFile(self.path)
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            item = zipfile.ZipInfo("special")
            item.external_attr = (mode | 0o777) << 16
            self.write([(item, b"x")])
            with self.assertRaisesRegex(ValueError, "special"):
                client.DiskZipFile(self.path)
        self.write([("secret", b"x")])
        data = bytearray(self.path.read_bytes())
        cd = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, cd + 8, 1)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Encrypted"):
            client.DiskZipFile(self.path)

    def test_nul_name_and_directory_truncation_count_and_extent_rejected(self):
        for corruption in ("nul", "truncated", "count", "extent", "duplicate-offset", "multidisk"):
            with self.subTest(corruption=corruption):
                self.write([("abc", b"one"), ("def", b"two")])
                data = bytearray(self.path.read_bytes())
                cd, eocd = data.index(b"PK\x01\x02"), data.index(b"PK\x05\x06")
                if corruption == "nul": data[cd + 46] = 0
                if corruption == "truncated": struct.pack_into("<H", data, cd + 30, 65535)
                if corruption == "count": struct.pack_into("<HH", data, eocd + 8, 1, 1)
                if corruption == "extent": struct.pack_into("<I", data, cd + 20, 0xfffffffe)
                if corruption == "duplicate-offset": struct.pack_into("<I", data, cd + 49 + 42, 0)
                if corruption == "multidisk": struct.pack_into("<H", data, eocd + 4, 1)
                self.path.write_bytes(data)
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    client.DiskZipFile(self.path)

    def test_local_header_crc_and_overlap_checks_still_run(self):
        for corruption in ("crc", "name", "overlap"):
            with self.subTest(corruption=corruption):
                self.write([("abc", b"one"), ("def", b"two")], zipfile.ZIP_STORED)
                data = bytearray(self.path.read_bytes())
                cd = data.index(b"PK\x01\x02")
                if corruption == "crc": data[33] ^= 1
                if corruption == "name": data[30] = ord('z')
                if corruption == "overlap": struct.pack_into("<I", data, cd + 20, 15)
                self.path.write_bytes(data)
                with client.DiskZipFile(self.path) as archive:
                    with self.assertRaises(zipfile.BadZipFile):
                        archive.read(next(iter(archive)))

    def test_index_progress_keeps_existing_interruption_phase_and_storage_reserve(self):
        large_zip(self.path, 1001)
        events = []
        with client.DiskZipFile(self.path, lambda *args, **details: events.append((args, details))):
            pass
        self.assertEqual(events[0][0][0], "extracting")
        self.assertEqual(events[0][1], {"stage": "indexing_archive", "processed_files": 1000, "total_files": 1001})
        with mock.patch.object(client.shutil, "disk_usage", return_value=type("Usage", (), {"free": 0})()):
            with self.assertRaisesRegex(ValueError, "free internal storage"):
                client.DiskZipFile(self.path)

    def test_directory_cache_is_bounded_and_rechecks_evicted_symlinks(self):
        staging = self.root / "stage"
        staging.mkdir()
        checked = set()
        for number in range(1030):
            client.ensure_import_directory(staging, staging / str(number), checked)
            self.assertLessEqual(len(checked), 1024)
        (staging / "0").rmdir()
        (staging / "0").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Unsafe existing import directory"):
            client.ensure_import_directory(staging, staging / "0", checked)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux worker address-space limit")
    def test_600000_zip64_entries_fit_128_mib_with_crc_reads(self):
        large_zip(self.path, 600000)
        code = """
import client_prepare as client, json, resource, sys
client.limit_preparation_memory(128)
with client.DiskZipFile(sys.argv[1]) as archive:
    count = 0
    for item in archive:
        if count in (0, 599999):
            assert archive.read(item) == b'x'
        count += 1
    assert len(archive) == count == 600000
    assert archive.total == 600000
    assert archive.filelist == [] and archive.NameToInfo == {}
print(json.dumps({'entries': count, 'peakKiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""
        import os
        env = dict(os.environ, PYTHONPATH=str(Path(client.__file__).parent))
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], env=env,
                                capture_output=True, text=True, timeout=120, check=True)
        report = json.loads(result.stdout)
        self.assertLess(report["peakKiB"], 128 * 1024)
        print("ZIP64 capacity: " + result.stdout.strip(), flush=True)
        # The old eager standard-library reader fails under this same limit.
        old = subprocess.run([sys.executable, "-c", "import resource,zipfile,sys; resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2)); zipfile.ZipFile(sys.argv[1])", str(self.path)],
                             capture_output=True, text=True, timeout=60)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn("MemoryError", old.stderr)
