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
together whenever a preview bundles any such binary. The initial launcher
did not include those components in its APK. Version 0.1.4 added the focused
crypt32 session overlay described below; 0.1.5 also packages the native graphics
components described in the following section. The existing Wine/FEX runtime
is preserved.

## Wine crypt32 session overlay

The APK includes crypt32 modules built from the existing pinned Wine fork
`bylaws/wine` commit `a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`, with the
small name-constraint patch in `native/wine-empty-subject.patch`. Wine is
LGPL-2.1-or-later. The matching modified source, license, patch, compiler
identity, build configuration and build instructions are published as
`wine-trust-corresponding-source.tar.gz` with the APK. The immutable UO
Wine/FEX runtime and its matching sources remain available at their existing
v0.2.0 release. No game files are included.

## Native ARM64EC DXVK and Turnip graphics

Version 0.1.5 packages only DXVK's D3D11 and DXGI DLLs, built as native ARM64EC
from [DXVK 2.5.3](https://github.com/doitsujin/dxvk/tree/c707d9026f33b6ab89639f154b6ac5f6326fa037),
commit `c707d9026f33b6ab89639f154b6ac5f6326fa037`. DXVK is distributed under
its zlib/libpng license, copyright Philip Rebohle, Joshua Ashton, Robin Kertels
and Jeffrey Ellison. The unchanged upstream license is included in the APK and
launcher source as `docs/licenses/dxvk-2.5.3-LICENSE.txt`.

`client-graphics-corresponding-source.tar.gz`, published with the APK, retains
the complete pinned DXVK source, its original license and notices, and the
three source dependencies used by this Windows build:

| Source dependency | Pinned commit | License notices |
| --- | --- | --- |
| Khronos Vulkan-Headers | `46dc0f6e514f5730784bb2cac2a7c731636839e8` | Original license files and per-file notices retained in `dxvk/include/vulkan`. |
| Khronos SPIRV-Headers | `8b246ff75c6615ba4532fe4fde20f1be090c3764` | Original license files and per-file notices retained in `dxvk/include/spirv`. |
| Joshua Ashton's libdisplay-info fork | `275e6459c7ab1ddd4b125f28d0440716e4888078` | Original license files and per-file notices retained in `dxvk/subprojects/libdisplay-info`. |

The APK reuses the native ARM64 glibc Mesa 26.0.0 Turnip driver and the native
Vulkan device/X11 presentation probe from the immutable
[UO launcher v0.2.17 release](https://github.com/Russianranger/uo-android-launcher/releases/tag/v0.2.17).
The selected files come from `runtime-bridges.zip`, SHA-256
`e4acf8e2dd432e11ec4aac3ad86137890b664df90cd467455b64209dfb56e1ba`.
The build verifies both that archive and each selected file; no other component
from the bridge archive is installed.

Mesa's component license and copyright notices remain in its exact unmodified
source archive; most Mesa code is MIT-licensed, with individual source files
specifying their own terms. Its original license texts and source copyright
notice inventory are also packaged as `docs/licenses/mesa-26.0.0-notices.txt`.
That inventory covers the complete Mesa distribution and is broader than the
selected Turnip driver. The Mesa 26.0.0 source SHA-256 is
`2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72`.
Its build-time Khronos glslang 15.1.0 source archive, SHA-256
`4bdcd8cdb330313f0d4deed7be527b0ac1c115ff272e492853a6e98add61b4bc`,
is retained with its upstream license notices. glslang is not installed in the
APK or client runtime. The Turnip driver is open-source Mesa built for Qualcomm
KGSL; no proprietary Qualcomm driver is included.

The Vulkan probe is the original TRASC project's `vulkan/vulkan_probe.c`,
carried in that same UO release. Its exact source, original accompanying
third-party notices, and original Dockerfiles/build script are retained in
`turnip-original-source` inside `client-graphics-corresponding-source.tar.gz`.
The original source package is `runtime-corresponding-sources.tar.gz`, SHA-256
`492043660b1370e1910c8b8ca2b93be1f637f4929034f575591f14e67e015243`;
the graphics build extracts its nested `vulkan-sources.tar.gz`. The probe has
no separate license declaration in its source; these notices preserve its
original attribution without assigning it a new license.

The graphics source release also contains the native ARM64EC cross file,
source provenance, exact build/qualification scripts, and the original EVE
D3D11 qualification helper source. DXVK uses the same SHA-256-pinned
LLVM-MinGW 20250920 compiler as the existing Wine crypt32 overlay. The EVE
helper is launcher code compiled as x64 with that toolchain; the existing
MinGW-w64 notices above also apply. The graphics overlay adds no Wine/FEX
runtime upgrade and no game executables, resources or credentials.
