package io.github.russianranger.eve;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Deterministic peer fixtures for the startup display's RFB boundary. */
public final class RfbHostTest {
    private static final class Screen implements RfbClient.Screen {
        int width, height, updates;
        int[] pixels;
        byte[] rgba;
        int directCopies;
        @Override public void pixels(int w, int h, ByteBuffer values) {
            check(w == width && h == height && values.remaining() == w * h * 4, "complete direct framebuffer");
            rgba = new byte[values.remaining()]; values.get(rgba); directCopies++;
        }
        @Override public void resize(int w, int h) { width = w; height = h; }
        @Override public void pixels(int x, int y, int w, int h, int[] values) { check(x == 0 && y == 0 && w == 2 && h == 1, "rectangle coordinates"); pixels = Arrays.copyOf(values, w * h); }
        @Override public void updated() { updates++; }
    }
    private interface Checked { void run() throws Exception; }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private static void rejects(Checked action, String message) throws Exception {
        try { action.run(); } catch (IOException expected) { return; }
        throw new AssertionError(message);
    }
    private static byte[] hello(int width, int height) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream peer = new DataOutputStream(bytes);
        peer.write("RFB 003.008\n".getBytes(StandardCharsets.US_ASCII)); peer.writeByte(1); peer.writeByte(1); peer.writeInt(0);
        peer.writeShort(width); peer.writeShort(height); peer.write(new byte[16]); peer.writeInt(4); peer.writeBytes("test");
        return bytes.toByteArray();
    }
    private static byte[] update(int width, int height, int x, byte[] pixels) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream peer = new DataOutputStream(bytes);
        peer.writeByte(0); peer.writeByte(0); peer.writeShort(1); peer.writeShort(x); peer.writeShort(0); peer.writeShort(width); peer.writeShort(height); peer.writeInt(0); peer.write(pixels); return bytes.toByteArray();
    }
    private static byte[] together(byte[] first, byte[] second) throws IOException { ByteArrayOutputStream bytes = new ByteArrayOutputStream(); bytes.write(first); bytes.write(second); return bytes.toByteArray(); }
    private static InputStream fragmented(byte[] bytes) {
        return new ByteArrayInputStream(bytes) { @Override public synchronized int read(byte[] b, int off, int len) { return super.read(b, off, Math.min(3, len)); } };
    }
    private static void rawFrameAndInput() throws Exception {
        byte[] data = together(hello(2, 1), update(2, 1, 0, new byte[]{0x56, 0x34, 0x12, 0, (byte) 0xef, (byte) 0xcd, (byte) 0xab, 0}));
        Screen screen = new Screen(); ByteArrayOutputStream output = new ByteArrayOutputStream();
        RfbClient client = new RfbClient(fragmented(data), output, screen);
        client.handshake(); client.readUpdate(); client.key(0xff0d, true); client.key(0xff0d, false); client.pointer(999, -4, 1); client.pointer(1, 0, 0);
        check(screen.width == 2 && screen.height == 1 && screen.updates == 1, "frame publication");
        check(Arrays.equals(screen.pixels, new int[]{0xff123456, 0xffabcdef}), "raw RGB byte order and alpha");
        DataInputStream wire = new DataInputStream(new ByteArrayInputStream(output.toByteArray()));
        check(new String(wire.readNBytes(12), StandardCharsets.US_ASCII).equals("RFB 003.008\n"), "protocol negotiation");
        check(wire.readUnsignedByte() == 1 && wire.readUnsignedByte() == 1, "local security and shared display");
        check(wire.readInt() == 0, "pixel format framing");
        byte[] format = wire.readNBytes(16); check(format[0] == 32 && format[1] == 24 && format[2] == 0 && format[10] == 16, "requested little-endian RGB format");
        check(wire.readUnsignedByte() == 2 && wire.readUnsignedByte() == 0 && wire.readUnsignedShort() == 2 && wire.readInt() == 0 && wire.readInt() == -223, "raw/resize encodings only");
        for (int incremental = 0; incremental <= 1; incremental++) {
            check(wire.readUnsignedByte() == 3 && wire.readUnsignedByte() == incremental && wire.readUnsignedShort() == 0 && wire.readUnsignedShort() == 0 && wire.readUnsignedShort() == 2 && wire.readUnsignedShort() == 1, "frame request bounds");
        }
        for (int down = 1; down >= 0; down--) check(wire.readUnsignedByte() == 4 && wire.readUnsignedByte() == down && wire.readUnsignedShort() == 0 && wire.readInt() == 0xff0d, "paired key event framing");
        for (int mask = 1; mask >= 0; mask--) check(wire.readUnsignedByte() == 5 && wire.readUnsignedByte() == mask && wire.readUnsignedShort() == 1 && wire.readUnsignedShort() == 0, "clamped pointer and button release");
        check(wire.available() == 0, "no unexpected input payload");
    }
    private static void malformedFrames() throws Exception {
        Screen screen = new Screen();
        rejects(() -> new RfbClient(new ByteArrayInputStream(hello(0, 720)), new ByteArrayOutputStream(), screen).handshake(), "zero width accepted");
        rejects(() -> new RfbClient(new ByteArrayInputStream(hello(4096, 2160)), new ByteArrayOutputStream(), screen).handshake(), "excess framebuffer allocation accepted");
        RfbClient truncated = new RfbClient(new ByteArrayInputStream(together(hello(2, 1), update(2, 1, 0, new byte[7]))), new ByteArrayOutputStream(), screen);
        truncated.handshake(); rejects(truncated::readUpdate, "truncated pixel bytes accepted");
        RfbClient outside = new RfbClient(new ByteArrayInputStream(together(hello(2, 1), update(2, 1, 1, new byte[8]))), new ByteArrayOutputStream(), screen);
        outside.handshake(); rejects(outside::readUpdate, "out-of-bounds rectangle accepted");
        ByteArrayOutputStream clipboard = new ByteArrayOutputStream(); DataOutputStream peer = new DataOutputStream(clipboard); peer.writeByte(3); peer.write(new byte[3]); peer.writeInt(Integer.MAX_VALUE);
        RfbClient oversized = new RfbClient(new ByteArrayInputStream(together(hello(2, 1), clipboard.toByteArray())), new ByteArrayOutputStream(), screen);
        oversized.handshake(); rejects(oversized::readUpdate, "unbounded clipboard allocation accepted");
    }
    private static void directFramesAndPipeline() throws Exception {
        byte[] first = {0x12,0x34,0x56,0, (byte)0xab,(byte)0xcd,(byte)0xef,(byte)0xfe};
        byte[] data = together(hello(2, 1), update(2, 1, 0, first));
        Screen screen = new Screen(); ByteArrayOutputStream output = new ByteArrayOutputStream();
        int pixelOffset = hello(2, 1).length + 16;
        InputStream peer = new ByteArrayInputStream(data) {
            @Override public synchronized int read(byte[] bytes, int offset, int length) {
                if (pos >= pixelOffset) check(output.size() == 66, "next request must precede pixel reads");
                return super.read(bytes, offset, Math.min(1, length));
            }
        };
        RfbClient client = new RfbClient(peer, output, screen, true, true);
        client.handshake(); client.readUpdate();
        check(screen.pixels == null && Arrays.equals(screen.rgba, first), "direct RGBA and padding copied without conversion");
        check(screen.updates == 1, "direct frame published once");
        DataInputStream wire = new DataInputStream(new ByteArrayInputStream(output.toByteArray()));
        wire.skipNBytes(18); byte[] format = wire.readNBytes(16);
        check(format[0] == 32 && format[2] == 0 && format[10] == 0 && format[11] == 8 && format[12] == 16, "Android RGBA byte shifts");
        wire.skipNBytes(12);
        for (int incremental = 0; incremental <= 1; incremental++) check(wire.readUnsignedByte() == 3 && wire.readUnsignedByte() == incremental && wire.readUnsignedShort() == 0 && wire.readUnsignedShort() == 0 && wire.readUnsignedShort() == 2 && wire.readUnsignedShort() == 1, "exactly one pipelined request");
        check(wire.available() == 0, "no trailing duplicate request");
    }
    private static byte[] rectangle(int x, int y, int w, int h, int encoding, byte[] pixels) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream peer = new DataOutputStream(bytes);
        peer.writeByte(0); peer.writeByte(0); peer.writeShort(1); peer.writeShort(x); peer.writeShort(y); peer.writeShort(w); peer.writeShort(h); peer.writeInt(encoding); peer.write(pixels); return bytes.toByteArray();
    }
    private static void partialDirectFramesAndResize() throws Exception {
        byte[] first = new byte[24]; Arrays.fill(first, (byte) 0x2a);
        byte[] patch = {1,2,3,4,5,6,7,8};
        byte[] data = together(together(together(hello(3, 2), update(3, 2, 0, first)), rectangle(1, 0, 1, 2, 0, patch)), rectangle(0, 0, 2, 1, -223, new byte[0]));
        Screen screen = new Screen(); ByteArrayOutputStream output = new ByteArrayOutputStream();
        RfbClient client = new RfbClient(fragmented(data), output, screen, true, true);
        client.handshake(); client.readUpdate(); client.readUpdate();
        byte[] expected = first.clone(); System.arraycopy(patch, 0, expected, 4, 4); System.arraycopy(patch, 4, expected, 16, 4);
        check(Arrays.equals(screen.rgba, expected), "partial rectangles preserve untouched rows and columns");
        client.readUpdate();
        check(screen.width == 2 && screen.height == 1, "desktop resize accepted");
        byte[] requests = output.toByteArray();
        DataInputStream last = new DataInputStream(new ByteArrayInputStream(requests, requests.length - 10, 10));
        check(last.readUnsignedByte() == 3 && last.readUnsignedByte() == 0 && last.readUnsignedShort() == 0 && last.readUnsignedShort() == 0 && last.readUnsignedShort() == 2 && last.readUnsignedShort() == 1, "resized desktop gets full request using new bounds");
    }
    private static void multipleRectanglesAndModeCombinations() throws Exception {
        for (boolean direct : new boolean[]{false, true}) for (boolean pipeline : new boolean[]{false, true}) {
            Screen screen = new Screen(); ByteArrayOutputStream output = new ByteArrayOutputStream();
            RfbClient client = new RfbClient(fragmented(together(hello(2, 1), update(2, 1, 0, new byte[8]))), output, screen, direct, pipeline);
            client.handshake(); client.readUpdate();
            check(screen.updates == 1 && output.size() == 66, "pixel and request modes operate independently");
            check(direct ? screen.pixels == null && screen.directCopies == 1 : screen.rgba == null && screen.pixels.length == 2, "selected pixel mode only");
        }
        byte[] first = rectangle(0, 0, 2, 1, 0, new byte[]{1,2,3,0,4,5,6,0});
        byte[] second = rectangle(1, 0, 1, 1, 0, new byte[]{7,8,9,0});
        first[3] = 2;
        byte[] multi = together(first, Arrays.copyOfRange(second, 4, second.length));
        Screen screen = new Screen();
        RfbClient client = new RfbClient(fragmented(together(hello(2, 1), multi)), new ByteArrayOutputStream(), screen, true, true);
        client.handshake(); client.readUpdate();
        check(screen.directCopies == 1 && screen.updates == 1 && Arrays.equals(screen.rgba, new byte[]{1,2,3,0,7,8,9,0}), "multiple rectangles publish one complete framebuffer");
    }
    private static void malformedDirectFrames() throws Exception {
        for (boolean pipeline : new boolean[]{false, true}) {
            Screen screen = new Screen();
            for (byte[] update : new byte[][]{
                update(2, 1, 0, new byte[7]), rectangle(1, 0, 2, 1, 0, new byte[8]),
                rectangle(0, 1, 2, 1, 0, new byte[8]), rectangle(0, 0, 0, 1, 0, new byte[0]),
                rectangle(0, 0, 2, 1, 5, new byte[8]), rectangle(0, 0, 4096, 2160, -223, new byte[0])}) {
                RfbClient client = new RfbClient(fragmented(together(hello(2, 1), update)), new ByteArrayOutputStream(), screen, true, pipeline);
                client.handshake(); rejects(client::readUpdate, "invalid direct rectangle accepted");
                check(screen.rgba == null && screen.updates == 0, "invalid frame must not publish");
            }
        }
    }
    private static void frameCounters() {
        FrameStats frames = new FrameStats(); frames.reset(100);
        for (int i = 0; i < 30; i++) frames.received();
        for (int i = 0; i < 15; i++) frames.drawn();
        FrameStats.Sample sample = frames.sample(10000000100L);
        check(sample.received == 30 && sample.drawn == 15, "separate receive/draw counts");
        check(sample.receivedPerSecond == 3 && sample.drawnPerSecond == 1.5, "monotonic ten-second rates");
        sample = frames.sample(20000000100L);
        check(sample.receivedPerSecond == 0 && sample.drawnPerSecond == 0, "idle windows reset counts");
        frames.reset(900); frames.received(); sample = frames.sample(900);
        check(sample.receivedPerSecond == 0, "zero elapsed window is finite");
    }
    public static void main(String[] args) throws Exception {
        frameCounters(); rawFrameAndInput(); malformedFrames(); directFramesAndPipeline(); partialDirectFramesAndResize(); multipleRectanglesAndModeCombinations(); malformedDirectFrames();
        System.out.println("Client display RFB host fixtures passed");
    }
}
