#!/usr/bin/env bash
set -euo pipefail
proot_path= loader_path= output_path=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --proot) proot_path="$2"; shift 2;;
    --loader) loader_path="$2"; shift 2;;
    --output) output_path="$2"; shift 2;;
    *) echo 'Expected --proot PATH --loader PATH --output PATH' >&2; exit 2;;
  esac
done
[[ -x "$proot_path" && -f "$loader_path" && -n "$output_path" ]]
script_dir="$(cd "$(dirname "$0")" && pwd)"
if [[ -f /graphics-tests/native/eve-x11-shm-probe.c ]]; then
  native_dir=/graphics-tests/native
  checker=/graphics-tests/tests/check_x11_shm_rfb.py
  observer=/graphics-tests/graphics_present.py
else
  native_dir="$(cd "$script_dir/../native" && pwd)"
  checker="$script_dir/../tests/check_x11_shm_rfb.py"
  observer="$script_dir/../backend/graphics_present.py"
fi
mkdir -p "$(dirname "$output_path")"
output_dir="$(cd "$(dirname "$output_path")" && pwd)"
output_path="$output_dir/$(basename "$output_path")"
probe="$output_dir/shm-native-probe"
"${CC:-cc}" -std=c11 -D_POSIX_C_SOURCE=200809L -O2 -Wall -Wextra -Werror -pedantic -pthread \
  "$native_dir/eve-x11-shm-probe.c" -lxcb -o "$probe"
proot_tmp="$(mktemp -d /tmp/eve-shm-proot-XXXXXX)"
trap 'rm -rf "$proot_tmp"' EXIT
result=0
env -u PROOT_NO_SECCOMP -u EVE_X11_SHM_STAGING \
  PROOT_LOADER="$loader_path" PROOT_TMP_DIR="$proot_tmp" TRASC_PROOT_REPORT=1 \
  "$proot_path" --kill-on-exit --sysvipc -0 -r / -b /proc -b /dev -w / \
  /usr/bin/python3 "$checker" --probe "$probe" --observer "$observer" --output "$output_path" \
  > "$output_dir/shm-proot.log" 2>&1 || result=$?
python3 - "$output_path" "$output_dir/shm-proot.log" "$result" <<'PY'
import json
from pathlib import Path
import sys
path, log = map(Path, sys.argv[1:3])
if not path.is_file():
    raise SystemExit('SHM guest fixture did not write a report; inspect shm-proot.log')
report = json.loads(path.read_text())
report['memfdAllocationVerified'] = 'TRASC PRoot: SysV shared memory uses memfd' in log.read_text(errors='replace')
report['passed'] = report.get('passed') is True and report['memfdAllocationVerified'] and sys.argv[3] == '0'
path.write_text(json.dumps(report, indent=2) + '\n')
if not report['passed']:
    raise SystemExit('Production PRoot SHM fixture failed; inspect shm diagnostics')
print('Production PRoot + Xvnc SHM: three RGB/RFB frames, reuse, resize, teardown and failure controls passed')
PY
