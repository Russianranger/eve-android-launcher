#!/usr/bin/env bash
set -Eeuo pipefail

# SDE generation and synthetic seeding are CI work, not mobile first-start work.
sde_build=3396210
sde_url="https://developers.eveonline.com/static-data/tranquility/eve-online-static-data-${sde_build}-jsonl.zip"
sde_dir=/tmp/evejs-sde
mkdir -p "$sde_dir" /opt/evejs-seed/gameStore/data /opt/evejs-seed/market
curl --fail --location --retry 5 --retry-all-errors "$sde_url" -o /tmp/evejs-sde.zip
unzip -tq /tmp/evejs-sde.zip
unzip -q /tmp/evejs-sde.zip -d "$sde_dir"
test -f "$sde_dir/_sde.jsonl"
node --max-old-space-size=8192 /opt/evejs/tools/DatabaseCreator/database-creator.js \
  --sde-dir "$sde_dir" --out /opt/evejs-seed/gameStore/data \
  --build "$sde_build" --sde-url "$sde_url" --force
market-seed --config /build-tools/config/market-seed.toml build --force --preset jita_only
market-server --config /build-tools/config/market-seed-doctor.toml doctor
cp -a /opt/evejs/config /opt/evejs-seed/config
python3 - <<'PY'
import hashlib,json,pathlib,sqlite3
root=pathlib.Path('/opt/evejs-seed')
manifest=json.loads((root/'gameStore/manifest.json').read_text())
assert manifest['build']==3396210,manifest
assert (root/'gameStore/data/itemTypes/data.json').stat().st_size>0
with sqlite3.connect(root/'market/market.sqlite') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    db.execute('PRAGMA journal_mode=DELETE')
archive=pathlib.Path('/tmp/evejs-sde.zip')
digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
(root/'seed-provenance.json').write_text(json.dumps({'schemaVersion':1,'clientBuild':3396210,'sdeUrl':manifest['sdeUrl'],'sdeArchiveSha256':digest,'marketSeedEngine':'v1','marketPreset':'jita_only','historyDays':7,'optionalContentPacks':False},indent=2)+'\n')
PY
rm -rf "$sde_dir" /tmp/evejs-sde.zip
