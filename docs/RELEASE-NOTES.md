# EVE Android Launcher 0.1.4 — Wine certificate validation fix

The 0.1.3 certificate identity fix passed on the Thor. Its next attempt imported
and read back the private CA, negotiated TLS with the server, then stopped before
EVE launch with WinHTTP error 12157. The pinned Wine crypt32 wrongly applied an
excluded directoryName constraint to the server leaf's empty subject.

This update packages a narrow crypt32 correction from the same Wine commit and
compiler. The APK verifies the installed baseline and supplies the patched DLLs
through private client-session binds. A second small correction preserves
permitted-name detection across mixed DNS/IP constraints. Hostname, signature, expiry, exact CA,
DNS/IP and nonempty-subject constraints remain enforced. A real Wine regression
compares the baseline rejection with thirteen valid/invalid certificate cases.

Update without uninstalling or clearing app data. Preserve the accepted runtimes,
client cache, Wine prefix and world. No reimport, revalidation or repeat Wine/FEX
probe is needed. Start server → SERVER READY → Start EVE client → Open client
display → attempt local test login → Stop client → Save and stop server → export
the newest support ZIP. See [testing instructions](https://github.com/Russianranger/eve-android-launcher/blob/main/docs/TESTING.md).

Physical TLS, EVE startup/display and local login remain the next device gate.
