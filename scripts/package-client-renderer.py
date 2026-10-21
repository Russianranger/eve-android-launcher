#!/usr/bin/env python3
"""Package the bounded renderer payload and hash every shipped file."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

MAX_ARCHIVE = 64 * 1024**2
MAX_UNPACKED = 128 * 1024**2
RUNTIME = 'dxvk-turnip-1'
COMPONENTS = {
    'mesa': {'version': '25.2.8',
             'url': 'https://archive.mesa3d.org/mesa-25.2.8.tar.xz',
             'sha256': '097842f3e49d996868b38688db87b006f7d4541e93ce86d2f341d8b3e7be7c93'},
    'dxvk': {'version': '2.7.1',
             'url': 'https://github.com/doitsujin/dxvk/releases/download/v2.7.1/dxvk-2.7.1.tar.gz',
             'sha256': 'd85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87',
             'sourceUrl': 'https://github.com/doitsujin/dxvk/archive/refs/tags/v2.7.1.tar.gz',
             'sourceSha256': '4966be884da4a1ded7e38ee018caef5626bd06bbd0853715084b1a1644aaaf02'},
}
REQUIRED = {'lib/libvulkan_freedreno.so', 'dxvk/d3d11.dll', 'dxvk/dxgi.dll',
            'turnip_icd.json', 'licenses/mesa-license.rst', 'licenses/dxvk-LICENSE',
            'licenses/mesa-licenses.tar.gz', 'licenses/gcc-copyright', 'licenses/debian-packages.txt',
            'licenses/compiler.txt', 'licenses/meson.txt'}


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def package(source, archive, manifest):
    source, archive, manifest = Path(source), Path(archive), Path(manifest)
    files = []
    for item in sorted(source.rglob('*')):
        if item.is_symlink() or not (item.is_dir() or item.is_file()):
            raise ValueError('Renderer payload must contain only regular files and directories')
        if not item.is_file():
            continue
        name = item.relative_to(source).as_posix()
        if name not in REQUIRED:
            raise ValueError('Unexpected renderer file: ' + name)
        files.append({'path': name, 'sha256': digest(item), 'sizeBytes': item.stat().st_size})
    if {item['path'] for item in files} != REQUIRED:
        raise ValueError('Incomplete renderer payload')
    unpacked = sum(item['sizeBytes'] for item in files)
    if unpacked > MAX_UNPACKED:
        raise ValueError('Renderer payload exceeds bounded extraction limit')
    with (source / 'lib/libvulkan_freedreno.so').open('rb') as library:
        header = library.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
        raise ValueError('Turnip must be a native ARM64 ELF library')
    for name in ('d3d11.dll', 'dxgi.dll'):
        with (source / 'dxvk' / name).open('rb') as dll:
            header = dll.read(64)
            if len(header) != 64 or header[:2] != b'MZ':
                raise ValueError('Invalid DXVK DLL')
            dll.seek(int.from_bytes(header[60:64], 'little'))
            if dll.read(6) != b'PE\0\0d\x86':
                raise ValueError('DXVK must be the official x64 PE DLL')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open('wb') as target:
        with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.GNU_FORMAT) as output:
                for item in files:
                    entry = tarfile.TarInfo(item['path'])
                    entry.size = item['sizeBytes']
                    entry.mode = 0o644
                    entry.uid = entry.gid = entry.mtime = 0
                    with (source / item['path']).open('rb') as content:
                        output.addfile(entry, content)
    if archive.stat().st_size > MAX_ARCHIVE:
        archive.unlink()
        raise ValueError('Renderer archive exceeds download limit')
    report = {'format': 1, 'runtime': RUNTIME, 'architecture': 'arm64',
              'file': archive.name, 'sha256': digest(archive),
              'sizeBytes': archive.stat().st_size, 'unpackedBytes': unpacked,
              'components': COMPONENTS, 'files': files}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--output', default='backend/renderer-runtime.tar.gz')
    parser.add_argument('--manifest', default='backend/renderer-manifest.json')
    options = parser.parse_args()
    print(json.dumps(package(options.source, options.output, options.manifest)))


if __name__ == '__main__':
    main()
