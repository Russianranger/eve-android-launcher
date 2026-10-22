# Integrate the FPS work on the delivered application

The authoritative starting point is `codex/wine-localhost-tls` commit
`6fcf6b20c5b6b538ae6bb30ed90af41d6f9829e4`, which records delivery of 0.1.22/code 23.
The independent main work began at `6d84251`, still 0.1.3. Treating that old main
as the latest application omitted already-delivered features and adaptive icons.
This integration continues the development history with 0.1.23/code 24.

## Source decisions

| Prior main commit | Integration decision |
| --- | --- |
| `87f933d` — display measurements | Adapt fresh received/drawn counters and ten-second rates to the current DisplayPerformance reports, Surface and fullscreen overlays. Keep current process/thermal/input diagnostics. |
| `fee1d99` — guest controls | Adapt bounded performance.json, requested/effective reports, safe scheduling and FEX allowlist to current graphics/profile authority; preserve accepted defaults and existing performance-core experiment. |
| `42866c6` — display transport | Keep the branch's mature early-request/resize/Surface implementations. Add optional RGBA ByteBuffer/opaque Bitmap transfer with RGB probe and legacy recovery, preserving old bulk decoding. |
| `5d4cf66` — network sends | Add opt-in NULL/zero-length sendto BPF and send trap counts; retain the branch's already-qualified entry-only handling and extend its full native policy proof. |
| `39acdaf` — GPU package | Do not import: the branch already has native ARM64EC DXVK 2.4.1, accepted Mesa 26.2.4 + linear and stronger device gates. Main's translated x64 DXVK 2.7.1/Mesa 25 package would replace newer accepted work; later DXVK semaphore behavior was already a documented compatibility problem. |
| `197f3f4` — remove push test | The development tree already has no docs/PUSH-TEST.md. Keep it absent. |
| `834049f` — renderer archive asset fix | Not applicable: the current graphics build stages individually verified native assets, not main's renderer archive. Keep its existing package/source/license checks. |

No retail client content is committed or fetched. Exact EVE build/hash/patch
recipes, current private CA/TLS gate, loopback-only destination enforcement,
corroborated memory policy, process journaling and owned-window checks remain.
The existing explicit software-recovery selection is retained; old main's
automatic renderer fallback is not imported over the current mandatory GPU
qualification gates. A selected GPU failure reports its stage and stops; choose
software recovery explicitly when needed.
No new third-party binary/source pin or device bind is introduced. The existing
`-b /dev` exposes KGSL subject to Android permissions and existing hardware probes.

## Runtime selection

Use **Client → Edit advanced performance settings**. Save `{}` to retain the
current behavior and all saved UI preferences. New direct-pixel and network
acceleration choices are opt-in; the display measurement improvement is always
available. See CLIENT-RUNTIME.md for every accepted key and TESTING.md for exact
profiles. Every new performance choice is reversible without rebuilding the APK.

The editor requires stopped runtimes, rejects unknown/mistyped values, bounds
UTF-8 size and writes atomically. External malformed files use validated defaults
and warning receipts. Native network flags are selected before PRoot startup,
recorded as immutable guest environment facts, and cannot be changed by editing
the file during a session. Server priority uses a bounded private snapshot;
client-state is not exposed to the server. Requested and effective values remain
separate, including software-only workers, esync fallback and affinity precedence.

## Qualification and publication

Before each push, run full backend regressions, package/archive/RFB/controller
host fixtures, graphics policy/parser checks, compileall, shell syntax, lineage
and whitespace checks, then fetch/rebase against this exact development branch.
The workflow retains isolated native PRoot, native ARM64EC shader/readback/RFB,
selected Mesa ABI, Android API 33/35, release lint, package and signing checks.

The normal push to this exact branch now publishes the qualified prerelease,
including corresponding source artifacts, using the unchanged cached signing key
and published certificate anchor. A new release lineage gate requires ancestry
from the delivered 0.1.22 commit and a higher versionCode/versionName; a divergent
old main cannot publish merely by choosing a new filename. Existing tags/assets
are never replaced. Main is not changed by this integration.

Host compatibility and software-rendering fixtures do not prove Thor FPS/heat,
actual panel presentation, or performance benefit. Native trap logs, display
receipts, the game HUD and physical observations are complementary evidence.
