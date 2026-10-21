#!/usr/bin/env python3
"""Check that the built ARM64 launcher includes its actual runtime entrypoints."""
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path


def check_renderer(archive: zipfile.ZipFile) -> None:
    # Verify the bytes AssetManager will return, not just a matching filename.
    if archive.getinfo("assets/renderer-manifest.json").file_size > 128 * 1024:
        raise ValueError("Renderer manifest exceeds its size bound")
    manifest = json.loads(archive.read("assets/renderer-manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("file") != "renderer-runtime.tar.gz":
        raise ValueError("Unexpected renderer manifest filename")
    info = archive.getinfo("assets/renderer-runtime.bin")
    if not 1 <= info.file_size <= 64 * 1024**2 or info.file_size != manifest.get("sizeBytes"):
        raise ValueError("Renderer payload size mismatch")
    payload = archive.read(info)
    if payload[:3] != b"\x1f\x8b\x08" or hashlib.sha256(payload).hexdigest() != manifest.get("sha256"):
        raise ValueError("APK changed the hashed renderer gzip payload")


def check(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        check_renderer(archive)
        required = (
            "lib/arm64-v8a/libproot.so", "lib/arm64-v8a/libproot-loader.so",
            "assets/server_runtime.py", "assets/client_prepare.py", "assets/client_probe.sh",
            "assets/client_runtime.py", "assets/client_performance.py", "assets/eve-client-gate.exe",
            "assets/client_renderer.py", "assets/eve-renderer-probe.exe",
            "assets/renderer-runtime.bin", "assets/renderer-manifest.json",
        )
        for name in required:
            data = archive.read(name)
            if not data:
                raise ValueError(f"Empty APK entry: {name}")
            if name.startswith("lib/"):
                if data[:5] != b"\x7fELF\x02" or struct.unpack_from("<H", data, 18)[0] != 183:
                    raise ValueError(f"Expected a 64-bit ARM ELF: {name}")
            if name.endswith(("eve-client-gate.exe", "eve-renderer-probe.exe")):
                if data[:2] != b"MZ" or len(data) < 64:
                    raise ValueError("Missing Windows helper")
                offset = struct.unpack_from("<I", data, 60)[0]
                if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
                    raise ValueError("Expected an x64 Wine helper")
            if name.endswith("libproot.so") and b"--eve-client-network" not in data:
                raise ValueError("PRoot is missing the client loopback network policy")
            if name.endswith("libproot.so") and (b"--eve-client-network-fast-sendto" not in data or b"--eve-client-network-stats" not in data):
                raise ValueError("PRoot is missing selectable connected-send acceleration/telemetry")
        other_abis = [name for name in archive.namelist()
                      if name.startswith("lib/") and not name.startswith("lib/arm64-v8a/")]
        if other_abis:
            raise ValueError(f"Unexpected native ABI entries: {other_abis}")
    print(f"Verified ARM64 runtime and server/client backend assets: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    check(parser.parse_args().apk)
