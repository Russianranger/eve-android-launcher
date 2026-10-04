# EVE Android Launcher 0.1.11 — display startup and launcher layout

Opening the 0.1.10 display on Android 13 could crash before the RFB connection.
The first fullscreen call requested the window's insets controller before its
decor existed. 0.1.11 creates the decor first; an Android 13 regression replay
reproduces the original null dereference with the actual APK resources.

The four default layer names are now Main, Alt 1, Alt 2 and Alt 3. Loading an
existing profile migrates matching old default names while preserving custom
names and all bindings. Both Start buttons sit above the tabs. The app icon has
a dark starfield background; the orbital gear retains its existing design.

Update in place with client/server stopped. Open and reopen the display, confirm
the four names and then continue the controller test. Runtime, renderer, cache
and world settings are retained.

# EVE Android Launcher 0.1.10 — fullscreen and layered controller controls

The user accepts 0.1.9 Adreno rendering and usable input, reporting teens/20s FPS.
This update keeps that renderer and moves the display toolbar into a top-right
orbital gear menu. The game fills the fullscreen display with aspect-fit scaling;
the menu overlays it without changing guest resolution or touch coordinates.

Controller input follows the TRASC launcher at commit
`b3bb19532eb53830af936d5e4ce95e848a46bce4`: four default named layers, LT cycling,
left-stick WASD/right-stick cursor, keyboard/chord/mouse/wheel bindings and a
saved editor for one to six layers. Save applies validated settings; Cancel leaves
the saved profile intact. Layer changes show a brief banner. Menu, text/editor,
focus loss, app pause and controller disconnect release held inputs. The display
connection independently releases all wire-held keys/buttons before bounded close.

Update in place. Test the gear, LT layers, clicks and a saved custom binding;
then switch apps and reopen the display to check for stuck keys or mouse buttons.
These controls send the same default keys as TRASC; their in-game effect follows
EVE's configured shortcuts. Rendering optimization and gameplay/audio remain later
work. No runtime reinstall, client import or graphics reconfiguration is needed.

# EVE Android Launcher 0.1.9 — Xvnc presentation-wait compatibility

The 0.1.8 device test confirms EVE owns foreground/focus, yet its main thread
stops progressing and its window does not answer responsiveness probes. Focus
correction did not resolve the black screen; memory and display work remain low.

This candidate adds only `dxgi.syncInterval = 0` to the private DXVK configuration.
DXVK 2.4.1 waits indefinitely for FIFO presentation completion before releasing
its frame-latency signal. Mesa 26's X11 pixel-copy path can return the image without
advancing the present ID that wait needs. EVE switches to FIFO, while the old probe
used Present(0). The override bypasses that wait, with GPU rendering, 30 FPS cap,
one-frame queue, driver/compiler versions, cache and saved EVE preferences retained.
The wait mechanism is source-backed; the actual EVE fix still needs Thor confirmation.

The original shader/display probe now requests Present(1) for all three changing
frames. Qualification requires the fixed override, actual IMMEDIATE presentation
mode, exact native DLL identities and observed display pixels. Diagnostics retain
the exact frame-thread class and fixed session configuration in support exports.

Update in place with client/server stopped. Keep Adreno checked; use a fresh
account if login appears. If still black after three minutes, export while running,
then stop. Do not reset the imported client, prefix, shader cache or world.

# EVE Android Launcher 0.1.8 — owned window startup

The 0.1.7 Thor test still remains black. Live diagnostics show native graphics
setup, stable memory and idle background shader/submission/completion workers.
Those samples do not exclude synchronous compilation or another EVE wait.

This candidate adds an original x64 fixed-target launcher that holds EVE's child
process handle, activates only that child's visible main window once, and records
bounded numeric visibility, minimization, focus and message-pump evidence. DXVK
can treat a fullscreen window without foreground ownership as occluded, unlike
the previous WineD3D path. Focus is a compatibility hypothesis, not a confirmed
cause. No saved EVE settings or renderer/compiler tuning changes are included.

Startup now requires a fresh session-matched child-created receipt before it
reports process startup. The helper forwards EVE's exit; native CI verifies the
child keeps the launcher's Linux process group/session and clean ownership.
Diagnostics reserve client main-thread rows and exports keep the window receipt.

Update in place and retry with Adreno rendering checked. Use a fresh account.
If still black after three minutes, export while running, then stop the client
and save/stop the server. Preserve the imported client, prefix and world.

# EVE Android Launcher 0.1.7 — Adreno synchronization compatibility

0.1.6 launches EVE on native DXVK/Adreno 740, but the device test remains black
with pending shader compilation. Android decoding and drawing consume little
time, and there is no recorded crash or memory failure.

This preview builds unmodified DXVK 2.4.1 as native ARM64EC D3D11/DXGI. It avoids
the submission-completion timeline path introduced in DXVK 2.5, which upstream
reports identify as a performance regression with Turnip's emulated KGSL
timelines. Turnip 26 and the accepted Wine/FEX runtime remain in place. This is
a targeted compatibility candidate; the device test must confirm whether it
resolves EVE's stall. No shader-worker, API, network-policy or presentation
settings are changed. The prior 2.5.3 shader cache is retained separately.

Bounded client CPU/RSS, compiler-thread state/CPU/wait-channel and cache metadata
samples now survive Stop, including one prior session. Support exports include
them without credentials, stack dumps, command lines or screenshots. Real socket
tests confirm input can be sent while the display reader waits for pixels.

Update in place. Keep Adreno rendering checked and use a fresh local account.
If the black screen persists for three minutes, export support logs, then stop
the client and server. There is no need to wait ten minutes or reset saved data.
See [testing instructions](TESTING.md) and [evidence](CLIENT-PERFORMANCE.md).

# EVE Android Launcher 0.1.6 — graphics report reader

The 0.1.5 Thor test passed Turnip/Adreno 740 Vulkan presentation, native ARM64EC
D3D11 shader rendering and all three visible display frames. EVE then stopped
before launch because the reader expected compact JSON lines while the saved
display receipt was formatted JSON. 0.1.6 reads the complete receipt and keeps
the existing hardware, native DLL identity, pixel and process checks.

Regression coverage uses the observed display receipt, the actual atomic JSON
writer and formatted reports in supervisor startup/failure tests. Native CI also
runs the production reader on its actual display receipt before packaging.

Update in place and retry with Adreno rendering checked. Preserve the prepared
runtime, client cache, prefix and world. Use a fresh local account; ThorTest stays
retired. Actual GPU EVE performance and input responsiveness still need the next
device test. See [testing instructions](TESTING.md).

# EVE Android Launcher 0.1.5 — client performance

0.1.4 passed private Wine TLS, startup, local login and character selection on
Thor, but CPU rendering made the display and text entry nearly unusable.

This update adds native ARM64EC DXVK 2.5.3 with pinned Turnip 26.0.0 for Adreno,
using the existing Wine/FEX installation. Hardware-only checks verify the native
DLLs, shader pixels and three visible display frames before EVE runs. The initial
30 FPS cap and one-frame queue favor responsiveness. Versioned shader caches
persist; software rendering remains an explicit recovery option.

Text and key taps are sent in batches; pointer motion is coalesced without
losing button releases. Text defaults to replacing the selected field. Supervisor
status uses one process snapshot, and reserve checks read only available memory.
Four socket filters avoid unnecessary exit tracing while retaining the native
loopback/localhost:443 policy, immutable destination copies and sendmmsg copyback.
Support logs add separate CPU, receive/decode, Android presentation and input
latency counters without credentials or screenshots.

Update in place. Preserve runtimes, client cache, prefix and world; no reimport,
revalidation or repeated Wine/FEX probe is needed. Use a fresh local test account
such as EvePerf1; ThorTest is retired. Start server → GPU client → login/character
selection → clean stop → warm-cache repeat → save/stop server → export support ZIP.
See [testing instructions](TESTING.md) and [implementation evidence](CLIENT-PERFORMANCE.md).

Native ARM CI checks graphics interoperability, visible synthetic frames, CPU
rejection, exact assets and real PRoot network syscalls. Actual Thor EVE performance
still requires the next device test; CI results do not establish handheld FPS.
