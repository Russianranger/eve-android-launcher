#!/usr/bin/env python3
"""Build native DXVK and reuse only the verified immutable Turnip components.

Every downloaded executable byte is SHA-256 checked before use. Source archives
contain only the graphics components shipped, their exact original source and
the new build recipe. No TRASC Wine/D3D9/game patch bytes are deployed.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from pe_image import arm64ec_metadata


DXVK_COMMIT = "c707d9026f33b6ab89639f154b6ac5f6326fa037"
SUBMODULES = {
    "include/vulkan": "46dc0f6e514f5730784bb2cac2a7c731636839e8",
    "include/spirv": "8b246ff75c6615ba4532fe4fde20f1be090c3764",
    "subprojects/libdisplay-info": "275e6459c7ab1ddd4b125f28d0440716e4888078",
}
RELEASE = "https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.17/"
BUNDLE_HASH = "e4acf8e2dd432e11ec4aac3ad86137890b664df90cd467455b64209dfb56e1ba"
SOURCES_HASH = "492043660b1370e1910c8b8ca2b93be1f637f4929034f575591f14e67e015243"
BINARIES = {
    "turnip-26.0.0.so": ("51b968eed13c933d114cdc2956135758917e48451129f647ecb5ebbea5a527eb", 13841568),
    "vulkan-probe": ("e5d9f6f11b471415a981d2ae7aac3566ebe7f9d687409437b15fd89aacc69d8b", 68000),
}
SOURCE_ARCHIVES = {
    "mesa-26.0.0.tar.xz": "2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72",
    "glslang-15.1.0.tar.gz": "4bdcd8cdb330313f0d4deed7be527b0ac1c115ff272e492853a6e98add61b4bc",
}


def checked(data: bytes, digest: str, name: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"SHA-256 mismatch: {name}")
    return data


def download(name: str, digest: str, cache: Path) -> Path:
    path = cache / name
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return path
    request = urllib.request.Request(RELEASE + name, headers={"User-Agent": "EVE-Android-Graphics-Build/1"})
    temporary = path.with_suffix(path.suffix + ".new")
    with urllib.request.urlopen(request, timeout=180) as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target)
    checked(temporary.read_bytes(), digest, name)
    temporary.replace(path)
    return path


def file_by_suffix(archive: tarfile.TarFile, suffix: str) -> bytes:
    matches = [member for member in archive.getmembers()
               if member.isfile() and (member.name == suffix or member.name.endswith("/" + suffix))]
    if len(matches) != 1:
        raise ValueError(f"Expected one source member {suffix}, got {len(matches)}")
    stream = archive.extractfile(matches[0])
    assert stream is not None
    return stream.read()


def git(*arguments: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(["git", *arguments], cwd=cwd, text=True).strip()


def fetch_sources(source: Path, output: Path) -> None:
    source.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(parents=True, exist_ok=True)
    cache = output / "download-cache"
    cache.mkdir(parents=True, exist_ok=True)
    turnip_sources = source / "turnip-original-source"
    turnip_sources.mkdir(parents=True, exist_ok=True)
    bundle = download("runtime-bridges.zip", BUNDLE_HASH, cache)
    with zipfile.ZipFile(bundle) as archive:
        # Only these two immutable ELF files are selected from the larger ZIP.
        for name, (digest, size) in BINARIES.items():
            data = checked(archive.read("assets/" + name), digest, name)
            if len(data) != size:
                raise ValueError(f"Unexpected size: {name}")
            path = output / "assets" / name
            path.write_bytes(data)
            path.chmod(0o755 if name == "vulkan-probe" else 0o644)
        manifest = json.loads(archive.read("assets/vulkan-bundle.json"))
        for name, (digest, _) in BINARIES.items():
            if manifest.get("files", {}).get(name) != digest:
                raise ValueError(f"Original manifest disagrees: {name}")
    sources = download("runtime-corresponding-sources.tar.gz", SOURCES_HASH, cache)
    with tarfile.open(sources) as outer:
        nested = file_by_suffix(outer, "vulkan-sources.tar.gz")
        (turnip_sources / "ORIGINAL-THIRD-PARTY-NOTICES.md").write_bytes(
            file_by_suffix(outer, "THIRD_PARTY_NOTICES.md"))
    with tarfile.open(fileobj=io.BytesIO(nested), mode="r:gz") as original:
        for name, digest in SOURCE_ARCHIVES.items():
            (turnip_sources / name).write_bytes(checked(file_by_suffix(original, name), digest, name))
        # Retain the exact recipe and probe source accompanying the reused bytes.
        # The 24.3.4 Dockerfile compiled the retained Vulkan probe binary; the
        # 26.0.0 Dockerfile compiled only the selected Turnip driver.
        for name in ("vulkan/Dockerfile", "vulkan/Dockerfile.26", "vulkan/vulkan_probe.c", "build-vulkan.sh"):
            content = file_by_suffix(original, name)
            (turnip_sources / Path(name).name).write_bytes(content)
    checkout = source / "dxvk"
    git("init", str(checkout))
    git("remote", "add", "origin", "https://github.com/doitsujin/dxvk.git", cwd=checkout)
    git("fetch", "--depth", "1", "origin", DXVK_COMMIT, cwd=checkout)
    git("checkout", "--detach", "FETCH_HEAD", cwd=checkout)
    if git("rev-parse", "HEAD", cwd=checkout) != DXVK_COMMIT:
        raise ValueError("DXVK checkout mismatch")
    for path, commit in SUBMODULES.items():
        if git("ls-tree", "HEAD", path, cwd=checkout).split()[2] != commit:
            raise ValueError(f"Unexpected gitlink: {path}")
        git("submodule", "update", "--init", "--depth", "1", "--", path, cwd=checkout)
        if git("rev-parse", "HEAD", cwd=checkout / path) != commit:
            raise ValueError(f"Submodule checkout mismatch: {path}")
    provenance = {
        "runtime": "fex-arm64ec-1",
        "wineCommit": "a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29",
        "fexCommit": "320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab",
        "toolchain": "llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64",
        "toolchainSha256": "bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d",
        "dxvkVersion": "2.5.3", "dxvkCommit": DXVK_COMMIT, "submodules": SUBMODULES,
        "turnipVersion": "26.0.0", "mesaSourceSha256": SOURCE_ARCHIVES["mesa-26.0.0.tar.xz"],
        "turnipOriginalBinaryRelease": RELEASE, "turnipOriginalBundleSha256": BUNDLE_HASH,
        "turnipOriginalCorrespondingSourcesSha256": SOURCES_HASH,
        "licenses": {"dxvk": "Zlib", "mesa": "MIT and source component notices",
                     "vulkanProbe": "Original project probe source and accompanying notices retained"},
    }
    (source / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("Verified Turnip/probe bytes, exact corresponding source and native ARM64EC DXVK source.", flush=True)


def machine(data, kind):
    if kind == 'elf':
        if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
            raise ValueError('Expected little-endian ELF64')
        value, = struct.unpack_from('<H', data, 18)
        if value != 183:
            raise ValueError('Expected native AArch64 ELF')
        return value
    if data[:2] != b'MZ' or len(data) < 64:
        raise ValueError('Expected PE')
    offset, = struct.unpack_from('<I', data, 60)
    if offset + 26 > len(data) or data[offset:offset+4] != b'PE\0\0':
        raise ValueError('Truncated PE')
    value, = struct.unpack_from('<H', data, offset+4)
    magic, = struct.unpack_from('<H', data, offset+24)
    if value != 0x8664 or magic != 0x20b:
        raise ValueError('Expected final AMD64 PE32+')
    return value


def pe_diagnostics(data: bytes) -> dict:
    """Bounded build-only evidence when a linked image fails strict validation."""
    def read(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError('Truncated diagnostic field')
        return struct.unpack_from(fmt, data, offset)
    try:
        nt, = read('<I', 60)
        count, = read('<H', nt + 6)
        optional_size, = read('<H', nt + 20)
        optional = nt + 24
        image_base, = read('<Q', optional + 24)
        image_size, = read('<I', optional + 56)
        section_alignment, = read('<I', optional + 32)
        sections = []
        for index in range(min(count, 96)):
            entry = optional + optional_size + index * 40
            virtual_size, rva, raw_size, raw_start = read('<IIII', entry + 8)
            flags, = read('<I', entry + 36)
            sections.append({'name': data[entry:entry+8].split(b'\0')[0].decode('ascii', errors='replace'),
                             'rva': rva, 'virtualSize': virtual_size, 'rawSize': raw_size,
                             'rawStart': raw_start, 'flags': flags})
        def raw(rva, size):
            for section in sections:
                delta = rva - section['rva']
                if 0 <= delta <= section['rawSize'] and size <= section['rawSize'] - delta:
                    return section['rawStart'] + delta
            raise ValueError('Unmapped diagnostic RVA')
        config_rva, _ = read('<II', optional + 112 + 10 * 8)
        pointer, = read('<Q', raw(config_rva, 208) + 200)
        version, code_map_rva, ranges = read('<III', raw(pointer - image_base, 12))
        code_map = raw(code_map_rva, min(ranges, 16) * 8)
        entries = []
        for index in range(min(ranges, 16)):
            start, length = read('<II', code_map + index * 8)
            entries.append({'encodedStart': start, 'start': start & ~3,
                            'type': start & 3, 'length': length, 'end': (start & ~3) + length})
        return {'imageSize': image_size, 'sectionAlignment': section_alignment,
                'sections': sections, 'chpeVersion': version, 'codeMapRva': code_map_rva,
                'rangeCount': ranges, 'firstRanges': entries}
    except (ValueError, struct.error) as error:
        return {'diagnosticError': str(error)}


def make_manifest(assets):
    names = {
        'turnip-26.0.0.so': 'elf', 'vulkan-probe': 'elf',
        'dxvk-d3d11-arm64ec.dll': 'ec', 'dxvk-dxgi-arm64ec.dll': 'ec',
        'eve-d3d11-probe.exe': 'x64',
    }
    files = {}
    for name, kind in names.items():
        data = (assets / name).read_bytes()
        item = {'sha256': hashlib.sha256(data).hexdigest(), 'sizeBytes': len(data),
                'machine': machine(data, kind)}
        if kind == 'ec':
            try:
                item.update(arm64ec_metadata(data))
            except ValueError as error:
                print(json.dumps({'asset': name, 'validationError': str(error),
                                  'peDiagnostics': pe_diagnostics(data)}), flush=True)
                raise ValueError('Native EC validation failed: ' + name) from error
        elif kind == 'x64':
            try:
                arm64ec_metadata(data)
            except ValueError:
                pass
            else:
                raise ValueError('Probe EXE must execute x64 application code, not native EC')
        files[name] = item
    manifest = {
        'format': 1, 'bundle': 'eve-turnip-dxvk-1', 'runtime': 'fex-arm64ec-1',
        'wine_commit': 'a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29',
        'fex_commit': '320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab',
        'mesa': '26.0.0', 'dxvk': '2.5.3', 'dxvk_commit': 'c707d9026f33b6ab89639f154b6ac5f6326fa037',
        'architecture': 'arm64ec-and-arm64-glibc', 'kmd': 'kgsl', 'files': files,
        'baselineRuntimeSha256': 'f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e',
        'toolchain': {'name': 'llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64',
                      'sha256': 'bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d'},
        'sourceProvenance': {'dxvkRepository': 'https://github.com/doitsujin/dxvk',
                             'dxvkSubmodules': SUBMODULES,
                             'mesaSourceSha256': SOURCE_ARCHIVES['mesa-26.0.0.tar.xz'],
                             'glslangSourceSha256': SOURCE_ARCHIVES['glslang-15.1.0.tar.gz'],
                             'reusedRelease': RELEASE,
                             'reusedBundleSha256': BUNDLE_HASH,
                             'reusedCorrespondingSourcesSha256': SOURCES_HASH},
    }
    (assets / 'client-graphics-bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Validated native EC code ranges and all five packaged graphics files.', flush=True)


def runtime_identity(output):
    inherited = json.loads(Path('/source-provenance/wine-trust-overlay.json').read_text())
    if inherited['baselineRuntimeSha256'] != 'f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e':
        raise ValueError('Graphics builder did not inherit the qualified runtime archive')
    if inherited['wine_commit'] != 'a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29':
        raise ValueError('Graphics builder Wine source changed')
    folder = Path('/opt/wine')
    native = ['bin/wine', 'bin/wineserver', 'lib/wine/aarch64-unix/winevulkan.so']
    windows = ['lib/wine/aarch64-windows/winevulkan.dll',
               'lib/wine/aarch64-windows/ntdll.dll',
               'lib/wine/aarch64-windows/libarm64ecfex.dll',
               'lib/wine/aarch64-windows/libwow64fex.dll']
    files = {}
    for relative in native + windows:
        data = (folder / relative).read_bytes()
        if relative in native:
            if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
                raise ValueError('Fixture baseline is not native ARM64: ' + relative)
        files[relative] = {'sha256': hashlib.sha256(data).hexdigest(), 'sizeBytes': len(data)}
    # This is the baseline original, not the new trust overlay. The inherited
    # builder image is unmodified; the trust fixture only patched its container.
    crypt32 = (folder / 'lib/wine/aarch64-windows/crypt32.dll').read_bytes()
    if hashlib.sha256(crypt32).hexdigest() != 'b5f63e6d39d720d30a7ba124d1825a58d33a605d722b6e2b874c547c4d22b407':
        raise ValueError('The disposable graphics builder baseline was already modified')
    report = {'runtime': 'fex-arm64ec-1',
              'baselineRuntimeSha256': inherited['baselineRuntimeSha256'],
              'wine_commit': inherited['wine_commit'],
              'fex_commit': '320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab',
              'qualificationOnly': True, 'files': files}
    output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'fetch':
        fetch_sources(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'manifest':
        make_manifest(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'runtime-identity':
        runtime_identity(Path(sys.argv[2]))
    else:
        raise SystemExit('fetch-sources.py fetch SOURCE OUTPUT | manifest ASSETS | runtime-identity OUTPUT_JSON')
