package io.github.russianranger.eve;

/** Counts received updates and distinct presented frames using a monotonic clock. */
final class FrameStats {
    static final class Sample {
        final long received, drawn, elapsedNanos;
        final double receivedPerSecond, drawnPerSecond;
        Sample(long received, long drawn, long elapsedNanos) {
            this.received = received; this.drawn = drawn; this.elapsedNanos = elapsedNanos;
            receivedPerSecond = elapsedNanos > 0 ? received * 1e9 / elapsedNanos : 0;
            drawnPerSecond = elapsedNanos > 0 ? drawn * 1e9 / elapsedNanos : 0;
        }
    }
    private long since, received, drawn;
    synchronized void reset(long now) { since = now; received = 0; drawn = 0; }
    synchronized void received() { received++; }
    synchronized void drawn() { drawn++; }
    synchronized Sample sample(long now) {
        Sample result = new Sample(received, drawn, Math.max(0, now - since));
        reset(now); return result;
    }
}
