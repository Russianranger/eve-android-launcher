#!/usr/bin/env python3
"""Build native accepted/candidate PRoot fixtures from the pinned prepared source."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


TALLOC_SHA256 = "dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd"
PROOT_COMMIT = "7266fb3e8516535682f5a9c8f3a7e70f6506eddb"


def run(command, cwd, log):
    with log.open("a") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Native fixture build failed: {command[0]}\n" + log.read_text()[-8000:])


def verify(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Source digest differs for {path.name}: {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    prepared = args.prepared.resolve()
    actual_commit = subprocess.check_output(["git", "-C", str(prepared / "proot"), "rev-parse", "HEAD"], text=True).strip()
    if actual_commit != PROOT_COMMIT:
        raise RuntimeError("The prepared source is not the pinned PRoot revision")
    talloc_tar = prepared / "talloc.tar.gz"
    verify(talloc_tar, TALLOC_SHA256)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = work / "source"
    source.mkdir()
    shutil.copytree(prepared / "proot", source / "proot", ignore=shutil.ignore_patterns(".git"))
    run(["tar", "--no-same-owner", "-xzf", str(talloc_tar)], work, work / "extract.log")
    prefix = work / "prefix"
    (prefix / "include").mkdir(parents=True)
    (prefix / "lib").mkdir(parents=True)
    talloc = work / "talloc-2.4.3"
    run(["./configure", "--prefix=" + str(prefix), "--disable-rpath", "--disable-python"],
        talloc, work / "talloc-build.log")
    run(["make", "-j2"], talloc, work / "talloc-build.log")
    shutil.copy2(talloc / "talloc.h", prefix / "include/talloc.h")
    objects = sorted((talloc / "bin/default").glob("talloc*.o"))
    if not objects:
        raise RuntimeError("The talloc build produced no archive objects")
    run(["ar", "rcs", str(prefix / "lib/libtalloc.a")] + [str(path) for path in objects],
        work, work / "talloc-build.log")
    proot = source / "proot"
    callback = proot / "src/extension/eve_client_network/eve_client_network.c"
    original = callback.read_text()
    before = ("\t\t{ PR_connect, FILTER_SYSEXIT }, { PR_bind, FILTER_SYSEXIT },\n"
              "\t\t{ PR_sendto, FILTER_SYSEXIT }, { PR_sendmsg, FILTER_SYSEXIT },")
    after = ("\t\t{ PR_connect, 0 }, { PR_bind, 0 },\n"
             "\t\t{ PR_sendto, 0 }, { PR_sendmsg, 0 },")
    if original.count(after) != 1:
        raise RuntimeError("Candidate source has an unexpected network filter layout")
    candidate_sha = hashlib.sha256(callback.read_bytes()).hexdigest()
    callback.write_text(original.replace(after, before))
    loader = proot / "src/loader/loader"
    command = ["make", "-C", "src", "-j2", "CC=cc", "LD=cc", "STRIP=strip",
               "OBJCOPY=objcopy", "OBJDUMP=objdump",
               "CPPFLAGS=-D_FILE_OFFSET_BITS=64 -D_GNU_SOURCE -I. -I" + str(proot / "src") + " -I" + str(prefix / "include"),
               "LDFLAGS=-L" + str(prefix / "lib") + " -ltalloc -Wl,-z,noexecstack",
               "PROOT_UNBUNDLE_LOADER=" + str(loader)]
    run(command, proot, work / "proot-build.log")
    baseline = work / "proot-baseline"
    shutil.copy2(proot / "src/proot", baseline)
    callback.write_text(original)
    run(command, proot, work / "proot-entry-only-build.log")
    candidate = work / "proot-entry-only"
    shutil.copy2(proot / "src/proot", candidate)
    manifest = {"format": 1, "architecture": os.uname().machine,
                "prootCommit": PROOT_COMMIT, "tallocSha256": TALLOC_SHA256,
                "candidateNetworkSourceSha256": candidate_sha,
                "baseline": str(baseline), "candidate": str(candidate), "loader": str(loader),
                "change": "Only bind/connect/sendto/sendmsg filter flags changed to entry-only.",
                "sendmmsgExitCopybackRetained": True}
    (work / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
