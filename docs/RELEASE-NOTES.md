# EVE Android Launcher 0.1.8 — Optional DXVK / Turnip

Adds opt-in renderer=dxvk-turnip: official SHA-256 pinned DXVK2.7.1 x64 DLLs
and our native ARM64 KGSL/X11 ICD built from pinned official Mesa25.2.8 source.
An owned, bounded startup helper must create a D3D11 device and present a
swapchain before EVE receives GPU settings. Missing/failed device or presentation
checks fall back to selectable WineD3D with a clear status/support reason.

The default remains WineD3D. Runtime profiles preserve Xvnc60/resolution/esync/
worker/priority/FEX controls, direct/pipelined Surface display and connected-send
acceleration, each independently selectable. Received/drawn counters and exact
requested/effective profiles support device A/B testing. VNC presentation remains.

No CCP client files are bundled/downloaded. Exact build/hash/patch checks,
loopback containment, TLS checks, memory reserves and process journals remain.
Update in place and keep the accepted runtimes, prefix, client cache and world.
See TESTING.md for exact comparisons and GPU-PRESENTATION.md for provenance and
the future Android-surface X-server design. No physical Thor FPS gain is claimed.
