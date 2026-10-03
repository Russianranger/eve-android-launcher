# Client optimization evidence and qualification

The requested 60-minute investigation ran 2026-10-03 20:42:57–21:42:57 UTC.
Production changes began afterward. The accepted evidence is
`eve-support-20261003-154109.zip` (SHA-256
`2af4d0dfa4b280d0a8aaa5fde7f630ff00186791f5d8264f120ecfb4047be3fc`)
and the user's successful login/character-selection report.

## Findings and changes

| Finding | Change | Verification and limit |
|---|---|---|
| Launch explicitly forced WineD3D/llvmpipe CPU rendering | Native ARM64EC DXVK 2.5.3 → existing Wine Vulkan → glibc Turnip 26/KGSL | Real native/D3D/display helper gates; actual EVE FPS still needs Thor |
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

The build pins DXVK source `c707d9026f33b6ab89639f154b6ac5f6326fa037`, its Vulkan,
SPIR-V and libdisplay-info gitlinks, and the same LLVM-mingw 20250920 used by the
accepted Wine runtime. Only two ELF files are reused from UO v0.2.17; unrelated
TRASC/Wine/D3D9/game patches are excluded. Exact Mesa/glslang/probe source and the
original recipes accompany the source archive. Build scripts and qualification
reports are retained by Actions; release packaging includes corresponding source.
