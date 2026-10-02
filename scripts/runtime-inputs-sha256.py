#!/usr/bin/env python3
"""Fingerprint packaged server inputs; bound launcher scripts remain APK inputs."""
from hashlib import sha256
from pathlib import Path


def fingerprint(root: Path) -> str:
    files = [p for directory in ("server-runtime", "vendor/evejs")
             for p in (root / directory).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    files += [root / name for name in (
        "scripts/build-server-runtime.sh", "scripts/check-server-package.py",
        "scripts/check-server-runtime.py", "scripts/package-runtime.py",
        "tests/server-package-tests.py", "scripts/prepare-evejs-source.py",
        "scripts/runtime-inputs-sha256.py")]
    digest = sha256()
    for path in sorted(set(files), key=lambda p: p.relative_to(root).as_posix()):
        if not path.is_file():
            raise FileNotFoundError(path)
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


if __name__ == "__main__":
    print(fingerprint(Path(__file__).resolve().parent.parent))
