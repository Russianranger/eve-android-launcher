#!/usr/bin/env bash
# Build only the optional renderer. The qualified client/server rootfs is unchanged.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
test "$(uname -m)" = aarch64 || { echo 'Turnip requires a native ARM64 Linux build host.' >&2; exit 1; }
command -v docker >/dev/null
mkdir -p out
renderer_image=eve-android-renderer:local
renderer_source_image=eve-android-renderer-sources:local
renderer_container=''
renderer_source_container=''
renderer_stage=$(mktemp -d)
cleanup() {
    if [[ -n "$renderer_container" ]]; then docker rm -f "$renderer_container" >/dev/null 2>&1 || true; fi
    if [[ -n "$renderer_source_container" ]]; then docker rm -f "$renderer_source_container" >/dev/null 2>&1 || true; fi
    rm -rf "$renderer_stage"
}
trap cleanup EXIT
docker build --platform linux/arm64 --target renderer \
    -f renderer-runtime/Dockerfile -t "$renderer_image" .
renderer_container=$(docker create "$renderer_image" /bin/true)
docker cp "$renderer_container:/renderer/." "$renderer_stage/"
python3 scripts/package-client-renderer.py "$renderer_stage"
docker build --platform linux/arm64 --target corresponding-source \
    -f renderer-runtime/Dockerfile -t "$renderer_source_image" .
renderer_source_container=$(docker create "$renderer_source_image" /bin/true)
mkdir -p "$renderer_stage/sources"
docker cp "$renderer_source_container:/sources/." "$renderer_stage/sources/"
tar --format=gnu --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
    -C "$renderer_stage/sources" -czf out/renderer-corresponding-source.tar.gz .
python3 - <<'PY'
import hashlib, json
from pathlib import Path
source = Path('out/renderer-corresponding-source.tar.gz')
manifest = Path('backend/renderer-manifest.json')
report = json.loads(manifest.read_text())
with source.open('rb') as content:
    checksum = hashlib.file_digest(content, 'sha256').hexdigest()
report['correspondingSource'] = {'file': source.name, 'sha256': checksum, 'sizeBytes': source.stat().st_size}
manifest.write_text(json.dumps(report, indent=2) + '\n')
PY
cp backend/renderer-runtime.tar.gz backend/renderer-manifest.json out/
