"""Compile actual C parser on this host and compare against independent Python parser."""
from pathlib import Path
import tempfile
import ctypes
import hashlib
import importlib.util
import random
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIRECTORY = tempfile.TemporaryDirectory(prefix="eve-arm64ec-parser-")
BUILD = Path(BUILD_DIRECTORY.name)
text = (ROOT / "native/eve-d3d11-probe.c").read_text()
parser = text[text.index("static DWORD read32"):text.index("static BOOL expected_digest")]
header = r'''
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t BYTE;
typedef uint16_t WORD;
typedef uint32_t DWORD;
typedef uint64_t ULONGLONG;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define IMAGE_DOS_SIGNATURE 0x5a4d
#define IMAGE_NT_SIGNATURE 0x00004550
#define IMAGE_FILE_MACHINE_AMD64 0x8664
#define IMAGE_NT_OPTIONAL_HDR64_MAGIC 0x20b
#define IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG 10
#define IMAGE_SCN_MEM_EXECUTE 0x20000000
struct module_info {WORD disk_machine; DWORD chpe_version, ec_range_count;};
'''
wrapper = r'''
int probe_ec(const BYTE *data, size_t size, DWORD *native_ranges) {
    struct module_info info = {0};
    int result = arm64ec_file(data, size, &info);
    *native_ranges = info.ec_range_count;
    return result;
}
'''
(BUILD / "host-parser.c").write_text(header + parser + wrapper)
subprocess.run(["gcc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                "-fsanitize=undefined", str(BUILD / "host-parser.c"), "-o", str(BUILD / "host-parser.so")], check=True)
library = ctypes.CDLL(str(BUILD / "host-parser.so"))
library.probe_ec.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint32)]
library.probe_ec.restype = ctypes.c_int

spec = importlib.util.spec_from_file_location("independent", ROOT / "backend/pe_image.py")
independent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(independent)

def fixture():
    data = bytearray(0x800)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 240)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20b)
    struct.pack_into("<Q", data, optional+24, 0x180000000)
    struct.pack_into("<II", data, optional+32, 0x1000, 0x200)
    struct.pack_into("<II", data, optional+56, 0x2000, 0x200)
    struct.pack_into("<I", data, optional+108, 16)
    struct.pack_into("<II", data, optional+192, 0x1100, 208)
    table = optional+240
    data[table:table+5] = b".text"
    struct.pack_into("<IIII", data, table+8, 0x600, 0x1000, 0x600, 0x200)
    struct.pack_into("<I", data, table+36, 0x60000020)
    struct.pack_into("<I", data, 0x300, 208)
    struct.pack_into("<Q", data, 0x300+200, 0x180001200)
    struct.pack_into("<III", data, 0x400, 2, 0x1300, 1)
    struct.pack_into("<II", data, 0x500, 0x1401, 0x20)
    return data

def c_result(data):
    native = ctypes.c_uint32()
    buf = ctypes.create_string_buffer(bytes(data))
    return bool(library.probe_ec(buf, len(data), ctypes.byref(native))), native.value

def python_result(data):
    try:
        native = independent.arm64ec_metadata(data)["nativeEcCodeRanges"]
        return True, native
    except ValueError:
        return False, None

valid = fixture()
assert c_result(valid) == (True, 1)
assert python_result(valid) == (True, 1)
cases = {}
for name, offset, value in [
    ("native_code_in_headers", 0x500, 0x41),
    ("non_executable_section", 0x98+240+36, 0x40000040),
    ("code_past_virtual_size", 0x98+240+8, 0x400),
    ("code_past_image_size", 0x98+56, 0x1400),
    ("code_past_raw_size", 0x98+240+16, 0x400),
    ("raw_section_past_file", 0x98+240+16, 0xfffffff0),
    ("too_many_sections", 0x84, 0x00618664),
    ("untranslated_x64_only", 0x500, 0x1400),
]:
    mutation = valid.copy()
    struct.pack_into("<I", mutation, offset, value)
    assert not c_result(mutation)[0], name
    assert not python_result(mutation)[0], name
    cases[name] = "rejected"

sys.path.insert(0, str(ROOT / "tests"))
from test_client_graphics import coalesced_arm64ec_pe, coalesced_rejection_cases, mutate
coalesced = coalesced_arm64ec_pe()
for tag, native_ranges in ((0, 1), (1, 2), (2, 1)):
    image = mutate(coalesced, offset=0x3D88, format="<I", value=0x4000 | tag)
    assert c_result(image) == (True, native_ranges), ("coalesced", tag)
    assert python_result(image) == (True, native_ranges), ("coalesced", tag)
for name, image in coalesced_rejection_cases().items():
    assert not c_result(image)[0], name
    assert not python_result(image)[0], name
    cases[name] = "rejected"
linked_fixture = ROOT / "tests/fixtures/arm64ec/tiny-ec.dll"
assert hashlib.sha256(linked_fixture.read_bytes()).hexdigest() == "b3752ba8134659ff5c597d793dfd9906757cd21631783f67127ff40a2cc72b3f"
for path in [linked_fixture, *sys.argv[1:]]:
    image = Path(path).read_bytes()
    assert c_result(image)[0], path
    assert c_result(image) == python_result(image), path
    print({"actual_linked_ec_image": str(path), "native_ranges": c_result(image)[1]})

rng = random.Random(3396210)
for iteration in range(50_000):
    data = bytearray(valid if iteration % 2 == 0 else coalesced)
    for _ in range(rng.randint(1, 5)):
        offset = rng.randrange(len(data))
        data[offset] = rng.randrange(256)
    if iteration % 4 == 0:
        del data[rng.randrange(len(data)):]
    c_pass, c_native = c_result(data)
    py_pass, py_native = python_result(data)
    assert c_pass == py_pass, (iteration, c_pass, py_pass)
    if c_pass:
        assert c_native == py_native, (iteration, c_native, py_native)
print({"valid_native_ranges": 1, "negative_cases": cases, "mutations": 50_000,
       "c_python_equivalence": "passed", "undefined_behavior_sanitizer": "passed"})

BUILD_DIRECTORY.cleanup()
