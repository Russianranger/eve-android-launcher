# EVE Android Launcher

A server-first Android launcher for EVE.js 0.12.9 and its exact supported Windows
client, **EVE 24.01 build 3396210**. Target hardware is the AYN Thor Max
(ARM64 Android 13, Snapdragon 8 Gen 2, 16 GB RAM).

The initial server preview provides a prepared native ARM64 server runtime,
durable local world and Jita market, foreground session ownership, readiness
checks, supervised shutdown and support-log export. It also installs the pinned
Wine/FEX client runtime and validates complete user-supplied client imports.
0.1.4 passed private Wine TLS, EVE startup, local authentication and character
selection on the Thor. CPU rendering was too slow for usable text entry. 0.1.5
prioritizes native Adreno rendering, persistent shader caches, batched input and
performance diagnostics. Audio, controllers and gameplay qualification follow.
The 0.1.5 device test passed the native Adreno shader/display checks; 0.1.6 fixes
the formatted display-report reader that stopped EVE before launch.

## First server test

Download the APK from [the preview release](https://github.com/Russianranger/eve-android-launcher/releases/tag/v0.1.6).
In the Server tab, choose **Install server runtime**, **Prepare local world**,
then **Start server**. Wait for **SERVER READY**, briefly switch apps, then use
**Save and stop server**. Start it again and export support logs from the Logs tab.
See [the detailed test sequence](docs/TESTING.md).

The package builds Node.js, native SQLite and the Rust market service for ARM64
in CI. Static universe data and a small Jita-only synthetic market are generated
once during packaging, rather than compiled or generated on the handheld.
The initial package excludes optional universe content packs. Runtime downloads
require HTTPS and matching SHA-256; world data lives outside the replaceable
rootfs and repeated preparation preserves it.

## Client import recovery in 0.1.1

The initial Thor server gate and Wine/FEX x64 execution probe have passed.
The 0.1.1 preview fixes unbounded validation reads, limits the Python preparation
worker to 512 MiB, and pauses preparation when Android is short of memory.
Resource names are counted on disk and safe resource directories are checked
once; no full-cache recursive scan is needed to find the client root.

After updating, leave the server stopped and select **Resume interrupted client
import**. This reuses a surviving private ZIP. Old partial extractions are reused
only after checking each file's ZIP CRC and size. Exact client hashes and both
resource indexes still must pass before the cache becomes active. Export support
logs afterward; stage progress and worker/system memory diagnostics are included.
Do not clear app data or reinstall the already working runtimes.

The Thor recovery test has now passed: exact build 3396210, all 125,116 resources,
6 minutes 14 seconds, and 150.6 MiB peak worker RSS with no reported low-memory
condition. See [the accepted physical evidence](docs/HANDOFF.md). Keep the
prepared cache. The current preview uses that prepared cache. Startup/login passed; client
performance is the current device gate.

## Client performance preview in 0.1.6

Update in place, start the server and wait for **SERVER READY**, then leave
**Use Adreno GPU rendering** checked and start/open EVE. Native ARM64EC DXVK 2.5.3
uses the pinned Turnip 26 driver through the existing Wine/FEX runtime. It does not
replace that runtime or reset the accepted prefix/content/world. Before EVE,
hardware-only preflight checks Vulkan, shader pixels and visible display frames.
The initial render/display cap is 30 FPS with a one-frame DXGI queue. Shader caches
persist across launches. Software recovery retains the previous WineD3D/llvmpipe path.

Touch selects a field; **Text** defaults to replacing its contents and sends one
buffered batch. Use a fresh disposable local account such as `EvePerf1`; do not
reuse ThorTest. Detailed CPU/input/display metrics join the bounded support ZIP.
Host/CI helper results establish interoperability, while actual EVE speed and
responsiveness remain a physical device test. See [the test sequence](docs/TESTING.md)
and [optimization evidence](docs/CLIENT-PERFORMANCE.md).

The accepted native loopback policy, private CA checks and Wine crypt32 overlay
remain active. Client stop targets only recorded owned process identities; world
save behavior is preserved.

## Client preparation

Use **Install Wine / FEX runtime** before importing a ZIP with `tq/`, adjacent
`ResFiles/`, and `index_tranquility.txt`. Exact build and binary checks prevent
accidental use of an unrelated client. Assets are local during play; missing
resources fail validation. The independent **Probe Wine / FEX** executes a
minimal x64 fixture, not EVE. A passing probe does not establish game compatibility.
See [client preparation details](docs/CLIENT-RUNTIME.md).

## Development

The app uses Java 17, Android Gradle Plugin 8.9.1, Gradle 8.11.1, SDK 35 and
NDK 27.2.12479018. The workflow builds the server on native ARM64 Linux, checks
its real application readiness and clean shutdown, builds/lints the Android APK,
and publishes corresponding sources beside runtime binaries.

```sh
python3 scripts/prepare-evejs-source.py
python3 -m unittest discover -s tests -v
python3 tests/server-package-tests.py
bash scripts/check-archive-host.sh
bash scripts/check-client-display-host.sh
bash scripts/build-client-gate.sh
gradle :app:assembleDebug :app:lintDebug
```

The original x64 certificate helper requires `x86_64-w64-mingw32-gcc` (the
`gcc-mingw-w64-x86-64-posix` package in CI). It is generated from the retained C
source before packaging the APK; it does not rebuild the Wine/FEX runtime.

The runtime is installed in app-private internal storage. The client and server
use loopback connections; this initial integration does not expose a LAN server.
No retail EVE client files or credentials are distributed.

The pinned EVE.js source is stored as twelve source archive shards under
`vendor/`. Run `python3 scripts/prepare-evejs-source.py` after checkout to verify
every shard and the overall SHA-256, then reconstruct the complete
`vendor/evejs/` tree. CI performs this before source tests and server packaging;
the native server build script also performs it. Extracted files are ignored by
Git; update the pinned archive and provenance together when changing upstream.

## Sources and licensing

EVE.js source comes from the supplied `EveJS-v0.12.9.zip`; its exact SHA-256 and
excluded optional packs are recorded in [vendor/evejs/UPSTREAM.json](vendor/evejs/UPSTREAM.json).
Release source ZIPs include every source archive shard, the retained original
license and README, pinned provenance, and the reconstruction script. They
contain the complete vendored source without depending on an upstream download.
The project is AGPL-3.0-only. Runtime components and adaptations are identified
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), with corresponding source
archives included in releases. EVE Online is a trademark of CCP; this launcher
is an independent project.

The 0.1.4 APK supplies a verified, session-only crypt32 DLL overlay built from
the exact installed Wine source/toolchain. It preserves the installed runtime
and prefix. The focused Wine regression reproduces the original certificate
rejection and checks thirteen valid/invalid trust cases. See
[Wine trust source and test build](client-runtime/wine-trust/Dockerfile).
