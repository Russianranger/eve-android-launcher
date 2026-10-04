# Client optimization evidence and qualification

The requested 60-minute investigation ran 2026-10-03 20:42:57–21:42:57 UTC.
Production changes began afterward. The accepted evidence is
`eve-support-20261003-154109.zip` (SHA-256
`2af4d0dfa4b280d0a8aaa5fde7f630ff00186791f5d8264f120ecfb4047be3fc`)
and the user's successful login/character-selection report.

## Findings and changes

| Finding | Change | Verification and limit |
|---|---|---|
| Launch explicitly forced WineD3D/llvmpipe CPU rendering | Native ARM64EC DXVK 2.4.1 → existing Wine Vulkan → glibc Turnip 26/KGSL | Real native/D3D/display helper gates; actual EVE FPS still needs Thor |
| First display session forwarded 39.1 MiB over 784 seconds; comparison discarded most unchanged pixels | Keep existing Raw RFB and comparison behavior; raise GPU display cap from 15 to 30 | Host decoder/loopback tests have 30 Hz capacity; this is not device FPS |
| Twenty characters previously used 160 underlying writes and 40 flushes | Compound text/tap/chord output buffered under one lock | The same 320 bytes now require one underlying write/flush; duplex protocol fixture |
| Text always appended and touch movement could fill input queue | Replace selected field by default; coalesce movement while preserving button edges | Unicode/chord/press-release/cancel and lifecycle tests |
| Status scanned `/proc` once per role; 4 Hz reserve check read unused process status | One fresh grouped snapshot per status; dedicated MemAvailable reader | CPU/RSS/identity-reuse tests; unchanged reserve and cleanup requirements |
| Network extension requested exit stops for four entry-only socket checks | Keep entry checks/copies; remove only bind/connect/sendto/sendmsg exit flags | Actual native ARM syscall/IPC fixture is a required CI gate; sendmmsg exit copyback remains |
| Slow startup could involve shader warmup and display presentation | Persistent versioned caches and separate aggregate metrics | Mesa 512 MiB cache cap; DXVK pruning to 256 MiB and 16 owned files between sessions |

The GPU mode uses `dxgi.maxFrameRate=30` and `dxgi.maxFrameLatency=1` as an initial
responsiveness tradeoff. Default compiler concurrency remains unchanged. No
unsupported async shader option, TSO change, guessed EVE API flag, broad Wine/FEX
upgrade, resolution reduction or native display transport replacement is included.
The previous software mode remains explicit recovery.

## Native graphics proof

Five APK assets are selected: Turnip 26, the native Vulkan helper, native ARM64EC
D3D11/DXGI DLLs and an original x64 D3D11 helper. Exact runtime/compiler/source
pins and every asset's SHA-256/size/architecture are recorded in
`client-graphics-bundle.json`. ARM64EC final PE images use AMD64 Machine; bounded
CHPE metadata and executable native code ranges establish EC identity.
The pinned linker can coalesce ranges across executable sections and their PE
alignment padding. Validators check each segment and executable endpoints rather
than requiring the whole range to fit one raw section. A small original DLL
built by the exact compiler reproduces that layout for regression checks.

The initialized accepted prefix is required. Read-only private native DLLs bind
to system32 for this session without following old builtin symlinks. Source and
mapped hashes are checked after TLS, after rendering qualification and immediately
before EVE. Asset refresh stages a new inode and atomically replaces the old path.
Imported DLL shadows are rejected; accepted runtime/client/prefix/world data are
preserved. Graphics helper groups participate in cancellation, journaling,
shutdown and supervisor recovery with PID/start-time identity safeguards.

Device gates require Qualcomm/Turnip, Vulkan 1.3+, exact driver 26 and a nonsoftware
adapter. The x64 helper loads the exact native EC DLLs, creates a hardware D3D11
FL 11+ device, compiles original shaders and verifies staging pixels. A separate
Raw RFB observer checks the shader center and all three changing window colors.
It retains only counts/booleans, never framebuffer images.

The native ARM CI runs the same pinned Wine/FEX and newly built DLLs with Lavapipe
in an explicitly labeled software fixture. This proves cross-architecture
interop/shader/presentation behavior; it does not qualify Thor. The same CPU
adapter must fail hardware mode. Forced Turnip-only ICD loading must fail on CI
without KGSL even with the test-only software acceptance flag. That flag is absent
from the retail graphics CLI and backend parser.

## Measurements and next device gate

`graphics-preflight.json` proves helper capability, separately from actual EVE
rendering and login. Fresh EVE DXVK logs/HUD establish the game's chosen path;
device-creation log lines alone do not prove visible game frames. Current receipts
keep game graphics/login qualification separate from helper results.

`display-performance.json` separates socket read/wait, conversion, bitmap
publication, view draw, Android FrameMetrics and input queue/send timing. The
socket counter includes blocked receive time. Framebuffer updates are delivery
updates, not game FPS; Android GPU duration is bitmap presentation, not EVE GPU
render time. Counters contain no text, key symbols, pointer coordinates or images.
Process CPU percentages use 100% per logical core and can exceed 100%. New/recycled
PIDs and negative counters are excluded from deltas. Export metadata includes
thermal/power-save state at export; those are observations, not automatic causes.

Compare first/cached startup, settled HUD FPS, field selection/text replacement,
character selection, display reopen and clean shutdown. Use a fresh disposable
local identity such as EvePerf1. ThorTest is retired; existing account/world data
are retained. See [the test sequence](TESTING.md).

## Reproducibility

The build pins DXVK source `0cf05780abd7250c2cd713b7749cf32180157cf5`, its Vulkan,
SPIR-V and libdisplay-info gitlinks, and the same LLVM-mingw 20250920 used by the
accepted Wine runtime. Only two ELF files are reused from UO v0.2.17; unrelated
TRASC/Wine/D3D9/game patches are excluded. Exact Mesa/glslang/probe source and the
original recipes accompany the source archive. Build scripts and qualification
reports are retained by Actions; release packaging includes corresponding source.

## 0.1.6 physical stall and 0.1.7 compatibility candidate

`eve-support-20261003-194841.zip` (SHA-256
`4a61fb9e589c78d0297f61562848f2605a28041bbdb08cda02d2cb857be5e765`)
passes the native hardware preflight and launches EVE through DXVK 2.5.3. The
game creates a 1280x720 swapchain on Adreno 740. The user's screenshot shows a
black screen, 2.5 HUD FPS and pending shader compilation after a prolonged wait.
The display connection records 94 updates over 388.8 seconds, but decoding takes
only 73.5 ms total, bitmap publication 19.4 ms and view drawing 10.1 ms. No GPU
reset, compiler exception or OOM is recorded. Stop replaces live status CPU/RSS,
so this evidence cannot distinguish busy compilation from blocked work.

[DXVK issue 4484](https://github.com/doitsujin/dxvk/issues/4484) identifies an
Adreno/KGSL performance regression introduced by the DXVK 2.5 submission timeline
change. The exact shipped Mesa 26.0.0 source still uses the common software
timeline wrapper in `tu_knl_kgsl.cc`; its underlying KGSL synchronization type is
binary. This supports a targeted test of the prior synchronization path, without
proving that it caused this particular EVE stall. DXVK 2.4.1 uses fences for
submission completion; it still uses timeline semaphores where D3D11 fence APIs
require them. Reversing the newer queue code in 2.5.3 would also affect later
transfer/resource-relocation changes, so the build selects unmodified 2.4.1.

0.1.7 keeps the same Wine/FEX, Turnip, toolchain, dependency commits, display and
30 FPS/one-frame settings. Bundle `eve-turnip-dxvk-2` must pass all original native
EC/hash/pixel/display/CPU-rejection gates. Its 2.4.1 cache is separate; 2.5.3 state
is preserved. Default compiler concurrency and pipeline-library settings remain.

`client-performance.json` and one prior session retain bounded aggregate CPU/RSS,
compiler-thread CPU/state/wait-channel and metadata-only cache counts/bytes after
Stop. They contain no command lines, stacks, credentials or frame images. Real
loopback tests send keys, Unicode replacement text and pointer edges while the
reader blocks on either a header or partial pixels; no transport lock defect was
found. Device startup, login and usable input must now be retested.

## 0.1.7 live stall and 0.1.8 owned-window candidate

`eve-support-20261003-203244.zip` (SHA-256
`0b54714dfd01b47325e2662a16e03bd7b53d6b64c8e64cc30c7ec31f608799a3`)
confirms DXVK 2.4.1, passing physical Adreno/TLS preflight and another EVE black
screen, now without a visible HUD. The combined log still reaches a 1280x720
swapchain and eight compiler threads; the truncated standalone D3D log must not
be mistaken for an earlier failure. Thirty-six live samples span 181 seconds.
Once initialized, the named shader/submission/completion workers have zero CPU
deltas and sleep in futex waits. Client CPU remains about half of one logical
core, largely in other select/pipe workers; RSS stabilizes around 1.30 GiB with
7.5 GiB available. Mesa cache grows once by 3.4 KiB and then remains static.
Android decode/publication/draw totals about 115 ms over 141 seconds.

This does not demonstrate an active background shader backlog. It also cannot
exclude synchronous shader/library compilation or a fence wait on another thread.
The precise wait owner is still unproven. Default compiler, feature-level, queue,
driver, display and cache settings therefore remain unchanged in 0.1.8.

Exact [DXVK 2.4.1 Win32 WSI](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/wsi/win32/wsi_window_win32.cpp)
treats a window outside the foreground as occluded. The fullscreen presenter can
exit fullscreen and report `DXGI_STATUS_OCCLUDED`, whereas the pinned WineD3D
path's occlusion check uses minimization. A separate
[EVE focus report](https://github.com/pop-os/cosmic-epoch/issues/3328) describes a
black game window until focus, on different hardware/client/compositor; it is
supporting context, not confirmation for Thor. This motivates one controlled
owned-window activation and direct focus evidence rather than a graphics upgrade.

The fixed-target launcher holds the exact EVE child handle, verifies its window
PID before each asynchronous restore/foreground/raise, and makes one startup
activation attempt. Numeric metadata and a 50 ms WM_NULL probe are sampled for
at most three minutes and published every five seconds; no titles, pixels, input
or stack dumps are retained. The helper forwards child exit and must pass native
Wine/FEX proof of foreground restoration, bounded behavior with a hung message
pump, exit propagation and inherited Linux
process-group/session ownership. The supervisor requires a fresh nonce-matched
child-created receipt before observing startup. Rendering/login remain separate
device gates. CPU diagnostics also reserve bounded process-main-thread rows.
