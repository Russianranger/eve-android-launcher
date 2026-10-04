#!/usr/bin/env bash
# Build the graphics bundle and qualify the native EC path without changing the client runtime.
# Run on the same native ARM64 CI job immediately after the Wine trust build.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
test "$(uname -m)" = aarch64 || { echo 'Client graphics qualification requires native ARM64.' >&2; exit 1; }
docker image inspect eve-wine-trust-overlay:local >/dev/null
mkdir -p out
graphics_container=''
cleanup() {
  if [[ -n "$graphics_container" ]]; then docker rm -f "$graphics_container" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
docker build --platform linux/arm64 --target qualification \
  -f client-runtime/graphics/Dockerfile -t eve-client-graphics:local .
graphics_container=$(docker create --init -i --network none --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined eve-client-graphics:local /bin/bash -s)
qualification_status=0
docker start -ai "$graphics_container" <<'QUALIFICATION' || qualification_status=$?
set -Eeuo pipefail
export DISPLAY=:21
display_pid=''
cleanup_display() {
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -k || true
  if [[ -n "$display_pid" ]]; then kill "$display_pid" || true; fi
}
trap cleanup_display EXIT
/usr/bin/Xtigervnc "$DISPLAY" -geometry 320x240 -depth 24 -rfbport 5991 \
  -localhost yes -SecurityTypes None -nolisten tcp -ac -AlwaysShared \
  -FrameRate 30 -desktop 'EVE graphics fixture' > /graphics-out/xvnc.log 2>&1 &
display_pid=$!
python3 - <<'PY'
from pathlib import Path
import time
for _ in range(100):
    if Path('/tmp/.X11-unix/X21').is_socket():
        break
    time.sleep(0.1)
else:
    raise SystemExit('Xvnc did not create its display socket')
PY
# Initialize a disposable prefix with native Wine builtins; install only the
# newly built EC DLLs after the prefix's system32 targets actually exist.
WINEDLLOVERRIDES='winemenubuilder,mshtml,mscoree=;d3d11,dxgi,crypt32=b' \
  timeout --kill-after=10 180 /opt/wine/bin/wine wineboot -u \
  < /dev/null > /graphics-out/prefix.log 2>&1
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
python3 - <<'PY'
from pathlib import Path
import shutil
prefix = Path('/graphics-regression-prefix/drive_c/windows/system32')
if not prefix.is_dir():
    raise SystemExit('Disposable Wine prefix has no system32')
for name in ('d3d11', 'dxgi'):
    target = prefix / (name + '.dll')
    # Wine's builtin target may be a symlink. Never cp through that symlink.
    target.unlink(missing_ok=True)
    shutil.copyfile(Path('/graphics-out/assets') / ('dxvk-' + name + '-arm64ec.dll'), target)
PY
d3d11_digest=$(sha256sum /graphics-out/assets/dxvk-d3d11-arm64ec.dll | cut -d ' ' -f 1)
dxgi_digest=$(sha256sum /graphics-out/assets/dxvk-dxgi-arm64ec.dll | cut -d ' ' -f 1)
export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.aarch64.json
export VK_ICD_FILENAMES="$VK_DRIVER_FILES"
export DXVK_LOG_LEVEL=info DXVK_LOG_PATH='Z:\graphics-out'
export DXVK_CONFIG_FILE='Z:\graphics-out\dxvk.conf'
export DXVK_STATE_CACHE_PATH='Z:\graphics-out\cache\dxvk-2.4.1-arm64ec'
export MESA_SHADER_CACHE_DIR=/graphics-out/cache/mesa-26.0.0
mkdir -p /graphics-out/cache/dxvk-2.4.1-arm64ec /graphics-out/cache/mesa-26.0.0
cat > /graphics-out/dxvk.conf <<'CONFIG'
# Private initial responsiveness settings.
dxgi.maxFrameRate = 30
dxgi.maxFrameLatency = 1
dxgi.syncInterval = 0
CONFIG
test -f "$VK_DRIVER_FILES"
# This is an explicitly named software CI fixture. A successful result verifies
# x64 -> native EC D3D11/DXGI -> Wine Vulkan -> Xvnc, not Thor GPU performance.
/graphics-out/assets/vulkan-probe --allow-software \
  > /graphics-out/vulkan-fixture.json 2> /graphics-out/vulkan-fixture.log
python3 /graphics-tests/graphics_present.py --port 5991 \
  --report /graphics-out/d3d11-rfb-presentation.json \
  --stdout /graphics-out/d3d11-fixture.json --stderr /graphics-out/d3d11-fixture.log \
  -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
  fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
  'C:\windows\system32\dxgi.dll' "$dxgi_digest"
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
# The hardware mode must reject exactly the same CPU fixture driver.
if timeout --kill-after=10 60 /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
  hardware 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
  'C:\windows\system32\dxgi.dll' "$dxgi_digest" \
  > /graphics-out/d3d11-cpu-rejection.json 2> /graphics-out/d3d11-cpu-rejection.log; then
  echo 'Hardware qualification incorrectly accepted the CPU fixture' >&2
  exit 1
fi
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
# A native ARM64 CI machine does not have an Android KGSL device. Pin only our
# Turnip ICD and require a failure, proving no hidden Lavapipe fallback.
python3 /graphics-tests/scripts/check-client-window-runtime.py
test ! -e /dev/kgsl-3d0
python3 - <<'PY'
import json
from pathlib import Path
Path('/graphics-out/turnip-icd.json').write_text(json.dumps({
  'file_format_version': '1.0.0', 'ICD': {
    'library_path': '/graphics-out/assets/turnip-26.0.0.so', 'api_version': '1.3.0'}}))
PY
export VK_DRIVER_FILES=/graphics-out/turnip-icd.json VK_ICD_FILENAMES=/graphics-out/turnip-icd.json
# `--allow-software` bypasses this helper's early KGSL-permission check so it
# actually loads our forced ICD. If the pin were ignored and Lavapipe used,
# this invocation would succeed, making the negative control fail correctly.
if /graphics-out/assets/vulkan-probe --allow-software > /graphics-out/turnip-no-kgsl.json 2> /graphics-out/turnip-no-kgsl.log; then
  echo 'Turnip unexpectedly passed without KGSL; inspect the forced ICD and hardware gate' >&2
  exit 1
fi
python3 - <<'PY'
import json
import re
from pathlib import Path
folder = Path('/graphics-out')
def one_json(name):
    source = (folder / name).read_text()
    try:
        value = json.loads(source)
    except ValueError:
        pass
    else:
        if isinstance(value, dict):
            return value
        raise SystemExit('Expected one probe object in ' + name)
    reports = []
    for line in source.splitlines():
        try: value = json.loads(line)
        except ValueError: continue
        if isinstance(value, dict): reports.append(value)
    if len(reports) != 1:
        raise SystemExit('Expected one probe report in ' + name)
    return reports[0]
vulkan = one_json('vulkan-fixture.json')
assert vulkan['software'] is True and vulkan['presentation_frames'] == 3
assert vulkan['api_version'] >= (1 << 22 | 3 << 12)
d3d = one_json('d3d11-fixture.json')
assert d3d['mode'] == 'fixture' and d3d['passed'] is True
assert d3d['feature_level'] >= 0xb000 and d3d['pixels_verified'] is True
assert d3d['present_count'] == 3
assert type(d3d.get('requested_sync_interval')) is int and d3d['requested_sync_interval'] == 1
dxvk_log = (folder / 'd3d11-fixture.log').read_text()
sync_intervals = re.findall(r'^info:[ \t]+dxgi\.syncInterval[ \t]*=[ \t]*(\S+)[ \t]*\r?$', dxvk_log, re.MULTILINE)
present_modes = re.findall(r'^info:[ \t]+Present mode:[ \t]*(VK_PRESENT_MODE_[A-Z_]+)\b', dxvk_log, re.MULTILINE)
assert sync_intervals and all(value == '0' for value in sync_intervals)
assert present_modes and all(value == 'VK_PRESENT_MODE_IMMEDIATE_KHR' for value in present_modes)
presentation = one_json('d3d11-rfb-presentation.json')
assert presentation['display_pixels_verified'] is True
assert presentation['matched_frames'] == [0, 1, 2]
assert presentation['center_pixels_verified'] is True
for name in ('d3d11', 'dxgi'):
    assert d3d[name]['identity_verified'] is True
    assert d3d[name]['disk_machine'] == 0x8664 and d3d[name]['native_ec_ranges'] > 0
negative = one_json('d3d11-cpu-rejection.json')
assert negative['mode'] == 'hardware' and negative['passed'] is False
assert negative['present_count'] == 0 and negative['stage'] == 'select_adapter'
assert negative['hresult'] == 0x887a0002
assert all(negative[name]['identity_verified'] is True for name in ('d3d11', 'dxgi'))
report = {'passed': True, 'qualification': 'native-arm64-ec-lavapipe-ci-only',
          'physicalThorQualified': False, 'd3d11': d3d, 'vulkan': vulkan,
          'rfbPresentation': presentation,
          'presentationPolicy': 'requested-vsync-forced-immediate-1',
          'requestedSyncInterval': 1, 'forcedSyncInterval': 0,
          'observedPresentModes': present_modes,
          'baselineRuntimeIdentity': json.loads((folder / 'qualified-runtime-identity.json').read_text()),
          'cpuHardwareGateRejected': True, 'turnipWithoutKgslRejected': True}
(folder / 'client-graphics-check.json').write_text(json.dumps(report, indent=2) + '\n')
PY
QUALIFICATION
container_status=$(docker inspect --format '{{.State.ExitCode}}' "$graphics_container")
if [[ "$qualification_status" -eq 0 ]]; then qualification_status=$container_status; fi
# Preserve diagnostics before removing a failed container.
docker cp "$graphics_container:/graphics-out/." out/
if [[ "$qualification_status" -ne 0 ]]; then
  python3 - <<'PY'
from pathlib import Path
for path in sorted(Path('out').glob('*.log')):
    print('Graphics diagnostic: ' + path.name, flush=True)
    print(path.read_text(errors='replace')[-16000:], flush=True)
PY
  exit "$qualification_status"
fi

# Copy only the five exact graphics components and their manifest into APK assets.
python3 - <<'PYVALIDATE'
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, 'backend')
import client_graphics
assets = Path('out/assets')
# Byte equality keeps the container's literal configuration synchronized with
# the private configuration generated by the production backend.
assert Path('out/dxvk.conf').read_bytes() == client_graphics.DXVK_CONFIG.encode('utf-8')
client_graphics.verify_bundle(assets)
manifest = json.loads((assets / 'client-graphics-bundle.json').read_text())
for name in (*manifest['files'], 'client-graphics-bundle.json'):
    shutil.copyfile(assets / name, Path('backend') / name)
client_graphics.verify_bundle(Path('backend'))
# Exercise the production reader on the observer's actual formatted receipt,
# rather than qualifying only the independent CI summary reader.
client_graphics.parse_display(Path('out/d3d11-rfb-presentation.json').read_text())
report = json.loads(Path('out/client-graphics-check.json').read_text())
assert report['passed'] is True and report['physicalThorQualified'] is False
policy = client_graphics.parse_presentation_policy(Path('out/d3d11-fixture.log').read_text())
assert all(report.get(key) == value for key, value in policy.items())
assert type(report['d3d11'].get('requested_sync_interval')) is int and report['d3d11']['requested_sync_interval'] == 1
window = json.loads(Path('out/client-window-check.json').read_text())
helper = assets / 'eve-client-window.exe'
import hashlib
assert window['passed'] is True and window['physicalThorQualified'] is False
assert hashlib.sha256(helper.read_bytes()).hexdigest() == window['helperSha256']
shutil.copyfile(helper, Path('backend/eve-client-window.exe'))
PYVALIDATE
