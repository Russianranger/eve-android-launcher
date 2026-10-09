#!/usr/bin/env python3
"""Build native DXVK and reuse only the verified immutable Turnip components.

Every downloaded executable byte is SHA-256 checked before use. Source archives
contain only the graphics components shipped, their exact original source and
the new build recipe. No TRASC Wine/D3D9/game patch bytes are deployed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from pe_image import arm64ec_metadata


DXVK_COMMIT = "0cf05780abd7250c2cd713b7749cf32180157cf5"
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
A740_EXPERIMENT = {
    "format": 1, "name": "turnip-a740-pc-mode-1",
    "driver": "turnip-26.0.0-a740-pc-mode.so", "identityProbe": "a740-driver-probe",
    "mesaSourceSha256": SOURCE_ARCHIVES["mesa-26.0.0.tar.xz"],
    "upstreamCommit": "23f94c692cb1d41a2193a80fa531922d386e8d5d",
    "patchSha256": "1bb91daddcdbf264ee05337ef2fa4eebd544c9c3a1425810af73adf298e17b12",
    "probeSourceSha256": "8bd8d2faf2e959baad024be4d0e185942a92584d5f04b91de287d4f1527e4371",
    "sourceFileSha256": "25206d1bae7e650e7266b50e107d6656e69cb640aadcb0c8e50e900241df3d09",
    "patchedSourceFileSha256": "a59ac4f80c0109ebffa7cd766bf91661ced97bdae35771af084ce6e73831bfdc",
    "deviceId": 0x43050a01, "registerOffset": 0x9804, "originalValue": 0x3f, "value": 0x1f1f,
}
SHM_EXPERIMENT = {
    "format": 1, "name": "turnip-x11-shm-staging-1",
    "driver": "turnip-26.0.0-x11-shm.so",
    "mesaSourceSha256": SOURCE_ARCHIVES["mesa-26.0.0.tar.xz"],
    "patchSha256": "3ec5f29a7bee6328b824cc98a47228b9fc5ec63751d7e5d005703e999f0bc83c",
    "transportSourceSha256": "0966fed8c6bd81326876b11c3d9640eb8daca01c6ae8417b46956ac259a0fa25",
    "probeSourceSha256": "841cf72ac761d6d3dfc8316d0d8ade103a876ad1a0eb463f3018ef399fa5833e",
    "sourceFileSha256": "92831b74c892f1795c489fc14f1c05afa362ad857b4959e1e28c13932cba52e5",
    "patchedSourceFileSha256": "18281444fd6639f4a6a672d543685f99ba282cdba25ba204e0c5a52062cc74fd",
}
MESA262_SOURCE_NAME = "mesa-26.2.4.tar.xz"
MESA262_SOURCE_URL = "https://archive.mesa3d.org/" + MESA262_SOURCE_NAME
MESA262_EXPERIMENT = {
    "format": 1, "name": "turnip-mesa-26.2.4-1", "driver": "turnip-26.2.4.so",
    "identityProbe": "mesa262-driver-probe", "mesa": "26.2.4",
    "mesaSourceSha256": "bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9",
    "probeSourceSha256": "bb96b8e0721e167d20d8b15e433d180b79447b0bdb8f85dfaa614aa867c09d37",
    "deviceId": 0x43050a01, "pristine": True,
}


def checked(data: bytes, digest: str, name: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"SHA-256 mismatch: {name}")
    return data


def download(name: str, digest: str, cache: Path, url: str | None = None) -> Path:
    path = cache / name
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return path
    request = urllib.request.Request(url or RELEASE + name, headers={"User-Agent": "EVE-Android-Graphics-Build/1"})
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


def prepare_a740_sources(source: Path, recipe: Path) -> None:
    """Apply one checksum-locked A740 table change to the exact baseline source."""
    original = source / "turnip-original-source"
    for name, checksum in SOURCE_ARCHIVES.items():
        checked((original / name).read_bytes(), checksum, name)
    patch = recipe / "a740-pc-mode.patch"
    probe = recipe / "a740-driver-probe.c"
    checked(patch.read_bytes(), A740_EXPERIMENT["patchSha256"], patch.name)
    checked(probe.read_bytes(), A740_EXPERIMENT["probeSourceSha256"], probe.name)
    mesa = source / "mesa-a740"
    glslang = source / "glslang-a740"
    mesa.mkdir()
    glslang.mkdir()
    # These are the immutable, verified upstream source archives, never user
    # uploads. The applied file itself is checked both before and after patching.
    subprocess.run(["tar", "--no-same-owner", "--no-same-permissions", "-xf",
                    str(original / "mesa-26.0.0.tar.xz"), "-C", str(mesa)], check=True)
    subprocess.run(["tar", "--no-same-owner", "--no-same-permissions", "-xf",
                    str(original / "glslang-15.1.0.tar.gz"), "-C", str(glslang)], check=True)
    checkout = mesa / "mesa-26.0.0"
    changed = checkout / "src/freedreno/common/freedreno_devices.py"
    before = checked(changed.read_bytes(), A740_EXPERIMENT["sourceFileSha256"], changed.name)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=checkout, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=checkout, check=True)
    after = checked(changed.read_bytes(), A740_EXPERIMENT["patchedSourceFileSha256"], changed.name)
    start = before.index(b"a740_raw_magic_regs = [")
    end = before.index(b"\nadd_gpus(", start)
    expected = before[:start] + before[start:end].replace(
        b"[A6XXRegs.REG_A6XX_PC_MODE_CNTL,    0x0000003f]",
        b"[A6XXRegs.REG_A6XX_PC_MODE_CNTL,    0x1f1f]", 1) + before[end:]
    if before == after or after != expected:
        raise ValueError("A740 backport differs from the single selected register change")
    (source / "a740-pc-mode-experiment.json").write_text(json.dumps(A740_EXPERIMENT, indent=2) + "\n")


def prepare_shm_sources(source: Path, recipe: Path) -> None:
    """Patch only X11 software presentation in an independent pristine Mesa tree."""
    archive = source / "turnip-original-source/mesa-26.0.0.tar.xz"
    checked(archive.read_bytes(), SHM_EXPERIMENT["mesaSourceSha256"], archive.name)
    patch = recipe / "x11-shm-staging.patch"
    transport = recipe / "eve-x11-shm-staging.h"
    probe = recipe / "eve-x11-shm-probe.c"
    checked(patch.read_bytes(), SHM_EXPERIMENT["patchSha256"], patch.name)
    checked(transport.read_bytes(), SHM_EXPERIMENT["transportSourceSha256"], transport.name)
    checked(probe.read_bytes(), SHM_EXPERIMENT["probeSourceSha256"], probe.name)
    mesa = source / "mesa-shm"
    mesa.mkdir()
    subprocess.run(["tar", "--no-same-owner", "--no-same-permissions", "-xf",
                    str(archive), "-C", str(mesa)], check=True)
    checkout = mesa / "mesa-26.0.0"
    changed = checkout / "src/vulkan/wsi/wsi_common_x11.c"
    checked(changed.read_bytes(), SHM_EXPERIMENT["sourceFileSha256"], changed.name)
    changes = subprocess.check_output(
        ["git", "apply", "--numstat", str(patch)], cwd=checkout, text=True)
    if len(changes.splitlines()) != 1 or changes.split("\t")[-1].strip() != "src/vulkan/wsi/wsi_common_x11.c":
        raise ValueError("SHM experiment must change only the selected X11 WSI source")
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=checkout, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=checkout, check=True)
    checked(changed.read_bytes(), SHM_EXPERIMENT["patchedSourceFileSha256"], changed.name)
    # The standalone fixture compiles this identical header. It is not a second
    # implementation of the transport and remains in corresponding sources.
    shutil.copyfile(transport, changed.parent / transport.name)
    (source / "x11-shm-presentation-experiment.json").write_text(
        json.dumps(SHM_EXPERIMENT, indent=2) + "\n")


def write_mesa262_notices(checkout: Path, output: Path) -> dict:
    """Inventory upstream license text and complete source notice comments."""
    license_document = checkout / "docs/license.rst"
    license_files = sorted(path for path in (checkout / "licenses").rglob("*") if path.is_file())
    if not license_document.is_file() or not license_files:
        raise ValueError("Pinned Mesa 26.2.4 source is missing its upstream license inventory")
    header = (
        "Mesa 26.2.4 upstream license and copyright notices\n\n"
        "Extracted from the unchanged official Mesa 26.2.4 source archive\n"
        "(SHA-256 " + MESA262_EXPERIMENT["mesaSourceSha256"] + ").\n"
        "This inventory covers the complete source distribution and is broader\n"
        "than the selected Turnip binary. Individual source licenses apply.\n"
        "The exact archive, extracted source and build recipe accompany the APK\n"
        "in client-graphics-corresponding-source.tar.gz.\n\n")
    full_documents = {license_document, *license_files}
    notices: dict[bytes, list[str]] = {}
    # Preserve complete comment bytes, including each full permissive license,
    # rather than keeping only a copyright/SPDX line from a longer notice.
    comments = re.compile(rb"/\*.*?\*/|<!--.*?-->|(?:(?m:^[ \t]*(?:\#|//|;)[^\n]*(?:\n|$)))+", re.DOTALL)
    legal = re.compile(rb"copyright|spdx-license-identifier|permission is hereby|redistribution and use|gnu (?:general|lesser general) public", re.IGNORECASE)
    for path in sorted(checkout.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(checkout).as_posix()
        if re.search(r"(?:license|copying|copyright|notice)", path.name, re.IGNORECASE):
            full_documents.add(path)
        if path in full_documents:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for match in comments.finditer(data):
            notice = match.group()
            if legal.search(notice):
                origins = notices.setdefault(notice, [])
                if relative not in origins:
                    origins.append(relative)
    if not any(any(path.startswith("src/freedreno/") for path in paths) for paths in notices.values()):
        raise ValueError("Mesa 26.2.4 notices omit the selected Freedreno source copyright headers")
    parts = [header.encode("utf-8")]
    for path in sorted(full_documents):
        relative = path.relative_to(checkout).as_posix()
        parts.append(("\n===== " + relative + " =====\n\n").encode("utf-8"))
        parts.append(path.read_bytes())
        parts.append(b"\n")
    for notice, paths in notices.items():
        parts.append(("\n===== Source notice: " + ", ".join(paths) + " =====\n\n").encode("utf-8"))
        parts.extend((notice, b"\n"))
    data = b"".join(parts)
    path = output / "mesa-26.2.4-notices.txt"
    path.write_bytes(data)
    return {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data),
            "sourceArchiveSha256": MESA262_EXPERIMENT["mesaSourceSha256"],
            "upstreamLicenseDocuments": len(full_documents), "uniqueSourceNoticeComments": len(notices)}


def prepare_mesa262_sources(source: Path, recipe: Path, cache: Path, output: Path) -> dict:
    """Retain and extract the checksum-pinned upstream release without patches."""
    probe = recipe / "mesa262-driver-probe.c"
    checked(probe.read_bytes(), MESA262_EXPERIMENT["probeSourceSha256"], probe.name)
    archive = download(MESA262_SOURCE_NAME, MESA262_EXPERIMENT["mesaSourceSha256"],
                       cache, MESA262_SOURCE_URL)
    original = source / "mesa262-original-source"
    original.mkdir()
    shutil.copyfile(archive, original / MESA262_SOURCE_NAME)
    mesa = source / "mesa262"
    mesa.mkdir()
    subprocess.run(["tar", "--no-same-owner", "--no-same-permissions", "-xf",
                    str(archive), "-C", str(mesa)], check=True)
    checkout = mesa / "mesa-26.2.4"
    if (checkout / "VERSION").read_text().strip() != "26.2.4":
        raise ValueError("Optional Mesa release version does not match its pinned archive")
    (source / "mesa262-driver-experiment.json").write_text(
        json.dumps(MESA262_EXPERIMENT, indent=2) + "\n")
    notices = write_mesa262_notices(checkout, output)
    shutil.copyfile(output / notices["file"], original / notices["file"])
    notices_provenance = json.dumps(notices, indent=2) + "\n"
    (source / "mesa262-notices-provenance.json").write_text(notices_provenance)
    (output / "mesa262-notices-provenance.json").write_text(notices_provenance)
    return notices


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
    prepare_a740_sources(source, Path("/graphics-recipe"))
    prepare_shm_sources(source, Path("/graphics-recipe"))
    mesa262_notices = prepare_mesa262_sources(source, Path("/graphics-recipe"), cache, output)
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
        "dxvkVersion": "2.4.1", "dxvkCommit": DXVK_COMMIT, "submodules": SUBMODULES,
        "turnipVersion": "26.0.0", "mesaSourceSha256": SOURCE_ARCHIVES["mesa-26.0.0.tar.xz"],
        "turnipOriginalBinaryRelease": RELEASE, "turnipOriginalBundleSha256": BUNDLE_HASH,
        "turnipOriginalCorrespondingSourcesSha256": SOURCES_HASH,
        "a740PcModeExperiment": A740_EXPERIMENT,
        "shmPresentationExperiment": SHM_EXPERIMENT,
        "mesa262DriverExperiment": MESA262_EXPERIMENT,
        "mesa262SourceUrl": MESA262_SOURCE_URL,
        "mesa262Notices": mesa262_notices,
        "licenses": {"dxvk": "Zlib", "mesa": "MIT and source component notices",
                     "vulkanProbe": "Original project probe source and accompanying notices retained"},
    }
    (source / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("Verified original Turnip/probe bytes, pristine Mesa 26.2.4, corresponding sources and native ARM64EC DXVK source.", flush=True)


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


def native_link_requirements(path: Path) -> dict:
    """Read the actual ELF dynamic requirements, not its filename or ldd guess."""
    dynamic = subprocess.check_output(["readelf", "--dynamic", str(path)], text=True)
    versions = subprocess.check_output(["readelf", "--version-info", str(path)], text=True)
    needed = sorted(set(re.findall(r"\(NEEDED\).*Shared library: \[([^]]+)\]", dynamic)))
    requirements = {}
    # These libraries carry the Debian/glibc runtime ABI. The graphics driver
    # is rebuilt with the baseline's bookworm compiler/build flags.
    for family in ("GLIBC", "GLIBCXX", "CXXABI"):
        values = [tuple(map(int, value.split(".")))
                  for value in re.findall(r"Name: " + family + r"_([0-9.]+)\b", versions)]
        if values:
            requirements[family] = max(values)
    return {"needed": needed, "versionRequirements": requirements}


def verify_a740_link_compatibility(assets: Path) -> dict:
    """Reject new SONAME/ABI requirements beyond the accepted native components."""
    pairs = (("turnip-26.0.0.so", A740_EXPERIMENT["driver"]),
             ("vulkan-probe", A740_EXPERIMENT["identityProbe"]))
    report = {}
    for original, variant in pairs:
        baseline = native_link_requirements(assets / original)
        selected = native_link_requirements(assets / variant)
        if not set(selected["needed"]).issubset(baseline["needed"]):
            raise ValueError("Optional A740 native component adds a dynamic library requirement: " + variant)
        for family, version in selected["versionRequirements"].items():
            if version > baseline["versionRequirements"].get(family, (0,)):
                raise ValueError("Optional A740 native component requires a newer runtime ABI: " + variant + " " + family)
        linked = subprocess.check_output(["ldd", str(assets / variant)], text=True, stderr=subprocess.STDOUT)
        if "not found" in linked:
            raise ValueError("Optional A740 native component has unresolved runtime dependencies: " + variant)
        report[variant] = {"baseline": original, "requirements": selected,
                           "newDynamicDependencies": False, "newRuntimeAbiRequired": False}
    return report


def verify_shm_link_compatibility(assets: Path) -> dict:
    """The presentation-only candidate must retain the baseline native ABI."""
    original = "turnip-26.0.0.so"
    variant = SHM_EXPERIMENT["driver"]
    baseline = native_link_requirements(assets / original)
    selected = native_link_requirements(assets / variant)
    if not set(selected["needed"]).issubset(baseline["needed"]):
        raise ValueError("Optional SHM driver adds a dynamic library requirement")
    for family, version in selected["versionRequirements"].items():
        if version > baseline["versionRequirements"].get(family, (0,)):
            raise ValueError("Optional SHM driver requires a newer runtime ABI: " + family)
    linked = subprocess.check_output(["ldd", str(assets / variant)], text=True, stderr=subprocess.STDOUT)
    if "not found" in linked:
        raise ValueError("Optional SHM driver has unresolved runtime dependencies")
    return {variant: {"baseline": original, "requirements": selected,
                      "newDynamicDependencies": False, "newRuntimeAbiRequired": False}}


def verify_mesa262_link_compatibility(assets: Path) -> dict:
    """The separate release candidate must load in the existing glibc runtime."""
    pairs = (("turnip-26.0.0.so", MESA262_EXPERIMENT["driver"]),
             ("vulkan-probe", MESA262_EXPERIMENT["identityProbe"]))
    report = {}
    for original, variant in pairs:
        baseline = native_link_requirements(assets / original)
        selected = native_link_requirements(assets / variant)
        added = sorted(set(selected["needed"]) - set(baseline["needed"]))
        runtime_proof = None
        if added:
            # Only the new driver's upstream XCB-SHM import may extend the
            # original ELF's NEEDED list, after checking the exact unchanged
            # runtime archive. The native probe still has a strict subset gate.
            if variant != MESA262_EXPERIMENT["driver"] or added != ["libxcb-shm.so.0"]:
                raise ValueError("Optional Mesa 26.2.4 component adds unapproved dynamic libraries: "
                                 + variant + " " + repr(added))
            helper_path = Path(__file__).with_name("check-mesa262-runtime-libraries.py")
            spec = importlib.util.spec_from_file_location("mesa262_runtime_libraries", helper_path)
            if spec is None or spec.loader is None:
                raise ValueError("Pinned runtime ELF proof helper is missing")
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            runtime_proof = helper.validate_candidate(assets / variant, Path("/runtime-proof/mesa262-xcb-shm"))
        for family, version in selected["versionRequirements"].items():
            if version > baseline["versionRequirements"].get(family, (0,)):
                raise ValueError("Optional Mesa 26.2.4 component requires a newer runtime ABI: " + variant + " " + family)
        linked = subprocess.check_output(["ldd", str(assets / variant)], text=True, stderr=subprocess.STDOUT)
        if "not found" in linked:
            raise ValueError("Optional Mesa 26.2.4 component has unresolved runtime dependencies: " + variant)
        report[variant] = {"baseline": original, "requirements": selected, "newRuntimeAbiRequired": False}
        if variant == MESA262_EXPERIMENT["driver"]:
            report[variant]["addedDynamicDependencies"] = added
        else:
            report[variant]["newDynamicDependencies"] = False
        if runtime_proof is not None:
            report[variant]["pinnedRuntimeDependencyProof"] = runtime_proof
    symbols = subprocess.check_output([
        "readelf", "--dyn-syms", "--wide", str(assets / MESA262_EXPERIMENT["driver"])], text=True)
    # Only a defined, externally visible dynamic function can be called by the
    # Vulkan loader. A filename, string marker or undefined import is no proof.
    exported = False
    for line in symbols.splitlines():
        fields = line.split()
        if (len(fields) >= 8 and fields[3:6] == ["FUNC", "GLOBAL", "DEFAULT"]
                and fields[6] != "UND"
                and fields[7].split("@", 1)[0] == "vk_icdGetInstanceProcAddr"):
            exported = True
            break
    if not exported:
        raise ValueError("Optional Mesa 26.2.4 ELF does not export the Vulkan ICD entry point")
    report[MESA262_EXPERIMENT["driver"]]["icdEntryPoint"] = "vk_icdGetInstanceProcAddr"
    return report


def make_manifest(assets):
    names = {
        'turnip-26.0.0.so': 'elf', 'vulkan-probe': 'elf',
        'turnip-26.0.0-a740-pc-mode.so': 'elf', 'a740-driver-probe': 'elf',
        'turnip-26.0.0-x11-shm.so': 'elf',
        'turnip-26.2.4.so': 'elf', 'mesa262-driver-probe': 'elf',
        'dxvk-d3d11-arm64ec.dll': 'ec', 'dxvk-dxgi-arm64ec.dll': 'ec',
        'eve-d3d11-probe.exe': 'x64',
    }
    compatibility = verify_a740_link_compatibility(assets)
    (assets.parent / 'a740-link-compatibility.json').write_text(json.dumps(compatibility, indent=2) + '\n')
    (assets.parent / 'shm-link-compatibility.json').write_text(
        json.dumps(verify_shm_link_compatibility(assets), indent=2) + '\n')
    (assets.parent / 'mesa262-link-compatibility.json').write_text(
        json.dumps(verify_mesa262_link_compatibility(assets), indent=2) + '\n')
    candidate = (assets / SHM_EXPERIMENT['driver']).read_bytes()
    for marker in (b'EVE_X11_SHM_STAGING', b'EVE_X11_SHM {', b'eve-x11-shm-1'):
        if marker not in candidate:
            raise ValueError('Optional SHM driver lacks its compiled transport marker')
    mesa262 = (assets / MESA262_EXPERIMENT['driver']).read_bytes()
    if b'Mesa 26.2.4' not in mesa262:
        raise ValueError('Optional Mesa driver lacks its exact compiled release identity')
    for marker in (b'EVE_X11_SHM_STAGING', b'EVE_X11_SHM {', b'eve-x11-shm-1'):
        if marker in mesa262:
            raise ValueError('Pristine Mesa 26.2.4 driver unexpectedly contains the local SHM transport')
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
        'format': 1, 'bundle': 'eve-turnip-dxvk-2', 'runtime': 'fex-arm64ec-1',
        'wine_commit': 'a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29',
        'fex_commit': '320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab',
        'mesa': '26.0.0', 'dxvk': '2.4.1', 'dxvk_commit': DXVK_COMMIT,
        'architecture': 'arm64ec-and-arm64-glibc', 'kmd': 'kgsl', 'files': files,
        'a740PcModeExperiment': A740_EXPERIMENT,
        'shmPresentationExperiment': SHM_EXPERIMENT,
        'mesa262DriverExperiment': MESA262_EXPERIMENT,
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
    print('Validated native EC code ranges, original graphics bytes and optional A740/SHM/Mesa 26.2.4 drivers.', flush=True)


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
