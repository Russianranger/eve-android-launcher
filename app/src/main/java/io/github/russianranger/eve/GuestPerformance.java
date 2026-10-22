package io.github.russianranger.eve;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.util.JsonReader;
import android.util.JsonToken;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.*;

/** Optional guest overrides. Empty JSON preserves the selected graphics settings. */
final class GuestPerformance {
    static final int LIMIT = 16 * 1024;
    // Linux exposes this flag on API 26; OsConstants only added its Java field in API 27.
    private static final int CLOSE_ON_EXEC = 0x80000;
    private static final Set<String> KEYS = new HashSet<>(Arrays.asList("schemaVersion", "wineEsync", "wineDebug",
        "lpNumThreads", "wineServerNice", "serverNice", "cpuAffinity", "fex", "displayPixels", "resolution",
        "xvncFrameRate", "networkFastConnectedSends", "networkTrapStatistics"));
    private static final Set<String> FEX_KEYS = new HashSet<>(Arrays.asList("multiblock", "x87ReducedPrecision",
        "tsoEnabled", "vectorTsoEnabled", "memcpySetTsoEnabled", "halfBarrierTsoEnabled"));

    static final class Network {
        final boolean fastConnectedSends, trapStatistics;
        Network(boolean fast, boolean statistics) { fastConnectedSends = fast; trapStatistics = statistics; }
        String policyFlag() { return fastConnectedSends ? "--eve-client-network-fast-sendto" : "--eve-client-network"; }
    }

    private static String decode(byte[] bytes) throws IOException {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException invalid) { throw new IOException("Performance JSON must be valid UTF-8", invalid); }
    }

    private static byte[] encode(String text) throws IOException {
        if (text == null) throw new IOException("Performance settings must contain one JSON object");
        if (text.length() > LIMIT) throw new IOException("Performance JSON exceeds 16 KiB");
        try {
            ByteBuffer encoded = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).encode(java.nio.CharBuffer.wrap(text));
            if (encoded.remaining() > LIMIT) throw new IOException("Performance JSON exceeds 16 KiB");
            byte[] bytes = new byte[encoded.remaining()]; encoded.get(bytes); return bytes;
        } catch (CharacterCodingException invalid) { throw new IOException("Performance JSON must be valid UTF-8", invalid); }
    }

    static String read(File file) throws IOException {
        if (Files.isSymbolicLink(file.toPath()) || Files.isSymbolicLink(file.getParentFile().toPath()))
            throw new IOException("Linked performance settings are not supported");
        final FileDescriptor descriptor;
        try {
            descriptor = Os.open(file.getPath(), OsConstants.O_RDONLY | OsConstants.O_NONBLOCK
                | OsConstants.O_NOFOLLOW | CLOSE_ON_EXEC, 0);
        } catch (ErrnoException error) {
            if (error.errno == OsConstants.ENOENT) return "{}";
            throw new IOException("Cannot read performance settings", error);
        }
        try (ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            if (!OsConstants.S_ISREG(Os.fstat(descriptor).st_mode)) throw new IOException("Performance settings must be a regular file");
            byte[] buffer = new byte[4096]; int count;
            while ((count = Os.read(descriptor, buffer, 0, buffer.length)) > 0) {
                if (output.size() + count > LIMIT) throw new IOException("Performance JSON exceeds 16 KiB");
                output.write(buffer, 0, count);
            }
            return decode(output.toByteArray());
        } catch (ErrnoException error) { throw new IOException("Cannot inspect performance settings", error); }
        finally {
            try { Os.close(descriptor); }
            catch (ErrnoException error) { throw new IOException("Cannot close performance settings", error); }
        }
    }

    private static Object value(JsonReader reader, int depth) throws IOException, JSONException {
        if (depth > 4) throw new IOException("Performance JSON is nested too deeply");
        switch (reader.peek()) {
            case BEGIN_OBJECT: {
                JSONObject result = new JSONObject(); Set<String> names = new HashSet<>(); reader.beginObject();
                while (reader.hasNext()) {
                    String name = reader.nextName();
                    if (!names.add(name)) throw new IOException("Duplicate performance setting: " + name);
                    result.put(name, value(reader, depth + 1));
                }
                reader.endObject(); return result;
            }
            case BEGIN_ARRAY: {
                JSONArray result = new JSONArray(); reader.beginArray();
                while (reader.hasNext()) result.put(value(reader, depth + 1));
                reader.endArray(); return result;
            }
            case STRING: return reader.nextString();
            case BOOLEAN: return reader.nextBoolean();
            case NULL: reader.nextNull(); return JSONObject.NULL;
            case NUMBER: {
                String number = reader.nextString();
                if (number.matches("-?(0|[1-9][0-9]*)")) {
                    try { return Long.parseLong(number); }
                    catch (NumberFormatException invalid) { throw new IOException("Performance integer is out of range", invalid); }
                }
                double parsed = Double.parseDouble(number);
                if (Double.isInfinite(parsed) || Double.isNaN(parsed)) throw new IOException("Performance number is out of range");
                return parsed;
            }
            default: throw new IOException("Expected a JSON value");
        }
    }

    private static JSONObject object(String text) throws IOException {
        encode(text);
        try (JsonReader reader = new JsonReader(new StringReader(text))) {
            reader.setLenient(false);
            Object result = value(reader, 0);
            if (!(result instanceof JSONObject) || reader.peek() != JsonToken.END_DOCUMENT)
                throw new IOException("Performance settings must contain one JSON object");
            return (JSONObject) result;
        } catch (JSONException | NumberFormatException invalid) { throw new IOException("Invalid performance JSON", invalid); }
    }

    private static boolean integer(Object value, long low, long high) {
        return (value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= low
            && ((Number) value).longValue() <= high;
    }
    private static boolean choice(Object value, String... choices) {
        return value instanceof String && Arrays.asList(choices).contains(value);
    }

    static JSONObject validate(String text) throws IOException {
        JSONObject profile = object(text);
        Iterator<String> keys = profile.keys();
        while (keys.hasNext()) {
            String key = keys.next(); Object item = profile.opt(key); boolean valid;
            if (!KEYS.contains(key)) throw new IOException("Unknown performance setting: " + key);
            switch (key) {
                case "schemaVersion": valid = integer(item, 1, 1); break;
                case "wineEsync": case "networkFastConnectedSends": case "networkTrapStatistics": valid = item instanceof Boolean; break;
                case "wineDebug": valid = choice(item, "-all", "-all,err+all"); break;
                case "lpNumThreads": valid = integer(item, 1, 16) || choice(item, "auto"); break;
                case "wineServerNice": case "serverNice": valid = integer(item, 0, 19); break;
                case "xvncFrameRate": valid = integer(item, 1, 120); break;
                case "resolution": valid = choice(item, "1280x720", "960x540"); break;
                case "displayPixels": valid = choice(item, "legacy", "direct"); break;
                case "cpuAffinity": {
                    valid = item instanceof JSONArray && ((JSONArray) item).length() <= 64;
                    Set<Long> cpus = new HashSet<>();
                    if (valid) for (int index = 0; index < ((JSONArray) item).length(); index++) {
                        Object cpu = ((JSONArray) item).opt(index);
                        if (!integer(cpu, 0, 1023) || !cpus.add(((Number) cpu).longValue())) { valid = false; break; }
                    }
                    break;
                }
                case "fex": {
                    valid = item instanceof JSONObject;
                    if (valid) {
                        Iterator<String> names = ((JSONObject) item).keys();
                        while (names.hasNext()) {
                            String name = names.next();
                            if (!FEX_KEYS.contains(name) || !(((JSONObject) item).opt(name) instanceof Boolean)) { valid = false; break; }
                        }
                    }
                    break;
                }
                default: valid = false;
            }
            if (!valid) throw new IOException("Invalid performance setting: " + key);
        }
        return profile;
    }

    static Network network(File file) {
        try {
            JSONObject profile = object(read(file)); Object schema = profile.opt("schemaVersion");
            if (profile.has("schemaVersion") && !integer(schema, 1, 1)) return new Network(false, false);
            return new Network(Boolean.TRUE.equals(profile.opt("networkFastConnectedSends")),
                Boolean.TRUE.equals(profile.opt("networkTrapStatistics")));
        } catch (IOException invalid) { return new Network(false, false); }
    }

    static boolean canEdit(Context context) {
        return !RuntimeService.busy && !RuntimeManager.get(context).serverAlive() && !new ClientRuntime(context).alive();
    }

    private static void write(File target, String text) throws IOException {
        byte[] bytes = encode(text); File parent = target.getParentFile();
        if (Files.isSymbolicLink(parent.toPath()) || Files.isSymbolicLink(target.toPath()))
            throw new IOException("Linked performance settings are not supported");
        RuntimeManager.mkdir(parent);
        File temporary = File.createTempFile("performance-", ".tmp", parent);
        try {
            try (FileOutputStream output = new FileOutputStream(temporary)) { output.write(bytes); output.getFD().sync(); }
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { temporary.delete(); }
    }

    static void save(Context context, String text) throws IOException {
        JSONObject profile = validate(text);
        if (!canEdit(context)) throw new IOException("Stop both the server and client before editing guest performance settings");
        try { write(new File(RuntimeManager.get(context).clientState, "performance.json"), profile.toString(2) + "\n"); }
        catch (JSONException invalid) { throw new IOException("Invalid performance JSON", invalid); }
    }

    static void snapshotServer(RuntimeManager runtime) throws IOException {
        String selected;
        try { selected = read(new File(runtime.clientState, "performance.json")); object(selected); }
        catch (IOException invalid) { selected = "{}"; }
        write(new File(runtime.serverState, "performance.json"), selected);
    }

    static JSONObject diagnostic(File file) {
        JSONObject result = new JSONObject();
        try {
            result.put("present", file.exists()); validate(read(file)); result.put("valid", true);
        } catch (IOException | JSONException invalid) {
            try { result.put("valid", false).put("warning", invalid.getMessage()); } catch (JSONException ignored) { }
        }
        return result;
    }
}
