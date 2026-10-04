"""Private native graphics selection; hardware qualification never accepts a CPU fixture."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

from pe_image import arm64ec_metadata
from server_runtime import atomic_json

WINE_COMMIT = "a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29"
FEX_COMMIT = "320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab"
DXVK_COMMIT = "0cf05780abd7250c2cd713b7749cf32180157cf5"
DXVK_VERSION = "2.4.1"
MESA_VERSION = "26.0.0"
BASELINE_SHA256 = "f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e"
TOOLCHAIN_SHA256 = "bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d"
KNOWN_BINARY_HASHES = {
    "turnip-26.0.0.so": "51b968eed13c933d114cdc2956135758917e48451129f647ecb5ebbea5a527eb",
    "vulkan-probe": "e5d9f6f11b471415a981d2ae7aac3566ebe7f9d687409437b15fd89aacc69d8b",
}
DLLS = {name: "dxvk-" + name + "-arm64ec.dll" for name in ("d3d11", "dxgi")}
FILES = {*KNOWN_BINARY_HASHES, *DLLS.values(), "eve-d3d11-probe.exe"}
MODES = ("turnip-dxvk", "software")
LIMIT = 64 * 1024**2
DXVK_CACHE_LIMIT = 256 * 1024**2
DXVK_CACHE_FILES = 16
SOURCE_PINS = {
    "dxvkRepository": "https://github.com/doitsujin/dxvk",
    "dxvkSubmodules": {"include/vulkan": "46dc0f6e514f5730784bb2cac2a7c731636839e8",
                       "include/spirv": "8b246ff75c6615ba4532fe4fde20f1be090c3764",
                       "subprojects/libdisplay-info": "275e6459c7ab1ddd4b125f28d0440716e4888078"},
    "mesaSourceSha256": "2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72",
    "glslangSourceSha256": "4bdcd8cdb330313f0d4deed7be527b0ac1c115ff272e492853a6e98add61b4bc",
    "reusedRelease": "https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.17/",
    "reusedBundleSha256": "e4acf8e2dd432e11ec4aac3ad86137890b664df90cd467455b64209dfb56e1ba",
    "reusedCorrespondingSourcesSha256": "492043660b1370e1910c8b8ca2b93be1f637f4929034f575591f14e67e015243",
}


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= LIMIT:
        raise ValueError("Missing, linked or oversized graphics asset: " + path.name)
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_bundle(folder: Path) -> dict:
    path = folder / "client-graphics-bundle.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("Missing or invalid graphics bundle manifest")
    try:
        value = json.loads(path.read_text())
    except RecursionError as error:
        raise ValueError("Graphics manifest exceeds nesting limit") from error
    expected = {"format": 1, "bundle": "eve-turnip-dxvk-2", "runtime": "fex-arm64ec-1",
                "wine_commit": WINE_COMMIT, "fex_commit": FEX_COMMIT, "mesa": MESA_VERSION,
                "dxvk": DXVK_VERSION, "dxvk_commit": DXVK_COMMIT,
                "architecture": "arm64ec-and-arm64-glibc", "kmd": "kgsl",
                "baselineRuntimeSha256": BASELINE_SHA256}
    if not isinstance(value, dict) or type(value.get("format")) is not int or any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("Graphics bundle does not match the pinned Wine/FEX runtime")
    toolchain = value.get("toolchain")
    if toolchain != {"name": "llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64", "sha256": TOOLCHAIN_SHA256}:
        raise ValueError("Graphics bundle compiler does not match the pinned runtime")
    provenance = value.get("sourceProvenance")
    if not isinstance(provenance, dict) or any(provenance.get(key) != item for key, item in SOURCE_PINS.items()):
        raise ValueError("Graphics source provenance differs from the selected immutable inputs")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != FILES:
        raise ValueError("Graphics bundle must contain exactly the five selected assets")
    for name, info in files.items():
        asset = folder / name
        if not isinstance(info, dict) or type(info.get("sizeBytes")) is not int:
            raise ValueError("Invalid graphics asset metadata")
        sha = info.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid graphics asset checksum")
        if digest(asset) != sha or asset.stat().st_size != info["sizeBytes"]:
            raise ValueError("Graphics asset checksum failed: " + name)
        if name in KNOWN_BINARY_HASHES and sha != KNOWN_BINARY_HASHES[name]:
            raise ValueError("Graphics asset differs from the immutable selected driver/probe")
        data = asset.read_bytes()
        if name in KNOWN_BINARY_HASHES:
            machine = struct.unpack_from("<H", data, 18)[0] if len(data) >= 64 else None
            if data[:6] != b"\x7fELF\x02\x01" or machine != 183 or info.get("machine") != 183:
                raise ValueError("Graphics native component must be ARM64 glibc ELF")
        elif name in DLLS.values():
            native = arm64ec_metadata(data)
            if any(type(info.get(key)) is not int or info.get(key) != item for key, item in native.items()):
                raise ValueError("Native ARM64EC graphics metadata differs from the file")
        else:
            offset = struct.unpack_from("<I", data, 60)[0] if len(data) >= 64 else LIMIT
            if (data[:2] != b"MZ" or offset > len(data)-26 or data[offset:offset+4] != b"PE\0\0"
                    or struct.unpack_from("<H", data, offset+4)[0] != 0x8664
                    or struct.unpack_from("<H", data, offset+24)[0] != 0x20b
                    or info.get("machine") != 0x8664):
                raise ValueError("Graphics helper must exercise translated x64 PE32+")
            try:
                arm64ec_metadata(data)
            except ValueError:
                pass
            else:
                raise ValueError("Graphics helper must remain x64, not native ARM64EC")
    return value


def verify_mapped(folder: Path, state: Path) -> dict:
    manifest = verify_bundle(folder)
    for name, asset in DLLS.items():
        target = state / "prefix/drive_c/windows/system32" / (name + ".dll")
        if digest(target) != manifest["files"][asset]["sha256"]:
            raise ValueError("Client session did not bind the native " + name + " module")
        arm64ec_metadata(target.read_bytes())
    return manifest


def cache_directories(state: Path) -> tuple[Path, Path]:
    return (state / ("cache/dxvk-" + DXVK_VERSION + "-arm64ec"),
            state / ("cache/mesa-" + MESA_VERSION))


def prepare(folder: Path, state: Path, content: Path, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("Unsupported client renderer")
    if mode == "software":
        return {"mode": mode, "renderer": "WineD3D / llvmpipe"}
    for directory in (state, state / "run", state / "cache", state / "prefix",
                      state / "prefix/drive_c", state / "prefix/drive_c/windows",
                      state / "prefix/drive_c/windows/system32"):
        if directory.is_symlink():
            raise ValueError("Linked graphics state directory is not supported")
    manifest = verify_mapped(folder, state)
    for directory in (content / "tq", content / "tq/bin64"):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Missing exact client graphics search directory")
        if any(path.name.casefold() in ("d3d11.dll", "dxgi.dll") for path in directory.iterdir()):
            raise ValueError("Imported D3D11/DXGI DLL would shadow the selected graphics bundle; use software recovery")
    dxvk_cache, mesa_cache = cache_directories(state)
    for cache in (dxvk_cache, mesa_cache):
        if cache.is_symlink():
            raise ValueError("Linked graphics cache directory is not supported")
        cache.mkdir(parents=True, exist_ok=True)
    prune_dxvk_cache(dxvk_cache)
    atomic_json(state / "run/turnip-icd.json", {"file_format_version": "1.0.0", "ICD": {
        "library_path": str(folder / "turnip-26.0.0.so"), "api_version": "1.3.0"}})
    config = state / "run/dxvk.conf"
    temporary = config.with_name(".dxvk.conf.tmp")
    temporary.write_text("# Private initial responsiveness settings.\ndxgi.maxFrameRate = 30\ndxgi.maxFrameLatency = 1\n")
    os.replace(temporary, config)
    return manifest


def prune_dxvk_cache(folder: Path) -> None:
    """Bound only regenerable, version-owned state caches between sessions."""
    files = sorted((path for path in folder.iterdir()
                    if path.name.endswith(".dxvk-cache") and path.is_file() and not path.is_symlink()),
                   key=lambda path: (path.stat().st_mtime_ns, path.name))
    total = sum(path.stat().st_size for path in files)
    while files and (total > DXVK_CACHE_LIMIT or len(files) > DXVK_CACHE_FILES):
        oldest = files.pop(0)
        size = oldest.stat().st_size
        oldest.unlink()
        total -= size


def native_command(folder: Path) -> tuple[str, ...]:
    return (str(folder / "vulkan-probe"),)


def d3d_command(folder: Path, manifest: dict, wine: str = "/opt/wine/bin/wine") -> tuple[str, ...]:
    return (wine, str(folder / "eve-d3d11-probe.exe"), "hardware",
            "C:\\windows\\system32\\d3d11.dll", manifest["files"][DLLS["d3d11"]]["sha256"],
            "C:\\windows\\system32\\dxgi.dll", manifest["files"][DLLS["dxgi"]]["sha256"])


def configure_environment(base, mode, folder, state):
    """Prove graphics options cannot leak between software/GPU sessions."""
    if mode not in ("turnip-dxvk", "software"):
        raise ValueError("Unsupported renderer")
    env = {k:v for k,v in base.items()
           if not k.startswith(("DXVK_", "VK_", "MESA_", "LIBGL_"))
           and k not in ("WINE_D3D_CONFIG", "GALLIUM_DRIVER", "LP_NUM_THREADS", "mesa_glthread")}
    env["WINEDLLOVERRIDES"] = "winemenubuilder,mshtml,mscoree=;crypt32=b;d3d11,dxgi=" + ("n" if mode == "turnip-dxvk" else "b")
    if mode == "software":
        env.update(LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe", LP_NUM_THREADS="4")
    else:
        icd = str(state / "run/turnip-icd.json")
        dxvk_cache, mesa_cache = cache_directories(state)
        env.update(VK_DRIVER_FILES=icd, VK_ICD_FILENAMES=icd, MESA_VK_WSI_DEBUG="sw",
                   DXVK_LOG_LEVEL="info", DXVK_LOG_PATH="Z:" + str(state / "logs").replace("/", "\\"),
                   DXVK_HUD="devinfo,fps,compiler", DXVK_CONFIG_FILE="Z:" + str(state / "run/dxvk.conf").replace("/", "\\"),
                   DXVK_STATE_CACHE_PATH="Z:" + str(dxvk_cache).replace("/", "\\"),
                   MESA_SHADER_CACHE_DIR=str(mesa_cache),
                   MESA_SHADER_CACHE_MAX_SIZE="512M")
    return env


def last_report(text, helper=None):
    # Saved observer receipts use atomic_json's formatted document; helper
    # stdout uses compact JSON lines mixed with Wine diagnostics.
    text = text[-65536:]
    try:
        value = json.loads(text)
    except RecursionError as error:
        raise ValueError("Graphics report exceeds JSON nesting limit") from error
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(value, dict) and (helper is None or value.get("helper") == helper):
            return value
        raise ValueError("No graphics helper report")
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except RecursionError as error:
            raise ValueError("Graphics report exceeds JSON nesting limit") from error
        except ValueError:
            continue
        if isinstance(value, dict) and (helper is None or value.get("helper") == helper):
            return value
    raise ValueError("No graphics helper report")


def integer(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum


def color(value, expected):
    return (type(value) is list and len(value) == len(expected)
            and all(integer(component, 0, 255) and abs(component-want) <= 1
                    for component, want in zip(value, expected)))


def parse_vulkan(text):
    r = last_report(text)
    if (not integer(r.get("presentation_frames"), 3, 3)
            or not integer(r.get("api_version"), (1 << 22) | (3 << 12))
            or not integer(r.get("driver_version"), 26 << 22, 26 << 22)
            or not integer(r.get("driver_id"), 18, 18)
            or not integer(r.get("vendor_id"), 0x5143, 0x5143)
            or r.get("software") is not False
            or not isinstance(r.get("device"), str) or "adreno" not in r["device"].casefold()
            or not isinstance(r.get("driver"), str) or "turnip" not in r["driver"].casefold()):
        raise ValueError("Turnip 26 / Adreno hardware and Vulkan presentation were not verified")
    return r


def parse_d3d(text, manifest):
    r = last_report(text, "eve-d3d11-probe-1")
    a = r.get("adapter")
    if (r.get("mode") != "hardware" or r.get("passed") is not True or r.get("stage") != "passed"
            or not integer(r.get("hresult"), 0, 0) or not integer(r.get("win32_error"), 0, 0)
            or not integer(r.get("feature_level"), 0xb000)
            or r.get("pixels_verified") is not True or r.get("offscreen_pixels_verified") is not True
            or not color(r.get("center_rgba"), [32, 223, 64, 255]) or not color(r.get("corner_rgba"), [8, 16, 24, 255])
            or not integer(r.get("present_count"), 3, 3) or not isinstance(a, dict)
            or not integer(a.get("vendor_id"), 0x5143, 0x5143)
            or not integer(a.get("flags")) or a["flags"] & 2
            or not isinstance(a.get("description"), str) or "adreno" not in a["description"].casefold()):
        raise ValueError("Native D3D11 hardware shader rendering was not verified")
    for name in ("d3d11", "dxgi"):
        m = r.get(name)
        if (not isinstance(m, dict) or m.get("identity_verified") is not True
                or not integer(m.get("disk_machine"), 0x8664, 0x8664)
                or not integer(m.get("chpe_version"), 1)
                or not integer(m.get("native_ec_ranges"), 1, 65536)
                or m.get("sha256") != manifest["files"]["dxvk-"+name+"-arm64ec.dll"]["sha256"]
                or not isinstance(m.get("path"), str)
                or m["path"].replace("/", "\\").casefold() != ("C:\\windows\\system32\\"+name+".dll").casefold()):
            raise ValueError("Wrong or non-native graphics DLL loaded: " + name)
    return r


def parse_display(text):
    r = last_report(text, "eve-rfb-frame-1")
    if (not integer(r.get("format"), 1, 1) or r.get("display_pixels_verified") is not True
            or r.get("center_pixels_verified") is not True or r.get("matched_frames") != [0, 1, 2]
            or type(r.get("matched_frames")) is not list or not all(type(value) is int for value in r["matched_frames"])
            or not integer(r.get("expected_frames"), 3, 3)
            or not integer(r.get("process_exit_code"), 0, 0)
            or r.get("observer_error") != "" or r.get("process_error") != ""
            or not integer(r.get("framebuffer_updates"), 1)
            or not integer(r.get("raw_rectangles"), 1) or not integer(r.get("received_bytes"), 1)
            or not integer(r.get("width"), 160, 4096) or not integer(r.get("height"), 160, 2160)
            or r["width"] * r["height"] > 4194304):
        raise ValueError("Synthetic D3D11 frames did not reach the local display")
    return r
