#!/usr/bin/env python3
"""Execute real CryptoAPI cases in a disposable, caller-selected Wine prefix.

Compile native/eve-wine-trust-test.c as aarch64 PE for the native ARM Wine
runtime. The caller supplies DISPLAY, WINEPREFIX and any runtime library paths.
Use --expect-unpatched before applying the DLL overlay to reproduce the original
failure; it runs just the three valid empty-subject cases and requires the exact
excluded-name error. The normal run requires all 13 correct outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def run(args) -> None:
    if not os.environ.get("WINEPREFIX"):
        raise SystemExit("Set a disposable WINEPREFIX for this test")
    cases = json.loads((args.fixtures / "cases.json").read_text())
    if args.expect_unpatched:
        cases = [case for case in cases if case["expected_pass"]]
    reports = []
    for case in cases:
        root = "Z:" + str((args.fixtures / "root.der").resolve()).replace("/", "\\")
        leaf = "Z:" + str((args.fixtures / case["leaf"]).resolve()).replace("/", "\\")
        process = subprocess.run([str(args.wine), str(args.helper.resolve()), root, leaf, case["hostname"]],
                                 capture_output=True, text=True, timeout=90)
        results = []
        for line in process.stdout.splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "completed" in parsed:
                results.append(parsed)
        if process.returncode or len(results) != 1 or not results[0].get("completed"):
            raise AssertionError(f"{case['name']}: probe did not complete ({process.returncode})\n"
                                 + process.stdout + process.stderr)
        result = results[0]
        expected = False if args.expect_unpatched else case["expected_pass"]
        required_bits = 0x8000 if args.expect_unpatched else case["required_chain_bits"]
        if result["pass"] is not expected:
            raise AssertionError(f"{case['name']}: expected pass={expected}, received {result}\n"
                                 + process.stderr)
        if required_bits and not result["chain_error_status"] & required_bits:
            raise AssertionError(f"{case['name']}: missing expected chain error {required_bits:#x}: {result}")
        if expected and (not result["exact_root"] or result["chain_elements"] != 2):
            raise AssertionError(f"{case['name']}: did not build the exact two-certificate private chain: {result}")
        if case["name"] == "wrong-hostname" and not result["ssl_policy_error"]:
            raise AssertionError("Wrong hostname was not rejected by SSL policy")
        if case["name"] == "untrusted-issuer" and result["exact_root"]:
            raise AssertionError("Foreign issuer matched the private CA")
        reports.append({"case": case["name"], "expected_pass": expected, **result})
        print(json.dumps(reports[-1], sort_keys=True), flush=True)
    if args.output:
        args.output.write_text(json.dumps({"mode": "unpatched" if args.expect_unpatched else "patched",
                                          "cases": reports, "passed": True}, indent=2) + "\n")
    print(f"Wine certificate regression passed: {len(reports)} real CryptoAPI cases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wine", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-unpatched", action="store_true")
    run(parser.parse_args())
