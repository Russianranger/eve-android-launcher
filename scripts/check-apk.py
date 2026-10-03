#!/usr/bin/env python3
"""Check that the built ARM64 launcher includes its actual runtime entrypoints."""
import argparse
import struct
import zipfile
from pathlib import Path


def check(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        required = (
            "lib/arm64-v8a/libproot.so", "lib/arm64-v8a/libproot-loader.so",
            "assets/server_runtime.py", "assets/client_prepare.py", "assets/client_probe.sh",
            "assets/client_runtime.py", "assets/eve-client-gate.exe",
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
    print(f"Verified ARM64 runtime and server/client backend assets: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    check(parser.parse_args().apk)
