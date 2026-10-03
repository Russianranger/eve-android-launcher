#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
task_sources=("$task_root/app/src/main/java/io/github/russianranger/eve/RfbClient.java" "$task_root/app/src/main/java/io/github/russianranger/eve/DisplayPerformance.java" "$task_root/app/src/main/java/io/github/russianranger/eve/PointerMotion.java" "$task_root/tests/rfb_host/io/github/russianranger/eve/RfbHostTest.java")
if command -v javac >/dev/null 2>&1; then
    javac --release 17 -d "$task_build" "${task_sources[@]}"
else
    java --module jdk.compiler/com.sun.tools.javac.Main --release 17 -d "$task_build" "${task_sources[@]}"
fi
java -cp "$task_build" io.github.russianranger.eve.RfbHostTest
