#!/usr/bin/env python3
"""Collect corresponding source for the exact binary runtime, failing if absent."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.request

destination = pathlib.Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
source_root = destination / 'vendor/evejs'
shutil.copytree('/opt/evejs', source_root, symlinks=True, dirs_exist_ok=True)
shutil.copytree('/usr/share/doc', destination / 'debian/licenses', symlinks=True, dirs_exist_ok=True)
shutil.copytree('/usr/share/eve-android', destination / 'provenance', dirs_exist_ok=True)
shutil.copy2('/etc/eve-server-runtime.json', destination / 'provenance/runtime.json')
offline_cargo = destination / '.cargo'
offline_cargo.mkdir(exist_ok=True)
offline_config = (destination / 'rust/config.toml').read_text().replace('/export/rust/vendor', 'rust/vendor')
(offline_cargo / 'config.toml').write_text(offline_config)

node_version = subprocess.check_output(['node', '-p', 'process.version'], text=True).strip()
node_name = 'node-' + node_version + '.tar.gz'
node_url = 'https://nodejs.org/dist/' + node_version + '/' + node_name
node_dir = destination / 'node'
node_dir.mkdir()
with urllib.request.urlopen('https://nodejs.org/dist/' + node_version + '/SHASUMS256.txt', timeout=120) as response:
    sums = response.read().decode()
(node_dir / 'SHASUMS256.txt').write_text(sums)
expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == node_name)
with urllib.request.urlopen(node_url, timeout=120) as response, (node_dir / node_name).open('wb') as output:
    shutil.copyfileobj(response, output)
with (node_dir / node_name).open('rb') as handle:
    actual = hashlib.file_digest(handle, 'sha256').hexdigest()
if actual != expected:
    raise SystemExit('Node.js corresponding-source checksum mismatch')

# Upgrade the runtime base packages first (Dockerfile) so the exact source
# versions remain obtainable from these Debian suites. Never substitute a
# newer source release for a shipped binary.
for path in pathlib.Path('/etc/apt/sources.list.d').glob('*.sources'):
    text = path.read_text().replace('Types: deb\n', 'Types: deb deb-src\n')
    path.write_text(text)
subprocess.run(['apt-get', 'update'], check=True)
package_records = pathlib.Path('/usr/share/eve-android/debian-packages.tsv').read_text().splitlines()
source_packages = sorted({(parts[2] or parts[0], parts[3] or parts[1]) for row in package_records if (parts := row.split('\t')) and len(parts) == 4})
debian_dir = destination / 'debian/source'
debian_dir.mkdir(parents=True)
for name, version in source_packages:
    subprocess.run(['apt-get', '--yes', '--download-only', 'source', name + '=' + version], cwd=debian_dir, check=True)

index = []
for path in sorted(destination.rglob('*')):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as handle:
            index.append({'file': str(path.relative_to(destination)), 'sizeBytes': path.stat().st_size, 'sha256': hashlib.file_digest(handle, 'sha256').hexdigest()})
(destination / 'SOURCE-INDEX.json').write_text(json.dumps({'schemaVersion': 1, 'files': index}, indent=2) + '\n')
(destination / 'README.md').write_text('''# EVE Android server runtime corresponding source

`vendor/evejs/` is EVE.js 0.12.9 and its locked production npm dependencies,
including better-sqlite3 source and SQLite. `rust/vendor/` contains the locked
market daemon/seeder crate sources; `rust/config.toml` supports offline cargo
builds from this archive's root through `.cargo/config.toml`. `node/` contains
the exact Node.js source archive with verified hashes.
`debian/source/` contains exact-version Debian source packages; package copyright
and license files are under `debian/licenses/`. Provenance and a per-file
checksum index accompany these sources.

Build with the repository's `server-runtime/Dockerfile` and
`scripts/build-server-runtime.sh` on a native ARM64 Docker host. No secret keys
or proprietary client assets are needed to build the server. The installed
runtime is ordinary GNU tar; the Android launcher accepts the matching runtime
and manifest for replacement builds. Keep these sources available beside the
binary release.
''')
