# EVE Android Launcher 0.1.1 — Client import recovery

Fixes client import termination under Android memory pressure. Preparation now
checks file sizes before binary reads, bounds metadata/index lines, uses a disk
resource-name index, releases ZIP metadata before validation, and keeps only one
binary patch buffer at a time. Python preparation is limited to 512 MiB; Android
memory monitoring pauses work while retaining the ZIP and partial extraction.

The new **Resume interrupted client import** action can recover imports left by
0.1.0. Existing extracted files must pass ZIP CRC and size checks before reuse;
all exact-build, binary hash, resource and certificate checks remain enabled.
Stage-specific progress and worker/system memory diagnostics are exported.

Update the APK, leave the server stopped, resume the retained import, then export
support logs. If no complete private ZIP survived, import the original ZIP again.
Server/player data and the existing Wine/FEX installation are preserved.

The server runtime remains immutable runtime-v1 with Node 24.18.1. The initial
Thor server test and Wine/FEX x64 probe passed. EVE login and graphical gameplay
remain subsequent milestones. Supported client: EVE 24.01 build 3396210.

The release includes the APK, launcher source, testing instructions, checksums,
and the existing corresponding server/PRoot sources and qualified server package.
