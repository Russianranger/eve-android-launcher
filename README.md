# EVE Android Launcher

A server-first Android launcher for EVE.js 0.12.9 and its exact supported Windows
client, **EVE 24.01 build 3396210**. Target hardware is the AYN Thor Max
(ARM64 Android 13, Snapdragon 8 Gen 2, 16 GB RAM).

The initial 0.1.0 preview provides a prepared native ARM64 server runtime,
durable local world and Jita market, foreground session ownership, readiness
checks, supervised shutdown and support-log export. It also installs the pinned
Wine/FEX client runtime and validates complete user-supplied client imports.
EVE client login, graphics, audio and controller qualification remain subsequent
milestones; there is no gameplay launch button in this first pass.

## First server test

Download the APK from [the preview release](https://github.com/Russianranger/eve-android-launcher/releases/tag/v0.1.0).
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
python3 -m unittest discover -s tests -v
python3 tests/server-package-tests.py
bash scripts/check-archive-host.sh
gradle :app:assembleDebug :app:lintDebug
```

The runtime is installed in app-private internal storage. The client and server
use loopback connections; this initial integration does not expose a LAN server.
No retail EVE client files or credentials are distributed.

## Sources and licensing

EVE.js source comes from the supplied `EveJS-v0.12.9.zip`; its exact SHA-256 and
excluded optional packs are recorded in [vendor/evejs/UPSTREAM.json](vendor/evejs/UPSTREAM.json).
The project is AGPL-3.0-only. Runtime components and adaptations are identified
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), with corresponding source
archives included in releases. EVE Online is a trademark of CCP; this launcher
is an independent project.
