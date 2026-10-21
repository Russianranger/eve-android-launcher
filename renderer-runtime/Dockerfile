# Build our KGSL ICD from an unmodified, hashed official Mesa source release.
# Bookworm matches the pinned client rootfs; never use an Android/bionic ICD here.
FROM debian:bookworm-slim AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils build-essential pkg-config ninja-build \
    python3 python3-venv python3-mako python3-yaml python3-packaging \
    bison flex glslang-tools zlib1g-dev libexpat1-dev \
    libx11-dev libx11-xcb-dev libxcb1-dev libxcb-dri3-dev \
    libxcb-present-dev libxcb-shm0-dev libxcb-xfixes0-dev libxcb-randr0-dev \
    libxshmfence-dev \
 && python3 -m venv --system-site-packages /build-tools \
 && /build-tools/bin/pip install --no-cache-dir meson==1.8.5 \
 && mkdir -p /sources /src /renderer/lib /renderer/dxvk /renderer/licenses
ENV PATH=/build-tools/bin:$PATH
RUN curl -fL --retry 3 https://archive.mesa3d.org/mesa-25.2.8.tar.xz -o /sources/mesa-25.2.8.tar.xz \
 && echo '097842f3e49d996868b38688db87b006f7d4541e93ce86d2f341d8b3e7be7c93  /sources/mesa-25.2.8.tar.xz' | sha256sum -c - \
 && tar --no-same-owner -xJf /sources/mesa-25.2.8.tar.xz -C /src \
 && curl -fL --retry 3 https://github.com/doitsujin/dxvk/releases/download/v2.7.1/dxvk-2.7.1.tar.gz -o /sources/dxvk-2.7.1.tar.gz \
 && echo 'd85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87  /sources/dxvk-2.7.1.tar.gz' | sha256sum -c - \
 && tar --no-same-owner -xzf /sources/dxvk-2.7.1.tar.gz -C /src \
 && curl -fL --retry 3 https://github.com/doitsujin/dxvk/archive/refs/tags/v2.7.1.tar.gz -o /sources/dxvk-2.7.1-source.tar.gz \
 && echo '4966be884da4a1ded7e38ee018caef5626bd06bbd0853715084b1a1644aaaf02  /sources/dxvk-2.7.1-source.tar.gz' | sha256sum -c -
RUN meson setup /mesa-build /src/mesa-25.2.8 --prefix=/opt/eve-renderer --libdir=lib \
      --buildtype=release --wrap-mode=nofallback -Db_ndebug=true -Dcpp_link_args='-static-libstdc++ -static-libgcc' \
      -Dplatforms=x11 -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
      -Dgallium-drivers= -Dllvm=disabled -Dglx=disabled -Degl=disabled \
      -Dopengl=false -Dgles1=disabled -Dgles2=disabled -Dgbm=disabled \
      -Dbuild-tests=false -Dvalgrind=disabled -Dzlib=enabled -Dzstd=disabled \
 && meson compile -C /mesa-build -j 4 \
 && cp /mesa-build/src/freedreno/vulkan/libvulkan_freedreno.so /renderer/lib/ \
 && strip --strip-unneeded /renderer/lib/libvulkan_freedreno.so \
 && ldd /renderer/lib/libvulkan_freedreno.so > /sources/renderer-ldd.txt \
 && ! grep -q 'not found' /sources/renderer-ldd.txt \
 && ! grep -q 'libdrm' /sources/renderer-ldd.txt \
 && cp /src/dxvk-2.7.1/x64/d3d11.dll /src/dxvk-2.7.1/x64/dxgi.dll /renderer/dxvk/ \
 && cp /src/mesa-25.2.8/docs/license.rst /renderer/licenses/mesa-license.rst \
 && tar --format=gnu --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -C /src/mesa-25.2.8 -czf /renderer/licenses/mesa-licenses.tar.gz licenses \
 && tar -xOf /sources/dxvk-2.7.1-source.tar.gz dxvk-2.7.1/LICENSE > /renderer/licenses/dxvk-LICENSE \
 && cp /usr/share/doc/gcc-12-base/copyright /renderer/licenses/gcc-copyright \
 && dpkg-query -W > /sources/debian-packages.txt \
 && gcc --version > /sources/compiler.txt \
 && meson --version > /sources/meson.txt \
 && cp /sources/debian-packages.txt /sources/compiler.txt /sources/meson.txt /renderer/licenses/ \
 && printf '{"file_format_version":"1.0.0","ICD":{"library_path":"lib/libvulkan_freedreno.so","api_version":"1.4.0"}}\n' > /renderer/turnip_icd.json
COPY renderer-runtime/Dockerfile scripts/build-client-renderer.sh scripts/package-client-renderer.py /sources/build/
FROM scratch AS renderer
COPY --from=builder /renderer/ /renderer/
FROM scratch AS corresponding-source
COPY --from=builder /sources/ /sources/
