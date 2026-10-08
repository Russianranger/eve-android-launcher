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
# Every fixture starts from an explicit baseline. Per-process experiment
# assignments below must not leak into another trial or negative control.
unset TU_DEBUG FEX_HOSTFEATURES
export MESA_VK_WSI_DEBUG=sw
display_pid=''
responsive_display_pid=''
cleanup_display() {
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -k || true
  if [[ -n "$display_pid" ]]; then kill "$display_pid" || true; fi
  if [[ -n "$responsive_display_pid" ]]; then kill "$responsive_display_pid" || true; fi
}
trap cleanup_display EXIT
/usr/bin/Xtigervnc "$DISPLAY" -geometry 320x240 -depth 24 -rfbport 5991 \
  -localhost yes -SecurityTypes None -nolisten tcp -ac -AlwaysShared \
  -FrameRate 60 -desktop 'EVE graphics fixture' > /graphics-out/xvnc.log 2>&1 &
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
# Private performance profile: throughput.
dxgi.maxFrameRate = 60
dxgi.maxFrameLatency = 2
dxgi.syncInterval = 0
CONFIG
test -f "$VK_DRIVER_FILES"
# Capture only this fixed graphics allowlist, never arbitrary CI environment
# variables. These are the actual assignments inherited by each helper.
cat > /graphics-out/capture-graphics-environment.py <<'PY'
import json
import os
from pathlib import Path
import sys
keys = ('MESA_VK_WSI_DEBUG', 'TU_DEBUG', 'FEX_HOSTFEATURES',
        'VK_DRIVER_FILES', 'VK_ICD_FILENAMES', 'DISPLAY', 'DXVK_CONFIG_FILE',
        'DXVK_LOG_LEVEL', 'DXVK_LOG_PATH', 'DXVK_HUD', 'DXVK_STATE_CACHE_PATH',
        'MESA_SHADER_CACHE_DIR', 'MESA_SHADER_CACHE_MAX_SIZE', 'WINEDLLOVERRIDES')
Path('/graphics-out', sys.argv[1]).write_text(json.dumps(
    {key: os.environ.get(key) for key in keys}, indent=2) + '\n')
PY
python3 /graphics-out/capture-graphics-environment.py d3d11-throughput-environment.json
# This is an explicitly named software CI fixture. A successful result verifies
# x64 -> native EC D3D11/DXGI -> Wine Vulkan -> Xvnc, not Thor GPU performance.
/graphics-out/assets/vulkan-probe --allow-software \
  > /graphics-out/vulkan-fixture.json 2> /graphics-out/vulkan-fixture.log
# This helper reads exact native adapter identity and linear image capability.
# A software fixture must identify itself as such, and retail hardware mode
# must fail on this CI host before either experiment can be selected.
/graphics-out/assets/a740-driver-probe --fixture \
  > /graphics-out/a740-identity-cpu-fixture.json 2> /graphics-out/a740-identity-cpu-fixture.log
if /graphics-out/assets/a740-driver-probe \
    > /graphics-out/a740-identity-hardware-rejection.json 2> /graphics-out/a740-identity-hardware-rejection.log; then
  echo 'A740 identity gate incorrectly accepted the CI software adapter' >&2
  exit 1
fi
python3 /graphics-tests/graphics_present.py --port 5991 \
  --report /graphics-out/d3d11-rfb-presentation.json \
  --stdout /graphics-out/d3d11-fixture.json --stderr /graphics-out/d3d11-fixture.log \
  -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
  fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
  'C:\windows\system32\dxgi.dll' "$dxgi_digest"
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
# Reuse the same built DLLs and original Present(1) helper to qualify the exact
# responsive recovery profile on a separate 30Hz private Xvnc display.
/usr/bin/Xtigervnc :22 -geometry 320x240 -depth 24 -rfbport 5992 \
  -localhost yes -SecurityTypes None -nolisten tcp -ac -AlwaysShared \
  -FrameRate 30 -desktop 'EVE responsive fixture' > /graphics-out/xvnc-responsive.log 2>&1 &
responsive_display_pid=$!
python3 - <<'PY'
from pathlib import Path
import time
for _ in range(100):
    if Path('/tmp/.X11-unix/X22').is_socket():
        break
    time.sleep(0.1)
else:
    raise SystemExit('Responsive Xvnc did not create its display socket')
PY
cat > /graphics-out/dxvk-responsive.conf <<'CONFIG'
# Private performance profile: responsive.
dxgi.maxFrameRate = 30
dxgi.maxFrameLatency = 1
dxgi.syncInterval = 0
CONFIG
responsive_environment=(env -u TU_DEBUG -u FEX_HOSTFEATURES
  MESA_VK_WSI_DEBUG=sw DISPLAY=:22
  DXVK_CONFIG_FILE='Z:\graphics-out\dxvk-responsive.conf')
"${responsive_environment[@]}" python3 /graphics-out/capture-graphics-environment.py \
  d3d11-responsive-environment.json
"${responsive_environment[@]}" python3 /graphics-tests/graphics_present.py --port 5992 \
  --report /graphics-out/d3d11-responsive-rfb-presentation.json \
  --stdout /graphics-out/d3d11-responsive-fixture.json --stderr /graphics-out/d3d11-responsive-fixture.log \
  -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
  fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
  'C:\windows\system32\dxgi.dll' "$dxgi_digest"
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
# Qualify the isolated linear software-WSI path at the unchanged responsive
# 30 FPS / latency 1 / display 30 policy. The metadata query is a prerequisite;
# the EC shaders, staging pixels and independently observed frames must also
# pass. Lavapipe success is a software CI fixture, never A740 qualification.
linear_environment=(env -u TU_DEBUG -u FEX_HOSTFEATURES
  MESA_VK_WSI_DEBUG=sw,linear DISPLAY=:22
  DXVK_CONFIG_FILE='Z:\graphics-out\dxvk-responsive.conf')
"${linear_environment[@]}" /graphics-out/assets/a740-driver-probe --fixture \
  > /graphics-out/linear-identity-cpu-fixture.json 2> /graphics-out/linear-identity-cpu-fixture.log
"${linear_environment[@]}" python3 /graphics-out/capture-graphics-environment.py \
  linear-presentation-environment.json
"${linear_environment[@]}" python3 /graphics-tests/graphics_present.py --port 5992 \
  --report /graphics-out/d3d11-linear-rfb-presentation.json \
  --stdout /graphics-out/d3d11-linear-fixture.json --stderr /graphics-out/d3d11-linear-fixture.log \
  -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
  fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
  'C:\windows\system32\dxgi.dll' "$dxgi_digest"
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
# Exercise SYS alone and with linear presentation using the same fixed helper,
# native EC DLLs and responsive 30 FPS / latency 1 / display 30 policy. Lavapipe
# does not consume Turnip's TU_DEBUG: this qualifies option propagation and the
# complete software integration path, never physical Adreno render mode or FPS.
for trial in sysmem sysmem-linear; do
  trial_wsi=sw
  if [[ "$trial" == sysmem-linear ]]; then trial_wsi=sw,linear; fi
  sysmem_environment=(env -u FEX_HOSTFEATURES
    TU_DEBUG=sysmem "MESA_VK_WSI_DEBUG=$trial_wsi" DISPLAY=:22
    DXVK_CONFIG_FILE='Z:\graphics-out\dxvk-responsive.conf')
  "${sysmem_environment[@]}" python3 /graphics-out/capture-graphics-environment.py \
    "d3d11-$trial-environment.json"
  "${sysmem_environment[@]}" /graphics-out/assets/a740-driver-probe --fixture \
    > "/graphics-out/d3d11-$trial-identity-cpu-fixture.json" \
    2> "/graphics-out/d3d11-$trial-identity-cpu-fixture.log"
  "${sysmem_environment[@]}" python3 /graphics-tests/graphics_present.py --port 5992 \
    --report "/graphics-out/d3d11-$trial-rfb-presentation.json" \
    --stdout "/graphics-out/d3d11-$trial-fixture.json" \
    --stderr "/graphics-out/d3d11-$trial-fixture.log" \
    -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
    fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
    'C:\windows\system32\dxgi.dll' "$dxgi_digest"
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
done
unset TU_DEBUG FEX_HOSTFEATURES
export MESA_VK_WSI_DEBUG=sw
# Qualify each isolated profile and the allowlisted FEX instruction fallback
# through the same native EC shaders/readback and three visible frames.
for trial in render60 queue2 display60 fex-load; do
  trial_rate=30; trial_latency=1; trial_display=:22; trial_port=5992
  trial_profile=$trial; trial_features=''
  case "$trial" in
    render60) trial_rate=60 ;;
    queue2) trial_latency=2 ;;
    display60) trial_display=:21; trial_port=5991 ;;
    fex-load) trial_profile=responsive; trial_features=disablelrcpc2 ;;
  esac
  cat > "/graphics-out/dxvk-$trial.conf" <<CONFIG
# Private performance profile: $trial_profile.
dxgi.maxFrameRate = $trial_rate
dxgi.maxFrameLatency = $trial_latency
dxgi.syncInterval = 0
CONFIG
  trial_environment=(env -u TU_DEBUG -u FEX_HOSTFEATURES MESA_VK_WSI_DEBUG=sw)
  if [[ -n "$trial_features" ]]; then trial_environment+=("FEX_HOSTFEATURES=$trial_features"); fi
  "${trial_environment[@]}" DISPLAY="$trial_display" DXVK_CONFIG_FILE="Z:\\graphics-out\\dxvk-$trial.conf" \
    python3 /graphics-out/capture-graphics-environment.py "d3d11-$trial-environment.json"
  "${trial_environment[@]}" DISPLAY="$trial_display" DXVK_CONFIG_FILE="Z:\\graphics-out\\dxvk-$trial.conf" \
    python3 /graphics-tests/graphics_present.py --port "$trial_port" \
    --report "/graphics-out/d3d11-$trial-rfb-presentation.json" \
    --stdout "/graphics-out/d3d11-$trial-fixture.json" --stderr "/graphics-out/d3d11-$trial-fixture.log" \
    -- /opt/wine/bin/wine /graphics-out/assets/eve-d3d11-probe.exe \
    fixture 'C:\windows\system32\d3d11.dll' "$d3d11_digest" \
    'C:\windows\system32\dxgi.dll' "$dxgi_digest"
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
  timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
done
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
# Load the freshly built optional ICD on native ARM64 with the same loader.
# Absence of KGSL must still fail; this is not a physical A740 qualification.
python3 - <<'PY'
import json
from pathlib import Path
Path('/graphics-out/turnip-a740-icd.json').write_text(json.dumps({
  'file_format_version': '1.0.0', 'ICD': {
    'library_path': '/graphics-out/assets/turnip-26.0.0-a740-pc-mode.so', 'api_version': '1.3.0'}}))
PY
export VK_DRIVER_FILES=/graphics-out/turnip-a740-icd.json VK_ICD_FILENAMES=/graphics-out/turnip-a740-icd.json
if /graphics-out/assets/a740-driver-probe --fixture \
    > /graphics-out/a740-identity-no-kgsl.json 2> /graphics-out/a740-identity-no-kgsl.log; then
  echo 'Optional A740 driver incorrectly accepted a software fallback without KGSL' >&2
  exit 1
fi
if /graphics-out/assets/vulkan-probe --allow-software \
    > /graphics-out/turnip-a740-no-kgsl.json 2> /graphics-out/turnip-a740-no-kgsl.log; then
  echo 'Optional A740 driver unexpectedly rendered without KGSL' >&2
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
baseline_environment = one_json('d3d11-throughput-environment.json')
assert baseline_environment['MESA_VK_WSI_DEBUG'] == 'sw'
assert baseline_environment['TU_DEBUG'] is None and baseline_environment['FEX_HOSTFEATURES'] is None
assert baseline_environment['DISPLAY'] == ':21'
assert baseline_environment['DXVK_CONFIG_FILE'] == 'Z:\\graphics-out\\dxvk.conf'
report['effectiveEnvironment'] = baseline_environment
identity_fixture = one_json('a740-identity-cpu-fixture.json')
assert identity_fixture['helper'] == 'eve-a740-driver-probe-1'
assert identity_fixture['mode'] == 'fixture' and identity_fixture['passed'] is True
assert identity_fixture['software'] is True and type(identity_fixture['device_id']) is int
report['a740PcModeExperiment'] = {
    'identityFixture': identity_fixture, 'cpuHardwareGateRejected': True,
    'driverWithoutKgslRejected': True, 'identityOnly': True, 'physicalThorQualified': False,
    'sourceProvenance': json.loads((folder / 'assets/client-graphics-bundle.json').read_text())['a740PcModeExperiment'],
    'linkCompatibility': json.loads((folder / 'a740-link-compatibility.json').read_text()),
}
report['performance'] = {'requestedProfile': 'throughput', 'performanceProfile': 'throughput',
                         'targetFrameRate': 60, 'maxFrameLatency': 2, 'displayFrameRate': 60,
                         'diagnosticHud': False}
responsive = one_json('d3d11-responsive-fixture.json')
responsive_display = one_json('d3d11-responsive-rfb-presentation.json')
assert responsive['mode'] == 'fixture' and responsive['passed'] is True
assert responsive['pixels_verified'] is True and responsive['present_count'] == 3
assert type(responsive.get('requested_sync_interval')) is int and responsive['requested_sync_interval'] == 1
assert responsive_display['display_pixels_verified'] is True and responsive_display['matched_frames'] == [0, 1, 2]
assert responsive_display['center_pixels_verified'] is True
for name in ('d3d11', 'dxgi'):
    assert responsive[name]['identity_verified'] is True and responsive[name]['sha256'] == d3d[name]['sha256']
report['responsiveProfile'] = {'d3d11': responsive, 'rfbPresentation': responsive_display,
                              'performance': {'requestedProfile': 'responsive', 'performanceProfile': 'responsive',
                                              'targetFrameRate': 30, 'maxFrameLatency': 1, 'displayFrameRate': 30,
                                              'diagnosticHud': False}}
responsive_environment = one_json('d3d11-responsive-environment.json')
assert responsive_environment['MESA_VK_WSI_DEBUG'] == 'sw'
assert responsive_environment['TU_DEBUG'] is None and responsive_environment['FEX_HOSTFEATURES'] is None
assert responsive_environment['DISPLAY'] == ':22'
assert responsive_environment['DXVK_CONFIG_FILE'] == 'Z:\\graphics-out\\dxvk-responsive.conf'
report['responsiveProfile']['effectiveEnvironment'] = responsive_environment
linear_identity = one_json('linear-identity-cpu-fixture.json')
assert linear_identity['helper'] == 'eve-a740-driver-probe-1'
assert linear_identity['mode'] == 'fixture' and linear_identity['passed'] is True
assert linear_identity['software'] is True
assert linear_identity['linear_presentation'] == {
    'supported': True, 'bgra8_unorm': True, 'rgba8_unorm': True}
linear_environment = one_json('linear-presentation-environment.json')
assert linear_environment['MESA_VK_WSI_DEBUG'] == 'sw,linear'
assert linear_environment['DISPLAY'] == ':22'
assert linear_environment['DXVK_CONFIG_FILE'] == 'Z:\\graphics-out\\dxvk-responsive.conf'
assert linear_environment['VK_DRIVER_FILES'] == '/usr/share/vulkan/icd.d/lvp_icd.aarch64.json'
assert linear_environment['VK_ICD_FILENAMES'] == linear_environment['VK_DRIVER_FILES']
assert linear_environment['TU_DEBUG'] is None and linear_environment['FEX_HOSTFEATURES'] is None
linear = one_json('d3d11-linear-fixture.json')
linear_display = one_json('d3d11-linear-rfb-presentation.json')
assert linear['mode'] == 'fixture' and linear['passed'] is True
assert linear['pixels_verified'] is True and linear['present_count'] == 3
assert type(linear.get('requested_sync_interval')) is int and linear['requested_sync_interval'] == 1
assert linear_display['display_pixels_verified'] is True
assert linear_display['matched_frames'] == [0, 1, 2] and linear_display['center_pixels_verified'] is True
for name in ('d3d11', 'dxgi'):
    assert linear[name]['identity_verified'] is True and linear[name]['sha256'] == d3d[name]['sha256']
linear_log = (folder / 'd3d11-linear-fixture.log').read_text()
linear_sync = re.findall(r'^info:[ \t]+dxgi\.syncInterval[ \t]*=[ \t]*(\S+)[ \t]*\r?$', linear_log, re.MULTILINE)
linear_modes = re.findall(r'^info:[ \t]+Present mode:[ \t]*(VK_PRESENT_MODE_[A-Z_]+)\b', linear_log, re.MULTILINE)
assert linear_sync and all(value == '0' for value in linear_sync)
assert linear_modes and all(value == 'VK_PRESENT_MODE_IMMEDIATE_KHR' for value in linear_modes)
manifest = json.loads((folder / 'assets/client-graphics-bundle.json').read_text())
report['linearPresentationExperiment'] = {
    'qualification': 'native-arm64-ec-lavapipe-ci-only',
    'd3d11': linear, 'rfbPresentation': linear_display, 'identityFixture': linear_identity,
    'effectiveEnvironment': linear_environment,
    'performance': report['responsiveProfile']['performance'],
    'requestedSyncInterval': 1, 'forcedSyncInterval': 0, 'observedPresentModes': linear_modes,
    'clientDriver': 'turnip-26.0.0.so',
    'clientDriverSha256': manifest['files']['turnip-26.0.0.so']['sha256'],
    'mesaSourceSha256': manifest['a740PcModeExperiment']['mesaSourceSha256'],
    'probeSourceSha256': manifest['a740PcModeExperiment']['probeSourceSha256'],
    'nativeEffectVerified': False, 'physicalThorQualified': False,
}
report['sysmemRenderingExperiments'] = {}
for trial, linear_selected, expected_wsi in (
        ('sysmem', False, 'sw'), ('sysmem-linear', True, 'sw,linear')):
    environment = one_json('d3d11-' + trial + '-environment.json')
    # These literal expectations are intentionally independent of the backend
    # generator. A regression there must not redefine a passing native fixture.
    assert set(environment) == set(responsive_environment)
    assert environment['TU_DEBUG'] == 'sysmem'
    assert environment['MESA_VK_WSI_DEBUG'] == expected_wsi
    assert environment['FEX_HOSTFEATURES'] is None
    for key in environment.keys() - {'TU_DEBUG', 'MESA_VK_WSI_DEBUG'}:
        assert environment[key] == responsive_environment[key]
    identity = one_json('d3d11-' + trial + '-identity-cpu-fixture.json')
    assert identity['helper'] == 'eve-a740-driver-probe-1'
    assert identity['mode'] == 'fixture' and identity['passed'] is True
    assert identity['software'] is True and type(identity['device_id']) is int
    observed = one_json('d3d11-' + trial + '-fixture.json')
    assert observed['mode'] == 'fixture' and observed['passed'] is True
    assert observed['feature_level'] >= 0xb000
    assert observed['pixels_verified'] is True and observed['offscreen_pixels_verified'] is True
    assert observed['present_count'] == 3
    assert type(observed.get('requested_sync_interval')) is int and observed['requested_sync_interval'] == 1
    for name in ('d3d11', 'dxgi'):
        assert observed[name]['identity_verified'] is True
        assert observed[name]['disk_machine'] == 0x8664 and observed[name]['native_ec_ranges'] > 0
        assert observed[name]['sha256'] == d3d[name]['sha256']
    display = one_json('d3d11-' + trial + '-rfb-presentation.json')
    assert display['display_pixels_verified'] is True
    assert display['matched_frames'] == [0, 1, 2] and display['center_pixels_verified'] is True
    log = (folder / ('d3d11-' + trial + '-fixture.log')).read_text()
    sync = re.findall(r'^info:[ \t]+dxgi\.syncInterval[ \t]*=[ \t]*(\S+)[ \t]*\r?$', log, re.MULTILINE)
    modes = re.findall(r'^info:[ \t]+Present mode:[ \t]*(VK_PRESENT_MODE_[A-Z_]+)\b', log, re.MULTILINE)
    assert sync and all(value == '0' for value in sync)
    assert modes and all(value == 'VK_PRESENT_MODE_IMMEDIATE_KHR' for value in modes)
    report['sysmemRenderingExperiments'][trial] = {
        'qualification': 'native-arm64-ec-lavapipe-ci-only',
        'requestedSysmemRendering': True, 'sysmemRendering': True,
        'requestedLinearPresentation': linear_selected, 'linearPresentation': linear_selected,
        'turnipDebug': 'sysmem', 'mesaWsiDebug': expected_wsi,
        'effectiveEnvironment': environment, 'identityFixture': identity,
        'd3d11': observed, 'rfbPresentation': display,
        'performance': report['responsiveProfile']['performance'],
        'requestedSyncInterval': 1, 'forcedSyncInterval': 0, 'observedPresentModes': modes,
        'clientDriver': 'turnip-26.0.0.so',
        'clientDriverSha256': manifest['files']['turnip-26.0.0.so']['sha256'],
        'mesaSourceSha256': manifest['a740PcModeExperiment']['mesaSourceSha256'],
        'probeSourceSha256': manifest['a740PcModeExperiment']['probeSourceSha256'],
        'cpuHardwareGateRejected': True, 'nativeD3d11ShaderReadbackPassed': True,
        'visibleRfbFramesPassed': True,
        'softwareFixtureLimit': 'Lavapipe does not consume TU_DEBUG; this is not physical Adreno render-mode or performance proof',
        'nativeEffectVerified': False, 'physicalThorQualified': False,
    }
report['shaderReadbackRfbFixtures'] = [
    'throughput', 'responsive', 'linear', 'sysmem', 'sysmem-linear',
    'render60', 'queue2', 'display60', 'fex-load']
report['shaderReadbackRfbFixtureCount'] = len(report['shaderReadbackRfbFixtures'])
assert report['shaderReadbackRfbFixtureCount'] == 9
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

# Copy only the manifest-listed graphics components into APK assets.
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
assert Path('out/dxvk.conf').read_bytes() == client_graphics.dxvk_config('throughput').encode('utf-8')
assert Path('out/dxvk-responsive.conf').read_bytes() == client_graphics.dxvk_config('responsive').encode('utf-8')
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
assert report['a740PcModeExperiment']['sourceProvenance'] == client_graphics.A740_EXPERIMENT
assert report['a740PcModeExperiment']['physicalThorQualified'] is False
try:
    client_graphics.parse_a740_identity(Path('out/a740-identity-cpu-fixture.json').read_text())
except ValueError:
    pass
else:
    raise SystemExit('Production A740 selection parser accepted the software fixture')
policy = client_graphics.parse_performance_policy(Path('out/d3d11-fixture.log').read_text(), 'throughput')
assert all(report.get(key) == value for key, value in policy.items())
assert report['performance'] == client_graphics.performance_settings('turnip-dxvk', 'throughput')
responsive = report['responsiveProfile']
responsive['presentation'] = client_graphics.parse_performance_policy(
    Path('out/d3d11-responsive-fixture.log').read_text(), 'responsive')
assert responsive['performance'] == client_graphics.performance_settings('turnip-dxvk', 'responsive')
assert responsive['rfbPresentation'] == client_graphics.parse_display(
    Path('out/d3d11-responsive-rfb-presentation.json').read_text())
linear = report['linearPresentationExperiment']
assert linear['physicalThorQualified'] is False and linear['nativeEffectVerified'] is False
assert linear['clientDriverSha256'] == manifest['files']['turnip-26.0.0.so']['sha256']
assert linear['probeSourceSha256'] == client_graphics.A740_EXPERIMENT['probeSourceSha256']
linear['presentation'] = client_graphics.parse_performance_policy(
    Path('out/d3d11-linear-fixture.log').read_text(), 'responsive')
assert linear['performance'] == client_graphics.performance_settings('turnip-dxvk', 'responsive')
assert linear['rfbPresentation'] == client_graphics.parse_display(
    Path('out/d3d11-linear-rfb-presentation.json').read_text())
production_linear_env = client_graphics.configure_environment(
    {}, 'turnip-dxvk', assets, Path('out'), linear_presentation=True)
for key in ('MESA_VK_WSI_DEBUG', 'TU_DEBUG', 'FEX_HOSTFEATURES'):
    assert linear['effectiveEnvironment'][key] == production_linear_env.get(key)
try:
    client_graphics.parse_linear_presentation(
        Path('out/linear-identity-cpu-fixture.json').read_text(), report['vulkan'])
except ValueError:
    pass
else:
    raise SystemExit('Production hardware parser accepted the linear software fixture')
assert report['shaderReadbackRfbFixtureCount'] == 9
assert report['shaderReadbackRfbFixtures'] == [
    'throughput', 'responsive', 'linear', 'sysmem', 'sysmem-linear',
    'render60', 'queue2', 'display60', 'fex-load']
for trial, linear_selected, expected_wsi in (
        ('sysmem', False, 'sw'), ('sysmem-linear', True, 'sw,linear')):
    selected = report['sysmemRenderingExperiments'][trial]
    assert selected['physicalThorQualified'] is False and selected['nativeEffectVerified'] is False
    assert selected['requestedSysmemRendering'] is True and selected['sysmemRendering'] is True
    assert selected['linearPresentation'] is linear_selected
    assert selected['clientDriverSha256'] == manifest['files']['turnip-26.0.0.so']['sha256']
    assert selected['probeSourceSha256'] == client_graphics.A740_EXPERIMENT['probeSourceSha256']
    selected['presentation'] = client_graphics.parse_performance_policy(
        Path('out/d3d11-' + trial + '-fixture.log').read_text(), 'responsive')
    assert selected['performance'] == client_graphics.performance_settings('turnip-dxvk', 'responsive')
    assert selected['rfbPresentation'] == client_graphics.parse_display(
        Path('out/d3d11-' + trial + '-rfb-presentation.json').read_text())
    selected['optimizations'] = client_graphics.optimization_settings(
        'turnip-dxvk', linear_presentation=linear_selected, sysmem_rendering=True)
    for key in ('requestedSysmemRendering', 'sysmemRendering', 'requestedLinearPresentation',
                'linearPresentation', 'turnipDebug', 'mesaWsiDebug', 'nativeEffectVerified'):
        assert selected[key] == selected['optimizations'][key]
    # Generate assignments through production code with deliberately inherited
    # conflicting flags, and compare to independently literal native settings.
    production_env = client_graphics.configure_environment(
        {'TU_DEBUG': 'nocb', 'MESA_VK_WSI_DEBUG': 'invalid', 'FEX_HOSTFEATURES': 'disablelrcpc2'},
        'turnip-dxvk', assets, Path('out'),
        performance_profile='responsive', linear_presentation=linear_selected, sysmem_rendering=True)
    assert production_env.get('TU_DEBUG') == 'sysmem'
    assert production_env.get('MESA_VK_WSI_DEBUG') == expected_wsi
    assert production_env.get('FEX_HOSTFEATURES') is None
    for key in ('MESA_VK_WSI_DEBUG', 'TU_DEBUG', 'FEX_HOSTFEATURES'):
        assert selected['effectiveEnvironment'][key] == production_env.get(key)
    try:
        client_graphics.parse_sysmem_rendering(
            Path('out/d3d11-' + trial + '-identity-cpu-fixture.json').read_text(), report['vulkan'])
    except ValueError:
        pass
    else:
        raise SystemExit('Production SYSMEM hardware parser accepted the software fixture')
report['isolatedTrials'] = {}
for trial in ('render60', 'queue2', 'display60', 'fex-load'):
    profile = 'responsive' if trial == 'fex-load' else trial
    assert Path('out/dxvk-' + trial + '.conf').read_bytes() == client_graphics.dxvk_config(profile).encode('utf-8')
    d3d = client_graphics.last_report(Path('out/d3d11-' + trial + '-fixture.json').read_text())
    assert d3d['mode'] == 'fixture' and d3d['passed'] is True and d3d['pixels_verified'] is True
    assert d3d['present_count'] == 3 and d3d['requested_sync_interval'] == 1
    for name in ('d3d11', 'dxgi'):
        assert d3d[name]['identity_verified'] is True and d3d[name]['sha256'] == report['d3d11'][name]['sha256']
    environment = json.loads(Path('out/d3d11-' + trial + '-environment.json').read_text())
    assert environment['MESA_VK_WSI_DEBUG'] == 'sw' and environment['TU_DEBUG'] is None
    assert environment['FEX_HOSTFEATURES'] == ('disablelrcpc2' if trial == 'fex-load' else None)
    assert environment['DISPLAY'] == (':21' if trial == 'display60' else ':22')
    assert environment['DXVK_CONFIG_FILE'] == 'Z:\\graphics-out\\dxvk-' + trial + '.conf'
    report['isolatedTrials'][trial] = {
        'd3d11': d3d,
        'rfbPresentation': client_graphics.parse_display(Path('out/d3d11-' + trial + '-rfb-presentation.json').read_text()),
        'presentation': client_graphics.parse_performance_policy(Path('out/d3d11-' + trial + '-fixture.log').read_text(), profile),
        'performance': client_graphics.performance_settings('turnip-dxvk', profile),
        'effectiveEnvironment': environment,
        'fexHostFeatures': 'disablelrcpc2' if trial == 'fex-load' else None,
        'physicalThorQualified': False,
    }
assert 3 + len(report['sysmemRenderingExperiments']) + len(report['isolatedTrials']) == 9
Path('out/client-graphics-check.json').write_text(json.dumps(report, indent=2) + '\n')
assert type(report['d3d11'].get('requested_sync_interval')) is int and report['d3d11']['requested_sync_interval'] == 1
window = json.loads(Path('out/client-window-check.json').read_text())
helper = assets / 'eve-client-window.exe'
import hashlib
assert window['passed'] is True and window['physicalThorQualified'] is False
assert hashlib.sha256(helper.read_bytes()).hexdigest() == window['helperSha256']
shutil.copyfile(helper, Path('backend/eve-client-window.exe'))
PYVALIDATE
