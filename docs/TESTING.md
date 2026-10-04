# EVE Android Launcher 0.1.10: fullscreen controller qualification

The October 4 0.1.9 test accepts Adreno rendering and usable input, with user-reported
teens/20s FPS. Preserve the renderer and current local account; do not repeat import,
runtime, TLS or the prior black-screen investigation. Controller layers/fullscreen
are the active milestone. Follow [the defaults and six-step controls test](CONTROLS.md).
Update with `EVE-Android-Launcher-0.1.10.apk`, with client/server stopped, without
uninstalling or clearing data. Further graphics optimization is deferred.

The previous graphics test and earlier recovery evidence remain below for reference.

The October 3 0.1.4 test passed Wine certificate/localhost TLS, EVE startup,
local authentication, character selection and clean shutdown. The user reported
that rendering and text entry were extremely slow. Preserve the accepted Wine/FEX
runtime, imported cache, prefix and world. No repeat import, validation or runtime
probe is required for this update.

The 0.1.5 attempt passed real Adreno 740 Vulkan, native D3D11 shaders and all three
visible probe frames. A formatted display-report parsing error stopped EVE before
launch. 0.1.6 corrects that reader; EVE responsiveness remains the next device gate.
Its subsequent EVE test presented the Adreno HUD over a black screen with pending
compilation. 0.1.7 tests native DXVK 2.4.1 synchronization compatibility and retains
live diagnostics after Stop. It also stayed black. The retained graphics workers
are idle after initialization; synchronous compilation or another EVE wait remains
possible. 0.1.8 tests one-time activation of EVE's owned window and records focus
and message-pump state. Its device test confirms an owned, focused window, but
the EVE main thread stops progressing at about 57 seconds and remains in a futex
wait. 0.1.9 tests a session-only `dxgi.syncInterval=0` override, retaining GPU
rendering, the 30 FPS cap and queue limit. This bypasses DXVK's FIFO present-wait
path; the source mechanism and limits are documented in CLIENT-PERFORMANCE.md.
The subsequent 0.1.9 device test accepts EVE rendering/input for this milestone.

## GPU and input performance test

1. Stop the client and save/stop the server, then update to
   `EVE-Android-Launcher-0.1.9.apk` without uninstalling or clearing data.
2. Start the server and wait for **SERVER READY**. In Client, leave **Use Adreno GPU
   rendering** checked, then select **Start EVE client**.
3. The launcher verifies the exact GPU assets and existing trust/TLS setup. It
   checks a real Turnip/Adreno device, native D3D11 shader pixels and three changing
   frames through the local display before launching EVE. The revised probe
   requests Present(1), while the effective DXVK configuration and observed
   presentation mode must prove that the override avoids FIFO. A small colored probe
   window is expected briefly. The startup helper then activates EVE's own window
   once; it does not continually take focus or change saved graphics settings.
   If EVE remains black for three minutes, return to Launcher and export support
   logs while it is running, then stop the client and save/stop the server. The
   retained samples also survive Stop; do not clear the prefix or shader cache.
4. Select **Open client display**. Confirm the DXVK HUD names Adreno and report
   its FPS after the login screen settles. The initial cap is 30 FPS; that is a
   target, not a measured performance promise. Describe any remaining delay in
   clicks, field selection and text entry.
5. Use a new unused local account such as `EvePerf1` and a disposable password.
   **ThorTest is retired from future testing.** Tap the username field, choose
   **Text**, and send with **Replace selected field** checked. Repeat for the
   password. The checked option selects/replaces the existing field contents;
   unchecked explicitly appends. Repeated sends should not concatenate passwords.
   Do not use a retail identity. The local development server creates new accounts.
6. Reach character selection, then return to Launcher and reopen the display.
   Report whether it remains responsive. Use **Stop EVE client**; confirm clean
   stop. Run the client once more to compare a warm shader-cache start, then stop.
7. Use **Save and stop server** and export the newest support ZIP. Return it with
   cold/warm login-screen timing, HUD device/FPS, input behavior and furthest screen.

If GPU qualification fails, export that attempt first. Stop the client, uncheck
**Use Adreno GPU rendering**, and use the previous software renderer to recover.
That option preserves the working startup path and is expected to be slower.
Do not reset the prefix/cache/world to retry. Report the exact failed stage.

Performance pass requires visible EVE rendering on Adreno and usable clicks/text
entry through login and character selection, plus clean client/server stop. A
running process, helper result or GPU device initialization alone does not prove
EVE performance. The new hardware preflight is reported separately from game
qualification. Audio, controller and gameplay tests remain later milestones.

The support ZIP includes `client/graphics-preflight.json`,
`client/client-graphics-bundle.json`, `client/run/graphics-display.json`, native
Vulkan/D3D helper logs, fresh `exefile_d3d11.log`/`exefile_dxgi.log` when EVE uses
DXVK, `client/logs/display-performance.json` and retained
`client/client-performance.json` / `client/client-performance.json.1`, alongside existing TLS/process
and server logs. Timing/count metrics omit entered text, key values and images.
`client/run/client-window.json` and its prior copy record bounded numeric window
visibility, minimization, foreground/focus ownership and message-pump response.
`client/run/dxvk.conf` records the fixed session presentation policy. The exact
DXVK frame thread is classified as `presentation` in the existing bounded history.
Framebuffer update rate measures display delivery; it is not EVE FPS. Android
frame GPU duration measures presentation of the bitmap, not the game's GPU work.

## October 3 Wine TLS result

`eve-support-20261003-082827.zip` confirms 0.1.3 reached the private display and
Wine helper. The server was ready at 08:28:00 CDT; CA import/readback passed
(`wine_cryptoapi_trust=true`). At 08:28:17 the server logged a completed TLS
handshake. WinHTTP then returned 12157, before EVE was launched. Client cleanup
completed. About 9.3 GiB of memory remained available; this is not evidence of
another client-import memory failure.

The pinned Wine crypt32 source applies an excluded directoryName constraint to
an empty subject, rejecting the valid SAN-only EveJS leaf. 0.1.4 packages only the
patched crypt32 DLLs from the same Wine commit/toolchain. A session bind and
`crypt32=b` select them without modifying the installed runtime or prefix.
The same small patch also keeps permitted-name form detection across mixed
DNS/IP subtrees, closing the pinned Wine's trailing-subtree reset bug.
Certificate signatures, expiry, hostname, DNS/IP constraints, nonempty-subject
constraints and exact CA identity checks remain enforced. The Wine regression
harness compares the original module's false rejection with the patched module
using disposable certificates and a disposable host prefix; it does not repeat
the Thor's accepted import/probe qualification.

The subsequent 0.1.4 device test passed TLS, EVE startup and local login.
Use the performance sequence above for the current preview.

## Accepted Thor recovery test

`eve-support-20261002-212837.zip` confirms the 0.1.1 recovery passed: the exact
build 3396210 cache reached `content_prepared` with all 125,116 resources and three
binary checks accepted in 6 minutes 14 seconds. Worker peak RSS was 150.6 MiB;
Android reported no low-memory condition during this attempt. The user also
reported success. Preserve the imported cache, existing runtimes and saved world.

No repeat import is required for this accepted test. The 0.1.2 update added the
startup/login actions; 0.1.3 fixes the certificate comparison before those actions
can reach Wine/EVE. The 0.1.1 build did not offer a client launch action.
Its message referring to pending server qualification is stale wording, not a
failed server gate. The recovery instructions below remain for future interrupted
imports.

`eve-support-20261003-064156.zip` confirms revalidation also passed all 125,116
resources and exact binaries on October 3, with the same recorded server CA
hash as the accepted import. Both launch attempts stopped at preflight because
CRLF-to-LF normalization changed the private PEM copy's byte hash. No EVE
startup, display or login pass can be inferred from this attempt. The 0.1.3 DER
identity check accepts the existing receipt and equivalent copy while rejecting
an actually different certificate. Continue directly with the startup test.

## Recover the interrupted Thor client import

The initial server test passed on the Thor: both starts took about 17 seconds,
the first ready session ran over 12 minutes, and both stops saved cleanly. The
Wine 10.13/FEX x64 probe also passed with its expected exit code 37. Preserve
those results; this update does not require repeating server or probe tests.

1. Update to 0.1.1 without uninstalling or clearing app data.
2. Leave the server stopped. Open Client and select **Resume interrupted client
   import**. Do not start by copying the original ZIP again.
3. If 0.1.0 left an extracted stage, recovery checks each file's size and ZIP CRC
   before reusing it. Missing/incomplete files are extracted from the retained
   ZIP. If no complete private ZIP is available, use **Import complete client ZIP**.
4. Wait through extraction, both resource-index checks, binary hashes/patches,
   and private certificate preparation. Keep the app open for this recovery test.
5. Export the newest `eve-support-YYYYMMDD-HHMMSS.zip`, including a paused or
   failed attempt, and return it with the visible final message.

Pass: client status reaches `content_prepared`, `content_imported` is true, all
indexed resources and exact binaries pass, and the app remains usable. The
support ZIP includes `client/status.json`, `client/import-session.json` while
unfinished, `client/preparation-memory.json`, and both preparation/memory logs.
A low-memory pause is safe recovery behavior but is not a passed import test.
This recovery test does not qualify EVE launch/login; use the separate startup
test above after recovery succeeds.

Preparation uses a 512 MiB worker address-space limit, bounded text/index reads,
and a small disk-backed resource index. Android memory checks pause preparation
before its free-memory reserve is exhausted. Existing server/client runtimes and
previously active content must remain intact during a failed import.

## Install and server setup

1. Install `EVE-Android-Launcher-0.1.10.apk`. Grant the notification permission when
   prompted so the running server has a visible foreground notification.
2. Open the Server tab and install the server runtime. Keep the app open during
   the initial download and extraction. Use internal storage for the runtime.
3. Prepare the server. The first preparation creates private configuration and
   writable world state. A repeated preparation must retain those saves.
4. Start the server and wait for the actual readiness status. A process launching
   or a TCP port opening does not itself count as readiness.
5. Switch briefly to another app, return, and confirm the server remains running.
6. Stop the server and confirm the stopped status. Start it again and confirm
   readiness without reinstalling or preparing a fresh world.
7. Export the diagnostic logs after the test, including failed attempts, and
   report which operation failed and the visible status message.

Do not clear Android app data to repeat this test: that removes the imported
client and saved server state. The server is loopback-only for this pass.

## Client preparation

Use the Client tab to import the exact supported EVE Windows build **3396210**
(EVE 24.01) and its complete cache. Validation reports unsupported binaries or
missing resources before any runtime launch is attempted. An unrelated current
client cannot substitute for this build.

The expected client layout is `tq/` beside `ResFiles/`, with its matching resource
indexes. Retail client files are user supplied. A successful preparation check
does not establish client gameplay compatibility: graphics integration and the
station/undock/warp/dock qualification remain pending.

## What CI verifies

- Backend regression tests, client supervision/cleanup and Python/shell checks.
- Compiled loopback address policy, basic RFB protocol/input fixtures, x64
  certificate-helper compilation and packaged client-network option.
- Controller layers/chords/holds/profile validation, shared pad/keyboard/touch
  key and mouse ownership, and actual RFB release/input event ordering.
- Native ARM64 server dependency build, initial world preparation, application
  readiness, and supervised shutdown when runtime-v1 is first created.
- Packaged rootfs structure, architecture, seed data, provenance and SHA-256.
- The ARM64 Android PRoot executable and loader, Android APK build and lint,
  actual packaged backend assets and native architecture.
- The published preview signing certificate stays stable across updates.

The published runtime-v1 archive is immutable. Later launcher builds reuse it
only when the server input fingerprint matches. Runtime input changes require a
new runtime version and a matching launcher download URL.

## Preview signing

This preview uses a dedicated signing key retained in the repository's private
GitHub Actions cache. The key is neither committed nor released. If the cache is
unavailable after the first published APK, CI refuses to replace the signing
identity; restore the original cache before publishing an installable update.
