"""Bounded raw PE validation for native ARM64EC graphics overlays."""
import struct


def arm64ec_metadata(data: bytes) -> dict:
    """Validate raw PE CHPE metadata; final EC images deliberately use AMD64."""
    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError("Truncated ARM64EC image")
        return struct.unpack_from(fmt, data, offset)
    if data[:2] != b"MZ":
        raise ValueError("Missing PE image")
    nt, = unpack("<I", 60)
    if data[nt:nt+4] != b"PE\0\0":
        raise ValueError("Missing PE header")
    machine, sections = unpack("<HH", nt+4)
    optional_size, = unpack("<H", nt+20)
    optional = nt+24
    magic, = unpack("<H", optional)
    if machine != 0x8664 or magic != 0x20b or optional_size < 208 or optional+optional_size > len(data):
        raise ValueError("Expected final AMD64 PE32+ ARM64EC image")
    directory_count, = unpack("<I", optional+108)
    if directory_count <= 10:
        raise ValueError("Missing load configuration")
    image_base, = unpack("<Q", optional+24)
    image_size, = unpack("<I", optional+56)
    headers, = unpack("<I", optional+60)
    table = optional + optional_size
    if sections > 96 or table+sections*40 > len(data):
        raise ValueError("Invalid PE section table")
    ranges = []
    for index in range(sections):
        virtual_size, = unpack("<I", table+index*40+8)
        start, raw_size, raw_start = unpack("<III", table+index*40+12)
        flags, = unpack("<I", table+index*40+36)
        if raw_start > len(data) or raw_size > len(data)-raw_start:
            raise ValueError("PE raw section extends outside file")
        ranges.append((start, raw_size, raw_start, virtual_size, flags))
    def raw(rva, length):
        if rva < headers and length <= headers-rva and rva+length <= len(data):
            return rva
        for start, raw_size, raw_start, _, _ in ranges:
            delta = rva-start
            if 0 <= delta <= raw_size and length <= raw_size-delta and raw_start+delta+length <= len(data):
                return raw_start+delta
        raise ValueError("Unmapped ARM64EC metadata")
    config_rva, config_size = unpack("<II", optional+112+10*8)
    if not config_rva or config_size < 208:
        raise ValueError("Missing CHPE load configuration")
    config = raw(config_rva, 208)
    config_declared, = unpack("<I", config)
    if config_declared < 208:
        raise ValueError("Truncated CHPE configuration")
    metadata_va, = unpack("<Q", config+200)
    metadata_rva = metadata_va-image_base
    if not 0 < metadata_rva <= 0xffffffff:
        raise ValueError("Invalid CHPE pointer")
    metadata = raw(metadata_rva, 12)
    version, code_map_rva, count = unpack("<III", metadata)
    if not version or not code_map_rva or not 0 < count <= 65536:
        raise ValueError("Invalid CHPE code map")
    code_map = raw(code_map_rva, count*8)
    native = 0
    for index in range(count):
        start, length = unpack("<II", code_map+index*8)
        if not length:
            raise ValueError("Empty CHPE code range")
        raw(start & ~3, length)
        code_start = start & ~3
        if code_start >= image_size or length > image_size-code_start:
            raise ValueError("CHPE code range outside loaded image")
        if not any(section_start <= code_start and length <= virtual_size-(code_start-section_start)
                   and flags & 0x20000000
                   for section_start, _, _, virtual_size, flags in ranges):
            raise ValueError("CHPE code range outside executable section")
        native += (start & 3) == 1
    if not native:
        raise ValueError("Image contains no native ARM64EC code")
    return {"machine": machine, "chpeVersion": version, "nativeEcCodeRanges": native}


