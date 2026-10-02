#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
ndk_path="${ANDROID_NDK_HOME:-${ANDROID_HOME:?Set ANDROID_HOME}/ndk/27.2.12479018}"
llvm_bin="$ndk_path/toolchains/llvm/prebuilt/linux-x86_64/bin"
build_dir="$repo_root/runtime-work/native"
mkdir -p "$build_dir" "$repo_root/app/src/main/jniLibs/arm64-v8a"
cd "$build_dir"
if [ ! -f talloc.tar.gz ]; then curl --fail --location --retry 3 https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz -o talloc.tar.gz; fi
echo 'dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd  talloc.tar.gz' | sha256sum --check
if [ ! -d talloc-2.4.3 ]; then tar -xzf talloc.tar.gz; fi
if [ ! -d proot ]; then git clone https://github.com/termux/proot.git proot; fi
git -C proot checkout 7266fb3e8516535682f5a9c8f3a7e70f6506eddb
if git -C proot apply --check "$repo_root/native/proot-acceleration.patch"; then
    git -C proot apply "$repo_root/native/proot-acceleration.patch"
else
    git -C proot apply --reverse --check "$repo_root/native/proot-acceleration.patch"
fi
if git -C proot apply --check "$repo_root/native/proot-sysvipc.patch"; then
    git -C proot apply "$repo_root/native/proot-sysvipc.patch"
else
    git -C proot apply --reverse --check "$repo_root/native/proot-sysvipc.patch"
fi
# This pinned revision omits the declaration header needed by modern Clang.
python3 - <<'PY'
from pathlib import Path
p=Path('proot/src/extension/ashmem_memfd/ashmem_memfd.c')
s=p.read_text()
if '#include <string.h>' not in s:p.write_text('#include <string.h>\n'+s)
# Preserve the loader offset calculation without depending on GNU awk.
m=Path('proot/src/GNUmakefile')
s=m.read_text().replace('readelf -s $< | awk -f loader/loader-info.awk > $@', 'python3 loader/loader-info.py $< > $@')
m.write_text(s)
Path('proot/src/loader/loader-info.py').write_text('''import subprocess,sys
symbols={}
for line in subprocess.check_output(['readelf','-s',sys.argv[1]],text=True).splitlines():
    cols=line.split()
    if len(cols)>=8 and cols[-1] in ('_start','pokedata_workaround'): symbols[cols[-1]]=int(cols[1],16)
print('#include <unistd.h>')
print('const ssize_t offset_to_pokedata_workaround=%d;' % (symbols['pokedata_workaround']-symbols['_start']))
''')
PY
export CC="$llvm_bin/aarch64-linux-android26-clang"
export AR="$llvm_bin/llvm-ar"
export RANLIB="$llvm_bin/llvm-ranlib"
export CFLAGS='-O2 -fPIC'
export LDFLAGS='-Wl,-z,max-page-size=16384'
cd talloc-2.4.3
if [ ! -f "$build_dir/prefix/lib/libtalloc.a" ]; then
cat > cross-answers.txt <<'ANSWERS'
Checking uname sysname type: "Linux"
Checking uname machine type: "aarch64"
Checking uname release type: "dontcare"
Checking uname version type: "dontcare"
Checking simple C program: OK
building library support: OK
Checking for large file support: OK
Checking for -D_FILE_OFFSET_BITS=64: OK
Checking for WORDS_BIGENDIAN: FAIL
Checking for C99 vsnprintf: OK
Checking for HAVE_SECURE_MKSTEMP: OK
rpath library support: OK
-Wl,--version-script support: FAIL
Checking correct behavior of strtoll: OK
Checking correct behavior of strptime: OK
Checking for HAVE_IFACE_GETIFADDRS: OK
Checking for HAVE_IFACE_IFCONF: OK
Checking for HAVE_IFACE_IFREQ: OK
Checking getconf LFS_CFLAGS: OK
Checking for large file support without additional flags: OK
Checking for working strptime: OK
Checking for HAVE_SHARED_MMAP: OK
Checking for HAVE_MREMAP: OK
Checking for HAVE_INCOHERENT_MMAP: OK
Checking getconf large file support flags work: OK
ANSWERS
./configure --prefix="$build_dir/prefix" --disable-rpath --disable-python --cross-compile --cross-answers=cross-answers.txt
make -j2
mkdir -p "$build_dir/prefix/include" "$build_dir/prefix/lib"
cp talloc.h "$build_dir/prefix/include/"
"$AR" rcs "$build_dir/prefix/lib/libtalloc.a" bin/default/talloc*.o
fi
cd "$build_dir/proot"
make -C src -j2 CC="$CC" LD="$CC" STRIP="$llvm_bin/llvm-strip" OBJCOPY="$llvm_bin/llvm-objcopy" OBJDUMP="$llvm_bin/llvm-objdump" \
    CPPFLAGS="-D_FILE_OFFSET_BITS=64 -D_GNU_SOURCE -I. -I$build_dir/proot/src -I$build_dir/prefix/include" \
    LDFLAGS="-L$build_dir/prefix/lib -ltalloc -Wl,-z,noexecstack,-z,max-page-size=16384" \
    PROOT_UNBUNDLE_LOADER=/unused
cp src/proot "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot.so"
cp src/loader/loader "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot-loader.so"
"$llvm_bin/llvm-strip" "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot.so"
"$llvm_bin/llvm-strip" "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot-loader.so"
"$llvm_bin/llvm-readelf" -h "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot.so"
if "$llvm_bin/llvm-readelf" -d "$repo_root/app/src/main/jniLibs/arm64-v8a/libproot.so" | grep -q 'libtalloc.so'; then
    echo 'Unexpected dynamic talloc dependency' >&2; exit 1
fi
# Bundle the exact modified source rather than offering a moving upstream URL.
# The release workflow publishes this archive beside every APK using this build.
mkdir -p "$repo_root/out" "$build_dir/corresponding-sources/proot" "$build_dir/corresponding-sources/build"
python3 - "$build_dir" "$repo_root" <<'PY'
import pathlib, shutil, subprocess, sys
work, root = map(pathlib.Path, sys.argv[1:])
source = work / 'corresponding-sources'
tracked = subprocess.check_output(['git', '-C', str(work / 'proot'), 'ls-files', '-z']).decode().split('\0')
for relative in filter(None, tracked + ['src/loader/loader-info.py']):
    origin = work / 'proot' / relative
    if not origin.is_file():
        continue
    target = source / 'proot' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origin, target)
shutil.copy2(work / 'talloc.tar.gz', source / 'talloc-2.4.3.tar.gz')
shutil.copy2(root / 'scripts/build-proot.sh', source / 'build/build-proot.sh')
for name in ('proot-acceleration.patch', 'proot-sysvipc.patch'):
    shutil.copy2(root / 'native' / name, source / 'build' / name)
(source / 'README.txt').write_text(
    'Corresponding sources for the ARM64 Android PRoot executable and loader.\n'
    'PRoot: https://github.com/termux/proot commit 7266fb3e8516535682f5a9c8f3a7e70f6506eddb, GPL-2.0-or-later.\n'
    'talloc 2.4.3: https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz, LGPL-3.0-or-later.\n'
    'proot/ contains the patched source actually compiled. talloc source is included as its original archive.\n'
    'build/ contains the repository build script and local patches; Android NDK 27.2.12479018, API26.\n'
    'Run build/build-proot.sh in a launcher checkout; it fetches the pinned pristine sources and applies these changes.\n'
    'The loader-info.py generated by that script is also included in proot/src/loader/.\n')
PY
tar -C "$build_dir/corresponding-sources" -czf "$repo_root/out/proot-corresponding-source.tar.gz" .
sha256sum "$repo_root/out/proot-corresponding-source.tar.gz"
