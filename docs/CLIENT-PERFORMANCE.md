# Client optimization evidence and qualification

## October 5: warmed driver result and remaining candidates

The 0.1.14 A740 repeat produced no user-observed improvement: typically 26 FPS,
range 22–30, device temperature 61–63°C initially and 66–70°C warm. No new logs
were supplied. See [DEVICE-20261005.md](DEVICE-20261005.md) for the earlier logged
comparison and qualification boundaries. The original driver remains preferred;
the Adreno 740 station comparison is complete. Snapdragon 8 Elite videos with
other system drivers do not establish a useful recipe for this exact runtime.

The next small comparison is in-game **FSR 1**, retaining the 1280×720 output,
baseline profile and original driver. CCP's [upscaling compatibility notes](https://www.eveonline.com/news/view/patch-notes-version-23-01)
confirm FSR 1 works with DX11, whereas the newer Windows upscalers need DX12.
Upscaling reduces scene rendering work and helps FPS only when GPU rendering
is limiting. Compare Ultra Quality and then Quality, if offered, with all
other game/launcher settings held constant. Record warm HUD FPS and device
temperature; observe camera movement separately. This is an available game
setting, not a runtime upgrade or automatic rewrite of player preferences.
No prior completed FSR comparison or confirmed minimum graphics settings is
recorded. A positive result would support scene-GPU load reduction; unchanged
results would not alone identify a CPU or display bottleneck.

Read-only code review of the remaining engineering candidates found:

- Production sets `MESA_VK_WSI_DEBUG=sw` with the pinned glibc X11 driver. Exact
  [Mesa 26 X11 WSI](https://github.com/chaotic-cx/mesa-mirror/blob/mesa-26.0.0/src/vulkan/wsi/wsi_common_x11.c)
  selects CPU images and copies their pixels using `xcb_put_image`, before
  Xvnc/Raw RFB/Android bitmap presentation. Scene rendering is still on Adreno.
  Native Android presentation would need a new X-server/WSI/buffer/fence bridge,
  then exact Vulkan/EC shader/pixel/IMMEDIATE/input/reopen/shutdown qualification.
  Android decode/bitmap work around 3 ms/update and Xvnc around 30% of one core
  do not prove this whole path is the dominant bottleneck. Obtain producer and
  presentation timing plus actual clocks before choosing the larger replacement.
- Disabling TigerVNC framebuffer comparison is a small optional experiment, but
  can increase Raw transfer to a full-frame ceiling of 110.6 MB/s at 720p/30,
  versus roughly 44 MB/s observed. It is not selected as the next performance
  change because more unchanged-pixel traffic can add work and heat.
- Pinned [DXVK cached-resource documentation](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/dxvk.conf)
  describes `d3d11.cachedDynamicResources=c` as a workaround for CPU reads from
  mapped buffers and warns of lower GPU-bound performance. There is no evidence
  that EVE's mapped constant-buffer reads are limiting this run. The option
  affects eligible DEFAULT and DYNAMIC constant buffers and may fall back to
  uncached allocations. It remains deferred, not a promised 30-FPS fix.
  Qualification must inspect actual selected-driver Vulkan allocation flags
  through KGSL memory-info queries, require WRITEBACK/IOCOHERENT, exercise repeated
  CPU-write/GPU-uniform-read coherence, and add translated D3D WRITE_DISCARD plus
  DEFAULT UpdateSubresource coverage. Existing immutable-vertex/fixed-shader
  fixtures do not establish this behavior. CI software fixtures cannot substitute
  for Thor hardware allocation/coherence proof.

No renderer/runtime version, player data, resolution or application code changes
accompany this review. Current APK remains 0.1.14.

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

The initial GPU mode used `dxgi.maxFrameRate=30` and `dxgi.maxFrameLatency=1` as a
responsiveness tradeoff; 0.1.12 adds the profiles described below. Default compiler concurrency remains unchanged. No
unsupported async shader option, TSO change, guessed EVE API flag, broad Wine/FEX
upgrade, resolution reduction or native display transport replacement is included.
The previous software mode remains explicit recovery.

## October 4: 0.1.11 accepted session and 0.1.12 optimization

`eve-support-20261004-114813.zip` (343,025 bytes; SHA-256
`3fbeeb66d3385ffb090ba381495f3fd69d78f870f79f6a6fa4308011b3003520`)
and the user's screenshot/report accept fullscreen, controls, saved-character
reopen, login and visible station entry. The station screenshot displays 23.9 FPS.
The current Android exit records predate this session. Explicit server save/stop
completes cleanly; existing unexpected-client-exit semantics remain unchanged.

The display receives 13,286 updates over 785.367 seconds: 16.92 updates/s, not
EVE FPS. Decode averages 2.64 ms/update and bitmap publication 1.19 ms/update.
Raw loopback traffic averages 49.63 MB/s, with roughly 323 rectangles/update and
79.5% of frame pixels changing. Socket read time includes blocked waits. Android
GPU timing measures bitmap presentation rather than EVE rendering. All 1,765
input operations complete with no rejections and at most 3.65 ms queue delay.

The retained 53 live process samples cover approximately 270 seconds. Mean
EVE/Wine client-group CPU is 200.30% of one core, with Xvnc separately at 29.32%
and WineServer at 14.35%. The EVE main thread averages 44.13%; most remaining
client work is outside named graphics roles. PRoot tracer/backend supervisor CPU
is not exported. The completion worker waits in `adreno_drawctxt_wait` in 38/53
samples, a frequent GPU-fence-wait hint without duration/utilization proof.
Shader workers are effectively idle. These observations do not establish one
dominant bottleneck, but both existing 30 FPS caps categorically prevent 30+.

| Profile | DXVK FPS cap | DXVK latency cap | Xvnc FPS cap |
|---|---:|---:|---:|
| Performance (`throughput`, default) | 60 | 2 | 60 |
| Previous settings (`responsive`) | 30 | 1 | 30 |
| Software recovery | — | — | 15 |

Both GPU profiles retain `dxgi.syncInterval=0`. The exact
[DXVK 2.4.1 swapchain](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/dxgi/dxgi_swapchain.cpp)
caps actual latency using application/backbuffer limits, so configured latency 2
does not prove an actual two-frame EVE queue. Native qualification checks each
profile's actual logged caps, original Present(1), effective interval 0, IMMEDIATE
presentation, exact DLL identities and all three independently observed frames.

The display sends one next incremental request at the framebuffer-update header,
before decoding. This follows the pinned
[TigerVNC 1.14.1 viewer](https://github.com/TigerVNC/tigervnc/blob/v1.14.1/common/rfb/CConnection.cxx#L500-L510).
After a valid batch that changes desktop size, one full refresh uses the final
dimensions so newly exposed pixels cannot stall. Bell/clipboard messages send
no requests; an empty framebuffer update sends one. Real socket fixtures withhold
pixels until the next request, test blocked-read input, resize damage and bounded
request counts. Counters record the request policy without retaining pixels/input.

The optional fixed HUD adds frame times, GPU load and command-stream statistics.
Support status records selected/effective profiles. No driver/runtime upgrade,
compiler concurrency, TSO, synchronization patches, guessed EVE flags, guest
preferences, resolution or cache deletion is included. Actual FPS gain needs the
[same-scene warm comparison](TESTING.md). If GPU load remains high, manual EVE
graphics reduction and FSR 1 are supported DX11 options; see
[CCP's FSR compatibility notes](https://www.eveonline.com/news/view/patch-notes-version-23-01).

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

## 0.1.8 focused stall and 0.1.9 presentation candidate

`eve-support-20261003-221113.zip` (SHA-256
`5e758cce24118c65da2e9da58b4fd10092508f47ebc742d7a4a9eb9c81b5895f`)
confirms that the activation attempt succeeded: the live owned 1280x720 EVE
window has foreground/focus, but all 27 bounded WM_NULL probes time out through
180 seconds. Fifty live samples span 255 seconds. The child main thread stops
accumulating CPU ticks after 56.9 seconds and remains in a futex wait, as do the
named graphics workers. About 7.5 GiB remains available; no crash, device loss or
OOM is recorded. The Android bridge decodes 94 updates in 87.6 ms total, with
20.3 ms publication and 11.4 ms drawing. Focus did not resolve the upstream stall.

EVE's actual swapchain switches from IMMEDIATE to FIFO; present-wait/present-ID
extensions are enabled. Exact
[DXVK PresentBase](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/dxgi/dxgi_swapchain.cpp)
applies the supported `dxgi.syncInterval` override before D3D11 sees the request.
Its [presenter](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/dxvk/dxvk_presenter.cpp)
waits indefinitely for FIFO presentation completion before signaling the callback
fence used by the one-frame latency wait. IMMEDIATE bypasses this completion wait.

The shipped Mesa 26 source archive (SHA-256
`2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72`)
shows `wsi_common_x11.c`'s software/no-MIT-SHM image-copy path returns images
without advancing the completed present ID. Production uses `MESA_VK_WSI_DEBUG=sw`
for hardware Turnip rendering into Xvnc's pixel-copy display. That describes WSI,
not CPU rendering. The exact physical wait owner and DRI3 capabilities are not
recorded, so the EVE cause remains a source-backed hypothesis.

0.1.9 changes only the private presentation setting to `dxgi.syncInterval = 0`.
The 30 FPS cap, one-frame queue, native GPU path, versions, compiler/pipeline
settings, caches and saved game preferences remain. The earlier synthetic probe
requested Present(0) and bypassed EVE's request. Its three changing frames now
request Present(1); native CI and the physical supervisor require integer request
1, effective override 0, actual IMMEDIATE mode and independent visible pixels.
The fixed configuration and exact `dxvk-frame` presentation-thread class join
bounded support evidence. A CPU fixture without present-wait support cannot
reproduce the physical wait; passing CI therefore does not accept EVE performance.

## October 4: 0.1.9 physical rendering accepted

`eve-support-20261004-031450.zip` (264,829 bytes; SHA-256
`85d01efb17375992caca7f3d24dba7bb12020046cdefdf7cb4636b03993050dd`)
records 0.1.9 on AYN Thor API33. The user reports successful login and substantially
improved graphics in the teens and 20s FPS, acceptable for the current milestone.
Preserve this accepted result; further graphics optimization is deferred at the
user's request while controller support and the fullscreen display are added.

Native Adreno 740/DXVK 2.4.1 preflight passes the revised Present(1) test, effective
override 0, two actual IMMEDIATE modes and all three independently observed
frames. EVE's own combined log also records `dxgi.syncInterval = 0`, the existing
30 FPS/one-frame settings, and IMMEDIATE mode. Its owned 1280x720 window is now
focused and responsive through the three-minute observation, unlike 0.1.8.
The source-backed presentation workaround is therefore physically effective for
this tested session; the precise original wait owner remains an inference.

The connected display receives 7,876 updates over 458.264 seconds, averaging
17.19 updates per second. That is a transport update rate, not an independently
measured EVE FPS value. All 275 input operations complete, with zero rejections,
at most one queued operation and a maximum queue delay of 6.25 ms. Decode totals
13.410 seconds, bitmap publication 6.041 seconds and view drawing 0.552 seconds.
The retained 53 live performance samples span 269.8 seconds after older rows are
dropped for the existing byte bound. The EVE main thread progresses from 9,113
to 22,427 CPU ticks; graphics presentation/submission/completion workers also
progress. Client-group RSS ranges from 2.61 to 3.21 GiB. These observations
support a running renderer and usable transport rather than the earlier stall.

The server records the local handshake, new character creation/selection and
docked fitting bootstrap. Credentials are not copied into project documentation
or defaults. The client exits with code 0 after 474.5 seconds; no current
launcher stop operation is recorded, so the supervisor calls it an unexpected
exit. All owned groups are subsequently empty and `cleanShutdown=true`; the
server remains ready at export. This does not revoke the user's accepted
rendering result, but it does not qualify an explicit client/server shutdown,
reopen persistence, visible station gameplay, undock/warp/dock or audio.

## 0.1.13 isolated recovery and experiments

The October 4 optimization report ranked regression isolation first. The current
build restores the exact accepted caps and after-complete request policy; the
previous 0.1.12 “Previous settings” profile kept the new early-request policy.
Display protocol checks retain optimized buffers and resize/input safeguards.
Single-factor cap profiles and a separate early-request option isolate changes.

Two optional flags preserve the exact shipped binaries and game fidelity:

- Mesa 26's [nocb option](https://github.com/chaotic-cx/mesa-mirror/blob/mesa-26.0.0/src/freedreno/vulkan/tu_util.cc)
  disables concurrent binning through its existing A7xx command-buffer guards.
  A [later upstream change](https://github.com/chaotic-cx/mesa-mirror/commit/5529f15f31b0cd9c13f611148fcf9b272efd6b56)
  motivates this trial but provides no measured EVE gain.
- Pinned FEX [host feature selection](https://github.com/FEX-Emu/FEX/blob/320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab/Source/Common/HostFeatures.cpp)
  supports disablelrcpc2 for the immediate-addressing TSO instruction form,
  independently of ordinary RCPC/scalar TSO. Its ARM64EC module loads environment
  configuration. A [later CPU-specific fix](https://github.com/FEX-Emu/FEX/commit/8cc967fa22c9cef173ec3fe94c0b6661de468cbb)
  motivates testing on affected cores; no thread affinity is forced.

Both options are fixed allowlisted session values, default off, sanitized on
restart and removed in software mode. MIDR/topology reads may be unavailable on
Android. Receipts distinguish requested/effective environment assignments from
verified native effects. Native CI verifies the FEX option's shader/display path
on its CPU, while the Adreno option needs the Thor's hardware preflight/run.

The release APK disables debugging and enables shell profiling while retaining
its preview signing key. Android's [profileable guidance](https://developer.android.com/guide/topics/manifest/profileable-element)
explains the lower-overhead packaging, but device PRoot/ptrace and UI/controller
qualification cannot be inferred from a Linux fixture.

Cached dynamic resources are intentionally deferred until actual KGSL allocation
flags and dynamic constant-buffer CPU-write/GPU-read coherence pass a fixture.
The exact DXVK option would be d3d11.cachedDynamicResources=c; it is not enabled
or exposed by this build. More invasive driver/native-presentation/PRoot changes
remain conditional on the measured bottleneck. No FPS improvement is claimed
before repeated warmed device runs.
