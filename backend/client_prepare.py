#!/usr/bin/env python3
"""Prepare a private, exact-build EVE cache without launching any retail client.

PE patch semantics and JSON recipes are adapted from EveJS v0.12.9
tools/ClientSETUP (AGPL-3.0). See docs/CLIENT-RUNTIME.md and upstream source.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

BUILD = 3396210
MAX_FILES = 1_000_000
MAX_BYTES = 160 * 1024**3
RECIPE_DIR = Path(__file__).resolve().parent
RECIPES = ("blue_patch_recipe.json", "launchdarkly_patch_recipe.json", "crash_upload_patch_recipe.json")
RESOURCE_NAME = re.compile(r"^[0-9a-fA-F]{2}/[0-9a-fA-F]+_[0-9a-fA-F]+$")
MAX_INDEX_LINE = 16 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
PREPARATION_MEMORY_MIB = 512


def bounded_text(path, encoding="utf-8", limit=MAX_TEXT_BYTES):
    if Path(path).stat().st_size > limit:
        raise ValueError("Client metadata exceeds size limit: " + Path(path).name)
    with Path(path).open(encoding=encoding) as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Client metadata exceeds size limit: " + Path(path).name)
    return value


def memory_snapshot():
    result = {}
    for label, pid in (("worker", os.getpid()), ("parent", os.getppid())):
        try:
            with open("/proc/" + str(pid) + "/status") as source:
                for line in source:
                    key, _, value = line.partition(":")
                    if key in ("VmRSS", "VmHWM", "VmSize"):
                        result[label + key + "KiB"] = int(value.split()[0])
        except (OSError, ValueError):
            pass
    return result


def preparation_progress(state, phase, message, **details):
    report = {"phase": phase, "message": message, "client_launch_qualified": False,
              "memory": memory_snapshot(), "updated_at": int(time.time()), **details}
    atomic_json(Path(state) / "status.json", report)
    print(message + " | memory=" + json.dumps(report["memory"], sort_keys=True), flush=True)


def limit_preparation_memory(mib):
    if not 128 <= mib <= PREPARATION_MEMORY_MIB:
        raise ValueError("Preparation memory limit must be between 128 and 512 MiB")
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    requested = mib * 1024**2
    if soft != resource.RLIM_INFINITY:
        requested = min(requested, soft)
    if hard != resource.RLIM_INFINITY:
        requested = min(requested, hard)
    resource.setrlimit(resource.RLIMIT_AS, (requested, hard))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def certificate_sha256(path):
    """Identify one PEM certificate by DER, independent of text line endings."""
    pem = bounded_text(path, encoding="ascii").strip()
    match = re.fullmatch(r"-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]+)-----END CERTIFICATE-----", pem)
    if not match:
        raise ValueError("Local server CA is not a single PEM certificate")
    der = base64.b64decode("".join(match.group(1).split()), validate=True)
    if not der:
        raise ValueError("Local server CA certificate is empty")
    return hashlib.sha256(der).hexdigest()


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
    for line in bounded_text(path, encoding="utf-8-sig").splitlines():
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


def read_binary(path, recipe, original=False):
    sizes = {recipe["source"]["size"]}
    sizes.update(item["size"] for item in recipe.get("knownPatchedVariants", []))
    size = path.stat().st_size
    # Deterministic signature-stripped outputs may have a smaller size. They
    # still require an exact immutable backup and byte-for-byte recomputation.
    backup = path.with_name(path.name + ".evejs-original")
    if size <= 0 or size > max(sizes) or (size not in sizes and (original or not backup.is_file())):
        raise ValueError("Unsupported binary size for " + recipe["source"]["filename"] + "; requires build3396210")
    if original and size != recipe["source"]["size"]:
        raise ValueError("Unsupported original binary size: " + path.name)
    return path.read_bytes()


def validate_binaries(content, recipes=None, apply=False, progress=None):
    recipes = recipes if recipes is not None else load_recipes()
    planned, report = [], []
    # Keep proposed outputs on disk. Only one small, size-checked binary and
    # its patch buffer are resident at a time, rather than all before/after pairs.
    with tempfile.TemporaryDirectory(prefix="eve-binary-plan-") as temporary:
        for number, recipe in enumerate(recipes):
            filename = recipe["source"]["filename"]
            if progress:
                progress("checking_binaries", "Checking exact binary " + filename)
            target = contained_file(content, Path("tq/bin64") / filename)
            before = read_binary(target, recipe)
            backup = target.with_name(target.name + ".evejs-original")
            try:
                after, state = patch_bytes(before, recipe)
            except ValueError:
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
                    expected, _ = patch_bytes(read_binary(backup, recipe, original=True), recipe)
                    if expected != before:
                        raise ValueError("Client binary differs from exact recipe output: " + filename)
                    after, state = before, "verified_original_backup"
                    del expected
            before_sha = hashlib.sha256(before).hexdigest()
            after_sha = hashlib.sha256(after).hexdigest()
            report.append({"file": filename, "state": state, "sha256": after_sha})
            if apply and before != after:
                pending = Path(temporary) / str(number)
                pending.write_bytes(after)
                planned.append((target, pending, backup, before_sha))
            del before, after
        # Check all inputs and backups before replacing any client binary.
        for target, pending, backup, before_sha in planned:
            if digest(target) != before_sha:
                raise ValueError("Client binary changed during validation: " + target.name)
            if backup.exists() and (backup.is_symlink() or digest(backup) != before_sha):
                raise ValueError("Refusing to overwrite original binary backup: " + target.name)
        for target, pending, backup, before_sha in planned:
            if not backup.exists():
                shutil.copyfile(target, backup)
            output = target.with_name(target.name + ".evejs-tmp")
            shutil.copyfile(pending, output)
            output.replace(target)
    return report


def check_resources(content, progress=None):
    """Check both authoritative indexes using bounded reads and disk-backed names.

    Resource size/hash fields remain uninterpreted, matching the upstream gate.
    ZIP CRC verifies imported bytes. Every distinct indexed path must be a
    regular file; safe shard directories are checked once instead of resolving
    the entire root and all parents through PRoot for every resource reference.
    """
    content = Path(content).resolve()
    resource_root = content / "ResFiles"
    if not resource_root.is_dir() or resource_root.is_symlink():
        raise ValueError("Missing ResFiles beside tq; import the complete shared cache")
    contained_file(content, "index_tranquility.txt")
    checked, shards = 0, set()
    with tempfile.TemporaryDirectory(prefix="eve-resource-index-") as temporary:
        with sqlite3.connect(str(Path(temporary) / "names.sqlite")) as names:
            names.execute("PRAGMA cache_size=-2048")
            names.execute("PRAGMA journal_mode=OFF")
            names.execute("PRAGMA temp_store=FILE")
            names.execute("CREATE TABLE resources(name TEXT PRIMARY KEY) WITHOUT ROWID")
            for name in ("resfileindex.txt", "resfileindex_Windows.txt"):
                if progress:
                    progress("checking_resources", "Checking " + name, indexed_entries=checked)
                index = contained_file(content, Path("tq") / name)
                count = 0
                with index.open(encoding="utf-8-sig") as source:
                    line_number = 0
                    while True:
                        line = source.readline(MAX_INDEX_LINE + 1)
                        if not line:
                            break
                        line_number += 1
                        if len(line) > MAX_INDEX_LINE:
                            raise ValueError("Oversized " + name + " entry " + str(line_number))
                        if not line.strip():
                            continue
                        fields = line.strip().split(",")
                        if len(fields) != 5 or not fields[0].startswith("res:/") or not RESOURCE_NAME.fullmatch(fields[1]):
                            raise ValueError("Malformed " + name + " entry " + str(line_number))
                        inserted = names.execute("INSERT OR IGNORE INTO resources VALUES (?)", (fields[1],)).rowcount
                        if inserted:
                            shard = fields[1].split("/", 1)[0]
                            directory = resource_root / shard
                            if shard not in shards:
                                if directory.is_symlink():
                                    raise ValueError("Symbolic links are not permitted in imported client content: ResFiles/" + shard)
                                if not directory.is_dir():
                                    raise ValueError("Missing client file: ResFiles/" + fields[1])
                                shards.add(shard)
                            asset = resource_root / fields[1]
                            try:
                                mode = asset.lstat().st_mode
                            except FileNotFoundError:
                                raise ValueError("Missing client file: ResFiles/" + fields[1]) from None
                            if stat.S_ISLNK(mode):
                                raise ValueError("Symbolic links are not permitted in imported client content: ResFiles/" + fields[1])
                            if not stat.S_ISREG(mode):
                                raise ValueError("Missing client file: ResFiles/" + fields[1])
                        checked += 1
                        count += 1
                        if checked > MAX_FILES * 2:
                            raise ValueError("Too many indexed resources")
                        if progress and checked % 1000 == 0:
                            progress("checking_resources", "Checked " + str(checked) + " indexed resources", indexed_entries=checked)
                if count == 0:
                    raise ValueError("Empty resource index: " + name)
            unique = names.execute("SELECT COUNT(DISTINCT lower(name)) FROM resources").fetchone()[0]
    return {"indexed_entries": checked, "unique_resources": unique, "complete": True}


def validate_content(content, recipes=None, apply=False, progress=None):
    content = Path(content)
    values = ini_values(contained_file(content, "tq/start.ini"))
    if values.get("build") != str(BUILD):
        raise ValueError("Requires EVE 24.01 build3396210; found " + values.get("build", "no build"))
    resources = check_resources(content, progress)
    binaries = validate_binaries(content, recipes, apply, progress)
    if apply:
        start = content / "tq/start.ini"
        original = bounded_text(start, encoding="utf-8-sig")
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


def archive_cache_root(members):
    candidates = [PurePosixPath(item.filename).parent.parent.parent
                  for item in members if not item.is_dir()
                  and PurePosixPath(item.filename).parts[-3:] == ("tq", "bin64", "exefile.exe")]
    if len(candidates) != 1:
        raise ValueError("ZIP must contain one tq/bin64/exefile.exe and sibling ResFiles")
    return candidates[0]


def reusable_entry(path, item):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("Unsafe existing import entry: " + item.filename)
    if path.stat().st_size != item.file_size:
        return False
    crc = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            crc = zlib.crc32(chunk, crc)
    return (crc & 0xffffffff) == item.CRC


def ensure_import_directory(staging, directory, checked):
    relative = directory.relative_to(staging)
    current = staging
    for part in relative.parts:
        current = current / part
        if current in checked:
            continue
        if current.is_symlink():
            raise ValueError("Unsafe existing import directory: " + str(relative))
        current.mkdir(exist_ok=True)
        if not current.is_dir():
            raise ValueError("Invalid import directory: " + str(relative))
        checked.add(current)


def import_zip(archive_path, content, recipes=None, resume=False, progress=None, session_path=None):
    content = Path(content)
    archive_path = Path(archive_path)
    content.parent.mkdir(parents=True, exist_ok=True)
    recover_previous(content)
    session_path = Path(session_path) if session_path else content.with_name(content.name + ".import-session.json")
    identity = {"size": archive_path.stat().st_size, "mtime_ns": archive_path.stat().st_mtime_ns}
    stages = sorted((path for path in content.parent.glob(content.name + ".import-*")
                     if path.is_dir() and not path.is_symlink()), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    stages = [path for path in stages if path != session_path]
    previous_session = {}
    if resume and session_path.is_file():
        try:
            previous_session = json.loads(bounded_text(session_path))
        except (ValueError, OSError):
            pass
    chosen = next((path for path in stages if path.name == previous_session.get("staging")), None)
    if chosen is None and resume and stages:
        # 0.1.0 left no recovery receipt. Reuse only after each file's size and
        # ZIP CRC is verified; a log saying "Unpacked" is never sufficient.
        chosen = stages[0]
    if not resume:
        for path in stages:
            shutil.rmtree(path)
    staging = chosen if chosen is not None else Path(tempfile.mkdtemp(prefix=content.name + ".import-", dir=content.parent))
    trusted_extraction = (resume and previous_session.get("archive") == identity
                          and previous_session.get("staging") == staging.name
                          and previous_session.get("phase") == "extracted")
    with zipfile.ZipFile(archive_path) as archive:
        members, total = zip_members(archive)
        relative_cache = archive_cache_root(members)
        if not trusted_extraction:
            # Reused complete files need no additional space. Check remaining
            # space per copied chunk instead of demanding a second full cache.
            if not resume and shutil.disk_usage(content.parent).free < total + 512 * 1024**2:
                raise ValueError("Not enough free internal storage to stage the complete client cache")
            atomic_json(session_path, {"schemaVersion": 1, "archive": identity, "staging": staging.name, "phase": "extracting"})
            checked_directories = set()
            reused = 0
            for number, item in enumerate(members, 1):
                target = staging / item.filename
                ensure_import_directory(staging, target if item.is_dir() else target.parent, checked_directories)
                if not item.is_dir():
                    if resume and reusable_entry(target, item):
                        reused += 1
                    else:
                        if target.is_symlink():
                            raise ValueError("Unsafe existing import entry: " + item.filename)
                        with archive.open(item) as source, target.open("wb") as destination:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                if shutil.disk_usage(content.parent).free < len(chunk) + 512 * 1024**2:
                                    raise ValueError("Not enough free internal storage to finish the client import")
                                destination.write(chunk)
                        if target.stat().st_size != item.file_size:
                            raise ValueError("ZIP entry size differs from header")
                if number % 1000 == 0 or number == len(members):
                    message = ("Verified/reused " if resume else "Unpacked ") + str(number) + " client files"
                    if progress:
                        progress("extracting", message, processed_files=number, total_files=len(members), reused_files=reused)
                    else:
                        print(message, flush=True)
            atomic_json(session_path, {"schemaVersion": 1, "archive": identity, "staging": staging.name, "phase": "extracted"})
        else:
            if progress:
                progress("extracting", "Resuming validation of the fully extracted client cache")
        # ZIP metadata is no longer needed during resource/binary validation.
        del members
    del archive
    cache = staging / relative_cache
    report = validate_content(cache, recipes, apply=True, progress=progress)
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
    if previous.exists():
        shutil.rmtree(previous)
    if staging.exists():
        shutil.rmtree(staging)
    session_path.unlink(missing_ok=True)
    return report


def prepare_trust(content, state, ca_path):
    state = Path(state)
    ca_path = Path(ca_path)
    if not ca_path.is_file():
        return {"phase": "waiting_for_server_certificates", "bundles_prepared": False,
                "wine_trust_qualified": False, "message": "Prepare the server first to generate its private localhost CA"}
    ca = bounded_text(ca_path, encoding="ascii").strip()
    ca_der_sha256 = certificate_sha256(ca_path)
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
        base = bounded_text(original, encoding="ascii").rstrip()
        bundle.write_text(base + "\n\n" + ca + "\n", encoding="ascii")
    trust = state / "trust"
    trust.mkdir(parents=True, exist_ok=True)
    (trust / "evejs-ca.pem").write_text(ca + "\n", encoding="ascii")
    return {"phase": "client_bundles_prepared", "bundles_prepared": True, "bundle_count": len(bundles),
            "ca_sha256": digest(ca_path), "ca_der_sha256": ca_der_sha256, "wine_trust_qualified": False,
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
    original = bounded_text(prefs, encoding="cp1252") if prefs.is_file() else ""
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
    parser.add_argument("action", choices=("import", "resume", "validate", "fixture", "probe-result"))
    parser.add_argument("--content", type=Path, default=Path("/client-storage/content"))
    parser.add_argument("--state", type=Path, default=Path("/client-state"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--ca", type=Path, default=Path("/server-state/certs/xmpp-ca-cert.pem"))
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--wine-version", default="")
    parser.add_argument("--memory-limit-mib", type=int, default=PREPARATION_MEMORY_MIB)
    options = parser.parse_args(argv)
    options.state.mkdir(parents=True, exist_ok=True)
    if options.action == "fixture":
        make_x64_probe(options.state / "runtime-probe.exe")
        return 0
    if options.action == "probe-result":
        write_probe_report(options.state, options.exit_code, options.wine_version)
        return 0 if options.exit_code == 37 else 1
    try:
        limit_preparation_memory(options.memory_limit_mib)
        progress = lambda phase, message, **details: preparation_progress(options.state, phase, message, **details)
        progress("extracting" if options.action in ("import", "resume") else "validating",
                 "Resuming client import" if options.action == "resume" else "Preparing exact client cache",
                 memory_limit_mib=options.memory_limit_mib)
        if options.action in ("import", "resume"):
            if not options.archive:
                raise ValueError("Missing import archive")
            report = import_zip(options.archive, options.content, resume=options.action == "resume",
                                progress=progress, session_path=options.state / "import-session.json")
        else:
            recover_previous(options.content)
            report = validate_content(options.content, apply=True, progress=progress)
            atomic_json(options.content / "eve-client-content.json", report)
        progress("preparing_trust", "Preparing private client certificate bundles")
        trust = prepare_trust(options.content, options.state, options.ca)
        if trust["bundles_prepared"]:
            trust.update(prepare_offline_preferences(options.state))
        report.update(memory=memory_snapshot(), memory_limit_mib=options.memory_limit_mib, phase="content_prepared", message="Exact client and asset cache prepared. Start the server, then Start EVE client.", trust=trust)
        atomic_json(options.state / "status.json", report)
        print(json.dumps(report), flush=True)
        return 0
    except Exception as error:
        message = ("Client preparation reached its memory limit. Resume the interrupted import after freeing memory."
                   if isinstance(error, MemoryError) else str(error))
        report = {"phase": "validation_failed", "error": message, "message": message,
                  "memory": memory_snapshot(), "client_launch_qualified": False}
        atomic_json(options.state / "status.json", report)
        print(json.dumps(report), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
