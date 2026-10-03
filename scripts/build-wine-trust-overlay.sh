#!/usr/bin/env bash
# The targeted overlay is built separately from the pinned server/client runtime.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
test "$(uname -m)" = aarch64 || { echo 'Wine trust overlay requires a native ARM64 build host.' >&2; exit 1; }
command -v docker >/dev/null
mkdir -p out backend
overlay_image=eve-wine-trust-overlay:local
overlay_container=''
cleanup() {
  if [[ -n "$overlay_container" ]]; then docker rm -f "$overlay_container" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
docker build --platform linux/arm64 --target qualification \
  -f client-runtime/wine-trust/Dockerfile -t "$overlay_image" .
overlay_container=$(docker create --init -i --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined "$overlay_image" /bin/bash -s)
qualification_status=0
docker start -ai "$overlay_container" <<'QUALIFICATION' || qualification_status=$?
set -Eeuo pipefail
xvfb-run -a /bin/bash -s <<'WINE_TESTS'
set -Eeuo pipefail
trap 'timeout --kill-after=5 15 /opt/wine/bin/wineserver -k || true' EXIT
# Match the already-qualified UO runtime's disposable-prefix initialization.
# Suppress Wine's optional browser/.NET installers before starting CryptoAPI.
timeout --kill-after=10 180 /opt/wine/bin/wine wineboot -u \
  < /dev/null > /out/wine-trust-prefix.log 2>&1
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
python3 /wine-tests/wine_trust_regression.py \
  --wine /opt/wine/bin/wine --helper /wine-tests/eve-wine-trust-test.exe \
  --fixtures /wine-tests/fixtures --expect-unpatched --output /out/baseline-trust.json \
  > /out/wine-trust-baseline.log 2>&1
timeout --kill-after=5 15 /opt/wine/bin/wineserver -k
timeout --kill-after=5 15 /opt/wine/bin/wineserver -w
cp /out/assets/wine-crypt32-aarch64.dll /opt/wine/lib/wine/aarch64-windows/crypt32.dll
cp /out/assets/wine-crypt32-i386.dll /opt/wine/lib/wine/i386-windows/crypt32.dll
python3 /wine-tests/wine_trust_regression.py \
  --wine /opt/wine/bin/wine --helper /wine-tests/eve-wine-trust-test.exe \
  --fixtures /wine-tests/fixtures --output /out/patched-trust.json \
  > /out/wine-trust-regression.log 2>&1
WINE_TESTS
QUALIFICATION
# Read the container's exit status explicitly as well as Docker's attach status.
container_status=$(docker inspect --format '{{.State.ExitCode}}' "$overlay_container")
if [[ "$qualification_status" -eq 0 ]]; then qualification_status=$container_status; fi
# Copy diagnostics even when a probe failed, before EXIT removes the container.
docker cp "$overlay_container:/out/." out/
if [[ "$qualification_status" -ne 0 ]]; then
  python3 - <<'PYFAIL'
from pathlib import Path
for path in sorted(Path('out').glob('wine-trust-*.log')):
    print(f'Wine qualification diagnostic: {path.name}', flush=True)
    print(path.read_text(errors='replace')[-16000:], flush=True)
PYFAIL
  exit "$qualification_status"
fi
cp out/assets/wine-crypt32-aarch64.dll out/assets/wine-crypt32-i386.dll \
  out/assets/wine-trust-overlay.json backend/
python3 - <<'PY'
import hashlib, json, struct
from pathlib import Path
manifest = json.loads(Path('backend/wine-trust-overlay.json').read_text())
assert manifest['wine_commit'] == 'a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29'
assert manifest['runtime'] == 'fex-arm64ec-1'
assert len(manifest['files']) == 2
for name, count in [('baseline-trust.json', 3), ('patched-trust.json', 13)]:
    report = json.loads((Path('out') / name).read_text())
    assert report['passed'] is True and len(report['cases']) == count
for item in manifest['files']:
    path = Path('backend') / item['asset']
    assert path.parent == Path('backend') and path.suffix == '.dll'
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == item['sha256']
    offset = struct.unpack_from('<I', data, 60)[0]
    assert data[:2] == b'MZ' and data[offset:offset + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, offset + 4)[0] == item['machine']
Path('out/wine-trust-overlay.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
