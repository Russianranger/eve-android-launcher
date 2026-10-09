package io.github.russianranger.eve;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Debug;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.FileWriter;
import java.io.Writer;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Exact-build cache, Wine/FEX preparation and a supervised basic client session. */
final class ClientRuntime {
    private static final String RUNTIME = "fex-arm64ec-1";
    private static final String RELEASE = "https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.0/";
    private static final String ARCHIVE_HASH = "f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e";
    private static final String MANIFEST_HASH = "d375adf23b621f83ef7b5fff95365312377399704abb486fd8d4164a1fe29a13";
    private static final long MAX_ARCHIVE = 160L * 1024 * 1024 * 1024;
    private static final long MIN_FREE_MEMORY = 1024L * 1024 * 1024;
    private static final List<String> PERFORMANCE_OPTIONS = Arrays.asList("early-display-requests", "disable-concurrent-binning",
            "disable-lrcpc2", "a740-pc-mode", "linear-presentation", "sysmem-rendering", "shm-presentation", "separate-display-surface");
    private final Context context;
    private final RuntimeManager manager;
    private static volatile Process session;

    ClientRuntime(Context context) {
        this.context = context.getApplicationContext();
        manager = RuntimeManager.get(this.context);
    }

    String renderer() {
        return context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).getBoolean("use-adreno", true) ? "turnip-dxvk" : "software";
    }

    void useAdreno(boolean enabled) {
        if (alive() || RuntimeService.busy) throw new IllegalStateException("Stop the client before changing its renderer");
        context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit().putBoolean("use-adreno", enabled).apply();
    }

    String performanceProfile() {
        // A new key restores the accepted baseline once when upgrading from
        // the regressed 0.1.12 combined default. Later explicit trials persist.
        String value = context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE)
                .getString("performance-profile-v2", "responsive");
        return Arrays.asList("responsive", "render60", "queue2", "display60", "throughput").contains(value) ? value : "responsive";
    }

    void setPerformanceProfile(String profile) {
        if (!Arrays.asList("responsive", "render60", "queue2", "display60", "throughput").contains(profile))
            throw new IllegalArgumentException("Choose a supported performance profile");
        if (alive() || RuntimeService.busy) throw new IllegalStateException("Stop the client before changing its performance settings");
        context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit()
                .putString("performance-profile-v2", profile).apply();
    }

    boolean earlyDisplayRequests() { return performanceOption("early-display-requests"); }
    boolean disableConcurrentBinning() { return performanceOption("disable-concurrent-binning"); }
    boolean disableLrcpc2() { return performanceOption("disable-lrcpc2"); }
    boolean a740PcMode() { return renderer().equals("turnip-dxvk") && performanceOption("a740-pc-mode"); }
    boolean linearPresentation() { return renderer().equals("turnip-dxvk") && performanceOption("linear-presentation"); }
    boolean sysmemRendering() { return renderer().equals("turnip-dxvk") && performanceOption("sysmem-rendering"); }
    boolean shmPresentation() { return renderer().equals("turnip-dxvk") && performanceOption("shm-presentation"); }
    boolean separateDisplaySurface() { return performanceOption("separate-display-surface"); }

    boolean performanceOption(String key) {
        try { return context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).getBoolean(key, false); }
        catch (ClassCastException ignored) { return false; }
    }

    void setPerformanceOption(String key, boolean enabled) {
        if (!PERFORMANCE_OPTIONS.contains(key))
            throw new IllegalArgumentException("Choose a supported performance option");
        if (alive() || RuntimeService.busy) throw new IllegalStateException("Stop the client before changing its performance settings");
        android.content.SharedPreferences.Editor edit = context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE)
                .edit().putBoolean(key, enabled);
        if (enabled && key.equals("shm-presentation")) edit.putBoolean("a740-pc-mode", false);
        if (enabled && key.equals("a740-pc-mode")) edit.putBoolean("shm-presentation", false);
        edit.apply();
    }

    void restoreBaselineSettings() {
        if (alive() || RuntimeService.busy) throw new IllegalStateException("Stop the client before restoring baseline settings");
        android.content.SharedPreferences.Editor edit = context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit()
                .putString("performance-profile-v2", "responsive");
        for (String key : PERFORMANCE_OPTIONS) edit.putBoolean(key, false);
        edit.apply();
    }

    String performanceSummary() {
        String profile = performanceProfile();
        boolean software = renderer().equals("software");
        int render = Arrays.asList("render60", "throughput").contains(profile) ? 60 : 30;
        int queue = Arrays.asList("queue2", "throughput").contains(profile) ? 2 : 1;
        int display = Arrays.asList("display60", "throughput").contains(profile) ? 60 : 30;
        String caps = (software ? "Saved GPU caps: " : profile.equals("responsive") ? "Baseline caps: " : "Selected caps: ")
                + "render " + render + " FPS · queue " + queue + (queue == 1 ? " frame" : " frames") + " · display " + display + " FPS";
        String[] labels = {"Early display requests", "Concurrent binning disabled", "Alternate CPU load instructions",
                "A740 driver", "Reduce GPU frame copies", "Direct GPU rendering", "Shared-memory frame transport", "Separate display surface"};
        List<String> selected = new ArrayList<>();
        for (int index = 0; index < PERFORMANCE_OPTIONS.size(); index++) {
            String key = PERFORMANCE_OPTIONS.get(index);
            if (performanceOption(key)) selected.add(labels[index] + (software
                    ? key.equals("early-display-requests") || key.equals("separate-display-surface") ? " (active)" : " (inactive in software)" : ""));
        }
        return caps + "\n" + (software ? "Saved experiments: " : "Selected experiments: ")
                + (selected.isEmpty() ? "none" : String.join(", ", selected));
    }

    boolean diagnosticHud() {
        return context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).getBoolean("diagnostic-hud", false);
    }

    void setDiagnosticHud(boolean enabled) {
        if (alive() || RuntimeService.busy) throw new IllegalStateException("Stop the client before changing its performance settings");
        context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit().putBoolean("diagnostic-hud", enabled).apply();
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
        JSONObject out = new JSONObject().put("runtime", RUNTIME).put("installed", installed()).put("selectedGraphicsMode", renderer())
                .put("selectedPerformanceProfile", performanceProfile()).put("diagnosticHud", diagnosticHud())
                .put("earlyDisplayRequests", earlyDisplayRequests()).put("disableConcurrentBinning", disableConcurrentBinning())
                .put("disableLrcpc2", disableLrcpc2()).put("a740PcMode", a740PcMode())
                .put("linearPresentation", linearPresentation()).put("requestedLinearPresentation", performanceOption("linear-presentation"))
                .put("sysmemRendering", sysmemRendering()).put("requestedSysmemRendering", performanceOption("sysmem-rendering"))
                .put("shmPresentation", shmPresentation()).put("requestedShmPresentation", performanceOption("shm-presentation"))
                .put("separateDisplaySurface", separateDisplaySurface())
                .put("supported_build", 3396210).put("client_launch_qualified", false)
                .put("phase", "missing_client").put("message", "Import the complete EVE build 3396210 shared cache first");
        File status = new File(manager.clientState, "status.json");
        if (status.isFile()) {
            JSONObject preparation = json(status);
            out.put("preparation", preparation).put("phase", preparation.optString("phase"))
                    .put("message", preparation.optString("message"));
            if (preparation.optString("phase").equals("content_prepared"))
                out.put("message", "Exact client and asset cache prepared. Start the server, then Start EVE client.");
            boolean running = RuntimeService.busy && Arrays.asList("import-client", "validate-client", "resume-client")
                    .contains(RuntimeService.operation);
            if (!running && Arrays.asList("copying", "extracting", "validating", "checking_resources", "checking_binaries", "preparing_trust")
                    .contains(preparation.optString("phase"))) {
                out.put("phase", "preparation_interrupted").put("message",
                        "Client preparation was interrupted. Resume the saved import, or validate existing content.");
            }
        }
        out.put("resumable_import", new File(manager.clientState, "client-import.zip").isFile());
        File content = new File(manager.clientContent, "eve-client-content.json");
        out.put("content_imported", content.isFile());
        if (content.isFile()) out.put("content", json(content));
        File probe = new File(manager.clientState, "probe.json");
        if (probe.isFile()) out.put("probe", json(probe));
        JSONObject client = sessionStatus();
        out.put("session", client).put("alive", client.optBoolean("alive")).put("ready", client.optBoolean("ready"));
        if (client.optBoolean("alive") || Arrays.asList("failed", "stopping").contains(client.optString("phase")))
            out.put("phase", client.optString("phase")).put("message", client.optString("message", "Client session is active"));
        return out;
    }

    void install(RuntimeManager.Progress progress) throws Exception {
        requireClientStopped();
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
        requireServerStopped();
        requireClientStopped();
        manager.clientState.mkdirs();
        File archive = new File(manager.clientState, "client-import.zip");
        File incoming = new File(manager.clientState, "client-import.zip.incoming");
        long size = 0, lastProgress = 0;
        boolean copied = false;
        try {
            progress.update("Copying the complete shared cache ZIP to private storage");
            writePreparationStatus("copying", "Copying the complete shared cache ZIP to private storage", "");
            try (InputStream input = source; FileOutputStream output = new FileOutputStream(incoming)) {
                byte[] buffer = new byte[1024 * 1024];
                for (int read; (read = input.read(buffer)) != -1;) {
                    if (Thread.currentThread().isInterrupted()) throw new InterruptedException("Client import cancelled");
                    size += read;
                    if (size > MAX_ARCHIVE) throw new IOException("Client ZIP exceeds 160 GiB import limit");
                    if (manager.clientState.getUsableSpace() < 512L * 1024 * 1024) throw new IOException("Not enough free internal storage for client import");
                    output.write(buffer, 0, read);
                    long now = System.currentTimeMillis();
                    if (now - lastProgress >= 1000) {
                        ActivityManager.MemoryInfo memory = memoryInfo();
                        if (underMemoryPressure(memory)) recordMemory(0, Long.MAX_VALUE, memory);
                        progress.update("Copied " + (size / 1024 / 1024) + " MiB of client ZIP"); lastProgress = now;
                    }
                }
                output.getFD().sync();
            }
            Files.move(incoming.toPath(), archive.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            copied = true;
            runPreparation("import", progress);
            archive.delete();
        } catch (Exception error) {
            if (!copied) writePreparationStatus("copy_failed", "Client ZIP copy stopped. Any previous saved import is preserved.", String.valueOf(error.getMessage()));
            throw error;
        } finally { incoming.delete(); }
    }

    void validate(RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        requireServerStopped();
        requireClientStopped();
        runPreparation("validate", progress);
    }

    void resume(RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        requireServerStopped();
        requireClientStopped();
        File archive = new File(manager.clientState, "client-import.zip");
        if (!archive.isFile()) throw new IOException("No saved complete import ZIP is available. Import the client ZIP again.");
        progress.update("Resuming the saved client import without copying its ZIP again");
        runPreparation("resume", progress);
        archive.delete();
    }

    void probe(RuntimeManager.Progress progress) throws Exception {
        requireRuntime();
        requireClientStopped();
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

    private void requireServerStopped() throws IOException {
        if (manager.serverAlive()) throw new IOException("Save and stop the server before importing or validating client content");
    }

    private void requireClientStopped() throws IOException {
        if (alive()) throw new IOException("Stop the client before changing or probing its runtime or imported content");
    }

    private JSONObject sessionReport() {
        try { return json(new File(manager.clientState, "run/status.json")); }
        catch (Exception ignored) { return new JSONObject(); }
    }

    private boolean identityAlive(JSONObject identity) {
        if (identity == null) return false;
        try {
            int pid = identity.getInt("pid");
            if (pid <= 0) return false;
            String stat = RuntimeManager.read(new File("/proc/" + pid + "/stat"), 8192);
            String[] fields = stat.substring(stat.lastIndexOf(')') + 2).trim().split("\\s+");
            return fields.length > 19 && !fields[0].equals("Z") && fields[19].equals(identity.getString("startTicks"));
        } catch (Exception ignored) { return false; }
    }

    boolean alive() {
        Process current = session;
        return (current != null && current.isAlive()) || identityAlive(sessionReport().optJSONObject("supervisorIdentity"));
    }

    JSONObject sessionStatus() throws Exception {
        JSONObject state = sessionReport();
        boolean running = alive();
        state.put("alive", running).put("ready", running && state.optBoolean("ready") && state.optString("phase").equals("running"));
        if (!running && !RuntimeService.busy && Arrays.asList("running", "starting", "stopping").contains(state.optString("phase")))
            state.put("phase", "stopped").put("ready", false)
                    .put("message", "The previous client session is closed. Start the client to check it again.");
        if (!state.has("message")) state.put("message", "Client stopped");
        return state;
    }

    void start(RuntimeManager.Progress progress) throws Exception {
        if (alive()) { progress.update(sessionStatus().optString("message")); return; }
        requireRuntime();
        if (!manager.serverStatus().optBoolean("ready")) throw new IOException("Start the server and wait for SERVER READY before starting the client");
        if (!new File(manager.clientContent, "eve-client-content.json").isFile())
            throw new IOException("Import and prepare the exact client build3396210 first");
        JSONObject preparation = json(new File(manager.clientState, "status.json"));
        if (!preparation.optString("phase").equals("content_prepared"))
            throw new IOException("Complete Validate and prepare client before starting it");
        JSONObject probe = json(new File(manager.clientState, "probe.json"));
        if (!probe.optBoolean("translated_x64_probe_passed")) throw new IOException("Pass Probe Wine / FEX before starting the client");
        manager.assets();
        RuntimeManager.mkdir(new File(manager.clientState, "run"));
        String graphicsMode = renderer();
        String performanceProfile = performanceProfile();
        boolean diagnosticHud = diagnosticHud();
        new File(manager.clientState, "run/stop").delete();
        JSONObject pending = new JSONObject().put("phase", "starting").put("ready", false).put("cleanShutdown", false)
                .put("message", "Starting EVE with " + (graphicsMode.equals("turnip-dxvk") ? "Adreno GPU rendering…" : "software recovery rendering…")).put("graphicsMode", graphicsMode).put("client_launch_qualified", false)
                .put("performanceProfile", performanceProfile).put("diagnosticHud", diagnosticHud)
                .put("earlyDisplayRequests", earlyDisplayRequests()).put("disableConcurrentBinning", disableConcurrentBinning())
                .put("disableLrcpc2", disableLrcpc2()).put("a740PcMode", a740PcMode())
                .put("linearPresentation", linearPresentation()).put("requestedLinearPresentation", performanceOption("linear-presentation"))
                .put("sysmemRendering", sysmemRendering()).put("requestedSysmemRendering", performanceOption("sysmem-rendering"))
                .put("shmPresentation", shmPresentation()).put("requestedShmPresentation", performanceOption("shm-presentation"))
                .put("separateDisplaySurface", separateDisplaySurface())
                .put("login_qualified", false).put("graphics_qualified", false);
        RuntimeManager.text(new File(manager.clientState, "run/status.json"), pending.toString());
        List<String> launch = launchCommand(graphicsMode, performanceProfile, diagnosticHud);
        session = manager.guest(manager.clientRoot, sessionBindings(graphicsMode), launch,
                new File(manager.clientState, "logs/client-supervisor.log"), true);
        long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(6);
        try {
            while (System.nanoTime() < deadline) {
                RuntimeManager.cancelled();
                JSONObject state = sessionStatus();
                progress.update(state.optString("message", "Waiting for the client display and process…"));
                if (state.optBoolean("ready")) return;
                if (!alive()) {
                    String detail = state.optString("error");
                    throw new IOException(detail.isEmpty() ? state.optString("message", "Client closed during startup; export support logs") : detail);
                }
                Thread.sleep(500);
            }
            throw new IOException("Client has not become ready within 6 minutes; export support logs");
        } catch (Exception error) {
            requestStop();
            throw error;
        }
    }

    List<String> launchCommand(String graphicsMode, String performanceProfile, boolean diagnosticHud) {
        List<String> launch = new ArrayList<>(Arrays.asList("/usr/bin/python3.11", "/opt/eve-android/client_runtime.py", "start",
                "--content", "/client", "--state", "/client-state", "--server-state", "/server-state", "--graphics-mode", graphicsMode,
                "--performance-profile", performanceProfile));
        if (diagnosticHud) launch.add("--diagnostic-hud");
        if (disableConcurrentBinning()) launch.add("--disable-concurrent-binning");
        if (disableLrcpc2()) launch.add("--disable-lrcpc2");
        if (graphicsMode.equals("turnip-dxvk") && a740PcMode()) launch.add("--a740-pc-mode");
        if (graphicsMode.equals("turnip-dxvk") && linearPresentation()) launch.add("--linear-presentation");
        if (graphicsMode.equals("turnip-dxvk") && sysmemRendering()) launch.add("--sysmem-rendering");
        if (graphicsMode.equals("turnip-dxvk") && shmPresentation()) launch.add("--shm-presentation");
        return launch;
    }

    void requestStop() throws IOException {
        RuntimeManager.text(new File(manager.clientState, "run/stop"), "stop\n");
    }

    void stop(RuntimeManager.Progress progress) throws Exception {
        Process current = session;
        requestStop();
        if (!alive()) {
            if (new File(manager.clientState, "run/processes.json").isFile()) {
                requireRuntime(); manager.assets();
                progress.update("Recovering the recorded client processes…");
                Process recovery = manager.guest(manager.clientRoot, bindings(true), Arrays.asList("/usr/bin/python3.11", "/opt/eve-android/client_runtime.py", "recover",
                        "--content", "/client", "--state", "/client-state", "--server-state", "/server-state"),
                        new File(manager.clientState, "logs/client-supervisor.log"), true);
                RuntimeManager.waitFor(recovery, 120);
                if (!sessionReport().optBoolean("cleanShutdown")) throw new IOException("Recovered client required forced cleanup; export support logs");
                progress.update("Recorded client processes recovered and stopped.");
            } else progress.update("Client is stopped.");
            return;
        }
        progress.update("Stopping the EVE client and display…");
        if (current != null && current.isAlive()) {
            if (!current.waitFor(120, TimeUnit.SECONDS)) throw new IOException("Client cleanup is still pending; keep the app open and export support logs");
            session = null;
            if (current.exitValue() != 0) throw new IOException("Client stopped with a cleanup error; export support logs");
        } else {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120);
            while (alive() && System.nanoTime() < deadline) { RuntimeManager.cancelled(); Thread.sleep(500); }
            if (alive()) throw new IOException("Recovered client cleanup is still pending; export support logs");
        }
        if (!sessionReport().optBoolean("cleanShutdown")) throw new IOException("Client closed without a clean shutdown receipt; export support logs");
        progress.update("Client and display stopped.");
    }

    private void writePreparationStatus(String phase, String message, String error) throws Exception {
        File status = new File(manager.clientState, "status.json");
        JSONObject previous = new JSONObject();
        if (status.isFile()) try { previous = json(status); } catch (Exception ignored) { /* Keep a writable failure receipt even after malformed status. */ }
        RuntimeManager.text(status, previous
                .put("phase", phase).put("message", message).put("error", error)
                .put("client_launch_qualified", false).toString());
    }

    private Map<File, String> bindings() {
        Map<File, String> bindings = new LinkedHashMap<>();
        manager.clientContent.getParentFile().mkdirs();
        manager.serverState.mkdirs();
        bindings.put(manager.backend, "/opt/eve-android");
        bindings.put(manager.clientState, "/client-state");
        bindings.put(manager.serverState, "/server-state");
        bindings.put(manager.clientContent.getParentFile(), "/client-storage");
        if (manager.clientContent.isDirectory()) bindings.put(manager.clientContent, "/client");
        return bindings;
    }

    private Map<File, String> bindings(boolean trustOverlay) throws Exception {
        Map<File, String> result = bindings();
        if (!trustOverlay) return result;
        JSONObject manifest = json(new File(manager.backend, "wine-trust-overlay.json"));
        JSONObject marker = json(new File(manager.clientRoot, "etc/memento-client-runtime.json"));
        String wineCommit = "a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29";
        if (manifest.optInt("format") != 1 || !"wine-empty-subject-1".equals(manifest.optString("overlay"))
                || !RUNTIME.equals(manifest.optString("runtime")) || !wineCommit.equals(manifest.optString("wine_commit"))
                || !wineCommit.equals(marker.optString("wine_commit")))
            throw new IOException("The private Wine trust fix does not match the pinned runtime; export support logs");
        JSONArray files = manifest.getJSONArray("files");
        if (files.length() != 2) throw new IOException("Invalid Wine trust overlay file list");
        java.util.HashSet<String> targets = new java.util.HashSet<>();
        for (int index = 0; index < files.length(); index++) {
            JSONObject item = files.getJSONObject(index);
            String asset = item.getString("asset"), target = item.getString("target");
            String architecture = asset.equals("wine-crypt32-aarch64.dll") ? "aarch64" : asset.equals("wine-crypt32-i386.dll") ? "i386" : "";
            if (architecture.isEmpty() || !target.equals("opt/wine/lib/wine/" + architecture + "-windows/crypt32.dll")
                    || !targets.add(target)) throw new IOException("Invalid Wine trust overlay path");
            File source = new File(manager.backend, asset), original = new File(manager.clientRoot, target);
            if (!source.isFile() || Files.isSymbolicLink(source.toPath()) || !original.isFile()
                    || Files.isSymbolicLink(original.toPath())
                    || !RuntimeManager.sha256(source).equals(item.getString("sha256"))
                    || !RuntimeManager.sha256(original).equals(item.getString("baselineSha256")))
                throw new IOException("The private Wine trust fix is missing or damaged; export support logs");
            result.put(source, "/" + target);
        }
        return result;
    }

    private Map<File, String> sessionBindings(String mode) throws Exception {
        Map<File, String> result = bindings(true);
        if (mode.equals("software")) return result;
        if (!mode.equals("turnip-dxvk")) throw new IOException("Unsupported client renderer");
        if (!new File(manager.clientState, "prefix/system.reg").isFile()
                || !new File(manager.clientState, "prefix/drive_c/windows/system32").isDirectory())
            throw new IOException("Pass the Wine / FEX probe to initialize the prefix before GPU rendering");
        JSONObject manifest = json(new File(manager.backend, "client-graphics-bundle.json"));
        if (manifest.optInt("format") != 1 || !manifest.optString("bundle").equals("eve-turnip-dxvk-2")
                || !manifest.optString("runtime").equals(RUNTIME)
                || !manifest.optString("wine_commit").equals("a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29")
                || !manifest.optString("mesa").equals("26.0.0") || !manifest.optString("dxvk").equals("2.4.1"))
            throw new IOException("GPU assets do not match the pinned runtime");
        JSONObject files = manifest.getJSONObject("files");
        String[] names = graphicsAssetNames(manifest, a740PcMode(), shmPresentation());
        for (String name : names) {
            File source = new File(manager.backend, name);
            JSONObject item = files.getJSONObject(name);
            if (!source.isFile() || Files.isSymbolicLink(source.toPath()) || source.length() != item.getLong("sizeBytes")
                    || !RuntimeManager.sha256(source).equals(item.getString("sha256")))
                throw new IOException("Missing or damaged GPU asset: " + name);
            if (name.startsWith("dxvk-")) {
                String dll = name.equals("dxvk-d3d11-arm64ec.dll") ? "d3d11" : "dxgi";
                // Avoid following the old prefix's Wine builtin symlink. The
                // source is private/read-only and the bind lasts this session.
                result.put(source, "/client-state/prefix/drive_c/windows/system32/" + dll + ".dll!");
            }
        }
        return result;
    }

    static String[] graphicsAssetNames(JSONObject manifest, boolean experimentEnabled) throws Exception {
        return graphicsAssetNames(manifest, experimentEnabled, false);
    }

    static String[] graphicsAssetNames(JSONObject manifest, boolean a740Enabled, boolean shmEnabled) throws Exception {
        List<String> names = new ArrayList<>(Arrays.asList("turnip-26.0.0.so", "vulkan-probe", "dxvk-d3d11-arm64ec.dll",
                "dxvk-dxgi-arm64ec.dll", "eve-d3d11-probe.exe"));
        if (manifest.has("a740PcModeExperiment")) {
            JSONObject experiment = manifest.optJSONObject("a740PcModeExperiment");
            if (experiment == null || !Integer.valueOf(1).equals(experiment.opt("format"))
                    || !experiment.optString("name").equals("turnip-a740-pc-mode-1")
                    || !experiment.optString("driver").equals("turnip-26.0.0-a740-pc-mode.so")
                    || !experiment.optString("identityProbe").equals("a740-driver-probe")
                    || !experiment.optString("upstreamCommit").equals("23f94c692cb1d41a2193a80fa531922d386e8d5d"))
                throw new IOException("A740 driver experiment does not match the pinned change");
            names.add("turnip-26.0.0-a740-pc-mode.so");
            names.add("a740-driver-probe");
        } else if (a740Enabled) throw new IOException("GPU bundle does not contain the A740 driver experiment");
        if (manifest.has("shmPresentationExperiment")) {
            JSONObject experiment = manifest.optJSONObject("shmPresentationExperiment");
            if (experiment == null || !Integer.valueOf(1).equals(experiment.opt("format"))
                    || !experiment.optString("name").equals("turnip-x11-shm-staging-1")
                    || !experiment.optString("driver").equals("turnip-26.0.0-x11-shm.so")
                    || !experiment.optString("mesaSourceSha256").equals("2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72"))
                throw new IOException("Shared-memory frame transport experiment does not match the pinned change");
            names.add("turnip-26.0.0-x11-shm.so");
            if (!names.contains("a740-driver-probe")) names.add("a740-driver-probe");
        } else if (shmEnabled) throw new IOException("GPU bundle does not contain the shared-memory frame transport experiment");
        JSONObject files = manifest.getJSONObject("files");
        if (files.length() != names.size()) throw new IOException("Incomplete GPU bundle");
        for (String name : names) if (!files.has(name)) throw new IOException("Missing GPU asset: " + name);
        return names.toArray(new String[0]);
    }

    private void runPreparation(String action, RuntimeManager.Progress progress) throws Exception {
        manager.assets();
        manager.clientState.mkdirs();
        File log = new File(manager.clientState, "logs/client-prepare.log");
        List<String> command = new ArrayList<>(Arrays.asList("/usr/bin/python3.11", "/opt/eve-android/client_prepare.py", action,
                "--content", "/client-storage/" + manager.clientContent.getName(), "--state", "/client-state",
                "--memory-limit-mib", "512"));
        if (action.equals("import") || action.equals("resume")) command.addAll(Arrays.asList("--archive", "/client-state/client-import.zip"));
        try {
            recordMemory(0, Long.MAX_VALUE, memoryInfo());
            Process process = manager.guest(manager.clientRoot, bindings(), command, log);
            await(process, action.equals("validate") ? 3600 : 10800, "Checking client binaries and offline resources", progress, log, true);
            JSONObject state = json(new File(manager.clientState, "status.json"));
            progress.update(state.optString("message", "Client preparation finished"));
        } catch (Exception error) {
            String detail = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
            writePreparationStatus("preparation_paused", detail + " Saved import files are preserved.", detail);
            throw error;
        }
    }

    private void await(Process process, int timeout, String task, RuntimeManager.Progress progress, File log) throws Exception {
        await(process, timeout, task, progress, log, false);
    }

    private ActivityManager.MemoryInfo memoryInfo() {
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        context.getSystemService(ActivityManager.class).getMemoryInfo(memory);
        return memory;
    }

    private boolean underMemoryPressure(ActivityManager.MemoryInfo memory) {
        return memory.lowMemory || memory.availMem < Math.max(MIN_FREE_MEMORY, memory.threshold * 2);
    }

    private long recordMemory(long elapsed, long lowestAvailable, ActivityManager.MemoryInfo memory) throws Exception {
        long lowest = Math.min(lowestAvailable, memory.availMem);
        Runtime javaRuntime = Runtime.getRuntime();
        JSONObject sample = new JSONObject().put("elapsed_seconds", elapsed).put("timeMillis", System.currentTimeMillis())
                .put("availableBytes", memory.availMem).put("lowestAvailableBytes", lowest).put("totalBytes", memory.totalMem)
                .put("lowMemory", memory.lowMemory).put("thresholdBytes", memory.threshold)
                .put("reservedBytes", Math.max(MIN_FREE_MEMORY, memory.threshold * 2))
                .put("appPssKiB", Debug.getPss()).put("javaUsedBytes", javaRuntime.totalMemory() - javaRuntime.freeMemory())
                .put("javaMaxBytes", javaRuntime.maxMemory()).put("preparationMemoryLimitMiB", 512);
        RuntimeManager.text(new File(manager.clientState, "preparation-memory.json"), sample.toString());
        File log = new File(manager.clientState, "logs/preparation-memory.log");
        RuntimeManager.mkdir(log.getParentFile());
        if (log.length() > 256 * 1024) RuntimeManager.text(log, "Earlier memory samples rotated.\n");
        try (Writer writer = new FileWriter(log, true)) { writer.write(sample.toString() + "\n"); }
        if (underMemoryPressure(memory))
            throw new IOException("Client preparation paused because Android is low on memory. Close other apps, then use Resume interrupted client import or Validate and prepare client");
        return lowest;
    }

    private void await(Process process, int timeout, String task, RuntimeManager.Progress progress, File log, boolean preparation) throws Exception {
        long started = System.nanoTime();
        long lastMemorySample = -5, lowestAvailable = Long.MAX_VALUE;
        if (preparation) try { lowestAvailable = json(new File(manager.clientState, "preparation-memory.json")).optLong("lowestAvailableBytes", Long.MAX_VALUE); }
        catch (Exception ignored) { /* A fresh sample will recreate this optional telemetry. */ }
        try {
            while (!process.waitFor(1, TimeUnit.SECONDS)) {
                long elapsed = TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - started);
                if (elapsed > timeout) throw new IOException(task + " timed out; export support logs");
                if (preparation) {
                    ActivityManager.MemoryInfo memory = memoryInfo();
                    lowestAvailable = Math.min(lowestAvailable, memory.availMem);
                    if (underMemoryPressure(memory) || elapsed - lastMemorySample >= 5) {
                        lowestAvailable = recordMemory(elapsed, lowestAvailable, memory);
                        lastMemorySample = elapsed;
                    }
                }
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
