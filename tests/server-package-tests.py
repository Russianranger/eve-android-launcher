#!/usr/bin/env python3
"""Small archive fixtures exercise safety and native-runtime rejection paths."""
import hashlib
import importlib.util
import io
import json
import pathlib
import sqlite3
import struct
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = load('eve_package', 'scripts/package-runtime.py')
checker = load('eve_checker', 'scripts/check-server-package.py')


class ServerPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def add(self, bundle, name, content=b'', kind=tarfile.REGTYPE, link=''):
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = link
        entry.mode = 0o4755
        entry.size = len(content) if kind == tarfile.REGTYPE else 0
        bundle.addfile(entry, io.BytesIO(content) if kind == tarfile.REGTYPE else None)

    def test_normalizes_hardlinks_long_names_and_discards_special_nodes(self):
        raw = self.root / 'docker.tar'
        long_name = 'opt/evejs/' + ('a' * 110) + '/source.js'
        with tarfile.open(raw, 'w', format=tarfile.PAX_FORMAT) as bundle:
            self.add(bundle, 'usr/bin/python3', b'python')
            self.add(bundle, 'usr/bin/python', kind=tarfile.LNKTYPE, link='usr/bin/python3')
            self.add(bundle, 'bin', kind=tarfile.SYMTYPE, link='usr/bin')
            self.add(bundle, 'etc/alternatives/python', kind=tarfile.SYMTYPE, link='/usr/bin/python3')
            self.add(bundle, long_name, b'long name')
            self.add(bundle, 'dev/null', kind=tarfile.CHRTYPE)
            self.add(bundle, 'tmp/fifo', kind=tarfile.FIFOTYPE)
            self.add(bundle, 'run/host-secret', b'ignore me')
        result = self.root / 'runtime.tar.gz'
        package.pack(raw, result)
        with tarfile.open(result) as bundle:
            self.assertEqual(bundle.extractfile('usr/bin/python').read(), b'python')
            self.assertTrue(bundle.getmember('usr/bin/python').isfile())
            self.assertEqual(bundle.getmember('bin').linkname, 'usr/bin')
            self.assertEqual(bundle.extractfile(long_name).read(), b'long name')
            self.assertFalse(any(entry.pax_headers for entry in bundle))
            self.assertFalse(any(entry.name.startswith(('dev/', 'run/', 'tmp/')) for entry in bundle))
            self.assertEqual(bundle.getmember('usr/bin/python3').mode, 0o755)

    def test_rejects_path_and_relative_symlink_escapes(self):
        for name, kind, link in [('etc/../../outside', tarfile.REGTYPE, ''), ('opt/escape', tarfile.SYMTYPE, '../../outside')]:
            with self.subTest(name=name):
                raw = self.root / 'unsafe.tar'
                with tarfile.open(raw, 'w') as bundle:
                    self.add(bundle, name, b'test', kind, link)
                with self.assertRaises(ValueError):
                    package.pack(raw, self.root / 'unsafe.tar.gz')

    def create_valid_archive(self, machine=183):
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', elf, 18, machine)
        database = self.root / 'market.sqlite'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS seeded_orders (id INTEGER PRIMARY KEY)')
        marker = {'format': 1, 'schemaVersion': 1, 'architecture': 'arm64', 'runtime': 'eve-server-1', 'evejsVersion': '0.12.9', 'clientBuild': 3396210, 'node': {'architecture': 'arm64'}, 'upstreamArchiveSha256': 'a' * 64}
        raw = self.root / 'valid.tar'
        with tarfile.open(raw, 'w') as bundle:
            for name in ['usr/local/bin/node', 'usr/local/bin/market-server', 'opt/evejs/server/node_modules/better-sqlite3/build/Release/better_sqlite3.node']:
                self.add(bundle, name, bytes(elf))
            self.add(bundle, 'etc/eve-server-runtime.json', json.dumps(marker).encode())
            self.add(bundle, 'opt/evejs-seed/gameStore/manifest.json', b'{"build":3396210}')
            self.add(bundle, 'opt/evejs-seed/gameStore/data/itemTypes/data.json', b'{"items":[1]}')
            self.add(bundle, 'opt/evejs-seed/config/server.json', b'{}')
            self.add(bundle, 'opt/evejs-seed/seed-provenance.json', b'{"clientBuild":3396210,"marketPreset":"jita_only","optionalContentPacks":false}')
            self.add(bundle, 'opt/evejs-seed/market/market.sqlite', database.read_bytes())
        archive = self.root / 'server-runtime-arm64.tar.gz'
        unpacked = package.pack(raw, archive)
        manifest = {'formatVersion': 1, 'architecture': 'arm64', 'runtime': 'eve-server-1', 'clientBuild': 3396210, 'file': archive.name, 'sizeBytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'upstreamArchiveSha256': 'a' * 64, 'unpackedBytes': unpacked}
        manifest_path = self.root / 'server-runtime-manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        return archive

    def test_checks_valid_seed_native_abi_and_rejects_wrong_arch(self):
        self.assertTrue(checker.check(self.create_valid_archive())['passed'])
        with self.assertRaisesRegex(ValueError, 'AArch64'):
            checker.check(self.create_valid_archive(machine=62))

    def test_rejects_corrupt_archive_before_install(self):
        archive = self.create_valid_archive()
        with archive.open('ab') as handle:
            handle.write(b'corrupt')
        with self.assertRaisesRegex(AssertionError, 'size mismatch'):
            checker.check(archive)


if __name__ == '__main__':
    unittest.main()
