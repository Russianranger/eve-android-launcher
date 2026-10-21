# EVE Android Launcher 0.1.7 — Connected send acceleration

Adds an independently selectable in-kernel fast path for connected
sendto(NULL,0). Explicit destinations and socket/connect/bind, sendmsg/sendmmsg
and io_uring retain the existing loopback enforcement. Wildcard binds and TLS
port rewriting remain unchanged. Set networkFastSendto=false for the baseline.

Opt-in networkTraceStats logs cumulative send trap counts for device A/B tests;
no Thor sendmsg frequency or FPS gain is claimed. Default statistics are off.
The 0.1.5 runtime knobs and 0.1.6 direct Surface display remain configurable.
See TESTING.md for exact FPS/trap comparisons. Update in place, retaining all
accepted client files, runtime/prefix and world state.
