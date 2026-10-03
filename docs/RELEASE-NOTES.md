# EVE Android Launcher 0.1.3 — Certificate preflight hotfix

Fixes the false "The local server CA changed" error reported on the Thor in
0.1.2. Client preparation normalized CRLF PEM text to LF, but startup compared
raw file hashes. The identical certificate was rejected even after successful
revalidation of all 125,116 resources. Startup now compares decoded DER
certificate identity, accepts existing receipts and equivalent private copies,
and still rejects a genuinely different CA.

Wine TLS failures now show the helper stage and Windows error code alongside
the detailed log, making the next device result easier to diagnose.

Update without uninstalling or clearing app data. Keep the accepted runtimes,
client cache, Wine prefix and world. No reimport, revalidation or repeat Wine/FEX
probe is needed. Start server → SERVER READY → Start EVE client → Open client
display → attempt local test login → Stop client → Save and stop server → export
the newest support ZIP. See [testing instructions](https://github.com/Russianranger/eve-android-launcher/blob/main/docs/TESTING.md).

The failed 0.1.2 attempt stopped before Wine/EVE launch; physical startup, display
and local login remain unqualified. Server runtime-v1/Node 24.18.1 and the pinned
Wine/FEX binaries are unchanged. Earlier accepted server, probe and import gates
remain accepted.
