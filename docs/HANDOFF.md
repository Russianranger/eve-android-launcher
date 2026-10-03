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

## Next milestones

1. Accepted: server install/preparation/background/restart, Wine/FEX x64 execution
   probe, and 0.1.1 exact-client import/recovery. Preserve installed runtimes,
   imported cache, prefix and world/player data; no repeat import is needed.
2. Physically qualify the supervised startup test for the prepared EVE 24.01 build 3396210
   through the existing Wine/FEX runtime, with bounded logs and clean stop.
   Use the basic display/input to observe startup and attempt local
   login. Qualify private Wine trust, actual client endpoint routing (including
   direct localhost TLS443), and outbound traffic containment. The current
   gateway readiness check on port 26003 does not prove the client's direct port 443 path.
3. After process startup/local login evidence, improve graphics, audio and
   controller support, then qualify character select, station, undock, warp,
   dock and persistent reopen. Do not start broad graphics optimization before
   the basic client startup/login gate.

Runtime-v1 is immutable. Server package source/build input changes require a new
runtime tag and matching app URL. APK backend scripts are bound independently
and can update without replacing player data. Preview key is retained privately
in Actions cache; CI must not silently replace the signing identity.
