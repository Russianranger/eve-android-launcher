package io.github.russianranger.eve;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;

/** Basic RFB 3.x display/input transport. The only endpoint is the local client session. */
final class RfbClient {
    interface Screen {
        void resize(int width, int height);
        void pixels(int x, int y, int width, int height, int[] argb);
        void pixels(int width, int height, ByteBuffer rgba);
        void updated();
    }
    private final DataInputStream in;
    private final DataOutputStream out;
    private final Screen screen;
    private volatile int width, height;
    private int[] pixelBuffer = new int[0];
    private byte[] rowBuffer = new byte[0];
    private ByteBuffer framebuffer;
    private final boolean directPixels, pipelineRequests;

    RfbClient(InputStream input, OutputStream output, Screen screen) {
        this(input, output, screen, false, false);
    }
    RfbClient(InputStream input, OutputStream output, Screen screen, boolean directPixels, boolean pipelineRequests) {
        this.directPixels = directPixels; this.pipelineRequests = pipelineRequests;
        in = new DataInputStream(new BufferedInputStream(input, 65536));
        out = new DataOutputStream(output);
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
            out.write(new byte[]{32,24,0,1,0,(byte)255,0,(byte)255,0,(byte)255,
                (byte) (directPixels ? 0 : 16),8,(byte) (directPixels ? 16 : 0),0,0,0});
            out.writeByte(2); out.writeByte(0); out.writeShort(2);
            out.writeInt(0); out.writeInt(-223); // Raw and DesktopSize.
            out.flush();
        }
        request(false);
    }
    private void resize(int w, int h) throws IOException {
        if (w < 1 || h < 1 || w > 4096 || h > 2160 || (long) w * h > 4194304) throw new IOException("Unsupported display dimensions");
        width = w; height = h;
        if (directPixels) framebuffer = ByteBuffer.allocate(w * h * 4);
        screen.resize(w, h);
    }
    void readUpdate() throws IOException {
        int message = in.readUnsignedByte();
        if (message == 2) return; // Bell.
        if (message == 3) { bytes(3); bytes(in.readInt()); return; } // No clipboard integration.
        if (message != 0) throw new IOException("Unexpected display message: " + message);
        in.readUnsignedByte(); int count = in.readUnsignedShort();
        // Keep one request in flight while decoding/uploading the current frame.
        if (pipelineRequests) request(true);
        boolean resized = false, changed = false;
        for (int i = 0; i < count; i++) {
            int x = in.readUnsignedShort(), y = in.readUnsignedShort();
            int w = in.readUnsignedShort(), h = in.readUnsignedShort(), encoding = in.readInt();
            if (encoding == -223) { resize(w, h); resized = true; continue; }
            if (w < 1 || h < 1 || (long) x + w > width || (long) y + h > height) throw new IOException("Display rectangle is outside the framebuffer");
            if (encoding != 0) throw new IOException("Unsupported display encoding: " + encoding);
            changed = true;
            if (directPixels) {
                // Heap ByteBuffer lets readFully place wire RGBA bytes directly in the
                // framebuffer. Only partial-width rectangles need a row loop.
                byte[] target = framebuffer.array();
                if (x == 0 && w == width) in.readFully(target, y * width * 4, w * h * 4);
                else for (int row = 0; row < h; row++) in.readFully(target, ((y + row) * width + x) * 4, w * 4);
                continue;
            }
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
            screen.pixels(x, y, w, h, pixelBuffer);
        }
        if (directPixels && changed) {
            framebuffer.position(0);
            screen.pixels(width, height, framebuffer.asReadOnlyBuffer());
        }
        if (count > 0) screen.updated();
        // A pipelined request used the old dimensions. Request the entire resized
        // framebuffer so newly exposed pixels are never left uninitialized.
        if (resized) request(false);
        else if (!pipelineRequests) request(true);
    }
    private void request(boolean incremental) throws IOException {
        synchronized (out) {
            out.writeByte(3); out.writeByte(incremental ? 1 : 0);
            out.writeShort(0); out.writeShort(0); out.writeShort(width); out.writeShort(height); out.flush();
        }
    }
    void key(int keysym, boolean down) throws IOException {
        synchronized (out) { out.writeByte(4); out.writeByte(down ? 1 : 0); out.writeShort(0); out.writeInt(keysym); out.flush(); }
    }
    void pointer(int x, int y, int mask) throws IOException {
        synchronized (out) {
            out.writeByte(5); out.writeByte(mask & 31);
            out.writeShort(Math.max(0, Math.min(width - 1, x))); out.writeShort(Math.max(0, Math.min(height - 1, y))); out.flush();
        }
    }
}
