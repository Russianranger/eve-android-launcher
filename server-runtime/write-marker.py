#!/usr/bin/env python3
"""Record the actual native ABI, exact upstream source and installed versions."""
import json
import pathlib
import subprocess

root = pathlib.Path('/opt/evejs')
upstream = json.loads((root / 'UPSTREAM.json').read_text())
versions = json.loads(subprocess.check_output(['node', '-p', 'JSON.stringify({node:process.version,architecture:process.arch,versions:process.versions})'], text=True))
if versions['architecture'] != 'arm64':
    raise SystemExit('Refusing to produce a non-native ARM64 runtime')
packages = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n'], text=True)
marker = {
    'format': 1,
    'schemaVersion': 1,
    'runtime': 'eve-server-1',
    'architecture': 'arm64',
    'evejsVersion': upstream['version'],
    'clientBuild': upstream['clientBuild'],
    'upstreamArchiveSha256': upstream['archiveSha256'],
    'sourceSha256': upstream['archiveSha256'],
    'node': versions,
    'marketSeedEngine': 'v1',
    'marketPreset': 'jita_only',
    'optionalContentPacks': False,
}
pathlib.Path('/etc/eve-server-runtime.json').write_text(json.dumps(marker, indent=2) + '\n')
notices = pathlib.Path('/usr/share/eve-android')
notices.mkdir(parents=True, exist_ok=True)
(notices / 'debian-packages.tsv').write_text(packages)
(notices / 'upstream.json').write_text(json.dumps(upstream, indent=2) + '\n')
