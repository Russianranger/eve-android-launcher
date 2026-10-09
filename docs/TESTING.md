# EVE Android Launcher 0.1.20: one newer Turnip driver experiment

## Current 0.1.20 test

Your surface run really used the new path but did not improve FPS; temperatures
rose into the low/mid 70s Celsius. Accept that result. No surface or baseline
performance rerun is requested. This build tests a separate pristine Mesa 26.2.4
KGSL driver while retaining Wine/FEX and DXVK 2.4.1, completion fences, full RGB
and IMMEDIATE presentation. The original driver and shader caches remain available.

1. Stop client/server, then install **EVE-Android-Launcher-0.1.20.apk** over the
   existing app. Keep app data, import, runtime, prefix, account/world, caches
   and mappings. No reimport or validation is needed.
2. Keep **Use Adreno GPU rendering** enabled. Tap **Restore baseline settings**,
   then enable only **Reduce GPU frame copies (experiment)**,
   **Use newer Turnip driver (26.2.4 experiment)** and HUD. Confirm
   30 FPS / queue 1 / display 30. Shared-memory transport, separate display
   surface, SYS, A740, binning, alternate CPU instructions and early requests
   stay off. This tests one driver candidate using the original Android display
   and ordinary X11 transport; it is not a binary-identical single-factor A/B.
3. Keep FSR off and the same 1280×720 station/game settings/fan/power mode.
   Start server → SERVER READY → EVE client → Open client display. Startup
   requires fresh original and selected-driver qualification; confirm the HUD
   reports Mesa 26.2.4. Check ships, station geometry, text/colors, transparency,
   fullscreen, gear/controller layers, mouse/touch and text entry. The new
   version has a separate Mesa cache, so first-use shader warm-up is expected.
4. Warm three minutes, then observe two minutes with a static camera and
   two minutes while moving the camera. Record HUD FPS range, starting/ending SoC temperatures, stutter
   and input delay. Export while running as **0.1.20-linear-mesa262**, reopen
   the display and confirm the same session and controls remain usable.
   Quit normally, then save and stop the server.

Return this single labeled ZIP, FPS/temperatures and visual/input/export faults.
If startup qualification fails, export immediately and report the stage rather
than deleting data. If worse or faulty, stop and disable only **Use newer Turnip
driver** to recover the original Mesa driver/cache while keeping linear.
If a crash occurs, reopen and export before restarting; a baseline run is only
needed to isolate that fault. Engine FPS and actual temperatures determine
benefit; display-update rates or passing compatibility gates do not.

Earlier instructions remain below as historical evidence.

## Completed 0.1.19 test

Your shared-memory run really used the new transport but did not improve FPS or
heat. That result is accepted; no baseline rerun is requested. This build tries
one different target: Android display composition through a separate surface.

1. Stop client/server, then install **EVE-Android-Launcher-0.1.19.apk** over the
   existing app. Keep app data, import, runtime, prefix, caches, account/world and
   mappings. No reimport or validation is needed.
2. Keep **Use Adreno GPU rendering** enabled. Tap **Restore baseline settings**,
   then enable **Reduce GPU frame copies (experiment)**, **Use shared-memory frame
   transport (experiment)**, **Use separate display surface (experiment)** and HUD.
   Confirm 30 FPS / queue 1 / display 30, with only those three experiments.
   SYS, A740, binning, alternate CPU instructions and early requests stay off.
3. Keep FSR off and the same resolution/station/game settings/fan/power mode.
   Start server → SERVER READY → EVE client → Open client display. Check full
   RGB colors, ships/text/transparency, aspect ratio/black bars and fullscreen.
   Open the gear menu, use controller layers, touch/drag/right-click and text
   entry; the menu and keyboard must remain above the game image.
4. Warm three minutes, then observe two with static camera and movement
   separately. Record HUD FPS range, starting/ending SoC temperatures, stutter
   and input delay. Export while running, label **0.1.19-linear-shm-surface**,
   reopen the display and confirm the same session/controls remain usable.
   Briefly leave/reopen once to check the surface redraws rather than remaining
   black. Quit normally, then save and stop the server.

Return this single labeled ZIP with FPS/temperatures and visual/input/export
faults. The export records actual surface posts and phase costs. A lower app-window
GPU metric alone is not proof of less total GPU work or better EVE performance.
If the surface path fails, it should recover through the existing bitmap display
and record that fallback. If worse or faulty, stop and disable only **Use separate
display surface**; the prior linear+SHM setup remains available. If a crash occurs,
reopen and export before restarting; a baseline test is only needed to isolate
that fault. Do not reimport or delete any data.

Earlier instructions remain below as historical evidence.

## Completed 0.1.18 test

Your SYS+linear run showed no improvement. That result is accepted; no repeat of
linear-only or the old baseline/SYS matrix is required. The log records no
current crash evidence and directly validates the repaired ample-memory guard.

Install **EVE-Android-Launcher-0.1.18.apk** over the existing app with client and
server stopped. Keep app data, import, installed runtime, prefix, shader caches,
account/world and mappings. No reimport or validation is needed; signing identity
remains the same. This adds a separate WSI-only shared-memory driver and leaves
the original available. Its cache starts separately, so allow shader warm-up.

1. With the client stopped, keep **Use Adreno GPU rendering** enabled. Press
   **Restore baseline settings**, then enable **Reduce GPU frame copies
   (experiment)**, **Use shared-memory frame transport (experiment)** and the HUD.
   Confirm render 30/queue 1/display 30 and only **Reduce GPU frame copies,
   Shared-memory frame transport** in the experiment summary. Direct GPU rendering,
   A740, binning, alternate CPU instructions and early requests should be off.
2. Keep FSR off and the same 1280×720 station, character, game settings,
   camera/windows and Thor fan/power mode. Start server → **SERVER READY** → EVE
   client → Open client display. Check geometry, ships, text, transparency,
   fullscreen and controls. Startup also checks actual SHM use; if it fails,
   export immediately and report the stage rather than reimporting anything.
3. Warm three minutes, then observe two, checking static camera and movement
   separately. Record warm HUD FPS range, stutter/input delay and starting/ending
   SoC temperature. Export while running as **0.1.18-linear-shm**, reopen the
   display and confirm the same session and controls remain usable.
4. Quit normally, then save and stop the server. If the new path is worse or shows
   faults, disable only **Use shared-memory frame transport** after stopping;
   that restores the original driver and its cache while retaining linear.

Return this single labeled ZIP, FPS range, starting/ending temperatures and
visible/input/export faults. Display updates are not engine FPS. Shared-memory
activation/phase timing proves the transport path, not a sustained FPS/heat gain.
If a crash occurs, reopen and export before restarting; a baseline rerun is only
needed if that fault requires isolating the new path.

Earlier instructions remain below as historical evidence.

## Completed 0.1.17 SYS experiment

Install **EVE-Android-Launcher-0.1.17.apk** over the existing app with client and
server stopped. Preserve app data, imported client, runtime, prefix, shader
caches, account/world and mappings. No reimport or validation is needed; preview
signing identity remains the same.

Your latest reports favor linear slightly. This test keeps linear in both arms
and changes only the new direct GPU rendering experiment. It selects the pinned
Turnip driver's SYSMEM mode; upstream favors this mode for DXVK, but forced SYS
can also worsen FPS/heat. The opaque Android bitmap change is present in both
arms, preserving RGB precision. No game-quality or runtime upgrade is involved.

1. With the client stopped, keep **Use Adreno GPU rendering** enabled. Press
   **Restore baseline settings**, then enable only **Reduce GPU frame copies
   (experiment)** and the diagnostic HUD. Confirm render 30/queue 1/display 30
   and **Selected experiments: Reduce GPU frame copies**. Leave A740, binning,
   alternate CPU instructions, early display requests and direct GPU rendering off.
2. Keep FSR off because of the earlier black lines. Use the same 1280×720 station,
   character, camera/windows, other game settings and Thor fan/power mode. Start
   server → **SERVER READY** → Start EVE client → Open client display. Check
   fullscreen, text/geometry and controls.
3. Warm three minutes, then observe two minutes, keeping equal static-camera and
   movement intervals in both runs. Record HUD FPS range, stutter/input delay and
   starting/ending SoC temperature. Export while running as **0.1.17-linear**,
   reopen the display and confirm the same client/server session remains usable.
   Quit EVE normally; leave the server running.
4. Cool to a similar starting temperature. With the client stopped, enable
   **Use direct GPU rendering (experiment)** as well. Confirm the summary has
   only **Reduce GPU frame copies, Direct GPU rendering**. Repeat the same five-minute
   run and live export as **0.1.17-linear-sysmem**. Check ships, transparency,
   effects, station geometry, text, controls and export/reopen continuity.
5. If SYS qualification fails, export immediately and report the stage. If FPS,
   heat or visual behavior worsens, turn off only direct GPU rendering after
   stopping. If it helps, repeat once after cooling with the caches warm before
   keeping it. Quit normally, then save and stop the server.

Return both labeled ZIPs, HUD FPS ranges, starting/ending temperatures, any
visible/input faults and export continuity. Display updates are not engine FPS;
thermal driver labels and unavailable fields retain their actual meanings.
Do not repeat the old cap/binning/FEX/A740 matrix. The helpers qualify compatibility,
not physical SYS selection or stable 30 FPS. Abrupt Android memory kills remain
possible without callbacks; the existing corroborated-pressure guard is unchanged.

Earlier instructions remain below as historical evidence.

## Completed 0.1.16 baseline/linear test

Install **EVE-Android-Launcher-0.1.16.apk** over the existing app with client and
server stopped. Preserve app data, client import, runtime, prefix, shader caches,
account, world and controller mappings. No import, validation or probe is needed.
The preview signing identity remains the same.

The October 8 exports both retained linear presentation. The apparent crash was
our pressure guard requesting an orderly stop after a trim callback despite 4.66 GiB
available and lowMemory=false. This update requires corroborating pressure,
provides an explicit baseline reset and makes active experiments visible. It adds
bounded read-only frequency/thermal observations where Android allows access.
There is no new rendering experiment or game-quality change in this pass.

1. With the client stopped, keep **Use Adreno GPU rendering** enabled and press
   **Restore baseline settings**. Enable the diagnostic HUD. Confirm the visible
   summary says **Baseline caps** with render 30/queue 1/display 30 and
   **Selected experiments: none**. This button clears all experiments in one step;
   selecting a profile alone changes caps and keeps previously selected experiments.
2. Keep FSR off because of the earlier black lines, and retain the same station,
   1280×720 output, other game settings, camera/windows and Thor fan/power mode.
   Start server → **SERVER READY** → Start EVE client → Open client display.
   Enter the existing character's station and check fullscreen/controls.
3. Warm up three minutes, then observe two. Record warm HUD FPS range, stutter and
   starting/ending GPU/SoC temperature. Observe static camera and movement
   separately. While EVE is still running, export support as **0.1.16-baseline**.
   Return from the file picker and reopen the display: EVE should remain in the
   same session when memory is sufficient. Confirm controls and the server remain
   working. Report any stop message and export again before restarting if it stops.
4. Quit EVE normally and let the device cool to a similar starting temperature.
   Press **Restore baseline settings** again, then enable only
   **Reduce GPU frame copies (experiment)**. Confirm that is the only experiment
   in the summary. Repeat the same warm-up/observation and live export as
   **0.1.16-linear**, then reopen the display to check export continuity.
5. Quit normally; confirm the client reports stopped and the server remains ready.
   Save and stop the server afterward. If linear qualification fails, performance
   is worse, or geometry/controls glitch, export and turn that experiment off.

Return both labeled ZIPs, FPS ranges, approximate temperatures, visible faults
and whether exporting preserved each running session. Do not repeat the old
render-cap/binning/FEX/A740 matrix. Linear compatibility passed the previous
physical helper gates, but sustained FPS/heat benefit is still unproven.

The pressure stop remains best effort when fresh Android MemoryInfo corroborates
low memory. Abrupt Android kills can lack callbacks. Frequency fields retain their
kernel meanings; CPU scaling frequencies may be requested states, not measured
clocks. Thermal sensors keep their driver labels; unreadable sensors remain
unavailable. Battery temperature is separate from the user's SoC reading.
DXVK GPU% and delivered RFB updates do not measure physical GPU load or engine FPS.

Earlier tests remain below as historical evidence.

## Completed 0.1.14 station comparison

The two logged runs ended cleanly, and the later warmed A740 repeat had similar
performance: typically 26 FPS, ranging 22–30, with reported device temperatures
61–63°C initially and 66–70°C warm. That repeat supplied no additional logs.
The driver change has no demonstrated station-performance benefit; the original
driver remains preferred. The sequence below records the completed test.

## 0.1.14 test sequence

Install **EVE-Android-Launcher-0.1.14.apk** in place with client and server
stopped. Preserve app data, the imported client, installed runtime, prefix,
shader caches, local account and saved character. No reimport, revalidation or
Wine/FEX probe is needed. The preview signing identity remains unchanged.

1. Keep **Use Adreno GPU rendering** enabled. Select **Baseline · 30 FPS
   target**, enable the diagnostic HUD, and turn every experiment off,
   including binning, alternate CPU instructions and early display requests.
   Keep the same 1280×720 scene, camera, graphics settings and Thor fan/power mode.
2. Start server → SERVER READY → Start EVE client → Open client display.
   Enter the existing character's station. Check fullscreen and controls, then
   warm up for three minutes and observe another two. Record the HUD FPS range,
   stutter, visible faults and device temperature. Export **0.1.14-baseline**
   while running, then quit EVE normally. A code-0 quit should report stopped,
   and the server should stay running.
3. Allow the device to return to a similar starting temperature. With the client
   stopped, enable only **Use A740 driver experiment** and repeat the same
   five-minute station run. Export **0.1.14-a740** while running. The first
   experiment run uses its own shader cache, so initial warm-up may be slower.
   If it improves warm FPS without faults, repeat once with that cache warmed.
4. Check station geometry, ships, text and effects for distorted shapes or
   flickering. If they appear, stop the client and switch the experiment off.
   If driver qualification fails, export immediately and report the stage;
   switching it off restores the existing driver. Save/stop the server afterward.

Return the labeled ZIPs, warm HUD FPS ranges, approximate starting/ending
temperatures and how each run ended. Do not repeat the earlier four-option
matrix. Display update counts are not engine FPS. The A740 option changes one
upstream primitive-processing register value; it is an experiment until this
physical rendering test passes. It is off by default and refuses other GPUs.
After a fault-free comparison, if the HUD holds at 30 FPS, optionally try
**Render cap only · 60 FPS** with A740 enabled to check 30+ FPS. Keep the other
experiments off and export **0.1.14-a740-render60**. The display cap remains 30;
use the engine HUD for this measurement.

Android critical running-memory callbacks now request an orderly client stop
while leaving the server running. Ordinary background/navigation callbacks do
not stop it. An abrupt Android low-memory kill can occur without a callback;
this is best-effort protection, not a guarantee. After any unexpected closure,
reopen the launcher and export before restarting the client. Logs retain bounded
memory/thermal samples and critical-pressure events. Battery temperature is
labeled separately from the Thor's GPU/SoC temperature.

Earlier tests remain below as historical evidence.

## Current 0.1.13 performance recovery test

Install **EVE-Android-Launcher-0.1.13.apk** over the existing app with the
client and server stopped. Keep app data, imported client, runtime, prefix,
shader caches, current local account and saved character. No import, validation
or runtime probe is needed. This APK uses the same preview signing identity with
Android debugging disabled and shell profiling enabled; physical Android PRoot
startup must still be checked.

1. In Client, leave **Use Adreno GPU rendering** enabled and select
   **Baseline · 30 FPS target**. Leave all three experiment checkboxes off.
   Enable **Show frame-time and GPU diagnostics** and keep it enabled for all
   comparisons. This update initially selects the accepted 0.1.11 caps and
   after-complete display requests, including when upgrading from 0.1.12.
2. Start server → **SERVER READY** → Start EVE client → Open client display.
   Log in with the existing local account and enter the same station/character.
   Confirm fullscreen, LT layer switching, both sticks and gear actions work.
   If startup fails, export immediately and report the exact stage; preserve data.
3. Keep the same camera, windows, graphics settings and Thor fan/performance mode.
   Allow at least three minutes in station for loading/shaders to settle, then
   observe another two minutes. Record HUD FPS range, frame-time spikes, GPU load,
   stutter/input delay, visible faults and device temperature if available.
   Export support while running, then stop the client cleanly. Label this ZIP
   **baseline**. Delivery counters are not EVE engine FPS.
4. Repeat that scene with only **Disable concurrent binning (Adreno experiment)**
   enabled. Export **nocb**. Stop the client, turn it off, then repeat with only
   **Use alternate CPU load instructions (FEX experiment)** enabled and export
   **FEX**. Each experiment starts a new client process; the server may remain on.
   Keep a change only if repeated warm runs improve without visual/input faults.
5. Return both checkboxes off. Compare **Render cap only · 60 FPS** using the same
   scene and timing. This tests whether raising the render limit helps without
   also raising the display cap or queue. Export **render60**. If an experiment
   helped, repeat render60 with only that experiment and label the combination.
6. Re-run Baseline after the trials to detect device warming/scene drift. Save and
   stop server. Return the labeled ZIPs, FPS ranges and which setting felt best.

The extra **Frame queue only · 2 frames**, **Display cap only · 60 FPS** and
**Request next display frame early** options are available for later isolation.
**0.1.12 combined · 60 FPS / 2 frames** recreates its caps; also enable early
requests to reproduce its delivery policy. Each control is locked while the
client is running or an operation is active. All options preserve the working
immediate-presentation workaround; profiles do not modify game preferences.
Baseline caps at 30 FPS. A 60 FPS cap allows higher engine FPS but cannot promise
30+ FPS or a matching visible display rate.

The support export records selected/effective caps, allowlisted driver/CPU
assignments, actual per-connection request policy, and bounded readable CPU
MIDR/topology. Assigned FEX/Turnip options are distinct from proof of native effect
or measured speed. Non-debuggable Android packaging is verified in CI, while
PRoot/TLS/server/controls compatibility still needs this Thor run.
Cached dynamic buffers are deferred until actual KGSL allocation flags and
CPU-write/GPU-read coherence are qualified. No cached-buffer switch is included.


The October 4 0.1.11 test accepts fullscreen/controls, saved-character reopen,
login and visible station entry on Thor. The screenshot shows 23.9 FPS. Keep
those accepted milestones; the active goal is smoother rendering at 30+ FPS.

1. Stop the client and save/stop the server. Install
   `EVE-Android-Launcher-0.1.12.apk` in place without clearing data.
2. Start the server. In Client, keep Adreno enabled and select
   **Performance · 60 FPS target**. Optionally enable
   **Show frame-time and GPU diagnostics** for this comparison.
3. Start the client and use the existing local account/character. Settle in the
   same station with the same camera and graphics settings for 30–60 seconds.
   Report the HUD FPS range and controller response; export support logs before
   stopping the client so each profile has its own evidence.
4. With the client stopped, select **Previous settings · 30 FPS target** and
   repeat the same warm scene. Export a second ZIP. The server can stay running
   between client runs; save/stop it after the comparison.
5. Confirm the home-screen app icon has the dark space backdrop. If the launcher
   retains its previous icon, refresh the home screen or restart the device;
   preserve app data.

60 is a cap, not a promised FPS. The two-frame latency setting is also a cap:
EVE's own latency/backbuffer limits may reduce it. Both profiles use the accepted
`dxgi.syncInterval=0` workaround and the same runtime, drivers, guest resolution
and graphics preferences. The display pipeline optimization applies to both.
Display-update counts and Android GPU timings are not EVE FPS/GPU measurements.

If FPS remains below 30 and the diagnostic HUD shows sustained high GPU load,
compare lower in-game shadows/ambient occlusion/anti-aliasing and DX11-compatible
FSR 1 Quality, one change at a time. These are manual EVE settings; the launcher
does not replace saved graphics preferences. Keep diagnostic screenshots and logs
so later work can distinguish rendering cost from delivery or CPU work.

## Earlier 0.1.11 fullscreen controller qualification

The October 4 0.1.9 test accepts Adreno rendering and usable input, with user-reported
teens/20s FPS. Preserve the renderer and current local account; do not repeat import,
runtime, TLS or the prior black-screen investigation. Controller layers/fullscreen
are the active milestone. Follow [the defaults and six-step controls test](CONTROLS.md).
Update with `EVE-Android-Launcher-0.1.11.apk`, with client/server stopped, without
uninstalling or clearing data. Further graphics optimization is deferred.

0.1.11 corrects the 0.1.10 crash before display connection on Android 13.
Both Start buttons are pinned above the tabs. Confirm the display opens, the
default layers show Main/Alt 1/Alt 2/Alt 3 and the app icon has its dark space
background; reopen the display once before continuing the controls test.

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

1. Install `EVE-Android-Launcher-0.1.11.apk`. Grant the notification permission when
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
