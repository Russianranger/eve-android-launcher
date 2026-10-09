# Build only crypt32 from the already installed Wine/FEX runtime's exact source
# and compiler. The runtime itself, FEX and the user's prefix are not upgraded.
# Patch only empty-subject directory exclusion and name-form accumulation across
# mixed DNS/IP permitted constraints; every trust/policy check remains enabled.
FROM debian:bookworm-slim AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git xz-utils build-essential python3 bison flex pkg-config \
    libfreetype-dev libfontconfig-dev libx11-dev libxext-dev libxrender-dev \
    libxrandr-dev libxi-dev libxcursor-dev libxfixes-dev libxinerama-dev \
    libxxf86vm-dev libxcomposite-dev libxdamage-dev libvulkan-dev libgl-dev \
    libgnutls28-dev libasound2-dev libpulse-dev libdbus-1-dev libudev-dev libunwind-dev \
    openssl xvfb xauth python3-cryptography
ARG WINE_COMMIT=a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29
RUN test "$(uname -m)" = aarch64 \
 && curl -fL --retry 3 https://github.com/bylaws/llvm-mingw/releases/download/20250920/llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64.tar.xz -o /tmp/toolchain.tar.xz \
 && echo 'bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d  /tmp/toolchain.tar.xz' | sha256sum -c - \
 && mkdir /toolchain && tar -xJf /tmp/toolchain.tar.xz --strip-components=1 -C /toolchain \
 && rm /tmp/toolchain.tar.xz
ENV PATH=/toolchain/bin:$PATH
RUN git init /src/wine && cd /src/wine \
 && git remote add origin https://github.com/bylaws/wine.git \
 && git fetch --depth 1 origin "$WINE_COMMIT" && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$WINE_COMMIT" \
 && echo 'cf178a128a02340956d4b615ad58e35b3590599730916ebd5bd2763c58c3bc15  dlls/crypt32/chain.c' | sha256sum -c -
COPY native/wine-empty-subject.patch /src/wine-empty-subject.patch
RUN cd /src/wine && git apply --check /src/wine-empty-subject.patch \
 && git apply /src/wine-empty-subject.patch \
 && test "$(git diff --numstat)" = "$(printf '1\t2\tdlls/crypt32/chain.c')" \
 && mkdir /wine-build && cd /wine-build \
 && /src/wine/configure --prefix=/opt/wine --enable-archs=arm64ec,aarch64,i386 --with-mingw=clang --disable-tests \
      --without-wayland --without-gstreamer --without-cups --without-sane --without-gphoto \
 && make -j4 dlls/crypt32/all
# Wine's ARM64X build combines ARM64EC and ARM64 objects in aarch64-windows.
# Keep both architectures at exactly their existing installed paths. Validate
# the PE headers before exporting; do not infer architecture from filenames.
RUN mkdir -p /out/assets /source-provenance \
 && cp /wine-build/dlls/crypt32/aarch64-windows/crypt32.dll /out/assets/wine-crypt32-aarch64.dll \
 && cp /wine-build/dlls/crypt32/i386-windows/crypt32.dll /out/assets/wine-crypt32-i386.dll \
 && cp /wine-build/config.log /source-provenance/wine-build-config.log \
 && cp /src/wine-empty-subject.patch /source-provenance/ \
 && cp /src/wine/COPYING.LIB /source-provenance/Wine-COPYING.LIB
RUN python3 - <<'PY'
import hashlib, json, struct
from pathlib import Path
files = []
for arch, machine, baseline in (
    ('aarch64', 0xaa64, 'b5f63e6d39d720d30a7ba124d1825a58d33a605d722b6e2b874c547c4d22b407'),
    ('i386', 0x14c, 'e03468cad9af9d6a94c6ad1f86191b5412c35f9c1edc246bb1b4ac0bd416d279'),
):
    path = Path('/out/assets') / f'wine-crypt32-{arch}.dll'
    data = path.read_bytes()
    offset = struct.unpack_from('<I', data, 60)[0]
    assert data[:2] == b'MZ' and data[offset:offset + 4] == b'PE\0\0', path
    actual = struct.unpack_from('<H', data, offset + 4)[0]
    assert actual == machine, (path, hex(actual), hex(machine))
    files.append({'asset': path.name, 'target': f'opt/wine/lib/wine/{arch}-windows/crypt32.dll',
                  'sha256': hashlib.sha256(data).hexdigest(), 'machine': actual,
                  'baselineSha256': baseline, 'sizeBytes': len(data)})
manifest = {'format': 1, 'overlay': 'wine-empty-subject-1', 'runtime': 'fex-arm64ec-1',
            'wine_commit': 'a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29',
            'toolchain': 'llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64',
            'toolchainSha256': 'bce5cc755c613515fd44e1ee9523123d854103abae147571adb645450036274d',
            'baselineRuntimeSha256': 'f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e',
            'patchSha256': hashlib.sha256(Path('/src/wine-empty-subject.patch').read_bytes()).hexdigest(),
            'license': 'LGPL-2.1-or-later', 'sourceRepository': 'https://github.com/bylaws/wine',
            'files': files}
text = json.dumps(manifest, indent=2) + '\n'
Path('/out/assets/wine-trust-overlay.json').write_text(text)
Path('/source-provenance/wine-trust-overlay.json').write_text(text)
PY
COPY client-runtime/wine-trust/Dockerfile scripts/build-wine-trust-overlay.sh \
    native/eve-wine-trust-test.c tests/wine_trust_fixtures.py tests/wine_trust_regression.py /source-provenance/
RUN tar --exclude=.git --sort=name --owner=0 --group=0 --numeric-owner \
    -czf /out/wine-trust-corresponding-source.tar.gz -C /src wine -C / source-provenance

# Qualification runs the native ARM64 test helper with the exact already
# qualified runtime. This test-only copy never becomes a runtime update.
FROM builder AS qualification
COPY scripts/check-mesa262-runtime-libraries.py /wine-tests/check-mesa262-runtime-libraries.py
RUN curl -fL --retry 3 https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.0/client-runtime-arm64.tar.gz -o /tmp/baseline.tar.gz \
 && echo 'f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e  /tmp/baseline.tar.gz' | sha256sum -c - \
 && tar -xzf /tmp/baseline.tar.gz -C / opt/wine \
 && python3 /wine-tests/check-mesa262-runtime-libraries.py extract /tmp/baseline.tar.gz /runtime-proof/mesa262-xcb-shm \
 && rm /tmp/baseline.tar.gz
COPY native/eve-wine-trust-test.c /wine-tests/eve-wine-trust-test.c
COPY tests/wine_trust_fixtures.py /wine-tests/wine_trust_fixtures.py
COPY tests/wine_trust_regression.py /wine-tests/wine_trust_regression.py
RUN python3 /wine-tests/wine_trust_fixtures.py /wine-tests/fixtures \
 && aarch64-w64-mingw32-gcc -std=c11 -Os -Wall -Wextra -Werror -municode -static-libgcc \
      -Wl,--no-insert-timestamp /wine-tests/eve-wine-trust-test.c -lcrypt32 \
      -o /wine-tests/eve-wine-trust-test.exe
ENV WINEPREFIX=/wine-regression-prefix WINEARCH=win64 WINEDEBUG=-all,err+all \
    WINEDLLOVERRIDES="winemenubuilder,mshtml,mscoree=;d3d11,dxgi,crypt32=b" \
    WINEESYNC=0 WINEFSYNC=0 FEX_DISABLETELEMETRY=1
# The driver runs these tests in a retained container, rather than a Docker RUN
# layer, so prefix/probe logs survive an initialization or policy-test failure.
CMD ["/bin/true"]
