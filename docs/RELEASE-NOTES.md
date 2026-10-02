# EVE Android Launcher 0.1.0 — server setup preview

Initial ARM64 Android integration of the supplied EVE.js 0.12.9 source. The
launcher installs a pinned native Linux server runtime, prepares persistent
private world state, supervises server readiness and shutdown, and provides
diagnostic export. Client import and exact-build preparation are developed
alongside the server. Client rendering and gameplay are pending device
qualification.

The supported Windows client is EVE build 3396210. Retail EVE client binaries and
resources are user supplied and are not part of this release. Read the included
testing instructions before the initial server test.

The release includes the ARM64 server runtime, its manifest and qualification
report, the complete launcher source, and corresponding source archives for
the server runtime and PRoot/talloc.
