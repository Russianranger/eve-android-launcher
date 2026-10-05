package io.github.russianranger.eve;

import android.app.ActivityManager;
import android.content.ComponentCallbacks2;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Debug;
import android.os.PowerManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** Bounded Android pressure evidence; ordinary navigation trim levels are never stop requests. */
final class MemoryPressure {
    static final int EVENT_LIMIT = 64;
    static final int SAMPLE_LIMIT = 120;
    static final int HISTORY_BYTE_LIMIT = 128 * 1024;
    static final String EVENTS = "android-memory-pressure.json";
    static final String LIVE = "android-memory-state.json";

    private MemoryPressure() { }

    static boolean criticalRunning(int level) {
        // These constants are not a monotonic pressure scale: UI_HIDDEN and
        // BACKGROUND have higher values while valid runtime sessions continue.
        return level == ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL;
    }

    static File file(Context context, String name) {
        return new File(RuntimeManager.get(context).clientState, "logs/" + name);
    }

    static JSONObject snapshot(Context context, boolean detailed) throws Exception {
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        context.getSystemService(ActivityManager.class).getMemoryInfo(memory);
        Runtime java = Runtime.getRuntime();
        JSONObject result = new JSONObject().put("timeMillis", System.currentTimeMillis())
                .put("pid", android.os.Process.myPid()).put("availableBytes", memory.availMem)
                .put("totalBytes", memory.totalMem).put("thresholdBytes", memory.threshold)
                .put("lowMemory", memory.lowMemory)
                .put("javaUsedBytes", java.totalMemory() - java.freeMemory()).put("javaMaxBytes", java.maxMemory());
        PowerManager power = context.getSystemService(PowerManager.class);
        if (power != null) {
            result.put("powerSaveMode", power.isPowerSaveMode());
            if (Build.VERSION.SDK_INT >= 29) result.put("thermalStatus", power.getCurrentThermalStatus());
        }
        try {
            Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            int temperature = battery == null ? Integer.MIN_VALUE
                    : battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
            if (temperature != Integer.MIN_VALUE) result.put("batteryTemperatureDeciC", temperature);
            else result.put("batteryTemperatureAvailable", false);
        } catch (RuntimeException unavailable) { result.put("batteryTemperatureAvailable", false); }
        try {
            String status = RuntimeManager.read(new File("/proc/self/status"), 16 * 1024);
            for (String line : status.split("\n")) {
                if (line.startsWith("VmRSS:")) result.put("appRssKiB", Long.parseLong(line.trim().split("\\s+")[1]));
                else if (line.startsWith("VmHWM:")) result.put("appPeakRssKiB", Long.parseLong(line.trim().split("\\s+")[1]));
            }
        } catch (IOException | NumberFormatException unavailable) { result.put("appRssAvailable", false); }
        // PSS requires an accounting scan. Capture it once for a critical event,
        // never in the lightweight ten-second running sampler.
        if (detailed) result.put("appPssKiB", Debug.getPss());
        try { result.put("memoryPressure", RuntimeManager.read(new File("/proc/pressure/memory"), 2048)); }
        catch (IOException unavailable) { result.put("memoryPressureAvailable", false); }
        return result;
    }

    static void saveLive(Context context) throws Exception {
        appendLive(context, snapshot(context, false));
    }

    static synchronized void appendLive(Context context, JSONObject current) throws Exception {
        File liveFile = file(context, LIVE);
        JSONArray previous;
        try { previous = new JSONObject(RuntimeManager.read(liveFile, HISTORY_BYTE_LIMIT)).getJSONArray("samples"); }
        catch (Exception unavailable) { previous = new JSONArray(); }
        JSONArray samples = new JSONArray();
        for (int index = Math.max(0, previous.length() - SAMPLE_LIMIT + 1); index < previous.length(); index++)
            samples.put(previous.getJSONObject(index));
        samples.put(current);
        // Keep the current snapshot directly readable, alongside the bounded
        // ten-second timeline needed to compare warmup, pressure and heat.
        JSONObject history = new JSONObject(current.toString()).put("format", 1).put("sampleLimit", SAMPLE_LIMIT)
                .put("sampleIntervalSeconds", 10).put("samples", samples);
        RuntimeManager.text(liveFile, bounded(history, samples));
    }

    static void recordCritical(Context context, int level, long observedAt) throws Exception {
        JSONObject event = snapshot(context, true).put("observedAtMillis", observedAt).put("trimLevel", level)
                .put("event", "running-critical").put("response", "orderly-client-stop-requested")
                .put("serverStopRequested", false);
        append(context, event);
    }

    static synchronized void append(Context context, JSONObject event) throws Exception {
        File historyFile = file(context, EVENTS);
        JSONArray previous;
        try { previous = new JSONObject(RuntimeManager.read(historyFile, HISTORY_BYTE_LIMIT)).getJSONArray("events"); }
        catch (Exception unavailable) { previous = new JSONArray(); }
        JSONArray events = new JSONArray();
        for (int index = Math.max(0, previous.length() - EVENT_LIMIT + 1); index < previous.length(); index++)
            events.put(previous.getJSONObject(index));
        events.put(event);
        JSONObject history = new JSONObject().put("format", 1).put("eventLimit", EVENT_LIMIT).put("events", events);
        RuntimeManager.text(historyFile, bounded(history, events));
    }

    private static String bounded(JSONObject history, JSONArray rows) throws IOException {
        String data = history.toString();
        while (data.getBytes(StandardCharsets.UTF_8).length > HISTORY_BYTE_LIMIT && rows.length() > 1) {
            rows.remove(0); data = history.toString();
        }
        if (data.getBytes(StandardCharsets.UTF_8).length > HISTORY_BYTE_LIMIT)
            throw new IOException("Android pressure event exceeds history bound");
        // The existing writer replaces the target atomically; a killed process
        // cannot leave a partly written evidence document at the exported path.
        return data;
    }
}
