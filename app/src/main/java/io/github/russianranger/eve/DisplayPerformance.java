package io.github.russianranger.eve;

import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** Aggregate costs only: no key, text, pointer-position or framebuffer content is retained. */
final class DisplayPerformance {
    private static final AtomicLong IDS = new AtomicLong();
    final long id = IDS.incrementAndGet();
    final long started = System.nanoTime();
    final AtomicBoolean active = new AtomicBoolean(true);
    private final AtomicLong ended = new AtomicLong();
    private final Object receiveLock = new Object();
    private long readingStarted;
    final AtomicLong width = new AtomicLong(), height = new AtomicLong();
    final AtomicLong socketBytes = new AtomicLong(), socketReads = new AtomicLong(), socketNanos = new AtomicLong();
    final AtomicLong updates = new AtomicLong(), rectangles = new AtomicLong(), pixels = new AtomicLong();
    final AtomicLong decodeNanos = new AtomicLong(), publishNanos = new AtomicLong(), drawNanos = new AtomicLong(), draws = new AtomicLong();
    final AtomicLong inputs = new AtomicLong(), completedInputs = new AtomicLong(), rejectedInputs = new AtomicLong();
    final AtomicLong queueNanos = new AtomicLong(), maxQueueNanos = new AtomicLong(), sendNanos = new AtomicLong(), maxSendNanos = new AtomicLong(), maxQueueDepth = new AtomicLong();
    final AtomicLong androidFrames = new AtomicLong(), androidTotalNanos = new AtomicLong(), androidDrawNanos = new AtomicLong(), androidSyncNanos = new AtomicLong(), androidGpuNanos = new AtomicLong(), gpuSamples = new AtomicLong(), droppedFrameReports = new AtomicLong();
    static void maximum(AtomicLong value, long sample) { value.accumulateAndGet(sample, Math::max); }
    InputStream measure(InputStream source) {
        return new FilterInputStream(source) {
            @Override public int read() throws IOException {
                long start = System.nanoTime(); int result = -1;
                receiving(start);
                try { result = in.read(); return result; }
                finally { received(start, result < 0 ? 0 : 1); }
            }
            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                long start = System.nanoTime(); int count = 0;
                receiving(start);
                try { count = in.read(bytes, offset, length); return count; }
                finally { received(start, Math.max(0, count)); }
            }
            private void received(long start, int bytes) {
                synchronized (receiveLock) {
                    socketReads.incrementAndGet(); socketBytes.addAndGet(bytes); socketNanos.addAndGet(System.nanoTime() - start);
                    readingStarted = 0;
                }
            }
            private void receiving(long start) { synchronized (receiveLock) { readingStarted = start; } }
        };
    }
    void finish() { ended.compareAndSet(0, System.nanoTime()); active.set(false); }
    private long sampleTime() { long last = ended.get(); return last == 0 ? System.nanoTime() : last; }
    private long socketTime() {
        synchronized (receiveLock) {
            return socketNanos.get() + (readingStarted == 0 ? 0 : Math.max(0, sampleTime() - readingStarted));
        }
    }
    void inputQueued(int depth) { inputs.incrementAndGet(); maximum(maxQueueDepth, depth); }
    void inputStarted(long wait) { queueNanos.addAndGet(wait); maximum(maxQueueNanos, wait); }
    void inputFinished(long elapsed) { completedInputs.incrementAndGet(); sendNanos.addAndGet(elapsed); maximum(maxSendNanos, elapsed); }
    void frame(long total, long draw, long sync, long gpu, int dropped) {
        androidFrames.incrementAndGet(); androidTotalNanos.addAndGet(Math.max(0, total));
        androidDrawNanos.addAndGet(Math.max(0, draw)); androidSyncNanos.addAndGet(Math.max(0, sync));
        if (gpu >= 0) { androidGpuNanos.addAndGet(gpu); gpuSamples.incrementAndGet(); }
        droppedFrameReports.addAndGet(Math.max(0, dropped));
    }
    String json() {
        return json(active.get());
    }
    String json(boolean connected) {
        StringBuilder out = new StringBuilder(1024).append("{\n  \"format\": 1,\n  \"connection_id\": ").append(id)
            .append(",\n  \"active\": ").append(connected);
        number(out, "elapsed_ms", (sampleTime() - started) / 1000000);
        number(out, "width", width.get()); number(out, "height", height.get());
        number(out, "socket_bytes", socketBytes.get()); number(out, "socket_reads", socketReads.get());
        out.append(",\n  \"socket_read_ms\": ").append(socketTime() / 1000000.0); // Includes an unfinished native read waiting for server data.
        number(out, "framebuffer_updates", updates.get()); number(out, "raw_rectangles", rectangles.get()); number(out, "raw_pixels", pixels.get());
        millis(out, "decode_work_ms", decodeNanos); millis(out, "bitmap_publish_ms", publishNanos);
        number(out, "view_draws", draws.get()); millis(out, "view_draw_cpu_ms", drawNanos);
        number(out, "input_operations", inputs.get()); number(out, "completed_input_operations", completedInputs.get()); number(out, "rejected_input_operations", rejectedInputs.get());
        number(out, "max_input_queue_depth", maxQueueDepth.get()); millis(out, "input_queue_ms", queueNanos); millis(out, "max_input_queue_ms", maxQueueNanos);
        millis(out, "input_send_ms", sendNanos); millis(out, "max_input_send_ms", maxSendNanos);
        number(out, "android_window_frames", androidFrames.get()); millis(out, "android_frame_total_ms", androidTotalNanos);
        millis(out, "android_frame_draw_ms", androidDrawNanos); millis(out, "android_frame_sync_ms", androidSyncNanos);
        millis(out, "android_frame_gpu_ms", androidGpuNanos); number(out, "android_gpu_samples", gpuSamples.get()); number(out, "dropped_android_frame_reports", droppedFrameReports.get());
        return out.append("\n}\n").toString();
    }
    private static void number(StringBuilder out, String name, long value) { out.append(",\n  \"").append(name).append("\": ").append(value); }
    private static void millis(StringBuilder out, String name, AtomicLong nanos) { out.append(",\n  \"").append(name).append("\": ").append(nanos.get() / 1000000.0); }
}
