# EVE Android Launcher handoff

## Current 0.1.20 continuation: separate pristine Mesa 26.2.4 driver

Accept the user's neutral 0.1.19 FPS result and temperatures rising into the
low/mid 70s Celsius. [DEVICE-20261009-SURFACE.md](DEVICE-20261009-SURFACE.md)
confirms 6,364 successful surface posts with no fallback, at least 6,000 EVE SHM
transfers and a captured CPU sensor rising 61.4→73.9°C. App-window metrics now
exclude the game surface and cannot prove whole-device GPU savings. Readable
clock ceilings do not fall; no thermal-throttling proof or new current-session
crash is established. The ZIP ends at export start, so reopen continuity is
unverified. No baseline performance repeat is requested.

0.1.20 adds default-off **Use newer Turnip driver (26.2.4 experiment)**, preference
`mesa262-driver`, CLI `--mesa262-driver`. Select independent pristine KGSL asset
`turnip-26.2.4.so`, new exact-version hardware helper `mesa262-driver-probe` and
cache `mesa-26.2.4`. The immutable original and old A740/SHM driver choices remain;
driver choices exclude each other atomically while linear stays independent.
Restore baseline clears all nine flags while preserving renderer/HUD/data.

Pin the official source SHA-256
`bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9` and new probe
source SHA-256 `bb96b8e0721e167d20d8b15e433d180b79447b0bdb8f85dfaa614aa867c09d37`.
Build independently without local A740/SHM patches, preserve original ABI
requirements and record complete corresponding sources. The new driver adds
`libxcb-shm.so.0` to its ELF requirements; accept that sole additional SONAME only
after checking the actual checksum-pinned installed runtime's library, exported
symbols and dependency closure. Do not ship a runtime or library update.
Explicit new-driver `sw,noshm` / `sw,noshm,linear` policy keeps this test on ordinary
X11 transport. Keep Wine/FEX, DXVK
2.4.1 per-submit fences, IMMEDIATE presentation, full RGB, VNC comparison,
memory-pressure policy, input/fullscreen behavior and client/server data intact.

Each accepted start requires fresh original Vulkan/exact-A740 identity, selected
exact-26.2.4 hardware identity/linear capabilities, selected Vulkan presentation
and native EC shader/readback/three-visible-RFB-frame qualification. Default old
parsers remain strict 26.0.0; explicit selection accepts only the pinned newer
version and consistent physical identity. Record actual selected version/driver
hash/cache and separate requested/effective/qualified/unverified benefit fields.
Software mode does not activate the optional GPU driver.

Follow [one 0.1.20 run](TESTING.md): linear + newer driver, 30/1/display30, SHM and
separate surface off, other experiments off, FSR off, unchanged scene/fan/power.
This changes the driver and removes completed neutral transport/display trials;
rebuilt binaries can differ, so it is not a binary-identical single-factor A/B.
Do not request an old baseline solely for that reason. If worse/faulty, disable
only the newer-driver flag to recover the original driver/cache. If neutral,
bounded native render/completion/readback measurements are the next evidence
target. [CLIENT-PERFORMANCE.md](CLIENT-PERFORMANCE.md) and
[MESA-26.2-CANDIDATE.md](MESA-26.2-CANDIDATE.md) record the source rationale and
limits. Actual FPS/heat improvement and device compatibility remain unproven.

Build qualification will be recorded after CI and signed APK inspection pass.

## Historical 0.1.19 continuation: separate Android display surface

Accept the user's neutral 0.1.18 FPS/temperature result; no baseline repeat.
[DEVICE-20261008-SHM.md](DEVICE-20261008-SHM.md) proves actual EVE-sized shared
transport with at least 2,400 completed frames and no fallback. Sampled warm
copies are around 1 ms and server-reply waits around 7 µs, so this wire-leg change
has not solved performance. An earlier launcher process has Android LOW_MEMORY
exit reason; the later/current run remains alive at export capture. The ZIP ends
at export start and does not establish post-export continuity.

0.1.19 adds default-off **Use separate display surface (experiment)**, key
`separate-display-surface`. This is an Android display selection, independent of
hardware/software guest rendering; it does not add a guest CLI/environment flag
or change graphics asset selection. Restore baseline atomically clears all eight
options while preserving renderer/HUD/data. Saved settings persist across upgrade.

The experiment retains opaque full-RGB ARGB8888 framebuffer and Raw RFB. A separate
CPU Canvas surface is drawn at game resolution; the system scales/composes it
outside the app's bitmap texture drawing path. Upper gear/controller/text menus
retain normal Android UI/input. Rendering uses a bounded latest-frame worker with
surface/lifecycle checks; surface failure recovers to the original bitmap view.
Window FrameMetrics now measures only app UI, so surface phase/post/fallback
receipts and physical FPS/temperatures are required, not a lower window GPU value.

Follow only [the 0.1.19 case](TESTING.md): keep linear+SHM at 30/1/display30 and add
only separate surface; SYS/A740/other flags off, FSR off, same game/fan/power state.
The Wine/FEX/DXVK/Mesa source pins, GPU fences, IMMEDIATE mode, graphics gates,
corroborated-pressure policy and existing runtime/data remain intact.
CI still rebuilds native graphics from those same sources; resulting DLL/optional
driver byte hashes can differ. This trial selects only one new option, but is not
a controlled binary-identical A/B. Do not infer a performance change from hashes
or request a completed baseline repeat solely for that reason.
[CLIENT-PERFORMANCE.md](CLIENT-PERFORMANCE.md) records the measured target and
limits; [MESA-26.2-CANDIDATE.md](MESA-26.2-CANDIDATE.md) preserves the next primary-
source GPU/compiler candidate if the display experiment is also neutral.

### 0.1.19 build and delivery qualification

Qualified source `e658702e8ee33a4526a90517609b78e5a6ba9773` on
`codex/wine-localhost-tls`. [Actions run 37874742414](https://github.com/Russianranger/eve-android-launcher/actions/runs/37874742414)
passed backend/host regressions, server reuse, native Wine trust/PRoot/graphics,
Android release build/tests/lint and APK content/signing checks. Publication is
skipped on this branch; main remains unchanged.

- Backend: 209 tests and the RFB/controller host checks passed locally and in CI.
- Android: all 120 cases passed on API 33 and 35, with no failures/errors/skips:
  surface 20, display activity 14, settings 50, pressure 30, support export 6.
  Release lint has 38 warnings and no errors. The initial build exposed a test
  assertion reading SurfaceView's real private field instead of Robolectric's
  fake holder; the final source checks the requested RGBX8888 format on that
  holder. The production format request and full-RGB requirement are unchanged.
- Native: all nine ARM64EC shader/readback fixtures and three visible RFB frames
  per fixture passed. Production-source PRoot SHM passed 640×480 and 1280×720,
  reuse/resize/delayed teardown/cleanup and negative controls. Original driver
  dependencies/ABI and IMMEDIATE presentation policy remain qualified. These
  are Linux software-rendering CI checks; physical Adreno surface composition,
  HWC use, sustained FPS and temperature benefit remain unverified.
- Delivered APK: `EVE-Android-Launcher-0.1.19.apk`, package
  `io.github.russianranger.eve`, versionCode 20, 13,530,138 bytes; SHA-256
  `cd06ee499161de53d0aaab870a67c4afa59c4692df7359063da9cf42078c88e1`.
  Signing certificate SHA-256 remains
  `456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
  CI verified signatures and manifest/content policy. Local inspection verified
  APK ZIP integrity, certificate identity, version, new option/receipt strings,
  and all ten packaged backend Python/shell sources against the checkout.

Deliver only the focused 0.1.19 test above. The user's neutral 0.1.18 result is
accepted; no baseline performance rerun is required.

## Historical 0.1.18 continuation: shared-memory frame transport

The user ran only the 0.1.17 SYS experiment, reported no improvement and explicitly
requires no other baseline repeat unless investigating a crash. Accept that result.
[DEVICE-20261008-SYSMEM.md](DEVICE-20261008-SYSMEM.md) confirms actual SYS+linear,
fresh hardware/native pixel gates, similar warm CPU/RSS and no current crash
record. A fresh critical trim with 6.71 GiB available directly exercises the fixed
guard: client retained. The ZIP ends at export start, so do not claim post-export
continuity from this export. Earlier native DLL bytes differ despite the same
version/source pins; the historical metric comparison is not a new controlled A/B.

0.1.18 adds default-off **Use shared-memory frame transport (experiment)**.
The new `turnip-26.0.0-x11-shm.so` is built from the exact pristine Mesa 26 source
with only the X11 WSI staging patch and shared helper. It does not include the
neutral A740 register change. The immutable original remains available; A740 and
SHM driver selections exclude each other. Renderer/HUD and other independent
experiments remain saved. Restore baseline clears all seven flags.

Each eligible CPU-mapped image gets its own bounded SysV stage. After the existing
GPU fence, a CPU memcpy fills that separate stage and a small SHM PutImage request
replaces the full X11 pixel payload. The helper issues a geometry request after
the shared read; it waits for that reply before overwriting the stage or teardown.
The Vulkan source image can become available independently, preserving overlap.
The old early geometry query/resize check remains. Full RGB, IMMEDIATE policy,
Xvnc framebuffer comparison, RFB, opaque Android bitmap and controls are retained.
Allocation/attach failures use safe ordinary PutImage fallback. Qualification
requires actual successful SHM completion records from the selected native EC
helper, not just a flag or correct pixels; a fallback does not pass this experiment.

Thin fixed-protocol wrappers use core XCB without adding a runtime library.
The strict dependency/ABI comparison against the original driver remains a gate.

The production patch and native transport fixture share the same header. CI must
exercise that helper under the production-source PRoot SysV namespace with Xvnc,
verify exact pixels/visible frames, reuse, resize, pending teardown and negative
controls. Server-grab cases hold reads pending during reuse and teardown, and
server-death cleanup verifies segment removal. Retain the existing nine native EC shader/readback/RFB fixtures.
Lavapipe cannot initialize KGSL Turnip; physical activation and performance remain
Thor checks. Fresh original A740 identity and selected-driver Vulkan/EC shader/
readback/RFB checks precede EVE. Old driver/cache and accepted runtime/data remain.
The new driver uses its own Mesa cache; first-run warm-up is not a measured gain.

The single device case uses linear+SHM, SYS and A740 off, responsive 30/1/display30.
No old cap/FEX/binning/SYS matrix or new game-quality changes. CPU copying, Xvnc
copying and RFB still exist, and no dominant bottleneck or stable-30 result is
established. [CLIENT-PERFORMANCE.md](CLIENT-PERFORMANCE.md) records the research;
[TESTING.md](TESTING.md) supplies the one-run instructions.
### 0.1.18 build and delivery qualification

Implementation `696b2f612dc0384f01683836283cf24c43b9dcff` on
`codex/wine-localhost-tls`. [Actions run 37867367620](https://github.com/Russianranger/eve-android-launcher/actions/runs/37867367620)
passed all build jobs: backend/host regressions, immutable server reuse,
native Wine trust/PRoot/graphics, Android release build/tests/lint and APK
content/signing checks. Development publication is skipped; main was not changed.

- Backend: 209 tests passed, including strict experiment manifest pins,
  mutually exclusive driver selection, inherited-environment cleanup, fresh
  qualification receipts and positive/negative SHM completion parsing.
- Android: 96 cases passed across API 33 and 35, no failures/errors/skips:
  display 12, performance settings 48, pressure 30, support export 6.
  Release lint has 37 warnings and no errors.
- Native: all nine exact ARM64EC shader/readback/three-visible-RFB-frame fixtures
  passed. Real SHM fixtures under production-source PRoot passed at 640×480 and
  1280×720, including reuse, resize, pending teardown and cleanup. Server-grab
  controls blocked reuse/teardown for 199.85–200.86 ms until release. Allocation,
  mapping, attach rejection, bounds, missing extension and server-death controls
  passed; actual segment disappearance and 17 memfd allocations were observed.
  The activation parser rejects all negative controls. These use native Linux
  libc and software rendering; Android/physical Adreno activation and sustained
  FPS/temperature benefit remain unverified.
- The driver retains all 11 original dynamic dependencies and original ABI
  limits, without libxcb-shm. Driver SHA-256:
  `ed8a9566755001c59696a3de7a2c46a8724e3fcacdb2cd0df1d24aa58c738be1`.
  Header, probe, patch, Mesa and PRoot provenance pins match repository source.
  Independent native/source reviews found no material blockers.
- Downloaded artifact ZIP digests and source SHA match GitHub metadata. Local APK
  inspection passes: all ten tracked backend Python/shell assets match source
  byte for byte, experiment strings/assets are packaged, strict manifest checks
  pass, and the embedded v2 certificate matches CI's signing verification.

Built **EVE-Android-Launcher-0.1.18.apk**, 13,524,242 bytes, versionCode 19,
non-debuggable with shell profiling enabled. APK SHA-256:
`0cee955a4291ad6bd1f15431da1d3eaf09a611ff1562565a9a2c55d423aa9c16`.
Existing signing-anchor SHA-256:
`456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
Install in place with client/server stopped and preserve existing data/runtime.
Use only the one linear+SHM case above; accepted neutral SYS needs no baseline
repeat unless a new fault requires isolation.

## Historical 0.1.17 continuation: direct GPU rendering alongside linear

[The October 8 evening exports](DEVICE-20261008-EVENING.md) are a true A/B:
baseline `sw`/linear=false versus `sw,linear`/linear=true, with the original
driver and responsive 30/queue 1/display 30. The user reports a small FPS gain
and slight cooling from linear. Matched warm CPU/RSS and cpuss-0 means remain
similar (~68°C); GPU ceilings remain 680 MHz. Logs do not record engine FPS or
prove throttling. The baseline export completed and the same client remained
alive after reopening; no fresh pressure-guard event appears in either export.

Upstream Mesa 26.1 prefers SYSMEM for DXVK/VKD3D because these games commonly
favor it over GMEM. The pinned Mesa 26.0.0 already has `TU_DEBUG=sysmem`. 0.1.17
adds independent default-off **Use direct GPU rendering (experiment)** to select
that existing mode. This is a forced older-driver mode, not a backport of newer
Mesa's full autotuner. It can increase memory traffic/heat or reduce performance.
Keep the original driver; test linear alone versus linear+SYS, not the previous
cap/binning/FEX/A740 matrix. No game-quality changes are included.

Session assignments use only `sysmem` or the existing fixed combination
`nocb,sysmem`; inherited TU flags are scrubbed, software ignores the selection,
and off restarts clear it. Fresh original-driver Vulkan/exact-A740 identity,
selected-environment Vulkan, exact ARM64EC D3D11 shader/readback and three visible
RFB frames qualify compatibility before EVE. Receipts distinguish requested,
effective and independent gate results, retaining `nativeEffectVerified=false`:
the helpers do not prove the physical render-mode choice or sustained benefit.
An accepted start removes stale preflight output before preparation/TLS; a
rejected start preserves the previous session evidence. Baseline
reset now clears all six experiments atomically and keeps renderer/HUD/data.

The Android display bitmap remains ARGB_8888 with full 8-bit RGB. Since decoded
RFB pixels are all opaque, allocation now uses hasAlpha=false, matching black
untouched pixels and allowing Android's opaque drawing hint. Lifecycle tests
cover partial updates, reuse, resize, rendering and destruction. Both test arms
include this hint; the A/B isolates only SYS. The pressure correction, bounded
telemetry, completion fences, IMMEDIATE policy, runtime/native driver pins,
shader caches, prefix/world/account and fullscreen controls remain intact.

[CLIENT-PERFORMANCE.md](CLIENT-PERFORMANCE.md) ranks the research and deferred
transport work. [TESTING.md](TESTING.md) gives the next focused physical trial.
### 0.1.17 build and delivery qualification

Implementation `568d1416e3e13e448f71f006a3c93c42bb8a84a8` on
`codex/wine-localhost-tls`. [Actions run 37860125710](https://github.com/Russianranger/eve-android-launcher/actions/runs/37860125710)
completed successfully: backend/host regressions, immutable server reuse,
native Wine trust/PRoot/graphics, Android release build/tests/lint, APK content
checks and signing-anchor equality. Development release publication is skipped;
main remains `b3880ff92049ce690b6ae0f6f23b6d8c84a7f292`.

- Backend: 197 tests passed, plus server package, archive, display/controller,
  graphics observer and native EC parser/mutation checks. Early accepted TLS
  failure clears old qualification; rejected/busy starts retain its evidence.
- Android: 86 cases passed across API 33 and 35, no failures/errors/skips:
  display 12, performance settings 38, pressure 30, support export 6. New SYS
  persistence/reset/launch behavior and opaque bitmap partial-update/resize/draw/
  destruction tests pass on both APIs. Release lint has 36 warnings, no errors.
- Native: all nine exact ARM64EC shader/readback/three-visible-RFB-frame fixtures
  and software/no-KGSL hardware rejection controls passed. Actual SYS-only and
  linear+SYS assignments match production; later trials clear them. Present(1)
  is forced to IMMEDIATE. Driver/source/helper pins and Wine/FEX byte identities
  match 0.1.16. These are 320×240 Lavapipe integration fixtures with
  `nativeEffectVerified=false`, `physicalThorQualified=false`, not Adreno FPS proof.
- Independent source/UI/native evidence reviews found no remaining issues.
  Downloaded ZIP digests match GitHub artifact metadata and the implementation
  SHA. Local APK checks pass; all ten tracked backend Python/shell assets match
  source byte for byte, and the new UI/flag strings are packaged.

Delivered **EVE-Android-Launcher-0.1.17.apk**, 10,764,017 bytes, versionCode 18,
non-debuggable with shell profiling enabled. APK SHA-256:
`d330fe8d1fd564135c57b352b3024d16891af62a2aa405ae77ebc53aea98c245`.
The embedded APK v2 certificate fingerprint was independently checked against
CI's full signature verification and the existing signing anchor SHA-256:
`456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
Install in place with client/server stopped; preserve import/runtime/prefix,
shader caches, world/account and mappings. No reimport or validation is needed.
Test linear alone versus linear+SYS using TESTING.md. Sustained 30 FPS, heat
benefit and physical geometry/input/export continuity remain Thor gates.

## Historical 0.1.16 continuation: export-time pressure stop and baseline clarity

The October 8 user reports slight linear FPS improvement, 72°C and a client
closure while exporting. [DEVICE-20261008.md](DEVICE-20261008.md) records the exact
session/event analysis. Both supplied ZIPs retain requested/effective linear=true
and `MESA_VK_WSI_DEBUG=sw,linear`, including the one labeled baseline. Fresh exact
A740 capability/Vulkan/EC shader/readback/RFB gates and actual EVE BGRA8/720p
IMMEDIATE swapchains passed. This supports compatibility, not an A/B performance
or heat conclusion. Do not treat the filenames as actual configurations.

The first session was deliberately stopped by our unconditional trim level 15 guard at
16:24:28, with cleanup 16:24:30 and export beginning 16:24:45. At the event,
lowMemory=false, available 4.66 GiB, threshold 216 MiB. No fresh native/game crash or
Android kill is recorded; server remains ready. The same event is in both ZIPs.
The second session remained alive when exporting. The earlier 0.1.14 safeguard
was too aggressive and is corrected before another physical performance trial.

0.1.16 records critical trims but requires fresh corroboration: Android lowMemory
or a valid available-byte reading at/below its positive low-memory threshold.
Ample or unavailable readings retain the client. Asynchronous work is bound to
its original session and rechecked before delayed stop dispatch; manual stop
precedence and server ownership remain. Abrupt LMKD protection remains best effort.

**Restore baseline settings** explicitly restores responsive 30/queue 1/display 30
and clears all five experiment flags in one preferences transaction. It retains
HUD, renderer, caches and unrelated settings. Ordinary profile selection remains
cap-only; the visible summary distinguishes baseline caps from active experiments.
No automatic preference reset on upgrade occurs. The next physical test uses the
reset action for an actual `sw` baseline, then only linear after cooling.

New bounded read-only hardware observations retain driver-reported GPU frequencies,
CPU scaling/requested state and thermal driver labels/units where readable. Missing
or denied sysfs data remains explicit; no root permission, clock, governor or
thermal-policy change is made. The existing history size limits remain enforced.
User-reported 72°C was not recorded by prior battery 41–43°C/thermalStatus0 fields;
no existing evidence proves throttling. Matched warm clientCPU ~202–204% and
RSS ~3 GiB are similar; compiler workers are idle and Adreno completion waits recur.

Keep original Turnip 26/Wine 10.13/FEX 2510/native DXVK 2.4.1, IMMEDIATE policy,
client build 3396210/EVE.js 0.12.9, world, fullscreen and controls. No new third GPU
experiment or further game-quality tuning is introduced. Optional SHM staging is
an audited later candidate, not an unqualified toggle; see CLIENT-PERFORMANCE.md.
Build/device qualification follows below. [TESTING.md](TESTING.md) has the focused
export-continuity and actual original-versus-linear comparison.

### 0.1.16 build and delivery qualification

Implementation `fe285e127ee84e8c2bc510e4b66b063fb5923f49` on
`codex/wine-localhost-tls`. [Actions run 37849222118](https://github.com/Russianranger/eve-android-launcher/actions/runs/37849222118)
passed backend/host regressions, immutable server reuse, native Wine trust/PRoot/
graphics, Android release build/tests/lint, APK content checks and signing-anchor
equality. Development release publication is skipped; main remains unchanged at
`b3880ff92049ce690b6ae0f6f23b6d8c84a7f292`.

- Backend: 188 tests passed; server package, archive, display/controller,
  graphics observer and ARM64EC parser/mutation checks passed.
- Android: 82 cases passed across API 33 and 35, no failures/errors/skips:
  display 10, performance settings 36, pressure 30, support export 6. Release
  lint completed with 36 warnings and no errors.
- Native: all seven exact ARM64EC shader/readback/three-frame RFB fixtures and
  CPU/no-KGSL/A740/linear rejection controls passed. IMMEDIATE policy remains.
  Native source/driver pins are unchanged; CI remains lavapipe qualification,
  `physicalThorQualified=false`, not a physical performance result.
- Independent review confirmed the final guard, reset/UI, telemetry bounds and
  downloaded native/Android evidence. Downloaded ZIP digests match GitHub;
  local APK checks pass and all ten tracked backend Python/shell files match
  checked-out source byte for byte.

Delivered **EVE-Android-Launcher-0.1.16.apk**, 10,762,921 bytes, versionCode 17,
non-debuggable with shell profiling enabled. APK SHA-256:
`a473a283e5c646d06a3557154b0c6de6660abc0c53a239294c4e04d5c567f5d1`.
The embedded APK v2 certificate was independently checked and matches the
CI-verified signing anchor SHA-256:
`456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
Update in place with client/server stopped; preserve import, runtime, prefix,
shader caches, account, world and mappings. No reimport or revalidation is needed.
Physical export continuity and sustained FPS/temperature require the focused
Thor comparison in TESTING.md; no stable-30 or heat improvement is claimed.


## Historical 0.1.15 continuation: linear presentation

The October 7 FSR test helped modestly but introduced black lines; the user
explicitly requests optimization outside game settings. The original driver
remains preferred after the neutral warmed A740 comparison. Do not repeat those
experiments or promote Snapdragon 8 Elite recipes as qualified Thor settings.

The supplied screenshot shows Adreno 740/Mesa 26, 24.7 FPS and HUD GPU 98%.
[DEVICE-20261007.md](DEVICE-20261007.md) records the fresh clean-exit log evidence.
Warm shader workers are effectively idle, RSS is about 3 GiB and graphics threads
repeatedly wait for Adreno completion. DXVK GPU% is derived from completion-queue
idle ticks, not hardware utilization; it includes copy/fence pressure and does
not prove a shader-only bottleneck or thermal throttling.

0.1.15 adds default-off **Reduce GPU frame copies (experiment)**. The pinned
Mesa 26 `sw,linear` CPU-WSI path maps the linear swapchain image directly rather
than using an optimal image plus GPU image-to-buffer staging copy. It retains
XCB/Xvnc/Raw RFB, rendering completion waits and IMMEDIATE presentation. Linear
layout can hurt rendering and cannot promise 30 FPS. No runtime/driver/DXVK
version, game preferences, shader cache, import, world or controls are changed.

A current-session original-driver Vulkan check and source-built A740 identity
helper require exact chip 0x43050a01 plus LINEAR BGRA8/RGBA8 UNORM capability for
1280×720, COLOR_ATTACHMENT|TRANSFER_DST, sample 1/mip 1/layer 1. The selected
presentation environment then independently repeats native Vulkan, exact ARM64EC
D3D11 shader/readback and three visible RFB frames. Software ignores the flag;
receipts retain requested/effective state and nativeEffectVerified=false.
The old optional driver and this flag remain independently selectable, but the
focused Thor comparison uses only this flag and the original driver.

Support export now reserves current client receipts, run files and graphics/
performance logs before server history. The prior shared 100-entry budget let 94
server files crowd current client diagnostics out of the October 7 ZIP. Global
limits, log tails and symlink/privacy checks remain bounded.

Build qualification is recorded below; physical EVE performance needs the Thor test.
Follow [the focused test](TESTING.md); update in place without data reset.


### 0.1.15 build and delivery qualification

Implementation `77a8eaef6142b81a58056141777817a422493828` on
`codex/wine-localhost-tls`. [Actions run 37617363750](https://github.com/Russianranger/eve-android-launcher/actions/runs/37617363750)
passed verify, immutable server reuse, native Wine trust/PRoot/graphics,
Android release tests/build/lint, APK content checks and signing-anchor equality.
Development release publication is skipped; main remains unchanged.

- 179 backend tests, four server package tests, archive/RFB/controller fixtures
  and ARM64EC parser checks passed. All 58 Android release-unit cases passed on
  API 33/35: display 10, performance/UI 28, memory-pressure 14, support-export 6.
- All seven EC shader/readback/RFB fixtures passed, including the new isolated
  linear environment with responsive 30/latency 1/display 30. The linear test
  independently observed frames [0,1,2] in five RFB updates, verified both queried
  formats, native EC DLL hashes and IMMEDIATE swapchains despite Present(1).
  The fixture uses Mesa 22.3.6 Lavapipe/LLVM 15, not physical Turnip 26. Reports retain
  physicalThorQualified=false and nativeEffectVerified=false.
- Production rejected the software capability receipt. CPU hardware mode failed
  adapter selection with zero presents; original and optional Turnip each failed
  Vulkan enumeration without KGSL. Existing native gates remain enforced.
- Original Turnip SHA-256 remains
  `51b968eed13c933d114cdc2956135758917e48451129f647ecb5ebbea5a527eb`.
  Updated identity/capability source SHA-256 is
  `8bd8d2faf2e959baad024be4d0e185942a92584d5f04b91de287d4f1527e4371`.
- Delivered `EVE-Android-Launcher-0.1.15.apk`, 10,758,025 bytes, SHA-256
  `f8096cdb2c2f15e8b4934a26798cee164adafe878de290efdb9207f16b193971`.
  Package `io.github.russianranger.eve`, versionCode16/versionName0.1.15,
  non-debuggable and shell-profileable. Signing certificate SHA-256 remains
  `456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
  Root rechecked downloaded archive digests, compiled certificate, APK contents,
  runtime manifests and exact backend/native-source identities before delivery.

Physical startup, linear allocation/presentation, station geometry, sustained FPS,
controls/reopen and clean exit still need the focused Thor test in TESTING.md.
No further game-quality comparison is the next task.

## Historical warmed A740 repeat

The user repeated 0.1.14 with the A740 driver option enabled after its first
cache warm-up. Performance was similar: typically 26 FPS, ranging 22–30, with
device temperature about 61–63°C initially and 66–70°C after warm-up depending
on camera movement. No new logs accompany this observation. This gives no
observed improvement; prefer the original driver and consider the station
driver comparison complete. The user also inspected the videos: Snapdragon
8 Elite and different system-driver combinations do not supply useful settings
for Thor/Adreno 740. The next pass must address an independent, qualified
optimization while preserving the accepted runtime, client, world and controls.
This historical comparison proposed EVE's DX11-compatible FSR1; it is now
complete with modest improvement and black-line artifacts. The exact-source
[display and cached-buffer audit](CLIENT-PERFORMANCE.md) preceded the optional
0.1.15 linear presentation implementation.

## Latest October 5 device feedback and research

The two 0.1.14 baseline/A740 exports show clean code-0 closure and no new Android
kill; the user reports high60s/low70s Celsius and performance still below stable
30 FPS. [DEVICE-20261005.md](DEVICE-20261005.md) records the selected A740 driver
hash and passed hardware/helper identities, matched warm CPU/RSS measurements,
and its separate first-run shader-cache caveat. Warm CPU is effectively equal,
with no demonstrated warm performance gain. Memory timelines show no critical
pressure; battery readings do not explain the reported high device temperatures,
and actual clock/SoC traces are absent. Do not infer that the pressure
handler prevented a kill or that the driver experiment has won.

A firsthand Reddit commenter identifies Winlator 11 beta and reports getting
EVE working. The thread links a February 1 Snapdragon 8 Elite demonstration;
that creator also published a March 13 settings/game-test video. The commenter's
version is not verified as either video's configuration. Retrieved evidence
does not provide a complete Wine/translator/DXVK/Turnip/FPS recipe or an 8 Gen 2
stable30 combination. Keep the accepted runtime intact while researching
reproducible combinations; public-client reports do not qualify our exact build.

## Current 0.1.14 continuation

The October 5 four-run evidence is recorded in [DEVICE-20261005.md](DEVICE-20261005.md).
The baseline was an Android LOW_MEMORY kill. Other exports show code-0 EVE
exits with completed cleanup; they do not prove three more crashes. Warm RSS
plateaus near 3 GiB, with recurring Adreno completion waits and no warm compiler
work. Heat was observed; throttling is not established by the old logs.

0.1.14 adds best-effort Android 13 critical running-memory protection, bounded
memory/thermal histories, correct observed code-0 exit reporting, and an optional
Mesa 26.0.0 A740 register backport. The original driver stays default. Exact
Thor chip ID 0x43050a01 is required under the baseline driver before selection,
followed by the existing native Vulkan/D3D11/pixel/display checks under the new
driver. Physical geometry and performance remain unqualified; related register
values historically caused vertex corruption. Follow the two-run TESTING.md
comparison. Preserve all accepted account/world/runtime/fullscreen/control gates.

### 0.1.14 build and delivery qualification

Implementation `56c332a7645ab10b8a3c5b65f1a234f983fd284e` on
`codex/wine-localhost-tls`. [Actions run 37300719277](https://github.com/Russianranger/eve-android-launcher/actions/runs/37300719277)
passed verify, immutable server reuse, native Wine trust/PRoot/graphics, Android
release tests/build/lint, package checks and preview signing-anchor equality.
Development-branch release publication was skipped; main remains unchanged.

- 173 backend tests, four server packaging tests, archive/RFB/controller and
  ARM64EC parser checks passed. 48 Android release-unit cases passed on API 33/35,
  including 14 pressure cases and 24 performance/UI cases.
- All six native shader/RFB fixtures passed with three independently visible
  frames and forced IMMEDIATE presentation. A740 software-identity and both
  no-KGSL driver negative controls passed. The identity helper creates no device
  or queue. Original driver bytes remain pinned and unchanged.
- Rebuilt A740 driver SHA-256
  `0d16491675a04da2266be778124b94eccec690a004e8a2e589dc4cc9bd742620`,
  13,841,568 bytes. Native ABI comparison against the baseline passed: no new
  SONAMEs, GLIBC no newer than 2.34, CXXABI no newer than 1.3. Exact source,
  single-register patch and native probe inputs matched provenance.
- Delivered `EVE-Android-Launcher-0.1.14.apk`, 10,755,969 bytes, SHA-256
  `19d2613e0985d1ba18a46e1b2062bc2ec909507bf674b36bf9c302d506a91037`.
  Package `io.github.russianranger.eve`, versionCode15/versionName0.1.14,
  non-debuggable and shell-profileable. Certificate SHA-256 remains
  `456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
  Downloaded APK assets/hashes, package identity and manifest were checked again.

The pressure stop is best effort for Thor Android13; abrupt LMKD kills may lack
a callback. Android34+ no longer dispatches RUNNING_CRITICAL. API35 fixtures
verify handler logic, not a platform notification guarantee; timeline sampling
works separately. This build does not accept physical A740 performance or
geometry correctness and does not promise 30+ FPS. Cached buffers remain deferred.

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

- Default restoration of accepted 0.1.11 DXVK30/latency 1/Xvnc30 and requests after
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
  ARM64EC parser checks passed; 26 Android release-unit tests passed on API 33/35.
- Baseline and throughput native shader/display fixtures passed, plus render60,
  queue2, display60 and disablelrcpc2 trials. Each requires the pinned EC DLL
  identities, Present(1) forced to IMMEDIATE and three independently visible
  shader frames. CPU/no-KGSL hardware-gate negative controls passed.
- Compiled package `io.github.russianranger.eve`, versionCode14/versionName0.1.13
  is non-debuggable and shell-profileable. Signing certificate SHA-256 remains
  `456c617128420fd315e1aa453d154e3d08f71a9b593d91966d21f75eed3a2c15`.
- Delivered `EVE-Android-Launcher-0.1.13.apk`, 7,995,029 bytes, SHA-256
  `14a30de2e2b739aae5d45a34519d802abb0c12432beafb728460635b14be1a36`.

At that build's delivery, no new Thor performance or non-debuggable PRoot result
existed. The October 5 exports now supersede that pending comparison; see the
0.1.14 continuation above. Cached-buffer qualification remains deferred.

## Next milestones

1. Preserve accepted server/world lifecycle, Wine/FEX probe, exact 125,116-resource
   import, private TLS, client startup/local login and 0.1.9 Adreno rendering/input.
2. Preserve accepted 0.1.11 controls/fullscreen, saved-character reopen and station
   entry. The warmed 0.1.14 A740 repeat showed no observed improvement; its
   station comparison is complete. Qualify the next independent optimization
   against the exact Adreno 740/runtime; the target is sustained 30+ FPS.
3. Qualify undock/warp/dock and audio using the current local account/world.

Runtime-v1 is immutable. Server package source/build input changes require a new
runtime tag and matching app URL. APK backend scripts are bound independently
and can update without replacing player data. Preview key is retained privately
in Actions cache; CI must not silently replace the signing identity.
