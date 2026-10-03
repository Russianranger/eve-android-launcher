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
    private int lastX, lastY;
    private boolean touching;

    RfbView(Context context) { super(context); setBackgroundColor(Color.BLACK); setFocusable(true); }
    void setPointer(Pointer value) { pointer = value; }
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
        super.onDraw(canvas);
        synchronized (lock) { fit(); if (image != null) canvas.drawBitmap(image, null, destination, paint); }
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
    void dispose() { synchronized (lock) { if (image != null) { image.recycle(); image = null; } } }
}
