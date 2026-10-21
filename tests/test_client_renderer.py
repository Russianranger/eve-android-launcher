import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import client_renderer

spec = importlib.util.spec_from_file_location("renderer_packager", Path(__file__).resolve().parents[1] / "scripts/package-client-renderer.py")
renderer_packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer_packager)


def elf(machine=183):
    value = bytearray(64)
    value[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", value, 18, machine)
    return bytes(value)


def pe(machine=0x8664):
    value = bytearray(128)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 60, 64)
    value[64:68] = b"PE\0\0"
    struct.pack_into("<H", value, 68, machine)
    return bytes(value)


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.prefix = self.state / "prefix"
        self.system = self.prefix / "drive_c/windows/system32"
        self.system.mkdir(parents=True)
        self.files = {"lib/libvulkan_freedreno.so": elf(), "dxvk/d3d11.dll": pe(),
                      "dxvk/dxgi.dll": pe(), "licenses/mesa.txt": b"MIT test fixture",
                      "turnip_icd.json": b'{"ICD":{"library_path":"lib/libvulkan_freedreno.so"}}'}
        (self.assets / "eve-renderer-probe.exe").write_bytes(pe())
        self.package()

    def package(self, extra=None):
        archive = self.assets / "renderer-runtime.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            for name, value in self.files.items():
                row = tarfile.TarInfo(name)
                row.size = len(value)
                output.addfile(row, io.BytesIO(value))
            if extra is not None:
                output.addfile(extra)
        self.manifest = {"format": 1, "runtime": client_renderer.RUNTIME, "architecture": "arm64",
                         "file": archive.name, "sizeBytes": archive.stat().st_size,
                         "unpackedBytes": sum(map(len, self.files.values())),
                         "sha256": client_renderer.digest(archive),
                         "components": copy.deepcopy(client_renderer.SOURCE_PINS),
                         "files": [{"path": name, "sizeBytes": len(value),
                                    "sha256": hashlib.sha256(value).hexdigest()}
                                   for name, value in self.files.items()]}
        self.write_manifest()

    def write_manifest(self):
        (self.assets / "renderer-manifest.json").write_text(json.dumps(self.manifest))

    def prepare(self, kgsl=Path("/dev/null")):
        return client_renderer.prepare(self.state, self.prefix, self.assets, kgsl)

    def test_selects_only_pinned_native_dxvk_and_turnip(self):
        prepared = self.prepare()
        self.assertEqual(prepared.env["WINEDLLOVERRIDES"], "winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n")
        self.assertEqual(prepared.env["MESA_VK_WSI_DEBUG"], "sw")
        icd = Path(prepared.env["VK_ICD_FILENAMES"])
        self.assertTrue(icd.is_file())
        self.assertEqual(prepared.report["packageSha256"], self.manifest["sha256"])
        self.assertFalse(prepared.report["deviceProbePassed"])
        self.assertEqual(prepared.probe_command("/opt/wine/bin/wine"),
                         ("/opt/wine/bin/wine", str(self.assets / "eve-renderer-probe.exe")))
        self.assertEqual((self.system / "d3d11.dll").read_bytes(), pe())
        self.assertTrue(all(name not in prepared.env for name in client_renderer.SOFTWARE_VARIABLES))

    def test_replaces_builtin_link_without_modifying_target(self):
        builtin = self.root / "wine-d3d11.dll"
        builtin.write_bytes(b"original builtin")
        (self.system / "d3d11.dll").symlink_to(builtin)
        self.prepare()
        self.assertEqual(builtin.read_bytes(), b"original builtin")
        self.assertFalse((self.system / "d3d11.dll").is_symlink())

    def test_corrupt_cached_install_is_replaced(self):
        first = self.prepare()
        icd = Path(first.env["VK_ICD_FILENAMES"])
        library = icd.parent / "lib/libvulkan_freedreno.so"
        library.write_bytes(b"bad")
        second = self.prepare()
        self.assertEqual(first.report, second.report)
        self.assertEqual(library.read_bytes(), elf())

    def test_wrong_source_pin_and_archive_corruption_fail(self):
        self.manifest["components"]["mesa"]["sha256"] = "0" * 64
        self.write_manifest()
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "pins"):
            self.prepare()
        self.package()
        with (self.assets / "renderer-runtime.tar.gz").open("ab") as output:
            output.write(b"tamper")
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "checksum"):
            self.prepare()

    def test_no_kgsl_and_wrong_architecture_fail_cleanly(self):
        with self.assertRaises(client_renderer.RendererUnavailable):
            self.prepare(self.root / "absent-kgsl")
        regular = self.root / "fake-kgsl"
        regular.write_bytes(b"")
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "KGSL"):
            self.prepare(regular)
        self.files["lib/libvulkan_freedreno.so"] = elf(62)
        self.package()
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "ARM64"):
            self.prepare()

    def test_archive_links_traversal_and_unlisted_members_rejected(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("dxvk/link", tarfile.SYMTYPE),
                           ("extra", tarfile.REGTYPE)):
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name)
                extra.type = kind
                extra.linkname = "../../escape"
                self.package(extra)
                with self.assertRaises(client_renderer.RendererUnavailable):
                    self.prepare()
                self.assertFalse((self.root / "escape").exists())

    def test_manifest_duplicate_and_allocation_limits(self):
        self.manifest["files"].append(self.manifest["files"][0])
        self.write_manifest()
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "duplicate"):
            self.prepare()
        self.package()
        self.manifest["files"][0]["sizeBytes"] = client_renderer.MAX_UNPACKED + 1
        self.write_manifest()
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "unpacked"):
            self.prepare()

    def test_prefix_directory_symlink_is_rejected(self):
        self.system.rmdir()
        target = self.root / "outside"
        target.mkdir()
        self.system.symlink_to(target)
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "symbolic"):
            self.prepare()
        self.assertEqual(list(target.iterdir()), [])

    def test_prefix_root_link_and_external_prefix_are_rejected(self):
        alternate = self.root / "other-prefix"
        alternate.mkdir()
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "private"):
            client_renderer.prepare(self.state, alternate, self.assets, Path("/dev/null"))
        linked = self.state / "linked-prefix"
        linked.symlink_to(self.prefix)
        with self.assertRaisesRegex(client_renderer.RendererUnavailable, "symbolic"):
            client_renderer.prepare(self.state, linked, self.assets, Path("/dev/null"))

    def test_build_packager_and_backend_agree(self):
        payload = self.root / "payload"
        payload.mkdir()
        for name in renderer_packager.REQUIRED:
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.files.get(name, b"license/build record fixture"))
        report = renderer_packager.package(payload, self.assets / "renderer-runtime.tar.gz",
                                            self.assets / "renderer-manifest.json")
        prepared = self.prepare()
        self.assertEqual(prepared.report["packageSha256"], report["sha256"])
        (payload / "unexpected.dll").write_bytes(pe())
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            renderer_packager.package(payload, self.assets / "renderer-runtime.tar.gz",
                                       self.assets / "renderer-manifest.json")


if __name__ == "__main__":
    unittest.main()
