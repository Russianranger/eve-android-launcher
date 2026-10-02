#!/usr/bin/env python3
"""Verify and materialize the pinned upstream source archive for CI/builds."""
import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

RETAINED = ("LICENSE", "README.md", "UPSTREAM.json")
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 100_000


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verified_archive(pin: dict, vendor: Path) -> tuple[Path, bool]:
    """Assemble individually pinned upload-sized shards before verifying the tar."""
    if pin["file"] != "../evejs-source.tar.gz":
        raise ValueError("The pinned source archive must be vendor/evejs-source.tar.gz")
    if pin.get("format") != "gnu-tar-gzip":
        raise ValueError("Unsupported EVE.js source archive format")
    if not isinstance(pin["sizeBytes"], int) or not 0 < pin["sizeBytes"] <= MAX_SOURCE_BYTES:
        raise ValueError("Invalid source archive size")
    temporary = False
    archive = vendor / "evejs-source.tar.gz"
    try:
        if "parts" in pin:
            if not pin["parts"] or len(pin["parts"]) > 1000:
                raise ValueError("Invalid source archive shard list")
            with tempfile.NamedTemporaryFile(prefix=".evejs-source-", suffix=".tar.gz", dir=vendor,
                                             delete=False) as assembled:
                archive = Path(assembled.name)
                temporary = True
                for index, part in enumerate(pin["parts"], 1):
                    expected_name = f"../evejs-source.tar.gz.part{index:02d}"
                    if part["file"] != expected_name:
                        raise ValueError("Source archive shards must be ordered sequentially")
                    shard = vendor / expected_name.removeprefix("../")
                    if shard.is_symlink() or shard.stat().st_size != part["sizeBytes"]:
                        raise ValueError(f"Source archive shard size mismatch: {shard.name}")
                    digest = hashlib.sha256()
                    with shard.open("rb") as content:
                        while chunk := content.read(1024 * 1024):
                            digest.update(chunk)
                            assembled.write(chunk)
                    if digest.hexdigest() != part["sha256"]:
                        raise ValueError(f"Source archive shard SHA-256 mismatch: {shard.name}")
                    if assembled.tell() > pin["sizeBytes"]:
                        raise ValueError("Source archive shards exceed the pinned overall size")
        elif archive.is_symlink():
            raise ValueError("The source archive must not be a symlink")
        if archive.stat().st_size != pin["sizeBytes"]:
            raise ValueError("EVE.js source archive size mismatch")
        if file_sha256(archive) != pin["sha256"]:
            raise ValueError("EVE.js source archive SHA-256 mismatch")
        return archive, temporary
    except BaseException:
        if temporary:
            archive.unlink(missing_ok=True)
        raise


def materialize(root: Path) -> dict:
    root = root.resolve()
    vendor = root / "vendor"
    destination = vendor / "evejs"
    if destination.is_symlink():
        raise ValueError("The source destination must not be a symlink")
    metadata = json.loads((destination / "UPSTREAM.json").read_text())
    pin = metadata["sourceArchive"]
    archive, temporary_archive = verified_archive(pin, vendor)
    staging = Path(tempfile.mkdtemp(prefix=".evejs-materialize-", dir=vendor))
    backup = vendor / (staging.name + "-previous")
    source_bytes = 0
    entry_count = 0
    seen = set()
    try:
        with tarfile.open(archive, "r|gz") as source:
            for entry in source:
                path = PurePosixPath(entry.name)
                if path.as_posix() in (".", "") and entry.isdir():
                    continue
                if path.is_absolute() or ".." in path.parts or "\\" in entry.name:
                    raise ValueError(f"Unsafe source archive path: {entry.name}")
                if not path.parts or path.as_posix() in RETAINED:
                    raise ValueError(f"Archive cannot replace retained provenance: {entry.name}")
                if not (entry.isdir() or entry.isfile()):
                    raise ValueError(f"Links and special entries are unsupported: {entry.name}")
                if path.as_posix() in seen:
                    raise ValueError(f"Duplicate source archive entry: {entry.name}")
                seen.add(path.as_posix())
                entry_count += 1
                source_bytes += entry.size
                if entry_count > MAX_ENTRIES or source_bytes > MAX_SOURCE_BYTES:
                    raise ValueError("Source archive exceeds the allowed extraction size")
                output = staging.joinpath(*path.parts)
                if entry.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    output.chmod(0o755)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    content = source.extractfile(entry)
                    if content is None:
                        raise ValueError(f"Missing source entry data: {entry.name}")
                    with content, output.open("wb") as handle:
                        shutil.copyfileobj(content, handle)
                    output.chmod(entry.mode & 0o777)
                    os.utime(output, (0, 0))
        if entry_count == 0:
            raise ValueError("Empty source archive")
        for name in RETAINED:
            original = destination / name
            if not original.is_file() or original.is_symlink():
                raise ValueError(f"Missing retained source provenance: {name}")
            shutil.copy2(original, staging / name)
        # Replace the complete tree so removed or stale files cannot silently
        # affect runtime provenance. The prior tree remains intact on failure.
        destination.replace(backup)
        try:
            staging.replace(destination)
        except BaseException:
            backup.replace(destination)
            raise
        shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary_archive:
            archive.unlink(missing_ok=True)
    return {"sha256": pin["sha256"], "entries": entry_count,
            "sourceBytes": source_bytes, "destination": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    arguments = parser.parse_args()
    print(json.dumps(materialize(arguments.repo_root), sort_keys=True))
