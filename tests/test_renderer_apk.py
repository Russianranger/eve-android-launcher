"""The Android asset transport must preserve the exact signed gzip archive."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("check_apk", Path(__file__).resolve().parents[1] / "scripts/check-apk.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RendererApkTests(unittest.TestCase):
    def archive(self, payload, *, name="renderer-runtime.bin", changed=None, manifest=None):
        value = manifest or {"file": "renderer-runtime.tar.gz", "sizeBytes": len(payload),
                             "sha256": hashlib.sha256(payload).hexdigest()}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("assets/renderer-manifest.json", json.dumps(value))
            output.writestr("assets/" + name, payload if changed is None else changed)
        return zipfile.ZipFile(io.BytesIO(stream.getvalue()))

    def test_neutral_asset_name_preserves_gzip_bytes_after_zip_compression(self):
        with self.archive(gzip.compress(b"exact renderer fixture", mtime=0)) as archive:
            MODULE.check_renderer(archive)

    def test_stripped_suffix_or_unwrapped_gzip_cannot_pass(self):
        raw = b"exact renderer fixture"
        payload = gzip.compress(raw, mtime=0)
        with self.archive(payload, name="renderer-runtime.tar", changed=raw) as archive:
            with self.assertRaises(KeyError):
                MODULE.check_renderer(archive)
        with self.archive(payload, changed=raw) as archive:
            with self.assertRaises(ValueError):
                MODULE.check_renderer(archive)

    def test_payload_corruption_and_manifest_size_or_name_mismatch_fail(self):
        payload = gzip.compress(b"exact renderer fixture", mtime=0)
        with self.archive(payload, changed=payload[:-1] + bytes([payload[-1] ^ 1])) as archive:
            with self.assertRaisesRegex(ValueError, "hashed renderer"):
                MODULE.check_renderer(archive)
        for value in ({"file": "renderer-runtime.tar.gz", "sizeBytes": len(payload) + 1},
                      {"file": "other.gz", "sizeBytes": len(payload)}):
            with self.archive(payload, manifest=value) as archive:
                with self.assertRaises(ValueError):
                    MODULE.check_renderer(archive)


if __name__ == "__main__":
    unittest.main()
