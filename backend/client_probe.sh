#!/bin/sh
# Exercise the pinned native Wine + FEX runtime without starting EVE.
set -eu
state=/client-state
mkdir -p "$state/prefix"
export WINEPREFIX="$state/prefix"
export WINEDEBUG=-all,err+all
export WINEARCH=win64
export WINEDLLOVERRIDES="winemenubuilder,mshtml,mscoree="
export FEX_DISABLETELEMETRY=1
export WINEESYNC=0
export WINEFSYNC=0
# A headless probe must never inherit a retail proxy or client launcher.
unset DISPLAY http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy || true
export NO_PROXY=127.0.0.1,localhost,::1
export no_proxy="$NO_PROXY"
if [ -f "$state/trust/evejs-ca.pem" ]; then
    export SSL_CERT_FILE="$state/trust/evejs-ca.pem"
fi
version=$(/opt/wine/bin/wine --version)
printf 'Native Wine: %s\n' "$version"
/usr/bin/python3.11 /opt/eve-android/client_prepare.py fixture --state "$state"
set +e
/opt/wine/bin/wine wineboot -u
boot=$?
printf 'Wine prefix initialization exit: %s\n' "$boot"
/opt/wine/bin/wine "$state/runtime-probe.exe"
result=$?
/opt/wine/bin/wineserver -w
set -e
printf 'Translated x64 PE exit: %s (expected 37)\n' "$result"
/usr/bin/python3.11 /opt/eve-android/client_prepare.py probe-result --state "$state" --exit-code "$result" --wine-version "$version"
