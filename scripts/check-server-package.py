#!/usr/bin/env python3
"""Verify archive integrity, the ARM64 native ABI and immutable seed metadata."""
import argparse
import hashlib
import json
import pathlib
import sqlite3
import struct
import tarfile
import tempfile


def check_elf(handle, description):
    header = handle.read(64)
    if len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != 183:
        raise ValueError(description + ' must be ELF64 little-endian AArch64')


def check(archive, manifest_path=None):
    archive = pathlib.Path(archive)
    manifest_path = pathlib.Path(manifest_path or archive.with_name('server-runtime-manifest.json'))
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get('formatVersion') == 1, 'Unsupported manifest format'
    assert manifest.get('runtime') == 'eve-server-1', 'Unexpected runtime'
    assert manifest.get('architecture') == 'arm64', 'Unexpected architecture'
    assert manifest.get('clientBuild') == 3396210, 'Client build mismatch'
    assert manifest.get('file') == archive.name, 'Archive filename mismatch'
    assert manifest.get('sizeBytes') == archive.stat().st_size, 'Archive size mismatch'
    with archive.open('rb') as handle:
        assert manifest['sha256'] == hashlib.file_digest(handle, 'sha256').hexdigest(), 'Archive SHA-256 mismatch'
    source = manifest.get('correspondingSource')
    if source:
        source_path = archive.with_name(source['file'])
        assert source_path.name == source['file'] and '/' not in source['file'], 'Unsafe source filename'
        assert source_path.stat().st_size == source['sizeBytes'], 'Corresponding-source size mismatch'
        with source_path.open('rb') as handle:
            assert hashlib.file_digest(handle, 'sha256').hexdigest() == source['sha256'], 'Corresponding-source SHA-256 mismatch'
    seen = set()
    with tarfile.open(archive, 'r:gz') as bundle:
        for entry in bundle:
            name = entry.name.rstrip('/')
            assert name and not name.startswith('/') and '..' not in name.split('/'), 'Unsafe archive path: ' + name
            assert name not in seen, 'Duplicate archive path: ' + name
            seen.add(name)
            assert not entry.pax_headers, 'PAX header unsupported by Android extractor'
            assert entry.isdir() or entry.isfile() or entry.issym(), 'Unsupported archive type: ' + name
            assert not any(name.startswith(tree + '/') for tree in ('dev', 'proc', 'sys', 'run', 'tmp')), 'Pseudo filesystem content: ' + name
            if entry.issym():
                import posixpath
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), entry.linkname))
                assert entry.linkname and not target.startswith('../') and target != '..', 'Symlink escapes guest root: ' + name
        marker = json.load(bundle.extractfile('etc/eve-server-runtime.json'))
        assert marker['format'] == 1 and marker['schemaVersion'] == 1
        assert marker['architecture'] == 'arm64' and marker['runtime'] == 'eve-server-1'
        assert marker['evejsVersion'] == '0.12.9' and marker['clientBuild'] == 3396210
        assert marker['node']['architecture'] == 'arm64'
        assert marker['upstreamArchiveSha256'] == manifest['upstreamArchiveSha256']
        check_elf(bundle.extractfile('usr/local/bin/node'), 'Node.js')
        check_elf(bundle.extractfile('usr/local/bin/market-server'), 'Market daemon')
        check_elf(bundle.extractfile('opt/evejs/server/node_modules/better-sqlite3/build/Release/better_sqlite3.node'), 'Native SQLite module')
        game_manifest = json.load(bundle.extractfile('opt/evejs-seed/gameStore/manifest.json'))
        assert game_manifest['build'] == 3396210
        assert bundle.getmember('opt/evejs-seed/gameStore/data/itemTypes/data.json').size > 0
        assert 'opt/evejs-seed/config/server.json' in seen
        provenance = json.load(bundle.extractfile('opt/evejs-seed/seed-provenance.json'))
        assert provenance['clientBuild'] == 3396210 and provenance['marketPreset'] == 'jita_only'
        assert provenance['optionalContentPacks'] is False
        assert not any(name.startswith('opt/evejs/content-packs/') for name in seen)
        with tempfile.TemporaryDirectory(prefix='eve-market-check-') as directory:
            market_path = pathlib.Path(directory) / 'market.sqlite'
            with bundle.extractfile('opt/evejs-seed/market/market.sqlite') as source, market_path.open('wb') as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
            with sqlite3.connect('file:' + str(market_path) + '?mode=ro', uri=True) as connection:
                assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
    return {'passed': True, 'architecture': 'arm64', 'clientBuild': 3396210, 'entries': len(seen), 'sha256': manifest['sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--manifest')
    args = parser.parse_args()
    print(json.dumps(check(args.archive, args.manifest), indent=2))
