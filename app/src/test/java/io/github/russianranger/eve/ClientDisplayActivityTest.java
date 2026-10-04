package io.github.russianranger.eve;

import android.view.View;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import java.util.Map;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.util.ReflectionHelpers;
import static org.junit.Assert.*;

/** Uses Android's actual PhoneWindow and packaged vector resources before any client connection. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public final class ClientDisplayActivityTest {
    @Test public void createsDisplayBeforeWindowHasDecor() {
        ActivityController<ClientDisplayActivity> owned = Robolectric.buildActivity(ClientDisplayActivity.class);
        ClientDisplayActivity activity = owned.get();
        assertNull("A new PhoneWindow has no decor before onCreate", activity.getWindow().peekDecorView());
        owned.create();
        assertNotNull(activity.getWindow().peekDecorView());
        ImageButton gear = ReflectionHelpers.getField(activity, "gear");
        assertNotNull("The packaged space gear inflates on Android", gear.getDrawable());
        RfbView display = ReflectionHelpers.getField(activity, "screen");
        assertEquals(FrameLayout.LayoutParams.MATCH_PARENT, display.getLayoutParams().width);
        assertEquals(FrameLayout.LayoutParams.MATCH_PARENT, display.getLayoutParams().height);
        owned.destroy();
    }

    @Test public void gearMenuReleasesHeldInputsAndClosesCleanly() {
        ActivityController<ClientDisplayActivity> owned = Robolectric.buildActivity(ClientDisplayActivity.class).create();
        ClientDisplayActivity activity = owned.get();
        ImageButton gear = ReflectionHelpers.getField(activity, "gear");
        FrameLayout menu = ReflectionHelpers.getField(activity, "menuLayer");
        DisplayInput inputs = ReflectionHelpers.getField(activity, "gameInput");
        inputs.key("host-key", 'w', true);
        inputs.mouse("host-mouse", 1, true);
        gear.performClick();
        assertEquals(View.VISIBLE, menu.getVisibility());
        assertEquals("Close flight controls", gear.getContentDescription());
        assertTrue(((Map<?, ?>) ReflectionHelpers.getField(inputs, "keys")).isEmpty());
        assertTrue(((Map<?, ?>) ReflectionHelpers.getField(inputs, "buttons")).isEmpty());
        ControllerManager controller = ReflectionHelpers.getField(activity, "controller");
        assertFalse(controller.active());
        gear.performClick();
        assertEquals(View.GONE, menu.getVisibility());
        assertEquals("Open flight controls", gear.getContentDescription());
        owned.destroy();
    }

    @Test public void pauseAndRecreationRetainSavedMappings() throws Exception {
        ActivityController<ClientDisplayActivity> first = Robolectric.buildActivity(ClientDisplayActivity.class).create();
        ClientDisplayActivity activity = first.get();
        ControllerManager controller = ReflectionHelpers.getField(activity, "controller");
        JSONObject profile = controller.state();
        profile.getJSONArray("layers").getJSONObject(1).put("name", "Navigation");
        controller.configure(profile, true);
        DisplayInput inputs = ReflectionHelpers.getField(activity, "gameInput");
        inputs.key("host-key", 'w', true);
        inputs.mouse("host-mouse", 1, true);
        // No running Xvnc or EVE client is needed; the first loopback attempt is immediately cancelled.
        first.start().resume().pause().stop();
        assertFalse(controller.active());
        assertTrue(((Map<?, ?>) ReflectionHelpers.getField(inputs, "keys")).isEmpty());
        assertTrue(((Map<?, ?>) ReflectionHelpers.getField(inputs, "buttons")).isEmpty());
        first.destroy();
        ActivityController<ClientDisplayActivity> replacement = Robolectric.buildActivity(ClientDisplayActivity.class).create();
        ControllerManager restored = ReflectionHelpers.getField(replacement.get(), "controller");
        assertEquals("Navigation", restored.state().getJSONArray("layers").getJSONObject(1).getString("name"));
        replacement.get().onBackPressed();
        replacement.get().onBackPressed();
        replacement.destroy();
    }

    private static void assertBindingsUnchanged(JSONObject before, JSONObject after) throws Exception {
        assertEquals(before.getJSONArray("layers").length(), after.getJSONArray("layers").length());
        for (int layer = 0; layer < before.getJSONArray("layers").length(); layer++) {
            JSONObject oldMap = before.getJSONArray("layers").getJSONObject(layer).getJSONObject("bindings");
            JSONObject newMap = after.getJSONArray("layers").getJSONObject(layer).getJSONObject("bindings");
            for (String source : ControllerInput.SOURCES) assertEquals(oldMap.getString(source), newMap.getString(source));
        }
    }

    @Test public void explicitLegacyLayerNameSurvivesSaveAndReload() throws Exception {
        File work = new File(RuntimeEnvironment.getApplication().getFilesDir(), "explicit-layer-test");
        ControllerManager controller = new ControllerManager(RuntimeEnvironment.getApplication(), work, event -> { });
        try {
            JSONObject profile = controller.state();
            profile.getJSONArray("layers").getJSONObject(1).put("name", "Hotbar 2");
            profile.getJSONArray("layers").getJSONObject(1).getJSONObject("bindings").put("A", "F7");
            controller.configure(profile, true);
            JSONObject saved = new JSONObject(new String(Files.readAllBytes(new File(work, "controller.json").toPath()), StandardCharsets.UTF_8));
            assertEquals(1, saved.getInt("layer_names_version"));
            controller.reload();
            JSONObject restored = controller.state();
            assertEquals("Hotbar 2", restored.getJSONArray("layers").getJSONObject(1).getString("name"));
            assertBindingsUnchanged(profile, restored);
        } finally { controller.close(); }
    }

    @Test public void unmarkedOldDefaultNamesMigrateWithoutChangingBindings() throws Exception {
        File work = new File(RuntimeEnvironment.getApplication().getFilesDir(), "old-layer-test");
        ControllerManager controller = new ControllerManager(RuntimeEnvironment.getApplication(), work, event -> { });
        try {
            JSONObject old = controller.state();
            old.remove("layer_names_version");
            String[] names = {"Main", "Hotbar 2", "Spells", "Inventory"};
            for (int layer = 0; layer < names.length; layer++) old.getJSONArray("layers").getJSONObject(layer).put("name", names[layer]);
            old.getJSONArray("layers").getJSONObject(2).getJSONObject("bindings").put("A", "F7");
            assertTrue(work.mkdirs() || work.isDirectory());
            Files.write(new File(work, "controller.json").toPath(), old.toString().getBytes(StandardCharsets.UTF_8));
            controller.reload();
            JSONObject migrated = controller.state();
            String[] expected = {"Main", "Alt 1", "Alt 2", "Alt 3"};
            for (int layer = 0; layer < expected.length; layer++) assertEquals(expected[layer], migrated.getJSONArray("layers").getJSONObject(layer).getString("name"));
            assertBindingsUnchanged(old, migrated);
        } finally { controller.close(); }
    }
}
