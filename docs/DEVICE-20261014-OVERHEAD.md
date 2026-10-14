# October 14: 0.1.21 overhead experiments were neutral

Evidence: `eve-support-20261014-161104.zip`; user: FPS unchanged, no noticeable
improvement. Accept that result without another baseline test.

The support status confirms build 3396210, launcher 0.1.21, Mesa 26.2.4,
linear presentation, responsive 30/1/display30 and all three new flags enabled.
The decoder records `bulk-little-endian-64k`; controller callbacks total 573
rather than an always-running timer. The telemetry writer records 125 cached
sample serializations and zero periodic fsync requests. These demonstrate active
paths, not performance benefit.

The retained 40 warm samples span 203 seconds. Mean CPU usage (100% = one logical
core): client 222.36%, Xvnc 23.41%, WineServer 15.48%. Lifetime RFB delivery is
18.71 updates/s, with 58.89 MB/s on the loopback socket. Decode averages 1.387 ms
and bitmap publication 0.520 ms per update. RFB delivery is not engine FPS.
Shader compiler threads are effectively idle in the retained warm interval.
The latest cpuss-0 sensor is 84.9 C; its driver label is retained and must not
be conflated with the user's temperature display. Readable CPU frequency values
alone do not establish a thermal bottleneck. Current server CPU is approximately
1.3% of one core; optimizing server work is a smaller measured target.

The next three independent candidates target client execution:

1. Restrict the owned EVE/Wine launch to performance-capacity CPUs allowed by
   Android. Thor's observed capacity clusters are 280/855/1024; no hardcoded
   mask or frequency/privileged scheduler writes. Apply before Wine exec so new
   threads inherit it. Preserve PID/session ownership, server, WineServer and
   Xvnc placement. Record the current owned client thread masks, bounded to 256.
   Missing topology or denied scheduling fails the selected test explicitly.
   Hotter/fewer cores may also hurt performance.
2. `d3d11.exposeDriverCommandLists = False` requests an immediate-context path
   if EVE consults the capability. Actual EVE behavior may remain unchanged;
   capability/config readback is not proof it changes the engine's workload.
3. `d3d11.cachedDynamicResources = "vi"` uses cached memory for dynamic vertex
   and index buffers, retaining default constant/resource handling. This is a
   diagnostic candidate for CPU read overhead, not a demonstrated EVE bug.
   It can worsen GPU-bound performance and must be judged on the device.

Primary source: pinned DXVK 2.4.1
[configuration](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/dxvk.conf)
and [parser](https://github.com/doitsujin/dxvk/blob/0cf05780abd7250c2cd713b7749cf32180157cf5/src/util/config/config.cpp).
The parser removes string quotes before recording effective configuration.
No barriers, shader correctness assumptions, TSO, MSAA or texture quality are
weakened. These candidates are default-off; old settings/data/caches persist.
The cached-buffer fixture additionally maps dynamic vertex/index buffers, draws
indexed geometry and verifies its shader output and three visible frames. The
updated qualification helper preserves its original immutable-buffer mode for
other trials. Native software fixtures do not qualify EVE-specific buffer usage,
physical Adreno speed or actual command-list avoidance. Fresh hardware/pixel
checks precede each Thor launch. See TESTING.md for three isolated tests.
