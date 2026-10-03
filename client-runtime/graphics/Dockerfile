# Reuse the qualified Wine trust image's pinned llvm-mingw20250920 and /opt/wine.
# No runtime rootfs rebuild or Wine/FEX version change.
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
COPY client-runtime/graphics/Dockerfile scripts/build-client-graphics.sh /graphics-recipe/
RUN cp -R /graphics-recipe /graphics-src/recipe \
 && cp /graphics-tests/native/eve-d3d11-probe.c /graphics-src/recipe/ \
 && cp /graphics-tests/graphics_present.py /graphics-tests/scripts/build-client-graphics-probe.sh /graphics-src/recipe/ \
 && cp /graphics-build/meson-logs/meson-log.txt /graphics-src/recipe/ \
 && tar --exclude=.git --sort=name --owner=0 --group=0 --numeric-owner \
      -czf /graphics-out/client-graphics-corresponding-source.tar.gz -C /graphics-src . \
 && rm -rf /graphics-out/download-cache

FROM builder AS qualification
ENV WINEPREFIX=/graphics-regression-prefix WINEARCH=win64 WINEDEBUG=-all,err+all \
    WINEDLLOVERRIDES="winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n;d3dcompiler_47,crypt32=b" \
    WINEESYNC=0 WINEFSYNC=0 FEX_DISABLETELEMETRY=1 MESA_VK_WSI_DEBUG=sw
CMD ["/bin/true"]
