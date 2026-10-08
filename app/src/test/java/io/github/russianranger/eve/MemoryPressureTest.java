package io.github.russianranger.eve;

import android.app.ActivityManager;
import android.content.ComponentCallbacks2;
import android.content.Context;
import android.content.ContextWrapper;
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
import java.util.concurrent.CountDownLatch;
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

/** Only corroborated Android pressure may stop the same live client; trim events remain bounded evidence. */
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
        new File(RuntimeManager.get(context).clientState, "run/status.json").delete();
        owner = Robolectric.buildService(RuntimeService.class).create();
        service = owner.get();
        memory(false, 5_004_591_104L, 226_492_416L);
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

    private void receipt(int pid, String ticks) throws Exception {
        RuntimeManager.text(new File(RuntimeManager.get(context).clientState, "run/status.json"),
                new JSONObject().put("phase", "running").put("supervisorIdentity",
                        new JSONObject().put("pid", pid).put("startTicks", ticks)).toString());
    }

    private void memory(boolean low, long available, long threshold) {
        ActivityManager.MemoryInfo info = new ActivityManager.MemoryInfo();
        info.lowMemory = low; info.availMem = available; info.threshold = threshold; info.totalMem = 16L * 1024 * 1024 * 1024;
        Shadows.shadowOf(context.getSystemService(ActivityManager.class)).setMemoryInfo(info);
    }

    private JSONArray events() throws Exception {
        return new JSONObject(RuntimeManager.read(MemoryPressure.file(context, MemoryPressure.EVENTS),
                MemoryPressure.HISTORY_BYTE_LIMIT)).getJSONArray("events");
    }

    private void flushCritical() throws Exception {
        finishPressureWork(); Shadows.shadowOf(Looper.getMainLooper()).idle(); finishPressureWork();
    }

    private Thread provideBusyLiveClient() throws Exception {
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        receipt(10001, "100");
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
        memory(true, 5_004_591_104L, 226_492_416L);
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
        assertEquals("client-stop-queued", event.getString("response"));
        assertFalse(event.getBoolean("clientStopRequested"));
        assertFalse(event.getBoolean("serverStopRequested"));
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        finishPressureWork();
        assertEquals("stop-client", ReflectionHelpers.getField(service, "pendingStop"));
        assertTrue(existingWorker.isInterrupted());
        assertTrue(new File(RuntimeManager.get(context).clientState, "run/stop").isFile());
        assertFalse(new File(RuntimeManager.get(context).serverState, "run/stop").exists());
        assertEquals("orderly-client-stop-requested", events().getJSONObject(0).getString("response"));
        assertEquals("android-low-memory", events().getJSONObject(0).getString("reason"));
        assertTrue(events().getJSONObject(0).getBoolean("clientStopRequested"));
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        assertEquals(1, new JSONObject(RuntimeManager.read(MemoryPressure.file(context, MemoryPressure.EVENTS),
                MemoryPressure.HISTORY_BYTE_LIMIT)).getJSONArray("events").length());
    }

    @Test public void exactOctober8CriticalTrimRecordsAmpleMemoryWithoutStoppingAndLaterPressureCanStop() throws Exception {
        Thread existingWorker = provideBusyLiveClient();
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        flushCritical();
        JSONObject event = events().getJSONObject(0);
        assertEquals(5_004_591_104L, event.getLong("availableBytes"));
        assertEquals(226_492_416L, event.getLong("thresholdBytes"));
        assertFalse(event.getBoolean("lowMemory"));
        assertEquals("client-retained", event.getString("response"));
        assertEquals("android-memory-ample", event.getString("reason"));
        assertFalse(event.getBoolean("clientStopRequested"));
        assertFalse(existingWorker.isInterrupted());
        assertNull(ReflectionHelpers.getField(service, "pendingStop"));
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        assertTrue(new ClientRuntime(context).alive());
        memory(false, 226_492_416L, 226_492_416L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        flushCritical();
        assertEquals(2, events().length());
        assertEquals("available-at-or-below-android-threshold", events().getJSONObject(1).getString("reason"));
        assertTrue(events().getJSONObject(1).getBoolean("clientStopRequested"));
        assertTrue(existingWorker.isInterrupted());
        assertFalse(new File(RuntimeManager.get(context).serverState, "run/stop").exists());
    }

    @Test public void policyRequiresFreshStrictMemoryEvidenceAndIncludesTheThresholdBoundary() throws Exception {
        JSONObject valid = new JSONObject().put("memoryInfoAvailable", true).put("lowMemory", false)
                .put("availableBytes", 100L).put("thresholdBytes", 100L);
        assertEquals("available-at-or-below-android-threshold", MemoryPressure.stopReason(valid));
        assertEquals("available-at-or-below-android-threshold", MemoryPressure.stopReason(new JSONObject(valid.toString()).put("availableBytes", 0L)));
        assertEquals("android-low-memory", MemoryPressure.stopReason(new JSONObject().put("memoryInfoAvailable", true).put("lowMemory", true)));
        assertNull(MemoryPressure.stopReason(null));
        for (JSONObject unknown : new JSONObject[]{new JSONObject(), new JSONObject(valid.toString()).put("memoryInfoAvailable", false),
                new JSONObject(valid.toString()).put("memoryInfoAvailable", "true"), new JSONObject().put("lowMemory", true),
                new JSONObject(valid.toString()).put("availableBytes", -1L), new JSONObject(valid.toString()).put("thresholdBytes", 0L),
                new JSONObject(valid.toString()).put("availableBytes", "100"), new JSONObject(valid.toString()).put("thresholdBytes", 100.0),
                new JSONObject(valid.toString()).put("availableBytes", JSONObject.NULL),
                new JSONObject(valid.toString()).put("availableBytes", 101L)})
            assertNull("Invalid or ample memory evidence stopped the client: " + unknown, MemoryPressure.stopReason(unknown));
        Context unavailable = new ContextWrapper(context) {
            @Override public Object getSystemService(String name) {
                return Context.ACTIVITY_SERVICE.equals(name) ? null : super.getSystemService(name);
            }
        };
        JSONObject missing = MemoryPressure.snapshot(unavailable, false);
        assertFalse(missing.getBoolean("memoryInfoAvailable"));
        assertNull(MemoryPressure.stopReason(missing));
        assertEquals("android-memory-info-unavailable", MemoryPressure.retentionReason(missing));
    }

    @Test public void unknownMemoryValuesRetainClientAndRecoveredMemoryCancelsDelayedDispatch() throws Exception {
        Thread existingWorker = provideBusyLiveClient();
        memory(false, -1L, 0L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        flushCritical();
        assertEquals("android-memory-values-unavailable", events().getJSONObject(0).getString("reason"));
        memory(true, 100L, 100L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        memory(false, 5_004_591_104L, 226_492_416L);
        Shadows.shadowOf(Looper.getMainLooper()).idle(); finishPressureWork();
        JSONObject event = events().getJSONObject(1);
        assertEquals("client-retained", event.getString("response"));
        assertEquals("android-memory-ample", event.getString("reason"));
        assertEquals(5_004_591_104L, event.getJSONObject("dispatchMemoryInfo").getLong("availableBytes"));
        assertFalse(existingWorker.isInterrupted());
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
    }

    private void acceptRestart(int pid, String ticks) throws Exception {
        ReflectionHelpers.setField(service, "worker", null);
        RuntimeService.busy = false;
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        receipt(pid, ticks);
        service.onStartCommand(new Intent(service, RuntimeService.class).setAction("start-client"), 0, 0);
        Thread start = ReflectionHelpers.getField(service, "worker");
        if (start != null) start.join(5000);
        assertFalse(RuntimeService.busy);
    }

    @Test public void delayedExecutorEventCannotStopRestartOrClearItsNewRequest() throws Exception {
        provideBusyLiveClient();
        memory(true, 100L, 100L);
        ScheduledThreadPoolExecutor executor = ReflectionHelpers.getField(service, "pressureWork");
        CountDownLatch entered = new CountDownLatch(1), unblock = new CountDownLatch(1);
        executor.execute(() -> { entered.countDown(); try { unblock.await(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) { } });
        assertTrue(entered.await(5, TimeUnit.SECONDS));
        try {
            service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
            acceptRestart(10002, "200");
            Thread newWorker = new Thread(() -> { });
            ReflectionHelpers.setField(service, "worker", newWorker);
            RuntimeService.busy = true; RuntimeService.operation = "start-client";
            service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
            unblock.countDown(); flushCritical();
            assertEquals(1, events().length());
            assertEquals("10002:200", events().getJSONObject(0).getString("clientSession"));
            assertTrue(events().getJSONObject(0).getBoolean("clientStopRequested"));
            assertTrue(newWorker.isInterrupted());
        } finally { unblock.countDown(); }
    }

    @Test public void delayedMainDispatchAndPendingPressureStopCannotReachRestartedClient() throws Exception {
        provideBusyLiveClient(); memory(true, 100L, 100L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        finishPressureWork();
        acceptRestart(10002, "200");
        Shadows.shadowOf(Looper.getMainLooper()).idle(); finishPressureWork();
        assertEquals("client-retained", events().getJSONObject(0).getString("response"));
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        Thread worker = new Thread(() -> { }); ReflectionHelpers.setField(service, "worker", worker);
        RuntimeService.busy = true; RuntimeService.operation = "start-client";
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); flushCritical();
        assertEquals("stop-client", ReflectionHelpers.getField(service, "pendingStop"));
        assertNotNull(ReflectionHelpers.getField(service, "pendingPressureStop"));
        new File(RuntimeManager.get(context).clientState, "run/stop").delete();
        acceptRestart(10003, "300");
        service.drainPendingStop(0);
        Shadows.shadowOf(Looper.getMainLooper()).idle(); finishPressureWork();
        assertNull(ReflectionHelpers.getField(service, "pendingStop"));
        assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        assertTrue(new ClientRuntime(context).alive());
    }

    @Test public void changedOrMissingSupervisorIdentityAndEndedClientCancelQueuedStop() throws Exception {
        for (int scenario = 0; scenario < 3; scenario++) {
            provideBusyLiveClient(); memory(true, 100L, 100L);
            service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); finishPressureWork();
            if (scenario == 0) receipt(10001, "101"); // Same PID, different native lifetime.
            else if (scenario == 1) new File(RuntimeManager.get(context).clientState, "run/status.json").delete();
            else ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
            Shadows.shadowOf(Looper.getMainLooper()).idle(); finishPressureWork();
            JSONObject event = events().getJSONObject(scenario);
            assertEquals("client-retained", event.getString("response"));
            assertFalse(event.getBoolean("clientStopRequested"));
            assertNull(ReflectionHelpers.getField(service, "pendingStop"));
            assertFalse(new File(RuntimeManager.get(context).clientState, "run/stop").exists());
        }
    }

    @Test public void manualStopAndSaveServerAlwaysTakePrecedenceOverPressureQueue() throws Exception {
        provideBusyLiveClient(); memory(true, 100L, 100L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); flushCritical();
        assertNotNull(ReflectionHelpers.getField(service, "pendingPressureStop"));
        service.onStartCommand(new Intent(service, RuntimeService.class).setAction("stop-client"), 0, 0);
        assertEquals("stop-client", ReflectionHelpers.getField(service, "pendingStop"));
        assertNull(ReflectionHelpers.getField(service, "pendingPressureStop"));
        service.onStartCommand(new Intent(service, RuntimeService.class).setAction("stop-server"), 0, 0);
        assertEquals("stop-server", ReflectionHelpers.getField(service, "pendingStop"));
        assertNull(ReflectionHelpers.getField(service, "pendingPressureStop"));
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); flushCritical();
        assertEquals("stop-server", ReflectionHelpers.getField(service, "pendingStop"));
    }

    @Test public void failedPressureOnlyStopRearmsSameClientWithoutClaimingCompletion() throws Exception {
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess() {
            @Override public boolean waitFor(long timeout, TimeUnit unit) { return false; }
        });
        receipt(10001, "100"); memory(true, 100L, 100L);
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); flushCritical();
        Thread stopping = ReflectionHelpers.getField(service, "worker");
        if (stopping != null) stopping.join(5000);
        assertFalse(RuntimeService.busy);
        assertTrue(new ClientRuntime(context).alive());
        assertTrue(RuntimeService.error.contains("cleanup is still pending"));
        assertNull(((java.util.concurrent.atomic.AtomicReference<?>) ReflectionHelpers.getField(service, "criticalRequest")).get());
        assertEquals("orderly-client-stop-requested", events().getJSONObject(0).getString("response"));
        assertFalse(events().getJSONObject(0).has("clientStopCompleted"));
        Thread existingWorker = new Thread(() -> { });
        ReflectionHelpers.setField(service, "worker", existingWorker);
        RuntimeService.busy = true; RuntimeService.operation = "start-client";
        service.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL); flushCritical();
        assertEquals(2, events().length());
        assertTrue(existingWorker.isInterrupted());
        assertFalse(new File(RuntimeManager.get(context).serverState, "run/stop").exists());
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

    private static class LiveProcess extends Process {
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { return 0; }
        @Override public int exitValue() { throw new IllegalThreadStateException("Client alive"); }
        @Override public void destroy() { }
        @Override public boolean isAlive() { return true; }
    }
}
