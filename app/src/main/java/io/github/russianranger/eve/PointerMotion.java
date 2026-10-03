package io.github.russianranger.eve;

/** Coalesce position changes only; button transitions are never delayed or dropped. */
final class PointerMotion {
    interface Sink { void send(int x, int y, int mask); }
    interface Scheduler { void post(Runnable task); void remove(Runnable task); }
    private final Sink sink;
    private final Scheduler scheduler;
    private int x, y, mask;
    private boolean pending;
    private final Runnable flush;
    PointerMotion(Sink sink, Scheduler scheduler) {
        this.sink = sink; this.scheduler = scheduler;
        flush = () -> { if (pending) { pending = false; this.sink.send(x, y, mask); } };
    }
    void move(int x, int y, int mask) {
        this.x = x; this.y = y; this.mask = mask;
        if (!pending) { pending = true; scheduler.post(flush); }
    }
    void edge(int x, int y, int mask) { cancel(); sink.send(x, y, mask); }
    void cancel() { if (pending) { pending = false; scheduler.remove(flush); } }
}
