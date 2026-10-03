#!/usr/bin/env bash
# Build the original x64 probe with the existing qualification toolchain.
set -euo pipefail
graphics_repo=$(cd "$(dirname "$0")/.." && pwd)
: "${EVE_CLIENT_GRAPHICS_CC:=x86_64-w64-mingw32-gcc}"
graphics_output=${1:-"$graphics_repo/backend/eve-d3d11-probe.exe"}
if [[ $# -gt 1 ]]; then
    echo 'Usage: build-client-graphics-probe.sh [output-exe]' >&2
    exit 2
fi
mkdir -p "$(dirname "$graphics_output")"
"$EVE_CLIENT_GRAPHICS_CC" -std=c11 -O2 -Wall -Wextra -Werror -municode \
    -static-libgcc -Wl,--no-insert-timestamp \
    "$graphics_repo/native/eve-d3d11-probe.c" -ladvapi32 -luser32 \
    -o "$graphics_output"
