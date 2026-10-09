# Mesa 26.2.4 candidate after the neutral surface trial

Research checkpoint: October 8–9, 2026. 0.1.20 integrates this as a default-off
separate pristine driver/cache after the physically activated 0.1.19 surface
trial was neutral for FPS and did not improve heat. Build/ABI qualification and
the next physical test remain required; no speedup is claimed. No repeat of the
original baseline, SYS, A740 PC mode, FEX, SHM, surface or cap matrix is requested.

## Ranking and current decision

1. **A separately selectable, source-pinned Mesa 26.2.4 KGSL driver** is the
   current native-rendering candidate. It includes actual IR3 shader compiler and A7xx
   state changes since 26.0.0. Preserve native DXVK 2.4.1 and its existing GPU
   completion fences. No source establishes a working EVE/Thor 30-FPS recipe.
2. **A short, bounded Turnip GPU timing capture** can distinguish render passes,
   copies and GPU work when the preceding evidence remains ambiguous. It is
   diagnostic work, not an optimization, and tracing overhead must be reported.
3. **Cached D3D11 constant buffers** remain deferred. The pinned DXVK option is
   a CPU-read workaround which can regress GPU-bound rendering. There is no
   evidence that EVE reads its mapped constant buffers as the limiting operation.

The completed optional Canvas SurfaceView really posted frames but had no
user-observed FPS/heat gain; do not promote or repeat it. The earlier roughly
7.55 ms app-window GPU average motivated that trial. Its new app-UI-only metrics
exclude game presentation, so smaller totals do not establish GPU savings.
See [the actual device evidence](DEVICE-20261009-SURFACE.md).

## Verified source pin

[Mesa's 26.2.4 release notes](https://docs.mesa3d.org/relnotes/26.2.4.html) identify
the October 1, 2026 bugfix release. The official archive is
[mesa-26.2.4.tar.xz](https://archive.mesa3d.org/mesa-26.2.4.tar.xz), with SHA-256:

`bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9`

This pin identifies source, not a built Android-compatible ELF. Record archive
bytes, extracted source and final ELF hashes in the eventual bundle. Build from
pristine release source with the existing X11/KGSL options; do not combine the
local A740 register patch or SHM staging patch with this first driver trial.

## Specific changes worth investigating

The upstream [26.1.0](https://docs.mesa3d.org/relnotes/26.1.0.html) and
[26.2.0](https://docs.mesa3d.org/relnotes/26.2.0.html) change lists establish the
following leads. Their applicability and benefit to EVE remain unmeasured.

| Change | Concrete mechanism | Qualification limit |
|---|---|---|
| IR3 limits large predicated blocks | In `ir3_compiler_nir.c`, `block_can_be_predicated` counts NIR instructions and switches to ordinary branches above 32 instructions. Even a divergent condition can be uniform within a wave; predication still traverses the untaken block instead of jumping over it, with effects disabled by predicates. | Requires EVE shaders containing affected branches. Do not promise a shader-wide speedup. |
| IR3 constant-vector propagation and global-address optimizations | 26.2 adds constant-vector propagation, constant source handling for global loads/stores, and global-offset lowering/optimization. | Changes generated shader code, so existing cached shaders must use a distinct versioned cache and visual correctness needs Thor. |
| A7xx interpolation state | The 26.2 list includes avoiding forced `IJ_LINEAR_PIXEL` for `FragFace`/`FragCoord`. | A relevant A7xx state correction, not a measured EVE FPS fix. |
| Turnip autotuning preference | 26.1 prefers SYSMEM for DXVK/vkd3d as part of revised autotuning rather than the old unconditional debug override. | The prior forced SYS trial was neutral. This is bundled policy in the newer driver, not a reason to repeat that old flag. |
| KGSL memory-type support detection | New code examines flags returned by the allocation ioctl instead of treating allocation success alone as support. | Primarily a correctness fix; it can change exposed memory types and allocation behavior. |

The predication implementation was checked in the release-tagged
[26.2.4 IR3 source](https://github.com/chaotic-cx/mesa-mirror/blob/mesa-26.2.4/src/freedreno/ir3/ir3_compiler_nir.c).
The exact new
[KGSL implementation](https://github.com/chaotic-cx/mesa-mirror/blob/mesa-26.2.4/src/freedreno/vulkan/tu_knl_kgsl.cc)
documents kernels which silently strip unsupported flags. Its probe now requires
`(req_alloc.flags & flags) == flags` before exposing support. Exact 26.0.0 only
checks ioctl success. This is a possible false-exposure hazard on some KGSL
versions; it is not proof that the Thor kernel strips IOCOHERENT.

The tempting `blit_cache_cleaned` fix is narrower than its name:
[upstream commit ba8de990](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/ba8de990e36474c9b46a103ca274c52fc15c87b8)
addresses redundant flushing with dynamic input attachments. Pinned DXVK 2.4.1
does not establish that EVE exercises that newer Vulkan path, so it is not ranked
as an isolated EVE backport. UBO preamble realignment also has nearly unchanged
aggregate shader statistics and is not independently a strong gain claim.

## Build and runtime requirements before selection

The release Meson files retain X11/core-XCB dependencies and KGSL support.
Meson minimum 1.4.0 is satisfied by the existing pinned 1.5.2 tool. The existing
glibc builder can attempt a pure Turnip build without LLVM, Gallium, EGL, GLX or
GBM. These source observations do not establish compatibility: the ELF must pass
the current SONAME and symbol-version guards against the accepted runtime.
Optional dependencies such as libelf or SPIRV-Tools must not be accidentally
picked up and introduced into the driver. Use existing source/compiler/tool
pins where compatible, and record every necessary build-only change.

Before a device experiment:

- Keep original Mesa 26.0.0 as the unchanged default and recovery; use a separate
  driver asset, cache directory, manifest identity and default-off option.
- Keep Wine 10.13/FEX 2510, native EC DXVK 2.4.1, responsive 30/queue 1/display 30
  and `dxgi.syncInterval=0`. DXVK 2.5+ changes submission completion to timelines;
  the existing KGSL emulated-timeline regression remains a separate blocker.
- Review 26.2.4 X11 CPU WSI allocation, copying, present-ID and IMMEDIATE behavior
  against the accepted 26.0.0 path. Keep all GPU completion/cache-coherence fences.
- Require exact A740 chip identity and selected-driver Vulkan qualification,
  native EC D3D shader/staging pixels, and three independent visible RFB frames.
  Native CI lacking KGSL proves integration, not Thor driver rendering.
- Check fullscreen colors, depth/transparency, station geometry, camera motion,
  input, display reopen, export continuity and shutdown in one future device run.
  Do not delete old caches or ask for the neutral experiment matrix again.

## Timing and cached-buffer limits

[Mesa u_trace](https://docs.mesa3d.org/u_trace.html) supports Turnip GPU tracepoints
for rendering, blits and resolves. The pinned source already contains u_trace,
but its older output does not provide newer per-process file placeholders.
An implementation must allocate a session-owned path, avoid concurrent probe/EVE
writers, bound capture duration/size and preserve the native wait logic. Public
Vulkan timestamps likewise need query-availability, device-lifetime and calibrated
clock handling; CPU fence wait duration is not GPU execution duration.

The pinned [DXVK configuration](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/dxvk.conf)
and [D3D11 buffer implementation](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/d3d11/d3d11_buffer.cpp)
show `d3d11.cachedDynamicResources=c` affects eligible host-visible DEFAULT and
DYNAMIC constant buffers. A safe trial needs actual KGSL WRITEBACK/IOCOHERENT
allocation-flag proof plus repeated CPU-write/GPU-read coherence tests through
both DYNAMIC WRITE_DISCARD and DEFAULT UpdateSubresource. Generic Vulkan flags
alone are insufficient in light of the old support-detection issue. The existing
CPU WSI already requests cached coherent host memory where exposed, so another
generic readback-cache knob duplicates selection rather than removing a copy.

## Independent review of the completed SurfaceView experiment

[SurfaceView](https://developer.android.com/reference/android/view/SurfaceView)
provides a separate drawing surface; normal ordering keeps launcher controls
above it. Android warns that overlapping controls can require an alpha-blended
composite when the surface changes. Thus a lower application-window GPU duration
after moving pixels to a separate surface cannot by itself prove lower overall
GPU cost or faster EVE rendering.

[SurfaceHolder](https://developer.android.com/reference/android/view/SurfaceHolder)
distinguishes software `lockCanvas` from hardware Canvas rendering and requires
all pixels to be redrawn unless the caller supplies a valid dirty rectangle.
Use opaque full-RGB pixels, clear the whole buffer including letterbox areas,
draw only while the holder is valid, and coalesce draws so stale frames do not
build a queue. Preserve pointer-coordinate geometry and visible controls.
Do not hold the framebuffer lock while waiting for a surface buffer.

Measure lock wait, CPU drawing and post duration separately, plus submitted frame
counts and dropped/coalesced requests. Physical FPS, temperature and control
continuity are still the success criteria. A software SurfaceView retains RFB,
CPU copying and Android composition; it does not provide native Vulkan/AHB
presentation or guarantee removal of SurfaceFlinger GPU work.
