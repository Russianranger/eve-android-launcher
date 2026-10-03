# EVE Android Launcher 0.1.6 — graphics report reader

The 0.1.5 Thor test passed Turnip/Adreno 740 Vulkan presentation, native ARM64EC
D3D11 shader rendering and all three visible display frames. EVE then stopped
before launch because the reader expected compact JSON lines while the saved
display receipt was formatted JSON. 0.1.6 reads the complete receipt and keeps
the existing hardware, native DLL identity, pixel and process checks.

Regression coverage uses the observed display receipt, the actual atomic JSON
writer and formatted reports in supervisor startup/failure tests. Native CI also
runs the production reader on its actual display receipt before packaging.

Update in place and retry with Adreno rendering checked. Preserve the prepared
runtime, client cache, prefix and world. Use a fresh local account; ThorTest stays
retired. Actual GPU EVE performance and input responsiveness still need the next
device test. See [testing instructions](TESTING.md).

# EVE Android Launcher 0.1.5 — client performance

0.1.4 passed private Wine TLS, startup, local login and character selection on
Thor, but CPU rendering made the display and text entry nearly unusable.

This update adds native ARM64EC DXVK 2.5.3 with pinned Turnip 26.0.0 for Adreno,
using the existing Wine/FEX installation. Hardware-only checks verify the native
DLLs, shader pixels and three visible display frames before EVE runs. The initial
30 FPS cap and one-frame queue favor responsiveness. Versioned shader caches
persist; software rendering remains an explicit recovery option.

Text and key taps are sent in batches; pointer motion is coalesced without
losing button releases. Text defaults to replacing the selected field. Supervisor
status uses one process snapshot, and reserve checks read only available memory.
Four socket filters avoid unnecessary exit tracing while retaining the native
loopback/localhost:443 policy, immutable destination copies and sendmmsg copyback.
Support logs add separate CPU, receive/decode, Android presentation and input
latency counters without credentials or screenshots.

Update in place. Preserve runtimes, client cache, prefix and world; no reimport,
revalidation or repeated Wine/FEX probe is needed. Use a fresh local test account
such as EvePerf1; ThorTest is retired. Start server → GPU client → login/character
selection → clean stop → warm-cache repeat → save/stop server → export support ZIP.
See [testing instructions](TESTING.md) and [implementation evidence](CLIENT-PERFORMANCE.md).

Native ARM CI checks graphics interoperability, visible synthetic frames, CPU
rejection, exact assets and real PRoot network syscalls. Actual Thor EVE performance
still requires the next device test; CI results do not establish handheld FPS.
