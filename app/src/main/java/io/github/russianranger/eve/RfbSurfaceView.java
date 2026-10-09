package io.github.russianranger.eve;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;

/** CPU canvas on a separate SurfaceFlinger layer; RFB and the game renderer are unchanged. */
final class RfbSurfaceView extends FrameLayout implements RfbScreen, SurfaceHolder.Callback {
    interface SurfaceAccess {
        Canvas lock();
        void post(Canvas canvas);
    }
    interface Failure { void failed(RfbSurfaceView source, String reason); }
    interface BitmapFactory { Bitmap create(int width, int height); }
    private final Object lock = new Object();
    private final SurfaceView surface;
    private final SurfaceAccess access;
    private final Failure failure;
    private final BitmapFactory allocator;
    private final RectF destination = new RectF();
    private final PointerMotion motion;
    private final Thread renderer;
    private Bitmap image, completed;
    private Canvas completedCanvas;
    private boolean resumed, surfaceReady, dirty, disposed, failed;
    private long epoch, completedVersion;
    private volatile RfbView.Pointer pointer;
    private volatile DisplayPerformance performance;
    private int lastX, lastY;
    private boolean touching;

    RfbSurfaceView(Context context, Failure failure) { this(context, failure, null); }
    RfbSurfaceView(Context context, Failure failure, SurfaceAccess injected) {
        this(context, failure, injected, (width, height) -> Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888, false));
    }
    RfbSurfaceView(Context context, Failure failure, SurfaceAccess injected, BitmapFactory allocator) {
        super(context);
        this.failure = failure;
        this.allocator = allocator;
        setBackgroundColor(Color.BLACK); setFocusable(true);
        surface = new SurfaceView(context);
        // SurfaceView punches through the app UI. Its own View background must stay transparent.
        surface.getHolder().setFormat(PixelFormat.RGBX_8888);
        surface.getHolder().addCallback(this);
        addView(surface, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
        access = injected != null ? injected : new SurfaceAccess() {
            public Canvas lock() { return surface.getHolder().lockCanvas(); }
            public void post(Canvas canvas) { surface.getHolder().unlockCanvasAndPost(canvas); }
        };
        motion = new PointerMotion((x, y, mask) -> { RfbView.Pointer target = pointer; if (target != null) target.send(x, y, mask); },
            new PointerMotion.Scheduler() {
                public void post(Runnable task) { postOnAnimation(task); }
                public void remove(Runnable task) { removeCallbacks(task); }
            });
        renderer = new Thread(this::render, "eve-display-surface");
        renderer.setDaemon(true); renderer.start();
    }

    @Override public View view() { return this; }
    @Override public void setPointer(RfbView.Pointer value) { motion.cancel(); pointer = value; }
    @Override public void setPerformance(DisplayPerformance value) {
        performance = value;
        synchronized (lock) {
            epoch++;
            if (value != null) {
                value.surfaceRequested();
                value.surfaceInvalidated();
            }
            dirty = true; lock.notifyAll();
        }
    }
    @Override public void resize(int width, int height) {
        if (width < 1 || height < 1 || width > 4096 || height > 2160 || (long) width * height > 4194304)
            throw new IllegalArgumentException("Unsupported display dimensions");
        try {
            synchronized (lock) {
                if (disposed || failed || image != null && image.getWidth() == width && image.getHeight() == height) return;
                Bitmap replacement = allocator.create(width, height);
                if (image != null) image.recycle();
                if (completed != null) completed.recycle();
                image = replacement; completed = null; completedCanvas = null;
                epoch++; dirty = false; state();
            }
        } catch (OutOfMemoryError exhausted) { fail("framebuffer-allocation-failed"); return; }
        catch (RuntimeException rejected) { fail("framebuffer-allocation-failed"); return; }
        post(() -> {
            final int widthNow, heightNow;
            synchronized (lock) { if (disposed || image == null) return; widthNow = image.getWidth(); heightNow = image.getHeight(); }
            // Keep CPU copies at game resolution; the separate layer scales to its fitted View bounds.
            surface.getHolder().setFixedSize(widthNow, heightNow);
            requestLayout();
        });
    }
    @Override public void pixels(int x, int y, int width, int height, int[] argb) {
        synchronized (lock) { if (!disposed && !failed && image != null) image.setPixels(argb, 0, width, x, y, width, height); }
    }
    @Override public void updated() {
        DisplayPerformance measured = performance;
        long began = System.nanoTime();
        try {
            synchronized (lock) {
                if (disposed || failed || image == null) return;
                if (completed == null) {
                    completed = allocator.create(image.getWidth(), image.getHeight());
                    completedCanvas = new Canvas(completed);
                }
                // Snapshot only after every rectangle of this RFB update was decoded.
                completedCanvas.drawBitmap(image, 0, 0, null);
                completedVersion++;
                if (measured != null) {
                    measured.surfaceRequests.incrementAndGet();
                    if (dirty) measured.surfaceCoalesced.incrementAndGet();
                    measured.surfaceSnapshotNanos.addAndGet(System.nanoTime() - began);
                    measured.surfaceSnapshots.incrementAndGet();
                }
                dirty = true; lock.notifyAll();
            }
        } catch (OutOfMemoryError exhausted) { fail("snapshot-allocation-failed"); }
        catch (RuntimeException rejected) { fail("snapshot-copy-failed"); }
    }
    @Override public void resumePresentation() {
        synchronized (lock) { if (disposed) return; resumed = true; epoch++; dirty = true; state(); lock.notifyAll(); }
    }
    @Override public void pausePresentation() {
        synchronized (lock) { resumed = false; epoch++; state(); lock.notifyAll(); }
    }
    private void state() {
        DisplayPerformance measured = performance;
        if (measured != null) measured.surfaceInvalidated();
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        synchronized (lock) { if (disposed) return; surfaceReady = true; epoch++; dirty = true; state(); lock.notifyAll(); }
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        synchronized (lock) { if (disposed) return; surfaceReady = true; epoch++; dirty = true; state(); lock.notifyAll(); }
    }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        // No native canvas operation or renderer join occurs under this callback's lock.
        synchronized (lock) { surfaceReady = false; epoch++; state(); lock.notifyAll(); }
    }
    private void render() {
        RectF target = new RectF();
        while (true) {
            final long token;
            final DisplayPerformance measured;
            synchronized (lock) {
                while (!disposed && (!resumed || !surfaceReady || !dirty || completed == null || failed)) {
                    try { lock.wait(); } catch (InterruptedException cancelled) { return; }
                }
                if (disposed) return;
                dirty = false; token = epoch; measured = performance;
            }
            Canvas canvas = null;
            boolean drew = false, posted = false;
            long drawnVersion = 0;
            String error = null;
            try {
                long started = System.nanoTime();
                // BufferQueue may wait here. Never hold the framebuffer/lifecycle lock while it does.
                canvas = access.lock();
                if (measured != null) measured.surfaceLockNanos.addAndGet(System.nanoTime() - started);
                if (canvas == null) { error = "canvas-unavailable"; }
                else if (canvas.isHardwareAccelerated()) { error = "unexpected-hardware-canvas"; }
                else {
                    started = System.nanoTime();
                    // A stale lifecycle token still has to release a completely defined CPU buffer.
                    canvas.drawColor(Color.BLACK);
                    synchronized (lock) {
                        if (!disposed && !failed && resumed && surfaceReady && epoch == token && completed != null) {
                            // Fixed-size surface is normally one-to-one; retain complete pixels during resize transitions.
                            target.set(0, 0, canvas.getWidth(), canvas.getHeight());
                            canvas.drawBitmap(completed, null, target, null);
                            drew = true; drawnVersion = completedVersion;
                        }
                    }
                    if (measured != null) measured.surfaceDrawNanos.addAndGet(System.nanoTime() - started);
                }
            } catch (RuntimeException rejected) { error = "canvas-render-failed"; }
            finally {
                if (canvas != null) {
                    try {
                        long started = System.nanoTime();
                        // Always release an acquired canvas, including a stale pause/resize token.
                        access.post(canvas); posted = true;
                        if (measured != null) measured.surfacePostNanos.addAndGet(System.nanoTime() - started);
                    } catch (RuntimeException rejected) { error = "canvas-post-failed"; }
                }
            }
            synchronized (lock) {
                if (posted && drew && !disposed && !failed && resumed && surfaceReady && epoch == token && measured == performance) {
                    if (measured != null) measured.surfacePosted();
                    if (completedVersion == drawnVersion) dirty = false;
                }
                if (disposed) return;
                // A stale holder during a normal pause/resize is not an experimental failure.
                if (epoch != token || !resumed || !surfaceReady) error = null;
            }
            if (error != null) failCurrent(error, token);
        }
    }
    private void fail(String reason) {
        failCurrent(reason, -1);
    }
    private void failCurrent(String reason, long expectedEpoch) {
        synchronized (lock) {
            if (failed || disposed || expectedEpoch >= 0 && (epoch != expectedEpoch || !resumed || !surfaceReady)) return;
            failed = true; epoch++; state(); lock.notifyAll();
            if (completed != null) completed.recycle();
            completed = null; completedCanvas = null; dirty = false;
            DisplayPerformance measured = performance;
            if (measured != null) measured.surfaceFailed(reason);
        }
        post(() -> { synchronized (lock) { if (disposed) return; } failure.failed(this, reason); });
    }
    void transferTo(RfbView target) {
        synchronized (lock) {
            if (disposed) return;
            target.adoptImage(image); image = null;
        }
    }
    private void fit() {
        if (image == null) { destination.setEmpty(); return; }
        float scale = Math.min((float) getWidth() / image.getWidth(), (float) getHeight() / image.getHeight());
        float w = image.getWidth() * scale, h = image.getHeight() * scale;
        destination.set((getWidth() - w) / 2, (getHeight() - h) / 2, (getWidth() + w) / 2, (getHeight() + h) / 2);
    }
    @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        int x1, y1, x2, y2;
        synchronized (lock) {
            fit();
            x1 = destination.isEmpty() ? 0 : Math.round(destination.left);
            y1 = destination.isEmpty() ? 0 : Math.round(destination.top);
            x2 = destination.isEmpty() ? getWidth() : Math.round(destination.right);
            y2 = destination.isEmpty() ? getHeight() : Math.round(destination.bottom);
        }
        surface.layout(x1, y1, x2, y2);
    }
    private boolean position(float x, float y, boolean clamp) {
        synchronized (lock) {
            fit();
            if (image == null || destination.isEmpty() || (!clamp && !destination.contains(x, y))) return false;
            lastX = Math.max(0, Math.min(image.getWidth() - 1, (int) ((x - destination.left) * image.getWidth() / destination.width())));
            lastY = Math.max(0, Math.min(image.getHeight() - 1, (int) ((y - destination.top) * image.getHeight() / destination.height())));
            return true;
        }
    }
    private void edge(int mask) { motion.edge(lastX, lastY, mask); }
    @Override public boolean onTouchEvent(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (!position(event.getX(), event.getY(), false)) return false;
                touching = true; getParent().requestDisallowInterceptTouchEvent(true); edge(1); return true;
            case MotionEvent.ACTION_MOVE:
                if (!touching) return false;
                if (position(event.getX(), event.getY(), true)) motion.move(lastX, lastY, 1); return true;
            case MotionEvent.ACTION_UP:
                if (!touching) return false;
                position(event.getX(), event.getY(), true); touching = false; edge(0); performClick(); return true;
            case MotionEvent.ACTION_CANCEL:
                touching = false; edge(0); return true;
            default: return touching;
        }
    }
    @Override public boolean onHoverEvent(MotionEvent event) {
        if (!touching && position(event.getX(), event.getY(), false)) { motion.move(lastX, lastY, 0); return true; }
        return super.onHoverEvent(event);
    }
    @Override public boolean performClick() { super.performClick(); return true; }
    @Override public void releasePointer() { boolean held = touching; touching = false; motion.cancel(); if (held) edge(0); }
    @Override public void dispose() {
        releasePointer(); pointer = null;
        synchronized (lock) {
            disposed = true; resumed = false; surfaceReady = false; epoch++; state(); performance = null;
            if (image != null) image.recycle();
            if (completed != null) completed.recycle();
            image = null; completed = null; completedCanvas = null; dirty = false; lock.notifyAll();
        }
        surface.getHolder().removeCallback(this);
    }
}
