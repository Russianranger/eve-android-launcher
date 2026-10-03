"""Exact patch, cache completeness and staged import regression tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile

MODULE = Path(__file__).resolve().parents[1] / "backend/client_prepare.py"
spec = importlib.util.spec_from_file_location("client_prepare", MODULE)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ClientPreparationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.original = self.root / "original.exe"
        client.make_x64_probe(self.original)
        data = bytearray(self.original.read_bytes())
        checksum, security = client.pe_fields(data)
        struct.pack_into("<II", data, security, len(data), 128)
        data += b"S" * 128
        self.binary = bytes(data)
        self.recipe = {"supportedBuild": client.BUILD,
                       "source": {"filename": "exefile.exe", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                       "patches": [{"offset": 0x201, "beforeHex": "25", "afterHex": "26"}], "knownPatchedVariants": []}

    def make_cache(self, folder, malformed=False):
        (folder / "tq/bin64").mkdir(parents=True)
        (folder / "tq/start.ini").write_text("build = 3396210\nserver = tranquility\ncryptoPack = CryptoAPI\n")
        (folder / "tq/bin64/exefile.exe").write_bytes(self.binary)
        (folder / "ResFiles/aa").mkdir(parents=True)
        (folder / "ResFiles/aa/0123_4567").write_bytes(b"resource data")
        for name in ("resfileindex.txt", "resfileindex_Windows.txt"):
            (folder / "tq" / name).write_text("wrong\n" if malformed else "res:/example,aa/0123_4567,hash,13,13\n")
        (folder / "index_tranquility.txt").write_text("build3396210")
        return folder

    def archive(self, folder, path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in folder.rglob("*"):
                if file.is_file():
                    archive.write(file, "SharedCache/" + str(file.relative_to(folder)))
        return path

    def test_patch_removes_signature_and_updates_checksum(self):
        output, state = client.patch_bytes(self.binary, self.recipe)
        self.assertEqual(state, "patched_exact_original")
        self.assertEqual(len(output), 0x600)
        checksum, security = client.pe_fields(output)
        self.assertEqual(struct.unpack_from("<II", output, security), (0, 0))
        self.assertEqual(output[0x201], 0x26)
        self.assertEqual(struct.unpack_from("<I", output, checksum)[0], client.pe_checksum(output, checksum))

    def test_wrong_binary_hash_cannot_be_relaxed(self):
        damaged = bytearray(self.binary)
        damaged[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            client.patch_bytes(damaged, self.recipe)

    def test_repeat_validate_uses_original_exact_hash(self):
        cache = self.make_cache(self.root / "cache")
        first = client.validate_content(cache, [self.recipe], apply=True)
        original = (cache / "tq/bin64/exefile.exe.evejs-original").read_bytes()
        second = client.validate_content(cache, [self.recipe], apply=True)
        self.assertEqual(first["binaries"][0]["sha256"], second["binaries"][0]["sha256"])
        self.assertEqual(original, self.binary)
        self.assertEqual(client.ini_values(cache / "tq/start.ini")["server"], "127.0.0.1")
        self.assertFalse(second["client_launch_qualified"])

    def test_complete_shared_cache_import_promotes_only_valid_content(self):
        cache = self.make_cache(self.root / "source")
        archive = self.archive(cache, self.root / "client.zip")
        target = self.root / "content"
        report = client.import_zip(archive, target, [self.recipe])
        self.assertEqual(report["resources"]["indexed_entries"], 2)
        self.assertTrue((target / "tq/bin64/exefile.exe").is_file())
        self.assertTrue((target / "eve-client-content.json").is_file())
        # A second corrupt import must retain every byte of existing content.
        before = (target / "tq/bin64/exefile.exe").read_bytes()
        (cache / "tq/bin64/exefile.exe").write_bytes(b"unsupported")
        self.archive(cache, archive)
        with self.assertRaises(ValueError):
            client.import_zip(archive, target, [self.recipe])
        self.assertEqual((target / "tq/bin64/exefile.exe").read_bytes(), before)

    def test_resource_gate_rejects_missing_and_malformed_assets(self):
        cache = self.make_cache(self.root / "cache")
        (cache / "ResFiles/aa/0123_4567").unlink()
        with self.assertRaisesRegex(ValueError, "Missing client file"):
            client.check_resources(cache)
        malformed = self.make_cache(self.root / "malformed", malformed=True)
        with self.assertRaisesRegex(ValueError, "Malformed"):
            client.check_resources(malformed)

    def test_oversized_binary_is_rejected_before_any_full_file_read(self):
        cache = self.make_cache(self.root / "cache")
        binary = cache / "tq/bin64/exefile.exe"
        # Sparse size creates no large resident buffer or expensive fixture.
        with binary.open("r+b") as output:
            output.truncate(1024**3)
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded binary read")):
            with self.assertRaisesRegex(ValueError, "Unsupported binary size"):
                client.validate_binaries(cache, [self.recipe], apply=True)
        self.assertFalse(binary.with_name(binary.name + ".evejs-original").exists())

    def test_oversized_resource_index_line_is_rejected(self):
        cache = self.make_cache(self.root / "cache")
        index = cache / "tq/resfileindex_Windows.txt"
        index.write_text("res:/example,aa/0123_4567," + "h" * client.MAX_INDEX_LINE + ",13,13\n")
        with self.assertRaisesRegex(ValueError, "Oversized resfileindex_Windows.txt entry 1"):
            client.check_resources(cache)

    def test_resource_duplicate_counts_and_case_variants_remain_accurate(self):
        cache = self.make_cache(self.root / "cache")
        (cache / "ResFiles/AA").mkdir()
        (cache / "ResFiles/AA/0123_4567").write_bytes(b"resource data")
        lower = "res:/example,aa/0123_4567,hash,13,13\n"
        upper = "res:/example,AA/0123_4567,hash,13,13\n"
        (cache / "tq/resfileindex.txt").write_text(lower * 3 + upper)
        (cache / "tq/resfileindex_Windows.txt").write_text(upper + lower * 2)
        result = client.check_resources(cache)
        self.assertEqual(result, {"indexed_entries": 7, "unique_resources": 1, "complete": True})
        # A duplicate spelling with different case must still have its own real
        # asset on this case-sensitive private filesystem.
        (cache / "ResFiles/AA/0123_4567").unlink()
        with self.assertRaisesRegex(ValueError, "Missing client file: ResFiles/AA/"):
            client.check_resources(cache)

    def test_resource_symlink_asset_and_shard_are_rejected(self):
        for kind in ("asset", "shard"):
            with self.subTest(kind=kind):
                cache = self.make_cache(self.root / kind)
                asset = cache / "ResFiles/aa/0123_4567"
                if kind == "asset":
                    outside = self.root / "outside-resource"
                    outside.write_bytes(asset.read_bytes())
                    asset.unlink()
                    asset.symlink_to(outside)
                else:
                    outside = self.root / "outside-shard"
                    (cache / "ResFiles/aa").replace(outside)
                    (cache / "ResFiles/aa").symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "Symbolic links"):
                    client.check_resources(cache)

    def test_late_windows_index_failure_precedes_all_binary_mutation(self):
        cache = self.make_cache(self.root / "cache")
        index = cache / "tq/resfileindex_Windows.txt"
        index.write_text("res:/example,aa/0123_4567,hash,13,13\n" * 1000
                         + "res:/late,aa/9876_5432,hash,13,13\n")
        progress = []
        with self.assertRaisesRegex(ValueError, "Missing client file: ResFiles/aa/9876_5432"):
            client.validate_content(cache, [self.recipe], apply=True,
                                    progress=lambda phase, message, **details: progress.append((phase, details)))
        self.assertTrue(any(details.get("indexed_entries") == 1000 for _, details in progress))
        self.assertEqual((cache / "tq/bin64/exefile.exe").read_bytes(), self.binary)
        self.assertFalse((cache / "tq/bin64/exefile.exe.evejs-original").exists())

    def test_binary_plan_does_not_apply_first_patch_when_later_hash_fails(self):
        cache = self.make_cache(self.root / "cache")
        second = json.loads(json.dumps(self.recipe))
        second["source"]["filename"] = "blue.dll"
        damaged = bytearray(self.binary)
        damaged[-1] ^= 1
        (cache / "tq/bin64/blue.dll").write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            client.validate_binaries(cache, [self.recipe, second], apply=True)
        self.assertEqual((cache / "tq/bin64/exefile.exe").read_bytes(), self.binary)
        self.assertFalse((cache / "tq/bin64/exefile.exe.evejs-original").exists())

    def test_legacy_interrupted_import_reuses_crc_valid_files_and_repairs_bad_files(self):
        source = self.make_cache(self.root / "source")
        archive = self.archive(source, self.root / "client.zip")
        target = self.make_cache(self.root / "content")
        (target / "existing-content-marker").write_text("keep until successful validation")
        stage = self.root / "content.import-legacy"
        staged_cache = stage / "SharedCache"
        shutil.copytree(source, staged_cache)
        valid_index = staged_cache / "tq/resfileindex.txt"
        original_index_mtime = valid_index.stat().st_mtime_ns
        # Same-size corruption exercises CRC rather than only length checking.
        (staged_cache / "ResFiles/aa/0123_4567").write_bytes(b"corrupt bytes")
        self.assertEqual(len(b"corrupt bytes"), len(b"resource data"))
        (staged_cache / "tq/bin64/exefile.exe").write_bytes(self.binary[:17])
        opened = []
        original_open = zipfile.ZipFile.open

        def track_open(value, member, *args, **kwargs):
            opened.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
            return original_open(value, member, *args, **kwargs)

        observed_validation = []

        def progress(phase, message, **details):
            if phase == "checking_resources":
                self.assertTrue((target / "existing-content-marker").is_file())
                self.assertEqual((target / "tq/bin64/exefile.exe").read_bytes(), self.binary)
                observed_validation.append(True)

        with mock.patch.object(zipfile.ZipFile, "open", track_open):
            report = client.import_zip(archive, target, [self.recipe], resume=True, progress=progress)
        self.assertTrue(observed_validation)
        self.assertEqual(set(opened), {"SharedCache/ResFiles/aa/0123_4567", "SharedCache/tq/bin64/exefile.exe"})
        self.assertEqual((target / "tq/resfileindex.txt").stat().st_mtime_ns, original_index_mtime)
        self.assertEqual((target / "ResFiles/aa/0123_4567").read_bytes(), b"resource data")
        self.assertEqual(report["resources"]["indexed_entries"], 2)
        self.assertFalse((target / "existing-content-marker").exists())
        self.assertFalse(stage.exists())

    def test_completed_extraction_retry_skips_decompression_but_rechecks_assets_and_binary_hash(self):
        source = self.make_cache(self.root / "source")
        archive = self.archive(source, self.root / "client.zip")
        target = self.make_cache(self.root / "content")
        (target / "existing-content-marker").write_text("retained")
        with mock.patch.object(client, "validate_content", side_effect=MemoryError("interrupted validation")):
            with self.assertRaises(MemoryError):
                client.import_zip(archive, target, [self.recipe])
        session_file = target.with_name(target.name + ".import-session.json")
        session = json.loads(session_file.read_text())
        self.assertEqual(session["phase"], "extracted")
        staged_cache = self.root / session["staging"] / "SharedCache"
        staged_asset = staged_cache / "ResFiles/aa/0123_4567"
        staged_asset.unlink()
        # Receipt-based retry may avoid decompression, but never resource or
        # exact-build binary validation or preservation of active content.
        with mock.patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("unexpected ZIP decompression")):
            with self.assertRaisesRegex(ValueError, "Missing client file"):
                client.import_zip(archive, target, [self.recipe], resume=True)
            self.assertTrue((target / "existing-content-marker").is_file())
            staged_asset.write_bytes(b"resource data")
            damaged = bytearray(self.binary)
            damaged[-1] ^= 1
            (staged_cache / "tq/bin64/exefile.exe").write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                client.import_zip(archive, target, [self.recipe], resume=True)
            self.assertTrue((target / "existing-content-marker").is_file())
            (staged_cache / "tq/bin64/exefile.exe").write_bytes(self.binary)
            report = client.import_zip(archive, target, [self.recipe], resume=True)
        self.assertTrue(report["resources"]["complete"])
        expected, _ = client.patch_bytes(self.binary, self.recipe)
        self.assertEqual(report["binaries"][0]["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertFalse(session_file.exists())

    def test_interrupted_extraction_retains_stage_for_crc_verified_retry(self):
        source = self.make_cache(self.root / "source")
        archive = self.archive(source, self.root / "client.zip")
        target = self.make_cache(self.root / "content")
        (target / "existing-content-marker").write_text("retained")
        opened = []
        original_open = zipfile.ZipFile.open

        def interrupt_second_entry(value, member, *args, **kwargs):
            opened.append(member.filename)
            if len(opened) == 2:
                raise KeyboardInterrupt("simulated process interruption")
            return original_open(value, member, *args, **kwargs)

        with mock.patch.object(zipfile.ZipFile, "open", interrupt_second_entry):
            with self.assertRaises(KeyboardInterrupt):
                client.import_zip(archive, target, [self.recipe])
        session_file = target.with_name(target.name + ".import-session.json")
        session = json.loads(session_file.read_text())
        self.assertEqual(session["phase"], "extracting")
        first_file = self.root / session["staging"] / opened[0]
        first_mtime = first_file.stat().st_mtime_ns
        self.assertTrue((target / "existing-content-marker").is_file())
        retried_entries = []

        def track_retry(value, member, *args, **kwargs):
            retried_entries.append(member.filename)
            return original_open(value, member, *args, **kwargs)

        with mock.patch.object(zipfile.ZipFile, "open", track_retry):
            report = client.import_zip(archive, target, [self.recipe], resume=True)
        self.assertNotIn(opened[0], retried_entries)
        promoted_first = target / Path(*Path(opened[0]).parts[1:])
        self.assertEqual(promoted_first.stat().st_mtime_ns, first_mtime)
        self.assertTrue(report["resources"]["complete"])
        self.assertFalse(session_file.exists())

    def test_import_discovers_cache_root_without_recursive_filesystem_scan(self):
        source = self.make_cache(self.root / "source")
        archive = self.archive(source, self.root / "client.zip")
        with mock.patch.object(Path, "rglob", side_effect=AssertionError("recursive client scan")):
            report = client.import_zip(archive, self.root / "content", [self.recipe])
        self.assertTrue(report["resources"]["complete"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux worker address-space limit")
    def test_many_resource_names_fit_128_mib_worker_address_space(self):
        # Isolate the cardinality regression: synthetic regular assets avoid
        # creating 600,000 filesystem entries. Real missing/link checks are
        # exercised separately; parser and disk-backed name storage are real.
        worker = textwrap.dedent("""
            import importlib.util, json, pathlib, resource, stat, sys, tempfile
            spec = importlib.util.spec_from_file_location('client_prepare', sys.argv[1])
            client = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(client)
            client.limit_preparation_memory(128)
            with tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                (root / 'ResFiles/aa').mkdir(parents=True)
                (root / 'tq').mkdir()
                (root / 'index_tranquility.txt').write_text('build3396210')
                for name in ('resfileindex.txt', 'resfileindex_Windows.txt'):
                    with (root / 'tq' / name).open('w') as output:
                        for number in range(600000):
                            output.write('res:/synthetic,aa/%032x_%032x,hash,13,13\\n' % (number, number))
                original_lstat = pathlib.Path.lstat
                def synthetic_lstat(path):
                    if path.parent == root / 'ResFiles/aa':
                        class Regular:
                            st_mode = stat.S_IFREG | 0o644
                        return Regular()
                    return original_lstat(path)
                pathlib.Path.lstat = synthetic_lstat
                report = client.check_resources(root)
                print(json.dumps({'report': report, 'peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
            """)
        result = subprocess.run([sys.executable, "-c", worker, str(MODULE)],
                                check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        report = json.loads(result.stdout)
        self.assertEqual(report["report"], {"indexed_entries": 1200000, "unique_resources": 600000, "complete": True})
        self.assertLess(report["peak_kib"], 128 * 1024)
        print("Resource capacity: 1,200,000 references / 600,000 names; peak "
              + str(report["peak_kib"]) + " KiB RSS under 128 MiB address-space limit", flush=True)

    def test_duplicate_ini_and_wrong_build_are_rejected(self):
        cache = self.make_cache(self.root / "cache")
        ini = cache / "tq/start.ini"
        ini.write_text("build=3396210\nBuild=3396210\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            client.validate_content(cache, [self.recipe])
        ini.write_text("build=999\n")
        with self.assertRaisesRegex(ValueError, "build3396210"):
            client.validate_content(cache, [self.recipe])

    def test_unsafe_zip_paths_links_and_case_collisions(self):
        bad_names = ("../escaped", "/absolute", "C:/windows", "tq/../../escaped", "tq\\bin64\\evil", "x:y", "./evil")
        for index, name in enumerate(bad_names):
            archive = self.root / ("unsafe" + str(index) + ".zip")
            with zipfile.ZipFile(archive, "w") as value:
                value.writestr(name, b"bad")
            with zipfile.ZipFile(archive) as value, self.assertRaisesRegex(ValueError, "Unsafe ZIP"):
                client.zip_members(value)
        archive = self.root / "duplicates.zip"
        with zipfile.ZipFile(archive, "w") as value:
            value.writestr("tq/A", b"one")
            value.writestr("tq/a", b"two")
        with zipfile.ZipFile(archive) as value, self.assertRaisesRegex(ValueError, "Duplicate"):
            client.zip_members(value)
        archive = self.root / "symlink.zip"
        with zipfile.ZipFile(archive, "w") as value:
            item = zipfile.ZipInfo("tq/link")
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            value.writestr(item, "../../outside")
        with zipfile.ZipFile(archive) as value, self.assertRaisesRegex(ValueError, "special"):
            client.zip_members(value)

    def test_x64_probe_really_contains_x64_entry_and_expected_exit(self):
        data = self.original.read_bytes()
        self.assertEqual(struct.unpack_from("<H", data, 0x84)[0], 0x8664)
        self.assertEqual(data[0x200:0x205], b"\xb9\x25\0\0\0")
        failed = client.write_probe_report(self.root / "state", 1, "wine-test")
        self.assertFalse(failed["translated_x64_probe_passed"])
        self.assertFalse(failed["client_launch_qualified"])
        passed = client.write_probe_report(self.root / "state", 37, "wine-test")
        self.assertTrue(passed["translated_x64_probe_passed"])
        self.assertFalse(passed["client_launch_qualified"])

    def test_missing_server_certificates_is_honest_waiting_state(self):
        result = client.prepare_trust(self.root / "content", self.root / "state", self.root / "missing-ca.pem")
        self.assertFalse(result["bundles_prepared"])
        self.assertFalse(result["wine_trust_qualified"])
        self.assertEqual(result["phase"], "waiting_for_server_certificates")

    def test_certificate_rotation_rebuilds_private_bundles_and_preferences(self):
        content = self.root / "content"
        bundle = content / "tq/lib/certifi/cacert.pem"
        bundle.parent.mkdir(parents=True)
        bundle.write_text("# original client trust bundle\n", encoding="ascii")
        server = self.root / "server"
        server.mkdir()
        ca = server / "xmpp-ca-cert.pem"
        state = self.root / "state"
        for identity in ("First", "Second"):
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=EveJS Test " + identity, "-keyout", str(server / "key.pem"), "-out", str(ca)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            expected = ca.read_text(encoding="ascii").strip()
            result = client.prepare_trust(content, state, ca)
            self.assertTrue(result["bundles_prepared"])
            self.assertFalse(result["wine_trust_qualified"])
            self.assertEqual(result["ca_der_sha256"], client.certificate_sha256(ca))
            self.assertEqual(bundle.read_text().count("-----BEGIN CERTIFICATE-----"), 1)
            self.assertIn(expected, bundle.read_text())
            # Repeat preparation does not append the certificate again.
            client.prepare_trust(content, state, ca)
            self.assertEqual(bundle.read_text().count("-----BEGIN CERTIFICATE-----"), 1)
        client.prepare_offline_preferences(state)
        policy = json.loads((state / "launch-policy.json").read_text())
        self.assertFalse(policy["launch_enabled"])
        self.assertEqual(policy["environment"]["HTTP_PROXY"], "http://127.0.0.1:26002/")
        prefs = state / "prefix/drive_c/users/root/AppData/Local/CCP/EVE/z_client_tq_127.0.0.1/settings/prefs.ini"
        self.assertIn("breakpadUpload=0", prefs.read_text())


if __name__ == "__main__":
    unittest.main()
