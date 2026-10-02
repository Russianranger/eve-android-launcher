# syntax=docker/dockerfile:1
# Build on a native Linux ARM64 runner. Never publish a QEMU-qualified runtime.
ARG NODE_IMAGE=node:24-bookworm-slim
ARG RUST_IMAGE=rust:1.95-bookworm

FROM ${RUST_IMAGE} AS rust-build
ENV CARGO_TARGET_DIR=/build/target
WORKDIR /build/vendor/evejs
COPY vendor/evejs/externalservices/market-server externalservices/market-server
COPY vendor/evejs/tools/market-seed tools/market-seed
RUN test "$(uname -m)" = aarch64 \
 && cargo build --locked --release --manifest-path externalservices/market-server/Cargo.toml \
 && cargo build --locked --release --manifest-path tools/market-seed/Cargo.toml \
 && mkdir -p /export/rust \
 && cargo vendor --locked --versioned-dirs --manifest-path externalservices/market-server/Cargo.toml \
      --sync tools/market-seed/Cargo.toml /export/rust/vendor > /export/rust/config.toml \
 && rustc --version > /export/rust/toolchain.txt

FROM ${NODE_IMAGE} AS node-build
ENV DEBIAN_FRONTEND=noninteractive
RUN test "$(uname -m)" = aarch64 \
 && apt-get update \
 && apt-get install --yes --no-install-recommends g++ make python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/evejs
COPY vendor/evejs/package.json vendor/evejs/package-lock.json ./
RUN npm ci --omit=dev
WORKDIR /opt/evejs/server
COPY vendor/evejs/server/package.json vendor/evejs/server/package-lock.json ./
# Force source compilation, including SQLite, for the exact Node ABI and ARM64.
RUN npm_config_build_from_source=true npm ci --omit=dev \
 && node -e 'const D=require("better-sqlite3");const db=new D(":memory:");if(process.arch!=="arm64"||db.prepare("select 42 as answer").get().answer!==42)process.exit(1);db.close()'

FROM node-build AS seed-build
RUN apt-get update \
 && apt-get install --yes --no-install-recommends curl unzip \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/evejs
COPY vendor/evejs ./
COPY --from=rust-build /build/target/release/market-seed /usr/local/bin/market-seed
COPY --from=rust-build /build/target/release/market-server /usr/local/bin/market-server
COPY server-runtime /build-tools
RUN bash /build-tools/build-seed.sh

FROM ${NODE_IMAGE} AS runtime
ENV DEBIAN_FRONTEND=noninteractive
RUN test "$(uname -m)" = aarch64 \
 && apt-get update \
 && apt-get upgrade --yes \
 && apt-get install --yes --no-install-recommends python3 ca-certificates openssl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/evejs
COPY vendor/evejs ./
COPY --from=node-build /opt/evejs/node_modules node_modules
COPY --from=node-build /opt/evejs/server/node_modules server/node_modules
COPY --from=rust-build /build/target/release/market-server /usr/local/bin/market-server
COPY --from=rust-build /build/target/release/market-seed /usr/local/bin/market-seed
COPY --from=seed-build /opt/evejs-seed /opt/evejs-seed
COPY server-runtime/THIRD-PARTY-NOTICES.md /usr/share/eve-android/THIRD-PARTY-NOTICES.md
COPY server-runtime/write-marker.py /tmp/write-marker.py
RUN mkdir -p /state /tmp /root /opt/eve-android \
 && chmod 1777 /tmp \
 && python3 /tmp/write-marker.py \
 && rm /tmp/write-marker.py
ENV LANG=C.UTF-8 NODE_ENV=production
CMD ["python3", "/opt/eve-android/server_runtime.py", "start"]

# The source artifact is published beside every binary runtime. It deliberately
# contains source packages for the exact Debian package versions in runtime.
FROM runtime AS source-build
COPY --from=rust-build /export/rust /export/sources/rust
COPY server-runtime /export/sources/server-runtime
COPY scripts /export/sources/scripts
COPY tests /export/sources/tests
COPY docs /export/sources/docs
COPY backend /export/sources/backend
COPY vendor/evejs-source.tar.gz.part* /export/sources/vendor/
COPY server-runtime/collect-sources.py /tmp/collect-sources.py
RUN python3 /tmp/collect-sources.py /export/sources

FROM scratch AS corresponding-source
COPY --from=source-build /export/sources /sources
