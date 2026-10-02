#!/usr/bin/env python3
"""Prepare a private, exact-build EVE cache without launching any retail client.

PE patch semantics and JSON recipes are adapted from EveJS v0.12.9
tools/ClientSETUP (AGPL-3.0). See docs/CLIENT-RUNTIME.md and upstream source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

BUILD = 3396210
MAX_FILES = 1_000_000
MAX_BYTES = 160 * 1024**3
RECIPE_DIR = Path(__file__).resolve().parent
RECIPES = ("blue_patch_recipe.json", "launchdarkly_patch_recipe.json", "crash_upload_patch_recipe.json")
RESOURCE_NAME = re.compile(r"^[0-9a-fA-F]{2}/[0-9a-fA-F]+_[0-9a-fA-F]+$")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def contained_file(root, relative):
    root = Path(root).resolve()
    candidate = root / relative
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError("Symbolic links are not permitted in imported client content: " + str(relative))
        cursor = cursor.parent
        if cursor == cursor.parent and cursor != root:
            raise ValueError("Client path escapes its private content folder")
    if not candidate.is_file():
        raise ValueError("Missing client file: " + str(relative))
    return candidate


def ini_values(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match:
            name, value = match.group(1).lower(), match.group(2)
            if name in values:
                raise ValueError("Duplicate start.ini key: " + name)
            values[name] = value
    return values


def load_recipes(folder=RECIPE_DIR):
    recipes = [json.loads((Path(folder) / name).read_text()) for name in RECIPES]
    for recipe in recipes:
        if recipe["supportedBuild"] != BUILD:
            raise ValueError("Unsupported binary patch recipe build")
    return recipes


def pe_fields(data):
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise ValueError("Binary is not a PE image")
    offset = struct.unpack_from("<I", data, 0x3c)[0]
    if offset < 0x40 or offset + 24 >= len(data) or data[offset:offset + 4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    optional = offset + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directories = optional + (112 if magic == 0x20b else 96 if magic == 0x10b else 0)
    if directories == optional or directories + 40 > len(data):
        raise ValueError("Unsupported or truncated PE optional header")
    checksum = optional + 64
    security = directories + 32
    return checksum, security


def pe_checksum(data, checksum_offset):
    total = 0
    for index in range(0, len(data), 2):
        if checksum_offset <= index < checksum_offset + 4:
            continue
        word = data[index] | ((data[index + 1] if index + 1 < len(data) else 0) << 8)
        total += word
        total = (total & 0xffffffff) + (total >> 32)
    total = (total & 0xffff) + (total >> 16)
    total += total >> 16
    return (total & 0xffff) + len(data)


def matching_patches(data, recipe, side):
    return all(data[patch["offset"]:patch["offset"] + len(bytes.fromhex(patch[side + "Hex"]))]
               == bytes.fromhex(patch[side + "Hex"]) for patch in recipe["patches"])


def patch_bytes(data, recipe):
    """Require a recorded SHA-256, including when accepting an existing patch.

    Upstream permits relaxed blue.dll matching; Android deliberately accepts
    only exact source hashes, exact known variants, or the deterministic output
    recomputed from the original immutable backup.
    """
    sha = hashlib.sha256(data).hexdigest()
    variants = recipe.get("knownPatchedVariants", [])
    if any(item["size"] == len(data) and item["sha256"] == sha for item in variants):
        if not matching_patches(data, recipe, "after"):
            raise ValueError("Known variant has inconsistent patch bytes")
        return data, "known_patched"
    source = recipe["source"]
    if len(data) != source["size"] or sha != source["sha256"]:
        raise ValueError("Unsupported binary SHA-256 for " + source["filename"] + "; requires build3396210")
    if not matching_patches(data, recipe, "before"):
        raise ValueError("Original patch bytes differ from recipe")
    output = bytearray(data)
    checksum, security = pe_fields(output)
    for patch in recipe["patches"]:
        before, after = bytes.fromhex(patch["beforeHex"]), bytes.fromhex(patch["afterHex"])
        if len(before) != len(after) or patch["offset"] + len(before) > len(output):
            raise ValueError("Invalid fixed-length patch")
        output[patch["offset"]:patch["offset"] + len(after)] = after
    certificate, certificate_size = struct.unpack_from("<II", output, security)
    if certificate or certificate_size:
        if not certificate or not certificate_size or certificate < security + 8 or certificate + certificate_size > len(output):
            raise ValueError("Invalid PE security directory")
        output = output[:certificate]
    struct.pack_into("<II", output, security, 0, 0)
    struct.pack_into("<I", output, checksum, 0)
    struct.pack_into("<I", output, checksum, pe_checksum(output, checksum))
    if not matching_patches(output, recipe, "after"):
        raise ValueError("Output binary failed patch verification")
    if recipe.get("requireExactHash") and variants:
        output_sha = hashlib.sha256(output).hexdigest()
        if not any(item["size"] == len(output) and item["sha256"] == output_sha for item in variants):
            raise ValueError("Patched output differs from recorded known SHA-256: " + source["filename"])
    return bytes(output), "patched_exact_original"


def validate_binaries(content, recipes=None, apply=False):
    recipes = recipes if recipes is not None else load_recipes()
    planned, report = [], []
    for recipe in recipes:
        filename = recipe["source"]["filename"]
        target = contained_file(content, Path("tq/bin64") / filename)
        before = target.read_bytes()
        backup = target.with_name(target.name + ".evejs-original")
        try:
            after, state = patch_bytes(before, recipe)
        except ValueError:
            # Support exact prior numeric-loopback LaunchDarkly recipe too.
            upgrade = RECIPE_DIR / "launchdarkly_localhost_upgrade_recipe.json"
            if filename == "launchdarkly_stackless_client_sdk.pyd" and upgrade.exists():
                try:
                    after, state = patch_bytes(before, json.loads(upgrade.read_text()))
                except ValueError:
                    after, state = None, None
            else:
                after, state = None, None
            if after is None:
                if not backup.is_file() or backup.is_symlink():
                    raise
                expected, _ = patch_bytes(backup.read_bytes(), recipe)
                if expected != before:
                    raise ValueError("Client binary differs from exact recipe output: " + filename)
                after, state = before, "verified_original_backup"
        planned.append((target, before, after, backup))
        report.append({"file": filename, "state": state, "sha256": hashlib.sha256(after).hexdigest()})
    # No binary is changed until every binary's SHA and patch bytes pass.
    if apply:
        for target, before, after, backup in planned:
            if before != after and backup.exists() and (backup.is_symlink() or backup.read_bytes() != before):
                raise ValueError("Refusing to overwrite original binary backup: " + target.name)
        for target, before, after, backup in planned:
            if before == after:
                continue
            if not backup.exists():
                backup.write_bytes(before)
            temporary = target.with_name(target.name + ".evejs-tmp")
            temporary.write_bytes(after)
            temporary.replace(target)
    return report


def check_resources(content):
    """Match the authoritative offline resource gate: both indexes, every file.

    Asset size/hash field meanings are not guessed: their format is not
    specified by the supplied upstream resource gate. ZIP CRC verifies imports.
    """
    resource_root = Path(content) / "ResFiles"
    if not resource_root.is_dir() or resource_root.is_symlink():
        raise ValueError("Missing ResFiles beside tq; import the complete shared cache")
    contained_file(content, "index_tranquility.txt")
    checked = 0
    unique = set()
    for name in ("resfileindex.txt", "resfileindex_Windows.txt"):
        index = contained_file(content, Path("tq") / name)
        count = 0
        with index.open(encoding="utf-8-sig") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                fields = line.strip().split(",")
                if len(fields) != 5 or not fields[0].startswith("res:/") or not RESOURCE_NAME.fullmatch(fields[1]):
                    raise ValueError("Malformed " + name + " entry " + str(line_number))
                relative = "ResFiles/" + fields[1]
                resource = contained_file(content, relative)
                unique.add(fields[1].lower())
                checked += 1
                count += 1
                if checked > MAX_FILES * 2:
                    raise ValueError("Too many indexed resources")
        if count == 0:
            raise ValueError("Empty resource index: " + name)
    return {"indexed_entries": checked, "unique_resources": len(unique), "complete": True}


def validate_content(content, recipes=None, apply=False):
    content = Path(content)
    values = ini_values(contained_file(content, "tq/start.ini"))
    if values.get("build") != str(BUILD):
        raise ValueError("Requires EVE 24.01 build3396210; found " + values.get("build", "no build"))
    resources = check_resources(content)
    binaries = validate_binaries(content, recipes, apply)
    if apply:
        start = content / "tq/start.ini"
        original = start.read_text(encoding="utf-8-sig")
        lines = [line for line in original.splitlines()
                 if not re.match(r"^\s*(?:server|serverip|cryptopack)\s*=", line, re.I)]
        if not start.with_name("start.ini.evejs-original").exists():
            start.with_name("start.ini.evejs-original").write_text(original, encoding="utf-8")
        start.write_text("\r\n".join(lines + ["server = 127.0.0.1", "cryptoPack = Placebo", ""]), encoding="utf-8")
    return {"format": 1, "build": BUILD, "resources": resources, "binaries": binaries,
            "client_launch_qualified": False, "network_policy": "loopback_configuration_only", "validated_at": int(time.time())}


def zip_members(archive):
    members, names, total = [], set(), 0
    for item in archive.infolist():
        name = item.filename
        path = PurePosixPath(name)
        if not name or "\\" in name or ":" in name or path.is_absolute() or any(part in (".", "..") for part in name.split("/")) or "\0" in name:
            raise ValueError("Unsafe ZIP path: " + name)
        normalized = "/".join(path.parts)
        key = normalized.casefold()
        if key in names:
            raise ValueError("Duplicate ZIP path (including case variants): " + name)
        names.add(key)
        mode = item.external_attr >> 16
        if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("ZIP links or special files are unsupported: " + name)
        if item.flag_bits & 1:
            raise ValueError("Encrypted ZIPs are unsupported")
        total += item.file_size
        if len(names) > MAX_FILES or total > MAX_BYTES or item.file_size > MAX_BYTES:
            raise ValueError("Client ZIP exceeds file count or size limits")
        members.append(item)
    return members, total


def recover_previous(content):
    content = Path(content)
    previous = content.with_name(content.name + ".previous")
    if not content.exists() and previous.exists():
        previous.replace(content)


def import_zip(archive_path, content, recipes=None):
    content = Path(content)
    content.parent.mkdir(parents=True, exist_ok=True)
    recover_previous(content)
    with zipfile.ZipFile(archive_path) as archive:
        members, total = zip_members(archive)
        if shutil.disk_usage(content.parent).free < total + 512 * 1024**2:
            raise ValueError("Not enough free internal storage to stage the complete client cache")
        staging = Path(tempfile.mkdtemp(prefix=content.name + ".import-", dir=content.parent))
        try:
            for number, item in enumerate(members, 1):
                target = staging / item.filename
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, 1024 * 1024)
                    if target.stat().st_size != item.file_size:
                        raise ValueError("ZIP entry size differs from header")
                if number % 1000 == 0:
                    print("Unpacked " + str(number) + " client files", flush=True)
            candidates = [path.parent.parent for path in staging.rglob("bin64/exefile.exe")
                          if path.parent.parent.name.lower() == "tq"]
            if len(candidates) != 1:
                raise ValueError("ZIP must contain one tq/bin64/exefile.exe and sibling ResFiles")
            cache = candidates[0].parent
            # The imported cache is normalized to one private tq/ResFiles root.
            report = validate_content(cache, recipes, apply=True)
            atomic_json(cache / "eve-client-content.json", report)
            previous = content.with_name(content.name + ".previous")
            if previous.exists():
                shutil.rmtree(previous)
            if content.exists():
                content.replace(previous)
            try:
                cache.replace(content)
            except BaseException:
                recover_previous(content)
                raise
            # Previous content remains until successful promotion and is then
            # reclaimed so a 50GB client doesn't permanently double storage.
            if previous.exists():
                shutil.rmtree(previous)
            return report
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def prepare_trust(content, state, ca_path):
    state = Path(state)
    ca_path = Path(ca_path)
    if not ca_path.is_file():
        return {"phase": "waiting_for_server_certificates", "bundles_prepared": False,
                "wine_trust_qualified": False, "message": "Prepare the server first to generate its private localhost CA"}
    ca = ca_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"-----BEGIN CERTIFICATE-----[\s\S]+-----END CERTIFICATE-----", ca):
        raise ValueError("Server CA is not a PEM certificate")
    result = subprocess.run(["openssl", "x509", "-in", str(ca_path), "-noout", "-checkend", "0"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise ValueError("Server CA validation failed: " + result.stdout.strip())
    bundles = list((Path(content) / "tq").rglob("cacert.pem"))
    if not bundles:
        raise ValueError("No cacert.pem found in client; import the complete client binaries")
    for bundle in bundles:
        contained_file(content, bundle.relative_to(content))
        original = bundle.with_name(bundle.name + ".evejs-original")
        if not original.exists():
            shutil.copyfile(bundle, original)
        if original.is_symlink():
            raise ValueError("Client CA backup must be a regular file")
        base = original.read_text(encoding="ascii").rstrip()
        bundle.write_text(base + "\n\n" + ca + "\n", encoding="ascii")
    trust = state / "trust"
    trust.mkdir(parents=True, exist_ok=True)
    (trust / "evejs-ca.pem").write_text(ca + "\n", encoding="ascii")
    return {"phase": "client_bundles_prepared", "bundles_prepared": True, "bundle_count": len(bundles),
            "ca_sha256": digest(ca_path), "wine_trust_qualified": False,
            "message": "Private client certificate bundles prepared; Wine TLS/gameplay remains to be qualified"}


def prepare_offline_preferences(state):
    """Create settings for the eventual stable Z:\\client\\tq launch location.

    This modifies only the dedicated private prefix. No Windows/Wine commands
    or client executables are run while preparing this configuration.
    """
    state = Path(state)
    settings = state / "prefix/drive_c/users/root/AppData/Local/CCP/EVE/z_client_tq_127.0.0.1/settings"
    settings.mkdir(parents=True, exist_ok=True)
    prefs = settings / "prefs.ini"
    original = prefs.read_text(encoding="cp1252") if prefs.is_file() else ""
    kept = [line for line in original.splitlines() if not re.match(r"^\s*(?:sentry_io_dsn|breakpadUpload)\s*=", line, re.I)]
    prefs.write_text("\r\n".join(kept + ["sentry_io_dsn=http://evejs@127.0.0.1:26002/1", "breakpadUpload=0", ""]), encoding="cp1252")
    policy = {"client_executable": "Z:\\client\\tq\\bin64\\exefile.exe", "cwd": "Z:\\client\\tq",
              "arguments": ["/noCrashReportUpload", "/resfileserver=http://127.0.0.1:26002/resfiles/", "/port:26000"],
              "environment": {"EO_REMOTEFILECACHEFOLDER": "Z:\\client\\ResFiles",
                              "HTTP_PROXY": "http://127.0.0.1:26002/", "HTTPS_PROXY": "http://127.0.0.1:26002/",
                              "ALL_PROXY": "http://127.0.0.1:26002/", "NO_PROXY": "127.0.0.1,localhost,::1",
                              "EVE_CLIENT_SENTRY_DSN": "http://evejs@127.0.0.1:26002/1",
                              "SSL_CERT_FILE": "Z:\\client-state\\trust\\evejs-ca.pem"},
              "launch_enabled": False, "wine_trust_qualified": False,
              "unqualified_gates": ["Wine CryptoAPI trust", "localhost443 TLS", "network containment", "DX11 renderer", "EVE login"]}
    atomic_json(state / "launch-policy.json", policy)
    return {"private_prefix_configured": True, "launch_enabled": False}


def make_x64_probe(path):
    """Build a deterministic original x64 PE that calls ExitProcess(37).

    No retail data or external compiler is involved. An exit status of37 proves
    Wine actually executed x64 code through its FEX translator, rather than only
    printing the native ARM64 Wine version.
    """
    data = bytearray(0x600)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 2, 0, 0, 0, 240, 0x22)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20b)
    struct.pack_into("<III", data, optional + 4, 0x200, 0x200, 0)
    struct.pack_into("<IIQ", data, optional + 16, 0x1000, 0x1000, 0x140000000)
    struct.pack_into("<II", data, optional + 32, 0x1000, 0x200)
    struct.pack_into("<HH", data, optional + 40, 6, 0)
    struct.pack_into("<HH", data, optional + 48, 6, 0)
    struct.pack_into("<II", data, optional + 56, 0x3000, 0x200)
    struct.pack_into("<HH", data, optional + 68, 3, 0x100)
    struct.pack_into("<QQQQII", data, optional + 72, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    struct.pack_into("<II", data, optional + 120, 0x2000, 40)
    struct.pack_into("<II", data, optional + 112 + 12 * 8, 0x2050, 16)
    section = optional + 240
    for index, (name, rva, raw, flags) in enumerate(((b".text", 0x1000, 0x200, 0x60000020), (b".rdata", 0x2000, 0x400, 0xc0000040))):
        location = section + index * 40
        data[location:location + len(name)] = name
        struct.pack_into("<IIIIIIHHI", data, location + 8, 0x200, rva, 0x200, raw, 0, 0, 0, 0, flags)
    # mov ecx,37; sub rsp,40; call [rip+IAT]; int3
    data[0x200:0x210] = b"\xb9\x25\0\0\0\x48\x83\xec\x28\xff\x15" + struct.pack("<i", 0x2050 - 0x100f) + b"\xcc"
    struct.pack_into("<IIIII", data, 0x400, 0x2040, 0, 0, 0x2060, 0x2050)
    struct.pack_into("<Q", data, 0x440, 0x2070)
    struct.pack_into("<Q", data, 0x450, 0x2070)
    data[0x460:0x46d] = b"kernel32.dll\0"
    data[0x472:0x47e] = b"ExitProcess\0"
    checksum, _ = pe_fields(data)
    struct.pack_into("<I", data, checksum, pe_checksum(data, checksum))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def write_probe_report(state, code, version):
    report = {"phase": "runtime_probe_passed" if code == 37 else "runtime_probe_failed",
              "translated_x64_probe_passed": code == 37, "exit_code": code,
              "wine_version": version, "client_launch_qualified": False,
              "message": "Wine/FEX executed the x64 probe; EVE rendering and login remain unqualified" if code == 37
                         else "Wine/FEX x64 execution failed; inspect client-probe.log", "timestamp": int(time.time())}
    atomic_json(Path(state) / "probe.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("import", "validate", "fixture", "probe-result"))
    parser.add_argument("--content", type=Path, default=Path("/client-storage/content"))
    parser.add_argument("--state", type=Path, default=Path("/client-state"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--ca", type=Path, default=Path("/server-state/certs/xmpp-ca-cert.pem"))
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--wine-version", default="")
    options = parser.parse_args(argv)
    options.state.mkdir(parents=True, exist_ok=True)
    if options.action == "fixture":
        make_x64_probe(options.state / "runtime-probe.exe")
        return 0
    if options.action == "probe-result":
        write_probe_report(options.state, options.exit_code, options.wine_version)
        return 0 if options.exit_code == 37 else 1
    try:
        atomic_json(options.state / "status.json", {"phase": "validating", "client_launch_qualified": False,
                    "message": "Checking exact client binaries and complete offline cache"})
        if options.action == "import":
            if not options.archive:
                raise ValueError("Missing import archive")
            report = import_zip(options.archive, options.content)
        else:
            recover_previous(options.content)
            report = validate_content(options.content, apply=True)
            atomic_json(options.content / "eve-client-content.json", report)
        trust = prepare_trust(options.content, options.state, options.ca)
        if trust["bundles_prepared"]:
            trust.update(prepare_offline_preferences(options.state))
        report.update(phase="content_prepared", message="Exact client and asset cache prepared; gameplay launch awaits server qualification", trust=trust)
        atomic_json(options.state / "status.json", report)
        print(json.dumps(report), flush=True)
        return 0
    except Exception as error:
        report = {"phase": "validation_failed", "error": str(error), "message": str(error), "client_launch_qualified": False}
        atomic_json(options.state / "status.json", report)
        print(json.dumps(report), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
