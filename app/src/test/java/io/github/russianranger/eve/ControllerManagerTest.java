package io.github.russianranger.eve;

import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import java.io.File;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.LooperMode;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

/** Exercise the Android Handler and physical event entry points, not a model of the scheduler. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
@LooperMode(LooperMode.Mode.PAUSED)
public final class ControllerManagerTest {
    private static final int DEVICE = 51;
    private static void advance(long milliseconds) { shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(milliseconds)); }
    private ControllerManager manager(boolean idleAware, List<JSONObject> events) {
        return new ControllerManager(RuntimeEnvironment.getApplication(),
            new File(RuntimeEnvironment.getApplication().getFilesDir(), "controller-idle-" + idleAware), events::add, idleAware);
    }
    private static void key(ControllerManager manager, int code, boolean down) {
        long now = SystemClock.uptimeMillis();
        assertTrue(manager.key(new KeyEvent(now, now, down ? KeyEvent.ACTION_DOWN : KeyEvent.ACTION_UP,
            code, 0, 0, DEVICE, 0, 0, InputDevice.SOURCE_GAMEPAD)));
    }
    private static void stick(ControllerManager manager, float x, float y) {
        long now = SystemClock.uptimeMillis();
        MotionEvent.PointerProperties property = new MotionEvent.PointerProperties(); property.id = 0;
        MotionEvent.PointerCoords coords = new MotionEvent.PointerCoords();
        coords.setAxisValue(MotionEvent.AXIS_Z, x); coords.setAxisValue(MotionEvent.AXIS_RZ, y);
        MotionEvent event = MotionEvent.obtain(now, now, MotionEvent.ACTION_MOVE, 1,
            new MotionEvent.PointerProperties[]{property}, new MotionEvent.PointerCoords[]{coords},
            0, 0, 1, 1, DEVICE, 0, InputDevice.SOURCE_JOYSTICK, 0);
        try { assertTrue(manager.motion(event)); } finally { event.recycle(); }
    }
    private static List<JSONObject> pointers(List<JSONObject> events) {
        List<JSONObject> result = new ArrayList<>();
        for (JSONObject event : events) if (event.optString("type").equals("pointer")) result.add(event);
        return result;
    }

    @Test public void centeredInputRemovesIdleWakeupsAndFreshMotionDoesNotIntegrateIdleTime() throws Exception {
        List<JSONObject> events = new ArrayList<>(); ControllerManager manager = manager(true, events);
        try {
            manager.capture(true); advance(10_000);
            assertEquals(0, manager.state().getLong("pointer_tick_callbacks"));
            stick(manager, .2f, 0); advance(500);
            assertEquals("Deadzone input stays timer-free", 0, manager.state().getLong("pointer_tick_callbacks"));
            stick(manager, .6f, 0); advance(16);
            List<JSONObject> motion = pointers(events); assertEquals(1, motion.size());
            assertEquals("Only the new 16 ms motion interval is integrated", 5.6, motion.get(0).getDouble("x"), .001);
            advance(48); assertEquals("Held pointer motion continues at the existing cadence", 4, pointers(events).size());
            stick(manager, -.6f, 0); advance(16);
            motion = pointers(events); assertEquals(-5.6, motion.get(motion.size() - 1).getDouble("x"), .001);
            stick(manager, 0, 0); long stopped = manager.state().getLong("pointer_tick_callbacks"); advance(10_000);
            assertEquals(stopped, manager.state().getLong("pointer_tick_callbacks"));
            assertFalse(manager.state().getBoolean("pointer_tick_scheduled"));
            stick(manager, 0, -.6f); advance(16);
            motion = pointers(events); assertEquals(-5.6, motion.get(motion.size() - 1).getDouble("y"), .001);
        } finally { manager.close(); }
    }

    @Test public void defaultConstructorRetainsContinuousBaselineTicks() throws Exception {
        List<JSONObject> events = new ArrayList<>();
        ControllerManager manager = new ControllerManager(RuntimeEnvironment.getApplication(),
            new File(RuntimeEnvironment.getApplication().getFilesDir(), "controller-baseline"), events::add);
        try {
            manager.capture(true); advance(1000);
            assertFalse(manager.state().getBoolean("idle_pointer_ticks"));
            assertTrue(manager.state().getLong("pointer_tick_callbacks") >= 60);
            assertTrue(pointers(events).isEmpty());
            manager.capture(false); long stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000);
            assertEquals(stopped, manager.state().getLong("pointer_tick_callbacks"));
        } finally { manager.close(); }
    }

    @Test public void pointerButtonsCancellationLayersAndLifecycleAllRescheduleFromEvents() throws Exception {
        List<JSONObject> events = new ArrayList<>(); ControllerManager manager = manager(true, events);
        try {
            JSONObject profile = manager.state();
            profile.getJSONArray("layers").getJSONObject(0).getJSONObject("bindings")
                .put("A", "PointerLeft").put("B", "PointerRight");
            profile.getJSONArray("layers").getJSONObject(1).getJSONObject("bindings")
                .put("A", "KeyF").put("B", "KeyC");
            manager.configure(profile, false); manager.capture(true);
            key(manager, KeyEvent.KEYCODE_BUTTON_A, true); advance(16);
            assertTrue(pointers(events).get(0).getDouble("x") < 0);
            key(manager, KeyEvent.KEYCODE_BUTTON_B, true); long stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000);
            assertEquals("Opposing pointer buttons do not keep an idle timer", stopped, manager.state().getLong("pointer_tick_callbacks"));
            key(manager, KeyEvent.KEYCODE_BUTTON_B, false); advance(16);
            assertEquals(stopped + 1, manager.state().getLong("pointer_tick_callbacks"));
            manager.nextLayer(); stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000);
            assertEquals("Held source remapped to a key needs no timer", stopped, manager.state().getLong("pointer_tick_callbacks"));
            assertTrue(events.stream().anyMatch(event -> event.optString("type").equals("button")
                && event.optString("action").equals("KeyF") && event.optBoolean("down")));
            manager.selectLayer(0); advance(16); assertEquals(stopped + 1, manager.state().getLong("pointer_tick_callbacks"));
            manager.capture(false); stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000);
            assertEquals("Focus loss cancels outstanding timer", stopped, manager.state().getLong("pointer_tick_callbacks"));
            manager.capture(true); advance(1000); assertEquals("Recapture has no stale held pointer", stopped, manager.state().getLong("pointer_tick_callbacks"));
            stick(manager, 1, 0); advance(16); manager.onInputDeviceRemoved(DEVICE);
            stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000); assertEquals(stopped, manager.state().getLong("pointer_tick_callbacks"));
            stick(manager, 1, 0); advance(16); manager.onInputDeviceChanged(DEVICE);
            stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000); assertEquals(stopped, manager.state().getLong("pointer_tick_callbacks"));
            stick(manager, 1, 0); manager.close(); stopped = manager.state().getLong("pointer_tick_callbacks"); advance(1000);
            assertEquals("Close prevents a delayed pointer callback", stopped, manager.state().getLong("pointer_tick_callbacks"));
        } finally { manager.close(); }
    }
}
