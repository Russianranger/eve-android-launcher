package io.github.russianranger.eve;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Private exact-build cache and tested Wine/FEX runtime; EVE launch is a later gate. */
final class ClientRuntime {
    private static final String RUNTIME = "fex-arm64ec-1";
    private static final String RELEASE = "https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.0/";
    private static final String ARCHIVE_HASH = "f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e";
    private static final String MANIFEST_HASH = "d375adf23b621f83ef7b5fff95365312377399704abb486fd8d4164a1fe29a13";
    private static final long MAX_ARCHIVE = 160L * 1024 * 1024 * 1024;
    private final Context context;
    private final RuntimeManager manager;

    ClientRuntime(Context context) {
        this.context = context.getApplicationContext();
        manager = RuntimeManager.get(this.context);
    }

    private JSONObject json(File file) throws Exception {
        return new JSONObject(RuntimeManager.read(file, 131072));
    }

    private boolean installed() {
        try {
            JSONObject marker = json(new File(manager.clientRoot, "etc/memento-client-runtime.json"));
            return marker.optInt("format") == 2 && "arm64".equals(marker.optString("architecture"))
                    && RUNTIME.equals(marker.optString("runtime"));
        } catch (Exception ignored) { return false; }
    }

    JSONObject status() throws Exception {
        JSONObject out = new JSONObject().put("runtime", RUNTIME).put("installed", installed())
                .put("supported_build", 3396210).put("client_launch_qualified", false)
                .put("phase", "missing_client").put("message", "Import the complete EVE build3396210 shared cache; gameplay is a later milestone");
        File status = new File(manager.clientState, "status.json");
        if (status.isFile()) {
            JSONObject preparation = json(status);
            out.put("preparation", preparation).put("phase", preparation.optString("phase"))
                    .put("message", preparation.optString("message"));
        }
        File content = new File(manager.clientContent, "eve-client-content.json");
        out.put("content_imported", content.isFile());
        if (content.isFile()) out.put("content", json(content));
        File probe = new File(manager.clientState, "probe.json");
        if (probe.isFile()) out.put("probe", json(probe));
        return out;
    }

    void install(RuntimeManager.Progress progress) throws Exception {
        if (installed()) { progress.update("Pinned Wine/FEX runtime already installed"); return; }
        manager.assets();
        manager.clientState.mkdirs();
        File archive = new File(context.getCacheDir(), "eve-client-runtime.tar.gz");
        File manifest = new File(context.getCacheDir(), "eve-client-runtime-manifest.json");
        try {
            manager.download(RELEASE + "client-runtime-manifest.json", manifest, MANIFEST_HASH, progress);
            JSONObject info = json(manifest);
            if (!RUNTIME.equals(info.optString("runtime")) || !ARCHIVE_HASH.equals(info.optString("sha256")))
                throw new IOException("Pinned Wine/FEX manifest identity failed");
            manager.download(RELEASE + "client-runtime-arm64.tar.gz", archive, ARCHIVE_HASH, progress);
            manager.installTar(archive, manager.clientRoot, progress);
            if (!installed()) throw new IOException("Client runtime marker identity failed");
            for (String relative : Arrays.asList("usr/bin/python3.11", "opt/wine/bin/wine", "opt/wine/bin/wineserver",
                    "opt/wine/lib/wine/aarch64-windows/libarm64ecfex.dll", "opt/wine/lib/wine/aarch64-windows/libwow64fex.dll"))
                if (!new File(manager.clientRoot, relative).isFile()) throw new IOException("Incomplete Wine/FEX runtime: " + relative);
            for (String name : Arrays.asList("wine", "wineserver")) {
                try (FileInputStream source = new FileInputStream(new File(manager.clientRoot, "opt/wine/bin/" + name))) {
                    byte[] header = new byte[20];
                    int count = 0;
                    while (count < header.length) { int read = source.read(header, count, header.length - count); if (read < 0) break; count += read; }
                    if (count != header.length || header[0] != 127 || header[1] != 'E' || header[2] != 'L' || header[3] != 'F'
                            || header[4] != 2 || header[5] != 1 || (header[18] & 255) != 183 || header[19] != 0)
                        throw new IOException("Wine executable must be native ARM64: " + name);
                }
            }
            progress.update("Pinned ARM64 Wine/FEX installed; runtime probe is available");
        } finally { archive.delete(); manifest.delete(); }
    }

    void importZip(InputStream source, RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        manager.clientState.mkdirs();
        File archive = new File(manager.clientState, "client-import.zip");
        long size = 0, lastProgress = 0;
        try {
            progress.update("Copying the complete shared cache ZIP to private storage");
            try (InputStream input = source; FileOutputStream output = new FileOutputStream(archive)) {
                byte[] buffer = new byte[1024 * 1024];
                for (int read; (read = input.read(buffer)) != -1;) {
                    if (Thread.currentThread().isInterrupted()) throw new InterruptedException("Client import cancelled");
                    size += read;
                    if (size > MAX_ARCHIVE) throw new IOException("Client ZIP exceeds 160 GiB import limit");
                    if (manager.clientState.getUsableSpace() < 512L * 1024 * 1024) throw new IOException("Not enough free internal storage for client import");
                    output.write(buffer, 0, read);
                    long now = System.currentTimeMillis();
                    if (now - lastProgress >= 1000) { progress.update("Copied " + (size / 1024 / 1024) + " MiB of client ZIP"); lastProgress = now; }
                }
            }
            runPreparation("import", progress);
        } finally { archive.delete(); }
    }

    void validate(RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        runPreparation("validate", progress);
    }

    void probe(RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        manager.assets();
        manager.clientState.mkdirs();
        Map<File, String> bindings = bindings();
        File log = new File(manager.clientState, "logs/client-probe.log");
        File probe = new File(manager.clientState, "probe.json");
        RuntimeManager.text(probe, new JSONObject().put("phase", "probing").put("translated_x64_probe_passed", false)
                .put("client_launch_qualified", false).put("message", "Testing Wine/FEX x64 execution").toString());
        try {
            Process process = manager.guest(manager.clientRoot, bindings,
                    Arrays.asList("/bin/sh", "/opt/eve-android/client_probe.sh"), log);
            await(process, 180, "Probing Wine/FEX x64 execution", progress, log);
            JSONObject report = json(probe);
            if (!report.optBoolean("translated_x64_probe_passed")) throw new IOException("Wine/FEX probe did not pass; export support logs");
            progress.update("Wine/FEX executed x64 code. EVE login and rendering remain to be qualified");
        } catch (Exception error) {
            RuntimeManager.text(probe, new JSONObject().put("phase", "runtime_probe_failed").put("translated_x64_probe_passed", false)
                    .put("client_launch_qualified", false).put("error", String.valueOf(error.getMessage()))
                    .put("message", "Wine/FEX execution failed; export support logs").toString());
            throw error;
        }
    }

    private void requireRuntime() throws IOException {
        if (!installed()) throw new IOException("Install the client Wine/FEX runtime first");
    }

    private Map<File, String> bindings() {
        Map<File, String> bindings = new LinkedHashMap<>();
        manager.clientContent.getParentFile().mkdirs();
        manager.serverState.mkdirs();
        bindings.put(manager.backend, "/opt/eve-android");
        bindings.put(manager.clientState, "/client-state");
        bindings.put(manager.serverState, "/server-state");
        bindings.put(manager.clientContent.getParentFile(), "/client-storage");
        return bindings;
    }

    private void runPreparation(String action, RuntimeManager.Progress progress) throws Exception {
        manager.assets();
        manager.clientState.mkdirs();
        File log = new File(manager.clientState, "logs/client-prepare.log");
        List<String> command = new ArrayList<>(Arrays.asList("/usr/bin/python3.11", "/opt/eve-android/client_prepare.py", action,
                "--content", "/client-storage/" + manager.clientContent.getName(), "--state", "/client-state"));
        if (action.equals("import")) command.addAll(Arrays.asList("--archive", "/client-state/client-import.zip"));
        Process process = manager.guest(manager.clientRoot, bindings(), command, log);
        await(process, action.equals("import") ? 10800 : 3600, "Checking client binaries and offline resources", progress, log);
        JSONObject state = json(new File(manager.clientState, "status.json"));
        progress.update(state.optString("message", "Client preparation finished"));
    }

    private void await(Process process, int timeout, String task, RuntimeManager.Progress progress, File log) throws Exception {
        long started = System.nanoTime();
        try {
            while (!process.waitFor(1, TimeUnit.SECONDS)) {
                long elapsed = TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - started);
                if (elapsed > timeout) throw new IOException(task + " timed out; export support logs");
                if (elapsed % 5 == 0) progress.update(task + " · " + elapsed + " seconds");
            }
            if (process.exitValue() != 0) {
                String error = "";
                File status = new File(manager.clientState, "status.json");
                if (!log.getName().equals("client-probe.log") && status.isFile()) try { error = json(status).optString("error"); } catch (Exception ignored) { }
                throw new IOException(error.isEmpty() ? task + " failed; export support logs (" + log.getName() + ")" : error);
            }
        } finally {
            if (process.isAlive()) { process.destroy(); if (!process.waitFor(3, TimeUnit.SECONDS)) process.destroyForcibly(); }
        }
    }
}
