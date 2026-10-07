package io.github.russianranger.eve;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Bounded support logs and receipts; never exports client assets, world tables or CA keys. */
final class SupportExport {
    static final int FILE_LIMIT = 100;
    static final int SERVER_LOG_LIMIT = 30;
    static final int FILE_BYTE_LIMIT = 256 * 1024;

    static LinkedHashMap<String, File> files(Context context) {
        RuntimeManager runtime = RuntimeManager.get(context);
        LinkedHashMap<String, File> result = new LinkedHashMap<>();
        add(result, runtime.home, "operations.log", "operations.log");
        // Reserve current client evidence before considering either runtime's
        // history. Server diagnostics previously exhausted the shared limit
        // before the client display and DXVK logs could be selected.
        for (String name : new String[]{"status.json", "validation.json", "prepared.json", "probe.json", "import.json",
                "import-session.json", "client-performance.json", "client-performance.json.1", "controller.json",
                "graphics-preflight.json", "client-graphics-bundle.json", "client-gate.json", "launch-observation.json",
                "launch-policy.json", "wine-trust-overlay.json", "preparation-memory.json"})
            add(result, runtime.clientState, "client/" + name, name);
        for (String name : new String[]{"status.json", "processes.json", "client-window.json", "client-window.json.1",
                "dxvk.conf", "turnip-icd.json", "graphics-display.json"})
            add(result, runtime.clientState, "client/run/" + name, "run/" + name);
        for (String name : new String[]{MemoryPressure.EVENTS, MemoryPressure.LIVE, "display-performance.json",
                "client-client.log", "exefile_d3d11.log", "exefile_dxgi.log", "client-display.log", "client-supervisor.log",
                "client-wineServer.log", "client-gate.log", "client-probe.log", "client-prepare.log", "preparation-memory.log",
                "client-graphicsIdentity.log", "client-graphicsVulkan.log", "client-graphicsD3d.log",
                "client-graphicsD3d-helper.log", "client-graphicsD3d-helper-errors.log"})
            add(result, runtime.clientState, "client/logs/" + name, "logs/" + name);
        for (String name : new String[]{"status.json", "readiness.json"})
            add(result, runtime.serverState, "server/run/" + name, "run/" + name);
        add(result, runtime.serverState, "server/prepared.json", "prepared.json");

        int serverStart = result.size();
        for (String name : new String[]{"supervisor.log", "server-console.log", "market-console.log", "setup.log"})
            add(result, runtime.serverState, "server/logs/" + name, "logs/" + name);
        // Give server logs their own budget, including their current logs.
        // Remaining slots belong to client diagnostics, even with a large
        // directory of old server reports. All selection is deterministic.
        gatherLogs(result, runtime.serverState, new File(runtime.serverState, "logs"), "server/logs/", 0,
                Math.min(FILE_LIMIT, serverStart + SERVER_LOG_LIMIT));
        gatherLogs(result, runtime.clientState, runtime.clientState, "client/", 0, FILE_LIMIT);
        return result;
    }
    private static void add(Map<String, File> result, File root, String name, String relative) {
        File file = new File(root, relative);
        if (result.size() < FILE_LIMIT && safeFile(root, file)) result.put(name, file);
    }
    private static boolean safeFile(File root, File file) {
        if (!file.isFile()) return false;
        for (File current = file; current != null; current = current.getParentFile()) {
            if (java.nio.file.Files.isSymbolicLink(current.toPath())) return false;
            if (current.equals(root)) return true;
        }
        return false;
    }
    private static void gatherLogs(Map<String, File> result, File root, File dir, String prefix, int depth, int limit) {
        if (depth > 2 || !dir.isDirectory() || java.nio.file.Files.isSymbolicLink(dir.toPath())) return;
        File[] entries = dir.listFiles(); if (entries == null) return;
        // Direct files precede subdirectory history at each bounded depth.
        Arrays.sort(entries, Comparator.comparing(File::isDirectory).thenComparing(File::getName));
        for (File file : entries) {
            if (result.size() >= limit) break;
            if (java.nio.file.Files.isSymbolicLink(file.toPath())) continue;
            if (file.isDirectory()) gatherLogs(result, root, file, prefix + file.getName() + "/", depth + 1, limit);
            else if ((file.getName().endsWith(".log") || file.getName().endsWith(".json")) && safeFile(root, file))
                result.put(prefix + file.getName(), file);
        }
    }
    static String tail(File file, int limit) throws IOException {
        if (!file.isFile()) return "";
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            long offset = Math.max(0, input.length() - limit); input.seek(offset);
            byte[] data = new byte[(int) Math.min(limit, input.length() - offset)]; input.readFully(data);
            String text = new String(data, StandardCharsets.UTF_8);
            if (offset > 0 && text.contains("\n")) text = "[Earlier output omitted]\n" + text.substring(text.indexOf('\n') + 1);
            return text;
        }
    }
    private static JSONArray exits(Context context) throws JSONException {
        JSONArray exits = new JSONArray();
        if (Build.VERSION.SDK_INT >= 30) {
            for (ApplicationExitInfo entry : context.getSystemService(ActivityManager.class).getHistoricalProcessExitReasons(context.getPackageName(), 0, 5)) {
                exits.put(new JSONObject().put("timeMillis", entry.getTimestamp()).put("reason", entry.getReason()).put("status", entry.getStatus()).put("description", entry.getDescription()).put("pssKiB", entry.getPss()).put("rssKiB", entry.getRss()));
            }
        }
        return exits;
    }
    static void write(Context context, OutputStream output) throws Exception {
        RuntimeManager runtime = RuntimeManager.get(context);
        JSONObject metadata = new JSONObject().put("appVersion", BuildConfig.VERSION_NAME).put("clientBuild", 3396210)
            .put("device", Build.MANUFACTURER + " " + Build.MODEL).put("androidApi", Build.VERSION.SDK_INT)
            .put("freeBytes", runtime.home.getUsableSpace()).put("server", runtime.serverStatus())
            .put("client", new ClientRuntime(context).status()).put("operation", RuntimeService.operation)
            .put("message", RuntimeService.message).put("error", RuntimeService.error).put("androidExits", exits(context));
        android.os.PowerManager power = context.getSystemService(android.os.PowerManager.class);
        metadata.put("powerSaveModeAtExport", power.isPowerSaveMode());
        if (Build.VERSION.SDK_INT >= 29) metadata.put("thermalStatusAtExport", power.getCurrentThermalStatus());
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            entry(zip, "support.json", metadata.toString(2));
            for (Map.Entry<String, File> item : files(context).entrySet()) {
                RuntimeManager.cancelled();
                if (safeFile(runtime.home, item.getValue())) entry(zip, item.getKey(), tail(item.getValue(), FILE_BYTE_LIMIT));
            }
        }
    }
    private static void entry(ZipOutputStream zip, String name, String value) throws IOException {
        zip.putNextEntry(new ZipEntry(name)); zip.write(value.getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
    }
}
