"""Verify the APK's narrow crypt32 overlay against the pinned Wine build."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

WINE_COMMIT = "a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29"
OVERLAY = "wine-empty-subject-1"
TARGETS = {
    "opt/wine/lib/wine/aarch64-windows/crypt32.dll": ("wine-crypt32-aarch64.dll", {0xAA64}),
    "opt/wine/lib/wine/i386-windows/crypt32.dll": ("wine-crypt32-i386.dll", {0x014C}),
}
LIMIT = 16 * 1024 * 1024


def sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= LIMIT:
        raise ValueError("Missing, oversized or linked Wine trust module")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pe_machine(path: Path) -> int:
    with path.open("rb") as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("Wine trust module is not a PE binary")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset > LIMIT - 6:
            raise ValueError("Invalid Wine trust PE offset")
        source.seek(offset)
        header = source.read(6)
    if len(header) != 6 or header[:4] != b"PE\0\0":
        raise ValueError("Invalid Wine trust PE signature")
    return struct.unpack_from("<H", header, 4)[0]


def verify(manifest: Path, *, bound_root: Path | None = None) -> dict:
    if manifest.is_symlink() or manifest.stat().st_size > 65536:
        raise ValueError("Invalid Wine trust manifest")
    value = json.loads(manifest.read_text())
    if (value.get("format") != 1 or value.get("overlay") != OVERLAY
            or value.get("runtime") != "fex-arm64ec-1" or value.get("wine_commit") != WINE_COMMIT):
        raise ValueError("Wine trust overlay does not match the pinned runtime")
    files = value.get("files")
    if not isinstance(files, list) or len(files) != len(TARGETS):
        raise ValueError("Wine trust overlay must contain the pinned 64-bit and 32-bit modules")
    seen = set()
    for item in files:
        target = item.get("target")
        if target not in TARGETS or target in seen:
            raise ValueError("Invalid or duplicate Wine trust target")
        seen.add(target)
        asset, machines = TARGETS[target]
        if item.get("asset") != asset or item.get("machine") not in machines:
            raise ValueError("Wine trust architecture does not match its runtime path")
        for field in ("sha256", "baselineSha256"):
            digest = item.get(field, "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid Wine trust module checksum")
        source = manifest.parent / asset
        if sha256(source) != item["sha256"] or pe_machine(source) != item["machine"]:
            raise ValueError("APK Wine trust module checksum or architecture failed")
        if bound_root is not None:
            bound = bound_root / target
            if sha256(bound) != item["sha256"] or pe_machine(bound) != item["machine"]:
                raise ValueError("The client session did not bind the patched Wine trust module")
    return value
