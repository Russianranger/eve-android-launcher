"""Exact patch, cache completeness and staged import regression tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest
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
