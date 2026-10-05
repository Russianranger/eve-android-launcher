package io.github.russianranger.eve;

import android.content.ComponentCallbacks2;
import android.content.Context;
import android.content.Intent;
import android.os.BatteryManager;
import android.os.Looper;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.android.controller.ServiceController;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;
import static org.junit.Assert.*;

/** Android pressure stops only a live client, asynchronously, and retains bounded crash evidence. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
public final class MemoryPressureTest {
    private Context context;
    private ServiceController<RuntimeService> owner;
    private RuntimeService service;

    @Before public void prepare() throws Exception {
        context = RuntimeEnvironment.getApplication();
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        RuntimeService.active = false;
        RuntimeService.busy = false;
        RuntimeService.message = "Ready";
        RuntimeService.error = "";
        MemoryPressure.file(context, MemoryPressure.EVENTS).delete();
        MemoryPressure.file(context, MemoryPressure.LIVE).delete();
        new File(RuntimeManager.get(context).clientState, "run/stop").delete();
        owner = Robolectric.buildService(RuntimeService.class).create();
        service = owner.get();
    }

    @After public void release() throws Exception {
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        ReflectionHelpers.setField(service, "worker", null);
        owner.destroy();
        RuntimeService.active = false;
        RuntimeService.busy = false;
    }

    private void finishPressureWork() throws Exception {
        ScheduledThreadPoolExecutor executor = ReflectionHelpers.getField(service, "pressureWork");
        executor.submit(() -> { }).get(5, TimeUnit.SECONDS);
    }

    private Thread provideBusyLiveClient() {
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        Thread existingWorker = new Thread(() -> { }, "test-runtime-worker");
        ReflectionHelpers.setField(service, "worker", existingWorker);
        RuntimeService.busy = true;
        RuntimeService.operation = "start-client";
        return existingWorker;
    }

    @Test public void navigationAndBackgroundTrimLevelsLeaveLiveClientUntouched() throws Exception {
        provideBusyLiveClient();
        for (int level : new int[]{ComponentCallbacks2.TRIM_MEMORY_RUNNING_MODERATE,
                ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW, ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN,
                ComponentCallbacks2.TRIM_MEMORY_BACKGROUND, ComponentCallbacks2.TRIM_MEMORY_MODERATE,
                ComponentCallbacks2.TRIM_MEMORY_COMPLETE}) {
            assertFalse(MemoryPressure.criticalRunning(level));
            service.onTrimMemory(level);
        }
        finishPressureWork();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertFalse(MemoryPressure.file(context, MemoryPressure.EVENTS).exists());
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        assertNull(ReflectionHelpers.getField(service, "pendingStop"));
        assertTrue(new ClientRuntime(context).alive());
    }

    @Test public void runningCriticalWithoutClientDoesNotStopTheServerOrRecordAClientEvent() throws Exception {
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertFalse(MemoryPressure.file(context, MemoryPressure.EVENTS).exists());
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        assertFalse(new File(RuntimeManager.get(context).serverState, "run/stop").exists());
        assertNull(ReflectionHelpers.getField(service, "pendingStop"));
    }

    @Test public void criticalEventUsesQueuedClientStopAndDuplicateCallbacksAreIdempotent() throws Exception {
        Thread existingWorker = provideBusyLiveClient();
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        // Recording executes off the callback. The service stop is queued for
        // the main handler and has not interrupted the existing worker yet.
        assertNull(ReflectionHelpers.getField(service, "pendingStop"));
        assertFalse(existingWorker.isInterrupted());
        JSONArray events = new JSONObject(RuntimeManager.read(MemoryPressure.file(context, MemoryPressure.EVENTS),
                MemoryPressure.HISTORY_BYTE_LIMIT)).getJSONArray("events");
        assertEquals(1, events.length());
        JSONObject event = events.getJSONObject(0);
        assertEquals(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL, event.getInt("trimLevel"));
        assertTrue(event.getLong("observedAtMillis") > 0);
        assertTrue(event.has("appPssKiB"));
        assertTrue(event.has("availableBytes"));
        assertTrue(event.has("lowMemory"));
        assertFalse(event.getBoolean("serverStopRequested"));
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals("stop-client", ReflectionHelpers.getField(service, "pendingStop"));
        assertTrue(existingWorker.isInterrupted());
        assertTrue(new File(RuntimeManager.get(context).clientState, "run/stop").isFile());
        assertFalse(new File(RuntimeManager.get(context).serverState, "run/stop").exists());
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        assertEquals(1, new JSONObject(RuntimeManager.read(MemoryPressure.file(context, MemoryPressure.EVENTS),
                MemoryPressure.HISTORY_BYTE_LIMIT)).getJSONArray("events").length());
    }

    @Test public void historyRecoversFromMalformedEvidenceAndRetainsOnlyLatest64Events() throws Exception {
        File file = MemoryPressure.file(context, MemoryPressure.EVENTS);
        RuntimeManager.text(file, "interrupted old evidence");
        for (int index = 0; index < 70; index++) MemoryPressure.append(context, new JSONObject().put("sequence", index));
        JSONObject history = new JSONObject(RuntimeManager.read(file, MemoryPressure.HISTORY_BYTE_LIMIT));
        assertEquals(64, history.getInt("eventLimit"));
        JSONArray events = history.getJSONArray("events");
        assertEquals(64, events.length());
        assertEquals(6, events.getJSONObject(0).getInt("sequence"));
        assertEquals(69, events.getJSONObject(63).getInt("sequence"));
        assertFalse(new File(file.getParentFile(), file.getName() + ".new").exists());
    }

    @Test public void historyHasAByteBoundAndBothPressureFilesAreExplicitlyExported() throws Exception {
        for (int index = 0; index < 64; index++)
            MemoryPressure.append(context, new JSONObject().put("sequence", index).put("details", "x".repeat(4096)));
        File events = MemoryPressure.file(context, MemoryPressure.EVENTS);
        assertTrue(events.length() <= MemoryPressure.HISTORY_BYTE_LIMIT);
        JSONArray history = new JSONObject(RuntimeManager.read(events, MemoryPressure.HISTORY_BYTE_LIMIT)).getJSONArray("events");
        assertTrue(history.length() < 64);
        assertEquals(63, history.getJSONObject(history.length() - 1).getInt("sequence"));
        MemoryPressure.saveLive(context);
        JSONObject live = new JSONObject(RuntimeManager.read(MemoryPressure.file(context, MemoryPressure.LIVE), 16 * 1024));
        assertFalse("Periodic pressure sampling must not scan PSS", live.has("appPssKiB"));
        assertTrue(live.has("timeMillis"));
        assertEquals(events, SupportExport.files(context).get("client/logs/" + MemoryPressure.EVENTS));
        assertEquals(MemoryPressure.file(context, MemoryPressure.LIVE),
                SupportExport.files(context).get("client/logs/" + MemoryPressure.LIVE));
    }

    @Test public void liveTimelineKeepsLatest120SamplesAndCurrentSnapshotUnderByteBound() throws Exception {
        for (int index = 0; index < 135; index++)
            MemoryPressure.appendLive(context, new JSONObject().put("timeMillis", index * 10000L)
                    .put("sequence", index).put("pid", 42).put("batteryTemperatureDeciC", 400 + index));
        File file = MemoryPressure.file(context, MemoryPressure.LIVE);
        JSONObject timeline = new JSONObject(RuntimeManager.read(file, MemoryPressure.HISTORY_BYTE_LIMIT));
        JSONArray samples = timeline.getJSONArray("samples");
        assertEquals(120, timeline.getInt("sampleLimit"));
        assertEquals(10, timeline.getInt("sampleIntervalSeconds"));
        assertEquals(120, samples.length());
        assertEquals(15, samples.getJSONObject(0).getInt("sequence"));
        assertEquals(134, timeline.getInt("sequence"));
        assertEquals(134, samples.getJSONObject(119).getInt("sequence"));
        assertFalse(timeline.has("appPssKiB"));
        for (int index = 135; index < 170; index++)
            MemoryPressure.appendLive(context, new JSONObject().put("sequence", index).put("details", "x".repeat(4096)));
        assertTrue(file.length() <= MemoryPressure.HISTORY_BYTE_LIMIT);
        timeline = new JSONObject(RuntimeManager.read(file, MemoryPressure.HISTORY_BYTE_LIMIT));
        samples = timeline.getJSONArray("samples");
        assertTrue(samples.length() < 120);
        assertEquals(169, timeline.getInt("sequence"));
        assertEquals(169, samples.getJSONObject(samples.length() - 1).getInt("sequence"));
    }

    @Test public void thermalEvidenceLabelsBatteryTemperatureAndAvoidsPeriodicPssScans() throws Exception {
        context.sendStickyBroadcast(new Intent(Intent.ACTION_BATTERY_CHANGED)
                .putExtra(BatteryManager.EXTRA_TEMPERATURE, 435));
        JSONObject sample = MemoryPressure.snapshot(context, false);
        assertEquals(435, sample.getInt("batteryTemperatureDeciC"));
        assertTrue(sample.has("thermalStatus"));
        assertTrue(sample.has("powerSaveMode"));
        assertFalse(sample.has("appPssKiB"));
        assertFalse("Battery temperature must never be presented as a SoC temperature", sample.has("socTemperatureC"));
    }

    private static final class LiveProcess extends Process {
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { return 0; }
        @Override public int exitValue() { throw new IllegalThreadStateException("Client alive"); }
        @Override public void destroy() { }
        @Override public boolean isAlive() { return true; }
    }
}
