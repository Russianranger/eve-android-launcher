package android.system;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.EnumSet;
import java.util.Set;

/** Host filesystem adapter for the Android calls made by the real extractor. */
public final class Os {
    public static void chmod(String path, int mode) throws IOException {
        Set<PosixFilePermission> permissions = EnumSet.noneOf(PosixFilePermission.class);
        PosixFilePermission[] values = {
            PosixFilePermission.OTHERS_EXECUTE, PosixFilePermission.OTHERS_WRITE,
            PosixFilePermission.OTHERS_READ, PosixFilePermission.GROUP_EXECUTE,
            PosixFilePermission.GROUP_WRITE, PosixFilePermission.GROUP_READ,
            PosixFilePermission.OWNER_EXECUTE, PosixFilePermission.OWNER_WRITE,
            PosixFilePermission.OWNER_READ,
        };
        for (int bit = 0; bit < values.length; bit++) {
            if ((mode & (1 << bit)) != 0) permissions.add(values[bit]);
        }
        Files.setPosixFilePermissions(Path.of(path), permissions);
    }

    public static void link(String source, String destination) throws IOException {
        Files.createLink(Path.of(destination), Path.of(source));
    }

    public static void symlink(String target, String destination) throws IOException {
        Files.createSymbolicLink(Path.of(destination), Path.of(target));
    }
}
