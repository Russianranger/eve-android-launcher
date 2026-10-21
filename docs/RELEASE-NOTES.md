# EVE Android Launcher 0.1.6 — Direct Surface display

Adds bulk RGBA ByteBuffer→opaque Bitmap updates, early incremental RFB requests
and a dedicated SurfaceView rendering worker. Each change is independently
selectable in Client → Edit performance settings; legacy pixels, View drawing
and end-of-decode requests remain available. A runtime pixel/opacity self-check
falls back cleanly if Android's buffer layout differs.

Default `{}` now enables the direct/surface/pipelined display alongside the
0.1.5 runtime knobs. Separate received/drawn counters and connection settings
are exported. Compare one setting at a time using TESTING.md; physical Thor FPS
is unmeasured. Existing content validation, loopback restrictions, TLS, memory
reserves, input release and process journals remain in place.
