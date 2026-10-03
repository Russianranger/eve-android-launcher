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
PRoot/Android behavior. The first device gate is install/prepare/start/switch-apps/
stop/restart and support-log export. Full client assets have not been imported
here, so EVE login, rendering, audio and controllers remain unqualified.

The client probe reports only successful x64 execution in Wine/FEX. Client TLS
preparation does not pretend that Wine CryptoAPI trust or direct localhost443
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
  resume action using the surviving private ZIP/stage. Full Thor recovery remains
  a physical gate; do not claim this fix proves client login or rendering.

## Next milestones

1. Server install/preparation/background/restart and Wine/FEX x64 probe accepted.
   Qualify the 0.1.1 interrupted client import recovery on the Thor.
2. Import exact complete EVE client build3396210; qualify Wine/FEX probe and
   private Wine trust plus all local gateway endpoints, including direct TLS443.
3. Add accelerated client display/input/audio and prove character select, station,
   undock, warp, dock and persistent reopen before controller/UI polish.

Runtime-v1 is immutable. Server package source/build input changes require a new
runtime tag and matching app URL. APK backend scripts are bound independently
and can update without replacing player data. Preview key is retained privately
in Actions cache; CI must not silently replace the signing identity.
