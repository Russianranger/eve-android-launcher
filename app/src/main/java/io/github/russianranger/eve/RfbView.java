package io.github.russianranger.eve;

import android.content.Context;
import android.graphics.*;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;
import java.nio.ByteBuffer;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Fit the local framebuffer to the screen and forward ordinary touch clicks/drags. */
final class RfbView extends FrameLayout implements RfbClient.Screen, SurfaceHolder.Callback {
    interface Pointer { void send(int x, int y, int mask); }
    private final Object lock = new Object();
    private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final RectF destination = new RectF();
    private final View legacy;
    private final SurfaceView surface;
    private final ExecutorService renderer = Executors.newSingleThreadExecutor(task -> new Thread(task, "eve-display-surface"));
    private final AtomicBoolean queued = new AtomicBoolean();
    private Bitmap image;
    private volatile Pointer pointer;
    private volatile Runnable frameListener;
    private volatile boolean surfaceMode, surfaceReady, disposed;
    private long frameVersion, drawnVersion;
    private int lastX, lastY;
    private boolean touching;

    RfbView(Context context) {
        super(context); setBackgroundColor(Color.BLACK); setFocusable(true);
        legacy = new View(context) {
            @Override protected void onDraw(Canvas canvas) {
                super.onDraw(canvas);
                long version;
                synchronized (lock) { version = drawFrame(canvas); }
                presented(version);
            }
        };
        surface = new SurfaceView(context); surface.getHolder().addCallback(this);
        addView(legacy, new LayoutParams(-1, -1)); addView(surface, new LayoutParams(-1, -1));
        surface.setVisibility(GONE);
    }
    /** Check native Bitmap byte order and opaque padding handling before RFB negotiation. */
    static boolean directPixelsSupported() {
        Bitmap source = null, target = null;
        try {
            source = Bitmap.createBitmap(3, 1, Bitmap.Config.ARGB_8888);
            source.setHasAlpha(false);
            source.copyPixelsFromBuffer(ByteBuffer.wrap(new byte[]{
                (byte) 255,0,0,0, 0,(byte) 255,0,(byte) 254, 0,0,(byte) 255,0}));
            target = Bitmap.createBitmap(3, 1, Bitmap.Config.ARGB_8888);
            target.setHasAlpha(false); target.eraseColor(Color.BLACK);
            new Canvas(target).drawBitmap(source, 0, 0, null);
            return target.getPixel(0, 0) == Color.RED && target.getPixel(1, 0) == Color.GREEN
                && target.getPixel(2, 0) == Color.BLUE;
        } catch (RuntimeException | OutOfMemoryError unavailable) {
            return false;
        } finally {
            if (source != null) source.recycle();
            if (target != null) target.recycle();
        }
    }
    void setDisplayMode(boolean useSurface) {
        surfaceMode = useSurface;
        legacy.setVisibility(useSurface ? GONE : VISIBLE); surface.setVisibility(useSurface ? VISIBLE : GONE);
        updatedPresentation();
    }
    void setFrameListener(Runnable listener) { frameListener = listener; }
    void setPointer(Pointer value) { pointer = value; }
    @Override public void resize(int width, int height) {
        synchronized (lock) {
            if (disposed || (image != null && image.getWidth() == width && image.getHeight() == height)) return;
            if (image != null) image.recycle();
            image = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            // RFB's fourth byte is unused padding, not alpha. Copy wire bytes without
            // converting each pixel and tell Canvas to treat the bitmap as opaque.
            image.setHasAlpha(false); image.eraseColor(Color.BLACK);
        }
        updatedPresentation();
    }
    @Override public void pixels(int x, int y, int width, int height, int[] argb) {
        synchronized (lock) { if (image != null) image.setPixels(argb, 0, width, x, y, width, height); }
    }
    @Override public void pixels(int width, int height, ByteBuffer rgba) {
        synchronized (lock) {
            if (image != null && image.getWidth() == width && image.getHeight() == height) image.copyPixelsFromBuffer(rgba);
        }
    }
    @Override public void updated() {
        synchronized (lock) { frameVersion++; }
        updatedPresentation();
    }
    private void updatedPresentation() {
        if (disposed) return;
        if (surfaceMode) scheduleSurface();
        else legacy.postInvalidateOnAnimation();
    }
    private void scheduleSurface() {
        if (disposed || !surfaceMode || !surfaceReady || !queued.compareAndSet(false, true)) return;
        try { renderer.execute(() -> {
            long version = 0;
            try {
                if (disposed || !surfaceMode || !surfaceReady) return;
                SurfaceHolder holder = surface.getHolder();
                Canvas canvas = holder.lockCanvas();
                if (canvas != null) {
                    try { synchronized (lock) { version = drawFrame(canvas); } }
                    finally { holder.unlockCanvasAndPost(canvas); }
                    presented(version);
                }
            } catch (RuntimeException unavailable) {
                // Surface recreation can race lockCanvas. The next surface callback
                // or framebuffer update retries; no frame is counted as drawn here.
            } finally {
                queued.set(false);
                boolean pending;
                synchronized (lock) { pending = frameVersion > version && frameVersion > drawnVersion; }
                if (pending) {
                    if (version > 0) scheduleSurface();
                    else postDelayed(this::scheduleSurface, 50);
                }
            }
        }); } catch (RejectedExecutionException stopped) { queued.set(false); }
    }
    private long drawFrame(Canvas canvas) {
        canvas.drawColor(Color.BLACK); fit();
        if (image == null || disposed) return 0;
        canvas.drawBitmap(image, null, destination, paint);
        return frameVersion;
    }
    private void presented(long version) {
        Runnable listener;
        synchronized (lock) {
            if (version == 0 || version <= drawnVersion || disposed) return;
            drawnVersion = version; listener = frameListener;
        }
        if (listener != null) listener.run();
    }
    @Override public void surfaceCreated(SurfaceHolder holder) { surfaceReady = true; scheduleSurface(); }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { scheduleSurface(); }
    @Override public void surfaceDestroyed(SurfaceHolder holder) { surfaceReady = false; }
    private void fit() {
        if (image == null) { destination.setEmpty(); return; }
        float scale = Math.min((float) getWidth() / image.getWidth(), (float) getHeight() / image.getHeight());
        float w = image.getWidth() * scale, h = image.getHeight() * scale;
        destination.set((getWidth() - w) / 2, (getHeight() - h) / 2, (getWidth() + w) / 2, (getHeight() + h) / 2);
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
    private void send(int mask) { Pointer target = pointer; if (target != null) target.send(lastX, lastY, mask); }
    @Override public boolean onTouchEvent(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (!position(event.getX(), event.getY(), false)) return false;
                touching = true; getParent().requestDisallowInterceptTouchEvent(true); send(1); return true;
            case MotionEvent.ACTION_MOVE:
                if (!touching) return false;
                if (position(event.getX(), event.getY(), true)) send(1); return true;
            case MotionEvent.ACTION_UP:
                if (!touching) return false;
                position(event.getX(), event.getY(), true); touching = false; send(0); performClick(); return true;
            case MotionEvent.ACTION_CANCEL:
                touching = false; send(0); return true;
            default: return touching;
        }
    }
    @Override public boolean onHoverEvent(MotionEvent event) {
        if (position(event.getX(), event.getY(), false)) { send(0); return true; }
        return super.onHoverEvent(event);
    }
    @Override public boolean performClick() { super.performClick(); return true; }
    void rightClick() { send(4); send(0); }
    void releasePointer() { touching = false; send(0); }
    void dispose() {
        disposed = true; renderer.shutdown();
        synchronized (lock) { if (image != null) { image.recycle(); image = null; } }
    }
}
