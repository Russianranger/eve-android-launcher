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
startup/login and usable Adreno rendering/input have also been accepted on Thor.
Controllers, fullscreen, saved-character reopen and station entry are accepted by
the October 4 0.1.11 test. Audio and undock/warp/dock remain unqualified.

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

## October 3: 0.1.8 focused stall and 0.1.9 presentation candidate

`eve-support-20261003-221113.zip` (SHA-256
`5e758cce24118c65da2e9da58b4fd10092508f47ebc742d7a4a9eb9c81b5895f`)
records successful owned-window foreground/focus but 27 timed-out responsiveness
probes. EVE's main thread stops progressing after 56.9 seconds; idle graphics
workers, stable memory and inexpensive display work persist for 255 seconds.
The focus candidate did not fix the black screen. Actual DXVK presentation
switches to FIFO with present-wait enabled.

Pinned DXVK 2.4.1 waits indefinitely for FIFO presentation completion; the exact
shipped Mesa 26 software X11 copy path can return an image without advancing the
present ID that wait needs. 0.1.9 adds only private `dxgi.syncInterval = 0` while
retaining the 30 FPS cap, one-frame queue, versions, cache and game preferences.
The native probe now requests Present(1), as EVE does; both CI and physical
preflight require logged override 0, actual IMMEDIATE mode and three visible
frames. The fixed config and bounded presentation-thread class join support
exports. See [exact source and inference limits](CLIENT-PERFORMANCE.md).
The physical wait owner is unproven and EVE responsiveness requires Thor testing.

## October 4: 0.1.9 rendering accepted; controller/fullscreen continuation

`eve-support-20261004-031450.zip` (264,829 bytes; SHA-256
`85d01efb17375992caca7f3d24dba7bb12020046cdefdf7cb4636b03993050dd`)
confirms 0.1.9 on AYN Thor API33. The user reports successful login, improved
graphics in the teens and 20s FPS, and that performance works for now. Accept
Adreno rendering and usable input for this milestone. Do not repeat the earlier
black-screen qualification or the completed research hour; retain the current
renderer, caches and presentation settings. Further performance work is deferred.

The physical revised Present(1) preflight passes with effective override 0,
IMMEDIATE mode and three independently visible frames. EVE itself also logs
override 0/IMMEDIATE, and the owned 1280x720 window is focused and responsive.
The display delivers 7,876 updates over 458.264 seconds (17.19 updates/second,
not an EVE FPS measurement); 275 input operations complete with zero rejections.
Live CPU sampling confirms main/presentation-thread progress. See
[detailed performance evidence](CLIENT-PERFORMANCE.md).

The server records local handshake success, new character creation/selection and
docked fitting bootstrap. The supplied local test credentials must remain out of
committed documents, defaults and support metadata. The client subsequently exits
code 0 after 474.5 seconds; without a launcher stop request the supervisor labels
this unexpected. Owned groups are cleaned successfully, while the server remains
ready at export. Preserve the accepted visual result and track explicit shutdown,
reopen persistence and visible station/space gameplay separately.

The user now requests the TRASC launcher's controller scheme: multiple switchable
layers, persisted per-control bindings to keyboard/mouse actions, and joystick
support. Make the display fullscreen and move its toolbar actions into a gear
menu with a sci-fi/space-themed icon. Controller/fullscreen work is the active
milestone; do not change graphics policy or server/runtime packages for it.

## 0.1.10 controller/fullscreen implementation

TRASC controller behavior is pinned to
`b3bb19532eb53830af936d5e4ce95e848a46bce4`. Its pure mapper, Android adapter and
layer editor are adapted to EVE's RFB transport with four exact default layers,
one-to-six layer editing, inheritance/cyclic/direct/held switches, keyboard/chord,
mouse/wheel/cursor bindings and atomic bounded private profiles. Shared held state
aggregates pad, keyboard and touch so one source cannot release another's input.
Focus/menu/text/editor/pause/device removal release game input; disconnect releases
wire-held keys/buttons with a 250 ms socket-close deadline. Genuine gamepad source
filtering keeps physical keyboard/remote arrows from claiming the controller slot.

The display is immersive fullscreen and keeps its guest framebuffer/aspect-fit
transform. A top-right orbital gear overlays Text/Tab/Enter/Esc/right-click,
controller settings and Launcher; the toolbar no longer reserves height. Layer
changes show a short banner. Graphics policy/runtime/source pins remain unchanged.
Support includes the saved controller profile without entered login text.

Host checks cover 10,000 mixed controller transitions, binding/profile rejection,
reference-counted modifiers and controller/physical/touch RFB event ordering,
including independent wire-key release. Android build and physical Thor controls
qualification are required before accepting this milestone. See [the controls
test](CONTROLS.md). Preserve the accepted 0.1.9 visual/performance result.

## 0.1.10 display crash and 0.1.11 update

`eve-support-20261004-075810.zip` (SHA-256
`a98e24e310eed61f232ed26a226d58828b57a0aab4762a065364b2565c012ce4`)
records an Android API33 reason4 crash at 07:57:53.695 CDT on October 4.
No exception stack is exported. EVE's owned window was responsive with progressing
CPU and IMMEDIATE presentation 1.86 seconds earlier; there is no display-connected
operation in this session. The exported display-performance file is stale from
the accepted 0.1.9 session and cannot qualify 0.1.10 controls.

An Android 13 Robolectric replay using the exact 0.1.10 APK resources reproduces
`PhoneWindow.getInsetsController()` dereferencing its null decor during the first
`fullscreen()` call in `onCreate`. 0.1.11 installs the decor before requesting
its insets controller. Android construction/lifecycle tests now accompany the
pure controller/RFB checks. Physical display reopening still requires confirmation.

0.1.11 also names the default layers Main/Alt 1/Alt 2/Alt 3, safely migrates matching
old default names on load, pins both Start buttons above the tabs and gives the
app icon a dark starfield. Custom bindings/names and graphics/runtime pins remain
intact. The gear icon is unchanged, following the user's clarification.

## October 4 accepted 0.1.11 and 0.1.12 performance update

`eve-support-20261004-114813.zip` (SHA-256
`3fbeeb66d3385ffb090ba381495f3fd69d78f870f79f6a6fa4308011b3003520`)
and the user's visible station screenshot accept login, existing-character reopen,
fullscreen and usable controller controls. The screenshot shows 23.9 FPS.
Preserve these accepted gates. See [measured limits](CLIENT-PERFORMANCE.md).

0.1.12 adds selectable 60 FPS/latency-cap-2/Xvnc60 and prior 30/1/Xvnc30 profiles,
earlier bounded RFB update requests and an optional diagnostic HUD. Both profiles
retain the physically effective immediate presentation policy. The adaptive app
icon uses an opaque full-bleed space backdrop; the gear design stays unchanged.
Actual 30+ FPS must be measured on Thor, separately from helper/host results.

## October 4 regression research and 0.1.13 continuation

Recovered exact latest branch `codex/wine-localhost-tls` at
`63b46b8ee20588d49268a62e0e3684c371699eb3`; main remains 0.1.3. The prior agent
completed the 60-minute optimization report without changing repository/runtime
settings. `eve-support-20261004-171239.zip` records 0.1.12 with 60/2/60 caps and
one-ahead requests. The user reports worse performance. Neither delivery counts
nor unequal startup/scene windows establish an engine-FPS regression cause.

0.1.13 implements the first reversible experiments from that report:

- Default restoration of accepted 0.1.11 DXVK30/latency1/Xvnc30 and requests after
  each validated complete update. A versioned preference key restores baseline
  once on upgrade, then preserves explicit new profile choices.
- Separate render60, queue2 and display60 profiles plus the prior combined caps.
  Early display requests are independent, default off; both policies retain
  resize refresh, malformed-message rejection and duplex controller input.
- Optional fixed `TU_DEBUG=nocb` and `FEX_HOSTFEATURES=disablelrcpc2`, both default
  off and removed in software mode. Inherited TU/FEX feature values are stripped;
  scalar TSO remains untouched. Receipts record assignments without claiming
  native effect. Bounded readable native MIDR/topology is included separately.
- Same-signed non-debuggable/profileable APK; compiled manifest and original
  preview certificate checks gate distribution. Physical Thor PRoot startup and
  its accepted TLS/server/controls still require device confirmation.

Cached dynamic constant-buffer trials are deferred: advertised cached/coherent
Vulkan types do not prove actual KGSL returned flags or CPU-write/GPU-read
coherence. No driver/runtime upgrades, saved preference rewrite, resource import,
cache reset or world change is part of this continuation.

Native CI additionally tests all three isolated profiles and the FEX option
through exact ARM64EC DLL identity, requested Present(1), observed IMMEDIATE mode,
shader pixels and three independent visible frames. This is a Lavapipe fixture,
not an Adreno performance result. See current [test instructions](TESTING.md).

### 0.1.13 build qualification

Implementation: `16b09857058ca774f43e7b6be738f1958fd18da5` on
`codex/wine-localhost-tls`. [Actions run 37257641115](https://github.com/Russianranger/eve-android-launcher/actions/runs/37257641115)
passed verify, immutable server reuse, native Wine/PRoot/graphics, Android release
build, lint, package checks and signing-anchor equality. Release publication was
skipped for this development branch; the preview APK comes from its passing
Actions artifact.

- 164 backend tests, four server packaging tests, archive/RFB/controller and
  ARM64EC parser checks passed; 26 Android release-unit tests passed on API33/35.
- Baseline and throughput native shader/display fixtures passed, plus render60,
  queue2, display60 and disablelrcpc2 trials. Each requires the pinned EC DLL
  identities, Present(1) forced to IMMEDIATE and three independently visible
  shader frames. CPU/no-KGSL hardware-gate negative controls passed.
- Compiled package `io.github.russianranger.eve`, versionCode14/versionName0.1.13
  is non-debuggable and shell-profileable. Signing certificate SHA-256 remains
  `456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
- Delivered `EVE-Android-Launcher-0.1.13.apk`, 7,995,029 bytes, SHA-256
  `14a30de2e2b739aae5d45a34519d802abb0c12432beafb728460635b14be1a36`.

No new Thor performance or non-debuggable PRoot compatibility result exists yet.
Continue the baseline → individual nocb/FEX/render60 → baseline comparison in
TESTING.md. Keep accepted data/runtimes and record device results before claiming
recovery or sustained 30+ FPS. Cached-buffer qualification remains deferred.

## Next milestones

1. Preserve accepted server/world lifecycle, Wine/FEX probe, exact 125,116-resource
   import, private TLS, client startup/local login and 0.1.9 Adreno rendering/input.
2. Preserve accepted 0.1.11 controls/fullscreen, saved-character reopen and station
   entry. Compare 0.1.13 baseline and isolated experiments in the same warm station scene,
   with diagnostic HUD and separate support exports; the target is sustained 30+ FPS.
3. Qualify undock/warp/dock and audio using the current local account/world.

Runtime-v1 is immutable. Server package source/build input changes require a new
runtime tag and matching app URL. APK backend scripts are bound independently
and can update without replacing player data. Preview key is retained privately
in Actions cache; CI must not silently replace the signing identity.
