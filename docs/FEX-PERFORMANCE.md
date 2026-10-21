# Pinned ARM64EC FEX tuning

The installed `fex-arm64ec-1` runtime comes from the existing pinned UO runtime. Its [Dockerfile at 80859342](https://github.com/Russianranger/uo-android-launcher/blob/80859342ae2e8cf3cdcfad508d94b5d76774d379/client-runtime/Dockerfile) builds FEX at `320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab` (FEX-2510), including its ARM64EC and AArch64 DLLs.

This is the Windows DLL configuration path, rather than the native Linux FEX launcher: [`Source/Windows/ARM64EC/Module.cpp`](https://github.com/FEX-Emu/FEX/blob/320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab/Source/Windows/ARM64EC/Module.cpp) calls `LoadConfig(exepath, _environ, ReadPortabilityInformation)` during `ProcessInit`. [`Source/Common/Config.cpp`](https://github.com/FEX-Emu/FEX/blob/320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab/Source/Common/Config.cpp) installs the environment loader after the main/application/file override layers. It maps the `FEX_` prefix plus the generated option name; these switches do not use Wine registry values.

The same source supports JSON configuration. On Windows its home lookup first uses `WINEHOMEDIR`, then `LOCALAPPDATA`, then `.`. Configuration paths also honor `FEX_APP_CONFIG_LOCATION` or `XDG_CONFIG_HOME`; otherwise the home path is followed by `/.fex-emu/`. The launcher uses a bounded environment allowlist to avoid creating additional configuration files or relying on those Windows paths.

`client-state/performance.json` accepts this optional `fex` object:

| JSON boolean | Environment option | Pinned source default |
| --- | --- | --- |
| `multiblock` | `FEX_MULTIBLOCK` | `true` |
| `x87ReducedPrecision` | `FEX_X87REDUCEDPRECISION` | `false` |
| `tsoEnabled` | `FEX_TSOENABLED` | `true` |
| `vectorTsoEnabled` | `FEX_VECTORTSOENABLED` | `false` |
| `memcpySetTsoEnabled` | `FEX_MEMCPYSETTSOENABLED` | `false` |
| `halfBarrierTsoEnabled` | `FEX_HALFBARRIERTSOENABLED` | `true` |

Defaults are verified in [`FEXCore/Source/Interface/Config/Config.json.in`](https://github.com/FEX-Emu/FEX/blob/320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab/FEXCore/Source/Interface/Config/Config.json.in). The launcher default is an empty `fex` object: it preserves the pinned runtime behavior and adds no relaxed TSO overrides. Every inherited `FEX_*` variable is removed; only explicitly requested valid booleans are emitted as `0` or `1`, together with the existing telemetry disable setting. Unknown names or non-booleans reject the whole `fex` object and generate a warning.

For a first isolated FEX comparison, keep every other setting fixed and compare `"fex": {}` against `"fex": {"multiblock": true, "x87ReducedPrecision": true}`. Multiblock is already enabled in the pinned source; explicitly setting it proves the environment path without claiming a gain. Reduced precision changes floating-point behavior. Disabling TSO options or enabling alternative barriers can affect guest memory ordering; leave these experiments until the display and renderer comparisons are complete, change one option at a time, and check stability as well as both display counters. Restart the client after editing the profile.
