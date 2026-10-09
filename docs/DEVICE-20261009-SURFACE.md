# Thor separate display surface run: October 9, 2026

The user reports unchanged FPS with temperatures increasing over time to the
low to mid 70s Celsius on 0.1.19. Accept this as a neutral FPS result and no
demonstrated thermal improvement for linear + SHM + separate display surface.
The archive proves that the new surface path actually posted game frames;
unselected settings or fallback do not explain the outcome. Do not request
another baseline performance run merely to repeat this result.

Times below use CDT (UTC−5), unless explicitly marked UTC. Private account,
character, ship, station, process and session identifiers are omitted.

## Source and active configuration

`eve-support-20261009-083509.zip`, 171,770 bytes, 73 entries, SHA-256
`eaa72ec7681a918575ee6128caf88e9914a018052a4c8cb8c8c26d6c8738ab6f`.
Read directly from the provided attachment; the attachment is not modified.

The export records app 0.1.19, AYN Thor Android 13/API 33, EVE build 3396210,
the FEX ARM64EC runtime, native DXVK 2.4.1 and Turnip Mesa 26.0.0/KGSL.
Selected settings, runtime receipts and actual display metrics agree:

| Setting | Captured value |
|---|---|
| GPU rendering | Turnip/DXVK, exact Adreno 740 identity `0x43050a01` |
| Linear presentation | On; `MESA_VK_WSI_DEBUG=sw,linear` |
| Shared-memory presentation | On; dedicated SHM driver/cache |
| Separate Android display surface | On; actual successful posts verified |
| Forced SYSMEM / A740 PC mode | Off / off |
| Early display requests / concurrent-binning disable / LRCPC2 disable | Off / off / off |
| Profile / render cap / queue latency / display cap | Responsive / 30 / 1 / 30 |
| Diagnostic HUD | On |
| Framebuffer | 1280×720, full RGB888 in 32-bit RFB pixels |

The active driver is `turnip-26.0.0-x11-shm.so`, SHA-256
`66e3a609875d7815db32b2887a11b6e5fc2a2b670a9a91dc32cb92a07931f5e2`.
Native D3D11 and DXGI hashes are respectively
`334fc38a430743033a0e84742f7ef8ba57a49906c27a12abd1968d68df8c7868`
and `04942742e296d19d904c6a82a06d53d43d721f7613326808b301b64915d650ba`.
These differ from the earlier 0.1.18 export's rebuilt bytes. Source versions
are retained, but this is not a byte-identical controlled A/B.

Fresh original-driver Vulkan, exact A740 identity, selected-driver Vulkan,
selected-environment Vulkan, native D3D11 shader/readback and three visible
RFB helper frames all pass. SHM helper activation is verified independently.
The helper's requested sync interval is overridden to IMMEDIATE; the actual
EVE configuration remains `dxgi.syncInterval=0`, `dxgi.maxFrameRate=30` and
`dxgi.maxFrameLatency=1`. The old content-preparation
`client_launch_qualified=false` field is not a current graphics failure.

## Separate surface activation and costs

The actual Android display connection lasts 389.168 seconds, approximately
08:28:38..08:35:07. Its final receipt has
`presentation_mode=separate-surface-cpu-canvas`,
`separate_surface_requested=true`,
`separate_surface_activation_verified=true`, `surface_failure=none` and zero
surface failures. There is no fallback operation in the current lifetime.
Final `active=false` and `separate_surface_active=false` follow the clean
display disconnect, rather than indicate that the experiment was inactive
during the run.

| Surface lifetime measurement | Value |
|---|---:|
| Completed-update requests / snapshots | 6,531 / 6,531 |
| Successful game-frame posts | 6,364 |
| Coalesced requests | 29; 0.44% of requests |
| Snapshot wall time | 2,143.80 ms total; 0.328 ms per snapshot |
| `lockCanvas` wall time | 5,417.75 ms total |
| Canvas clear/draw wall time | 6,450.59 ms total |
| `unlockCanvasAndPost` wall time | 8,502.23 ms total |
| Lock + draw + post wall time | 20,370.57 ms total; 3.201 ms per successful post |

Normalized to the successful-post count, lock/draw/post totals are about
0.851 / 1.014 / 1.336 ms per successful post. The timings can include stale
lifecycle buffer releases and native BufferQueue waits, so these are aggregate
normalizations, not independently measured distributions of valid-frame
latency. Snapshot work is separate. Do not sum these CPU wall-time counters
with EVE GPU time or interpret them as physical GPU utilization.

The 167-request difference between snapshots and successful posts is not a
167-frame failure count. Posts are counted only after an accepted, current
lifecycle/connection token; frame-rate pacing, coalescing and lifecycle
transitions can retire requests. The sparse final counters do not attribute
each difference. All 1,286 input operations complete, none are rejected,
maximum input queue depth is two and maximum sampled queue wait is 5.42 ms.

The new path avoids the original bitmap view's game draws (`view_draws=0`)
but retains framebuffer decode, a completed-image snapshot, CPU canvas copy
and surface composition. Actual Hardware Composer selection and total
Android GPU work are not captured. Successful surface posts establish
activation, not improved FPS, cooling or zero-copy presentation.

## RFB and FrameMetrics measurement domains

| Lifetime connection measurement | Previous 0.1.18 linear + SHM | Current 0.1.19 linear + SHM + surface |
|---|---:|---:|
| Connection duration | 242.001 s | 389.168 s |
| Raw RFB socket throughput | 27.18 MiB/s | 42.52 MiB/s |
| Framebuffer updates per second | 14.51 | 16.78 |
| Raw rectangles per update | 110.85 | 68.22 |
| Decode + bitmap publication per update | 2.14 ms | 2.94 ms |
| Socket read wall-time fraction | 96.88% | 95.06% |
| Window FrameMetrics reports | 3,527 | 179 |

Neither framebuffer update rate nor surface-post rate is engine FPS. Socket
read wall time includes waiting for data and is not socket CPU utilization.
Different startup durations, camera activity and full-pixel traffic prevent
these lifetime rates from establishing a causal performance improvement.

The new `android_frame_metrics_scope=app-ui-window-only` is essential:
SurfaceView game frames are outside the measured app window. Its 179 reports
have 1,503.04 ms aggregate GPU duration and 3,519.00 ms total duration, about
8.40 ms GPU and 19.66 ms total per report. The earlier bitmap path included
game bitmap presentation in its window reports. These are different workloads;
the dramatic reduction in report count/total GPU duration cannot establish a
reduction in whole-device GPU time or game frame latency. No reports are
dropped.

Xvnc's comparison tracker records 5.32111 Gpixels in and 4.33465 Gpixels out,
filtering about 18.54% of compared pixels. Disabling comparison would add
about 22.76% of those output pixels for this workload. Preserve comparison;
increased output versus yesterday does not justify disabling it.

## Actual EVE SHM activity

The current game log contains 32 active reports for four separate 1280×720
SHM stages. Each has row pitch 5,120 bytes and size 3,686,400 bytes, totaling
14.06 MiB. Each stage reports completions 1, 2, 3, 300, 600, 900, 1,200 and
1,500: at least 6,000 completed EVE-sized SHM presents. There are no SHM
fallback reports; all have `barrierAfterPut=true` and
`pendingBeforeOverwrite=false`. Sparse counts must not be converted to FPS.

| Sparse SHM sample group | CPU copy duration | Wait when checking prior server consumption |
|---|---:|---:|
| First transfer, four stages | 2.778..5.260 ms | 2.396..2.864 µs |
| Transfers 2 and 3 | 0.213..0.416 ms | 1.719..3.177 µs |
| Twenty later samples | 0.245..1.294 ms; median 0.390 ms | 0.937..11.094 µs; median 5.286 µs |

These exclude rendering, GPU-completion fences/readback, Xvnc's consumption
duration and Android presentation. Low server-check waits are consistent
with already-completed prior consumption, not proof that the total transport
or render/readback path is free. Retain correctness synchronization.

## Heat, frequencies and memory

Current native performance capture starts at 08:28:27.55. The size-bounded
file retains forty samples from 08:31:44.87 through 08:35:08.07; 38 older
samples were removed. Twenty retained hardware samples show:

- `cpuss-0` increases 61.4→73.9°C, range 58.3..73.9°C.
- `aoss-0` increases 55.1→69.2°C and `pa` 56.1→69.5°C.
- GPU current frequencies are 401, 475 and 680 MHz; readable maximum stays
  680 MHz. Readable CPU3–6 maxima stay 2,323.2 MHz, CPU7 stays 2,476.8 MHz;
  CPU0–2 maxima are permission denied.

This directly records substantial CPU-sensor heating, consistent with the
user's report. The named CPU sensor is not guaranteed to match their overlay.
There is no named GPU sensor among the bounded first 32 zones. The captured
policy ceilings do not fall; current-frequency variation and heating alone
do not prove temperature-driven throttling. Android thermal status is zero,
which does not negate the sensor temperatures or the user's observation.

Client CPU spans 145.52..225.02%, median 206.34%, where 100% means one logical
CPU. In the final twelve samples, client CPU median is 206.22%, Xvnc 24.33%
and WineServer 14.22%; shader worker CPU is zero. Completion point snapshots
show `adreno_drawctxt_wait` in nine of twelve, futex wait in two and a traced
stop in one. These are sampled wait locations, not accumulated GPU duration
or utilization. Measure render/completion/readback phases before ranking them.

EVE cohort RSS is 2,891.52→3,056.50 MiB in the retained interval, with a peak
3,111.37 MiB; final twelve samples remain about 3,053..3,057 MiB. Two client
processes, one Xvnc and one WineServer persist. This bounded observation does
not establish an unbounded leak. Forty-two current-app Android memory samples
from 08:28:19 through 08:35:09 all have `lowMemory=false`, with 4.53..7.20 GiB
available against a 216 MiB threshold. Launcher RSS is 146.63..174.58 MiB,
ending 168.46 MiB; Java used memory is 3.84..27.17 MiB. Power-save mode is
false. There is no trim event for the current app lifetime.

## Session and export boundary

Server reaches READY at 08:27:49. Client start completes at 08:28:33 and the
display connects at 08:28:38. The display closes cleanly at 08:35:07; the
native status still records running EVE/display/server at 08:35:08..09.
Export begins at 08:35:10. The ZIP includes neither export completion nor a
later display reopen, so post-export continuity is unverified.

Android exit records and memory-pressure events in this ZIP are historical.
The newest app exit is October 8 at 20:56:44 (reason 10); the reason-3
low-memory death at 20:40:55 is the same earlier lifetime already documented
in `DEVICE-20261008-SHM.md`. There is no new Android exit record or current
unexpected EVE-exit receipt before this export boundary. The rotated native
performance file also belongs to October 8; do not mix it into today's run.

## Next optimization decision

Keep separate surface default-off and disable it for the next isolated
candidate: actual activation without FPS benefit does not justify promotion.
Keep the user's earlier useful linear option; SHM remains independently
neutral and should be off unless the next candidate depends on its transport.
Preserve 30 / 1 / 30, IMMEDIATE, full RGB, fences, changed-pixel comparison,
cache/data and input behavior. Prioritize a qualified driver/render-path
candidate or bounded native render/completion/readback measurements over
another Android presentation micro-change. Request one candidate run and one
live-export ZIP; an old baseline is needed only to isolate an actual fault.
