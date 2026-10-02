#!/usr/bin/env python3
"""Normalize Docker export to the small GNU-tar subset the Android app reads."""
import argparse
import gzip
import hashlib
import io
import json
import pathlib
import posixpath
import tarfile

EXCLUDED_TREES = {'dev', 'proc', 'sys', 'run', 'tmp', 'var/cache/apt', 'var/lib/apt/lists'}
EXCLUDED_FILES = {'.dockerenv', 'etc/mtab', 'etc/hostname', 'etc/hosts', 'etc/resolv.conf'}


def canonical(name):
    name = name.removeprefix('./').rstrip('/')
    if not name or name == '.':
        return ''
    if name.startswith('/') or any(part in ('..', '') for part in name.split('/')):
        raise ValueError('Unsafe archive path: ' + name)
    return name


def excluded(name):
    return name in EXCLUDED_FILES or any(name.startswith(tree + '/') for tree in EXCLUDED_TREES)


def pack(source, destination):
    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    unpacked_bytes = 0
    names = set()
    with tarfile.open(source, 'r:*') as original, destination.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.GNU_FORMAT) as packed:
                for entry in original:
                    name = canonical(entry.name)
                    if not name or excluded(name):
                        continue
                    if name in names:
                        raise ValueError('Duplicate Docker-export entry: ' + name)
                    names.add(name)
                    if not (entry.isdir() or entry.isfile() or entry.islnk() or entry.issym()):
                        continue  # sockets, FIFOs and device nodes never leave CI
                    normalized = tarfile.TarInfo(name)
                    normalized.uid = normalized.gid = 0
                    normalized.uname = normalized.gname = 'root'
                    normalized.mtime = 0
                    normalized.mode = entry.mode & 0o777  # drop setuid/setgid
                    if entry.isdir():
                        normalized.type = tarfile.DIRTYPE
                        packed.addfile(normalized)
                    elif entry.issym():
                        if '\x00' in entry.linkname or not entry.linkname:
                            raise ValueError('Invalid symlink: ' + name)
                        # Absolute targets are guest paths. Relative targets must
                        # resolve inside the guest root; app defers link creation.
                        if not entry.linkname.startswith('/'):
                            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), entry.linkname))
                            if target == '..' or target.startswith('../'):
                                raise ValueError('Symlink escapes guest root: ' + name)
                        normalized.type = tarfile.SYMTYPE
                        normalized.linkname = entry.linkname
                        packed.addfile(normalized)
                    else:
                        handle = original.extractfile(entry)
                        if handle is None:
                            raise ValueError('Cannot dereference regular/hardlinked file: ' + name)
                        # Materialize hardlinks: the app does not need tar type1.
                        normalized.size = entry.size
                        if entry.islnk():
                            normalized.size = handle.seek(0, 2)
                            handle.seek(0)
                        normalized.type = tarfile.REGTYPE
                        packed.addfile(normalized, handle)
                        unpacked_bytes += normalized.size
                for name, content in (
                    ('etc/hosts', b'127.0.0.1 localhost\n::1 localhost\n'),
                    ('etc/hostname', b'eve-android\n'),
                    ('etc/resolv.conf', b'nameserver 1.1.1.1\nnameserver 8.8.8.8\n'),
                ):
                    entry = tarfile.TarInfo(name)
                    entry.mode = 0o644
                    entry.size = len(content)
                    packed.addfile(entry, io.BytesIO(content))
                    unpacked_bytes += len(content)
    return unpacked_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('docker_export')
    parser.add_argument('--output', default='out/server-runtime-arm64.tar.gz')
    parser.add_argument('--manifest', default='out/server-runtime-manifest.json')
    parser.add_argument('--inputs-sha256', required=True)
    args = parser.parse_args()
    unpacked = pack(args.docker_export, args.output)
    archive = pathlib.Path(args.output)
    with tarfile.open(archive, 'r:gz') as bundle:
        marker = json.load(bundle.extractfile('etc/eve-server-runtime.json'))
    with archive.open('rb') as handle:
        checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest = {
        'format': 1,
        'formatVersion': 1,
        'architecture': 'arm64',
        'runtime': 'eve-server-1',
        'clientBuild': 3396210,
        'file': archive.name,
        'sha256': checksum,
        'sizeBytes': archive.stat().st_size,
        'unpackedBytes': unpacked,
        'upstreamVersion': marker['evejsVersion'],
        'upstreamArchiveSha256': marker['upstreamArchiveSha256'],
        'runtimeInputsSha256': args.inputs_sha256,
    }
    pathlib.Path(args.manifest).write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
