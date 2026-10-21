#!/usr/bin/env python3
"""Install and select the separately packaged, pinned KGSL renderer.

No downloads happen in the contained guest. The APK supplies a generated,
hashed manifest and archive built from the official Mesa and DXVK releases.
The supervisor owns the Wine probe process and decides whether to use the
returned environment after its device/swapchain probe succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import tarfile
import tempfile
from typing import Any

import client_prepare


RUNTIME = "dxvk-turnip-1"
MAX_ARCHIVE = 64 * 1024**2
MAX_UNPACKED = 128 * 1024**2
SOURCE_PINS = {
    "mesa": {"version": "25.2.8", "url": "https://archive.mesa3d.org/mesa-25.2.8.tar.xz",
             "sha256": "097842f3e49d996868b38688db87b006f7d4541e93ce86d2f341d8b3e7be7c93"},
    "dxvk": {"version": "2.7.1", "url": "https://github.com/doitsujin/dxvk/releases/download/v2.7.1/dxvk-2.7.1.tar.gz",
             "sha256": "d85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87",
             "sourceUrl": "https://github.com/doitsujin/dxvk/archive/refs/tags/v2.7.1.tar.gz",
             "sourceSha256": "4966be884da4a1ded7e38ee018caef5626bd06bbd0853715084b1a1644aaaf02"},
}
REQUIRED_FILES = {"lib/libvulkan_freedreno.so", "turnip_icd.json", "dxvk/d3d11.dll", "dxvk/dxgi.dll"}
SOFTWARE_VARIABLES = ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "LP_NUM_THREADS")


class RendererUnavailable(ValueError):
    """A recoverable opt-in renderer failure; use the WineD3D profile."""


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked_path(root: Path, relative: str, *, allow_leaf_link: bool = False) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in (".", "..") for p in parts.parts) or "\\" in relative:
        raise RendererUnavailable("Invalid renderer package path")
    result = root.joinpath(*parts.parts)
    cursor = result.parent if allow_leaf_link else result
    while cursor != root:
        if cursor.is_symlink():
            raise RendererUnavailable("Renderer package path contains a symbolic link")
        cursor = cursor.parent
    return result


def manifest_files(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (manifest.get("format"), manifest.get("runtime"), manifest.get("architecture")) != (1, RUNTIME, "arm64"):
        raise RendererUnavailable("Unsupported renderer package identity")
    if manifest.get("components") != SOURCE_PINS or manifest.get("file") != "renderer-runtime.tar.gz":
        raise RendererUnavailable("Renderer source release pins do not match this launcher")
    size = manifest.get("sizeBytes")
    if type(size) is not int or not 1 <= size <= MAX_ARCHIVE:
        raise RendererUnavailable("Renderer archive exceeds its size limit")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not 4 <= len(rows) <= 128:
        raise RendererUnavailable("Invalid renderer package file list")
    files: dict[str, dict[str, Any]] = {}
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise RendererUnavailable("Invalid renderer package file")
        path, size, sha = row.get("path"), row.get("sizeBytes"), row.get("sha256")
        if not isinstance(path, str) or path in files or type(size) is not int or size <= 0:
            raise RendererUnavailable("Invalid or duplicate renderer package file")
        checked_path(Path("/renderer"), path)
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise RendererUnavailable("Invalid renderer file checksum")
        total += size
        if total > MAX_UNPACKED:
            raise RendererUnavailable("Renderer package exceeds its unpacked limit")
        files[path] = row
    if not REQUIRED_FILES.issubset(files) or total != manifest.get("unpackedBytes"):
        raise RendererUnavailable("Incomplete renderer package")
    return files


def validate_binary(path: Path, machine: int, *, pe: bool = False) -> None:
    with path.open("rb") as source:
        header = source.read(64)
        if pe:
            if len(header) != 64 or header[:2] != b"MZ":
                raise RendererUnavailable("Renderer DLL is not a Windows binary")
            offset = struct.unpack_from("<I", header, 60)[0]
            if offset > 1024 * 1024:
                raise RendererUnavailable("Renderer DLL has an invalid PE header")
            source.seek(offset)
            header = source.read(6)
            if len(header) != 6 or header[:4] != b"PE\0\0" or struct.unpack_from("<H", header, 4)[0] != machine:
                raise RendererUnavailable("Renderer DLL has the wrong architecture")
        elif len(header) < 20 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != machine:
            raise RendererUnavailable("Turnip must be a native ARM64 Linux library")


def install(assets: Path, state: Path) -> tuple[Path, dict[str, Any]]:
    manifest = json.loads(client_prepare.bounded_text(assets / "renderer-manifest.json", limit=128 * 1024))
    if not isinstance(manifest, dict):
        raise RendererUnavailable("Invalid renderer manifest")
    files = manifest_files(manifest)
    archive = checked_path(assets, "renderer-runtime.tar.gz")
    if archive.stat().st_size != manifest["sizeBytes"] or digest(archive) != manifest.get("sha256"):
        raise RendererUnavailable("Packaged renderer archive checksum failed")
    # Content-addressed installation never replaces an active library. The
    # supervisor's existing exclusive session lock serializes all callers.
    state = state.resolve()
    parent = checked_path(state, "renderers")
    parent.mkdir(parents=True, exist_ok=True)
    root = checked_path(parent, manifest["sha256"])
    intact = root.is_dir() and all(
        (path := checked_path(root, name)).is_file() and path.stat().st_size == row["sizeBytes"]
        and digest(path) == row["sha256"] for name, row in files.items())
    if not intact:
        if root.exists():
            shutil.rmtree(root)
        stage = Path(tempfile.mkdtemp(prefix="incoming-", dir=parent))
        try:
            seen: set[str] = set()
            with tarfile.open(archive, "r:gz") as source:
                for member in source:
                    if member.isdir():
                        checked_path(stage, member.name)
                        continue
                    if not member.isfile() or member.name not in files or member.name in seen:
                        raise RendererUnavailable("Unexpected renderer archive entry")
                    row = files[member.name]
                    if member.size != row["sizeBytes"]:
                        raise RendererUnavailable("Renderer member size mismatch")
                    target = checked_path(stage, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = source.extractfile(member)
                    if extracted is None:
                        raise RendererUnavailable("Missing renderer archive data")
                    with extracted, target.open("xb") as output:
                        shutil.copyfileobj(extracted, output, length=1024 * 1024)
                    if digest(target) != row["sha256"]:
                        raise RendererUnavailable("Renderer member checksum failed")
                    target.chmod(0o644)
                    seen.add(member.name)
            if seen != set(files):
                raise RendererUnavailable("Renderer archive is incomplete")
            stage.rename(root)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    validate_binary(root / "lib/libvulkan_freedreno.so", 183)
    for name in ("d3d11", "dxgi"):
        validate_binary(root / ("dxvk/" + name + ".dll"), 0x8664, pe=True)
    icd = json.loads(client_prepare.bounded_text(root / "turnip_icd.json", limit=4096))
    if icd.get("ICD", {}).get("library_path") != "lib/libvulkan_freedreno.so":
        raise RendererUnavailable("Turnip ICD must refer only to the packaged library")
    return root, manifest


@dataclass(frozen=True)
class PreparedRenderer:
    env: dict[str, str]
    report: dict[str, Any]
    probe: Path

    def probe_command(self, wine: str) -> tuple[str, ...]:
        return (wine, str(self.probe))


def prepare(state: Path, prefix: Path, assets: Path = Path("/opt/eve-android"),
            kgsl: Path = Path("/dev/kgsl-3d0")) -> PreparedRenderer:
    """Stage an opt-in GPU renderer, or raise a recoverable fallback reason."""
    try:
        if not stat.S_ISCHR(kgsl.stat().st_mode) or not os.access(kgsl, os.R_OK | os.W_OK):
            raise RendererUnavailable("Android KGSL device is not readable/writable through the existing /dev bind")
        root, manifest = install(assets, state)
        probe = checked_path(assets, "eve-renderer-probe.exe")
        validate_binary(probe, 0x8664, pe=True)
        state_root = state.resolve()
        try:
            relative_prefix = prefix.absolute().relative_to(state_root).as_posix()
        except ValueError as error:
            raise RendererUnavailable("Wine prefix must remain inside private client state") from error
        checked_prefix = checked_path(state_root, relative_prefix)
        system = checked_path(checked_prefix, "drive_c/windows/system32")
        if not system.is_dir():
            raise RendererUnavailable("Wine prefix system32 is missing")
        for name in ("d3d11.dll", "dxgi.dll"):
            target = checked_path(system, name, allow_leaf_link=True)
            # Wine's builtin symlink may be replaced; never write through it
            # into the immutable Wine installation. Builtin fallback uses =b.
            with tempfile.NamedTemporaryFile(prefix="eve-dxvk-", dir=system, delete=False) as output:
                incoming = Path(output.name)
                try:
                    with (root / "dxvk" / name).open("rb") as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                    incoming.chmod(0o644)
                    os.replace(incoming, target)
                finally:
                    incoming.unlink(missing_ok=True)
        return PreparedRenderer(
            env={"WINEDLLOVERRIDES": "winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n",
                 "VK_ICD_FILENAMES": str(root / "turnip_icd.json"),
                 "VK_DRIVER_FILES": str(root / "turnip_icd.json"),
                 "MESA_VK_WSI_DEBUG": "sw", "DXVK_LOG_LEVEL": "info",
                 # DXVK still uses Wine's console channel, which the
                 # supervisor rotates. Avoid an unbounded second file log.
                 "DXVK_LOG_PATH": "none"},
            report={"requested": "dxvk-turnip", "active": "dxvk-turnip", "runtime": RUNTIME,
                    "packageSha256": manifest["sha256"], "components": SOURCE_PINS,
                    "kgslReachable": True, "presentation": "x11-software-swapchain-vnc",
                    "deviceProbePassed": False}, probe=probe)
    except RendererUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError) as error:
        raise RendererUnavailable("DXVK/Turnip unavailable: " + str(error)) from error
