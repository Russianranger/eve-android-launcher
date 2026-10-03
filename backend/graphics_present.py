#!/usr/bin/env python3
"""Observe only the fixed synthetic D3D11 probe through private Raw RFB.

Run only the synthetic graphics preflight before launching EVE. No images are
saved: only fixed probe color matches and aggregate RFB counts are reported.
The fixed pixel contract belongs to eve-d3d11-frame-1 only.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

CENTER = (32, 223, 64)
CORNERS = ((8, 16, 24), (48, 32, 16), (16, 48, 32))
PF = bytes((32, 24, 0, 1, 0, 255, 0, 255, 0, 255, 16, 8, 0, 0, 0, 0))


class ProbeObserver:
    def __init__(self, port: int, timeout: float):
        self.deadline = time.monotonic() + timeout
        self.stop = threading.Event()
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(0.25)
        self.width = self.height = self.updates = self.rectangles = self.received = 0
        self.image = bytearray()
        self.matched: set[int] = set()
        self.center_matched = False
        self.error = ""
        self.reader: threading.Thread | None = None

    def read(self, count: int) -> bytes:
        if count < 0 or count > 16 * 1024 * 1024:
            raise ValueError("RFB payload exceeds fixture limits")
        output = bytearray(count)
        at = 0
        while at < count:
            if self.stop.is_set():
                raise InterruptedError("observer stopped")
            if time.monotonic() >= self.deadline:
                raise TimeoutError("RFB fixture observation timed out")
            try:
                length = self.sock.recv_into(memoryview(output)[at:])
            except socket.timeout:
                continue
            if length == 0:
                raise EOFError("RFB peer closed")
            at += length
            self.received += length
        return bytes(output)

    def resize(self, width: int, height: int) -> None:
        if not 1 <= width <= 4096 or not 1 <= height <= 2160 or width * height > 4_194_304:
            raise ValueError("RFB dimensions exceed fixture limits")
        self.width, self.height = width, height
        self.image = bytearray(width * height * 4)

    def request(self, incremental: bool) -> None:
        self.sock.sendall(struct.pack(">BBHHHH", 3, int(incremental), 0, 0, self.width, self.height))

    def handshake(self) -> None:
        version = self.read(12)
        if version not in (b"RFB 003.003\n", b"RFB 003.007\n", b"RFB 003.008\n"):
            raise ValueError("Unexpected RFB version")
        self.sock.sendall(version)
        if version == b"RFB 003.003\n":
            if struct.unpack(">I", self.read(4))[0] != 1:
                raise ValueError("Fixture requires local None security")
        else:
            count = self.read(1)[0]
            if count == 0 or 1 not in self.read(count):
                raise ValueError("Fixture requires local None security")
            self.sock.sendall(b"\x01")
            if version == b"RFB 003.008\n" and self.read(4) != b"\x00" * 4:
                raise ValueError("RFB local authentication failed")
        self.sock.sendall(b"\x01")
        self.resize(*struct.unpack(">HH", self.read(4)))
        self.read(16)
        name_length = struct.unpack(">I", self.read(4))[0]
        if name_length > 65536:
            raise ValueError("RFB display name exceeds fixture limits")
        self.read(name_length)
        self.sock.sendall(b"\x00" * 4 + PF + struct.pack(">BBHii", 2, 0, 2, 0, -223))
        # A server-rendered cursor must not cover the fixed probe samples.
        self.sock.sendall(struct.pack(">BBHH", 5, 0, 0, 0))
        self.request(False)

    def rgb(self, x: int, y: int) -> tuple[int, int, int] | None:
        if x >= self.width or y >= self.height:
            return None
        at = (y * self.width + x) * 4
        return self.image[at + 2], self.image[at + 1], self.image[at]

    @staticmethod
    def color_matches(actual: tuple[int, int, int] | None, expected: tuple[int, int, int]) -> bool:
        # The native helper accepts one UNORM quantization step on readback.
        return actual is not None and all(abs(a - b) <= 1 for a, b in zip(actual, expected))

    def observe(self) -> None:
        if self.color_matches(self.rgb(96, 96), CENTER):
            self.center_matched = True
            corner = self.rgb(34, 34)
            for frame, expected in enumerate(CORNERS):
                if self.color_matches(corner, expected):
                    self.matched.add(frame)

    def update(self) -> None:
        message = self.read(1)[0]
        if message == 2:
            return
        if message == 3:
            self.read(3)
            length = struct.unpack(">I", self.read(4))[0]
            if length > 1_048_576:
                raise ValueError("RFB cut text exceeds fixture limits")
            self.read(length)  # Deliberately ignored; no clipboard integration/logging.
            return
        if message != 0:
            raise ValueError("Unexpected RFB message")
        _, count = struct.unpack(">BH", self.read(3))
        for _ in range(count):
            x, y, width, height, encoding = struct.unpack(">HHHHi", self.read(12))
            if encoding == -223:
                self.resize(width, height)
                continue
            if not width or not height or x + width > self.width or y + height > self.height:
                raise ValueError("RFB rectangle outside framebuffer")
            if encoding != 0:
                raise ValueError("Fixture supports Raw encoding only")
            pixels = self.read(width * height * 4)
            for row in range(height):
                source = row * width * 4
                destination = ((y + row) * self.width + x) * 4
                self.image[destination:destination + width * 4] = pixels[source:source + width * 4]
            self.rectangles += 1
        if count:
            self.updates += 1
            self.observe()
        self.request(True)

    def start(self) -> None:
        self.handshake()
        def receive() -> None:
            try:
                while not self.stop.is_set():
                    self.update()
            except Exception as error:
                if not self.stop.is_set():
                    self.error = type(error).__name__ + ": " + str(error)
        self.reader = threading.Thread(target=receive, name="probe-rfb-reader", daemon=True)
        self.reader.start()

    def close(self) -> None:
        self.stop.set()
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        if self.reader:
            self.reader.join(timeout=1)
        self.image.clear()

    def report(self, exit_code: int | None, process_error: str = "") -> dict:
        return {
            "format": 1, "helper": "eve-rfb-frame-1",
            "display_pixels_verified": exit_code == 0 and not self.error and not process_error
                and self.center_matched and self.matched == {0, 1, 2},
            "center_pixels_verified": self.center_matched,
            "matched_frames": sorted(self.matched), "expected_frames": 3,
            "framebuffer_updates": self.updates, "raw_rectangles": self.rectangles,
            "received_bytes": self.received,
            "width": self.width, "height": self.height,
            "process_exit_code": exit_code,
            "observer_error": self.error, "process_error": process_error,
        }


def run(port: int, timeout: float, command: list[str], stdout: Path, stderr: Path) -> dict:
    observer = ProbeObserver(port, timeout + 10)
    exit_code = None
    process_error = ""
    try:
        observer.start()
        stdout.parent.mkdir(parents=True, exist_ok=True)
        stderr.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("wb") as output, stderr.open("wb") as errors:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors)
            try:
                exit_code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process_error = "D3D probe process timed out"
                child.kill()
                exit_code = child.wait(timeout=5)
        # The final frame remains displayed, so allow its pending request to complete.
        deadline = time.monotonic() + 0.5
        while observer.matched != {0, 1, 2} and not observer.error and time.monotonic() < deadline:
            time.sleep(0.01)
    except Exception as error:
        process_error = type(error).__name__ + ": " + str(error)
    finally:
        observer.close()
    return observer.report(exit_code, process_error)


def self_test() -> None:
    import tempfile
    def exact(sock: socket.socket, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            part = sock.recv(count-len(chunks))
            if not part:
                raise EOFError
            chunks.extend(part)
        return bytes(chunks)
    with tempfile.TemporaryDirectory() as temporary:
        for case, expected_pass in (("exact", True), ("rounding", True), ("missing", False),
                ("wrong", False), ("wrong-center", False), ("nonzero", False)):
            assert all(max(abs(a-b) for a,b in zip(first,second)) >= 8
                for index,first in enumerate(CORNERS) for second in CORNERS[index+1:])
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); listener.listen(1)
                def peer() -> None:
                    with listener.accept()[0] as sock:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        sock.sendall(b"RFB 003.008\n\x01\x01" + b"\x00" * 4
                            + struct.pack(">HH", 320, 240) + b"\x00" * 16 + struct.pack(">I", 4) + b"test")
                        exact(sock, 62)
                        for color in CORNERS[:2 if case == "missing" else 3]:
                            if case == "rounding":
                                color = tuple(value + 1 for value in color)
                            elif case == "wrong":
                                color = (color[0] + 4, color[1], color[2])
                            body = bytearray(bytes((color[2], color[1], color[0], 0)) * (128*128))
                            at = (64*128+64)*4
                            body[at:at+4] = bytes((CENTER[2]-int(case=="rounding"),CENTER[1]+int(case=="rounding"),
                                CENTER[0]+int(case=="rounding")+4*int(case=="wrong-center"),0))
                            packet = b"\x00\x00\x00\x01" + struct.pack(">HHHHi",32,32,128,128,0)+body
                            # Fragment every header/pixel stream boundary deterministically.
                            for at in range(0,len(packet),137):
                                sock.sendall(packet[at:at+137])
                            exact(sock,10)
                            time.sleep(0.05)
                        with contextlib.suppress(EOFError,OSError):
                            while sock.recv(1024):
                                pass
                thread=threading.Thread(target=peer,daemon=True);thread.start()
                command = "import time,sys;time.sleep(.4);sys.exit("+str(int(case=="nonzero"))+")"
                report=run(listener.getsockname()[1],3,[sys.executable,"-c",command],
                    Path(temporary)/"stdout",Path(temporary)/"stderr")
                assert report["display_pixels_verified"] is expected_pass,report
                assert report["matched_frames"] == ([0,1,2] if expected_pass or case == "nonzero" else [0,1] if case == "missing" else []),report
                assert report["center_pixels_verified"] is (case != "wrong-center"),report
                thread.join(timeout=1)
    print("RFB D3D fixture exact/rounding/missing/wrong-color/wrong-center/nonzero-exit fragmented-peer tests passed")


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--port",type=int,default=5907)
    parser.add_argument("--timeout",type=float,default=90)
    parser.add_argument("--report",type=Path)
    parser.add_argument("--stdout",type=Path)
    parser.add_argument("--stderr",type=Path)
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.self_test:
        self_test();return 0
    command=args.command[1:] if args.command[:1]==["--"] else args.command
    if not command or not args.report or not args.stdout or not args.stderr:
        parser.error("--report, --stdout, --stderr and a command after -- are required")
    try:
        report=run(args.port,args.timeout,command,args.stdout,args.stderr)
    except Exception as error:
        report={"format":1,"helper":"eve-rfb-frame-1","display_pixels_verified":False,
            "observer_error":type(error).__name__+": "+str(error)}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,separators=(",",":")))
    return 0 if report["display_pixels_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
