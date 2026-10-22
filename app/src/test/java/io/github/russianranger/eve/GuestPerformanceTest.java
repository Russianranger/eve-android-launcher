package io.github.russianranger.eve;

import static org.junit.Assert.*;

import android.app.AlertDialog;
import android.content.Context;
import android.os.Looper;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.system.StructStat;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.LinkOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Collections;
import java.util.Comparator;
import java.util.IdentityHashMap;
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
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import org.robolectric.annotation.Resetter;
import org.robolectric.shadows.ShadowAlertDialog;
import org.robolectric.shadows.ShadowLinux;
import org.robolectric.util.ReflectionHelpers;

/** Validates optional guest settings without changing the accepted graphics selections. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35}, shadows = GuestPerformanceTest.ProfileLinux.class)
public final class GuestPerformanceTest {
    private Context context;
    private RuntimeManager runtime;

    @Before public void prepare() throws Exception {
        context = RuntimeEnvironment.getApplication();
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        RuntimeService.busy = false;
        RuntimeService.active = false;
        RuntimeService.operation = "";
        RuntimeService.message = "Ready";
        RuntimeService.error = "";
        runtime = RuntimeManager.get(context);
        clear(runtime.serverState);
        clear(runtime.clientState);
        context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit().clear().commit();
    }

    @After public void release() throws Exception {
        ProfileLinux.assertAllDescriptorsClosed();
        RuntimeService.busy = false;
        RuntimeService.active = false;
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        ReflectionHelpers.setField(runtime, "server", null);
        clear(runtime.serverState);
        clear(runtime.clientState);
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
    }

    private static void clear(File directory) throws Exception {
        if (!Files.exists(directory.toPath())) return;
        try (java.util.stream.Stream<Path> paths = Files.walk(directory.toPath())) {
            for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator)
                Files.delete(path);
        }
    }

    private File profile() { return new File(runtime.clientState, "performance.json"); }

    private interface Checked { void run() throws Exception; }
    private static void rejects(Checked action) throws Exception {
        try { action.run(); }
        catch (IOException expected) { return; }
        fail("Invalid or unsafe profile operation was accepted");
    }

    @Test public void optionalSettingsAcceptOnlyTheDocumentedSchemaAndKeepExistingGraphicsChoices() throws Exception {
        assertEquals(0, GuestPerformance.validate("{}").length());
        JSONObject complete = GuestPerformance.validate("{\"schemaVersion\":1,\"wineEsync\":true,"
                + "\"wineDebug\":\"-all\",\"lpNumThreads\":\"auto\",\"wineServerNice\":19,\"serverNice\":0,"
                + "\"cpuAffinity\":[0,1023],\"fex\":{\"multiblock\":true,\"x87ReducedPrecision\":false,"
                + "\"tsoEnabled\":true,\"vectorTsoEnabled\":false,\"memcpySetTsoEnabled\":true,"
                + "\"halfBarrierTsoEnabled\":false},\"displayPixels\":\"direct\","
                + "\"networkFastConnectedSends\":true,\"networkTrapStatistics\":false,"
                + "\"resolution\":\"960x540\",\"xvncFrameRate\":120}");
        assertEquals(120, complete.getInt("xvncFrameRate"));
        assertEquals("auto", complete.getString("lpNumThreads"));
        for (int threads : new int[]{1, 16})
            assertEquals(threads, GuestPerformance.validate("{\"lpNumThreads\":" + threads + "}").getInt("lpNumThreads"));
        GuestPerformance.validate("{\"wineDebug\":\"-all,err+all\",\"cpuAffinity\":[],\"displayPixels\":\"legacy\","
                + "\"resolution\":\"1280x720\",\"xvncFrameRate\":1}");
        for (String invalid : new String[]{"{\"renderer\":\"dxvk-turnip\"}", "{\"schemaVersion\":2}",
                "{\"schemaVersion\":true}", "{\"wineEsync\":1}", "{\"wineDebug\":\"+all\"}",
                "{\"lpNumThreads\":0}", "{\"lpNumThreads\":17}", "{\"lpNumThreads\":1.5}",
                "{\"lpNumThreads\":\"4\"}", "{\"wineServerNice\":-1}", "{\"serverNice\":20}",
                "{\"cpuAffinity\":[0,0]}", "{\"cpuAffinity\":[-1]}", "{\"cpuAffinity\":[1024]}",
                "{\"cpuAffinity\":[true]}", "{\"fex\":{\"RootFS\":true}}", "{\"fex\":{\"multiblock\":1}}",
                "{\"displayPixels\":\"rgba16\"}", "{\"networkFastConnectedSends\":\"true\"}",
                "{\"networkTrapStatistics\":null}", "{\"resolution\":\"1920x1080\"}", "{\"xvncFrameRate\":0}",
                "{\"xvncFrameRate\":121}", "{\"unknown\":true}"})
            rejects(() -> GuestPerformance.validate(invalid));
        StringBuilder many = new StringBuilder("{\"cpuAffinity\":[");
        for (int number = 0; number < 65; number++) { if (number != 0) many.append(','); many.append(number); }
        rejects(() -> GuestPerformance.validate(many.append("]}").toString()));
    }

    @Test public void editorRejectsNonstandardJsonTrailingTextAndOversizedUtf8() throws Exception {
        for (String invalid : new String[]{"[]", "null", "", "{'wineEsync':true}", "{wineEsync:true}",
                "{\"wineEsync\":true,}", "{\"wineEsync\":true}//comment", "{} trailing", "/*comment*/{}",
                "{\"wineEsync\":true,\"wineEsync\":false}"})
            rejects(() -> GuestPerformance.validate(invalid));
        GuestPerformance.validate("{}" + " ".repeat(16382));
        rejects(() -> GuestPerformance.validate("{}" + " ".repeat(16383)));
    }

    @Test public void readsAreBoundedStrictUtf8RegularFilesAndNeverFollowLeafLinks() throws Exception {
        assertEquals("{}", GuestPerformance.read(profile()));
        ProfileLinux.assertAllDescriptorsClosed();
        RuntimeManager.text(profile(), "{\"wineEsync\":false}");
        assertEquals("{\"wineEsync\":false}", GuestPerformance.read(profile()));
        ProfileLinux.assertAllDescriptorsClosed();
        Files.write(profile().toPath(), new byte[]{(byte) 0xc3, (byte) 0x28});
        rejects(() -> GuestPerformance.read(profile()));
        ProfileLinux.assertAllDescriptorsClosed();
        Files.write(profile().toPath(), "{}".getBytes(StandardCharsets.UTF_8));
        File linked = new File(runtime.clientState, "linked.json");
        Files.createSymbolicLink(linked.toPath(), profile().toPath());
        rejects(() -> GuestPerformance.read(linked));
        rejects(() -> GuestPerformance.read(runtime.clientState));
        Files.write(profile().toPath(), ("{}" + " ".repeat(16383)).getBytes(StandardCharsets.UTF_8));
        rejects(() -> GuestPerformance.read(profile()));
        ProfileLinux.assertAllDescriptorsClosed();
    }

    @Test public void networkSelectionIsStrictDefaultOffAndUsesOnlyFixedPolicyFlags() throws Exception {
        GuestPerformance.Network defaults = GuestPerformance.network(profile());
        assertFalse(defaults.fastConnectedSends); assertFalse(defaults.trapStatistics);
        assertEquals("--eve-client-network", defaults.policyFlag());
        RuntimeManager.text(profile(), "{\"networkFastConnectedSends\":true,\"networkTrapStatistics\":true}");
        GuestPerformance.Network fast = GuestPerformance.network(profile());
        assertTrue(fast.fastConnectedSends); assertTrue(fast.trapStatistics);
        assertEquals("--eve-client-network-fast-sendto", fast.policyFlag());
        for (String invalid : new String[]{"{\"schemaVersion\":2,\"networkFastConnectedSends\":true}",
                "{\"networkFastConnectedSends\":\"true\",\"networkTrapStatistics\":1}", "[]", "{} trailing"}) {
            RuntimeManager.text(profile(), invalid);
            GuestPerformance.Network safe = GuestPerformance.network(profile());
            assertFalse(safe.fastConnectedSends); assertFalse(safe.trapStatistics);
            assertEquals("--eve-client-network", safe.policyFlag());
        }
    }

    @Test public void invalidOrBusySavesPreservePriorBytesAndAcceptedGraphicsSelections() throws Exception {
        context.getSharedPreferences("client-graphics", Context.MODE_PRIVATE).edit()
                .putBoolean("mesa262-driver", true).putBoolean("linear-presentation", true).commit();
        GuestPerformance.save(context, "{\"xvncFrameRate\":60}");
        String previous = GuestPerformance.read(profile());
        rejects(() -> GuestPerformance.save(context, "{\"xvncFrameRate\":-1}"));
        assertEquals(previous, GuestPerformance.read(profile()));
        RuntimeService.busy = true;
        assertFalse(GuestPerformance.canEdit(context));
        rejects(() -> GuestPerformance.save(context, "{}"));
        assertEquals(previous, GuestPerformance.read(profile()));
        RuntimeService.busy = false;
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", new LiveProcess());
        assertFalse(GuestPerformance.canEdit(context));
        rejects(() -> GuestPerformance.save(context, "{}"));
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        ReflectionHelpers.setField(runtime, "server", new LiveProcess());
        assertFalse(GuestPerformance.canEdit(context));
        rejects(() -> GuestPerformance.save(context, "{}"));
        ReflectionHelpers.setField(runtime, "server", null);
        assertTrue(GuestPerformance.canEdit(context));
        assertEquals(previous, GuestPerformance.read(profile()));
        assertTrue(new ClientRuntime(context).mesa262Driver());
        assertTrue(new ClientRuntime(context).linearPresentation());
        assertFalse(new File(runtime.clientState, "performance.json.new").exists());
    }

    @Test public void serverSnapshotIsIndependentBoundedAndExportedWithTheSourceProfile() throws Exception {
        GuestPerformance.save(context, "{\"serverNice\":7,\"networkTrapStatistics\":true}");
        GuestPerformance.snapshotServer(runtime);
        File snapshot = new File(runtime.serverState, "performance.json");
        String serverCopy = GuestPerformance.read(snapshot);
        assertEquals(7, new JSONObject(serverCopy).getInt("serverNice"));
        GuestPerformance.save(context, "{\"serverNice\":2}");
        assertEquals(serverCopy, GuestPerformance.read(snapshot));
        Map<String, File> files = SupportExport.files(context);
        assertEquals(profile(), files.get("client/performance.json"));
        assertEquals(snapshot, files.get("server/performance.json"));
        RuntimeManager.text(profile(), "not json");
        GuestPerformance.snapshotServer(runtime);
        assertEquals(0, new JSONObject(GuestPerformance.read(snapshot)).length());
    }

    @Test public void advancedEditorValidatesWithoutClosingAndDefaultsNeedExplicitSave() throws Exception {
        GuestPerformance.save(context, "{\"serverNice\":7}");
        ActivityController<MainActivity> owner = Robolectric.buildActivity(MainActivity.class).create().start().resume().visible();
        try {
            View root = owner.get().findViewById(android.R.id.content);
            button(root, "Client").performClick(); idle();
            View advanced = find(root, Button.class, "Advanced guest performance settings", true);
            assertNotNull(advanced); assertTrue(advanced.isEnabled()); advanced.performClick(); idle();
            AlertDialog dialog = ShadowAlertDialog.getLatestAlertDialog();
            assertNotNull(dialog); assertTrue(dialog.isShowing());
            EditText input = (EditText) find(dialog.getWindow().getDecorView(), EditText.class, "Guest performance JSON", true);
            assertNotNull(input);
            assertEquals(7, new JSONObject(input.getText().toString()).getInt("serverNice"));
            input.setText("{\"serverNice\":-1}");
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(); idle();
            assertTrue(dialog.isShowing()); assertNotNull(input.getError());
            assertEquals(7, new JSONObject(GuestPerformance.read(profile())).getInt("serverNice"));
            input.setText("{\"serverNice\":8}"); RuntimeService.busy = true;
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(); idle();
            assertTrue(dialog.isShowing()); assertNotNull(input.getError());
            assertEquals(7, new JSONObject(GuestPerformance.read(profile())).getInt("serverNice"));
            RuntimeService.busy = false;
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).performClick(); idle();
            assertTrue(dialog.isShowing()); assertEquals(0, new JSONObject(input.getText().toString()).length());
            assertEquals(7, new JSONObject(GuestPerformance.read(profile())).getInt("serverNice"));
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(); idle();
            assertFalse(dialog.isShowing()); assertEquals(0, new JSONObject(GuestPerformance.read(profile())).length());
        } finally { owner.pause().stop().destroy(); }
    }

    @Test public void supportMetadataRecordsProfileValidationAndKeepsItsServerSnapshotSeparate() throws Exception {
        GuestPerformance.save(context, "{\"serverNice\":5}");
        GuestPerformance.snapshotServer(runtime);
        RuntimeManager.text(profile(), "{\"serverNice\":99}");
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        SupportExport.write(context, output);
        JSONObject metadata = null;
        try (java.util.zip.ZipInputStream zip = new java.util.zip.ZipInputStream(new ByteArrayInputStream(output.toByteArray()))) {
            for (java.util.zip.ZipEntry entry; (entry = zip.getNextEntry()) != null;) {
                if (entry.getName().equals("support.json"))
                    metadata = new JSONObject(new String(zip.readAllBytes(), StandardCharsets.UTF_8));
            }
        }
        assertNotNull(metadata);
        assertFalse(metadata.getJSONObject("guestPerformanceProfile").getBoolean("valid"));
        assertTrue(metadata.getJSONObject("guestPerformanceProfile").getString("warning").contains("serverNice"));
        assertTrue(metadata.getJSONObject("serverPerformanceSnapshot").getBoolean("valid"));
        assertEquals(5, new JSONObject(GuestPerformance.read(new File(runtime.serverState, "performance.json"))).getInt("serverNice"));
    }

    private static void idle() { Shadows.shadowOf(Looper.getMainLooper()).idle(); }
    private static Button button(View root, String text) {
        Button button = (Button) find(root, Button.class, text, false);
        assertNotNull("Missing button: " + text, button); return button;
    }
    private static View find(View root, Class<?> type, String text, boolean description) {
        String actual = description ? String.valueOf(root.getContentDescription())
                : root instanceof TextView ? ((TextView) root).getText().toString() : "";
        if (type.isInstance(root) && text.equals(actual)) return root;
        if (root instanceof ViewGroup) for (int index = 0; index < ((ViewGroup) root).getChildCount(); index++) {
            View found = find(((ViewGroup) root).getChildAt(index), type, text, description);
            if (found != null) return found;
        }
        return null;
    }
    private static final class LiveProcess extends Process {
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { return 0; }
        @Override public int exitValue() { throw new IllegalThreadStateException("Runtime alive"); }
        @Override public void destroy() { }
        @Override public boolean isAlive() { return true; }
    }

    /** Robolectric 4.14's fstat(fd) loses the descriptor mode; retain real file metadata for these fixtures. */
    @Implements(className = "libcore.io.Linux", isInAndroidSdk = false, minSdk = 26)
    public static final class ProfileLinux extends ShadowLinux {
        private static final Map<FileDescriptor, OpenFile> FILES = Collections.synchronizedMap(new IdentityHashMap<>());
        private static int opened;
        private static int closed;

        private static final class OpenFile {
            final RandomAccessFile stream;
            final BasicFileAttributes attributes;
            OpenFile(RandomAccessFile stream, BasicFileAttributes attributes) {
                this.stream = stream; this.attributes = attributes;
            }
        }

        @Implementation @Override protected FileDescriptor open(String path, int flags, int mode) throws ErrnoException {
            if ((flags & OsConstants.O_NOFOLLOW) == 0 || (flags & (OsConstants.O_WRONLY | OsConstants.O_RDWR)) != 0)
                return super.open(path, flags, mode);
            Path file = new File(path).toPath();
            try {
                if ((flags & OsConstants.O_NOFOLLOW) != 0 && Files.isSymbolicLink(file))
                    throw new ErrnoException("open", OsConstants.ELOOP);
                BasicFileAttributes attributes = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                if (!attributes.isRegularFile()) throw new ErrnoException("open", OsConstants.EISDIR);
                RandomAccessFile input = new RandomAccessFile(path, "r");
                FileDescriptor descriptor = input.getFD();
                FILES.put(descriptor, new OpenFile(input, attributes));
                opened++;
                return descriptor;
            } catch (java.nio.file.NoSuchFileException missing) {
                throw new ErrnoException("open", OsConstants.ENOENT);
            } catch (IOException invalid) {
                throw new ErrnoException("open", OsConstants.EIO);
            }
        }

        @Implementation @Override protected StructStat fstat(FileDescriptor descriptor) throws ErrnoException {
            OpenFile file = FILES.get(descriptor);
            if (file == null) return super.fstat(descriptor);
            return new StructStat(0, 0, OsConstants.S_IFREG, 1, 0, 0, 0,
                    file.attributes.size(), 0, 0, 0, 0, 0);
        }

        @Implementation protected int read(FileDescriptor descriptor, byte[] bytes, int offset, int count) throws ErrnoException {
            OpenFile file = FILES.get(descriptor);
            try {
                int result = file == null ? new FileInputStream(descriptor).read(bytes, offset, count)
                        : file.stream.read(bytes, offset, count);
                return result < 0 ? 0 : result;
            } catch (IOException failure) {
                throw new ErrnoException("read", OsConstants.EIO);
            }
        }

        @Implementation protected void close(FileDescriptor descriptor) throws ErrnoException {
            OpenFile file = FILES.get(descriptor);
            try {
                if (file == null) new FileInputStream(descriptor).close();
                else {
                    file.stream.close();
                    assertFalse("Os.close must close the owned descriptor", descriptor.valid());
                    FILES.remove(descriptor);
                    closed++;
                }
            } catch (IOException failure) {
                throw new ErrnoException("close", OsConstants.EIO);
            }
        }

        static void assertAllDescriptorsClosed() {
            assertEquals("No profile descriptor may survive a completed read", 0, FILES.size());
            assertEquals("Every opened profile descriptor must be closed", opened, closed);
        }

        @Resetter public static void closeFixtures() {
            synchronized (FILES) {
                for (OpenFile file : FILES.values()) try { file.stream.close(); } catch (IOException ignored) { }
                FILES.clear();
                opened = 0;
                closed = 0;
            }
        }
    }
}
