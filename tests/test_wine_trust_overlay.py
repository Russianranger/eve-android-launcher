"""Refuse damaged or mismatched trust modules before launching Wine."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import wine_trust_overlay as overlay


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bound = self.root / "runtime"
        self.manifest = self.root / "wine-trust-overlay.json"
        files = []
        for target, (asset, machines) in overlay.TARGETS.items():
            machine = next(iter(machines))
            data = bytearray(70)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 60, 64)
            data[64:68] = b"PE\0\0"
            struct.pack_into("<H", data, 68, machine)
            (self.root / asset).write_bytes(data)
            bound = self.bound / target
            bound.parent.mkdir(parents=True, exist_ok=True)
            bound.write_bytes(data)
            files.append({"target": target, "asset": asset, "machine": machine,
                          "sha256": hashlib.sha256(data).hexdigest(), "baselineSha256": "a" * 64})
        self.value = {"format": 1, "runtime": "fex-arm64ec-1", "overlay": overlay.OVERLAY,
                      "wine_commit": overlay.WINE_COMMIT, "files": files}
        self.write(self.value)

    def write(self, value):
        self.manifest.write_text(json.dumps(value))

    def test_bound_overlay_is_verified_without_modifying_runtime(self):
        before = {p: p.read_bytes() for p in self.bound.rglob("*.dll")}
        result = overlay.verify(self.manifest, bound_root=self.bound)
        self.assertEqual(result["overlay"], overlay.OVERLAY)
        self.assertEqual(before, {p: p.read_bytes() for p in self.bound.rglob("*.dll")})

    def test_rejects_damage_and_absent_session_binding(self):
        item = self.value["files"][0]
        path = self.bound / item["target"]
        path.write_bytes(b"unpatched runtime")
        with self.assertRaises(ValueError):
            overlay.verify(self.manifest, bound_root=self.bound)
        (self.root / item["asset"]).write_bytes(b"damaged APK asset")
        with self.assertRaises(ValueError):
            overlay.verify(self.manifest)

    def test_rejects_mismatched_build_architecture_and_paths(self):
        mutations = [
            lambda value: value.update(wine_commit="0" * 40),
            lambda value: value["files"][0].update(machine=0x8664),
            lambda value: value["files"][0].update(target="../../prefix/system.reg"),
            lambda value: value["files"][0].update(asset="../other.dll"),
            lambda value: value["files"].append(value["files"][0]),
            lambda value: value["files"].pop(),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(self.value)
                mutation(value)
                self.write(value)
                with self.assertRaises(ValueError):
                    overlay.verify(self.manifest)

    def test_rejects_linked_module(self):
        asset = self.root / self.value["files"][0]["asset"]
        data = asset.read_bytes()
        asset.unlink()
        (self.root / "other.dll").write_bytes(data)
        asset.symlink_to(self.root / "other.dll")
        with self.assertRaises(ValueError):
            overlay.verify(self.manifest)


if __name__ == "__main__":
    unittest.main()
