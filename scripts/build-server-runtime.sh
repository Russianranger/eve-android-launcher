#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
python3 scripts/prepare-evejs-source.py
test "$(uname -m)" = aarch64 || { echo 'Server runtime requires a native ARM64 Linux build host.' >&2; exit 1; }
command -v docker >/dev/null
mkdir -p out
runtime_image=eve-android-server:local
source_image=eve-android-server-sources:local
runtime_container=''
source_container=''
cleanup() {
  if [[ -n "$runtime_container" ]]; then docker rm -f "$runtime_container" >/dev/null 2>&1 || true; fi
  if [[ -n "$source_container" ]]; then docker rm -f "$source_container" >/dev/null 2>&1 || true; fi
  rm -f out/server-runtime.raw.tar
}
trap cleanup EXIT
docker build --platform linux/arm64 --target runtime \
  -f server-runtime/Dockerfile -t "$runtime_image" .
python3 scripts/check-server-runtime.py --image "$runtime_image" --output out/server-runtime-check.json
runtime_container=$(docker create "$runtime_image")
docker export "$runtime_container" -o out/server-runtime.raw.tar
inputs_sha256=$(python3 scripts/runtime-inputs-sha256.py)
python3 scripts/package-runtime.py out/server-runtime.raw.tar --inputs-sha256 "$inputs_sha256"
python3 scripts/check-server-package.py out/server-runtime-arm64.tar.gz
# Keep corresponding source alongside the exact binaries, rather than only
# referring users to moving upstream dependency websites.
docker build --platform linux/arm64 --target corresponding-source \
  -f server-runtime/Dockerfile -t "$source_image" .
source_container=$(docker create "$source_image" /bin/true)
mkdir -p out/server-runtime-source
docker cp "$source_container:/sources/." out/server-runtime-source/
tar --format=gnu --sort=name --owner=0 --group=0 --numeric-owner \
  -C out/server-runtime-source -czf out/server-runtime-source.tar.gz .
python3 - <<'PY'
import hashlib,json,pathlib
path=pathlib.Path('out/server-runtime-source.tar.gz')
manifest_path=pathlib.Path('out/server-runtime-manifest.json')
manifest=json.loads(manifest_path.read_text())
with path.open('rb') as handle: checksum=hashlib.file_digest(handle,'sha256').hexdigest()
manifest['correspondingSource']={'file':path.name,'sha256':checksum,'sizeBytes':path.stat().st_size}
manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
PY
rm -rf out/server-runtime-source
python3 scripts/check-server-package.py out/server-runtime-arm64.tar.gz
