#!/usr/bin/env python3
"""Reject APK publication from a branch missing the delivered development baseline."""
import re
import subprocess
from pathlib import Path

BASELINE = "6fcf6b20c5b6b538ae6bb30ed90af41d6f9829e4"


def version(source):
    code = re.search(r"\bversionCode\s+(\d+)\b", source)
    name = re.search(r"\bversionName\s+'(\d+\.\d+\.\d+)'", source)
    if not code or not name:
        raise ValueError("Missing release version identity")
    return int(code[1]), tuple(map(int, name[1].split(".")))


def check(root, baseline=BASELINE):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()

    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", baseline, "HEAD"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError("Release does not include the delivered development baseline; fetch full history and integrate it")
    previous = version(git("show", f"{baseline}:app/build.gradle"))
    current = version((root / "app/build.gradle").read_text())
    if current[0] <= previous[0] or current[1] <= previous[1]:
        raise ValueError("Release version must be newer than the delivered development baseline")
    workflow = (root / ".github/workflows/build.yml").read_text()
    expected = ".".join(map(str, current[1]))
    if not re.search(r"EVE_APP_VERSION:\s*'" + re.escape(expected) + "'", workflow):
        raise ValueError("Workflow and APK versions differ")
    print(f"Release {expected}/code {current[0]} includes delivered baseline {baseline}")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
