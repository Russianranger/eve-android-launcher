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
overlay_container=$(docker create "$overlay_image")
docker cp "$overlay_container:/out/assets/." backend/
docker cp "$overlay_container:/out/wine-trust-corresponding-source.tar.gz" out/
docker cp "$overlay_container:/out/wine-trust-regression.log" out/
docker cp "$overlay_container:/out/wine-trust-baseline.log" out/
docker cp "$overlay_container:/out/baseline-trust.json" out/
docker cp "$overlay_container:/out/patched-trust.json" out/
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
