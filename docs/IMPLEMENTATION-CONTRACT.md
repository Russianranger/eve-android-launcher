# Initial pass contracts

Package: io.github.russianranger.eve; Java17; Android26+; ARM64 only.
APK 0.1.0, debug preview stable CI signature. No EVE retail assets in repo.

Shared RuntimeManager.java owned by root provides:
- static get(Context), final File home, serverRoot, clientRoot, serverState, clientState, clientContent, backend.
- interface Progress { void update(String message); }
- static text(File,String), read(File,int), sha256(File), copy(InputStream,File), remove(File).
- void download(String url,File target,String expectedSha256,Progress).
- void installTar(File archive,File destination,Progress) (staged GNU tar extraction).
- void assets() copies APK backend assets to private backend directory.
- Process guest(File root, Map<File,String> bindings, List<String> command, File log): ARM64 PRoot, /dev,/proc,/sys,tmp, cwd/, clean env HOME/root PATH/usr/local/bin:/usr/bin:/bin LANGC.UTF-8, takes explicit additional bindings; redirects output to log. Ensure all runtime scripts paths /opt/eve-android/<name>; caller binds backend there.
- int waitFor(Process,long seconds) (throws on timeout/nonzero).
- boolean serverInstalled(), JSONObject serverStatus(), void installServer(Progress), void prepareServer(Progress), void startServer(Progress), void stopServer(Progress), boolean serverAlive().
Server backend CLI: python3 /opt/eve-android/server_runtime.py {prepare,check,start}; guest uses /state bound to private serverState, /opt/evejs/config bound to serverState/config. Stop sentinel /state/run/stop. backend script supervises until exit for start and writes status.json atomically under /state/run. Fields phase (not_prepared/preparing/starting/running/stopping/stopped/failed), message, ready bool, error optional; prepared.json receipt inside /state root. Do not fake readiness from open TCP alone. Bound source /opt/evejs; ARM64 runtime release rootfs contains source, Node deps, native market daemon and generated static world seed under /opt/evejs-seed, etc/eve-server-runtime.json marker. Initial mobile profile reduced Rust market pool; optional content packs excluded initial pass. Never overwrite player saves on repeat prepare.
ClientRuntime agent owns Java ClientRuntime.java and backend client_prepare.py/client_probe.sh. Public-ish package methods ClientRuntime(Context), JSONObject status(), install(Progress), importZip(InputStream,Progress), validate(Progress), probe(Progress). Use matching RuntimeManager field names. Full gameplay rendering deferred until server qualification; import and binary patch/cert/runtime preparation should be concrete rather than pretend success. Exact build3396210, complete assets, no live EVE connection. Root will call these methods from service actions/UI.
