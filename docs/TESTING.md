# EVE Android Launcher 0.1.0: server setup preview

Target: AYN Thor Max or another ARM64 Android 8.0+ device. The first pass qualifies
local server installation and lifecycle. Client preparation is developed in
tandem; on-device EVE login and rendered gameplay are subsequent milestones.

## Install and server setup

1. Install `EVE-Android-Launcher-0.1.0.apk`. Grant the notification permission when
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

- Backend regression tests and Python/shell source checks.
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
