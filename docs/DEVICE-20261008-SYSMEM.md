# Thor direct GPU rendering run: October 8, 2026

The user ran only the 0.1.17 experiment and reports no improvement. Accept this
as the physical result and deprioritize forced SYSMEM. The user explicitly
declines another baseline run unless a crash requires investigation. The earlier
0.1.16 baseline and linear runs remain available as historical references;
they are not a fresh paired comparison with this APK. Times use CDT (UTC−5)
unless marked UTC.

## Source archive

`eve-support-20261008-185828.zip`, 197,869 bytes, 73 entries, SHA-256
`0ae65a49e5d8b0db22d175890abbb459fe1e9a768d5b97f9af7b6502bc3a83b1`.

## Configuration and fresh graphics gates

The export records app 0.1.17, Thor Android 13/API 33 and EVE build 3396210.
Selected and effective settings both have linear presentation and direct GPU
rendering enabled: `MESA_VK_WSI_DEBUG=sw,linear` and `TU_DEBUG=sysmem`. The
responsive caps remain render 30 / queue latency 1 / display 30, with diagnostic
HUD on. Early display requests, concurrent-binning disable, LRCPC2 disable and
A740 PC-mode driver selection are off.

The graphics bundle keeps the earlier source/runtime/version pins: Wine/FEX
ARM64EC runtime, native DXVK 2.4.1 and original Turnip Mesa 26.0.0. Original
driver SHA-256 is
`51b968eed13c933d114cdc2956135758917e48451129f647ecb5ebbea5a527eb`.
Baseline runtime SHA-256 is
`f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`.
Fresh native D3D11 and DXGI identities match the new bundle's exact ARM64EC
binaries. The bundle as a whole is not byte-identical to 0.1.16: D3D11 is now
`c1dd5f8b88843485b42b78dd74938efc0a662379e49292121f3b6c327e024775`
versus earlier
`2cc6d59a27fb05af60e66bccadb0e5a84efe204321403f8b713c63c8494079d8`;
DXGI is now
`eb3c89925a5c1801c018c1c7fbaa7f5dae853ba87e95b57b96b34f418d4750bd`
versus earlier
`75cbc2336dba62a2d8ca956ad78a0712cf9abd3b8d7aac3325f5a1f52e844f82`.
The optional, unselected PC-mode driver hash also differs. These are the only
differences between parsed graphics-bundle metadata. This export does not
explain the DLL byte differences; preserve this caveat in historical comparisons.

Fresh original-driver Vulkan presentation, exact A740 identity
(`device_id=0x43050a01`), selected-environment Vulkan presentation, native D3D11
shader/readback and three independently matched visible RFB frames all pass.
The linear format-capability gate also passes. Both SYS and linear receipts
retain `nativeEffectVerified=false`: the gates establish the selected
environment, compatible hardware and correct helper pixels. They do not observe
physical EVE render-pass mode or establish a performance effect.

The actual EVE log confirms DXVK 2.4.1, original Turnip Adreno 740 and
`dxgi.syncInterval=0`, `dxgi.maxFrameRate=30`, `dxgi.maxFrameLatency=1`.
The actual swapchain is BGRA8 UNORM, 1280×720, IMMEDIATE and four images. The
current session reaches the same station, character and ship as the earlier
runs; private identifiers are omitted here. The generic content preparation and
launch-policy qualification fields remain conservative and must not be read as
a current failed graphics gate.

## Historical aligned warm observations

The current docked GetSelfInvItemResult is 23:55:08.405 UTC. The last process
sample is +198.63 seconds, so the earlier +180..240-second comparison window
cannot be reused in full. Use +150..200 seconds after the docked inventory
anchor in all three retained histories. These are elapsed-time-aligned
observations, not a controlled physical A/B: camera activity, starting
temperature and run duration differ, and 0.1.17 also adds the opaque Android
bitmap allocation and contains the different native DLL bytes listed above.

| Measurement | Earlier 0.1.16 baseline | Earlier 0.1.16 linear | 0.1.17 linear + SYS |
|---|---:|---:|---:|
| Process samples | 10 | 9 | 10 |
| Sample offsets after docking | 150.64..197.60 s | 154.50..196.21 s | 151.63..198.63 s |
| Client CPU mean, 100%=one logical core | 196.96% | 203.18% | 202.00% |
| Xvnc CPU mean | 24.13% | 26.75% | 25.30% |
| WineServer CPU mean | 13.20% | 14.08% | 13.87% |
| Client RSS mean | 2982.58 MiB | 2993.27 MiB | 2997.87 MiB |
| Child main-thread CPU mean | 49.30% | 48.55% | 50.65% |
| Completion snapshots in `adreno_drawctxt_wait` | 6/10 | 7/9 | 8/10 |
| Shader worker CPU | 0% | 0% | 0% |
| Hardware samples in interval | 5 | 5 | 5 |
| `cpuss-0` temperature mean | 66.08°C | 66.48°C | 66.26°C |

The current client RSS is 2996.53→3003.71 MiB in this interval. This modest
change does not establish a leak or memory constraint. Shader workers are idle
in the aligned interval. Thread waits are point snapshots, not accumulated wait
time, physical GPU utilization or EVE frame times. The telemetry neither
contradicts the user's no-improvement report nor quantifies an FPS change.

## Clocks, thermal and memory observations

Across the current 20 retained hardware samples, GPU current frequency is
401 MHz ten times, 475 MHz four times, 550 MHz once and 680 MHz five times.
Early samples include login and initial docking. In the aligned warm interval
the GPU reads 680 MHz in four of five samples and 550 MHz once. Its readable
policy maximum remains 680 MHz throughout. CPU3–6 current and policy maximum
remain 2323.2 MHz; CPU7 maximum remains 2476.8 MHz and current varies between
595.2 and 2476.8 MHz. CPU0–2 maximum is permission denied.

As in the previous runs, the CPU policy ceilings are below the topology's
startup hardware maxima; these logs do not establish their cause. No readable
maximum falls with increasing temperature. Do not infer thermal throttling from
current frequency changes or a temperature alone.

The first retained `cpuss-0` sample is 52.8°C, the last 66.5°C and the maximum
67.3°C. The retained range is 48.9..67.3°C and includes early login/docking.
This is one named CPU thermal sensor, not a recorded engine GPU temperature;
the first 32 thermal zones contain no named GPU sensor. Full-run peaks must not
be compared directly against the longer earlier baseline run. The five aligned
samples read 66.1, 67.3, 67.3, 64.1 and 66.5°C.

There are 30 current-app memory samples from 18:53:37 to 18:58:27. All report
`lowMemory=false`, with 5.04..7.44 GiB available. Android thermal status is 0
and power-save mode false throughout. Battery readings are 30..32°C and are a
separate measurement from the CPU sensor.

## Fresh memory-guard validation and export continuity

A new trim-level 15 (`running-critical`) callback occurs at 18:54:25 while the
current EVE session is running. The fresh Android snapshot has lowMemory=false,
6.71 GiB available and a 216 MiB threshold. Its recorded response is
`client-retained`, reason `android-memory-ample`, with both client and server
stop requests false. The same client identity remains running afterwards.
This directly exercises the corrected callback policy from 0.1.16; previous
exports had only the historical overaggressive-stop event.

The current Android RFB connection closes cleanly at 18:58:23. A Start EVE
operation at 18:58:24 returns the already-running session rather than creating
a new supervisor or client. At 18:58:27, the original client identity still has
two processes, Xvnc is alive and the server is running. Export starts at
18:58:29. No current native fault, device-lost or unexpected-exit evidence is
present; the newest Android app exit record predates this run at 18:23:49.
The ZIP ends before export completion, so it cannot establish post-export
continuity. The clean display disconnect is not evidence of an EVE crash.

The rotated history also extends the earlier 0.1.16 linear session: it remains
alive at 18:18:54 and 18:18:59 after the completed 18:18:52 export and reconnect
at 18:18:56. It is stopping with no client processes by 18:19:03, preceding
the display closure and later manual Stop. This confirms that earlier export
did not immediately terminate the client; it does not qualify this run's
post-export state.

## Display observations and next-candidate implications

The whole current RFB connection lasts 267.558 seconds and records:

| Lifetime connection measurement | 0.1.17 linear + SYS |
|---|---:|
| Raw RFB socket throughput | 28.11 MiB/s |
| Framebuffer updates per second | 14.15 |
| Raw rectangles per update | 102.22 |
| Decode work per update | 1.84 ms |
| Bitmap publication per update | 0.47 ms |
| Decode plus publication per update | 2.32 ms |
| Socket read wall-time fraction | 96.71% |
| Android frame GPU time per reported sample | 6.78 ms |
| Android frame total time per reported frame | 10.13 ms |

These lifetime statistics include startup and changing coverage/activity, so
their lower throughput than earlier runs is not proof of an optimization.
Framebuffer-update rate is not engine FPS; socket-read wall time includes
waiting; Android frame GPU time measures the bitmap presentation path, not
EVE GPU frame time. No Android frame reports are dropped. All 819 input
operations complete, none are rejected and maximum input queue depth is one.

Xvnc's comparison tracker records 3.01122 Gpixels in and 1.96892 Gpixels out
for the current Android connection, filtering about 34.6% of compared pixels.
Disabling comparison would send about 52.9% more of those compared pixels in
this observed workload, before accounting for request timing or additional
overhead. A comparison-bypass experiment would trade saved comparison CPU
against substantially more transport work; it is not a justified unconditional
default.

Forced SYSMEM stays default off and should be disabled for the next candidate.
Retain the user's earlier useful linear presentation result and focus on a
separately qualified client/transport change rather than repeating neutral
render-mode, cap, binning or FEX-feature matrices. Warm memory and shader
compilation are not supported as dominant constraints here. GPU-completion
waits remain visible, while Xvnc, full-color RFB and Android presentation remain
measurable work. The current evidence does not assign one dominant bottleneck
or guarantee stable 30 FPS.
