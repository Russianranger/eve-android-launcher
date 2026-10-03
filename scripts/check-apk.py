#!/usr/bin/env python3
"""Check that the built ARM64 launcher includes its actual runtime entrypoints."""
import argparse
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import wine_trust_overlay


def check(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        required = (
            "lib/arm64-v8a/libproot.so", "lib/arm64-v8a/libproot-loader.so",
            "assets/server_runtime.py", "assets/client_prepare.py", "assets/client_probe.sh",
            "assets/client_runtime.py", "assets/eve-client-gate.exe",
            "assets/wine_trust_overlay.py", "assets/wine-trust-overlay.json",
            "assets/wine-crypt32-aarch64.dll", "assets/wine-crypt32-i386.dll",
        )
        for name in required:
            data = archive.read(name)
            if not data:
                raise ValueError(f"Empty APK entry: {name}")
            if name.startswith("lib/"):
                if data[:5] != b"\x7fELF\x02" or struct.unpack_from("<H", data, 18)[0] != 183:
                    raise ValueError(f"Expected a 64-bit ARM ELF: {name}")
            if name.endswith("eve-client-gate.exe"):
                if data[:2] != b"MZ" or len(data) < 64:
                    raise ValueError("Missing Windows certificate helper")
                offset = struct.unpack_from("<I", data, 60)[0]
                if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
                    raise ValueError("Expected the x64 Wine certificate helper")
            if name.endswith("libproot.so") and b"--eve-client-network" not in data:
                raise ValueError("PRoot is missing the client loopback network policy")
        other_abis = [name for name in archive.namelist()
                      if name.startswith("lib/") and not name.startswith("lib/arm64-v8a/")]
        if other_abis:
            raise ValueError(f"Unexpected native ABI entries: {other_abis}")
        with tempfile.TemporaryDirectory(prefix="eve-apk-trust-") as directory:
            assets = Path(directory)
            for name in ("wine-trust-overlay.json", "wine-crypt32-aarch64.dll", "wine-crypt32-i386.dll"):
                (assets / name).write_bytes(archive.read("assets/" + name))
            wine_trust_overlay.verify(assets / "wine-trust-overlay.json")
    print(f"Verified ARM64 runtime and server/client backend assets: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    check(parser.parse_args().apk)
