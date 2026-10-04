#!/usr/bin/env python3
"""Qualify the packaged x64 window launcher with a disposable Wine/FEX game.

Run only inside the native ARM64 graphics qualification container. The fixed
production game path contains an original fixture here, never retail content.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time


OUT = Path("/graphics-out")
WINE = "/opt/wine/bin/wine"
SERVER = "/opt/wine/bin/wineserver"
HELPER = OUT / "assets/eve-client-window.exe"
GAME = Path("/client/tq/bin64/exefile.exe")
RECEIPT = Path("/client-state/run/client-window.json")
FIXTURE_RECEIPT = Path("/client-state/run/client-window-fixture.json")


def record(pid: int) -> dict | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rfind(")") + 2:].split()
        return {"pid": pid, "group": int(fields[2]), "session": int(fields[3]),
                "startTicks": fields[19]}
    except (OSError, IndexError, ValueError):
        return None


def run_case(name: str, wrapper: bool, expected_exit: int, extra_env: dict | None = None) -> dict:
    RECEIPT.unlink(missing_ok=True)
    FIXTURE_RECEIPT.unlink(missing_ok=True)
    nonce = secrets.token_hex(16)
    env = dict(os.environ, EVE_WINDOW_SESSION=nonce)
    env.pop("EVE_WINDOW_FIXTURE_HUNG", None)
    env.update(extra_env or {})
    env.pop("DXVK_HUD", None)
    observed = {}
    with (OUT / f"client-window-{name}.log").open("wb") as output:
        command = [WINE, str(HELPER)] if wrapper else [
            WINE, str(GAME), "/noCrashReportUpload",
            "/resfileserver=http://127.0.0.1:26002/resfiles/", "/port:26000"]
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True, cwd=GAME.parent.parent)
        root = record(process.pid)
        assert root and root["group"] == process.pid and root["session"] == process.pid
        try:
            deadline = time.monotonic() + 35
            while process.poll() is None and time.monotonic() < deadline:
                if wrapper and GAME.exists():
                    # Verification-only inspection of our original fake game.
                    # Runtime ownership continues to use the trusted Linux PGID.
                    for entry in Path("/proc").iterdir():
                        if not entry.name.isdigit() or int(entry.name) == process.pid:
                            continue
                        try:
                            command_line = (entry / "cmdline").read_bytes().lower()
                        except OSError:
                            continue
                        if b"exefile.exe" not in command_line:
                            continue
                        child = record(int(entry.name))
                        if child:
                            assert child["group"] == process.pid, "Wine child escaped launcher PGID"
                            assert child["session"] == process.pid, "Wine child escaped launcher session"
                            observed[(child["pid"], child["startTicks"])] = child
                time.sleep(.05)
            if process.poll() is None:
                raise AssertionError(f"Window fixture timed out: {name}")
            assert process.returncode == expected_exit, (name, process.returncode)
        finally:
            if process.poll() is None:
                current = record(process.pid)
                if current and current["startTicks"] == root["startTicks"]:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            subprocess.run([SERVER, "-k"], timeout=15, check=False,
                           stdout=output, stderr=subprocess.STDOUT)
            subprocess.run([SERVER, "-w"], timeout=15, check=True,
                           stdout=output, stderr=subprocess.STDOUT)
    report = {}
    if wrapper:
        assert RECEIPT.is_file() and RECEIPT.stat().st_size < 8192
        report = json.loads(RECEIPT.read_text())
        assert report["format"] == 1 and report["helper"] == "eve-client-window-1"
        assert report["session"] == nonce
        (OUT / f"client-window-{name}.json").write_text(json.dumps(report, indent=2) + "\n")
    fixture = json.loads(FIXTURE_RECEIPT.read_text()) if FIXTURE_RECEIPT.is_file() else {}
    if GAME.exists():
        assert fixture, "The original GUI fixture did not publish its result"
        (OUT / f"client-window-{name}-fixture.json").write_text(json.dumps(fixture, indent=2) + "\n")
        assert '"helper":"eve-client-window-fixture-1"' in (OUT / f"client-window-{name}.log").read_text(errors="replace"), "Lost child stdout inheritance"
    return {"exitCode": process.returncode, "ownedGameMembers": list(observed.values()),
            "window": report, "fixture": fixture, "launcherUnixPid": process.pid}


def main() -> None:
    assert os.uname().machine == "aarch64"
    assert os.environ["WINEPREFIX"] == "/graphics-regression-prefix"
    assert not GAME.exists(), "Qualification must not overwrite a real client"
    GAME.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / "eve-client-window-fixture.exe", GAME)
    try:
        direct = run_case("direct-minimized", False, 38)
        assert direct["fixture"]["passed"] is False and direct["fixture"]["restored"] is False
        focused = run_case("owned-focus", True, 37)
        report = focused["window"]
        assert focused["ownedGameMembers"], "Did not observe the fixed child in its Unix process group"
        assert report["phase"] == "child_exited" and report["childExitCode"] == 37
        assert report["focusAttempted"] is True and report["focusSucceeded"] is True
        assert report["childWindowsPid"] != report["wrapperWindowsPid"]
        fixture = focused["fixture"]
        assert fixture["passed"] is True and fixture["foregroundOwned"] is True and fixture["focusOwned"] is True
        assert fixture["restored"] is True and fixture["hiddenUntouched"] is True and fixture["ownedPopupUntouched"] is True
        assert fixture["windowsPid"] == report["childWindowsPid"]
        assert fixture["unixGroup"] == focused["launcherUnixPid"] and fixture["unixSession"] == focused["launcherUnixPid"]
        hung = run_case("hung-pump", True, 37, {"EVE_WINDOW_FIXTURE_HUNG": "1"})
        assert hung["ownedGameMembers"]
        assert hung["fixture"]["hungMessagePump"] is True and hung["fixture"]["passed"] is False
        assert hung["window"]["phase"] == "child_exited" and hung["window"]["childExitCode"] == 37
        assert hung["window"]["focusSucceeded"] is False and hung["window"]["responsive"] is False
        assert hung["window"]["elapsedMs"] < 16000, "Hung game pump prevented bounded child-exit forwarding"
        GAME.unlink()
        missing = run_case("missing-child", True, 111)
        assert missing["window"]["phase"] == "failed"
        assert missing["window"].get("childWindowsPid") in (0, None)
        result = {"passed": True, "helper": "eve-client-window-1",
                  "qualification": "original-window-fixture-native-arm64-wine-fex-only",
                  "physicalThorQualified": False,
                  "helperSha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
                  "directMinimized": direct, "ownedFocus": focused, "hungPump": hung, "missingChild": missing}
        (OUT / "client-window-check.json").write_text(json.dumps(result, indent=2) + "\n")
        print("Owned-window focus, hung message-pump bounds, child exit and Unix group inheritance passed", flush=True)
    finally:
        GAME.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
