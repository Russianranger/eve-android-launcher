# Original linked ARM64EC regression fixture

`tiny-ec.c` exports one integer addition and a minimal successful `DllMain`.
`tiny-ec.dll` is compiled solely for parser regression tests. It is never
installed in the runtime or APK.

Reproduction uses the x64-host variant of the existing pinned toolchain:

- Release: https://github.com/bylaws/llvm-mingw/releases/tag/20250920
- Archive: `llvm-mingw-20250920-ucrt-ubuntu-22.04-x86_64.tar.xz`
- Archive SHA256: `8dd8c34fc051a50c2fae86015f35057f8aae93fe1e19b34537ef1269a8b4c772`
- Compiler LLVM commit: `c5668510b7c8a1881d5764d6a67ff253523d21e9`
- Fixture SHA256: `b3752ba8134659ff5c597d793dfd9906757cd21631783f67127ff40a2cc72b3f`
- Fixture size: 26,112 bytes

From the repository root:

```sh
arm64ec-w64-mingw32-clang -shared -O2 -s -Wl,--no-insert-timestamp tests/fixtures/arm64ec/tiny-ec.c -o tests/fixtures/arm64ec/tiny-ec.dll
llvm-readobj --coff-load-config tests/fixtures/arm64ec/tiny-ec.dll
python3 tests/check-arm64ec-parser.py tests/fixtures/arm64ec/tiny-ec.dll
```

The actual compiler emits an ARM64EC range at `0x1004..0x302c`, and an X64
range at `0x4000..0x5020`. The latter crosses the `.text` tail into `.hexpthk`
through exactly the PE SectionAlignment padding. Both code endpoints have
real executable file bytes. This reproduces the first native graphics CI
failure and prevents incorrectly requiring an entire code map range to fit
one raw section.

The compiler's MinGW CRT notices are retained in
`docs/licenses/mingw-w64-copyright.txt`.
