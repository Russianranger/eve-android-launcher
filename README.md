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
performance diagnostics. Audio and gameplay qualification follow.
The 0.1.5 device test passed the native Adreno shader/display checks; 0.1.6 fixes
the formatted display-report reader that stopped EVE before launch.
0.1.6 then reached a persistent shader/loading stall. 0.1.7 tests native DXVK 2.4.1
as an Adreno synchronization compatibility candidate and retains live
diagnostics after Stop. Actual EVE GPU responsiveness remains the device gate.
0.1.7 also remained black. Its retained samples show idle background graphics
workers after startup. 0.1.8 activates EVE's owned window once and records window
focus/message-pump evidence; it retains DXVK 2.4.1 and the accepted runtime.
The 0.1.8 device test confirms focus succeeds while EVE's main thread stalls.
0.1.9 overrides the session's presentation interval to avoid the FIFO completion
wait through Xvnc, retaining GPU rendering and the 30 FPS cap. The October 4
device test accepts responsive rendering/input in the teens and 20s FPS.
0.1.10 brings TRASC's layered controller bindings and fullscreen orbital gear menu.
0.1.11 fixes Android 13 display startup, renames the defaults to Main/Alt 1/Alt 2/Alt 3,
pins both Start buttons above the tabs and gives the app icon a dark space background.
The 0.1.11 Thor test accepts fullscreen/controls and reopening the saved character
in station. 0.1.12 adds a default 60 FPS/two-frame performance profile, the previous
30 FPS/one-frame option, earlier display requests and a dark adaptive app icon.
The user reports worse 0.1.12 performance. 0.1.13 restores the accepted baseline,
adds isolated cap/request comparisons and optional Adreno/FEX experiments, and
uses a same-signed non-debuggable APK. Follow the [warm station comparison](docs/TESTING.md);
actual speed and Android runtime compatibility still require the Thor test.

The October 5 tests recorded an Android low-memory kill in the baseline and
warm memory near 3 GiB. 0.1.14 adds critical-pressure handling, memory/thermal
histories, accurate normal-exit reporting and an optional exact-device A740
driver experiment. See [the measured evidence](docs/DEVICE-20261005.md) and
[the two-run test](docs/TESTING.md); physical driver performance remains unqualified.

The October 7 FSR test helped modestly but introduced black lines. 0.1.15 adds
an optional mapped-linear presentation experiment that removes one GPU staging
copy while retaining the accepted runtime and original driver. Fresh hardware
capability and native shader/display checks precede launch; actual warm FPS and
geometry need [the focused Thor comparison](docs/TESTING.md). Current client
logs now take priority over old server history in support exports.

The October 8 export-adjacent closure was the pressure guard overreacting despite
ample memory. 0.1.16 requires corroborated pressure, provides **Restore baseline
settings** and a visible experiment summary, and records bounded readable
frequency/thermal evidence. Both 0.1.15 exports retained linear, so use
[the actual baseline comparison](docs/TESTING.md) to assess its warm FPS/heat benefit.

The October 8 evening comparison records a true original-versus-linear pair.
The user reports a small linear FPS gain and slightly lower temperatures;
matched logged CPU/RSS/thermal readings remain similar. 0.1.17 adds default-off
**Use direct GPU rendering (experiment)** using the pinned driver's SYSMEM mode,
following newer Mesa's DXVK rendering preference. It also marks the full-color
Android display bitmap opaque. Test [linear alone versus linear plus direct GPU
rendering](docs/TESTING.md); stable 30 FPS and lower heat remain physical gates.
See [the evening evidence](docs/DEVICE-20261008-EVENING.md) and
[the source-backed optimization review](docs/CLIENT-PERFORMANCE.md).

## Fullscreen controls in 0.1.11

The display fills the screen; a top-right space-themed gear opens the controls
without shrinking the game. Text, Tab, Enter, Esc, right-click and Launcher now
live in that menu. LT cycles **Main → Alt 1 → Alt 2 → Alt 3**, with a
brief layer banner. Left stick sends WASD; right stick moves the cursor; RB/LB
hold left/right mouse buttons. Other defaults match the TRASC launcher.

Choose **Controller mappings** in the gear menu to edit every button and stick
direction, keyboard/chords/clicks/wheel, layer actions, names, deadzone and speed.
One to six layers are supported. **Save** persists the profile; **Cancel** keeps
the previous settings. Controls release on menus, focus loss and app switches.
See [default bindings and the device test](docs/CONTROLS.md).

## First server test

Download the APK from [the passing preview build artifacts](https://github.com/Russianranger/eve-android-launcher/actions/workflows/build.yml).
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
rendering/input and layered controls are accepted; 30+ FPS is the current device goal.

## Accepted client renderer from 0.1.9

Update in place, start the server and wait for **SERVER READY**, then leave
**Use Adreno GPU rendering** checked and start/open EVE. Native ARM64EC DXVK 2.4.1
uses the pinned Turnip 26 driver through the existing Wine/FEX runtime. It does not
replace that runtime or reset the accepted prefix/content/world. Before EVE,
hardware-only preflight checks Vulkan, shader pixels and visible display frames.
The initial render/display cap is 30 FPS with a one-frame DXGI queue. Shader caches
persist across launches. Software recovery retains the previous WineD3D/llvmpipe path.
The session disables vertical synchronization to bypass the Xvnc present-wait
path; saved EVE preferences are preserved. The native probe requests synchronized
presentation and verifies the override before testing three visible frames.

Touch selects a field; **Text** defaults to replacing its contents and sends one
buffered batch. Use a fresh disposable local account such as `EvePerf1`; do not
reuse ThorTest. Detailed CPU/input/display metrics join the bounded support ZIP.
Host/CI helper results establish interoperability; the October 4 user test accepts
EVE speed and responsiveness for now. See [the test sequence](docs/TESTING.md)
and [optimization evidence](docs/CLIENT-PERFORMANCE.md).

The fixed-target startup helper preserves the client process group, waits for
EVE's exit and reports only numeric window/focus state. It activates the owned
window once during startup, then stops observing after three minutes. It never
changes the saved EVE graphics preferences. If the screen remains black after
three minutes, export support logs while it is running, then stop the client.

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
