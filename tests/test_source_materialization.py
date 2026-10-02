import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prepare_source", ROOT / "scripts/prepare-evejs-source.py")
prepare_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_source)


class SourceMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "vendor/evejs"
        self.source.mkdir(parents=True)
        (self.source / "LICENSE").write_bytes(b"original license\n")
        (self.source / "README.md").write_bytes(b"original readme\n")
        (self.source / "old-stale-file.txt").write_text("must disappear")

    def archive(self, entries):
        path = self.root / "vendor/evejs-source.tar.gz"
        with tarfile.open(path, "w:gz", format=tarfile.GNU_FORMAT) as archive:
            for name, content, entry_type in entries:
                entry = tarfile.TarInfo(name)
                entry.type = entry_type
                entry.mode = 0o755 if name.endswith(".sh") else 0o644
                entry.size = len(content) if entry_type == tarfile.REGTYPE else 0
                if entry_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    entry.linkname = "../../outside"
                archive.addfile(entry, io.BytesIO(content) if entry.isfile() else None)
        metadata = {"sourceArchive": {
            "file": "../evejs-source.tar.gz", "format": "gnu-tar-gzip",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sizeBytes": path.stat().st_size}}
        (self.source / "UPSTREAM.json").write_text(json.dumps(metadata))
        return path

    def test_exact_source_bytes_retained_provenance_and_idempotence(self):
        self.archive([("server/main.js", b"console.log('native server');\n", tarfile.REGTYPE),
                      ("tools/setup.sh", b"#!/bin/sh\n", tarfile.REGTYPE)])
        provenance = (self.source / "UPSTREAM.json").read_bytes()
        first = prepare_source.materialize(self.root)
        self.assertEqual((self.source / "server/main.js").read_bytes(), b"console.log('native server');\n")
        self.assertEqual((self.source / "LICENSE").read_bytes(), b"original license\n")
        self.assertEqual((self.source / "UPSTREAM.json").read_bytes(), provenance)
        self.assertFalse((self.source / "old-stale-file.txt").exists())
        self.assertEqual((self.source / "tools/setup.sh").stat().st_mode & 0o777, 0o755)
        self.assertEqual(prepare_source.materialize(self.root), first)

    def test_hash_failure_preserves_existing_tree(self):
        path = self.archive([("server/main.js", b"original", tarfile.REGTYPE)])
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            prepare_source.materialize(self.root)
        self.assertTrue((self.source / "old-stale-file.txt").exists())

    def test_rejects_traversal_links_and_retained_overrides(self):
        for name, entry_type in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                                 ("linked", tarfile.SYMTYPE), ("hard", tarfile.LNKTYPE),
                                 ("LICENSE", tarfile.REGTYPE)):
            with self.subTest(name=name):
                self.archive([(name, b"invalid", entry_type)])
                with self.assertRaises(ValueError):
                    prepare_source.materialize(self.root)
                self.assertTrue((self.source / "old-stale-file.txt").exists())
                self.assertFalse((self.root / "escape").exists())

    def test_duplicate_paths_fail_without_replacing_source(self):
        self.archive([("server/file.js", b"first", tarfile.REGTYPE),
                      ("server/file.js", b"second", tarfile.REGTYPE)])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            prepare_source.materialize(self.root)
        self.assertTrue((self.source / "old-stale-file.txt").exists())

    def shard_archive(self, archive):
        metadata = json.loads((self.source / "UPSTREAM.json").read_text())
        payload = archive.read_bytes()
        parts = []
        for index, offset in enumerate(range(0, len(payload), 32), 1):
            chunk = payload[offset:offset + 32]
            name = f"evejs-source.tar.gz.part{index:02d}"
            (self.root / "vendor" / name).write_bytes(chunk)
            parts.append({"file": "../" + name, "sizeBytes": len(chunk),
                          "sha256": hashlib.sha256(chunk).hexdigest()})
        metadata["sourceArchive"]["parts"] = parts
        (self.source / "UPSTREAM.json").write_text(json.dumps(metadata))
        archive.unlink()

    def test_shards_reproduce_source_without_an_untracked_full_archive(self):
        archive = self.archive([("server/main.js", b"pinned source", tarfile.REGTYPE)])
        self.shard_archive(archive)
        prepare_source.materialize(self.root)
        self.assertEqual((self.source / "server/main.js").read_bytes(), b"pinned source")
        self.assertFalse(archive.exists())
        self.assertEqual(list((self.root / "vendor").glob(".evejs-source-*.tar.gz")), [])

    def test_corrupt_shard_fails_before_replacing_source(self):
        archive = self.archive([("server/main.js", b"pinned source", tarfile.REGTYPE)])
        self.shard_archive(archive)
        shard = self.root / "vendor/evejs-source.tar.gz.part01"
        shard.write_bytes(b"x" * shard.stat().st_size)
        with self.assertRaisesRegex(ValueError, "shard SHA-256"):
            prepare_source.materialize(self.root)
        self.assertTrue((self.source / "old-stale-file.txt").exists())
        self.assertEqual(list((self.root / "vendor").glob(".evejs-source-*.tar.gz")), [])


if __name__ == "__main__":
    unittest.main()
