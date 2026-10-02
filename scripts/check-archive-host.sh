#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/.." && pwd)
test_build_dir=$(mktemp -d)
trap 'rm -rf "$test_build_dir"' EXIT
mapfile -d '' -t fixtures < <(find "$project_dir/tests/archive_host" -name '*.java' -print0)
# Some executor images retain the JDK compiler module without a javac launcher.
compiler=(javac)
if ! command -v javac >/dev/null 2>&1; then
  compiler=(java --module jdk.compiler/com.sun.tools.javac.Main)
fi
"${compiler[@]}" --release 17 -d "$test_build_dir" \
  "$project_dir/app/src/main/java/io/github/russianranger/eve/TarExtractor.java" \
  "${fixtures[@]}"
java -cp "$test_build_dir" io.github.russianranger.eve.ArchiveHostTest
