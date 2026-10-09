#!/usr/bin/env python3
"""CI-only private Xvnc fixture; invoked inside ONE production PRoot guest.

The native probe includes the exact shared production staging header. This
tests CPU transport/lifetime, not KGSL initialization or Android performance.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time


def run_fixture(probe: Path, env: dict, args: list[str], folder: Path, name: str) -> dict:
    with (folder / f"{name}.json").open("wb") as output, (folder / f"{name}-transport.log").open("wb") as errors:
        result = subprocess.run([str(probe), "--fixture", *args], env=env,
                                stdout=output, stderr=errors, timeout=25)
    receipt = json.loads((folder / f"{name}.json").read_text())
    if result.returncode or receipt.get("passed") is not True:
        raise RuntimeError(f"{name} failed; inspect its fixture and transport logs")
    return receipt


def start_server(folder: Path, disabled: bool = False):
    executable = shutil.which("Xvnc") or shutil.which("Xtigervnc")
    if not executable:
        raise RuntimeError("The fixture requires actual TigerVNC Xvnc")
    chosen = None
    for display in range(90, 100):
        if Path(f"/tmp/.X11-unix/X{display}").exists() or Path(f"/tmp/.X{display}-lock").exists():
            continue
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", 6000 + display))
            except OSError:
                continue
        chosen = display
        break
    if chosen is None:
        raise RuntimeError("No free private fixture display")
    name = "shm-xvnc-no-extension.log" if disabled else "shm-xvnc.log"
    output = (folder / name).open("wb")
    command = [executable, f":{chosen}", "-geometry", "1280x720", "-depth", "24",
               "-rfbport", str(6000 + chosen), "-localhost", "yes", "-SecurityTypes", "None",
               "-nolisten", "tcp", "-ac", "-AlwaysShared", "-FrameRate", "30"]
    if disabled:
        command += ["-extension", "MIT-SHM"]
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if child.poll() is not None:
            output.close()
            raise RuntimeError(f"Private Xvnc exited; inspect {name}")
        if Path(f"/tmp/.X11-unix/X{chosen}").is_socket():
            try:
                with socket.create_connection(("127.0.0.1", 6000 + chosen), timeout=.2):
                    pass
                return child, output, chosen, 6000 + chosen
            except OSError:
                pass
        time.sleep(.05)
    child.kill()
    child.wait(timeout=5)
    output.close()
    raise TimeoutError("Private Xvnc socket did not become ready")


def stop_server(child, output) -> None:
    if child.poll() is None:
        child.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=5)
    if child.poll() is None:
        child.kill()
        child.wait(timeout=5)
    output.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.parent
    folder.mkdir(parents=True, exist_ok=True)
    report = {"format": 1, "helper": "eve-x11-shm-host-1", "passed": False,
              "productionSysvipcGuest": True, "memfdAllocationVerified": False,
              "namespaceSharingVerified": False, "dimensions": [[640, 480], [1280, 720]],
              "transportActiveLog": "shm-active-transport.log", "physicalThorQualified": False,
              "nativeGpuRenderingVerified": False}
    child = disabled_child = None
    output = disabled_output = None
    try:
        specification = importlib.util.spec_from_file_location("eve_shm_rfb_observer", args.observer)
        if specification is None or specification.loader is None:
            raise RuntimeError("Missing fixed Raw RFB observer")
        observer = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(observer)
        child, output, display, port = start_server(folder)
        env = os.environ.copy()
        env["DISPLAY"] = f":{display}"
        env.pop("EVE_X11_SHM_STAGING", None)
        positives = []
        for width, height, name in ((1280, 720, "shm-active"), (640, 480, "shm-640")):
            stdout, stderr = folder / f"{name}.json", folder / f"{name}-transport.log"
            # The observer is connected BEFORE the native window presents.
            old_display = os.environ.get("DISPLAY")
            os.environ["DISPLAY"] = env["DISPLAY"]
            try:
                visible = observer.run(port, 25,
                    [str(args.probe), "--fixture", "--width", str(width), "--height", str(height)],
                    stdout, stderr)
            finally:
                if old_display is None:
                    os.environ.pop("DISPLAY", None)
                else:
                    os.environ["DISPLAY"] = old_display
            (folder / f"{name}-rfb.json").write_text(json.dumps(visible, indent=2) + "\n")
            native = json.loads(stdout.read_text())
            if native.get("passed") is not True or visible.get("display_pixels_verified") is not True:
                raise RuntimeError(f"{name} native/Raw RFB pixels failed")
            positives.append(native)
        report.update(
            threeRfbFramesVerified=True,
            reuseVerified=all(item["reuseVerified"] for item in positives),
            resizeVerified=all(item["resizeVerified"] for item in positives),
            pendingTeardownVerified=all(item["pendingTeardownVerified"] for item in positives),
            delayedReuseVerified=all(item["delayedReuseVerified"] for item in positives),
            delayedTeardownVerified=all(item["delayedTeardownVerified"] for item in positives),
            cleanupVerified=all(item["cleanupVerified"] for item in positives),
            namespaceSharingVerified=True)
        negative = run_fixture(args.probe, env, ["--negative-controls"], folder, "shm-negative")
        report.update(allocationFallbackVerified=negative["passed"], attachFallbackVerified=negative["passed"],
                      boundsVerified=negative["passed"])
        disabled_child, disabled_output, disabled_display, _ = start_server(folder, disabled=True)
        disabled_env = dict(env, DISPLAY=f":{disabled_display}")
        no_extension = run_fixture(args.probe, disabled_env, ["--expect-extension-unavailable"],
                                   folder, "shm-no-extension")
        report["extensionFallbackVerified"] = no_extension["passed"]
        death = run_fixture(args.probe, env, ["--server-death", "--server-pid", str(child.pid)],
                            folder, "shm-server-death")
        report["serverDeathVerified"] = death["passed"]
        report["cleanupVerified"] = report["cleanupVerified"] and negative["cleanupVerified"] and death["cleanupVerified"]
        report["passed"] = True
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if child is not None:
            stop_server(child, output)
        if disabled_child is not None:
            stop_server(disabled_child, disabled_output)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
