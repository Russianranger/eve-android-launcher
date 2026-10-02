package io.github.russianranger.eve;

import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;
import java.util.zip.GZIPOutputStream;

/** Crafted GNU archives exercise the exact production Java extraction code. */
public final class ArchiveHostTest {
    interface Case { void run(Path temporary, Path root) throws Exception; }
    interface Operation { void run() throws Exception; }
    static int passed;

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    static void rejected(Class<? extends Exception> expected, Operation operation) throws Exception {
        try {
            operation.run();
        } catch (Exception failure) {
            if (expected.isInstance(failure)) return;
            throw new AssertionError("Expected " + expected.getName() + ", got " + failure, failure);
        }
        throw new AssertionError("Unsafe or incomplete archive was accepted");
    }

    static void run(String name, Case test) throws Exception {
        Path temporary = Files.createTempDirectory("eve-archive-test-");
        Path root = Files.createDirectory(temporary.resolve("root"));
        try {
            test.run(temporary, root);
            System.out.println("PASS " + name);
            passed++;
        } finally {
            Thread.interrupted();
            try (var paths = Files.walk(temporary)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                    Files.deleteIfExists(path);
                }
            }
        }
    }

    static void put(byte[] header, int start, int length, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        check(bytes.length <= length, "Test header field too long");
        System.arraycopy(bytes, 0, header, start, bytes.length);
    }

    static byte[] header(String name, char type, String link, long size) {
        byte[] result = new byte[512];
        put(result, 0, 100, name);
        put(result, 100, 8, "0000755\0");
        put(result, 108, 8, "0000000\0");
        put(result, 116, 8, "0000000\0");
        String octalSize = String.format("%011o", size);
        put(result, 124, 12, octalSize.length() < 12 ? octalSize + "\0" : octalSize);
        put(result, 136, 12, "00000000000\0");
        Arrays.fill(result, 148, 156, (byte) ' ');
        result[156] = (byte) type;
        put(result, 157, 100, link);
        put(result, 257, 6, "ustar ");
        put(result, 263, 2, " \0");
        int sum = 0;
        for (byte value : result) sum += value & 255;
        put(result, 148, 8, String.format("%06o", sum) + "\0 ");
        return result;
    }

    static final class Archive {
        final ByteArrayOutputStream tar = new ByteArrayOutputStream();
        Archive member(String name, char type, String link, byte[] data) throws IOException {
            tar.write(header(name, type, link, data.length));
            tar.write(data);
            tar.write(new byte[(512 - data.length % 512) % 512]);
            return this;
        }
        Archive file(String name, String value) throws IOException {
            return member(name, '0', "", value.getBytes(StandardCharsets.UTF_8));
        }
        Archive link(String name, char type, String target) throws IOException {
            return member(name, type, target, new byte[0]);
        }
        Path save(Path temporary, boolean terminate) throws IOException {
            if (terminate) tar.write(new byte[1024]);
            return gzip(temporary, tar.toByteArray());
        }
    }

    static Path gzip(Path temporary, byte[] raw) throws IOException {
        Path path = temporary.resolve("runtime.tar.gz");
        try (GZIPOutputStream output = new GZIPOutputStream(Files.newOutputStream(path))) {
            output.write(raw);
        }
        return path;
    }

    static void extract(Path archive, Path root) throws Exception {
        TarExtractor.extract(archive.toFile(), root.toFile(), count -> {});
    }

    public static void main(String[] args) throws Exception {
        run("regular files, executable mode and forward hardlink", (temporary, root) -> {
            Path archive = new Archive().link("bin/node-copy", '1', "bin/node")
                .file("bin/node", "native executable").save(temporary, true);
            extract(archive, root);
            check(Files.readString(root.resolve("bin/node-copy")).equals("native executable"), "Hardlink lost data");
            check(Files.isSameFile(root.resolve("bin/node"), root.resolve("bin/node-copy")), "Hardlink became a copy");
            check(Files.isExecutable(root.resolve("bin/node")), "Executable permission lost");
        });

        run("GNU long names and guest absolute symlinks", (temporary, root) -> {
            String longName = "usr/share/" + "a".repeat(120) + "/table.json";
            Path archive = new Archive().member("././@LongLink", 'L', "", (longName + "\0").getBytes(StandardCharsets.UTF_8))
                .file("ignored-short-name", "table").link("bin", '2', "/usr/bin").save(temporary, true);
            extract(archive, root);
            check(Files.readString(root.resolve(longName)).equals("table"), "GNU long name was not used");
            check(Files.readSymbolicLink(root.resolve("bin")).toString().equals("/usr/bin"), "Guest absolute link changed");
        });

        for (String name : new String[]{"../escaped", "safe/../escaped", "/escaped", "safe\\escaped"}) {
            run("reject archive path " + name, (temporary, root) -> {
                Path archive = new Archive().file(name, "must not escape").save(temporary, true);
                rejected(IOException.class, () -> extract(archive, root));
                check(!Files.exists(temporary.resolve("escaped")), "Traversal wrote outside extraction root");
            });
        }

        run("reject traversal supplied through GNU long name", (temporary, root) -> {
            Path archive = new Archive().member("././@LongLink", 'L', "", "../escaped\0".getBytes(StandardCharsets.UTF_8))
                .file("innocent", "malicious").save(temporary, true);
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(temporary.resolve("escaped")), "GNU traversal wrote outside extraction root");
        });

        run("reject truncated regular file payload", (temporary, root) -> {
            Archive archive = new Archive();
            archive.tar.write(header("large-file", '0', "", 900));
            archive.tar.write(new byte[100]);
            Path path = archive.save(temporary, false);
            rejected(EOFException.class, () -> extract(path, root));
        });

        run("reject missing tar terminator", (temporary, root) -> {
            Path archive = new Archive().file("first", "valid data but incomplete archive").save(temporary, false);
            rejected(EOFException.class, () -> extract(archive, root));
        });

        run("reject corrupt tar header checksum", (temporary, root) -> {
            byte[] broken = header("innocent", '0', "", 0);
            broken[0] = 'x';
            Path archive = gzip(temporary, broken);
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(root.resolve("xnnocent")), "Corrupt header created a file");
        });

        run("reject duplicate files without replacing first bytes", (temporary, root) -> {
            Path archive = new Archive().file("file", "first").file("file", "second").save(temporary, true);
            rejected(IOException.class, () -> extract(archive, root));
            check(Files.readString(root.resolve("file")).equals("first"), "Duplicate replaced extracted data");
        });

        run("symlink members cannot redirect later regular file writes", (temporary, root) -> {
            Path outside = Files.createDirectory(temporary.resolve("outside"));
            Path archive = new Archive().link("redirect", '2', outside.toString())
                .file("redirect/escaped", "must remain inside staging").save(temporary, true);
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(outside.resolve("escaped")), "Symlink redirected archive write");
            check(Files.readString(root.resolve("redirect/escaped")).equals("must remain inside staging"), "Regular data did not stay in staging");
        });

        run("reject nested symlink creation through an outside symlink", (temporary, root) -> {
            Path outside = Files.createDirectory(temporary.resolve("outside"));
            Path archive = new Archive().link("redirect", '2', outside.toString())
                .link("redirect/escaped", '2', "target").save(temporary, true);
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(outside.resolve("escaped"), LinkOption.NOFOLLOW_LINKS), "Nested link was created outside root");
        });

        run("reject hardlink source traversal", (temporary, root) -> {
            Files.writeString(temporary.resolve("outside"), "private host file");
            Path archive = new Archive().link("leak", '1', "../outside").save(temporary, true);
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(root.resolve("leak")), "External file linked into guest");
        });

        run("reject excessive declared member size before allocating", (temporary, root) -> {
            Path archive = gzip(temporary, header("large", '0', "", 8L * 1024 * 1024 * 1024 + 1));
            rejected(IOException.class, () -> extract(archive, root));
            check(!Files.exists(root.resolve("large")), "Oversized member began extraction");
        });

        run("reject nonzero data after tar terminator", (temporary, root) -> {
            Archive archive = new Archive();
            archive.tar.write(new byte[1024]);
            archive.tar.write(7);
            Path path = archive.save(temporary, false);
            rejected(IOException.class, () -> extract(path, root));
        });

        run("reject oversized all-zero tar trailer", (temporary, root) -> {
            Path archive = gzip(temporary, new byte[2 * 1024 * 1024]);
            rejected(IOException.class, () -> extract(archive, root));
        });

        run("interrupted extraction stops before following member", (temporary, root) -> {
            Archive archive = new Archive();
            for (int index = 1; index <= 501; index++) archive.file("files/" + index, "data");
            Path path = archive.save(temporary, true);
            rejected(InterruptedIOException.class, () -> TarExtractor.extract(path.toFile(), root.toFile(), count -> Thread.currentThread().interrupt()));
            check(Files.exists(root.resolve("files/500")), "Cancellation fixture did not reach progress callback");
            check(!Files.exists(root.resolve("files/501")), "Extraction ignored cancellation");
        });

        run("staging cleanup unlinks symlinks without deleting their targets", (temporary, root) -> {
            Path outside = Files.createDirectory(temporary.resolve("outside"));
            Path sentinel = Files.writeString(outside.resolve("preserve"), "host state");
            Path archive = new Archive().link("external", '2', outside.toString()).save(temporary, true);
            extract(archive, root);
            TarExtractor.remove(root.toFile());
            check(Files.readString(sentinel).equals("host state"), "Cleanup followed symlink into host data");
        });

        System.out.println("Archive host verification passed: " + passed + " cases");
    }
}
