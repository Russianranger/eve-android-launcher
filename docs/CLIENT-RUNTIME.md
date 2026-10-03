# Client runtime qualification

The preview APK prepares a private client cache and installs the exact FEX / Wine ARM64EC runtime already used by the UO launcher. The Thor server lifecycle, Wine/FEX x64 execution probe, exact client import, private TLS, local login and character selection have passed. The 0.1.5 preview prioritizes Adreno rendering and input responsiveness; acceptable performance, audio and controller support still need device qualification.

The accepted 0.1.1 recovery imported build 3396210 with all 125,116 indexed
resources in 6 minutes 14 seconds, peaking at 150.6 MiB preparation-worker RSS.
Preserve that cache and the existing runtime/prefix. Startup/local login passed
in 0.1.4. Client rendering/input optimization is the current gate; audio and
controller support follow. Detailed
physical evidence is recorded in [the handoff](HANDOFF.md).

## Exact client required

Import a ZIP of the complete EVE 24.01 **build 3396210** shared cache. The ZIP can have one containing folder, for example `SharedCache/`, but must contain exactly one `tq/bin64/exefile.exe` and all of the following under the same cache root:

- `tq/start.ini` identifying `build = 3396210`.
- `tq/bin64/blue.dll`, `launchdarkly_stackless_client_sdk.pyd`, and `exefile.exe` matching the supplied EveJS patch recipes.
- `tq/resfileindex.txt` and `tq/resfileindex_Windows.txt` with every referenced file present.
- The sibling `ResFiles` directory and `index_tranquility.txt`.
- The client's original `cacert.pem` bundles.

The launcher never downloads or redistributes retail client files. A currently available EVE client is not an interchangeable substitute. Android preparation requires the pinned client runtime first because its native ARM64 Python performs ZIP validation, extraction and binary patching.

## Preparation behavior

The ZIP is copied to internal private storage, scanned for unsafe paths, links, encrypted entries, case collisions, file count and uncompressed size limits, then unpacked into a temporary directory. Free space must cover the compressed archive, full staged extraction, the existing client if any, and a 512 MiB reserve. Imports are limited to one million entries and 160 GiB. ZIP CRC is checked during extraction. Both upstream resource indexes are parsed and every referenced asset must exist; unknown index hash/size algorithms are not guessed.

The three binary recipes accept only their exact recorded source hashes or exact known patched variants. Android deliberately does not use the upstream relaxed blue.dll byte-only match. Patches preserve their fixed byte lengths, remove the Authenticode security directory and recalculate the PE checksum. Immutable original backups let repeat validation recompute and compare deterministic outputs. `start.ini` receives loopback and Placebo settings. Existing imported content remains active if staging or validation fails; validated content is promoted atomically. Android cancels the guest process if the operation is interrupted.

After the server generates its current private CA at `server-state/certs/xmpp-ca-cert.pem`, validation checks the certificate with OpenSSL and prepares private client certificate bundles and a dedicated Wine prefix's offline crash preferences. Revalidating after a server certificate change rebuilds bundles from the original backup. This neither changes Android/system trust nor claims Wine CryptoAPI trust has passed. `launch-policy.json` records the eventual local executable path, resource cache, proxy endpoints and launch arguments, with `launch_enabled = false`.

## Bounded preparation and interrupted-import recovery

From 0.1.1, preparation has a 512 MiB Python address-space limit and Android
free-memory monitoring. Binary sizes are checked before reading; index rows and
metadata have size bounds. Unique resource names are stored in a temporary
SQLite table with a 2 MiB page cache. Resource shards are checked once, every
unique indexed file must be a regular file, and ZIP metadata is released before
resource/binary validation. Exact supported hashes and deterministic PE patches
are unchanged.

The private ZIP is atomically copied and retained on failure. **Resume interrupted
client import** uses it without another copy. A partial stage left by 0.1.0 is
reused only after streaming ZIP CRC/size checks. New complete extractions have a
private recovery receipt; restart can retry validation directly. Staging remains
inactive until all checks pass. Server sessions must be stopped for preparation.
Worker RSS/peak RSS, stage counts and system/app memory samples go into the
support export. A memory pause preserves recovery data rather than completing
an unqualified import.

## Wine / FEX execution probe

Client runtime installation fetches only the exact UO launcher `v0.2.0` binaries and manifest:

| Asset | SHA-256 |
| --- | --- |
| `client-runtime-arm64.tar.gz` | `f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e` |
| `client-runtime-manifest.json` | `d375adf23b621f83ef7b5fff95365312377399704abb486fd8d4164a1fe29a13` |

The manifest/rootfs marker must identify `format=2`, `architecture=arm64`, `runtime=fex-arm64ec-1`. Wine and wineserver must be native ARM64 ELF executables. Translator rebuilding is deliberately outside this pass.

The headless probe initializes the private prefix and executes an original deterministic x64 PE generated by `client_prepare.py`. Its entry point calls `ExitProcess(37)` through kernel32. Seeing exit 37 establishes that Wine executed x64 instructions through the translation path. It launches no EVE executable, consumes no retail assets, and contacts no EVE endpoint. Host tests validate the PE's header/import table/entry bytes, while execution on the actual Thor remains a device gate. Logs and the receipt are written to private `client-state/logs/client-probe.log` and `probe.json`.

Before claiming client startup/login, qualify Wine CryptoAPI and client CA trust,
localhost port 443 TLS behavior, outbound traffic containment and the minimum
display/input bridge. The server currently checks its local gateway on port 26003;
that is not evidence that the patched client's direct localhost:443 requests work.
Then qualify DX11/Turnip rendering, station/space transitions, controls/audio and
save/reopen. Preserve the already accepted server, probe and import results.

## Supervised startup in 0.1.2

`client_runtime.py` binds the existing prepared content at `/client`, preserves the
private prefix and requires the accepted exact client/probe receipts. It checks
the current binaries and CA without repeating the complete asset-cache scan.
It launches a private TigerVNC display, a foreground Wine server, the original
x64 trust helper, then EVE. Startup readiness observes a live process and display
for five seconds; it never claims successful authentication or gameplay.

The helper imports the current CA into that prefix's CurrentUser ROOT store,
closes/reopens it for persisted readback, verifies its chain, then requests
`https://localhost/health` through WinHTTP with no proxy and default certificate
checks. It verifies the peer chain's exact root and the local offline response.
Wine's `certutil` is a stub in the pinned build, so its exit status is not used as
trust evidence. The helper is built from `native/eve-client-gate.c`.

0.1.4 includes a session-only crypt32 overlay compiled from the exact pinned
Wine source/toolchain. The excluded directoryName comparison now skips an absent
subject, as required for the server's SAN-only leaf. DNS/IP and nonempty-subject
constraints remain enforced, including a correction to accumulated permitted
name-form detection across mixed DNS/IP subtrees. The launcher checks installed baseline hashes and
binds the two patched modules over their existing builtin paths; `crypt32=b`
ensures the gate and EVE use them. The runtime archive, CA and Wine prefix are
preserved. The guest verifies bound hashes and records `wine-trust-overlay.json`.
The separate Wine regression uses disposable certificates/prefixes to reproduce
the baseline bug and check valid and invalid trust cases.

The APK's opt-in PRoot `--eve-client-network` policy validates native socket
syscalls for the supervisor and all descendants. It restricts IP destinations to
loopback, rewrites wildcard binds to loopback and maps localhost:443 to port 26003,
including IPv6 mapped loopback. Direct syscall denial is checked before Wine is
started. Import/probe/server processes do not enable this option.

The performance preview uses native ARM64EC DXVK 2.5.3 and Turnip 26 on Adreno,
with a 1280×720 touch/text RFB display and explicit WineD3D/llvmpipe recovery.
The existing Wine/FEX runtime remains installed. See [graphics qualification and
measurement limits](CLIENT-PERFORMANCE.md). The service retains foreground ownership across Activity changes.
PID/start-time journals protect cleanup/recovery; child logs rotate at 8 MiB with
two previous copies, and memory reserve checks stop before available RAM falls
below 1 GiB. Support ZIPs include session/trust/startup receipts and bounded logs.

Use [the current physical test sequence](TESTING.md). Imported content and world
state remain in their existing private locations. A direct TLS/proxy environment
configuration in the preparation policy is still not itself proof; actual startup
requires the independent native network and Wine TLS gates.

## Source and licenses

The flat JSON patch recipes in `backend/` are unmodified copies from the user's `EveJS-v0.12.9.zip`, `tools/ClientSETUP/`, licensed under the supplied GNU AGPLv3. The Python PE patch behavior adapts that release's `blue_dll_patch.ps1`; the resource gate follows its `scripts/Test-EvEJSResources.ps1`. The server source and license are retained in the repository's vendor snapshot. No CCP executable or game asset is committed.

Pinned Wine/FEX runtime binaries and their corresponding source assets remain available together at [UO launcher v0.2.0](https://github.com/Russianranger/uo-android-launcher/releases/tag/v0.2.0), including `wine-arm64ec-source.tar.gz` and `fex-2510-source-with-submodules.tar.gz`. Their runtime provenance and notices remain inside that rootfs and in the upstream release. This integration reuses those files unchanged.
