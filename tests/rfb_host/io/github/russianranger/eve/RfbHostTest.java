package io.github.russianranger.eve;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;

/** Deterministic peer fixtures for the startup display's RFB boundary. */
public final class RfbHostTest {
    private static final class Screen implements RfbClient.Screen {
        int width, height, updates;
        int[] pixels;
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
    private static final class CountingOutput extends ByteArrayOutputStream {
        int writes, flushes;
        @Override public synchronized void write(byte[] bytes, int offset, int length) { writes++; super.write(bytes, offset, length); }
        @Override public void flush() { flushes++; }
        void clear() { reset(); writes = flushes = 0; }
    }
    private static void key(DataInputStream wire, int symbol, boolean down) throws IOException {
        check(wire.readUnsignedByte() == 4 && wire.readUnsignedByte() == (down ? 1 : 0)
            && wire.readUnsignedShort() == 0 && wire.readInt() == symbol, "atomic chord / Unicode event order");
    }
    private static void compoundInput() throws Exception {
        CountingOutput output = new CountingOutput();
        RfbClient client = new RfbClient(new ByteArrayInputStream(hello(2, 1)), output, new Screen());
        client.handshake(); output.clear();
        client.text("ab\ud83d\ude42", true);
        check(output.writes == 1 && output.flushes == 1, "compound text requires one write/flush");
        DataInputStream wire = new DataInputStream(new ByteArrayInputStream(output.toByteArray()));
        key(wire, 0xffe3, true); key(wire, 'a', true); key(wire, 'a', false); key(wire, 0xffe3, false);
        for (int symbol : new int[]{'a', 'b', 0x0101f642}) { key(wire, symbol, true); key(wire, symbol, false); }
        check(wire.available() == 0, "no duplicate text input");
        output.clear(); client.tap(0xff0d);
        check(output.writes == 1 && output.flushes == 1 && output.size() == 16, "paired tap batching");
        output.clear(); client.text("12345678901234567890", false);
        check(output.writes == 1 && output.flushes == 1 && output.size() == 320, "20-character text batching");
        output.clear(); rejects(() -> client.text("a".repeat(4097), true), "oversized text accepted");
        check(output.size() == 0, "oversized text sends no select-all chord");
    }
    private static void blockedReceiveDoesNotBlockInput() throws Exception {
        PipedInputStream pipe = new PipedInputStream(4096);
        PipedOutputStream peer = new PipedOutputStream(pipe); peer.write(hello(2, 1)); peer.flush();
        CountDownLatch waiting = new CountDownLatch(1);
        InputStream monitored = new FilterInputStream(pipe) {
            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                if (pipe.available() == 0) waiting.countDown();
                return in.read(bytes, offset, length);
            }
        };
        DisplayPerformance performance = new DisplayPerformance(); CountingOutput output = new CountingOutput();
        RfbClient client = new RfbClient(monitored, output, new Screen(), performance); client.handshake(); output.clear();
        ExecutorService threads = Executors.newFixedThreadPool(2);
        try {
            Future<?> receiving = threads.submit(() -> { try { client.readUpdate(); } catch (IOException expected) { } });
            check(waiting.await(1, TimeUnit.SECONDS), "reader entered native receive before input test");
            Future<?> sending = threads.submit(() -> { try { client.tap(0xff09); } catch (IOException error) { throw new RuntimeException(error); } });
            sending.get(1, TimeUnit.SECONDS);
            check(!receiving.isDone(), "receive remains blocked while input completes");
            check(output.size() == 16 && output.writes == 1, "blocked receive still sends paired input");
            peer.close(); receiving.get(2, TimeUnit.SECONDS);
            check(performance.socketReads.get() >= 2 && performance.socketBytes.get() == hello(2,1).length, "native receive accounting");
            check(performance.json().contains("\"socket_read_ms\"") && !performance.json().contains("password"), "content-free diagnostic schema");
        } finally { peer.close(); pipe.close(); threads.shutdownNow(); }
    }
    private static void motionKeepsButtonEdges() {
        List<String> delivered = new ArrayList<>(); List<Runnable> callbacks = new ArrayList<>();
        PointerMotion motion = new PointerMotion((x,y,mask) -> delivered.add(x+":"+y+":"+mask), new PointerMotion.Scheduler() {
            public void post(Runnable task) { callbacks.add(task); }
            public void remove(Runnable task) { callbacks.remove(task); }
        });
        motion.edge(1,1,1); motion.move(2,2,1); motion.move(3,3,1);
        check(callbacks.size() == 1, "motion uses one animation callback");
        Runnable pending = callbacks.remove(0); pending.run();
        motion.move(4,4,1); Runnable cancelled = callbacks.get(0); motion.edge(5,5,0); cancelled.run();
        motion.move(6,6,0); motion.edge(7,7,4); motion.edge(7,7,0);
        check(callbacks.isEmpty(), "button edges cancel pending motion");
        check(delivered.equals(Arrays.asList("1:1:1","3:3:1","5:5:0","7:7:4","7:7:0")), "down/latest-drag/up/right-click ordering");
        motion.move(8,8,0); Runnable abandoned = callbacks.get(0); motion.cancel(); abandoned.run();
        check(delivered.size() == 5, "dispose cancels pending input");
    }
    public static void main(String[] args) throws Exception {
        rawFrameAndInput(); malformedFrames(); compoundInput(); blockedReceiveDoesNotBlockInput(); motionKeepsButtonEdges();
        System.out.println("Client display RFB/input/motion/performance host fixtures passed");
    }
}
