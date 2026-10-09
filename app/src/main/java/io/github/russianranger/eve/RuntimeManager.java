package io.github.russianranger.eve;

import android.content.Context;
import android.os.Build;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Private ARM64 installations; durable world data is outside replaceable rootfs. */
final class RuntimeManager {
    interface Progress { void update(String message); }
    private static RuntimeManager instance;
    static synchronized RuntimeManager get(Context context) {
        if (instance == null) instance = new RuntimeManager(context.getApplicationContext());
        return instance;
    }
    private static final String RELEASE = "https://github.com/Russianranger/eve-android-launcher/releases/download/runtime-v1/";
    final Context context;
    final File home, serverRoot, clientRoot, serverState, clientState, clientContent, backend;
    private volatile Process server;
    private volatile String message = "Install the ARM64 server runtime to begin.";
    RuntimeManager(Context context) {
        this.context = context;
        home = context.getFilesDir();
        serverRoot = new File(home, "server-rootfs");
        clientRoot = new File(home, "client-rootfs");
        serverState = new File(home, "server-state");
        clientState = new File(home, "client-state");
        clientContent = new File(home, "client-content");
        backend = new File(home, "backend");
    }
    static void cancelled() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Operation cancelled");
    }
    static void mkdir(File dir) throws IOException {
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Cannot create " + dir.getName());
    }
    static void text(File file, String value) throws IOException {
        mkdir(file.getParentFile());
        File pending = new File(file.getParentFile(), file.getName() + ".new");
        try (OutputStream out = new FileOutputStream(pending)) { out.write(value.getBytes(StandardCharsets.UTF_8)); }
        Files.move(pending.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    }
    static String read(File file, int limit) throws IOException {
        try (InputStream in = new FileInputStream(file); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int n;
            while ((n = in.read(buffer)) != -1) {
                if (out.size() + n > limit) throw new IOException("File exceeds read limit: " + file.getName());
                out.write(buffer, 0, n);
            }
            return out.toString("UTF-8");
        }
    }
    static void copy(InputStream in, File target) throws IOException {
        mkdir(target.getParentFile());
        try (OutputStream out = new FileOutputStream(target)) {
            byte[] buffer = new byte[1024 * 1024]; int n;
            while ((n = in.read(buffer)) != -1) {
                cancelled();
                if (target.getParentFile().getUsableSpace() < n + 128L * 1024 * 1024) throw new IOException("Storage is full");
                out.write(buffer, 0, n);
            }
        }
    }
    static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buffer = new byte[1024 * 1024]; int n;
            while ((n = in.read(buffer)) != -1) { cancelled(); digest.update(buffer, 0, n); }
        }
        StringBuilder hash = new StringBuilder();
        for (byte b : digest.digest()) hash.append(String.format(Locale.ROOT, "%02x", b & 255));
        return hash.toString();
    }
    static void remove(File file) throws IOException { TarExtractor.remove(file); }
    void assets() throws Exception {
        mkdir(backend);
        for (String name : context.getAssets().list("")) {
            boolean graphicsDll = name.equals("dxvk-d3d11-arm64ec.dll") || name.equals("dxvk-dxgi-arm64ec.dll");
            if (name.endsWith(".py") || name.endsWith(".sh") || name.endsWith(".json") || name.endsWith(".exe") || name.startsWith("wine-crypt32-") && name.endsWith(".dll")
                    || graphicsDll || name.equals("turnip-26.0.0.so") || name.equals("turnip-26.0.0-a740-pc-mode.so")
                    || name.equals("turnip-26.0.0-x11-shm.so")
                    || name.equals("vulkan-probe") || name.equals("a740-driver-probe")) {
                File target = new File(backend, name);
                File staging = File.createTempFile("asset-", ".tmp", backend);
                try {
                    try (InputStream in = context.getAssets().open(name)) { copy(in, staging); }
                    if (graphicsDll && !staging.setReadOnly()) throw new IOException("Could not protect private graphics asset");
                    if ((name.equals("vulkan-probe") || name.equals("a740-driver-probe")) && !staging.setExecutable(true, true))
                        throw new IOException("Could not enable native graphics probe");
                    java.nio.file.Files.move(staging.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING,
                            java.nio.file.StandardCopyOption.ATOMIC_MOVE);
                } finally { staging.delete(); }
            }
        }
    }
    void download(String url, File target, String expectedSha256, Progress progress) throws Exception {
        if (expectedSha256 != null && !expectedSha256.matches("[a-fA-F0-9]{64}")) throw new IOException("Invalid runtime checksum");
        URL current = new URL(url);
        try {
            for (int redirect = 0; redirect < 8; redirect++) {
                cancelled();
                if (!"https".equals(current.getProtocol())) throw new IOException("HTTPS is required for runtime downloads");
                HttpURLConnection connection = (HttpURLConnection) current.openConnection();
                connection.setConnectTimeout(30000); connection.setReadTimeout(30000);
                connection.setInstanceFollowRedirects(false); connection.setRequestProperty("User-Agent", "EVE-Android/" + BuildConfig.VERSION_NAME);
                try {
                    int code = connection.getResponseCode();
                    if (code >= 300 && code < 400) {
                        String location = connection.getHeaderField("Location");
                        if (location == null) throw new IOException("Runtime redirect has no destination");
                        current = new URL(current, location); continue;
                    }
                    if (code != 200) throw new IOException("Runtime download returned HTTP " + code);
                    long size = connection.getContentLengthLong(), done = 0;
                    if (size > home.getUsableSpace() - 256L * 1024 * 1024) throw new IOException("Not enough storage for runtime download");
                    mkdir(target.getParentFile());
                    try (InputStream in = connection.getInputStream(); OutputStream out = new FileOutputStream(target)) {
                        byte[] buffer = new byte[1024 * 1024]; int n; long last = 0;
                        while ((n = in.read(buffer)) != -1) {
                            cancelled(); done += n;
                            if (done > 4L * 1024 * 1024 * 1024 || home.getUsableSpace() < 128L * 1024 * 1024) throw new IOException("Runtime download exceeds available storage");
                            out.write(buffer, 0, n);
                            if (done - last >= 4L * 1024 * 1024) { progress.update("Downloading runtime · " + done / 1048576 + " MiB"); last = done; }
                        }
                    }
                    if (size >= 0 && size != done) throw new IOException("Runtime download was incomplete");
                    if (expectedSha256 != null && !expectedSha256.equalsIgnoreCase(sha256(target))) throw new IOException("Runtime checksum failed");
                    return;
                } finally { connection.disconnect(); }
            }
            throw new IOException("Too many runtime redirects");
        } catch (Exception e) { target.delete(); throw e; }
    }
    void installTar(File archive, File destination, Progress progress) throws Exception {
        if (!Arrays.asList(Build.SUPPORTED_ABIS).contains("arm64-v8a")) throw new IOException("ARM64 Android is required");
        File staging = new File(destination.getParentFile(), destination.getName() + ".incoming");
        File previous = new File(destination.getParentFile(), destination.getName() + ".previous");
        if (!destination.exists() && previous.exists() && !previous.renameTo(destination)) throw new IOException("Cannot recover existing runtime");
        remove(staging); mkdir(staging);
        try {
            TarExtractor.extract(archive, staging, count -> progress.update("Unpacking runtime · " + count + " entries"));
            String markerPath = destination.equals(serverRoot) ? "etc/eve-server-runtime.json" : "etc/memento-client-runtime.json";
            JSONObject marker = new JSONObject(read(new File(staging, markerPath), 65536));
            int expectedFormat = destination.equals(serverRoot) ? 1 : 2;
            if (marker.getInt("format") != expectedFormat || !marker.getString("architecture").equals("arm64")) throw new IOException("Unsupported ARM64 runtime");
            if (destination.equals(serverRoot) && (!marker.getString("runtime").equals("eve-server-1") || marker.getInt("clientBuild") != 3396210)) throw new IOException("Wrong EVE server runtime");
            if (destination.equals(clientRoot) && !marker.getString("runtime").equals("fex-arm64ec-1")) throw new IOException("Wrong Wine/FEX client runtime");
            cancelled(); remove(previous);
            if (destination.exists() && !destination.renameTo(previous)) throw new IOException("Cannot retain previous runtime");
            if (!staging.renameTo(destination)) { previous.renameTo(destination); throw new IOException("Cannot activate runtime"); }
            remove(previous);
        } finally { remove(staging); }
    }
    Process guest(File root, Map<File, String> bindings, List<String> command, File log) throws Exception {
        return guest(root, bindings, command, log, false);
    }
    Process guest(File root, Map<File, String> bindings, List<String> command, File log, boolean restrictedClientNetwork) throws Exception {
        cancelled(); mkdir(root); mkdir(log.getParentFile());
        File tmp = new File(home, root.getName() + "-tmp"); mkdir(tmp);
        File nativeDir = new File(context.getApplicationInfo().nativeLibraryDir);
        File proot = new File(nativeDir, "libproot.so"), loader = new File(nativeDir, "libproot-loader.so");
        if (!proot.isFile() || !loader.isFile()) throw new IOException("The APK is missing the ARM64 process runtime");
        String hostname = "";
        try { hostname = read(new File("/proc/sys/kernel/hostname"), 1024).trim(); } catch (IOException ignored) { }
        String aliases = hostname.matches("[A-Za-z0-9][A-Za-z0-9.-]{0,251}") && !hostname.equalsIgnoreCase("localhost") ? " " + hostname : "";
        text(new File(root, "etc/hosts"), "127.0.0.1 localhost" + aliases + "\n::1 localhost" + aliases + "\n");
        List<String> args = new ArrayList<>(Arrays.asList(proot.getPath(), "--kill-on-exit", "-0", "-r", root.getPath(), "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", tmp + ":/tmp", "-w", "/"));
        if (root.equals(clientRoot)) args.add(1, "--sysvipc");
        if (restrictedClientNetwork) {
            if (!root.equals(clientRoot)) throw new IOException("Client network policy requires the client runtime");
            args.add(1, "--eve-client-network");
        }
        for (Map.Entry<File, String> entry : bindings.entrySet()) {
            if (!entry.getKey().isFile()) mkdir(entry.getKey());
            args.add("-b"); args.add(entry.getKey().getPath() + ":" + entry.getValue());
        }
        args.addAll(Arrays.asList("/usr/bin/env", "-i", "HOME=/root", "USER=root", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "TMPDIR=/tmp", "PYTHONUNBUFFERED=1"));
        if (restrictedClientNetwork) args.add("EVE_CLIENT_NETWORK_POLICY=loopback-v1");
        args.addAll(command);
        ProcessBuilder builder = new ProcessBuilder(args);
        builder.environment().put("PROOT_LOADER", loader.getPath()); builder.environment().put("PROOT_TMP_DIR", tmp.getPath());
        builder.environment().remove("PROOT_NO_SECCOMP"); builder.environment().put("TRASC_PROOT_REPORT", "1");
        builder.redirectErrorStream(true); builder.redirectOutput(ProcessBuilder.Redirect.appendTo(log));
        return builder.start();
    }
    static int waitFor(Process process, long seconds) throws Exception {
        try {
            if (!process.waitFor(seconds, TimeUnit.SECONDS)) throw new IOException("Operation timed out; inspect its log before retrying");
            if (process.exitValue() != 0) throw new IOException("Runtime operation failed (exit " + process.exitValue() + "); open Logs for details");
            return process.exitValue();
        } finally {
            if (process.isAlive()) { process.destroy(); if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly(); }
        }
    }
    boolean serverInstalled() { return new File(serverRoot, "etc/eve-server-runtime.json").isFile(); }
    private JSONObject report() {
        try { return new JSONObject(read(new File(serverState, "run/status.json"), 65536)); }
        catch (Exception ignored) { return new JSONObject(); }
    }
    private boolean identityAlive(JSONObject identity) {
        if (identity == null) return false;
        try {
            int pid = identity.getInt("pid");
            if (pid <= 0) return false;
            String stat = read(new File("/proc/" + pid + "/stat"), 8192);
            String[] fields = stat.substring(stat.lastIndexOf(')') + 2).trim().split("\\s+");
            return fields.length > 19 && !fields[0].equals("Z") && fields[19].equals(identity.getString("startTicks"));
        } catch (Exception ignored) { return false; }
    }
    boolean serverAlive() {
        Process current = server;
        return (current != null && current.isAlive()) || identityAlive(report().optJSONObject("supervisorIdentity"));
    }
    JSONObject serverStatus() throws Exception {
        JSONObject status = new JSONObject();
        File report = new File(serverState, "run/status.json");
        if (report.isFile()) { try { status = new JSONObject(read(report, 65536)); } catch (Exception ignored) { /* Atomic report may not yet exist. */ } }
        boolean alive = serverAlive();
        status.put("installed", serverInstalled()).put("prepared", new File(serverState, "prepared.json").isFile()).put("alive", alive);
        status.put("ready", alive && status.optBoolean("ready") && status.optString("phase").equals("running"));
        if (!alive && !RuntimeService.busy && Arrays.asList("running", "starting", "stopping", "preparing").contains(status.optString("phase"))) status.put("phase", "stopped").put("message", "The previous server operation is closed. Start it to check readiness.");
        if (!status.has("message")) status.put("message", message);
        return status;
    }
    private Map<File, String> serverBindings() throws Exception {
        assets(); mkdir(serverState); mkdir(new File(serverState, "config"));
        Map<File, String> bindings = new LinkedHashMap<>();
        bindings.put(serverState, "/state"); bindings.put(backend, "/opt/eve-android"); bindings.put(new File(serverState, "config"), "/opt/evejs/config");
        return bindings;
    }
    void installServer(Progress progress) throws Exception {
        if (new ClientRuntime(context).alive()) throw new IOException("Stop the client before installing the server runtime");
        if (serverAlive()) throw new IOException("Stop the server before installing its runtime");
        if (serverInstalled()) { progress.update("Server runtime is installed."); return; }
        mkdir(serverState);
        File manifestFile = new File(context.getCacheDir(), "server-runtime-manifest.json");
        File archive = new File(context.getCacheDir(), "server-runtime-arm64.tar.gz");
        try {
            progress.update("Fetching the server runtime manifest…");
            download(RELEASE + manifestFile.getName(), manifestFile, null, progress);
            JSONObject info = new JSONObject(read(manifestFile, 65536));
            if (info.getInt("format") != 1 || !info.getString("architecture").equals("arm64") || !info.getString("runtime").equals("eve-server-1") || !info.getString("file").equals(archive.getName())) throw new IOException("Unsupported server runtime manifest");
            download(RELEASE + archive.getName(), archive, info.getString("sha256"), progress);
            installTar(archive, serverRoot, progress);
            message = "Server runtime installed. Prepare the local world next."; progress.update(message);
        } finally { archive.delete(); manifestFile.delete(); }
    }
    void prepareServer(Progress progress) throws Exception {
        if (new ClientRuntime(context).alive()) throw new IOException("Stop the client before preparing the local world");
        if (serverAlive()) throw new IOException("Stop the server before preparing its world");
        if (!serverInstalled()) throw new IOException("Install the server runtime first");
        progress.update("Preparing the local universe and Jita market…");
        Process job = guest(serverRoot, serverBindings(), Arrays.asList("/usr/bin/python3", "/opt/eve-android/server_runtime.py", "prepare"), new File(serverState, "logs/setup.log"));
        waitFor(job, 1800);
        message = "Local world prepared. Start the server to check all services."; progress.update(message);
    }
    void startServer(Progress progress) throws Exception {
        if (serverAlive()) { progress.update(serverStatus().optString("message")); return; }
        if (!serverInstalled() || !new File(serverState, "prepared.json").isFile()) throw new IOException("Install the runtime and prepare the local world first");
        Map<File, String> bindings = serverBindings();
        new File(serverState, "run/stop").delete();
        JSONObject pending = report();
        pending.put("phase", "starting").put("ready", false).put("message", "Starting local server services…");
        text(new File(serverState, "run/status.json"), pending.toString());
        server = guest(serverRoot, bindings, Arrays.asList("/usr/bin/python3", "/opt/eve-android/server_runtime.py", "start"), new File(serverState, "logs/supervisor.log"));
        long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(10);
        try {
            while (System.nanoTime() < deadline) {
                cancelled(); JSONObject status = serverStatus();
                progress.update(status.optString("message", "Waiting for server readiness…"));
                if (status.optBoolean("ready")) return;
                if (!serverAlive()) throw new IOException(status.optString("error", "Server closed during startup; inspect Logs"));
                Thread.sleep(500);
            }
            throw new IOException("Server has not become ready within 10 minutes; inspect Logs");
        } catch (Exception e) { requestServerStop(); throw e; }
    }
    void requestServerStop() throws IOException { text(new File(serverState, "run/stop"), "stop\n"); }
    void stopServer(Progress progress) throws Exception {
        Process current = server;
        requestServerStop();
        if (!serverAlive()) { message = "Server is stopped."; progress.update(message); return; }
        progress.update("Saving the world and stopping server services…");
        if (current == null || !current.isAlive()) {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120);
            while (serverAlive() && System.nanoTime() < deadline) Thread.sleep(500);
            if (serverAlive()) throw new IOException("Recovered server cleanup is still pending; export Logs");
            JSONObject state = report();
            if (!state.optBoolean("cleanShutdown")) throw new IOException("Recovered server closed without a clean shutdown receipt; inspect Logs");
            message = "World saved and recovered server stopped."; progress.update(message); return;
        }
        if (!current.waitFor(120, TimeUnit.SECONDS)) throw new IOException("Server cleanup is still pending; keep the app open and export Logs");
        server = null;
        if (current.exitValue() != 0) throw new IOException("Server stopped with a cleanup error; inspect Logs");
        message = "World saved and server stopped."; progress.update(message);
    }
}
