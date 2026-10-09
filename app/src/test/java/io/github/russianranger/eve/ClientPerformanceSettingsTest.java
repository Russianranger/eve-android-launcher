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
import java.io.IOException;
import java.io.OutputStream;
import java.io.File;
import java.nio.file.Files;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.json.JSONObject;
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
    private static final String MESA262_LABEL = "Use newer Turnip driver (26.2.4 experiment)";
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

    @Test public void separateSurfaceIsSavedIndependentlyAndDoesNotChangeGuestLaunchOrAssets() throws Exception {
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.separateDisplaySurface());
        assertFalse(runtime.status().getBoolean("separateDisplaySurface"));
        runtime.setPerformanceOption("linear-presentation", true);
        runtime.setPerformanceOption("shm-presentation", true);
        runtime.setDiagnosticHud(true);
        List<String> hardware = runtime.launchCommand("turnip-dxvk", "responsive", true);
        List<String> software = runtime.launchCommand("software", "responsive", true);
        runtime.setPerformanceOption("separate-display-surface", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.separateDisplaySurface());
        assertTrue(restored.status().getBoolean("separateDisplaySurface"));
        assertEquals(hardware, restored.launchCommand("turnip-dxvk", "responsive", true));
        assertEquals(software, restored.launchCommand("software", "responsive", true));
        assertTrue(restored.linearPresentation()); assertTrue(restored.shmPresentation());
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Reduce GPU frame copies, Shared-memory frame transport, Separate display surface"));
        restored.useAdreno(false);
        assertTrue(restored.separateDisplaySurface());
        assertTrue(restored.performanceSummary().endsWith("Separate display surface (active)"));
        restored.restoreBaselineSettings();
        assertFalse(new ClientRuntime(context).separateDisplaySurface());
        assertTrue(restored.diagnosticHud());
        assertTrue(preferences.edit().putString("separate-display-surface", "true").commit());
        assertFalse(new ClientRuntime(context).separateDisplaySurface());
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
        assertFalse(runtime.a740PcMode());
        assertFalse(runtime.linearPresentation());
        assertFalse(runtime.sysmemRendering());
        assertFalse(runtime.shmPresentation());
        assertFalse(runtime.mesa262Driver());
        for (String profile : new String[]{"render60", "queue2", "display60", "throughput", "responsive"}) {
            runtime.setPerformanceProfile(profile);
            assertEquals(profile, new ClientRuntime(context).performanceProfile());
        }
        for (String option : new String[]{"early-display-requests", "disable-concurrent-binning", "disable-lrcpc2", "a740-pc-mode", "linear-presentation", "sysmem-rendering", "shm-presentation", "separate-display-surface", "mesa262-driver"}) {
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

    @Test public void a740DriverSelectionIsIndependentAndOnlyLaunchesWithGpuRendering() throws Exception {
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.a740PcMode());
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--a740-pc-mode"));
        runtime.setPerformanceOption("a740-pc-mode", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.a740PcMode());
        assertTrue(restored.status().getBoolean("a740PcMode"));
        assertTrue(restored.launchCommand("turnip-dxvk", "responsive", false).contains("--a740-pc-mode"));
        assertFalse(restored.disableConcurrentBinning());
        assertFalse(restored.disableLrcpc2());
        restored.useAdreno(false);
        assertTrue(restored.performanceOption("a740-pc-mode"));
        assertFalse(restored.a740PcMode());
        assertFalse(restored.status().getBoolean("a740PcMode"));
        assertFalse(restored.launchCommand("software", "responsive", false).contains("--a740-pc-mode"));
        restored.useAdreno(true);
        assertTrue(new ClientRuntime(context).a740PcMode());
        restored.setPerformanceOption("a740-pc-mode", false);
        assertFalse(new ClientRuntime(context).a740PcMode());
    }

    @Test public void invalidA740PreferenceFallsBackToDisabledWithoutChangingOtherSelections() {
        assertTrue(preferences.edit().putString("a740-pc-mode", "true")
                .putBoolean("disable-concurrent-binning", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.a740PcMode());
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--a740-pc-mode"));
        assertTrue(runtime.disableConcurrentBinning());
        runtime.setPerformanceOption("a740-pc-mode", true);
        assertTrue(new ClientRuntime(context).a740PcMode());
    }

    @Test public void mesa262DriverDefaultsOffPersistsAndOnlyRunsWithGpuRendering() throws Exception {
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.mesa262Driver());
        assertFalse(runtime.status().getBoolean("mesa262Driver"));
        assertFalse(runtime.status().getBoolean("requestedMesa262Driver"));
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--mesa262-driver"));
        runtime.setPerformanceProfile("render60"); runtime.setDiagnosticHud(true);
        runtime.setPerformanceOption("linear-presentation", true);
        runtime.setPerformanceOption("separate-display-surface", true);
        runtime.setPerformanceOption("mesa262-driver", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.mesa262Driver());
        assertTrue(restored.status().getBoolean("mesa262Driver"));
        assertTrue(restored.status().getBoolean("requestedMesa262Driver"));
        assertTrue(restored.launchCommand("turnip-dxvk", "render60", true).contains("--mesa262-driver"));
        assertFalse(restored.launchCommand("software", "render60", true).contains("--mesa262-driver"));
        assertTrue(restored.linearPresentation()); assertTrue(restored.separateDisplaySurface());
        assertEquals("render60", restored.performanceProfile()); assertTrue(restored.diagnosticHud());
        assertTrue(restored.performanceSummary().endsWith("Newer Turnip driver (26.2.4)"));
        restored.useAdreno(false);
        assertTrue(restored.performanceOption("mesa262-driver"));
        assertFalse(restored.mesa262Driver());
        assertFalse(restored.status().getBoolean("mesa262Driver"));
        assertTrue(restored.status().getBoolean("requestedMesa262Driver"));
        assertFalse(restored.launchCommand("software", "render60", true).contains("--mesa262-driver"));
        assertTrue(restored.performanceSummary().endsWith("Newer Turnip driver (26.2.4) (inactive in software)"));
        restored.useAdreno(true);
        assertTrue(new ClientRuntime(context).mesa262Driver());
        restored.setPerformanceOption("mesa262-driver", false);
        assertFalse(new ClientRuntime(context).mesa262Driver());
    }

    @Test public void invalidMesa262PreferenceIsIgnoredWithoutChangingExistingSelections() throws Exception {
        assertTrue(preferences.edit().putString("mesa262-driver", "true").putBoolean("shm-presentation", true)
                .putBoolean("linear-presentation", true).putBoolean("separate-display-surface", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.mesa262Driver());
        assertFalse(runtime.status().getBoolean("requestedMesa262Driver"));
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--mesa262-driver"));
        assertTrue(runtime.shmPresentation()); assertTrue(runtime.linearPresentation()); assertTrue(runtime.separateDisplaySurface());
        runtime.setPerformanceOption("mesa262-driver", true);
        assertTrue(new ClientRuntime(context).mesa262Driver());
        assertFalse(runtime.shmPresentation());
    }

    @Test public void linearPresentationPersistsIndependentlyAndOnlyLaunchesWithGpuRendering() throws Exception {
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.linearPresentation());
        assertFalse(runtime.status().getBoolean("requestedLinearPresentation"));
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--linear-presentation"));
        runtime.setPerformanceProfile("render60");
        runtime.setPerformanceOption("disable-lrcpc2", true);
        runtime.setPerformanceOption("linear-presentation", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.linearPresentation());
        assertTrue(restored.status().getBoolean("linearPresentation"));
        assertTrue(restored.status().getBoolean("requestedLinearPresentation"));
        assertTrue(restored.launchCommand("turnip-dxvk", "render60", false).contains("--linear-presentation"));
        assertEquals("render60", restored.performanceProfile());
        assertTrue(restored.disableLrcpc2());
        assertFalse(restored.disableConcurrentBinning());
        assertFalse(restored.a740PcMode());
        restored.useAdreno(false);
        assertTrue(restored.performanceOption("linear-presentation"));
        assertTrue(restored.status().getBoolean("requestedLinearPresentation"));
        assertFalse(restored.linearPresentation());
        assertFalse(restored.status().getBoolean("linearPresentation"));
        assertFalse(restored.launchCommand("software", "render60", false).contains("--linear-presentation"));
        restored.useAdreno(true);
        assertTrue(new ClientRuntime(context).linearPresentation());
        restored.setPerformanceOption("linear-presentation", false);
        assertFalse(new ClientRuntime(context).linearPresentation());
        assertEquals("render60", restored.performanceProfile());
        assertTrue(restored.disableLrcpc2());
    }

    @Test public void invalidLinearPreferenceFallsBackWithoutResettingExistingSettings() {
        assertTrue(preferences.edit().putString("linear-presentation", "true")
                .putString("performance-profile-v2", "queue2").putBoolean("a740-pc-mode", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.linearPresentation());
        assertFalse(runtime.launchCommand("turnip-dxvk", "queue2", false).contains("--linear-presentation"));
        assertEquals("queue2", runtime.performanceProfile());
        assertTrue(runtime.a740PcMode());
        runtime.setPerformanceOption("linear-presentation", true);
        assertTrue(new ClientRuntime(context).linearPresentation());
    }

    @Test public void sysmemRenderingPersistsIndependentlyAndOnlyLaunchesWithGpuRendering() throws Exception {
        assertTrue(preferences.edit().putBoolean("linear-presentation", true)
                .putString("performance-profile-v2", "queue2").putBoolean("diagnostic-hud", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertTrue(runtime.linearPresentation());
        assertFalse(runtime.sysmemRendering());
        assertFalse(runtime.status().getBoolean("requestedSysmemRendering"));
        assertFalse(runtime.launchCommand("turnip-dxvk", "queue2", true).contains("--sysmem-rendering"));
        runtime.setPerformanceOption("sysmem-rendering", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.sysmemRendering());
        assertTrue(restored.linearPresentation());
        assertTrue(restored.status().getBoolean("requestedSysmemRendering"));
        assertTrue(restored.status().getBoolean("sysmemRendering"));
        assertTrue(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--sysmem-rendering"));
        assertTrue(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--linear-presentation"));
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Reduce GPU frame copies, Direct GPU rendering"));
        restored.setPerformanceOption("linear-presentation", false);
        assertTrue(restored.sysmemRendering());
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Direct GPU rendering"));
        assertFalse(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--linear-presentation"));
        restored.setPerformanceOption("linear-presentation", true);
        restored.useAdreno(false);
        assertFalse(restored.sysmemRendering());
        assertTrue(restored.performanceOption("sysmem-rendering"));
        assertTrue(restored.status().getBoolean("requestedSysmemRendering"));
        assertFalse(restored.status().getBoolean("sysmemRendering"));
        assertFalse(restored.launchCommand("software", "queue2", true).contains("--sysmem-rendering"));
        assertTrue(restored.performanceSummary().endsWith("Reduce GPU frame copies (inactive in software), Direct GPU rendering (inactive in software)"));
        restored.useAdreno(true);
        assertTrue(new ClientRuntime(context).sysmemRendering());
        assertTrue(restored.linearPresentation());
        assertEquals("queue2", restored.performanceProfile());
        assertTrue(restored.diagnosticHud());
        restored.setPerformanceOption("sysmem-rendering", false);
        assertFalse(new ClientRuntime(context).sysmemRendering());
        assertTrue(restored.linearPresentation());
    }

    @Test public void softwareSummaryShowsSavedGpuCapsAndKeepsEarlyDisplayRequestsActive() {
        ClientRuntime runtime = new ClientRuntime(context);
        runtime.setPerformanceProfile("throughput");
        runtime.setPerformanceOption("early-display-requests", true);
        runtime.setPerformanceOption("linear-presentation", true);
        runtime.useAdreno(false);
        assertEquals("Saved GPU caps: render 60 FPS · queue 2 frames · display 60 FPS\n"
                + "Saved experiments: Early display requests (active), Reduce GPU frame copies (inactive in software)",
                runtime.performanceSummary());
        assertTrue(runtime.earlyDisplayRequests());
        assertFalse(runtime.linearPresentation());
        runtime.restoreBaselineSettings();
        assertEquals("Saved GPU caps: render 30 FPS · queue 1 frame · display 30 FPS\nSaved experiments: none",
                runtime.performanceSummary());
    }

    @Test public void shmPresentationDefaultsOffPersistsAndOnlyLaunchesWithGpuRendering() throws Exception {
        assertTrue(preferences.edit().putBoolean("linear-presentation", true).putBoolean("sysmem-rendering", true)
                .putString("performance-profile-v2", "queue2").putBoolean("diagnostic-hud", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.shmPresentation());
        assertFalse(runtime.status().getBoolean("requestedShmPresentation"));
        assertFalse(runtime.launchCommand("turnip-dxvk", "queue2", true).contains("--shm-presentation"));
        assertTrue(runtime.linearPresentation()); assertTrue(runtime.sysmemRendering());
        runtime.setPerformanceOption("shm-presentation", true);
        ClientRuntime restored = new ClientRuntime(context);
        assertTrue(restored.shmPresentation());
        assertTrue(restored.status().getBoolean("requestedShmPresentation"));
        assertTrue(restored.status().getBoolean("shmPresentation"));
        assertTrue(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--shm-presentation"));
        assertFalse(restored.launchCommand("software", "queue2", true).contains("--shm-presentation"));
        assertTrue(restored.linearPresentation()); assertTrue(restored.sysmemRendering());
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Reduce GPU frame copies, Direct GPU rendering, Shared-memory frame transport"));
        restored.setPerformanceOption("sysmem-rendering", false);
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Reduce GPU frame copies, Shared-memory frame transport"));
        assertTrue(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--linear-presentation"));
        assertFalse(restored.launchCommand("turnip-dxvk", "queue2", true).contains("--sysmem-rendering"));
        restored.setPerformanceOption("linear-presentation", false);
        assertTrue(restored.performanceSummary().endsWith("Selected experiments: Shared-memory frame transport"));
        restored.useAdreno(false);
        assertTrue(restored.performanceOption("shm-presentation"));
        assertTrue(restored.status().getBoolean("requestedShmPresentation"));
        assertFalse(restored.shmPresentation());
        assertFalse(restored.status().getBoolean("shmPresentation"));
        assertFalse(restored.launchCommand("software", "queue2", true).contains("--shm-presentation"));
        assertTrue(restored.performanceSummary().endsWith("Saved experiments: Shared-memory frame transport (inactive in software)"));
        restored.useAdreno(true);
        assertTrue(new ClientRuntime(context).shmPresentation());
        assertEquals("queue2", restored.performanceProfile()); assertTrue(restored.diagnosticHud());
        restored.setPerformanceOption("shm-presentation", false);
        assertFalse(new ClientRuntime(context).shmPresentation());
    }

    @Test public void threeDriverChoicesAreMutuallyExclusiveInOnePreferenceTransaction() {
        ClientRuntime runtime = new ClientRuntime(context);
        runtime.setPerformanceProfile("render60"); runtime.setDiagnosticHud(true);
        runtime.setPerformanceOption("linear-presentation", true);
        runtime.setPerformanceOption("sysmem-rendering", true);
        runtime.setPerformanceOption("separate-display-surface", true);
        runtime.setPerformanceOption("a740-pc-mode", true);
        List<Map<String, ?>> snapshots = new ArrayList<>();
        SharedPreferences.OnSharedPreferenceChangeListener observe = (changed, key) -> snapshots.add(changed.getAll());
        preferences.registerOnSharedPreferenceChangeListener(observe);
        try {
            String[] driverOptions = {"shm-presentation", "mesa262-driver", "a740-pc-mode"};
            for (String chosen : driverOptions) {
                snapshots.clear();
                runtime.setPerformanceOption(chosen, true); idle();
                assertFalse("Driver choice publishes its changes", snapshots.isEmpty());
                for (Map<String, ?> snapshot : snapshots) {
                    assertEquals(true, snapshot.get(chosen));
                    for (String driver : driverOptions)
                        assertEquals("Every notification sees a single selected driver", driver.equals(chosen), snapshot.get(driver));
                    assertEquals(true, snapshot.get("linear-presentation"));
                    assertEquals(true, snapshot.get("sysmem-rendering"));
                    assertEquals("render60", snapshot.get("performance-profile-v2"));
                    assertEquals(true, snapshot.get("diagnostic-hud"));
                    assertEquals(true, snapshot.get("separate-display-surface"));
                }
                ClientRuntime restored = new ClientRuntime(context);
                for (String driver : driverOptions) assertEquals(driver.equals(chosen), restored.performanceOption(driver));
                for (String other : driverOptions) if (!other.equals(chosen)) {
                    runtime.setPerformanceOption(other, false);
                    assertTrue("Disabling another option keeps the chosen driver", runtime.performanceOption(chosen));
                }
            }
        } finally { preferences.unregisterOnSharedPreferenceChangeListener(observe); }
    }

    @Test public void invalidShmPreferenceFallsBackWithoutResettingExistingSelections() {
        assertTrue(preferences.edit().putString("shm-presentation", "true").putBoolean("a740-pc-mode", true)
                .putBoolean("linear-presentation", true).putBoolean("sysmem-rendering", true).commit());
        ClientRuntime runtime = new ClientRuntime(context);
        assertFalse(runtime.shmPresentation());
        assertFalse(runtime.launchCommand("turnip-dxvk", "responsive", false).contains("--shm-presentation"));
        assertTrue(runtime.a740PcMode()); assertTrue(runtime.linearPresentation()); assertTrue(runtime.sysmemRendering());
        runtime.setPerformanceOption("shm-presentation", true);
        assertTrue(new ClientRuntime(context).shmPresentation());
        assertFalse(runtime.a740PcMode());
    }

    @Test public void explicitBaselineRestoreClearsEveryExperimentTogetherAndPreservesOtherSettings() {
        String[] options = {"early-display-requests", "disable-concurrent-binning", "disable-lrcpc2", "a740-pc-mode", "linear-presentation", "sysmem-rendering", "shm-presentation", "separate-display-surface", "mesa262-driver"};
        for (boolean adreno : new boolean[]{true, false}) {
            SharedPreferences.Editor setup = preferences.edit().putString("performance-profile-v2", "throughput")
                    .putBoolean("use-adreno", adreno).putBoolean("diagnostic-hud", true).putString("unrelated-setting", "preserved");
            for (String option : options) setup.putBoolean(option, true);
            assertTrue(setup.commit());
            List<Map<String, ?>> snapshots = new ArrayList<>();
            SharedPreferences.OnSharedPreferenceChangeListener observe = (changed, key) -> snapshots.add(changed.getAll());
            preferences.registerOnSharedPreferenceChangeListener(observe);
            try {
                new ClientRuntime(context).restoreBaselineSettings(); idle();
                assertFalse("Reset publishes its changed settings", snapshots.isEmpty());
                for (Map<String, ?> snapshot : snapshots) {
                    assertEquals("responsive", snapshot.get("performance-profile-v2"));
                    for (String option : options) assertEquals("Every notification sees the complete reset", false, snapshot.get(option));
                    assertEquals(adreno, snapshot.get("use-adreno"));
                    assertEquals(true, snapshot.get("diagnostic-hud"));
                    assertEquals("preserved", snapshot.get("unrelated-setting"));
                }
                ClientRuntime restored = new ClientRuntime(context);
                assertEquals("responsive", restored.performanceProfile());
                for (String option : options) assertFalse(restored.performanceOption(option));
                assertEquals(adreno ? "turnip-dxvk" : "software", restored.renderer());
                assertTrue(restored.diagnosticHud());
                assertEquals("preserved", preferences.getString("unrelated-setting", ""));
                assertTrue(restored.performanceSummary().endsWith("none"));
            } finally { preferences.unregisterOnSharedPreferenceChangeListener(observe); }
        }
    }

    @Test public void explicitBaselineRestoreRejectsBusyAndLiveSessionsWithoutClearingTheirSelections() {
        ClientRuntime runtime = new ClientRuntime(context);
        runtime.setPerformanceProfile("throughput"); runtime.setPerformanceOption("linear-presentation", true);
        RuntimeService.busy = true;
        try { runtime.restoreBaselineSettings(); fail("Busy session reset accepted"); }
        catch (IllegalStateException expected) { }
        finally { RuntimeService.busy = false; }
        assertEquals("throughput", runtime.performanceProfile()); assertTrue(runtime.linearPresentation());
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        try { runtime.restoreBaselineSettings(); fail("Live session reset accepted"); }
        catch (IllegalStateException expected) { }
        finally { ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null); }
        assertEquals("throughput", runtime.performanceProfile()); assertTrue(runtime.linearPresentation());
    }

    @Test public void baselineCapsKeepExperimentsVisibleUntilExplicitRestoreUpdatesAllControls() {
        ClientRuntime runtime = new ClientRuntime(context);
        runtime.setPerformanceProfile("render60"); runtime.setDiagnosticHud(true);
        for (String option : new String[]{"early-display-requests", "disable-concurrent-binning", "disable-lrcpc2", "a740-pc-mode", "linear-presentation", "sysmem-rendering", "shm-presentation", "separate-display-surface", "mesa262-driver"})
            runtime.setPerformanceOption(option, true);
        ActivityController<MainActivity> owned = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            View root = owned.get().findViewById(android.R.id.content);
            button(root, "Client").performClick(); idle();
            assertEquals(1, profile(root).getSelectedItemPosition());
            profile(root).setSelection(0); idle();
            assertEquals("responsive", new ClientRuntime(context).performanceProfile());
            assertTrue(new ClientRuntime(context).linearPresentation());
            assertTrue(checkBox(root, "Reduce GPU frame copies (experiment)").isChecked());
            assertTrue(performanceSummary(root).getText().toString().startsWith("Baseline caps:"));
            assertTrue(performanceSummary(root).getText().toString().contains("Reduce GPU frame copies"));
            button(root, "Restore baseline settings").performClick();
            assertEquals(0, profile(root).getSelectedItemPosition());
            for (String label : new String[]{"Request next display frame early", "Disable concurrent binning (Adreno experiment)",
                    "Use alternate CPU load instructions (FEX experiment)", "Use A740 driver experiment", "Reduce GPU frame copies (experiment)",
                    "Use direct GPU rendering (experiment)", "Use shared-memory frame transport (experiment)", "Use separate display surface (experiment)", MESA262_LABEL})
                assertFalse("Reset immediately clears " + label, checkBox(root, label).isChecked());
            assertEquals("Baseline caps: render 30 FPS · queue 1 frame · display 30 FPS\nSelected experiments: none",
                    performanceSummary(root).getText().toString());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isChecked());
            assertTrue(checkBox(root, "Use Adreno GPU rendering").isChecked());
            idle();
            assertFalse(new ClientRuntime(context).linearPresentation());
        } finally { owned.pause().stop().destroy(); }
    }

    @Test public void graphicsAssetSelectionKeepsBaselineAndRequiresBothPinnedExperimentAssets() throws Exception {
        JSONObject manifest = baselineGraphicsManifest();
        String[] baseline = {"turnip-26.0.0.so", "vulkan-probe", "dxvk-d3d11-arm64ec.dll", "dxvk-dxgi-arm64ec.dll", "eve-d3d11-probe.exe"};
        assertArrayEquals(baseline, ClientRuntime.graphicsAssetNames(manifest, false));
        expectInvalidGraphicsAssets(manifest, true);
        JSONObject experiment = new JSONObject().put("format", 1).put("name", "turnip-a740-pc-mode-1")
                .put("driver", "turnip-26.0.0-a740-pc-mode.so").put("identityProbe", "a740-driver-probe")
                .put("upstreamCommit", "23f94c692cb1d41a2193a80fa531922d386e8d5d");
        manifest.put("a740PcModeExperiment", experiment);
        JSONObject files = manifest.getJSONObject("files");
        files.put("turnip-26.0.0-a740-pc-mode.so", new JSONObject());
        expectInvalidGraphicsAssets(manifest, true);
        files.put("a740-driver-probe", new JSONObject());
        String[] extended = ClientRuntime.graphicsAssetNames(manifest, true);
        assertEquals(7, extended.length);
        assertTrue(Arrays.asList(extended).containsAll(Arrays.asList(baseline)));
        assertTrue(Arrays.asList(extended).contains("turnip-26.0.0-a740-pc-mode.so"));
        assertTrue(Arrays.asList(extended).contains("a740-driver-probe"));
        assertArrayEquals(extended, ClientRuntime.graphicsAssetNames(manifest, false));
        experiment.put("upstreamCommit", "unqualified-driver-change");
        expectInvalidGraphicsAssets(manifest, true);
        experiment.put("upstreamCommit", "23f94c692cb1d41a2193a80fa531922d386e8d5d");
        experiment.put("format", "1");
        expectInvalidGraphicsAssets(manifest, true);
    }

    @Test public void unknownGraphicsAssetsCannotReplaceAnyBaselineAsset() throws Exception {
        JSONObject manifest = baselineGraphicsManifest();
        JSONObject files = manifest.getJSONObject("files");
        files.remove("turnip-26.0.0.so");
        files.put("turnip-unqualified.so", new JSONObject());
        expectInvalidGraphicsAssets(manifest, false);
        files.put("turnip-26.0.0.so", new JSONObject());
        expectInvalidGraphicsAssets(manifest, false);
    }

    @Test public void shmGraphicsAssetsRequireSharedIdentityProbeAndFormAnExactUnion() throws Exception {
        JSONObject manifest = baselineGraphicsManifest();
        expectInvalidGraphicsAssets(manifest, false, true);
        JSONObject shm = new JSONObject().put("format", 1).put("name", "turnip-x11-shm-staging-1")
                .put("driver", "turnip-26.0.0-x11-shm.so")
                .put("mesaSourceSha256", "2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72");
        manifest.put("shmPresentationExperiment", shm);
        JSONObject files = manifest.getJSONObject("files");
        expectInvalidGraphicsAssets(manifest, false, true);
        files.put("turnip-26.0.0-x11-shm.so", new JSONObject());
        expectInvalidGraphicsAssets(manifest, false, true);
        files.put("a740-driver-probe", new JSONObject());
        String[] shmOnly = ClientRuntime.graphicsAssetNames(manifest, false, true);
        assertEquals(7, shmOnly.length);
        assertTrue(Arrays.asList(shmOnly).contains("turnip-26.0.0.so"));
        assertTrue(Arrays.asList(shmOnly).contains("turnip-26.0.0-x11-shm.so"));
        assertTrue(Arrays.asList(shmOnly).contains("a740-driver-probe"));
        assertArrayEquals(shmOnly, ClientRuntime.graphicsAssetNames(manifest, false, false));
        expectInvalidGraphicsAssets(manifest, true, false);
        manifest.put("a740PcModeExperiment", new JSONObject().put("format", 1).put("name", "turnip-a740-pc-mode-1")
                .put("driver", "turnip-26.0.0-a740-pc-mode.so").put("identityProbe", "a740-driver-probe")
                .put("upstreamCommit", "23f94c692cb1d41a2193a80fa531922d386e8d5d"));
        expectInvalidGraphicsAssets(manifest, false, true);
        files.put("turnip-26.0.0-a740-pc-mode.so", new JSONObject());
        String[] both = ClientRuntime.graphicsAssetNames(manifest, false, true);
        assertEquals(8, both.length);
        assertEquals(1, java.util.Collections.frequency(Arrays.asList(both), "a740-driver-probe"));
        assertTrue(Arrays.asList(both).containsAll(Arrays.asList(shmOnly)));
        assertArrayEquals(both, ClientRuntime.graphicsAssetNames(manifest, true, false));
        assertArrayEquals(both, ClientRuntime.graphicsAssetNames(manifest, false, false));
        shm.put("format", "1"); expectInvalidGraphicsAssets(manifest, false, true);
        shm.put("format", 1).put("name", "unqualified-transport"); expectInvalidGraphicsAssets(manifest, false, true);
        shm.put("name", "turnip-x11-shm-staging-1").put("driver", "turnip-unqualified.so");
        expectInvalidGraphicsAssets(manifest, false, true);
        shm.put("driver", "turnip-26.0.0-x11-shm.so").put("mesaSourceSha256", "unqualified-source");
        expectInvalidGraphicsAssets(manifest, false, true);
        shm.put("mesaSourceSha256", "2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72");
        files.put("unqualified-probe", new JSONObject()); expectInvalidGraphicsAssets(manifest, false, true);
    }

    @Test public void mesa262GraphicsAssetsRequireExactSourceAndHardwareProvenanceEvenWhenNotSelected() throws Exception {
        JSONObject baseline = baselineGraphicsManifest();
        expectInvalidGraphicsAssets(baseline, false, false, true);
        JSONObject manifest = mesa262GraphicsManifest();
        String[] names = ClientRuntime.graphicsAssetNames(manifest, false, false, true);
        assertEquals(8, names.length);
        assertTrue(Arrays.asList(names).containsAll(Arrays.asList(ClientRuntime.graphicsAssetNames(baseline, false))));
        assertTrue(Arrays.asList(names).contains("turnip-26.2.4.so"));
        assertTrue(Arrays.asList(names).contains("mesa262-driver-probe"));
        assertTrue(Arrays.asList(names).contains("a740-driver-probe"));
        assertArrayEquals(names, ClientRuntime.graphicsAssetNames(manifest, false, false, false));
        Object[][] corrupt = {{"format", "1"}, {"format", 2}, {"name", "turnip-unqualified"},
                {"driver", "turnip-26.0.0.so"}, {"identityProbe", "a740-driver-probe"}, {"mesa", "26.2.3"},
                {"mesaSourceSha256", "unqualified-source"}, {"probeSourceSha256", "unqualified-probe-source"},
                {"deviceId", "0x43050a01"}, {"deviceId", 0x43050a02}, {"pristine", "true"}, {"pristine", false},
                {"extraField", true}};
        for (Object[] change : corrupt) {
            JSONObject damaged = mesa262GraphicsManifest();
            damaged.getJSONObject("mesa262DriverExperiment").put((String) change[0], change[1]);
            expectInvalidGraphicsAssets(damaged, false, false, true);
            expectInvalidGraphicsAssets(damaged, false, false, false);
        }
        for (String field : new String[]{"format", "name", "driver", "identityProbe", "mesa", "mesaSourceSha256",
                "probeSourceSha256", "deviceId", "pristine"}) {
            JSONObject damaged = mesa262GraphicsManifest();
            damaged.getJSONObject("mesa262DriverExperiment").remove(field);
            expectInvalidGraphicsAssets(damaged, false, false, true);
        }
        for (String missing : new String[]{"turnip-26.0.0.so", "turnip-26.2.4.so", "mesa262-driver-probe", "a740-driver-probe"}) {
            JSONObject damaged = mesa262GraphicsManifest();
            damaged.getJSONObject("files").remove(missing);
            expectInvalidGraphicsAssets(damaged, false, false, true);
        }
        manifest.getJSONObject("files").put("unqualified-driver.so", new JSONObject());
        expectInvalidGraphicsAssets(manifest, false, false, true);
    }

    @Test public void mesa262AssetListRetainsBothExistingOptionalDriversAndSharedProbeExactlyOnce() throws Exception {
        JSONObject manifest = mesa262GraphicsManifest();
        manifest.put("a740PcModeExperiment", new JSONObject().put("format", 1).put("name", "turnip-a740-pc-mode-1")
                .put("driver", "turnip-26.0.0-a740-pc-mode.so").put("identityProbe", "a740-driver-probe")
                .put("upstreamCommit", "23f94c692cb1d41a2193a80fa531922d386e8d5d"));
        manifest.put("shmPresentationExperiment", new JSONObject().put("format", 1).put("name", "turnip-x11-shm-staging-1")
                .put("driver", "turnip-26.0.0-x11-shm.so")
                .put("mesaSourceSha256", "2a44e98e64d5c36cec64633de2d0ec7eff64703ee25b35364ba8fcaa84f33f72"));
        JSONObject files = manifest.getJSONObject("files");
        for (String name : new String[]{"turnip-26.0.0-a740-pc-mode.so", "a740-driver-probe", "turnip-26.0.0-x11-shm.so"})
            files.put(name, new JSONObject());
        List<String> names = Arrays.asList(ClientRuntime.graphicsAssetNames(manifest, false, false, true));
        assertEquals(10, names.size());
        assertEquals(1, java.util.Collections.frequency(names, "a740-driver-probe"));
        assertTrue(names.containsAll(Arrays.asList("turnip-26.0.0.so", "turnip-26.0.0-a740-pc-mode.so",
                "turnip-26.0.0-x11-shm.so", "turnip-26.2.4.so", "mesa262-driver-probe")));
    }

    @Test public void graphicsAssetGuardRejectsChangedBytesSizesMissingFilesAndSymlinks() throws Exception {
        File directory = Files.createTempDirectory("eve-graphics-identity-").toFile();
        File driver = new File(directory, "turnip-26.2.4.so");
        File link = new File(directory, "mesa262-driver-probe");
        try {
            RuntimeManager.text(driver, "verified-driver-fixture");
            JSONObject identity = new JSONObject().put("sizeBytes", driver.length()).put("sha256", RuntimeManager.sha256(driver));
            ClientRuntime.validateGraphicsAsset(driver, identity);
            JSONObject wrongSize = new JSONObject(identity.toString()).put("sizeBytes", driver.length() + 1);
            expectInvalidGraphicsAsset(driver, wrongSize);
            RuntimeManager.text(driver, "modified-driver-fixture");
            assertEquals("Corruption fixture keeps its size", identity.getLong("sizeBytes"), driver.length());
            expectInvalidGraphicsAsset(driver, identity);
            RuntimeManager.text(driver, "verified-driver-fixture");
            Files.createSymbolicLink(link.toPath(), driver.toPath());
            expectInvalidGraphicsAsset(link, identity);
            assertTrue(driver.delete());
            expectInvalidGraphicsAsset(driver, identity);
        } finally { Files.deleteIfExists(link.toPath()); RuntimeManager.remove(directory); }
    }

    @Test public void runtimeExtractsPackagedMesa262AssetsAndMakesItsIdentityProbeExecutable() throws Exception {
        RuntimeManager manager = RuntimeManager.get(context);
        manager.assets();
        JSONObject manifest = new JSONObject(RuntimeManager.read(new File(manager.backend, "client-graphics-bundle.json"), 131072));
        String[] names = ClientRuntime.graphicsAssetNames(manifest, false, false, true);
        assertEquals(10, names.length);
        JSONObject files = manifest.getJSONObject("files");
        for (String name : names) {
            File extracted = new File(manager.backend, name);
            ClientRuntime.validateGraphicsAsset(extracted, files.getJSONObject(name));
        }
        assertTrue(new File(manager.backend, "mesa262-driver-probe").canExecute());
        assertFalse(Files.isSymbolicLink(new File(manager.backend, "turnip-26.2.4.so").toPath()));
        String[] staged = manager.backend.list((directory, name) -> name.startsWith("asset-") && name.endsWith(".tmp"));
        assertNotNull(staged); assertEquals(0, staged.length);
    }

    private static JSONObject mesa262GraphicsManifest() throws Exception {
        JSONObject manifest = baselineGraphicsManifest();
        manifest.put("mesa262DriverExperiment", new JSONObject().put("format", 1).put("name", "turnip-mesa-26.2.4-1")
                .put("driver", "turnip-26.2.4.so").put("identityProbe", "mesa262-driver-probe").put("mesa", "26.2.4")
                .put("mesaSourceSha256", "bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9")
                .put("probeSourceSha256", "bb96b8e0721e167d20d8b15e433d180b79447b0bdb8f85dfaa614aa867c09d37")
                .put("deviceId", 0x43050a01).put("pristine", true));
        manifest.getJSONObject("files").put("turnip-26.2.4.so", new JSONObject()).put("mesa262-driver-probe", new JSONObject())
                .put("a740-driver-probe", new JSONObject());
        return manifest;
    }

    private static void expectInvalidGraphicsAsset(File source, JSONObject identity) throws Exception {
        try { ClientRuntime.validateGraphicsAsset(source, identity); fail("Damaged graphics asset accepted"); }
        catch (IOException expected) { }
    }

    private static void expectInvalidGraphicsAssets(JSONObject manifest, boolean a740Enabled, boolean shmEnabled, boolean mesa262Enabled) throws Exception {
        try { ClientRuntime.graphicsAssetNames(manifest, a740Enabled, shmEnabled, mesa262Enabled); fail("Invalid graphics asset selection accepted"); }
        catch (IOException expected) { }
    }

    private static JSONObject baselineGraphicsManifest() throws Exception {
        JSONObject files = new JSONObject();
        for (String name : new String[]{"turnip-26.0.0.so", "vulkan-probe", "dxvk-d3d11-arm64ec.dll", "dxvk-dxgi-arm64ec.dll", "eve-d3d11-probe.exe"})
            files.put(name, new JSONObject());
        return new JSONObject().put("files", files);
    }

    private static void expectInvalidGraphicsAssets(JSONObject manifest, boolean experimentEnabled) throws Exception {
        try { ClientRuntime.graphicsAssetNames(manifest, experimentEnabled); fail("Invalid graphics asset selection accepted"); }
        catch (IOException expected) { }
    }

    private static void expectInvalidGraphicsAssets(JSONObject manifest, boolean a740Enabled, boolean shmEnabled) throws Exception {
        try { ClientRuntime.graphicsAssetNames(manifest, a740Enabled, shmEnabled); fail("Invalid graphics asset selection accepted"); }
        catch (IOException expected) { }
    }

    private static void expectSettingsBlocked(ClientRuntime runtime) {
        try { runtime.setPerformanceProfile("responsive"); fail("Active client settings changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setDiagnosticHud(true); fail("Active client diagnostics changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setPerformanceOption("a740-pc-mode", true); fail("Active client driver changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setPerformanceOption("linear-presentation", true); fail("Active client presentation changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setPerformanceOption("sysmem-rendering", true); fail("Active client rendering experiment changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setPerformanceOption("shm-presentation", true); fail("Active client transport experiment changed"); }
        catch (IllegalStateException expected) { }
        try { runtime.setPerformanceOption("mesa262-driver", true); fail("Active client newer driver changed"); }
        catch (IllegalStateException expected) { }
        assertEquals("responsive", runtime.performanceProfile());
        assertFalse(runtime.diagnosticHud());
        assertFalse(runtime.a740PcMode());
        assertFalse(runtime.linearPresentation());
        assertFalse(runtime.sysmemRendering());
        assertFalse(runtime.shmPresentation());
        assertFalse(runtime.mesa262Driver());
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
            checkBox(root, "Use A740 driver experiment").performClick();
            assertTrue(new ClientRuntime(context).a740PcMode());
            checkBox(root, "Reduce GPU frame copies (experiment)").performClick();
            assertTrue(new ClientRuntime(context).linearPresentation());
            checkBox(root, "Use direct GPU rendering (experiment)").performClick();
            assertTrue(new ClientRuntime(context).sysmemRendering());
            button(root, "Server").performClick(); idle();
            button(root, "Client").performClick(); idle();
            assertEquals(1, profile(root).getSelectedItemPosition());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isChecked());
            assertTrue(checkBox(root, "Disable concurrent binning (Adreno experiment)").isChecked());
            assertTrue(checkBox(root, "Use A740 driver experiment").isChecked());
            assertTrue(checkBox(root, "Reduce GPU frame copies (experiment)").isChecked());
            assertTrue(checkBox(root, "Use direct GPU rendering (experiment)").isChecked());
            assertSame(startServer, root.findViewWithTag("start-server"));
            assertSame(startClient, root.findViewWithTag("start-client"));
            assertTopStart(startServer); assertTopStart(startClient);
        } finally { owned.pause().stop().destroy(); }
    }

    @Test public void launcherDriverChoicesImmediatelyUpdateTheOtherCheckboxAndSummary() {
        ClientRuntime runtime = new ClientRuntime(context);
        runtime.setPerformanceOption("linear-presentation", true);
        runtime.setPerformanceOption("sysmem-rendering", true);
        ActivityController<MainActivity> owned = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            View root = owned.get().findViewById(android.R.id.content);
            button(root, "Client").performClick(); idle();
            checkBox(root, "Use A740 driver experiment").performClick();
            assertTrue(checkBox(root, "Use A740 driver experiment").isChecked());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isChecked());
            assertFalse(checkBox(root, MESA262_LABEL).isChecked());
            checkBox(root, "Use shared-memory frame transport (experiment)").performClick();
            assertTrue(checkBox(root, "Use shared-memory frame transport (experiment)").isChecked());
            assertFalse(checkBox(root, "Use A740 driver experiment").isChecked());
            assertFalse(checkBox(root, MESA262_LABEL).isChecked());
            assertTrue(checkBox(root, "Reduce GPU frame copies (experiment)").isChecked());
            assertTrue(checkBox(root, "Use direct GPU rendering (experiment)").isChecked());
            assertTrue(performanceSummary(root).getText().toString().endsWith(
                    "Selected experiments: Reduce GPU frame copies, Direct GPU rendering, Shared-memory frame transport"));
            button(root, "Server").performClick(); idle();
            button(root, "Client").performClick(); idle();
            assertTrue(checkBox(root, "Use shared-memory frame transport (experiment)").isChecked());
            assertFalse(checkBox(root, "Use A740 driver experiment").isChecked());
            checkBox(root, MESA262_LABEL).performClick();
            assertTrue(checkBox(root, MESA262_LABEL).isChecked());
            assertFalse(checkBox(root, "Use A740 driver experiment").isChecked());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isChecked());
            assertTrue(checkBox(root, "Reduce GPU frame copies (experiment)").isChecked());
            assertTrue(checkBox(root, "Use direct GPU rendering (experiment)").isChecked());
            assertTrue(performanceSummary(root).getText().toString().endsWith(
                    "Selected experiments: Reduce GPU frame copies, Direct GPU rendering, Newer Turnip driver (26.2.4)"));
            button(root, "Server").performClick(); idle();
            button(root, "Client").performClick(); idle();
            assertTrue(checkBox(root, MESA262_LABEL).isChecked());
            assertTrue(new ClientRuntime(context).mesa262Driver());
            checkBox(root, "Use A740 driver experiment").performClick();
            assertTrue(checkBox(root, "Use A740 driver experiment").isChecked());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isChecked());
            assertFalse(checkBox(root, MESA262_LABEL).isChecked());
            assertTrue(performanceSummary(root).getText().toString().endsWith(
                    "Selected experiments: A740 driver, Reduce GPU frame copies, Direct GPU rendering"));
            assertFalse(new ClientRuntime(context).shmPresentation());
            assertTrue(new ClientRuntime(context).a740PcMode());
            assertFalse(new ClientRuntime(context).mesa262Driver());
        } finally { owned.pause().stop().destroy(); }
    }

    @Test public void launcherDisablesPerformanceControlsWhileBusyRunningOrUsingSoftware() {
        ActivityController<MainActivity> owned = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            View root = owned.get().findViewById(android.R.id.content);
            button(root, "Client").performClick(); idle();
            assertTrue(profile(root).isEnabled());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertTrue(button(root, "Restore baseline settings").isEnabled());
            assertTrue(checkBox(root, "Use direct GPU rendering (experiment)").isEnabled());
            assertTrue(checkBox(root, "Use shared-memory frame transport (experiment)").isEnabled());
            assertTrue(checkBox(root, MESA262_LABEL).isEnabled());
            RuntimeService.busy = true; refresh();
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertFalse(checkBox(root, "Request next display frame early").isEnabled());
            assertFalse(checkBox(root, "Disable concurrent binning (Adreno experiment)").isEnabled());
            assertFalse(checkBox(root, "Use alternate CPU load instructions (FEX experiment)").isEnabled());
            assertFalse(checkBox(root, "Use A740 driver experiment").isEnabled());
            assertFalse(checkBox(root, "Reduce GPU frame copies (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use direct GPU rendering (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isEnabled());
            assertFalse(checkBox(root, MESA262_LABEL).isEnabled());
            assertFalse(button(root, "Restore baseline settings").isEnabled());
            RuntimeService.busy = false;
            ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
            refresh();
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertFalse(checkBox(root, "Use A740 driver experiment").isEnabled());
            assertFalse(checkBox(root, "Reduce GPU frame copies (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use direct GPU rendering (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isEnabled());
            assertFalse(checkBox(root, MESA262_LABEL).isEnabled());
            assertFalse(button(root, "Restore baseline settings").isEnabled());
            ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null); refresh();
            checkBox(root, "Use Adreno GPU rendering").performClick();
            assertEquals("software", new ClientRuntime(context).renderer());
            assertFalse(profile(root).isEnabled());
            assertFalse(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertFalse(checkBox(root, "Use A740 driver experiment").isEnabled());
            assertFalse(checkBox(root, "Reduce GPU frame copies (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use direct GPU rendering (experiment)").isEnabled());
            assertFalse(checkBox(root, "Use shared-memory frame transport (experiment)").isEnabled());
            assertFalse(checkBox(root, MESA262_LABEL).isEnabled());
            assertFalse(button(root, "Restore baseline settings").isEnabled());
            checkBox(root, "Use Adreno GPU rendering").performClick();
            assertTrue(profile(root).isEnabled());
            assertTrue(checkBox(root, "Show frame-time and GPU diagnostics").isEnabled());
            assertTrue(checkBox(root, "Use A740 driver experiment").isEnabled());
            assertTrue(checkBox(root, "Reduce GPU frame copies (experiment)").isEnabled());
            assertTrue(checkBox(root, "Use direct GPU rendering (experiment)").isEnabled());
            assertTrue(checkBox(root, "Use shared-memory frame transport (experiment)").isEnabled());
            assertTrue(checkBox(root, MESA262_LABEL).isEnabled());
            assertTrue(button(root, "Restore baseline settings").isEnabled());
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
    private static TextView performanceSummary(View root) {
        TextView summary = (TextView) find(root, TextView.class, "Selected client performance settings", true); assertNotNull(summary); return summary;
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
