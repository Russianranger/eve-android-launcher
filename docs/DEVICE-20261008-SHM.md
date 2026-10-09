# Thor shared-memory presentation run: October 8, 2026

The user reports that 0.1.18 performance and temperatures are about the same
as before. Accept this as a neutral physical result for linear presentation
plus shared-memory frame transport. The user does not want another baseline
run merely to repeat a neutral performance comparison. This archive proves
that the experiment was active in EVE, so its neutral outcome cannot be
explained by an unselected flag or helper-only activation.

Times below use CDT (UTC−5), unless explicitly marked UTC. Private account,
character, ship, station, process and session identifiers are omitted.

## Source and configuration

`eve-support-20261008-204630.zip`, 176,668 bytes, 73 entries, SHA-256
`501c8f04a04f8e66394314e84d9ca7f3f56621461ad07b83491d5bdd64d008bb`.
The archive is read directly from the provided attachment; it is not modified.

The export records app 0.1.18, AYN Thor Android 13/API 33 and EVE build
3396210. The active client runtime remains Wine 10.13/FEX ARM64EC with native
DXVK 2.4.1 and Turnip Mesa 26.0.0. Selected and effective flags agree:

| Setting | Captured value |
|---|---|
| GPU rendering | Turnip/DXVK, Adreno 740 |
| Linear presentation | On; `MESA_VK_WSI_DEBUG=sw,linear` |
| Shared-memory presentation | On |
| Forced SYSMEM rendering | Off; no `TU_DEBUG` override |
| A740 PC-mode driver | Off |
| Early display requests, concurrent-binning disable, LRCPC2 disable | Off |
| Profile | Responsive |
| Render cap / queue latency / Android display cap | 30 / 1 / 30 |
| Diagnostic HUD | On |

The selected driver is `turnip-26.0.0-x11-shm.so`, SHA-256
`ed8a9566755001c59696a3de7a2c46a8724e3fcacdb2cd0df1d24aa58c738be1`.
Its dedicated Mesa cache is `mesa-26.0.0-x11-shm`. Fresh native D3D11 and
DXGI module hashes are respectively
`7c65883394c45c7e5f5a4f55f3f62c08b50360b526f3e828e8fe499ac71283d2`
and `ce8cc6e1078fed6aa8b327332b0a3d498396a407cb23d135f2b14ae0e12e1b03`.
They match this bundle's identities, but differ from the earlier 0.1.17 DLL
bytes. Same source versions do not make the two APKs byte-identical controls.

Fresh original-driver Vulkan, exact A740 identity (`device_id=0x43050a01`),
selected-driver Vulkan, selected-environment Vulkan, native D3D11 shaders and
readback all pass. Three independent visible RFB helper frames also pass.
The SHM qualification records three completed 128×128 native helper transfers,
three stages, hardware identity verified and `transportActivationVerified=true`.
The conservative `nativeEffectVerified=false` and `physicalBenefitVerified=false`
fields are correct: activation and pixel correctness are established; a
positive physical EVE performance effect is not.

The actual EVE log confirms DXVK 2.4.1, Turnip Adreno 740 and effective
`dxgi.syncInterval=0`, `dxgi.maxFrameRate=30`, `dxgi.maxFrameLatency=1`.
The current window is 1280×720. The generic content preparation's old
`client_launch_qualified=false` field is not a current graphics failure.

## Actual EVE-sized SHM transfers

The current `client-client.log` contains twenty `EVE_X11_SHM` active reports
for four separate 1280×720 stages. Each has row pitch 5,120 bytes and size
3,686,400 bytes, totaling 14.06 MiB for the four reported stages. Every stage
reports completions 1, 2, 3, 300 and 600. Taking the latest completion count
per stage establishes at least 2,400 completed EVE-sized SHM presents. Sparse
sampling intentionally does not record every frame or its timestamp, so this
count must not be converted into an engine FPS estimate.

All twenty reports have `barrierAfterPut=true` and
`pendingBeforeOverwrite=false`. There are no SHM fallback reports in the
current EVE log. PRoot also records real memfd-backed SysV allocations. This
is physical-device evidence of the intended transport, beyond the startup
helper's much smaller frames.

| Sample group | CPU copy duration | Wait for already-submitted server completion |
|---|---:|---:|
| First transfer on four fresh stages | 2.728..3.217 ms | 1.719..3.594 µs |
| Transfers 2 and 3 | 0.310..0.516 ms | 1.927..7.084 µs |
| Eight later samples at completions 300 and 600 | 0.891..1.877 ms; median 0.970 ms | 4.428..12.864 µs; median 7.083 µs |

These are sparse samples of the stage's CPU copy and the wait performed when
reusing or retiring that stage. The low sampled server wait means the
previous server consumption was generally already complete when checked.
It does not measure the duration of Xvnc's image copy, EVE rendering, the
Vulkan GPU-completion fence, Android presentation, or total frame latency.
The original GPU-completion synchronization remains required. The data does
not justify weakening it or adding an unconditional longer frame queue.

The user nevertheless observes no FPS or thermal improvement. Removing the
Mesa-to-Xvnc full-pixel X11 wire payload did not remove the frame's GPU
readback/completion dependency, this CPU staging copy, Xvnc framebuffer work,
Raw RFB output or Android bitmap presentation. Deprioritize this transport as
a standalone performance solution and retain its default-off status.

## Two launches and one reported Android low-memory exit

This export contains a failed earlier process lifetime and a later successful
running lifetime; it must not be described as an entirely crash-free test.

| Time CDT | Evidence |
|---|---|
| 20:37:14..20:37:35 | Server starts and reaches READY. |
| 20:39:10..20:39:30 | First EVE launch passes startup; display connects at 20:39:43. |
| 20:40:52 and 20:40:53 | Two trim-level 15 callbacks retain the client with `android-memory-ample`; neither client nor server stop is requested. |
| 20:40:55.665 | Newest Android application exit record has reason 3, status 0. |
| 20:41:04 | Start client is rejected because the server is no longer READY. |
| 20:41:07..20:41:40 | Server starts again and reaches READY. |
| 20:41:43..20:42:03 | Second client start succeeds; supervisor explicitly recovers previous EVE processes. |
| 20:42:26..20:46:28 | Current display connection runs and closes cleanly. |
| 20:46:28..20:46:29 | Current EVE has two processes; Xvnc, WineServer and server remain running. |
| 20:46:31 | Support export begins; this ZIP does not include export completion or a later reopen. |

Android's official `ApplicationExitInfo.REASON_LOW_MEMORY` value is **3**:
[ApplicationExitInfo reference](https://developer.android.com/reference/android/app/ApplicationExitInfo#REASON_LOW_MEMORY).
Thus the system reports the first application death as a low-memory kill,
rather than a Java exception, native crash or ANR. The record has no additional
description. It reports launcher RSS 208.96 MiB and PSS 88.81 MiB; these are
not the total memory of the EVE/server process cohort.

The last preceding first-lifetime Android sample still reports
`lowMemory=false`, 7.68 GiB available, a 216 MiB threshold, thermal status 0
and power-save mode false. The two trim callbacks had 6.73 and 7.06 GiB
available and correctly exercised the guard's retain policy. This does not
invalidate the OS exit record: an earlier sampled `MemoryInfo` snapshot and
an Android-reported process death are different evidence. It also does not
identify the exact kernel/vendor policy or pressure source. There is no
current app-initiated stop request corresponding to the death, and no reason
to reinstate the old indiscriminate stop-on-trim behavior.

Launcher process identity changes between the first and second lifetimes;
the first `client-performance.json.1` ends at 20:40:53. The supervisor's
recovery receipt belongs to the second launch. First-lifetime EVE crash cause,
post-export continuity and an LMK relationship to SHM cannot be established
from this ZIP. The current running lifetime has no unexpected-exit receipt
or SHM fallback. A clean RFB display disconnect is not an EVE crash.

## Current lifetime CPU, memory and thermal observations

The current performance capture starts at 20:41:58 and retains forty samples
from 20:43:05 to 20:46:28; thirteen oldest samples were removed by the bounded
file-size limit. Client CPU spans 101.88..223.37%, with median 171.78%, where
100% means one logical CPU. Client RSS grows 1,576.34→3,031.50 MiB across this
retained interval, which includes world loading. The final ten samples are
approximately 3,028..3,034 MiB. This is not evidence of an unbounded leak.
There are two client processes, one Xvnc and one WineServer throughout the
retained samples.

In the final twelve samples, client CPU median is 208.23%, Xvnc median 25.61%
and shader worker CPU is zero. Submission/completion/presentation thread CPU
means are approximately 3.27%, 3.27% and 1.75%, respectively. Five of twelve
completion point snapshots are in `adreno_drawctxt_wait`, six in futex wait
and one unavailable. Point snapshots are not accumulated GPU wait time or
GPU utilization; they support measuring the render/readback dependency but
do not assign a dominant bottleneck.

Twenty retained hardware samples show GPU current frequencies 401, 550, 615
and 680 MHz; the readable GPU policy maximum remains 680 MHz. CPU3–6 readable
maximum remains 2,323.2 MHz, CPU7 maximum remains 2,476.8 MHz and CPU0–2
maximum is permission denied. Current frequency variations do not establish
temperature-induced throttling. The readable policy ceilings do not fall
over this retained interval.

The retained `cpuss-0` sensor rises from 48.1°C to 61.8°C, with range
47.3..61.8°C. This is one named CPU sensor among the first 32 zones, which
contain no named GPU sensor; it is not necessarily the sensor used by the
user's temperature overlay. The user reports unchanged temperatures, and
that remains the physical outcome. This shorter, differently loaded run's
sensor range cannot establish cooling relative to earlier runs.

The current application lifetime has twenty-nine Android memory samples
from 20:41:47 to 20:46:28, all `lowMemory=false`, with 6.07..9.32 GiB available.
Launcher RSS ranges 131.50..185.20 MiB, Java used memory 3.97..26.21 MiB;
the final sample has 6.08 GiB available and launcher RSS 156.74 MiB. Android
thermal status remains 0 and power-save mode false. Battery values are a
separate temperature measurement. There are no new trim callback events in
this second application lifetime.

## Remaining display cost and historical comparison limits

The current Android RFB connection lasts 242.001 seconds. Its lifetime metrics
can be placed beside the previous 0.1.17 export as historical observations,
but neither rate is engine FPS and this is not a controlled physical A/B.
Durations, camera activity, startup state, selected render mode, driver and
rebuilt native DLL bytes differ.

| Lifetime connection measurement | Earlier 0.1.17 linear + SYS | Current 0.1.18 linear + SHM |
|---|---:|---:|
| Raw RFB socket throughput | 28.11 MiB/s | 27.18 MiB/s |
| Framebuffer updates per second | 14.15 | 14.51 |
| Raw rectangles per update | 102.22 | 110.85 |
| Decode plus bitmap publication per update | 2.32 ms | 2.14 ms |
| Socket read wall-time fraction | 96.71% | 96.88% |
| Android view CPU draw per view draw | 0.088 ms | 0.067 ms |
| Android frame GPU time per reported sample | 6.78 ms | 7.55 ms |
| Android total time per reported frame | 10.13 ms | 9.78 ms |

Socket read wall time includes waiting for data and does not mean that the
network consumed 96.88% of CPU. Android frame GPU time describes bitmap
presentation, not EVE's GPU frame duration. All 905 input operations complete,
none are rejected and maximum queue depth is one. No Android frame reports
are dropped.

Xvnc's comparison tracker records 2.78970 Gpixels in and 1.72148 Gpixels out,
filtering about 38.3% of compared pixels. Disabling comparison would add
approximately 62.1% of those compared pixels to output in this workload,
before accounting for other scheduling or overhead. Preserve comparison;
the neutral SHM result does not justify disabling it by default.

## Implications for the next candidate

1. Accept the neutral result. Keep linear as the user's earlier useful state;
   leave forced SYSMEM and SHM off for the next isolated candidate unless it
   explicitly depends on SHM. Do not request another performance baseline.
2. Measure upstream render completion/readback and submission pacing with
   bounded native phase timings. Existing SHM copy/wait samples exclude GPU
   wait and cannot rank that cost against EVE rendering. Preserve correctness
   fences and the 30 / 1 / 30 responsive defaults until evidence supports a
   separately gated change.
3. A display candidate should address remaining Xvnc/Raw RFB/Android upload
   work or its scheduling, rather than assume another change to the already
   successful Mesa-to-Xvnc wire leg will produce stable 30 FPS. Retain full
   color, opaque bitmap behavior, input responsiveness and changed-pixel
   comparison.
4. Extend app exit diagnostics with reason names and available importance/
   cohort memory context. Investigate the explicit Android low-memory death
   without attributing it to a shader cache, SHM's 14.06 MiB staging allocation
   or the corrected trim policy. An earlier ample-memory snapshot does not
   disprove an OS kill, and this archive lacks kernel/vendor LMK evidence.

No observation here establishes stable 30 FPS or a thermal reduction. The
next device request should be one independently qualified candidate run with
the user's FPS/temperature report and one live-export ZIP; repeat an old
baseline only if it becomes necessary to isolate an actual fault.
