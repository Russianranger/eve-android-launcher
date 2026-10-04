"""Validate the GPU bundle and prove software cannot qualify as hardware."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import client_graphics as graphics
from pe_image import arm64ec_metadata

def arm64ec_pe() -> bytes:
    data = bytearray(0xA00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    # COFF: AMD64, one section, OptionalHeader240, executable/DLL.
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x2022)
    opt = 0x98
    struct.pack_into("<H", data, opt, 0x20B)
    struct.pack_into("<I", data, opt + 16, 0x1500)
    struct.pack_into("<Q", data, opt + 24, 0x180000000)
    struct.pack_into("<II", data, opt + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, opt + 56, 0x2000, 0x200)
    struct.pack_into("<I", data, opt + 108, 16)
    # Data-directory10 is IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG.
    struct.pack_into("<II", data, opt + 112 + 10 * 8, 0x1100, 208)
    section = opt + 240
    data[section:section + 8] = b".fixture"
    struct.pack_into("<IIII", data, section + 8, 0x800, 0x1000, 0x800, 0x200)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    # Raw section maps RVA1000 -> file offset200.
    load = 0x300
    struct.pack_into("<I", data, load, 208)
    struct.pack_into("<Q", data, load + 200, 0x180001300)
    struct.pack_into("<III", data, 0x500, 1, 0x1380, 1)
    # Native EC range tag1; rawcode range lies within its executable section.
    struct.pack_into("<II", data, 0x580, 0x1501, 16)
    data[0x700:0x710] = b"\x1f\x20\x03\xd5" * 4
    return bytes(data)


def coalesced_arm64ec_pe() -> bytes:
    """Mirror the two code ranges emitted by pinned clang/lld for tiny-ec.c."""
    data = bytearray(0x4A00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 3, 0, 0, 0, 240, 0x2022)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional+24, 0x180000000)
    struct.pack_into("<II", data, optional+32, 0x1000, 0x200)
    struct.pack_into("<II", data, optional+56, 0x9000, 0x400)
    struct.pack_into("<I", data, optional+108, 16)
    struct.pack_into("<II", data, optional+192, 0x7100, 208)
    table = optional+240
    for index, (name, virtual_size, rva, raw_size, raw_start, flags) in enumerate((
            (b".text", 0x3186, 0x1000, 0x3400, 0x400, 0x60000020),
            (b".hexpthk", 0x20, 0x5000, 0x200, 0x3800, 0x60000020),
            (b".rdata", 0x1000, 0x7000, 0x1000, 0x3A00, 0x40000040))):
        entry = table+index*40
        data[entry:entry+len(name)] = name
        struct.pack_into("<IIII", data, entry+8, virtual_size, rva, raw_size, raw_start)
        struct.pack_into("<I", data, entry+36, flags)
    struct.pack_into("<I", data, 0x3B00, 208)
    struct.pack_into("<Q", data, 0x3B00+200, 0x180007300)
    struct.pack_into("<III", data, 0x3D00, 1, 0x7380, 2)
    struct.pack_into("<IIII", data, 0x3D80, 0x1005, 0x2028, 0x4002, 0x1020)
    return bytes(data)


def coalesced_rejection_cases() -> dict[str, bytes]:
    data = coalesced_arm64ec_pe()
    table = 0x98+240
    return {
        "range-crosses-non-executable-section": mutate(data, offset=table+40+36, format="<I", value=0x40000040),
        "range-leading-padding": mutate(data, offset=0x3D88, format="<I", value=0x4502),
        "range-trailing-padding": mutate(data, offset=0x3D8C, format="<I", value=0x800),
        "native-range-wholly-padding": mutate(data, offset=0x3D80, format="<I", value=0x4501),
        "overlapping-virtual-sections": mutate(data, offset=table+40+12, format="<I", value=0x4000),
        "huge-inter-section-padding": mutate(data, offset=table+40+12, format="<I", value=0x6000),
        "range-needs-virtual-only-bytes": mutate(data, offset=table+16, format="<I", value=0x2000),
        "unknown-code-map-type": mutate(data, offset=0x3D88, format="<I", value=0x4003),
        "range-outside-image": mutate(data, offset=0x3D8C, format="<I", value=0x6000),
        "zero-section-alignment": mutate(data, offset=0x98+32, format="<I", value=0),
        "non-power-of-two-alignment": mutate(data, offset=0x98+32, format="<I", value=0x1800),
        "unbounded-section-alignment": mutate(data, offset=0x98+32, format="<I", value=0x200000),
    }


def mutate(data: bytes, *, offset: int, format: str, value: int) -> bytes:
    result = bytearray(data)
    struct.pack_into(format, result, offset, value)
    return bytes(result)


def rejection_cases() -> dict[str, bytes]:
    ec = arm64ec_pe()
    return {
        "ordinary-x64-no-chpe": mutate(ec, offset=0x3C8, format="<Q", value=0),
        "ec-coff-machine-not-final-image": mutate(ec, offset=0x84, format="<H", value=0xA641),
        "wrong-optional-header": mutate(ec, offset=0x98, format="<H", value=0x10B),
        "pe-offset-outside-file": mutate(ec, offset=0x3C, format="<I", value=0xFFFFFFF0),
        "truncated-load-config": mutate(ec, offset=0x300, format="<I", value=200),
        "chpe-before-image-base": mutate(ec, offset=0x3C8, format="<Q", value=0x17FFFFFFF),
        "chpe-unmapped": mutate(ec, offset=0x3C8, format="<Q", value=0x180009000),
        "empty-code-map": mutate(ec, offset=0x508, format="<I", value=0),
        "huge-code-map-count": mutate(ec, offset=0x508, format="<I", value=0xFFFFFFFF),
        "code-map-unmapped": mutate(ec, offset=0x504, format="<I", value=0x9000),
        "code-map-no-native-ec-tag": mutate(ec, offset=0x580, format="<I", value=0x1500),
        "code-map-empty-native-range": mutate(ec, offset=0x584, format="<I", value=0),
        "native-range-outside-image": mutate(ec, offset=0x580, format="<I", value=0xFFFF0001),
        "raw-section-outside-file": mutate(ec, offset=0x198, format="<I", value=0xFFFFFF00),
    }


def vulkan_success() -> dict:
    return {"device": "Adreno (TM) 740", "driver": "turnip",
            "driver_info": "Mesa 26.0.0", "driver_version": 26 << 22,
            "driver_id": 18, "vendor_id": 0x5143,
            "api_version": (1 << 22) | (3 << 12), "software": False,
            "presentation_frames": 3}


def module_info(name: str, digest: str) -> dict:
    return {"path": "C:\\windows\\system32\\" + name + ".dll",
            "sha256": digest, "disk_machine": 0x8664, "loaded_machine": 0x8664,
            "chpe_version": 1, "native_ec_ranges": 1, "identity_verified": True}


def d3d_success(*, d3d11_sha: str = "1" * 64, dxgi_sha: str = "2" * 64) -> dict:
    return {"helper": "eve-d3d11-probe-1", "mode": "hardware", "passed": True,
            "stage": "passed", "hresult": 0, "win32_error": 0,
            "d3d11": module_info("d3d11", d3d11_sha), "dxgi": module_info("dxgi", dxgi_sha),
            "adapter": {"description": "Adreno (TM) 740", "vendor_id": 0x5143,
                        "device_id": 0x740, "flags": 0},
            "feature_level": 0xB000, "pixels_verified": True,
            "offscreen_pixels_verified": True, "display_pixels_verified": False,
            "center_rgba": [32, 223, 64, 255], "corner_rgba": [8, 16, 24, 255],
            "present_count": 3, "elapsed_ms": 120}


def modified(value: dict, path: tuple[str, ...], replacement) -> dict:
    result = copy.deepcopy(value)
    current = result
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement
    return result


def vulkan_failures() -> dict[str, dict]:
    accepted = vulkan_success()
    changes = {
        "software-adapter": (("software",), True),
        "software-marker-not-boolean": (("software",), 0),
        "wrong-vendor": (("vendor_id",), 0x10DE),
        "wrong-driver": (("driver_id",), 13),
        "old-mesa-major": (("driver_version",), 25 << 22),
        "vulkan12": (("api_version",), (1 << 22) | (2 << 12)),
        "missing-presentation": (("presentation_frames",), 0),
        "incomplete-presentation": (("presentation_frames",), 2),
        "presentation-string": (("presentation_frames",), "3"),
        "cpu-device-name": (("device",), "llvmpipe (LLVM 15.0.6, 128 bits)"),
        "lavapipe-driver-name": (("driver",), "llvmpipe"),
    }
    return {name: modified(accepted, path, replacement) for name, (path, replacement) in changes.items()}


def d3d_failures(value: dict | None = None) -> dict[str, dict]:
    accepted = value or d3d_success()
    changes = {
        "ci-fixture-cannot-qualify-hardware": (("mode",), "fixture"),
        "wrong-helper": (("helper",), "unrelated"),
        "passed-false": (("passed",), False),
        "partial-stage": (("stage",), "create-device"),
        "error-hresult": (("hresult",), 0x80004005),
        "error-win32": (("win32_error",), 126),
        "wrong-vendor": (("adapter", "vendor_id"), 0x10DE),
        "cpu-adapter": (("adapter", "flags"), 2),
        "cpu-adapter-name": (("adapter", "description"), "llvmpipe (LLVM 15.0.6, 128 bits)"),
        "feature-level10": (("feature_level",), 0xA100),
        "no-shader-readback": (("pixels_verified",), False),
        "readback-center-wrong": (("center_rgba",), [0, 0, 0, 255]),
        "readback-corner-wrong": (("corner_rgba",), [0, 0, 0, 255]),
        "only-two-presents": (("present_count",), 2),
        "present-count-string": (("present_count",), "3"),
    }
    for name in ("d3d11", "dxgi"):
        changes.update({
            name + "-shadow-directory": ((name, "path"), "Z:\\client\\tq\\bin64\\" + name + ".dll"),
            name + "-wrong-checksum": ((name, "sha256"), "0" * 64),
            name + "-wrong-disk-machine": ((name, "disk_machine"), 0xAA64),
            name + "-missing-chpe": ((name, "chpe_version"), 0),
            name + "-missing-native-code": ((name, "native_ec_ranges"), 0),
            name + "-unverified-identity": ((name, "identity_verified"), False),
        })
    return {name: modified(accepted, path, replacement) for name, (path, replacement) in changes.items()}


def noisy_log(report: dict) -> str:
    return "unrelated Wine startup warning\n" + json.dumps({"helper": "unrelated", "passed": True}) + "\n" + json.dumps(report) + "\n"


def display_success() -> dict:
    return {"format": 1, "helper": "eve-rfb-frame-1", "display_pixels_verified": True,
            "center_pixels_verified": True, "matched_frames": [0, 1, 2], "expected_frames": 3,
            "framebuffer_updates": 3, "raw_rectangles": 3, "received_bytes": 4096,
            "width": 1280, "height": 720, "process_exit_code": 0,
            "observer_error": "", "process_error": ""}


def display_failures() -> dict[str, dict]:
    accepted = display_success()
    changes = {
        "wrong-helper": (("helper",), "unrelated"),
        "wrong-format": (("format",), 2),
        "offscreen-only": (("display_pixels_verified",), False),
        "no-center-color": (("center_pixels_verified",), False),
        "incomplete-frame-colors": (("matched_frames",), [0, 1]),
        "repeated-frames": (("matched_frames",), [0, 0, 0]),
        "out-of-order-frames": (("matched_frames",), [2, 1, 0]),
        "wrong-frame-count": (("expected_frames",), 2),
        "wine-helper-failed": (("process_exit_code",), 1),
        "observer-failed": (("observer_error",), "missing expected frame"),
        "process-failed": (("process_error",), "shader helper failed"),
        "no-framebuffer-updates": (("framebuffer_updates",), 0),
        "no-raw-rectangles": (("raw_rectangles",), 0),
        "no-pixel-bytes": (("received_bytes",), 0),
        "zero-width": (("width",), 0),
        "zero-height": (("height",), 0),
    }
    return {name: modified(accepted, path, replacement) for name, (path, replacement) in changes.items()}


BASE_MANIFEST = json.loads(r'''{
  "format": 1,
  "bundle": "eve-turnip-dxvk-2",
  "runtime": "fex-arm64ec-1",
  "wine_commit": "a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29",
  "fex_commit": "320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab",
  "mesa": "26.0.0",
  "dxvk": "2.4.1",
  "dxvk_commit": "0cf05780abd7250c2cd713b7749cf32180157cf5",
  "architecture": "arm64ec-and-arm64-glibc",
  "kmd": "kgsl",
  "files": {
    "turnip-26.0.0.so": {
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "sizeBytes": 4096,
      "machine": 183
    },
    "vulkan-probe": {
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "sizeBytes": 4096,
      "machine": 183
    },
    "dxvk-d3d11-arm64ec.dll": {
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "sizeBytes": 4096,
      "machine": 34404,
      "chpeVersion": 1,
      "nativeEcCodeRanges": 1
    },
    "dxvk-dxgi-arm64ec.dll": {
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "sizeBytes": 4096,
      "machine": 34404,
      "chpeVersion": 1,
      "nativeEcCodeRanges": 1
    },
    "eve-d3d11-probe.exe": {
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "sizeBytes": 4096,
      "machine": 34404
    }
  },
  "baselineRuntimeSha256": "f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e",
  "toolchain": {
    "name": "llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64",
    "sha256": "bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d"
  }
}''')
BASE_MANIFEST["sourceProvenance"] = {
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

def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf_image():
    return b"\x7fELF\x02\x01" + bytes(12) + struct.pack("<H", 183) + bytes(44)


def x64_image():
    # Keep a complete AMD64 PE32+ image, but remove its native EC metadata.
    return mutate(arm64ec_pe(), offset=0x3C8, format="<Q", value=0)


class MetadataTests(unittest.TestCase):
    def test_linker_coalesced_ranges_preserve_native_type_and_executable_bounds(self):
        actual_layout = coalesced_arm64ec_pe()
        self.assertEqual(arm64ec_metadata(actual_layout)["nativeEcCodeRanges"], 1)
        # ARM64 type0 is valid but does not count as ARM64EC type1.
        arm64_span = mutate(actual_layout, offset=0x3D88, format="<I", value=0x4000)
        self.assertEqual(arm64ec_metadata(arm64_span)["nativeEcCodeRanges"], 1)
        native_span = mutate(actual_layout, offset=0x3D88, format="<I", value=0x4001)
        self.assertEqual(arm64ec_metadata(native_span)["nativeEcCodeRanges"], 2)
        for name, image in coalesced_rejection_cases().items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                arm64ec_metadata(image)

    def test_arm64_without_arm64ec_code_cannot_qualify_the_native_ec_bundle(self):
        image = mutate(coalesced_arm64ec_pe(), offset=0x3D80, format="<I", value=0x1004)
        with self.assertRaises(ValueError):
            arm64ec_metadata(image)

    def test_native_ec_metadata_requires_executable_code(self):
        self.assertEqual(arm64ec_metadata(arm64ec_pe()),
                         {"machine": 0x8664, "chpeVersion": 1, "nativeEcCodeRanges": 1})
        rejected = rejection_cases()
        rejected.update({
            "nonexecutable-section": mutate(arm64ec_pe(), offset=0x1AC, format="<I", value=0x40000040),
            "code-in-image-headers": mutate(arm64ec_pe(), offset=0x580, format="<I", value=0x81),
            "code-beyond-image": mutate(arm64ec_pe(), offset=0xD0, format="<I", value=0x1200),
        })
        for name, image in rejected.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                arm64ec_metadata(image)

    def test_truncated_images_fail_as_validation_errors(self):
        for size in (0, 1, 63, 64, 128, 0x188, 0x300, 0x3D0, 0x580, 0x588, 0x710, 0x9FF):
            with self.subTest(size=size), self.assertRaises(ValueError):
                arm64ec_metadata(arm64ec_pe()[:size])


class GraphicsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="eve-graphics-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.folder = self.root / "bundle"
        self.folder.mkdir()
        self.state = self.root / "client-state"
        self.state.mkdir()
        self.content = self.root / "client"
        (self.content / "tq/bin64").mkdir(parents=True)
        self.manifest = copy.deepcopy(BASE_MANIFEST)
        images = {
            "turnip-26.0.0.so": elf_image(), "vulkan-probe": elf_image(),
            "dxvk-d3d11-arm64ec.dll": arm64ec_pe(),
            "dxvk-dxgi-arm64ec.dll": mutate(arm64ec_pe(), offset=0x900, format="<I", value=0xD317),
            "eve-d3d11-probe.exe": x64_image(),
        }
        for name, image in images.items():
            (self.folder / name).write_bytes(image)
            self.manifest["files"][name].update(sha256=digest(image), sizeBytes=len(image))
        # These synthetic fixtures test byte/hash/architecture validation. Real
        # Turnip/probe anchors are required unmocked by graphics and APK CI.
        anchor = mock.patch.object(graphics, "KNOWN_BINARY_HASHES",
                                   {name: digest(images[name]) for name in ("turnip-26.0.0.so", "vulkan-probe")})
        anchor.start()
        self.addCleanup(anchor.stop)
        self.write_manifest()

    def write_manifest(self, value=None):
        (self.folder / "client-graphics-bundle.json").write_text(json.dumps(value or self.manifest))

    def report(self):
        return d3d_success(d3d11_sha=self.manifest["files"]["dxvk-d3d11-arm64ec.dll"]["sha256"],
                           dxgi_sha=self.manifest["files"]["dxvk-dxgi-arm64ec.dll"]["sha256"])

    def map_dlls(self):
        system32 = self.state / "prefix/drive_c/windows/system32"
        system32.mkdir(parents=True, exist_ok=True)
        for name, asset in graphics.DLLS.items():
            (system32 / (name + ".dll")).write_bytes((self.folder / asset).read_bytes())
        return system32

    def test_bundle_verification_preserves_existing_assets(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        result = graphics.verify_bundle(self.folder)
        self.assertEqual(result["files"], self.manifest["files"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.folder.iterdir()})

    def test_damaged_missing_and_linked_components_fail(self):
        for name in self.manifest["files"]:
            with self.subTest(name=name):
                path = self.folder / name
                original = path.read_bytes()
                path.write_bytes(original + b"damaged")
                with self.assertRaises(ValueError):
                    graphics.verify_bundle(self.folder)
                path.unlink()
                with self.assertRaises((OSError, ValueError)):
                    graphics.verify_bundle(self.folder)
                outside = self.root / "linked-binary"
                outside.write_bytes(original)
                path.symlink_to(outside)
                with self.assertRaises(ValueError):
                    graphics.verify_bundle(self.folder)
                path.unlink()
                path.write_bytes(original)

    def test_source_runtime_and_architecture_pins_are_required(self):
        for field in ("format", "bundle", "runtime", "wine_commit", "fex_commit", "mesa",
                      "dxvk", "dxvk_commit", "architecture", "kmd", "baselineRuntimeSha256", "toolchain", "sourceProvenance"):
            with self.subTest(field=field):
                value = copy.deepcopy(self.manifest)
                value[field] = "different-build"
                self.write_manifest(value)
                with self.assertRaises(ValueError):
                    graphics.verify_bundle(self.folder)
        self.write_manifest()

    def test_previous_timeline_queue_bundle_cannot_qualify(self):
        previous = copy.deepcopy(self.manifest)
        previous.update(bundle="eve-turnip-dxvk-1", dxvk="2.5.3",
                        dxvk_commit="c707d9026f33b6ab89639f154b6ac5f6326fa037")
        self.write_manifest(previous)
        with self.assertRaises(ValueError):
            graphics.verify_bundle(self.folder)

    def test_nested_source_pins_and_integer_manifest_metadata_are_checked(self):
        changes = [(("format",), True),
                   (("toolchain", "sha256"), "0" * 64),
                   (("sourceProvenance", "dxvkSubmodules", "include/vulkan"), "0" * 40),
                   (("sourceProvenance", "mesaSourceSha256"), "0" * 64),
                   (("sourceProvenance", "reusedRelease"), "https://example.test/changed/"),
                   (("files", "dxvk-d3d11-arm64ec.dll", "chpeVersion"), True),
                   (("files", "dxvk-dxgi-arm64ec.dll", "nativeEcCodeRanges"), 1.0)]
        for path, replacement in changes:
            with self.subTest(path=path):
                self.write_manifest(modified(self.manifest, path, replacement))
                with self.assertRaises(ValueError):
                    graphics.verify_bundle(self.folder)
        self.write_manifest()

    def test_manifest_requires_exact_component_set_and_rows(self):
        values = []
        value = copy.deepcopy(self.manifest)
        value["files"].pop("vulkan-probe")
        values.append(value)
        value = copy.deepcopy(self.manifest)
        value["files"]["../other.dll"] = value["files"]["dxvk-dxgi-arm64ec.dll"]
        values.append(value)
        for replacement in (None, [], "invalid"):
            value = copy.deepcopy(self.manifest)
            value["files"] = replacement
            values.append(value)
        for name in self.manifest["files"]:
            for field, replacement in (("sha256", "0" * 64), ("sizeBytes", 0), ("machine", 0)):
                value = copy.deepcopy(self.manifest)
                value["files"][name][field] = replacement
                values.append(value)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write_manifest(value)
                graphics.verify_bundle(self.folder)
        self.write_manifest()

    def test_renderer_switch_removes_inherited_graphics_options(self):
        base = {"KEEP": "value", "WINEESYNC": "0", "WINEFSYNC": "0", "SSL_CERT_FILE": "private-ca",
                "VK_DRIVER_FILES": "/other/icd.json", "VK_LAYER_PATH": "/other/layers",
                "DXVK_CONFIG_FILE": "/outside/config", "DXVK_STATE_CACHE_PATH": "/outside/cache",
                "MESA_SHADER_CACHE_DISABLE": "1", "MESA_VK_WSI_DEBUG": "linear",
                "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe", "LP_NUM_THREADS": "999",
                "WINE_D3D_CONFIG": "renderer=vulkan", "mesa_glthread": "true"}
        saved = dict(base)
        gpu = graphics.configure_environment(base, "turnip-dxvk", self.folder, self.state)
        software = graphics.configure_environment(gpu, "software", self.folder, self.state)
        gpu_again = graphics.configure_environment(software, "turnip-dxvk", self.folder, self.state)
        self.assertEqual(base, saved)
        self.assertEqual(gpu_again, gpu)
        self.assertTrue(gpu["WINEDLLOVERRIDES"].endswith("d3d11,dxgi=n"))
        self.assertTrue(software["WINEDLLOVERRIDES"].endswith("d3d11,dxgi=b"))
        self.assertFalse(any(key.startswith(("DXVK_", "VK_", "MESA_")) for key in software))
        for key in ("VK_LAYER_PATH", "MESA_SHADER_CACHE_DISABLE", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER",
                    "LP_NUM_THREADS", "WINE_D3D_CONFIG", "mesa_glthread"):
            self.assertNotIn(key, gpu)
        for key in ("KEEP", "WINEESYNC", "WINEFSYNC", "SSL_CERT_FILE"):
            self.assertEqual(gpu[key], base[key])
            self.assertEqual(software[key], base[key])

    def test_unknown_mode_is_not_an_implicit_fallback(self):
        for mode in ("fixture", "lavapipe", "turnip", "", None):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                graphics.configure_environment({}, mode, self.folder, self.state)

    def test_session_binding_must_match_exact_native_assets(self):
        system32 = self.map_dlls()
        self.assertEqual(graphics.verify_mapped(self.folder, self.state)["bundle"], "eve-turnip-dxvk-2")
        for name in graphics.DLLS:
            with self.subTest(name=name):
                path = system32 / (name + ".dll")
                original = path.read_bytes()
                path.write_bytes(x64_image())
                with self.assertRaises(ValueError):
                    graphics.verify_mapped(self.folder, self.state)
                path.unlink()
                path.symlink_to(self.folder / graphics.DLLS[name])
                with self.assertRaises(ValueError):
                    graphics.verify_mapped(self.folder, self.state)
                path.unlink()
                path.write_bytes(original)

    def test_gpu_preparation_preserves_content_prefix_trust_and_shader_cache(self):
        self.map_dlls()
        protected = {
            self.state / "prefix/system.reg": b"accepted existing prefix",
            self.state / "trust/evejs-ca.pem": b"accepted local CA",
            self.state / "cache/dxvk-2.5.3-arm64ec/exefile.dxvk-cache": b"retained previous-version cache",
            self.content / "eve-client-content.json": b"accepted resources receipt",
            self.content / "tq/bin64/exefile.exe": b"accepted client EXE",
        }
        for path, data in protected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = graphics.prepare(self.folder, self.state, self.content, "turnip-dxvk")
        self.assertEqual(result["bundle"], "eve-turnip-dxvk-2")
        cache = self.state / "cache/dxvk-2.4.1-arm64ec/exefile.dxvk-cache"
        cache.write_bytes(b"retained shader state")
        graphics.prepare(self.folder, self.state, self.content, "turnip-dxvk")
        self.assertEqual(cache.read_bytes(), b"retained shader state")
        self.assertTrue((self.state / "cache/mesa-26.0.0").is_dir())
        self.assertEqual(protected, {path: path.read_bytes() for path in protected})
        icd = json.loads((self.state / "run/turnip-icd.json").read_text())
        self.assertEqual(icd["ICD"]["library_path"], str(self.folder / "turnip-26.0.0.so"))
        config = (self.state / "run/dxvk.conf").read_text()
        self.assertIn("dxgi.maxFrameRate = 30", config)
        self.assertIn("dxgi.maxFrameLatency = 1", config)
        self.assertNotIn("enableGraphicsPipelineLibrary", config)
        self.assertEqual(graphics.configure_environment({}, "turnip-dxvk", self.folder, self.state)["DXVK_STATE_CACHE_PATH"],
                         "Z:" + str(self.state / "cache/dxvk-2.4.1-arm64ec").replace("/", "\\"))

    def test_software_recovery_does_not_require_or_mutate_gpu_bundle(self):
        keep = self.state / "keep-existing-state"
        keep.write_bytes(b"existing state")
        before = {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()}
        result = graphics.prepare(self.root / "missing-bundle", self.state, self.content, "software")
        self.assertEqual(result["mode"], "software")
        self.assertEqual(before, {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()})

    def test_imported_shadow_dlls_in_both_search_directories_are_rejected(self):
        self.map_dlls()
        for directory in (self.content / "tq", self.content / "tq/bin64"):
            for name in ("d3d11.dll", "D3D11.DLL", "dxgi.dll", "DxGi.dLl"):
                with self.subTest(directory=directory, name=name):
                    path = directory / name
                    path.write_bytes(b"imported shadow DLL")
                    with self.assertRaisesRegex(ValueError, "shadow"):
                        graphics.prepare(self.folder, self.state, self.content, "turnip-dxvk")
                    path.unlink()

    def test_linked_cache_parent_and_run_directory_cannot_redirect_writes(self):
        for name in ("cache", "run"):
            with self.subTest(name=name):
                self.state = self.root / ("state-" + name)
                self.state.mkdir()
                self.map_dlls()
                outside = self.root / ("outside-" + name)
                outside.mkdir()
                path = self.state / name
                path.symlink_to(outside, target_is_directory=True)
                with self.assertRaises(ValueError):
                    graphics.prepare(self.folder, self.state, self.content, "turnip-dxvk")
                self.assertEqual(list(outside.iterdir()), [])
                path.unlink()

    def test_dxvk_cache_limits_evict_oldest_owned_files_and_preserve_other_data(self):
        cache = self.state / "cache/dxvk-2.4.1-arm64ec"
        cache.mkdir(parents=True)
        paths = []
        for index in range(5):
            path = cache / (str(index) + ".dxvk-cache")
            path.write_bytes(bytes([index]) * 4)
            os.utime(path, ns=(index + 1, index + 1))
            paths.append(path)
        keep = cache / "unrelated-file"
        keep.write_bytes(b"preserved unrelated content")
        outside = self.root / "external-shader.dxvk-cache"
        outside.write_bytes(b"outside linked target")
        (cache / "linked.dxvk-cache").symlink_to(outside)
        with mock.patch.object(graphics, "DXVK_CACHE_LIMIT", 8), \
                mock.patch.object(graphics, "DXVK_CACHE_FILES", 3):
            graphics.prune_dxvk_cache(cache)
        self.assertEqual([path.name for path in paths if path.exists()], ["3.dxvk-cache", "4.dxvk-cache"])
        self.assertEqual(keep.read_bytes(), b"preserved unrelated content")
        self.assertEqual(outside.read_bytes(), b"outside linked target")
        self.assertTrue((cache / "linked.dxvk-cache").is_symlink())
        with mock.patch.object(graphics, "DXVK_CACHE_LIMIT", 100), \
                mock.patch.object(graphics, "DXVK_CACHE_FILES", 1):
            graphics.prune_dxvk_cache(cache)
        self.assertFalse(paths[3].exists())
        self.assertTrue(paths[4].exists())

    def test_native_vulkan_requires_qualcomm_hardware_and_presentations(self):
        report = vulkan_success()
        result = graphics.parse_vulkan(noisy_log(report))
        self.assertEqual(result["vendor_id"], 0x5143)
        for name, rejected in vulkan_failures().items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                graphics.parse_vulkan(noisy_log(rejected))

    def test_d3d_requires_native_bound_dlls_hardware_pixels_and_presentations(self):
        report = self.report()
        self.assertTrue(graphics.parse_d3d(noisy_log(report), self.manifest)["passed"])
        for name, rejected in d3d_failures(report).items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                graphics.parse_d3d(noisy_log(rejected), self.manifest)

    def test_loaded_pe_machine_is_observational_only(self):
        report = self.report()
        report["d3d11"]["loaded_machine"] = 0xAA64
        report["dxgi"]["loaded_machine"] = 0xAA64
        self.assertTrue(graphics.parse_d3d(noisy_log(report), self.manifest)["passed"])

    def test_color_rounding_and_typed_array_validation_match_native_probe(self):
        report = self.report()
        report["center_rgba"] = [31, 224, 63, 254]
        report["corner_rgba"] = [7, 17, 23, 254]
        self.assertTrue(graphics.parse_d3d(noisy_log(report), self.manifest)["passed"])
        for field in ("center_rgba", "corner_rgba"):
            report = self.report()
            report[field] = [float(value) for value in report[field]]
            with self.subTest(field=field), self.assertRaises(ValueError):
                graphics.parse_d3d(noisy_log(report), self.manifest)

    def test_presented_display_requires_three_distinct_ordered_pixel_frames(self):
        report = display_success()
        self.assertTrue(graphics.parse_display(noisy_log(report))["display_pixels_verified"])
        self.assertTrue(graphics.parse_display(noisy_log(dict(report, width=320, height=240)))["display_pixels_verified"])
        for name, rejected in display_failures().items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                graphics.parse_display(noisy_log(rejected))
        for frames in ([False, True, 2], [0.0, 1.0, 2.0]):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                graphics.parse_display(noisy_log(dict(report, matched_frames=frames)))

    def test_device_observer_receipt_round_trips_through_the_atomic_json_writer(self):
        # The device reached all three displayed frames, but this multiline
        # receipt was rejected even though the compact stdout copy passed.
        report = dict(display_success(), framebuffer_updates=6, raw_rectangles=20,
                      received_bytes=4014403)
        receipt = self.state / "run/graphics-display.json"
        graphics.atomic_json(receipt, report)
        text = receipt.read_text()
        self.assertIn('"matched_frames": [\n', text)
        self.assertEqual(graphics.parse_display(text), report)
        self.assertEqual(receipt.read_text(), text)

    def test_probe_readers_accept_complete_pretty_and_compact_json_documents(self):
        for report, parser in ((vulkan_success(), graphics.parse_vulkan),
                               (self.report(), lambda text: graphics.parse_d3d(text, self.manifest)),
                               (display_success(), graphics.parse_display)):
            for indent in (None, 2):
                text = " \n" + json.dumps(report, indent=indent) + "\r\n "
                with self.subTest(helper=report.get("helper", "vulkan"), indent=indent):
                    self.assertEqual(parser(text), report)

    def test_compact_stdout_reports_ignore_noise_and_unrelated_helpers(self):
        unrelated = json.dumps({"helper": "unrelated-helper", "passed": False})
        for report, parser in ((self.report(), lambda text: graphics.parse_d3d(text, self.manifest)),
                               (display_success(), graphics.parse_display)):
            text = ("wine:warn: diagnostic {not JSON}\n" + unrelated + "\n"
                    + json.dumps(report) + "\r\n" + unrelated + "\nhelper finished\n")
            with self.subTest(helper=report["helper"]):
                self.assertEqual(parser(text), report)
        report = vulkan_success()
        text = "driver diagnostic {not JSON}\n" + unrelated + "\n" + json.dumps(report) + "\nfinished\n"
        self.assertEqual(graphics.parse_vulkan(text), report)

    def test_complete_nonmatching_documents_cannot_expose_a_nested_helper_report(self):
        for report, parser in ((vulkan_success(), graphics.parse_vulkan),
                               (self.report(), lambda text: graphics.parse_d3d(text, self.manifest)),
                               (display_success(), graphics.parse_display)):
            nested_documents = (
                "null", "true", '"diagnostic"',
                "[\n" + json.dumps(report) + "\n]",
                '{"helper":"unrelated-helper","nested":\n' + json.dumps(report) + "\n}",
                json.dumps(dict(report, helper="unrelated-helper"), indent=2),
            )
            # Vulkan has no helper marker; changing one alone leaves its
            # hardware fields valid, so use an unrelated object instead.
            if "helper" not in report:
                nested_documents = nested_documents[:-1] + ('{"helper":"unrelated-helper"}',)
            for text in nested_documents:
                with self.subTest(helper=report.get("helper", "vulkan"), text=text[:40]), self.assertRaises(ValueError):
                    parser(text)

    def test_document_readers_reject_truncated_oversized_and_corrupt_pretty_receipts(self):
        for report, parser in ((vulkan_success(), graphics.parse_vulkan),
                               (self.report(), lambda text: graphics.parse_d3d(text, self.manifest)),
                               (display_success(), graphics.parse_display)):
            pretty = json.dumps(report, indent=2)
            oversized = dict(report, diagnostic="X" * 65536)
            for text in (pretty[:-1], pretty + "\ntrailing garbage", pretty + "\n" + pretty,
                         json.dumps(oversized), json.dumps(oversized, indent=2)):
                with self.subTest(helper=report.get("helper", "vulkan"), text=text[:40]), self.assertRaises(ValueError):
                    parser(text)
            # Bounded logs still accept a complete compact report at the tail.
            tail = ("diagnostic without a report\n" * 3000) + json.dumps(report) + "\n"
            with self.subTest(helper=report.get("helper", "vulkan")):
                self.assertEqual(parser(tail), report)

    def test_last_matching_display_failure_overrides_an_earlier_success(self):
        report = display_success()
        failed = dict(report, display_pixels_verified=False, matched_frames=[0, 1],
                      observer_error="Expected frame 2 did not reach the local display")
        text = (noisy_log(report) + json.dumps(failed) + "\n"
                + json.dumps({"helper": "unrelated-helper"}) + "\nfinished\n")
        with self.assertRaises(ValueError):
            graphics.parse_display(text)
        with self.assertRaises(ValueError):
            graphics.parse_display(json.dumps(failed, indent=2))

    def test_decoder_nesting_limit_is_a_validation_error(self):
        for helper, parser in (("none", graphics.parse_vulkan),
                               ("eve-d3d11-probe-1", lambda text: graphics.parse_d3d(text, self.manifest)),
                               ("eve-rfb-frame-1", graphics.parse_display)):
            nested = '{"helper":' + json.dumps(helper) + ',"nested":' + '[' * 15000 + '0' + ']' * 15000 + '}'
            with self.subTest(helper=helper), self.assertRaises(ValueError):
                parser(nested)

    def test_final_helper_failure_cannot_reuse_an_earlier_success(self):
        report = self.report()
        failed = dict(report, passed=False, stage="present", hresult=0x80004005)
        text = noisy_log(report) + json.dumps(failed) + "\n"
        with self.assertRaises(ValueError):
            graphics.parse_d3d(text, self.manifest)

    def test_both_probe_parsers_reject_absent_malformed_and_oversized_reports(self):
        for text in ("", "no report", "{\"helper\":", "[true]", "X" * (1024 * 1024)):
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                graphics.parse_vulkan(text)
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                graphics.parse_d3d(text, self.manifest)


if __name__ == "__main__":
    unittest.main()

