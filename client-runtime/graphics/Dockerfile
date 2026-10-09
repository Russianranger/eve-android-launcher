# Reuse the qualified Wine trust image's pinned llvm-mingw20250920 and /opt/wine.
# No runtime rootfs rebuild or Wine/FEX version change.
# DXVK 2.4.1 retains per-submit fences instead of the 2.5 timeline queue that
# regresses on Turnip's emulated KGSL timelines. Build the unmodified source.
ARG BUILDER_IMAGE=eve-wine-trust-overlay:local
FROM ${BUILDER_IMAGE} AS builder
RUN test "$(uname -m)" = aarch64 \
 && apt-get update && apt-get install -y --no-install-recommends \
      meson ninja-build glslang-tools mesa-vulkan-drivers tigervnc-standalone-server \
      libzstd1 libxcb-randr0 libxcb-xfixes0 libx11-xcb1 python3-pip \
      python3-mako python3-yaml python3-packaging libexpat1-dev zlib1g-dev libzstd-dev \
      libx11-xcb-dev libxcb-dri3-dev libxcb-present-dev libxcb-randr0-dev \
      libxcb-shm0-dev libxcb-sync-dev libxcb-xfixes0-dev libxshmfence-dev
COPY client-runtime/graphics/fetch-sources.py /graphics-recipe/fetch-sources.py
COPY client-runtime/graphics/arm64ec.txt /graphics-recipe/arm64ec.txt
COPY client-runtime/graphics/a740-pc-mode.patch native/a740-driver-probe.c /graphics-recipe/
COPY client-runtime/graphics/x11-shm-staging.patch native/eve-x11-shm-staging.h \
     native/eve-x11-shm-probe.c /graphics-recipe/
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
# Build an additional glibc/KGSL driver from exactly Mesa 26.0.0 plus the one
# A740 register backport. The immutable original Turnip stays the default.
# Keep build tools at the versions in the baseline's corresponding recipe.
RUN pip3 install --break-system-packages cmake==3.31.6 meson==1.5.2 \
 && /usr/local/bin/cmake -S /graphics-src/glslang-a740/glslang-15.1.0 -B /graphics-glslang-build \
      -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_OPT=OFF -DBUILD_TESTING=OFF -DGLSLANG_TESTS=OFF \
 && /usr/local/bin/cmake --build /graphics-glslang-build --parallel 2 \
 && /usr/local/bin/cmake --install /graphics-glslang-build \
 && /usr/local/bin/meson setup /graphics-mesa-a740-build /graphics-src/mesa-a740/mesa-26.0.0 \
      --buildtype=release -Dplatforms=x11 -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
      -Dgallium-drivers= -Dglx=disabled -Degl=disabled -Dgbm=disabled \
      -Dopengl=false -Dgles1=disabled -Dgles2=disabled -Dllvm=disabled \
      -Dvideo-codecs= -Dbuild-tests=false \
 && ninja -C /graphics-mesa-a740-build -j2 \
 && cp /graphics-mesa-a740-build/src/freedreno/vulkan/libvulkan_freedreno.so \
      /graphics-out/assets/turnip-26.0.0-a740-pc-mode.so \
 && /usr/bin/strip /graphics-out/assets/turnip-26.0.0-a740-pc-mode.so \
 && /usr/bin/cc -std=c11 -D_GNU_SOURCE -O2 -Wall -Wextra -Werror \
      /graphics-recipe/a740-driver-probe.c -lvulkan -o /graphics-out/assets/a740-driver-probe \
 && /usr/bin/strip /graphics-out/assets/a740-driver-probe \
 && ldd /graphics-out/assets/turnip-26.0.0-a740-pc-mode.so \
 && ldd /graphics-out/assets/a740-driver-probe
# This second optional driver is independently built from pristine Mesa 26.0.0
# with only the X11 software-WSI staging patch. No A740 register patch is mixed
# in, and the unchanged original Turnip remains the default asset.
RUN /usr/local/bin/meson setup /graphics-mesa-shm-build /graphics-src/mesa-shm/mesa-26.0.0 \
      --buildtype=release -Dplatforms=x11 -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
      -Dgallium-drivers= -Dglx=disabled -Degl=disabled -Dgbm=disabled \
      -Dopengl=false -Dgles1=disabled -Dgles2=disabled -Dllvm=disabled \
      -Dvideo-codecs= -Dbuild-tests=false \
 && ninja -C /graphics-mesa-shm-build -j2 \
 && cp /graphics-mesa-shm-build/src/freedreno/vulkan/libvulkan_freedreno.so \
      /graphics-out/assets/turnip-26.0.0-x11-shm.so \
 && /usr/bin/strip /graphics-out/assets/turnip-26.0.0-x11-shm.so \
 && ldd /graphics-out/assets/turnip-26.0.0-x11-shm.so
# Runtime bundle manifest validation/hashes are a separate Python step shared
# with APK validation; linked ARM64EC uses AMD64+CHPE metadata, NOT machineA641.
COPY native/eve-d3d11-probe.c /graphics-tests/native/
COPY scripts/build-client-graphics-probe.sh /graphics-tests/scripts/
RUN bash /graphics-tests/scripts/build-client-graphics-probe.sh /graphics-out/assets/eve-d3d11-probe.exe \
 && python3 /graphics-recipe/fetch-sources.py manifest /graphics-out/assets \
 && cp /graphics-out/assets/client-graphics-bundle.json /graphics-src/provenance-build.json \
 && cp /graphics-out/a740-link-compatibility.json /graphics-src/ \
 && cp /graphics-out/shm-link-compatibility.json /graphics-src/ \
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
COPY scripts/check-x11-shm-host.sh /graphics-tests/scripts/
COPY tests/check_x11_shm_rfb.py /graphics-tests/tests/
RUN cp -R /graphics-recipe /graphics-src/recipe \
 && cp /graphics-tests/native/eve-d3d11-probe.c /graphics-src/recipe/ \
 && cp /graphics-tests/graphics_present.py /graphics-tests/scripts/build-client-graphics-probe.sh /graphics-src/recipe/ \
 && cp /graphics-tests/native/eve-client-window*.c /graphics-tests/scripts/check-client-window-runtime.py \
      /graphics-tests/scripts/build-client-window.sh /graphics-src/recipe/ \
 && cp /graphics-build/meson-logs/meson-log.txt /graphics-src/recipe/ \
 && cp /graphics-mesa-a740-build/meson-logs/meson-log.txt /graphics-src/recipe/mesa-a740-meson-log.txt \
 && cp /graphics-mesa-shm-build/meson-logs/meson-log.txt /graphics-src/recipe/mesa-shm-meson-log.txt \
 && cp /graphics-tests/scripts/check-x11-shm-host.sh /graphics-tests/tests/check_x11_shm_rfb.py /graphics-src/recipe/ \
 && mkdir -p /graphics-tests/native-proot /graphics-tests/native \
 && cp /graphics-recipe/eve-x11-shm-staging.h /graphics-recipe/eve-x11-shm-probe.c /graphics-tests/native/ \
 && tar --exclude=.git --sort=name --owner=0 --group=0 --numeric-owner \
      -czf /graphics-out/client-graphics-corresponding-source.tar.gz -C /graphics-src . \
 && rm -rf /graphics-out/download-cache

FROM builder AS qualification
ENV WINEPREFIX=/graphics-regression-prefix WINEARCH=win64 WINEDEBUG=-all,err+all \
    WINEDLLOVERRIDES="winemenubuilder,mshtml,mscoree=;d3d11,dxgi=n;d3dcompiler_47,crypt32=b" \
    WINEESYNC=0 WINEFSYNC=0 FEX_DISABLETELEMETRY=1 MESA_VK_WSI_DEBUG=sw
CMD ["/bin/true"]
