#!/usr/bin/env python3
"""Prove the sole new Mesa dependency exists in the unchanged pinned runtime.

Retained ELFs are disposable CI fixtures, never APK assets or source archives.
The report records their original paths and hashes; validation rereads the
actual bytes rather than relying on the build container's installed libraries.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tarfile

RUNTIME_SHA256 = "f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e"
ADDITIONAL_SONAME = "libxcb-shm.so.0"
LOADER = "ld-linux-aarch64.so.1"
SEARCH_DIRS = ("lib/aarch64-linux-gnu", "usr/lib/aarch64-linux-gnu", "lib", "usr/lib")
# This closed set is the ordinary XCB/libc dependency closure, not permission
# for arbitrary newly linked libraries in the candidate or pinned archive.
ALLOWED_CLOSURE = {ADDITIONAL_SONAME, "libxcb.so.1", "libXau.so.6", "libXdmcp.so.6",
                   "libbsd.so.0", "libmd.so.0", "libc.so.6", LOADER}
REPORT_NAME = "actual-runtime-libraries.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def readelf(path: Path, option: str) -> str:
    return subprocess.check_output(["readelf", option, "--wide", str(path)], text=True,
                                   env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def dynamic_symbols(text: str) -> tuple[set[tuple[str, str | None]], set[tuple[str, str | None]]]:
    exports, imports = set(), set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[4] not in ("GLOBAL", "WEAK"):
            continue
        name, separator, version = fields[7].replace("@@", "@").partition("@")
        symbol = (name, version if separator else None)
        if fields[6] == "UND":
            if fields[4] == "GLOBAL":
                imports.add(symbol)
        elif fields[5] in ("DEFAULT", "PROTECTED"):
            exports.add(symbol)
            # A default version also supplies an unversioned import.
            if "@@" in fields[7]:
                exports.add((name, None))
    return exports, imports


def version_info(text: str) -> tuple[dict[str, list[str]], set[str]]:
    requirements: dict[str, set[str]] = {}
    definitions: set[str] = set()
    section, provider = "", None
    for line in text.splitlines():
        if line.startswith("Version "):
            section = "needs" if line.startswith("Version needs ") else "definitions" if line.startswith("Version definition ") else ""
            provider = None
        if section == "needs":
            match = re.search(r"\bFile: (\S+)", line)
            if match:
                provider = match.group(1)
                requirements.setdefault(provider, set())
            match = re.search(r"\bName: (\S+)", line)
            if match and provider is not None:
                requirements[provider].add(match.group(1))
        elif section == "definitions":
            match = re.search(r"\bName: (\S+)", line)
            if match:
                definitions.add(match.group(1))
    return {name: sorted(values) for name, values in sorted(requirements.items())}, definitions


def inspect_elf(path: Path) -> tuple[dict, set, set, set]:
    with path.open("rb") as stream:
        header = stream.read(64)
    if (len(header) < 64 or header[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", header, 18)[0] != 183
            or struct.unpack_from("<H", header, 16)[0] != 3):
        raise ValueError("Pinned runtime proof requires an ARM64 little-endian shared ELF: " + str(path))
    dynamic = readelf(path, "--dynamic")
    sonames = re.findall(r"\(SONAME\).*Library soname: \[([^]]+)\]", dynamic)
    needed = sorted(set(re.findall(r"\(NEEDED\).*Shared library: \[([^]]+)\]", dynamic)))
    versions, definitions = version_info(readelf(path, "--version-info"))
    exports, imports = dynamic_symbols(readelf(path, "--dyn-syms"))
    interpreter = re.findall(r"Requesting program interpreter: ([^]]+)\]", readelf(path, "--program-headers"))
    if len(sonames) > 1 or len(interpreter) > 1:
        raise ValueError("Ambiguous runtime ELF identity: " + str(path))
    metadata = {"sha256": sha256_file(path), "sizeBytes": path.stat().st_size,
                "machine": "ARM64", "soname": sonames[0] if sonames else None,
                "needed": needed, "versionRequirements": versions,
                "versionDefinitions": sorted(definitions), "interpreter": interpreter[0] if interpreter else None,
                "definedDynamicSymbols": len(exports), "requiredDynamicSymbols": len(imports)}
    return metadata, exports, imports, definitions


def archive_path(value: str) -> str:
    normalized = posixpath.normpath(value.lstrip("/"))
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("Runtime archive path escapes its root")
    return normalized


def resolve_member(index: dict[str, tarfile.TarInfo], requested: str) -> tuple[str, list[dict]]:
    path, chain = requested, []
    for _ in range(40):
        parts = path.split("/")
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            member = index.get(prefix)
            if member is not None and (member.issym() or member.islnk()):
                target = member.linkname
                resolved = archive_path(target if member.islnk() or target.startswith("/")
                                        else posixpath.join(posixpath.dirname(prefix), target))
                chain.append({"path": "/" + prefix, "target": target})
                path = archive_path(posixpath.join(resolved, *parts[length:]))
                break
        else:
            if path not in index or not index[path].isfile():
                raise ValueError("Pinned runtime library is missing: /" + requested)
            if posixpath.dirname(path) not in SEARCH_DIRS:
                raise ValueError("Pinned runtime symlink leaves approved library paths: /" + path)
            return path, chain
    raise ValueError("Pinned runtime library has a cyclic symlink: /" + requested)


def verify_closure(folder: Path, report: dict) -> tuple[dict, dict]:
    if (report.get("format") != 1 or report.get("baselineRuntimeSha256") != RUNTIME_SHA256
            or report.get("approvedAdditionalSonames") != [ADDITIONAL_SONAME]
            or report.get("librarySearchDirs") != list(SEARCH_DIRS)):
        raise ValueError("Pinned runtime library proof identity changed")
    libraries = report["libraries"]
    if set(libraries) - ALLOWED_CLOSURE or not {ADDITIONAL_SONAME, LOADER}.issubset(libraries):
        raise ValueError("Pinned runtime proof does not contain the approved dependency closure")
    inspections = {}
    for soname, receipt in libraries.items():
        if receipt["file"] != "elf/" + soname or posixpath.dirname(receipt["archivePath"].lstrip("/")) not in SEARCH_DIRS:
            raise ValueError("Pinned runtime proof contains an unapproved file path")
        inspected = inspect_elf(folder / receipt["file"])
        if inspected[0] != receipt["elf"] or inspected[0]["soname"] != soname:
            raise ValueError("Pinned runtime proof ELF bytes/identity changed: " + soname)
        inspections[soname] = inspected
    reached, pending = set(), [ADDITIONAL_SONAME, LOADER]
    while pending:
        soname = pending.pop()
        if soname in reached:
            continue
        if soname not in inspections:
            raise ValueError("Pinned runtime transitive dependency is missing: " + soname)
        reached.add(soname)
        pending.extend(inspections[soname][0]["needed"])
    if reached != set(libraries):
        raise ValueError("Pinned runtime proof contains unrelated libraries")
    all_exports = set().union(*(item[1] for item in inspections.values()))
    for soname, (metadata, _exports, imports, _definitions) in inspections.items():
        if metadata["interpreter"] is not None and metadata["interpreter"] != "/lib/" + LOADER:
            raise ValueError("Pinned runtime ELF requests an unapproved loader: " + soname)
        for provider, versions in metadata["versionRequirements"].items():
            if provider not in metadata["needed"] or provider not in inspections:
                raise ValueError("Pinned runtime version provider is missing: " + soname + " " + provider)
            if not set(versions).issubset(inspections[provider][3]):
                raise ValueError("Pinned runtime dependency requires unavailable ABI versions: " + soname + " " + provider)
        missing = imports - all_exports
        if missing:
            raise ValueError("Pinned runtime closure has unresolved imported symbols: " + soname + " " + repr(sorted(missing, key=str)))
    return libraries, inspections


def extract(archive: Path, folder: Path) -> dict:
    if sha256_file(archive) != RUNTIME_SHA256:
        raise ValueError("Pinned runtime archive SHA-256 mismatch")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "elf").mkdir(exist_ok=True)
    selected = {}
    with tarfile.open(archive, "r:gz") as source:
        index = {}
        for member in source.getmembers():
            name = archive_path(member.name)
            if name in index:
                raise ValueError("Duplicate path in pinned runtime archive: " + name)
            index[name] = member
        for soname in sorted(ALLOWED_CLOSURE):
            candidates = []
            for directory in SEARCH_DIRS:
                requested = directory + "/" + soname
                try:
                    actual, chain = resolve_member(index, requested)
                except ValueError as error:
                    if requested not in index and "library is missing" in str(error):
                        continue
                    raise
                candidates.append({"requestedPath": "/" + requested, "archivePath": "/" + actual,
                                   "symlinkResolution": chain})
            if not candidates:
                continue
            if len({item["archivePath"] for item in candidates}) != 1:
                raise ValueError("Ambiguous pinned runtime library search result: " + soname)
            selected[soname] = {"file": "elf/" + soname, "archivePath": candidates[0]["archivePath"],
                                "searchPaths": candidates}
        # Read selected members in archive order, avoiding repeated backwards
        # seeks through the compressed runtime. No archive member is installed.
        for soname in sorted(selected, key=lambda name: index[selected[name]["archivePath"].lstrip("/")].offset_data):
            member = index[selected[soname]["archivePath"].lstrip("/")]
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("Cannot read actual pinned runtime ELF")
            with stream, (folder / selected[soname]["file"]).open("wb") as target:
                shutil.copyfileobj(stream, target)
    for soname, receipt in selected.items():
        receipt["elf"] = inspect_elf(folder / receipt["file"])[0]
    reached, pending = set(), [ADDITIONAL_SONAME, LOADER]
    while pending:
        soname = pending.pop()
        if soname in reached:
            continue
        if soname not in selected or soname not in ALLOWED_CLOSURE:
            raise ValueError("Pinned runtime lacks the closed dependency/loader set: " + soname)
        reached.add(soname)
        pending.extend(selected[soname]["elf"]["needed"])
    for soname in set(selected) - reached:
        (folder / selected[soname]["file"]).unlink()
        del selected[soname]
    report = {"format": 1, "qualification": "actual-pinned-runtime-elf-dependency-closure",
              "baselineRuntimeSha256": RUNTIME_SHA256,
              "approvedAdditionalSonames": [ADDITIONAL_SONAME], "librarySearchDirs": list(SEARCH_DIRS),
              "libraries": selected, "transitiveDependenciesVerified": True,
              "loaderVerified": True, "symbolVersionsVerified": True,
              "requiredSymbolsVerified": True, "runtimeLibrariesInstalled": False}
    verify_closure(folder, report)
    (folder / REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n")
    return report


def validate_candidate(candidate: Path, folder: Path) -> dict:
    report = json.loads((folder / REPORT_NAME).read_text())
    _libraries, inspections = verify_closure(folder, report)
    metadata, _exports, imports, _definitions = inspect_elf(candidate)
    if ADDITIONAL_SONAME not in metadata["needed"]:
        raise ValueError("Candidate does not need the dependency this proof authorizes")
    required = {symbol for symbol in imports if symbol[0].startswith("xcb_shm_")}
    # Linker section collection can retain an upstream NEEDED entry after its
    # SHM callers are discarded. An empty import set adds no symbol requirement;
    # the actual library/loader dependency closure is still verified above.
    available = inspections[ADDITIONAL_SONAME][1]
    missing = required - available
    if missing:
        raise ValueError("Candidate requires unavailable pinned runtime xcb_shm symbols: "
                         + json.dumps({"required": sorted(required, key=str),
                                       "missing": sorted(missing, key=str),
                                       "available": sorted((symbol for symbol in available
                                                            if symbol[0].startswith("xcb_shm_")), key=str)}))
    versions = metadata["versionRequirements"].get(ADDITIONAL_SONAME, [])
    if not set(versions).issubset(inspections[ADDITIONAL_SONAME][3]):
        raise ValueError("Candidate requires a newer pinned runtime xcb-shm ABI: "
                         + json.dumps({"required": versions,
                                       "available": sorted(inspections[ADDITIONAL_SONAME][3])}))
    return {"baselineRuntimeSha256": RUNTIME_SHA256, "report": REPORT_NAME,
            "reportSha256": sha256_file(folder / REPORT_NAME), "additionalSoname": ADDITIONAL_SONAME,
            "actualRuntimeLibrary": report["libraries"][ADDITIONAL_SONAME],
            "candidateRequiredSymbols": [{"name": name, "version": version}
                                         for name, version in sorted(required, key=str)],
            "candidateSymbolsVerified": True, "transitiveDependenciesVerified": True,
            "loaderVerified": True, "symbolVersionsVerified": True,
            "runtimeLibrariesInstalled": False}


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "extract":
        extract(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit("usage: check-mesa262-runtime-libraries.py extract PINNED_ARCHIVE PROOF_FOLDER")
