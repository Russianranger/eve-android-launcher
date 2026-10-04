#!/usr/bin/env bash
# Build the original launcher and CI-only GUI child with the pinned toolchain.
set -euo pipefail
window_repo=$(cd "$(dirname "$0")/.." && pwd)
: "${EVE_CLIENT_WINDOW_CC:=x86_64-w64-mingw32-gcc}"
window_output=${1:-"$window_repo/backend"}
if [[ $# -gt 1 ]]; then
    echo 'Usage: build-client-window.sh [output-directory]' >&2
    exit 2
fi
mkdir -p "$window_output"
"$EVE_CLIENT_WINDOW_CC" -std=c11 -O2 -Wall -Wextra -Werror -municode -mconsole \
    -static-libgcc -Wl,--no-insert-timestamp \
    "$window_repo/native/eve-client-window.c" -luser32 \
    -o "$window_output/eve-client-window.exe"
"$EVE_CLIENT_WINDOW_CC" -std=c11 -O2 -Wall -Wextra -Werror -municode -mwindows \
    -static-libgcc -Wl,--no-insert-timestamp \
    "$window_repo/native/eve-client-window-fixture.c" -luser32 -lgdi32 -lshell32 \
    -o "$window_output/eve-client-window-fixture.exe"
