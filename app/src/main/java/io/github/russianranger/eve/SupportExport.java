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
    static LinkedHashMap<String, File> files(Context context) {
        RuntimeManager runtime = RuntimeManager.get(context);
        LinkedHashMap<String, File> result = new LinkedHashMap<>();
        result.put("operations.log", new File(runtime.home, "operations.log"));
        for (String name : new String[]{"status.json", "readiness.json"}) result.put("server/run/" + name, new File(runtime.serverState, "run/" + name));
        for (String name : new String[]{"prepared.json"}) result.put("server/" + name, new File(runtime.serverState, name));
        gatherLogs(result, new File(runtime.serverState, "logs"), "server/logs/", 0);
        gatherLogs(result, runtime.clientState, "client/", 0);
        for (String name : new String[]{"status.json", "validation.json", "prepared.json", "probe.json", "import.json"}) result.put("client/" + name, new File(runtime.clientState, name));
        return result;
    }
    private static void gatherLogs(Map<String, File> result, File dir, String prefix, int depth) {
        if (depth > 2 || !dir.isDirectory() || java.nio.file.Files.isSymbolicLink(dir.toPath())) return;
        File[] entries = dir.listFiles(); if (entries == null) return;
        Arrays.sort(entries, Comparator.comparing(File::getName));
        for (File file : entries) {
            if (result.size() > 100) break;
            if (java.nio.file.Files.isSymbolicLink(file.toPath())) continue;
            if (file.isDirectory()) gatherLogs(result, file, prefix + file.getName() + "/", depth + 1);
            else if (file.getName().endsWith(".log") || file.getName().endsWith(".json")) result.put(prefix + file.getName(), file);
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
                if (item.getValue().isFile() && !java.nio.file.Files.isSymbolicLink(item.getValue().toPath())) entry(zip, item.getKey(), tail(item.getValue(), 256 * 1024));
            }
        }
    }
    private static void entry(ZipOutputStream zip, String name, String value) throws IOException {
        zip.putNextEntry(new ZipEntry(name)); zip.write(value.getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
    }
}
