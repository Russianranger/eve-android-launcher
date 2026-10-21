# EVE Android Launcher 0.1.4 — Rendering measurements

Adds separate received updates/s and distinct drawn frames/s to the client
status bar and bounded support logs every ten seconds. Startup observations
and exports identify the exact active performance settings. This measurement
release retains the existing renderer, resolution, 15 Hz cap and drawing path.

Update in place without reimporting client files or clearing app data. Use the
same scene for a 30-second warmup and 60-second observation, then export support
logs. Physical FPS improvements are not claimed. Exact client validation,
loopback containment, TLS checks, memory reserve and process journals remain.
