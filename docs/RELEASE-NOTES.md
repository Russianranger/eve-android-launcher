# EVE Android Launcher 0.1.2 — Client startup preview

Adds the first supervised launch of the prepared EVE 24.01 build 3396210 through
the existing Wine 10.13/FEX runtime. A basic 1280×720 loopback display provides
touch clicks, text entry and Tab/Enter/Esc for local startup and login testing.

The startup gate checks exact binaries/current preparation receipts, server
readiness, native outbound socket rejection, private Wine CA import/readback and
strict direct localhost TLS. An opt-in PRoot policy keeps client IP sockets local
and maps localhost:443 to the existing server gateway on port 26003; server sessions,
preparation and the independent Wine/FEX probe retain their previous behavior.

The foreground service owns both sessions, supports separate client stop and
recovery, and stops the client before saving/stopping the server. Child logs are
bounded and session receipts include process identities, routing/trust results
and memory diagnostics. Low available memory stops the client safely.

Update without clearing app data. Keep your accepted runtime installations,
imported client cache, Wine prefix and saved world. Start server → SERVER READY →
Start EVE client → Open client display → attempt local test login → Stop client →
Save and stop server → export support logs. See the included testing instructions.

Physical EVE startup/login remains a device gate. Process/display readiness alone
is not a login qualification. Graphics optimization, audio and controllers follow
that evidence. The immutable server runtime remains runtime-v1/Node 24.18.1;
0.1.0 and 0.1.1 releases remain available unchanged.
