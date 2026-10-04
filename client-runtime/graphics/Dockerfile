# Reuse the qualified Wine trust image's pinned llvm-mingw20250920 and /opt/wine.
# No runtime rootfs rebuild or Wine/FEX version change.
# DXVK 2.4.1 retains per-submit fences instead of the 2.5 timeline queue that
# regresses on Turnip's emulated KGSL timelines. Build the unmodified source.
ARG BUILDER_IMAGE=eve-wine-trust-overlay:local
FROM ${BUILDER_IMAGE} AS builder
RUN test "$(uname -m)" = aarch64 \
 && apt-get update && apt-get install -y --no-install-recommends \
      meson ninja-build glslang-tools mesa-vulkan-drivers tigervnc-standalone-server \
      libzstd1 libxcb-randr0 libxcb-xfixes0 libx11-xcb1
COPY client-runtime/graphics/fetch-sources.py /graphics-recipe/fetch-sources.py
COPY client-runtime/graphics/arm64ec.txt /graphics-recipe/arm64ec.txt
COPY backend/pe_image.py /graphics-recipe/
RUN python3 /graphics-recipe/fetch-sources.py fetch /graphics-src /graphics-out \
 && cd /graphics-src/dxvk \
 && meson setup /graphics-build --cross-file /graphics-recipe/arm64ec.txt \
      --buildtype release --wrap-mode=forcefallback --strip -Db_ndebug=if-release \
      --prefix /graphics-install --bindir arm64ec --libdir arm64ec \
      -Denable_d3d8=false -Denable_d3d9=false -Denable_d3d10=false \
 && ninja -C /graphics-build -j4 install \
 && cp /graphics-install/arm64ec/d3d11.dll /graphics-out/assets/dxvk-d3d11-arm64ec.dll \
 && cp /graphics-install/arm64ec/dxgi.dll /graphics-out/assets/dxvk-dxgi-arm64ec.dll
# Runtime bundle manifest validation/hashes are a separate Python step shared
# with APK validation; linked ARM64EC uses AMD64+CHPE metadata, NOT machineA641.
COPY native/eve-d3d11-probe.c /graphics-tests/native/
COPY scripts/build-client-graphics-probe.sh /graphics-tests/scripts/
RUN bash /graphics-tests/scripts/build-client-graphics-probe.sh /graphics-out/assets/eve-d3d11-probe.exe \
 && python3 /graphics-recipe/fetch-sources.py manifest /graphics-out/assets \
 && cp /graphics-out/assets/client-graphics-bundle.json /graphics-src/provenance-build.json \
 && python3 /graphics-recipe/fetch-sources.py runtime-identity /graphics-out/qualified-runtime-identity.json \
 && cp /graphics-out/qualified-runtime-identity.json /graphics-src/
COPY backend/graphics_present.py /graphics-tests/graphics_present.py
COPY native/eve-client-window.c native/eve-client-window-fixture.c /graphics-tests/native/
COPY scripts/check-client-window-runtime.py scripts/build-client-window.sh /graphics-tests/scripts/
RUN EVE_CLIENT_WINDOW_CC=/toolchain/bin/x86_64-w64-mingw32-clang \
      bash /graphics-tests/scripts/build-client-window.sh /graphics-out/window-build \
 && mv /graphics-out/window-build/eve-client-window.exe /graphics-out/assets/ \
 && mv /graphics-out/window-build/eve-client-window-fixture.exe /graphics-out/ \
 && rmdir /graphics-out/window-build
COPY client-runtime/graphics/Dockerfile scripts/build-client-graphics.sh /graphics-recipe/
RUN cp -R /graphics-recipe /graphics-src/recipe \
 && cp /graphics-tests/native/eve-d3d11-probe.c /graphics-src/recipe/ \
 && cp /graphics-tests/graphics_present.py /graphics-tests/scripts/build-client-graphics-probe.sh /graphics-src/recipe/ \
 && cp /graphics-tests/native/eve-client-window*.c /graphics-tests/scripts/check-client-window-runtime.py \
      /graphics-tests/scripts/build-client-window.sh /graphics-src/recipe/ \
 && cp /graphics-build/meson-logs/meson-log.txt /graphics-src/recipe/ \
 && tar --exclude=.git --sort=name --owner=0 --group=0 --numeric-owner \
      -czf /graphics-out/client-graphics-corresponding-source.tar.gz -C /graphics-src . \
 && rm -rf /graphics-out/download-cache

FROM builder AS qualification
ENV WINEPREFIX=/graphics-regression-prefix WINEARCH=win64 WINEDEBUG=-all,err+all \
    WINEDLLOVERRIDES="winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n;d3dcompiler_47,crypt32=b" \
    WINEESYNC=0 WINEFSYNC=0 FEX_DISABLETELEMETRY=1 MESA_VK_WSI_DEBUG=sw
CMD ["/bin/true"]
