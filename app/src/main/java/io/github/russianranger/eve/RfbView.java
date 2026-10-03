package io.github.russianranger.eve;

import android.content.Context;
import android.graphics.*;
import android.view.MotionEvent;
import android.view.View;

/** Fit the local framebuffer to the screen and forward ordinary touch clicks/drags. */
final class RfbView extends View implements RfbClient.Screen {
    interface Pointer { void send(int x, int y, int mask); }
    private final Object lock = new Object();
    private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final RectF destination = new RectF();
    private Bitmap image;
    private volatile Pointer pointer;
    private volatile DisplayPerformance performance;
    private final PointerMotion motion;
    private int lastX, lastY;
    private boolean touching;

    RfbView(Context context) {
        super(context); setBackgroundColor(Color.BLACK); setFocusable(true);
        motion = new PointerMotion((x, y, mask) -> { Pointer target = pointer; if (target != null) target.send(x, y, mask); },
            new PointerMotion.Scheduler() {
                @Override public void post(Runnable task) { postOnAnimation(task); }
                @Override public void remove(Runnable task) { removeCallbacks(task); }
            });
    }
    void setPointer(Pointer value) { motion.cancel(); pointer = value; }
    void setPerformance(DisplayPerformance value) { performance = value; }
    @Override public void resize(int width, int height) {
        synchronized (lock) {
            if (image != null && image.getWidth() == width && image.getHeight() == height) return;
            if (image != null) image.recycle();
            image = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        }
        postInvalidate();
    }
    @Override public void pixels(int x, int y, int width, int height, int[] argb) {
        synchronized (lock) { if (image != null) image.setPixels(argb, 0, width, x, y, width, height); }
    }
    @Override public void updated() { postInvalidateOnAnimation(); }
    private void fit() {
        if (image == null) { destination.setEmpty(); return; }
        float scale = Math.min((float) getWidth() / image.getWidth(), (float) getHeight() / image.getHeight());
        float w = image.getWidth() * scale, h = image.getHeight() * scale;
        destination.set((getWidth() - w) / 2, (getHeight() - h) / 2, (getWidth() + w) / 2, (getHeight() + h) / 2);
    }
    @Override protected void onDraw(Canvas canvas) {
        long started = System.nanoTime(); DisplayPerformance measured = performance;
        super.onDraw(canvas);
        synchronized (lock) { fit(); if (image != null) canvas.drawBitmap(image, null, destination, paint); }
        if (measured != null) { measured.draws.incrementAndGet(); measured.drawNanos.addAndGet(System.nanoTime() - started); }
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
    void rightClick() { touching = false; edge(4); edge(0); }
    void releasePointer() { touching = false; edge(0); }
    void dispose() { motion.cancel(); pointer = null; performance = null; synchronized (lock) { if (image != null) { image.recycle(); image = null; } } }
}
