package io.github.russianranger.eve;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.drawable.AdaptiveIconDrawable;
import android.graphics.drawable.Drawable;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.time.Duration;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.util.ReflectionHelpers;
import static org.junit.Assert.*;

/** Exercises saved settings, their launcher controls and actual packaged launcher artwork. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public final class ClientPerformanceSettingsTest {
    private Context context;
    private SharedPreferences preferences;

    @Before public void prepareStoppedClient() {
        context = RuntimeEnvironment.getApplication();
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        RuntimeService.busy = false;
        RuntimeService.active = false;
        RuntimeService.message = "Ready";
        RuntimeService.error = "";
        preferences = context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE);
        assertTrue(preferences.edit().clear().commit());
    }

    @After public void releaseTestState() {
        RuntimeService.busy = false;
        RuntimeService.active = false;
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
    }

    @Test public void defaultsAndExplicitChoicesSurviveNewRuntimeInstances() {
        ClientRuntime runtime = new ClientRuntime(context);
        assertEquals("responsive", runtime.performanceProfile());
        assertFalse(runtime.diagnosticHud());
        runtime.setPerformanceProfile("render60");
        runtime.setDiagnosticHud(true);
        ClientRuntime restored = new ClientRuntime(context);
        assertEquals("render60", restored.performanceProfile());
        assertTrue(restored.diagnosticHud());
        restored.setPerformanceProfile("throughput");
        restored.setDiagnosticHud(false);
        assertEquals("throughput", new ClientRuntime(context).performanceProfile());
        assertFalse(new ClientRuntime(context).diagnosticHud());
    }

    @Test public void invalidStoredProfileFallsBackAndInvalidChoicesCannotOverwriteIt() {
        assertTrue(preferences.edit().putString("performance-profile-v2", "unsupported-profile").commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertEquals("responsive", runtime.performanceProfile());
        for (String invalid : new String[]{"unsupported-profile", "", null}) {
            try { runtime.setPerformanceProfile(invalid); fail("Unsupported profile was accepted"); }
            catch (IllegalArgumentException expected) { }
        }
        assertEquals("unsupported-profile", preferences.getString("performance-profile-v2", ""));
        runtime.setPerformanceProfile("responsive");
        assertEquals("responsive", new ClientRuntime(context).performanceProfile());
    }

    @Test public void upgradeRestoresBaselineAndIndependentExperimentsPersist() {
        assertTrue(preferences.edit().putString("performance-profile", "throughput").commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertEquals("responsive", runtime.performanceProfile());
        assertFalse(runtime.earlyDisplayRequests());
        assertFalse(runtime.disableConcurrentBinning());
        assertFalse(runtime.disableLrcpc2());
        for (String profile : new String[]{"render60", "queue2", "display60", "throughput", "responsive"}) {
            runtime.setPerformanceProfile(profile);
            assertEquals(profile, new ClientRuntime(context).performanceProfile());
        }
        for (String option : new String[]{"early-display-requests", "disable-concurrent-binning", "disable-lrcpc2"}) {
            runtime.setPerformanceOption(option, true);
            assertTrue(new ClientRuntime(context).performanceOption(option));
            RuntimeService.busy = true;
            try { runtime.setPerformanceOption(option, false); fail("Running option changed"); }
            catch (IllegalStateException expected) { }
            finally { RuntimeService.busy = false; }
            assertTrue(runtime.performanceOption(option));
            runtime.setPerformanceOption(option, false);
            assertFalse(new ClientRuntime(context).performanceOption(option));
        }
        try { runtime.setPerformanceOption("FEX_UNSAFE", true); fail("Unsupported flag accepted"); }
        catch (IllegalArgumentException expected) { }
    }

    private static void expectSettingsBlocked(ClientRuntime runtime) {
        try { runtime.setPerformanceProfile("responsive"); fail("Active client settings changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setDiagnosticHud(true); fail("Active client diagnostics changed"); }
        catch (IllegalStateException expected) { }
        assertEquals("responsive", runtime.performanceProfile());
        assertFalse(runtime.diagnosticHud());
    }

    @Test public void busyAndLiveSessionsRejectChangesWithoutMutatingPreferences() {
        ClientRuntime runtime = new ClientRuntime(context);
        RuntimeService.busy = true;
        try { expectSettingsBlocked(runtime); }
        finally { RuntimeService.busy = false; }
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        try { assertTrue(runtime.alive()); expectSettingsBlocked(runtime); }
        finally { ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null); }
        runtime.setPerformanceProfile("render60");
        runtime.setDiagnosticHud(true);
        assertEquals("render60", runtime.performanceProfile());
        assertTrue(runtime.diagnosticHud());
    }

    @Test public void launcherSelectionsPersistAcrossTabRendersAndKeepTopStartButtons() {
        ActivityController<MainActivity> owned = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            MainActivity activity = owned.get();
            View root = activity.findViewById(android.R.id.content);
            Button startServer = root.findViewWithTag("start-server");
            Button startClient = root.findViewWithTag("start-client");
            assertTopStart(startServer); assertTopStart(startClient);
            button(root, "Client").performClick(); idle();
            Spinner choice = profile(root);
            assertEquals(0, choice.getSelectedItemPosition());
            assertTrue(choice.isEnabled());
            choice.setSelection(1); idle();
            assertEquals("render60", new ClientRuntime(context).performanceProfile());
            checkBox(root, "Show frame-time and GPU diagnostics").performClick();
            assertTrue(new ClientRuntime(context).diagnosticHud());
            checkBox(root, "Disable concurrent binning (Adreno experiment)").performClick();
            assertTrue(new ClientRuntime(context).disableConcurrentBinning());
            button(root, "Server").performClick(); idle();
            button(root, "Client").performClick(); idle();
            assertEquals(1, profile(root).getSelectedItemPosition());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isChecked());
            assertTrue(checkBox(root, "Disable concurrent binning (Adreno experiment)").isChecked());
            assertSame(startServer, root.findViewWithTag("start-server"));
            assertSame(startClient, root.findViewWithTag("start-client"));
            assertTopStart(startServer); assertTopStart(startClient);
        } finally { owned.pause().stop().destroy(); }
    }

    @Test public void launcherDisablesPerformanceControlsWhileBusyRunningOrUsingSoftware() {
        ActivityController<MainActivity> owned = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            View root = owned.get().findViewById(android.R.id.content);
            button(root, "Client").performClick(); idle();
            assertTrue(profile(root).isEnabled());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            RuntimeService.busy = true; refresh();
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertFalse(checkBox(root, "Request next display frame early").isEnabled());
            assertFalse(checkBox(root, "Disable concurrent binning (Adreno experiment)").isEnabled());
            assertFalse(checkBox(root, "Use alternate CPU load instructions (FEX experiment)").isEnabled());
            RuntimeService.busy = false;
            ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
            refresh();
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null); refresh();
            checkBox(root, "Use Adreno GPU rendering").performClick();
            assertEquals("software", new ClientRuntime(context).renderer());
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            checkBox(root, "Use Adreno GPU rendering").performClick();
            assertTrue(profile(root).isEnabled());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
        } finally {
            RuntimeService.busy = false;
            ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
            owned.pause().stop().destroy();
        }
    }

    @Test public void normalAndRoundAdaptiveIconsHaveOpaqueDarkBackgroundEdges() throws Exception {
        int normalId = context.getResources().getIdentifier("ic_launcher", "mipmap", context.getPackageName());
        int roundId = context.getResources().getIdentifier("ic_launcher_round", "mipmap", context.getPackageName());
        assertNotEquals(0, normalId); assertNotEquals(0, roundId);
        assertEquals(normalId, context.getApplicationInfo().icon);
        // Robolectric 4.14.1's PackageManager icon method only reads its explicit test map.
        // Load the resource selected by the manifest to exercise the actual packaged artwork.
        assertTrue(context.getDrawable(context.getApplicationInfo().icon) instanceof AdaptiveIconDrawable);
        for (int id : new int[]{normalId, roundId}) {
            Drawable icon = context.getDrawable(id);
            assertTrue("Android uses adaptive artwork for both launcher shapes", icon instanceof AdaptiveIconDrawable);
            assertOpaqueDarkEdges(((AdaptiveIconDrawable) icon).getBackground());
        }
    }

    @Test public void legacyVectorAlsoFillsItsEdgesWithDarkArtwork() {
        Drawable fallback = context.getDrawable(context.getResources().getIdentifier("ic_launcher", "drawable", context.getPackageName()));
        assertNotNull(fallback);
        assertOpaqueDarkEdges(fallback);
    }

    private static void assertOpaqueDarkEdges(Drawable drawable) {
        Bitmap bitmap = Bitmap.createBitmap(216, 216, Bitmap.Config.ARGB_8888);
        drawable.setBounds(0, 0, bitmap.getWidth(), bitmap.getHeight());
        drawable.draw(new Canvas(bitmap));
        for (int offset = 0; offset < bitmap.getWidth(); offset++) {
            for (int color : new int[]{bitmap.getPixel(offset, 0), bitmap.getPixel(offset, 215), bitmap.getPixel(0, offset), bitmap.getPixel(215, offset)}) {
                assertEquals("Launcher background covers its full edge", 255, Color.alpha(color));
                assertTrue("Launcher edge is dark rather than white", Math.max(Color.red(color), Math.max(Color.green(color), Color.blue(color))) <= 64);
            }
        }
        bitmap.recycle();
    }

    private static void assertTopStart(Button button) {
        assertNotNull(button); assertEquals(View.VISIBLE, button.getVisibility());
        for (ViewParent parent = button.getParent(); parent != null; parent = parent.getParent())
            assertFalse("Start controls stay outside the scrolling tab content", parent instanceof ScrollView);
        View startRow = (View) button.getParent();
        ViewGroup deck = (ViewGroup) startRow.getParent();
        int scrollingContent = -1;
        for (int index = 0; index < deck.getChildCount(); index++)
            if (deck.getChildAt(index) instanceof ScrollView) scrollingContent = index;
        assertTrue("Tab content exists beneath the fixed controls", scrollingContent >= 0);
        assertTrue("Start controls remain above the scrolling tabs", deck.indexOfChild(startRow) < scrollingContent);
    }

    private static View find(View root, Class<?> type, String text, boolean description) {
        String actual = description ? String.valueOf(root.getContentDescription()) : root instanceof TextView ? ((TextView) root).getText().toString() : "";
        if (type.isInstance(root) && text.equals(actual)) return root;
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) {
            View found = find(((ViewGroup) root).getChildAt(i), type, text, description);
            if (found != null) return found;
        }
        return null;
    }
    private static Button button(View root, String text) {
        Button button = (Button) find(root, Button.class, text, false); assertNotNull("Missing button: " + text, button); return button;
    }
    private static CheckBox checkBox(View root, String text) {
        CheckBox box = (CheckBox) find(root, CheckBox.class, text, false); assertNotNull("Missing checkbox: " + text, box); return box;
    }
    private static Spinner profile(View root) {
        Spinner spinner = (Spinner) find(root, Spinner.class, "Client performance profile", true); assertNotNull(spinner); return spinner;
    }
    private static void idle() { Shadows.shadowOf(Looper.getMainLooper()).idle(); }
    private static void refresh() { Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1)); }

    /** Represents only the Java process-alive contract; launches no native process. */
    private static final class LiveProcess extends Process {
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { return 0; }
        @Override public int exitValue() { throw new IllegalThreadStateException("Test session is alive"); }
        @Override public void destroy() { }
        @Override public boolean isAlive() { return true; }
    }
}
