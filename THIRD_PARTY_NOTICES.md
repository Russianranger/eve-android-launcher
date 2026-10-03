# Third-party software

This project does not distribute CCP's EVE Online Windows client, retail resources,
launcher account credentials, or client certificates. Users supply the exact
supported build and its complete resources.

| Component | Version/source | License and distribution |
| --- | --- | --- |
| EVE.js | Uploaded EVE.js 0.12.9 source, preserved under `vendor/evejs`; original archive provenance is recorded in `vendor/evejs/UPSTREAM.json` | AGPL-3.0-only. Its original license and notices remain with the vendored source. Launcher source releases preserve that complete tree, and server runtime source releases also include build and dependency sources. |
| PRoot | [Termux PRoot](https://github.com/termux/proot), commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb` | GPL-2.0-or-later. Every APK release includes `proot-corresponding-source.tar.gz` with the exact modified source, original license, local patches, generated loader helper, and build script. |
| talloc | [talloc 2.4.3](https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz), SHA-256 `dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd` | LGPL-3.0-or-later. Statically linked into PRoot; its original complete source archive is included in the PRoot corresponding source release. Rebuilding PRoot with an altered talloc is supported through the published build script. |
| Debian server runtime | ARM64 Debian 12 Bookworm with native Node.js, package versions recorded during the server runtime build | Individual packages retain their original licenses. Package notices and corresponding sources are bundled by the runtime source build. |
| Node.js and server dependencies | Exact versions and dependency lockfiles retained with the server runtime source | Original third-party license files and applicable source are included in the corresponding runtime source archive. See that archive's build provenance and notices. |
| EVE.js Rust market daemon dependencies | Crate versions pinned by the upstream `Cargo.lock` | Original crate licenses and the offline vendor sources are retained in the server runtime corresponding source archive. |

`native/proot-acceleration.patch` and `native/proot-sysvipc.patch` are adapted from
the existing UO Android launcher's Android runtime work. They preserve seccomp
observability and replace unavailable Android ashmem allocations with memfd where
supported. `scripts/build-proot.sh` records the pinned NDK, compiler flags and
compatibility changes needed to reproduce the packaged native executables.

The basic RFB display transport adapts the existing UO launcher's AGPL-3.0-only
RFB implementation. Its source remains in the launcher source release.

The client startup preview also applies `native/eve-client-network.patch` to
that same PRoot source. It restricts the client session's IP sockets to loopback
and maps its localhost TLS port 443 requests to the existing server port 26003.
The modified source and patch are included in each PRoot source archive.

`native/eve-client-gate.c` is original launcher code. Its x64 qualification
helper is compiled with MinGW-w64 and uses the existing Wine CryptoAPI/WinHTTP
implementation; it does not bundle or replace Wine. MinGW-w64 startup/runtime
copyright and license notices are preserved in
`docs/licenses/mingw-w64-copyright.txt`, packaged as an APK asset and included
in the launcher source release. GCC runtime use is covered by its runtime
library exception. `scripts/build-client-gate.sh` reproduces the helper.

The complete EVE.js source is stored in pinned, compressed archive shards under
`vendor/`; its original license, README and provenance remain directly readable
in `vendor/evejs/`. Release source ZIPs include all shards and
`scripts/prepare-evejs-source.py`, which verifies their individual and combined
SHA-256 hashes and reconstructs the exact source tree for builds. Corresponding
server runtime source releases include both the reconstructed source and those
same shards, alongside dependency sources and build instructions.

The Windows client runtime is prepared separately from the server. Wine/FEX,
graphics drivers, and their corresponding source archives must be distributed
together before a later preview bundles any such binary. The initial launcher
does not include those components in its APK.
