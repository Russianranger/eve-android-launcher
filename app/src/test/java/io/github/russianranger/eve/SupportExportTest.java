package io.github.russianranger.eve;

import android.content.Context;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;
import static org.junit.Assert.*;

/** Current client evidence survives crowded server histories within the ZIP's bounds. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
public final class SupportExportTest {
    private Context context;
    private RuntimeManager runtime;
    private final String[] currentClientFiles = {"run/status.json", "run/processes.json", "run/client-window.json",
            "run/turnip-icd.json", "graphics-preflight.json", "client-performance.json", "client-performance.json.1",
            "logs/" + MemoryPressure.EVENTS, "logs/" + MemoryPressure.LIVE, "logs/display-performance.json",
            "logs/client-client.log", "logs/exefile_d3d11.log", "logs/exefile_dxgi.log", "logs/client-display.log"};

    @Before public void prepare() throws Exception {
        context = RuntimeEnvironment.getApplication();
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
        RuntimeService.active = false;
        RuntimeService.busy = false;
        RuntimeService.operation = "";
        RuntimeService.message = "Ready";
        RuntimeService.error = "";
        runtime = RuntimeManager.get(context);
        clearFixtures();
    }

    @After public void release() throws Exception {
        clearFixtures();
        ReflectionHelpers.setStaticField(RuntimeManager.class, "instance", null);
        ReflectionHelpers.setStaticField(ClientRuntime.class, "session", null);
    }

    private void clearFixtures() throws Exception {
        for (File directory : new File[]{runtime.serverState, runtime.clientState, runtime.clientContent}) {
            if (!Files.exists(directory.toPath())) continue;
            try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(directory.toPath())) {
                for (java.nio.file.Path path : (Iterable<java.nio.file.Path>) paths.sorted(Comparator.reverseOrder())::iterator)
                    Files.delete(path);
            }
        }
        Files.deleteIfExists(new File(runtime.home, "operations.log").toPath());
    }

    private static void put(File root, String relative, String contents) throws Exception {
        RuntimeManager.text(new File(root, relative), contents);
    }

    private void crowdHistories() throws Exception {
        put(runtime.home, "operations.log", "current operation\n");
        for (String relative : currentClientFiles) put(runtime.clientState, relative, "{\"current\":true}\n");
        for (String name : new String[]{"supervisor.log", "server-console.log", "market-console.log", "setup.log"})
            put(runtime.serverState, "logs/" + name, "current server log\n");
        for (int index = 0; index < 160; index++) {
            put(runtime.serverState, String.format(java.util.Locale.ROOT, "logs/000-history-%03d.json", index), "{\"old\":true}\n");
            put(runtime.clientState, String.format(java.util.Locale.ROOT, "old/a/history-%03d.json", index), "{\"old\":true}\n");
        }
    }

    @Test public void crowdedServerHistoryCannotDisplaceCurrentClientEvidenceAndSelectionIsBounded() throws Exception {
        crowdHistories();
        LinkedHashMap<String, File> files = SupportExport.files(context);
        for (String relative : currentClientFiles)
            assertEquals("Missing current client evidence: " + relative,
                    new File(runtime.clientState, relative), files.get("client/" + relative));
        for (String name : new String[]{"supervisor.log", "server-console.log", "market-console.log", "setup.log"})
            assertTrue(files.containsKey("server/logs/" + name));
        assertEquals(SupportExport.FILE_LIMIT, files.size());
        assertEquals(SupportExport.SERVER_LOG_LIMIT,
                files.keySet().stream().filter(name -> name.startsWith("server/logs/")).count());
        assertTrue(files.keySet().stream().anyMatch(name -> name.startsWith("client/old/a/")));
        assertEquals(new ArrayList<>(files.keySet()), new ArrayList<>(SupportExport.files(context).keySet()));
    }

    @Test public void explicitPrioritiesStillRejectLinkedFilesDirectoriesDeepHistoryAndPrivateAssets() throws Exception {
        File outside = Files.createTempDirectory("eve-support-private-").toFile();
        try {
            put(outside, "status.json", "{\"secret\":true}");
            put(outside, "secret.json", "{\"secret\":true}");
            put(runtime.clientState, "logs/normal.log", "safe\n");
            put(runtime.clientState, "a/b/allowed.json", "{}");
            put(runtime.clientState, "a/b/c/too-deep.json", "{}");
            put(runtime.clientState, "private.pem", "private certificate material");
            put(runtime.clientState, "client-assets.zip", "client asset bytes");
            put(runtime.clientContent, "assets.json", "{\"asset\":true}");
            put(runtime.serverState, "gameStore/tables/world.json", "{\"world\":true}");
            Files.createSymbolicLink(new File(runtime.clientState, "run").toPath(), outside.toPath());
            Files.createSymbolicLink(new File(runtime.clientState, "logs/client-client.log").toPath(),
                    new File(outside, "secret.json").toPath());
            Files.createSymbolicLink(new File(runtime.clientState, "logs/linked").toPath(), outside.toPath());
            Map<String, File> files = SupportExport.files(context);
            assertTrue(files.containsKey("client/logs/normal.log"));
            assertTrue(files.containsKey("client/a/b/allowed.json"));
            for (String excluded : new String[]{"client/run/status.json", "client/logs/client-client.log",
                    "client/logs/linked/secret.json", "client/a/b/c/too-deep.json", "client/private.pem",
                    "client/client-assets.zip", "client/assets.json", "server/gameStore/tables/world.json"})
                assertFalse("Unsafe export selected: " + excluded, files.containsKey(excluded));
        } finally {
            Files.deleteIfExists(new File(outside, "status.json").toPath());
            Files.deleteIfExists(new File(outside, "secret.json").toPath());
            Files.deleteIfExists(outside.toPath());
        }
    }

    @Test public void actualZipKeepsCurrentLogsAndBoundsFileCountAndEachLogTail() throws Exception {
        crowdHistories();
        String largeLog = "old output\n" + "x\n".repeat(SupportExport.FILE_BYTE_LIMIT) + "latest display receipt\n";
        put(runtime.clientState, "logs/client-client.log", largeLog);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        SupportExport.write(context, output);
        LinkedHashMap<String, byte[]> entries = new LinkedHashMap<>();
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(output.toByteArray()))) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                assertNull("Duplicate ZIP entry", entries.put(entry.getName(), zip.readAllBytes()));
                zip.closeEntry();
            }
        }
        assertEquals(SupportExport.FILE_LIMIT + 1, entries.size()); // support.json is metadata.
        assertTrue(entries.containsKey("support.json"));
        for (String relative : currentClientFiles) assertTrue(entries.containsKey("client/" + relative));
        for (Map.Entry<String, byte[]> entry : entries.entrySet())
            if (!entry.getKey().equals("support.json"))
                assertTrue("Oversized log tail: " + entry.getKey(), entry.getValue().length <= SupportExport.FILE_BYTE_LIMIT + 64);
        String clientLog = new String(entries.get("client/logs/client-client.log"), StandardCharsets.UTF_8);
        assertTrue(clientLog.startsWith("[Earlier output omitted]\n"));
        assertTrue(clientLog.endsWith("latest display receipt\n"));
    }
}
