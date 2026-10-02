# Server runtime build and qualification

The initial server package is a Debian Bookworm GNU/Linux ARM64 root filesystem,
used by the Android launcher through its bundled PRoot. The server runs native
ARM64 Node.js 24, native better-sqlite3/SQLite and the native Rust market daemon.
Wine and x86 CPU translation are reserved for the separate client runtime.

`vendor/evejs/UPSTREAM.json` records the exact EVE.js 0.12.9 upstream archive hash
and the checksum of `vendor/evejs-source.tar.gz`. Its committed `.part01` through
`.part12` shards are verified individually, concatenated in order and verified
again as one archive. This deterministic GNU tar contains the source files,
excluding the three directly committed
license, README and provenance files. `scripts/prepare-evejs-source.py` verifies
and safely expands this archive before building. The expanded tree stays local.
The initial profile targets EVE 24.01 client and SDE build **3396210**. The upstream
source and lock files are retained; optional `content-packs/` are omitted. The
launcher repository contains no retail EVE client installation or cache.

## Build

Use a native ARM64 Linux Docker host, such as GitHub's `ubuntu-24.04-arm` runner:

```sh
bash scripts/build-server-runtime.sh
```

The build refuses an x86 host; QEMU execution does not qualify the Android ARM64
runtime. Docker uses Node **24.18.1 Bookworm** and Rust 1.95 Bookworm images.
The npm and Rust dependencies use their committed lock files. better-sqlite3 is
compiled from source for the installed Node ABI and ARM64 architecture. Exact
runtime Node/Debian versions and source package versions are recorded in the
artifact rather than inferred from a moving image tag. Node is pinned because
later 24.x headers introduced an ObjectWrap cleanup-hook regression that aborts
the locked better-sqlite3 addon during ordinary garbage collection. Our native
24.21.0 world boot reproduced the same assertion documented in
[Node issue #65446](https://github.com/nodejs/node/issues/65446). The build and
runtime use matching 24.18.1 headers and binaries; the upstream npm lock remains
unchanged. An allocation-driven 300,000-statement SQLite probe runs during the
native addon build and before full server qualification.

The matching CCP JSONL static-data archive is downloaded in CI and its checksum
recorded. The world tables are generated once during the image build. The v1
market seeder prepares the `jita_only` geography with seven days of synthetic
history. This limits initial mobile market size; it does not trim the world map.
Android preparation copies these templates into persistent state, keeping an
existing world and its saved players on subsequent preparation.

## Installed paths

| Path | Contents |
| --- | --- |
| `/opt/evejs` | Upstream source and locked production Node modules |
| `/opt/evejs-seed/gameStore` | Generated `data/` world tables and `manifest.json` |
| `/opt/evejs-seed/market/market.sqlite` | Integrity-checked Jita market template |
| `/opt/evejs-seed/config` | Defaults copied before the persistent config bind |
| `/usr/local/bin/node` | Native ARM64 Node.js |
| `/usr/local/bin/market-server` | Native ARM64 market daemon |
| `/usr/local/bin/market-seed` | Native ARM64 v1 maintenance seeder |
| `/etc/eve-server-runtime.json` | Architecture, client build and source receipt |
| `/usr/share/eve-android` | Attribution and exact binary/source provenance |

The APK supplies the Python supervisor under `/opt/eve-android`. The Android
service binds private persistent state at `/state` and `/state/config` over the
installed source's `/opt/evejs/config` directory. All live listeners are intended
for the same device and loopback connection.

## Qualification and release files

Before export, `scripts/check-server-runtime.py` executes the native Node/SQLite
statement-collection probe, prepares persistent state, verifies repeat preparation preserves it,
boots the real Rust market daemon and Node world, checks application readiness,
and stops them through the same sentinel used by Android. It rejects an unclean
shutdown. This establishes ARM64 Linux server qualification; Android process,
storage and lifecycle behavior still require the user's Thor test.

The build produces:

| File | Purpose |
| --- | --- |
| `server-runtime-arm64.tar.gz` | GNU tar rootfs for Android import/download |
| `server-runtime-manifest.json` | SHA-256, sizes, source fingerprint and exact client build |
| `server-runtime-check.json` | Native server readiness and clean shutdown evidence |
| `server-runtime-source.tar.gz` | Corresponding source and license notices |

The rootfs packaging script removes pseudo filesystem content, device nodes,
sockets, FIFOs and Docker host metadata. Hardlinks become regular files; names
and links are validated. The output uses GNU tar with directories, regular files
and symlinks; it never relies on PAX headers or archive device nodes. APK import
validates its hash and receipt before switching runtime directories.

`scripts/check-server-package.py <archive>` validates the manifest/archive hash,
the native AArch64 ELF headers, seed build and market database integrity. Its
fixture tests run with `python3 tests/server-package-tests.py`.

## Corresponding source

The source artifact is published beside the binary runtime and contains the
EVE.js source, Android build/supervisor scripts, locked npm package source,
vendored Rust crates, the exact Node.js source release and exact-version Debian
source packages. Original license and attribution files remain included. The
artifact's `SOURCE-INDEX.json` provides a checksum inventory. Debian package
copyright files and source version records are also present. Offline cargo
configuration is supplied for the bundled market daemon/seeder source.

Runtime `runtime-v1` assets are immutable once published. Their input fingerprint
includes upstream source and packaging/build scripts. A server runtime change
requires a new versioned runtime release; APK UI or bound backend improvements
can reuse the matching verified package.
