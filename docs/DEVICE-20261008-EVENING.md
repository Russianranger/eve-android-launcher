# Thor baseline and linear runs: October 8, 2026 evening

The user reports baseline FPS in the 20s with temperatures in the high 60s to low
70s Celsius, then some FPS improvement and a slight temperature reduction with
linear presentation. These 0.1.16 exports establish a true baseline-versus-linear
comparison. The telemetry does not record engine FPS or quantify the reported
FPS improvement. Times use CDT (UTC−5) unless marked UTC.

## Source archives

- `eve-support-20261008-181120.zip`, 210,681 bytes, SHA-256
  `19f01016b428c6dbb70438e75569b96864497e479a3562c71080e1176b12b751`.
- `lineareve-support-20261008-181842.zip`, 206,921 bytes, SHA-256
  `ef187c0d77c2aae2e58998e6c8df93dc00965eb68514c6a9ac981129a397352e`.

## Configuration and fresh graphics gates

Both exports record app 0.1.16 on Thor Android 13/API 33, EVE build 3396210, the
existing Wine/FEX ARM64EC runtime, native DXVK 2.4.1, and original Turnip Mesa
26.0.0. Graphics bundle metadata is identical. The original driver SHA-256 is
`51b968eed13c933d114cdc2956135758917e48451129f647ecb5ebbea5a527eb`.
Both sessions enter the same station with the same character and ship.

| Runtime selection | Baseline | Linear |
|---|---|---|
| Requested/effective linear presentation | false / false | true / true |
| Recorded `mesaWsiDebug` | `sw` | `sw,linear` |
| Performance caps | render 30 / latency 1 / display 30 | render 30 / latency 1 / display 30 |
| Other experiments | off | off |
| Diagnostic HUD | on | on |

Actual EVE logs confirm `dxgi.syncInterval=0`, render cap 30, queue latency 1,
BGRA8 UNORM at 1280×720, IMMEDIATE presentation and four swapchain images in both
runs. Fresh hardware Vulkan, native D3D11 shader/readback and three independently
matched RFB-frame gates pass both. Linear also passes fresh exact A740 identity
and LINEAR format capability checks. `nativeEffectVerified=false` remains: these
checks qualify compatibility and visible helper frames, not a measured EVE
performance effect or physical swapchain tiling.

## Matched warm observations

Use +180..240 seconds after the current session's docked GetSelfInvItemResult:
23:05:24.153 UTC for baseline and 23:14:25.104 UTC for linear. Retained process
samples cover offsets 181.86..239.30 seconds and 180.56..237.93 seconds,
respectively. The bounded history evicts older samples; this common interval
avoids comparing different portions of startup.

| Measurement | Baseline | Linear |
|---|---:|---:|
| Process samples | 12 | 12 |
| Client CPU mean, 100%=one logical core | 194.05% | 198.71% |
| Xvnc CPU mean | 24.89% | 26.80% |
| WineServer CPU mean | 13.30% | 14.00% |
| Client RSS mean | 2983.10 MiB | 2989.20 MiB |
| Child main-thread CPU mean | 49.93% | 47.58% |
| Completion snapshots in `adreno_drawctxt_wait` | 5/12 | 10/12 |
| Shader worker CPU | 0% | 0% |
| Readable hardware samples | 6 | 6 |
| `cpuss-0` temperature mean | 68.03°C | 67.95°C |

Client RSS is nearly flat in this interval: 2984.09→2983.36 MiB baseline and
2991.56→2986.73 MiB linear. Warm shader workers are idle. Thread wait snapshots
are point observations, not accumulated wait duration, frame times or a direct
measure of physical GPU utilization. This evidence does not establish one
dominant client bottleneck.

## Readable clocks and thermal observations

Across the 20 retained hardware samples per run, the GPU reports 680 MHz in 19/20
baseline samples and 16/20 linear samples. Other current readings are 475 MHz
baseline and 401/615 MHz linear. The reported GPU policy maximum remains 680 MHz
throughout both. CPU3–6 current and policy maximum remain 2323.2 MHz; CPU7 policy
maximum remains 2476.8 MHz with dynamically changing current readings from
595.2 to 2476.8 MHz. CPU0–2 maximum attributes are permission denied.

These CPU ceilings are below the startup topology's hardware maxima of 2803.2
and 3187.2 MHz, but the logs do not establish the policy's cause. No readable
maximum decreases with rising temperature in either retained interval. Current
frequency variation alone does not establish thermal throttling, and frequency
attributes do not measure load or guaranteed execution frequency.

Readable thermal types include `pa`, `mmw3`, `aoss-0` and `cpuss-0`. The first
32-zone limit captures no named GPU temperature sensor. Baseline `cpuss-0` peaks
at 75.1°C and linear at 68.8°C in the retained history, but baseline export is
almost six minutes after docking versus about 4:27 for linear. Unequal duration
and activity confound full-run peak and mean comparisons. The matched three-to-
four-minute interval differs by only 0.08°C in this sensor's mean. Keep the
user's observed slight temperature benefit distinct from that limited sensor
comparison.

Android thermal status remains 0 and power-save mode is false. Battery readings
are 30–31°C baseline and 31–32°C linear; they are not the user's SoC temperature.

## Export continuity and memory guard

Baseline export completes at 18:11:21. In the linear archive's rotated baseline
history, the same baseline client identity still has two processes at 18:11:23,
18:11:28 and 18:11:33. The display reconnects at 18:11:29. The client exits by
18:11:34, the display connection closes at 18:11:35, and manual Stop follows at
18:11:41. This sequence fits the instructed quit after export; it does not show
the earlier pressure guard terminating EVE during export. No fresh native crash
or device-lost evidence appears.

The linear client and server are alive at the 18:18:48 snapshot and export starts
at 18:18:52. That archive cannot establish continuity after the second export.

Both pressure-history files contain only the identical old 16:24:28 event from
app PID 9004. The current app PID is 17317. No new critical trim callback is
recorded, so these runs do not directly exercise the new guard's callback
retention policy. Fresh memory samples report lowMemory=false throughout,
available memory 4.75–7.43 GiB baseline and 4.65–7.72 GiB linear. No new Android
app exit appears after 16:31. Memory and shader compilation do not emerge as
warm performance constraints in this evidence.

## Display observations and interpretation limits

| Lifetime connection measurement | Baseline | Linear |
|---|---:|---:|
| Raw RFB socket throughput | 48.44 MiB/s | 45.33 MiB/s |
| Decode plus bitmap publish per framebuffer update | 3.083 ms | 2.807 ms |
| Framebuffer updates per second | 17.05 | 17.48 |
| Socket read wall-time fraction | 94.7% | 95.1% |

These are whole-connection measurements with different durations, startup
coverage and input activity. RFB update rate is not EVE engine FPS. Socket read
wall time includes waiting and must not be treated as CPU-copy cost. Android
frame GPU timings describe bitmap presentation, not EVE GPU frame time. Input
queue depth reaches only one, with no rejected input operations or dropped
Android frame reports.

The display measurements quantify remaining transport and publish work and can
guide a separately qualified experiment. They do not establish presentation or
copying as the dominant bottleneck, prove the magnitude of the reported FPS
benefit, or guarantee stable 30 FPS.
