# EVE Android Launcher 0.1.5 — Runtime performance profiles

Adds an in-app bounded JSON profile editor and one-tap baseline settings.
Defaults now request Xvnc60Hz, 1280x720, esync with eventfd/fd-limit preflight,
quiet Wine logs, detected performance-core llvmpipe workers, and lower-priority
Node/wineserver processes. Resolution960x540, CPU affinity and verified FEX
settings can be compared without rebuilding. Relaxed TSO has no new default
overrides. WineD3D remains the default and fallback renderer.

Requested/effective profiles and fallback reasons are exported. Display metric
I/O runs off the UI thread with unique session/profile identity. Update in
place; preserve the client cache, prefix and world. No physical FPS increase is
claimed until Thor A/B results are available. See TESTING.md for exact trials.
