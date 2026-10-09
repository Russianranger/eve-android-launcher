package io.github.russianranger.eve;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.view.MotionEvent;
import android.view.SurfaceView;
import android.widget.FrameLayout;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.util.ReflectionHelpers;
import static org.junit.Assert.*;

/** Native Android CPU bitmap/canvas behavior with controlled BufferQueue wait/failure boundaries. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {33, 35})
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public final class RfbSurfaceViewTest {
    private static final class Access implements RfbSurfaceView.SurfaceAccess {
        final Bitmap buffer = Bitmap.createBitmap(3, 2, Bitmap.Config.ARGB_8888, false);
        final BlockingQueue<int[]> frames = new LinkedBlockingQueue<>();
        final CountDownLatch lockEntered = new CountDownLatch(1), postEntered = new CountDownLatch(1);
        volatile CountDownLatch lockGate = new CountDownLatch(0), postGate = new CountDownLatch(0);
        volatile boolean rejectLock, rejectPost;
        final AtomicInteger locks = new AtomicInteger();
        public Canvas lock() {
            locks.incrementAndGet(); lockEntered.countDown(); await(lockGate);
            if (rejectLock) throw new IllegalStateException("injected canvas lock failure");
            return new Canvas(buffer);
        }
        public void post(Canvas canvas) {
            postEntered.countDown(); await(postGate);
            if (rejectPost) throw new IllegalStateException("injected post failure");
            int[] pixels = new int[6]; buffer.getPixels(pixels, 0, 3, 0, 0, 3, 2); frames.add(pixels);
        }
        static void await(CountDownLatch latch) {
            try { assertTrue("Controlled worker boundary released", latch.await(5, TimeUnit.SECONDS)); }
            catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
        }
        int[] frame() throws Exception {
            int[] result = frames.poll(5, TimeUnit.SECONDS); assertNotNull("The worker posted a frame", result); return result;
        }
    }
    private static final class Fixture implements AutoCloseable {
        final Access access = new Access();
        final DisplayPerformance performance = new DisplayPerformance();
        final BlockingQueue<String> failures = new LinkedBlockingQueue<>();
        final RfbSurfaceView display;
        int verifiedFrames;
        Fixture() { this(null); }
        Fixture(RfbSurfaceView.BitmapFactory allocator) {
            Context context = RuntimeEnvironment.getApplication();
            display = allocator == null ? new RfbSurfaceView(context, (source, reason) -> failures.add(reason), access)
                : new RfbSurfaceView(context, (source, reason) -> failures.add(reason), access, allocator);
            display.setPerformance(performance); display.resize(3, 2);
            FrameLayout parent = new FrameLayout(context); parent.addView(display); display.layout(0, 0, 12, 8);
        }
        void start() { display.surfaceCreated(null); display.surfaceChanged(null, PixelFormat.RGBX_8888, 3, 2); display.resumePresentation(); }
        void pixel(int color) { display.pixels(1, 1, 1, 1, new int[]{color}); display.updated(); }
        JSONObject receipt() throws Exception { return new JSONObject(performance.json()); }
        int[] frame() throws Exception {
            int[] result = access.frame(); int expected = ++verifiedFrames;
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (performance.surfacePosts.get() < expected && System.nanoTime() < deadline) Thread.yield();
            assertTrue("Receipt follows a successful native post", performance.surfacePosts.get() >= expected); return result;
        }
        public void close() throws Exception {
            display.dispose(); access.lockGate.countDown(); access.postGate.countDown();
            Thread worker = ReflectionHelpers.getField(display, "renderer"); worker.join(3000);
            assertFalse("Disposed worker terminates after its native boundary returns", worker.isAlive()); access.buffer.recycle();
        }
    }
    @Test public void separateSurfacePreservesFullRgbAndCompletedPartialUpdates() throws Exception {
        try (Fixture f = new Fixture()) {
            SurfaceView child = ReflectionHelpers.getField(f.display, "surface");
            assertNull("The SurfaceView has no background covering its punch-through hole", child.getBackground());
            // Robolectric intercepts getHolder(): its fake owns the requested format, not SurfaceView's private field.
            assertEquals(PixelFormat.RGBX_8888, Shadows.shadowOf(child).getFakeSurfaceHolder().getRequestedFormat());
            f.pixel(0xff123456); f.start(); int[] first = f.frame();
            assertEquals(0xff123456, first[4]); assertEquals(Color.BLACK, first[0]);
            f.pixel(0xffabcdef); int[] second = f.frame(); assertEquals(0xffabcdef, second[4]);
            Bitmap source = ReflectionHelpers.getField(f.display, "image"), snapshot = ReflectionHelpers.getField(f.display, "completed");
            assertFalse(source.hasAlpha()); assertFalse(snapshot.hasAlpha());
            f.display.resize(3, 2); assertSame(source, ReflectionHelpers.getField(f.display, "image"));
            assertTrue(f.receipt().getBoolean("separate_surface_activation_verified"));
            assertEquals("app-ui-window-only", f.receipt().getString("android_frame_metrics_scope"));
        }
    }
    @Test public void blockedCanvasCoalescesLatestCompletedFrameAndDoesNotBlockPixels() throws Exception {
        try (Fixture f = new Fixture()) {
            f.access.lockGate = new CountDownLatch(1); f.pixel(0xff111111); f.start();
            assertTrue(f.access.lockEntered.await(5, TimeUnit.SECONDS));
            f.pixel(0xff222222); f.pixel(0xff333333); f.pixel(0xffabcdef);
            assertEquals("No claimed activation before a successful post", 0, f.performance.surfacePosts.get());
            assertTrue(f.performance.surfaceCoalesced.get() >= 2);
            f.access.lockGate.countDown(); assertEquals(0xffabcdef, f.frame()[4]);
            // All changes before the draw are consumed by that latest snapshot, with no queued old frames.
            assertNull(f.access.frames.poll(200, TimeUnit.MILLISECONDS));
        }
    }
    @Test public void pauseInvalidatesPendingFrameAndResumeNeedsANewVerifiedPost() throws Exception {
        try (Fixture f = new Fixture()) {
            f.pixel(0xff3984cf); f.start(); f.frame();
            assertTrue(f.receipt().getBoolean("separate_surface_active"));
            f.display.pausePresentation(); assertFalse(f.receipt().getBoolean("separate_surface_active"));
            f.access.lockGate = new CountDownLatch(1);
            f.display.resumePresentation();
            assertFalse("Historical activation cannot qualify a resumed holder", f.receipt().getBoolean("separate_surface_active"));
            f.access.lockGate.countDown(); assertEquals(0xff3984cf, f.frame()[4]);
        }
    }
    @Test public void surfaceRecreationKeepsPixelsButInvalidatesCurrentActivation() throws Exception {
        try (Fixture f = new Fixture()) {
            f.pixel(0xff6398de); f.start(); f.frame();
            f.display.surfaceDestroyed(null);
            f.access.lockGate = new CountDownLatch(1); f.display.surfaceCreated(null);
            assertTrue(f.receipt().getBoolean("separate_surface_activation_verified"));
            assertFalse(f.receipt().getBoolean("separate_surface_active"));
            f.access.lockGate.countDown(); assertEquals(0xff6398de, f.frame()[4]);
        }
    }
    @Test public void destroyDuringNativeLockRecyclesBitmapsAndRejectsLateCallbacks() throws Exception {
        try (Fixture f = new Fixture()) {
            f.access.lockGate = new CountDownLatch(1); f.pixel(0xffabcdef); f.start();
            assertTrue(f.access.lockEntered.await(5, TimeUnit.SECONDS));
            Bitmap source = ReflectionHelpers.getField(f.display, "image"), snapshot = ReflectionHelpers.getField(f.display, "completed");
            f.display.dispose(); assertTrue(source.isRecycled()); assertTrue(snapshot.isRecycled());
            f.display.resize(1280, 720); f.display.pixels(0, 0, 1, 1, new int[]{Color.RED}); f.display.updated();
            f.display.surfaceCreated(null); f.display.resumePresentation();
            assertNull(ReflectionHelpers.getField(f.display, "image"));
            f.access.lockGate.countDown();
            int[] stale = f.access.frame(); for (int color : stale) assertEquals("Stale canvas is fully opaque black", Color.BLACK, color);
            assertEquals(0, f.performance.surfacePosts.get());
        }
    }
    @Test public void blockedPostDoesNotHoldFramebufferLockOrCountStaleConnection() throws Exception {
        try (Fixture f = new Fixture()) {
            f.access.postGate = new CountDownLatch(1); f.pixel(0xffabcdef); f.start();
            assertTrue(f.access.postEntered.await(5, TimeUnit.SECONDS));
            f.pixel(0xff123456); f.display.pausePresentation(); f.display.setPerformance(null);
            f.access.postGate.countDown(); f.access.frame();
            assertEquals("Old connection does not claim an activation after pause", 0, f.performance.surfacePosts.get());
        }
    }
    @Test public void rejectedCanvasPostRecordsFailureAndTransfersFramebufferWithoutAnotherAllocation() throws Exception {
        try (Fixture f = new Fixture()) {
            f.access.rejectPost = true; f.pixel(0xff3859ac); f.start();
            assertTrue(f.access.postEntered.await(5, TimeUnit.SECONDS));
            // The reason is recorded on the worker before its main-thread fallback callback.
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (f.performance.surfaceFailures.get() == 0 && System.nanoTime() < deadline) Thread.yield();
            assertEquals(1, f.performance.surfaceFailures.get()); assertEquals(0, f.performance.surfacePosts.get());
            Bitmap image = ReflectionHelpers.getField(f.display, "image");
            assertNull("The failed completed snapshot releases its memory", ReflectionHelpers.getField(f.display, "completed"));
            RfbView original = new RfbView(RuntimeEnvironment.getApplication());
            f.display.transferTo(original);
            assertSame(image, ReflectionHelpers.getField(original, "image")); assertEquals(0xff3859ac, image.getPixel(1, 1));
            assertNull(ReflectionHelpers.getField(f.display, "image"));
            f.performance.surfaceFallback("canvas-post-failed");
            assertEquals("One native failure isn't counted again by fallback", 1, f.performance.surfaceFailures.get());
            assertEquals("bitmap-fallback", f.receipt().getString("presentation_mode")); original.dispose();
        }
    }
    @Test public void rejectedResizeRetainsOldImageForSafeFallback() throws Exception {
        AtomicInteger allocations = new AtomicInteger();
        try (Fixture f = new Fixture((width, height) -> {
            if (allocations.incrementAndGet() == 3) throw new OutOfMemoryError("injected resize rejection");
            return Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888, false);
        })) {
            f.pixel(0xff98acdf); Bitmap previous = ReflectionHelpers.getField(f.display, "image");
            f.display.resize(4, 3);
            assertSame(previous, ReflectionHelpers.getField(f.display, "image")); assertFalse(previous.isRecycled());
            // Pixels from the failed larger RFB desktop are ignored until fallback reconnects at the new size.
            f.display.pixels(3, 2, 1, 1, new int[]{Color.RED}); f.display.updated();
            assertEquals("framebuffer-allocation-failed", f.receipt().getString("surface_failure"));
            RfbView replacement = new RfbView(RuntimeEnvironment.getApplication()); f.display.transferTo(replacement);
            assertSame(previous, ReflectionHelpers.getField(replacement, "image")); replacement.dispose();
        }
    }
    @Test public void snapshotAllocationFailureRetainsRgbForFallback() throws Exception {
        AtomicInteger allocations = new AtomicInteger();
        try (Fixture f = new Fixture((width, height) -> {
            if (allocations.incrementAndGet() == 2) throw new OutOfMemoryError("injected snapshot rejection");
            return Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888, false);
        })) {
            f.pixel(0xff123abc);
            assertEquals("snapshot-allocation-failed", f.receipt().getString("surface_failure"));
            Bitmap retained = ReflectionHelpers.getField(f.display, "image"); assertEquals(0xff123abc, retained.getPixel(1, 1));
            assertNull(ReflectionHelpers.getField(f.display, "completed"));
        }
    }
    @Test public void fittedSeparateLayerKeepsLetterboxTouchCoordinatesAndCancelRelease() throws Exception {
        try (Fixture f = new Fixture()) {
            f.display.layout(0, 0, 20, 8); // 3:2 image fits at x=4..16; side bars reject clicks.
            SurfaceView child = ReflectionHelpers.getField(f.display, "surface"); assertEquals(4, child.getLeft()); assertEquals(16, child.getRight());
            List<int[]> events = new ArrayList<>(); f.display.setPointer((x, y, mask) -> events.add(new int[]{x, y, mask}));
            MotionEvent outside = MotionEvent.obtain(0, 0, MotionEvent.ACTION_DOWN, 1, 4, 0);
            try { assertFalse(f.display.onTouchEvent(outside)); } finally { outside.recycle(); }
            MotionEvent down = MotionEvent.obtain(0, 1, MotionEvent.ACTION_DOWN, 12, 6, 0);
            try { assertTrue(f.display.onTouchEvent(down)); } finally { down.recycle(); }
            assertArrayEquals(new int[]{2, 1, 1}, events.get(0)); f.display.releasePointer();
            assertArrayEquals(new int[]{2, 1, 0}, events.get(1));
        }
    }
}
