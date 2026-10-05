#!/usr/bin/env python3
"""Check that the built ARM64 launcher includes its actual runtime entrypoints."""
import argparse
import re
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import wine_trust_overlay
import client_graphics


def check_manifest(tree: str) -> None:
    """Require release performance flags in the APK's actual aapt XML tree."""
    elements = []
    current = None
    for line in tree.splitlines():
        element = re.match(r"^(\s*)E: ([\w.-]+)(?:\s|$)", line)
        if element:
            current = (len(element[1]), element[2], {})
            elements.append(current)
        elif current is not None:
            attribute = re.match(r"^\s*A: android:([\w]+)\(0x[0-9a-fA-F]+\)=(.*)$", line)
            relevant = {"application": {"debuggable"}, "profileable": {"shell", "enabled"}}
            if attribute and attribute[1] in relevant.get(current[1], set()):
                boolean = re.fullmatch(r"\(type 0x12\)(0x[0-9a-fA-F]+)", attribute[2])
                if not boolean:
                    raise ValueError(f"Unrecognized compiled {current[1]} {attribute[1]} boolean")
                current[2][attribute[1]] = int(boolean[1], 16) != 0
    applications = [(i, item) for i, item in enumerate(elements) if item[1] == "application"]
    if len(applications) != 1:
        raise ValueError("APK manifest must contain exactly one application")
    index, application = applications[0]
    # Android's default is false when this attribute is omitted.
    if application[2].get("debuggable", False):
        raise ValueError("Performance preview APK must not be debuggable")
    children = []
    for item in elements[index + 1:]:
        if item[0] <= application[0]:
            break
        if item[0] == application[0] + 2 and item[1] == "profileable":
            children.append(item)
    if len(children) != 1 or children[0][2].get("shell") is not True or not children[0][2].get("enabled", True):
        raise ValueError("Performance preview must enable shell profiling")


def check(path: Path, manifest_tree: Path) -> None:
    check_manifest(manifest_tree.read_text())
    with zipfile.ZipFile(path) as archive:
        required = (
            "lib/arm64-v8a/libproot.so", "lib/arm64-v8a/libproot-loader.so",
            "assets/server_runtime.py", "assets/client_prepare.py", "assets/client_probe.sh",
            "assets/client_runtime.py", "assets/eve-client-gate.exe",
            "assets/wine_trust_overlay.py", "assets/wine-trust-overlay.json",
            "assets/wine-crypt32-aarch64.dll", "assets/wine-crypt32-i386.dll",
            "assets/pe_image.py", "assets/process_metrics.py", "assets/client_graphics.py", "assets/graphics_present.py",
            "assets/client_diagnostics.py",
            "assets/eve-client-window.exe",
            "assets/client-graphics-bundle.json", "assets/turnip-26.0.0.so", "assets/vulkan-probe",
            "assets/turnip-26.0.0-a740-pc-mode.so", "assets/a740-driver-probe",
            "assets/dxvk-d3d11-arm64ec.dll", "assets/dxvk-dxgi-arm64ec.dll", "assets/eve-d3d11-probe.exe",
        )
        for name in required:
            data = archive.read(name)
            if not data:
                raise ValueError(f"Empty APK entry: {name}")
            if name.startswith("lib/"):
                if data[:5] != b"\x7fELF\x02" or struct.unpack_from("<H", data, 18)[0] != 183:
                    raise ValueError(f"Expected a 64-bit ARM ELF: {name}")
            if name.endswith(("eve-client-gate.exe", "eve-client-window.exe")):
                if data[:2] != b"MZ" or len(data) < 64:
                    raise ValueError("Missing original Windows helper")
                offset = struct.unpack_from("<I", data, 60)[0]
                if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
                    raise ValueError("Expected an original x64 Wine helper")
                if name.endswith("eve-client-window.exe") and (
                        offset + 94 > len(data)
                        or struct.unpack_from("<H", data, offset + 24)[0] != 0x20b
                        or struct.unpack_from("<H", data, offset + 92)[0] != 3):
                    raise ValueError("Window helper must preserve the original x64 CUI console/group")
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
            for name in (*client_graphics.FILES, "client-graphics-bundle.json"):
                (assets / name).write_bytes(archive.read("assets/" + name))
            for name in (client_graphics.A740_DRIVER, client_graphics.A740_PROBE):
                (assets / name).write_bytes(archive.read("assets/" + name))
            client_graphics.verify_bundle(assets)
    print(f"Verified non-debuggable profileable ARM64 APK and server/client backend assets: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("--manifest-tree", type=Path, required=True,
                        help="aapt dump xmltree APK AndroidManifest.xml output from this APK")
    args = parser.parse_args()
    check(args.apk, args.manifest_tree)
