# EVE Android Launcher 0.1.3: certificate fix and client startup

Target: AYN Thor Max, ARM64 Android13. The server lifecycle, Wine/FEX x64
probe and exact-client import/recovery have passed. Preserve those installations
and saves. This preview fixes the false CA-change failure found in the first
0.1.2 startup attempt. Physical EVE startup/local login still requires the test
below; rendering performance, audio, controllers and gameplay remain later gates.

## First EVE startup and login test

1. Update to `EVE-Android-Launcher-0.1.3.apk` without uninstalling or clearing app
   data. Keep the existing runtimes, cache, prefix and world. The accepted
   installation needs no reimport, revalidation or repeat Wine/FEX probe.
2. In Server, select **Start server** and wait for **SERVER READY**.
3. In Client, select **Start EVE client**. Preparation/binary receipts and the
   current private CA are checked, then the basic display starts. The private
   Wine helper imports/readbacks the CA and tests direct `https://localhost/health`
   with ordinary certificate checks. The client session's native socket policy
   restricts IP traffic to loopback and maps port 443 to the existing port 26003 gateway.
4. Wait for **EVE process and display started**, then select **Open client display**.
   That message establishes process startup, not successful login. A plain desktop
   may appear while EVE initializes. Allow a few minutes for its login screen.
5. Use touch to select a field, then **Text** to send a local test username such as
   `ThorTest`. Select the password field and send a disposable test password, then
   use the EVE login button or the toolbar's **Enter**. The stock local server
   auto-creates missing development accounts. Use this local test identity rather
   than a retail account. **Tab**, **Esc** and **Right click** are also available.
6. If login reaches character selection, stop there for this milestone. Briefly
   return to the launcher and reopen the display; the session should remain alive.
7. Use **Launcher** to return, then **Stop EVE client**. Confirm the client/display
   stopped. In Server, use **Save and stop server**.
8. Export the newest `eve-support-YYYYMMDD-HHMMSS.zip` from Logs. Return that ZIP
   and describe the furthest visible screen or error. Export a failed attempt too.

Startup pass: current exact-client checks and private Wine trust/TLS succeed,
`client/run/status.json` reaches `running` with display/process startup observed,
an EVE window/login screen is visible and responsive, and stop leaves no owned
client/display processes. Login pass additionally requires reaching character
selection and a corresponding successful local server authentication. Receipts
always keep login/graphics qualification false until physical evidence is accepted.
A running process or an empty desktop alone does not pass the login gate.

Fail: Wine certificate/TLS gate fails, EVE exits/crashes, the display remains
blank/unusable, local authentication fails, Android kills the app, or clean stop
fails. Preserve the cache/world and export logs; do not clear data to retry.
The renderer is basic WineD3D/llvmpipe for diagnosis; speed is not a pass criterion.

The support ZIP should contain `client/run/status.json`,
`client/run/processes.json` while a session is active, `client/client-gate.json`
after a passed TLS gate, `client/launch-observation.json` after observed startup,
`client/logs/client-supervisor.log`, `client-display.log`, `client-wineServer.log`,
`client-gate.log`, `client-client.log`, operation history and existing server logs.
On an early failure some later receipts/logs will be absent. No separate ZIP or
full client cache is needed.

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

1. Install `EVE-Android-Launcher-0.1.3.apk`. Grant the notification permission when
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
