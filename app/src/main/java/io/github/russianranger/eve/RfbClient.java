package io.github.russianranger.eve;

import java.io.*;
import java.nio.charset.StandardCharsets;

/** Basic RFB 3.x display/input transport. The only endpoint is the local client session. */
final class RfbClient {
    interface Screen {
        void resize(int width, int height);
        void pixels(int x, int y, int width, int height, int[] argb);
        void updated();
    }
    private final DataInputStream in;
    private final DataOutputStream out;
    private final Screen screen;
    private final DisplayPerformance performance;
    private volatile int width, height;
    private int[] pixelBuffer = new int[0];
    private byte[] rowBuffer = new byte[0];

    RfbClient(InputStream input, OutputStream output, Screen screen) {
        this(input, output, screen, new DisplayPerformance());
    }
    RfbClient(InputStream input, OutputStream output, Screen screen, DisplayPerformance performance) {
        this.performance = performance;
        in = new DataInputStream(new BufferedInputStream(performance.measure(input), 65536));
        out = new DataOutputStream(new BufferedOutputStream(output, 8192));
        this.screen = screen;
    }
    private byte[] bytes(int count) throws IOException {
        if (count < 0 || count > 1048576) throw new IOException("Display message exceeds limits");
        byte[] value = new byte[count]; in.readFully(value); return value;
    }
    void handshake() throws IOException {
        String version = new String(bytes(12), StandardCharsets.US_ASCII);
        boolean legacy = version.equals("RFB 003.003\n");
        if (!legacy && !version.equals("RFB 003.007\n") && !version.equals("RFB 003.008\n")) throw new IOException("Unsupported display protocol");
        synchronized (out) { out.write(version.getBytes(StandardCharsets.US_ASCII)); out.flush(); }
        if (legacy) {
            int security = in.readInt();
            if (security == 0) throw new IOException("Display refused connection: " + new String(bytes(in.readInt()), StandardCharsets.UTF_8));
            if (security != 1) throw new IOException("Unexpected authentication on the local display");
        } else {
            int count = in.readUnsignedByte();
            if (count == 0) throw new IOException("Display refused connection: " + new String(bytes(in.readInt()), StandardCharsets.UTF_8));
            boolean local = false;
            for (int i = 0; i < count; i++) if (in.readUnsignedByte() == 1) local = true;
            if (!local) throw new IOException("Unexpected authentication on the local display");
            synchronized (out) { out.writeByte(1); out.flush(); }
            if (version.equals("RFB 003.008\n") && in.readInt() != 0) throw new IOException("Local display authentication failed");
        }
        synchronized (out) { out.writeByte(1); out.flush(); }
        int w = in.readUnsignedShort(), h = in.readUnsignedShort();
        bytes(16); bytes(in.readInt()); resize(w, h);
        synchronized (out) {
            out.writeInt(0); // SetPixelFormat with padding, 32-bit little-endian RGB.
            out.write(new byte[]{32,24,0,1,0,(byte)255,0,(byte)255,0,(byte)255,16,8,0,0,0,0});
            out.writeByte(2); out.writeByte(0); out.writeShort(2);
            out.writeInt(0); out.writeInt(-223); // Raw and DesktopSize.
            out.flush();
        }
        request(false);
    }
    private void resize(int w, int h) throws IOException {
        if (w < 1 || h < 1 || w > 4096 || h > 2160 || (long) w * h > 4194304) throw new IOException("Unsupported display dimensions");
        width = w; height = h; performance.width.set(w); performance.height.set(h); screen.resize(w, h);
    }
    void readUpdate() throws IOException {
        long started = System.nanoTime(), receiving = performance.socketNanos.get(), publishing = performance.publishNanos.get();
        try { readMessage(); }
        finally {
            // Native reads include server wait. Bitmap publication is accounted separately.
            long work = System.nanoTime() - started - (performance.socketNanos.get() - receiving)
                - (performance.publishNanos.get() - publishing);
            performance.decodeNanos.addAndGet(Math.max(0, work));
        }
    }
    private void readMessage() throws IOException {
        int message = in.readUnsignedByte();
        if (message == 2) return; // Bell.
        if (message == 3) { bytes(3); bytes(in.readInt()); return; } // No clipboard integration.
        if (message != 0) throw new IOException("Unexpected display message: " + message);
        in.readUnsignedByte(); int count = in.readUnsignedShort();
        for (int i = 0; i < count; i++) {
            int x = in.readUnsignedShort(), y = in.readUnsignedShort();
            int w = in.readUnsignedShort(), h = in.readUnsignedShort(), encoding = in.readInt();
            if (encoding == -223) { resize(w, h); continue; }
            if (w < 1 || h < 1 || (long) x + w > width || (long) y + h > height) throw new IOException("Display rectangle is outside the framebuffer");
            if (encoding != 0) throw new IOException("Unsupported display encoding: " + encoding);
            int length = w * h;
            if (pixelBuffer.length < length) pixelBuffer = new int[length];
            if (rowBuffer.length < w * 4) rowBuffer = new byte[w * 4];
            for (int row = 0; row < h; row++) {
                in.readFully(rowBuffer, 0, w * 4);
                for (int column = 0; column < w; column++) {
                    int at = column * 4;
                    pixelBuffer[row * w + column] = 0xff000000 | ((rowBuffer[at + 2] & 255) << 16) | ((rowBuffer[at + 1] & 255) << 8) | (rowBuffer[at] & 255);
                }
            }
            long publishing = System.nanoTime();
            screen.pixels(x, y, w, h, pixelBuffer);
            performance.publishNanos.addAndGet(System.nanoTime() - publishing);
            performance.rectangles.incrementAndGet(); performance.pixels.addAndGet(length);
        }
        if (count > 0) { performance.updates.incrementAndGet(); screen.updated(); }
        request(true);
    }
    private void request(boolean incremental) throws IOException {
        synchronized (out) {
            out.writeByte(3); out.writeByte(incremental ? 1 : 0);
            out.writeShort(0); out.writeShort(0); out.writeShort(width); out.writeShort(height); out.flush();
        }
    }
    void key(int keysym, boolean down) throws IOException {
        synchronized (out) { writeKey(keysym, down); out.flush(); }
    }
    private void writeKey(int keysym, boolean down) throws IOException {
        out.writeByte(4); out.writeByte(down ? 1 : 0); out.writeShort(0); out.writeInt(keysym);
    }
    void tap(int keysym) throws IOException {
        synchronized (out) { writeKey(keysym, true); writeKey(keysym, false); out.flush(); }
    }
    void text(String value, boolean replace) throws IOException {
        if (value.length() > 4096) throw new IOException("Text exceeds input limits");
        synchronized (out) {
            if (replace) {
                writeKey(0xffe3, true); // Control_L + a selects the currently focused field.
                writeKey('a', true); writeKey('a', false); writeKey(0xffe3, false);
            }
            for (int i = 0; i < value.length();) {
                int code = value.codePointAt(i); i += Character.charCount(code);
                int keysym = code <= 255 ? code : 0x01000000 | code;
                writeKey(keysym, true); writeKey(keysym, false);
            }
            out.flush();
        }
    }
    void pointer(int x, int y, int mask) throws IOException {
        synchronized (out) {
            out.writeByte(5); out.writeByte(mask & 31);
            out.writeShort(Math.max(0, Math.min(width - 1, x))); out.writeShort(Math.max(0, Math.min(height - 1, y))); out.flush();
        }
    }
}
