package io.github.russianranger.eve;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

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
    private static void socketReceiveDoesNotBlockInput(boolean partialPixels) throws Exception {
        byte[] packet = update(2, 1, 0, new byte[]{0x56, 0x34, 0x12, 0, (byte)0xef, (byte)0xcd, (byte)0xab, 0});
        int prefix = partialPixels ? packet.length - 5 : 0;
        CountDownLatch ready = new CountDownLatch(1), waiting = new CountDownLatch(1);
        CountDownLatch inputReceived = new CountDownLatch(1), finishFrame = new CountDownLatch(1);
        ExecutorService threads = Executors.newFixedThreadPool(3);
        try (ServerSocket listener = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) {
            Future<?> peer = threads.submit(() -> {
                try (Socket socket = listener.accept()) {
                    socket.setSoTimeout(5000); socket.setTcpNoDelay(true);
                    OutputStream output = socket.getOutputStream();
                    DataInputStream wire = new DataInputStream(socket.getInputStream());
                    output.write(hello(2, 1)); output.flush();
                    wire.readFully(new byte[56]); // Complete client hello, format, encodings and first request.
                    check(ready.await(2, TimeUnit.SECONDS), "socket fixture ready after handshake");
                    if (prefix > 0) { output.write(packet, 0, prefix); output.flush(); }
                    // No further framebuffer bytes are sent until all input has arrived.
                    key(wire, 0xffe1, true); key(wire, 0xffe1, false);
                    key(wire, 0xff09, true); key(wire, 0xff09, false);
                    key(wire, 0xffe3, true); key(wire, 'a', true); key(wire, 'a', false); key(wire, 0xffe3, false);
                    for (int symbol : new int[]{'a', 0x0101f642}) { key(wire, symbol, true); key(wire, symbol, false); }
                    for (int mask = 1; mask >= 0; mask--) check(wire.readUnsignedByte() == 5 && wire.readUnsignedByte() == mask
                        && wire.readUnsignedShort() == 1 && wire.readUnsignedShort() == 0, "socket pointer down/up order while receive blocks");
                    inputReceived.countDown();
                    check(finishFrame.await(2, TimeUnit.SECONDS), "socket fixture released after input verification");
                    output.write(packet, prefix, packet.length - prefix); output.flush();
                    check(wire.readUnsignedByte() == 3 && wire.readUnsignedByte() == 1 && wire.readUnsignedShort() == 0
                        && wire.readUnsignedShort() == 0 && wire.readUnsignedShort() == 2 && wire.readUnsignedShort() == 1,
                        "incremental request after blocked frame completes");
                }
                return null;
            });
            try (Socket socket = new Socket("127.0.0.1", listener.getLocalPort())) {
                socket.setSoTimeout(5000); socket.setTcpNoDelay(true);
                AtomicBoolean watching = new AtomicBoolean();
                InputStream monitored = new FilterInputStream(socket.getInputStream()) {
                    private long received;
                    @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                        // This runs immediately before the real socket read, after the
                        // peer's complete prefix has been consumed (including fragmented reads).
                        if (watching.get() && received >= prefix) waiting.countDown();
                        int count = in.read(bytes, offset, length);
                        if (watching.get() && count > 0) received += count;
                        return count;
                    }
                };
                Screen screen = new Screen(); DisplayPerformance performance = new DisplayPerformance();
                RfbClient client = new RfbClient(monitored, socket.getOutputStream(), screen, performance);
                client.handshake(); watching.set(true); ready.countDown();
                Future<?> receiving = threads.submit(() -> { client.readUpdate(); return null; });
                check(waiting.await(2, TimeUnit.SECONDS), partialPixels ? "native socket waits for remaining raw pixels" : "native socket waits for message header");
                Future<?> sending = threads.submit(() -> {
                    client.key(0xffe1, true); client.key(0xffe1, false); client.tap(0xff09);
                    client.text("a\ud83d\ude42", true); client.pointer(1, 0, 1); client.pointer(1, 0, 0);
                    return null;
                });
                sending.get(2, TimeUnit.SECONDS);
                check(inputReceived.await(2, TimeUnit.SECONDS), "peer received every input operation while native read waits");
                check(!receiving.isDone(), "socket receive remains blocked until fixture releases frame");
                finishFrame.countDown(); receiving.get(2, TimeUnit.SECONDS); peer.get(2, TimeUnit.SECONDS);
                check(screen.updates == 1 && Arrays.equals(screen.pixels, new int[]{0xff123456, 0xffabcdef}), "socket raw frame decodes after input");
                check(performance.socketBytes.get() == hello(2, 1).length + packet.length, "socket receive counters include complete frame once");
            }
        } finally {
            ready.countDown(); finishFrame.countDown(); threads.shutdownNow();
            check(threads.awaitTermination(2, TimeUnit.SECONDS), "socket fixture threads stopped");
        }
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
    private static List<String> events(CountingOutput output) throws IOException {
        List<String> result = new ArrayList<>();
        DataInputStream wire = new DataInputStream(new ByteArrayInputStream(output.toByteArray()));
        while (wire.available() > 0) {
            int type = wire.readUnsignedByte(), state = wire.readUnsignedByte();
            if (type == 4) { check(wire.readUnsignedShort() == 0, "key padding"); result.add("key:" + wire.readInt() + ":" + state); }
            else if (type == 5) result.add("pointer:" + wire.readUnsignedShort() + ":" + wire.readUnsignedShort() + ":" + state);
            else throw new AssertionError("Unexpected input message " + type);
        }
        return result;
    }
    private static void controllerAndSharedInputReachWire() throws Exception {
        CountingOutput output = new CountingOutput();
        RfbClient client = new RfbClient(new ByteArrayInputStream(hello(1280, 720)), output, new Screen());
        client.handshake(); output.clear();
        DisplayInput display = new DisplayInput(new DisplayInput.Sink() {
            public void key(int symbol, boolean down) { try { client.key(symbol, down); } catch (IOException e) { throw new RuntimeException(e); } }
            public void pointer(int x, int y, int mask) { try { client.pointer(x, y, mask); } catch (IOException e) { throw new RuntimeException(e); } }
        });
        display.size(1280, 720);
        ControllerInput pad = new ControllerInput(new ControllerInput.Sink() {
            public void button(String action, boolean down) { display.action(action, down); }
            public void pointer(float x, float y) { display.move(x, y); }
            public void wheel(int amount) { display.wheel(amount); }
        });
        pad.activate(true);
        display.key("keyboard:1", '1', true); pad.value("X", 1); pad.value("X", 1);
        pad.value("X", 0); display.key("keyboard:1", '!', false);
        check(events(output).equals(Arrays.asList("key:49:1", "key:49:0")), "pad/keyboard refcounts preserve original release symbol");
        output.clear();
        pad.value("X", 1); pad.value("L2", 1); pad.value("L2", 1); pad.value("L2", 0); pad.value("X", 0);
        check(events(output).equals(Arrays.asList("key:49:1", "key:49:0", "key:56:1", "key:56:0")), "held hotkey switches once to Hotbar 2 and releases old layer");
        output.clear();
        display.position(500, 300); pad.value("R1", 1); display.touch(600, 400, 1);
        pad.value("R1", 0); display.touch(600, 400, 0);
        check(events(output).equals(Arrays.asList("pointer:500:300:0", "pointer:500:300:1", "pointer:600:400:1", "pointer:600:400:1", "pointer:600:400:0")), "touch/pad button ownership shares position without early release");
        output.clear(); pad.selectLayer(3); pad.value("X", 1); pad.value("X", 0);
        check(events(output).equals(Arrays.asList("key:65505:1", "key:66:1", "key:66:0", "key:65505:0")), "inventory Shift+B modifier/key order reaches RFB");
        output.clear(); pad.value("L1", 1); display.wheel(1); pad.value("L1", 0);
        check(events(output).equals(Arrays.asList("pointer:600:400:4", "pointer:600:400:12", "pointer:600:400:4", "pointer:600:400:0")), "wheel impulses preserve a held right mouse button");
        output.clear(); pad.value("L1", 1); pad.value("LeftUp", 1); pad.activate(false); display.releaseAll();
        List<String> released = events(output);
        check(released.contains("key:119:1") && released.contains("key:119:0"), "background/menu release sends movement key-up");
        check(released.get(released.size()-1).equals("pointer:600:400:0"), "all local pointer owners released");
        output.clear(); display.key("keyboard:w", 'w', true); display.key("keyboard:ctrl", 0xffe3, true); display.mouse("pad:right", 4, true);
        client.releaseInputs();
        List<String> shutdown = events(output);
        check(shutdown.contains("key:119:0") && shutdown.contains("key:65507:0"), "socket shutdown independently releases all wire-held keys");
        check(shutdown.get(shutdown.size()-1).equals("pointer:600:400:0"), "socket shutdown releases mouse at existing position");
        output.clear(); client.releaseInputs();
        check(events(output).equals(Arrays.asList("pointer:600:400:0")), "wire release is idempotent");
    }
    public static void main(String[] args) throws Exception {
        rawFrameAndInput(); malformedFrames(); compoundInput(); blockedReceiveDoesNotBlockInput();
        socketReceiveDoesNotBlockInput(false); socketReceiveDoesNotBlockInput(true); motionKeepsButtonEdges();
        controllerAndSharedInputReachWire();
        System.out.println("Client display RFB/controller/shared-hold/release/motion/performance host fixtures passed");
    }
}
