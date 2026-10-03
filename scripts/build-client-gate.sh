#!/usr/bin/env bash
# Build only the original qualification helper; reuse the pinned Wine/FEX runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${EVE_CLIENT_GATE_CC:=x86_64-w64-mingw32-gcc}"
"$EVE_CLIENT_GATE_CC" -O2 -Wall -Wextra -Werror -municode -static-libgcc \
    -Wl,--no-insert-timestamp native/eve-client-gate.c -lcrypt32 -lwinhttp \
    -o backend/eve-client-gate.exe
