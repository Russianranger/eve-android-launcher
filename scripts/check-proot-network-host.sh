#!/usr/bin/env bash
# Native PRoot policy proof: prepare with networking, run in an isolated container.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 2 ]; then
    echo 'Usage: check-proot-network-host.sh --prepare|--run ABSOLUTE_WORK_DIR' >&2
    exit 2
fi
work_dir="$(realpath -m "$2")"
case "$1" in
    --prepare)
        mkdir -p "$work_dir"
        if [ -e "$work_dir/proot" ]; then
            echo 'Use a fresh work directory for native source preparation' >&2
            exit 2
        fi
        curl --fail --location --retry 3 https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz -o "$work_dir/talloc.tar.gz"
        (cd "$work_dir"; echo 'dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd  talloc.tar.gz' | sha256sum --check)
        git init "$work_dir/proot"
        git -C "$work_dir/proot" remote add origin https://github.com/termux/proot.git
        git -C "$work_dir/proot" fetch --depth=1 origin 7266fb3e8516535682f5a9c8f3a7e70f6506eddb
        git -C "$work_dir/proot" checkout --detach FETCH_HEAD
        for patch in proot-acceleration.patch proot-sysvipc.patch eve-client-network.patch; do
            git -C "$work_dir/proot" apply "$repo_root/native/$patch"
        done
        mkdir -p "$work_dir/proot/src/extension/eve_client_network"
        cp "$repo_root/native/eve-client-network.c" "$work_dir/proot/src/extension/eve_client_network/eve_client_network.c"
        # Match the Android build's declaration/loader-generation compatibility
        # changes while compiling this fixture natively with its own libc.
        python3 - "$work_dir/proot" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
path = root / 'src/extension/ashmem_memfd/ashmem_memfd.c'
raw = path.read_text()
if '#include <string.h>' not in raw:
    path.write_text('#include <string.h>\n' + raw)
path = root / 'src/GNUmakefile'
path.write_text(path.read_text().replace('readelf -s $< | awk -f loader/loader-info.awk > $@',
                                        'python3 loader/loader-info.py $< > $@'))
(root / 'src/loader/loader-info.py').write_text('''import subprocess,sys
symbols={}
for line in subprocess.check_output(['readelf','-s',sys.argv[1]],text=True).splitlines():
    cols=line.split()
    if len(cols)>=8 and cols[-1] in ('_start','pokedata_workaround'): symbols[cols[-1]]=int(cols[1],16)
print('#include <unistd.h>')
print('const ssize_t offset_to_pokedata_workaround=%d;' % (symbols['pokedata_workaround']-symbols['_start']))
''')
PY
        ;;
    --run)
        # The Python runner independently checks interfaces/routes before its
        # negative syscalls. No source/dependency retrieval occurs in this mode.
        python3 "$repo_root/tests/build-network-proot.py" --prepared "$work_dir" --work-dir "$work_dir/native"
        python3 "$repo_root/tests/check-network-policy.py" \
            --baseline "$work_dir/native/proot-baseline" \
            --candidate "$work_dir/native/proot-entry-only" \
            --loader "$work_dir/native/source/proot/src/loader/loader" \
            --output "$work_dir/network-policy-result.json"
        ;;
    *)
        echo 'Expected --prepare or --run' >&2
        exit 2
        ;;
esac
