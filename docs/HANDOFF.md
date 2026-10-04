# EVE Android Launcher handoff

## Initial request and scope

Integrate the supplied EVE.js 0.12.9 server into the initially empty
Russianranger/eve-android-launcher repository. Develop the client runtime in
tandem, prioritizing server setup. Preserve the exact client/protocol build
3396210; no retail client is supplied.

## Implemented initial pass

- Java Android control app with Server, Client and Logs tabs; ARM64 PRoot in APK.
- HTTPS/SHA-256 runtime install, staged extraction and persistent world storage.
- Precompiled Node24/better-sqlite3/Rust package and CI-generated matching SDE
  world plus Jita-only market; optional content packs excluded for this pass.
- Shared foreground ownership, real market/offline-policy/game-handshake checks,
  graceful world shutdown before market and identity-aware child cleanup/recovery.
- Bounded log export, operation history and Android exit diagnostics.
- Pinned existing UO Wine/ARM64EC/FEX runtime installer, exact client cache importer,
  native patch recipes, local trust preparation and independent x64 execution probe.
- CI dependency build, real native ARM64 server smoke qualification, APK/lint,
  stable preview signing, source archives and test-release publication.

## Qualification boundaries

Host fixtures test durability, readiness and shutdown failure behavior. The CI
native ARM64 runtime smoke qualifies the real server on Linux; it does not prove
PRoot/Android behavior. The Thor server lifecycle, Wine/FEX execution probe and
exact client import gates have now passed with the evidence below. EVE process
startup, login, rendering, audio and controllers remain unqualified.

The client probe reports only successful x64 execution in Wine/FEX. Client TLS
preparation does not pretend that Wine CryptoAPI trust or direct localhost:443
access has been proved. Those belong to the later client connection gate.

## Physical evidence and 0.1.1 recovery fix

- `eve-support-20261002-192140.zip`: AYN Thor API33, 0.1.0; install/preparation
  passed; two readiness checks completed in 17 seconds each; first session ran
  over 12 minutes with a reported five-minute app switch; both clean stops and
  persistent repeat start passed. Node remains 24.18.1.
- `eve-support-20261002-192759.zip`: Wine 10.13 private prefix initialized,
  translated x64 fixture returned 37; execution probe accepted.
- `eve-support-20261002-204851.zip`: import stopped after logging 28,000 extracted
  files; no successful validation/promotion receipt. Android exit reason3 is a
  low-memory kill. Java sampled PSS77,146 KiB / RSS157,332 KiB does not identify
  native guest/tracer peak memory. The old `validating` status was written before
  extraction, so it cannot establish the precise failed stage.
- 0.1.1 bounds metadata/binary allocations and Python preparation memory, reduces
  resource-path translation work, adds system/worker memory evidence and a safe
  resume action using the surviving private ZIP/stage.
- `eve-support-20261002-212837.zip`: AYN Thor API33, 0.1.1; interrupted import
  recovery accepted. `resume-client` ran from 21:21:26 to 21:27:40 CDT on
  October 2, 2026 (6 minutes 14 seconds). Build3396210 reached
  `content_prepared`, `content_imported=true`, `resumable_import=false`;
  all 125,116 indexed/unique resources and three exact binaries passed. Two
  private CA bundles and the Wine prefix configuration were prepared. Worker
  peak RSS was 154,200 KiB (150.6 MiB), below its 512 MiB address-space limit.
  Android sampled at least 10,327,404,544 bytes available (9.62 GiB) and never
  reported `lowMemory`. Both exported Android exit entries predate this retry.
  ZIP SHA-256: `36a9d9dc420bef846861e7917561f54fcd371847f2bb4d959081e28569bd0900`.
  This accepts the import recovery fix, not EVE launch or Wine TLS compatibility.
  The 0.1.1 message saying launch awaits server qualification is stale; do not
  repeat the accepted server test on its account.

## 0.1.2 client startup implementation

Adds supervised client startup/recovery and clean stop around the existing
Wine/FEX runtime and accepted imported cache. Basic TigerVNC/RFB display and
touch/text input are available. Native PRoot loopback syscall enforcement maps
localhost:443 to the unchanged server port 26003 listener. An original x64 helper
imports/readbacks the prefix-local CA and verifies default Wine TLS/peer trust.
Child logs rotate, process identities are journaled, available-memory reserve is
checked and the service owns both sessions. See [current tests](TESTING.md).

CI/host fixtures cannot accept real EVE startup/login. The first 0.1.2 Thor
attempt reached the preparation preflight failure recorded below; Wine TLS and
EVE startup/login were not exercised. Preserve all prior accepted gates.
No Node, immutable server package or existing Wine/FEX binary upgrade is needed.

## October 3 startup failure and 0.1.3 certificate fix

- `eve-support-20261003-064156.zip` and the accompanying screenshot show the
  0.1.2 launcher reporting "The local server CA changed; Validate and prepare
  client again" before starting Wine or EVE. The server became ready at
  06:37:45 CDT; the first client attempt failed at 06:37:55.
- Revalidation initially required stopping the server, then completed from
  06:38:34 to 06:40:11 CDT. All 125,116 resources and the three exact patched
  binaries passed again. Both initial preparation and this revalidation recorded
  CA SHA-256 `6292129d8ed176f3da9df3c8fe0c1300810652e1c147e41388dc5dec17155beb`.
  The restarted server was ready at 06:41:44; client preflight failed again at
  06:41:47. The unchanged receipt hash and repeated successful preparation do
  not indicate actual certificate rotation or corrupt client content.
- Preparation normalized the server's CRLF PEM text to LF in the private CA
  copy, but launch compared both files' raw byte hashes. The same certificate
  therefore failed the comparison. A host reproduction with a valid CRLF CA
  confirmed different PEM byte hashes and identical decoded DER certificates.
- 0.1.3 compares DER certificate identity while retaining compatibility with
  existing preparation receipts and normalized private copies. A genuinely
  different CA remains rejected. Update in place; no client reimport,
  revalidation, runtime reinstall or repeat Wine/FEX probe is needed for the
  accepted prepared installation.
- This ZIP confirms successful revalidation and server readiness; preserve the
  earlier accepted gates. Physical Wine trust, EVE startup, display, login and
  graphics remain unqualified. The next device
  test is ready server → Start EVE client → Open client display → local test
  login → clean client/server stop → export the newest support ZIP.

## October 3 Wine TLS rejection and 0.1.4 continuation

- `eve-support-20261003-082827.zip` (SHA-256
  `5fe8678f8306842aaee6977cc11a057a2f9ce985d24e604997a54f8f7a600e52`) is from
  0.1.3. At 08:28:00 CDT server readiness passed; the private display then started
  and Wine imported/read back the exact CA (`wine_cryptoapi_trust=true`). The
  server logged TLS established at 13:28:17.983 UTC with no ALPN. WinHTTP failed
  at `connect_direct_localhost443` with error 12157. No EVE process was launched.
- The client supervisor completed cleanup (`cleanShutdown=true`, empty owned
  child member lists). The server remained running at export. About 9.3 GiB was
  available. Historical Android exit entries predate this attempt.
- Pinned Wine fork commit `a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`,
  `dlls/crypt32/chain.c`, incorrectly applies excluded directoryName subtrees to
  an empty subject. EveJS intentionally uses SAN-only empty-subject leaves under
  a constrained CA. Skip only that absent-subject comparison; all other trust
  and name checks stay active. Explicit TLS version selection would not repair
  this certificate-validation bug. The patch also preserves accumulated
  permitted-name form detection across mixed DNS/IP subtrees, so a trailing IP
  subtree cannot erase the fact that DNS names are constrained.
- 0.1.4 builds only crypt32 from the pinned source and compiler, packages its
  ARM64X/aarch64 and i386 modules in the APK, verifies the exact baseline DLL
  hashes, and binds patched DLLs only for owned EVE client sessions. `crypt32=b`
  selects builtin loading. Installed Wine/FEX, prefix, certificates, cache and
  server world remain intact. No runtime reinstall, Wine/FEX probe, import or
  resource revalidation is requested.
- New disposable-prefix CryptoAPI regression: require baseline false exclusion
  on three valid leaves, then patched success for those leaves and continued
  rejection of ten invalid cases. APK checks and guest preflight verify overlay
  hashes, architecture and session bindings. Support exports include the overlay
  receipt and bounded Wine trust warnings.
- Physical TLS/startup/display/login remains unqualified. Continue the exact
  startup/login test and return one new support ZIP. Host regression and CI
  results must be recorded before distributing the update.

## October 3 accepted startup/login and performance continuation

`eve-support-20261003-154109.zip` confirms 0.1.4 private Wine trust/localhost TLS
passed. Server logs recorded successful local authentication and character
selection; the user reached those screens and reported severe rendering/input
slowness. Clean shutdown left no owned client/display processes. This accepts
startup/login while performance remains a separate gate. ThorTest is retired
from future testing; retain its data and use a fresh disposable account.

The requested research hour ran 20:42:57–21:42:57 UTC. 0.1.5 implements native
ARM64EC DXVK 2.5.3/Turnip 26, persistent caches,30FPS/one-frame queue settings,
buffered/replacement text input, motion coalescing, grouped process metrics,
entry-only socket filters and privacy-safe display/input telemetry. See
[findings and verification limits](CLIENT-PERFORMANCE.md). CI requires real ARM
Wine/FEX shader/display and native PRoot syscall proof before distribution.

## October 3: physical Adreno preflight and 0.1.6 correction

`eve-support-20261003-180710.zip` (SHA-256
`a2577231a8ab5e1b2169c356a7e424589d06060eff02af16e79249ba19d1a4de`)
records passing localhost TLS, Turnip Adreno 740 Vulkan with three presents,
native ARM64EC DXVK hashes/feature level 11_1/correct shader pixels, and independent
RFB verification of all three visible frames. D3D helper elapsed time was 2,852 ms;
this measures the synthetic test, not EVE FPS. Cleanup was clean with no owned
groups and about 10.3 GiB available memory.

EVE did not launch in this attempt: `parse_display` could not read the formatted
`graphics-display.json`, despite its passing contents. 0.1.6 reads a whole JSON
document before the existing compact stdout-line fallback and retains all schema
checks. Supervisor regressions now use formatted receipts; native CI feeds its
actual observer file through the production reader. Older launch/client logs in
the ZIP describe the accepted 0.1.4 session, not this attempt. The next physical
gate is EVE with GPU rendering and usable input.

## October 3: EVE Adreno startup stall and 0.1.7 candidate

`eve-support-20261003-194841.zip` (SHA-256
`4a61fb9e589c78d0297f61562848f2605a28041bbdb08cda02d2cb857be5e765`)
confirms 0.1.6 passed native graphics preflight and started EVE with native DXVK
2.5.3/Turnip Adreno 740. It creates a 1280x720 swapchain but remains black with
pending shader tasks and a 2.5 FPS HUD. No recorded crash, GPU reset or OOM occurs;
the user stops cleanly. Android receive/decode/publish/draw metrics show the
screen is nearly static upstream of the display bridge. Stop overwrites live
CPU/RSS, leaving the exact stall mechanism unproven.

0.1.7 selects unmodified native ARM64EC DXVK 2.4.1, commit
`0cf05780abd7250c2cd713b7749cf32180157cf5`. Upstream DXVK issue 4484 ties a KGSL
performance regression to the 2.5 submission timeline change; exact Mesa 26 source
still emulates timelines. Reversing that code in 2.5.3 conflicts with later
transfer changes, and the proposed native KGSL timeline driver patch remains WIP.
Only D3D11/DXGI changes; Wine/FEX, Turnip, dependencies, hardware gates and display
settings remain. Old 2.5.3 shader state is retained; new state is version-owned.

Bounded CPU/RSS, compiler-thread CPU/state/wait-channel and cache metadata samples
survive Stop and include one prior session in support exports. No credentials,
command lines, stacks or images are recorded. Real socket regressions confirm
duplex input with both idle and partial-pixel reads; no input lock fix was needed.
The candidate must pass native/Android CI and then the Thor login/input test.
If still black after three minutes, export while running and stop; do not reset
accepted data or repeat the import/runtime gates.

## October 3: 0.1.7 still black and 0.1.8 owned-window candidate

`eve-support-20261003-203244.zip` (SHA-256
`0b54714dfd01b47325e2662a16e03bd7b53d6b64c8e64cc30c7ec31f608799a3`)
records the user-reported black screen without HUD. The complete combined log
still reaches native DXVK 2.4.1 swapchain setup. Thirty-six live samples over
181 seconds show idle named graphics workers, stable 1.30 GiB client RSS and
about 7.5 GiB available. CPU is mainly in other select/pipe workers; display
decode/publication/drawing remains cheap. This refutes an active background
compiler backlog as the observed workload but cannot rule out synchronous
compilation or another startup wait. EVE Adreno rendering remains unaccepted.

0.1.8 retains the same renderer/cache/driver/Wine/FEX settings. Exact DXVK source
has a foreground-dependent fullscreen occlusion path that differs from WineD3D.
An original fixed-target launcher therefore activates only its live EVE child's
owned main window once and records bounded numeric window/focus/message-pump
evidence. It does not change saved EVE settings or repeatedly take focus. The
supervisor requires a fresh session-matched child-created receipt before reporting
process startup. Native Wine/FEX qualification checks minimized negative control,
owned focus restoration, child exit forwarding and inherited Linux PGID/session;
Windows PIDs never authorize cleanup. Main-thread samples are reserved in the
existing bounded performance history. Support includes the current/prior window
receipt. Host/native/Android checks must pass before distributing the candidate;
actual EVE improvement still requires the Thor test.

## Next milestones

1. Preserve accepted server/world lifecycle, Wine/FEX probe, exact 125,116-resource
   import, private TLS, client startup and local login/character selection.
2. Physically qualify 0.1.8 EVE Adreno rendering and usable input, cold/warm-cache
   startup, display reopen and clean shutdown using a fresh local account.
3. After performance is usable, qualify character creation/station/undock/warp/dock
   and persistent reopen, then audio and controller support.

Runtime-v1 is immutable. Server package source/build input changes require a new
runtime tag and matching app URL. APK backend scripts are bound independently
and can update without replacing player data. Preview key is retained privately
in Actions cache; CI must not silently replace the signing identity.
