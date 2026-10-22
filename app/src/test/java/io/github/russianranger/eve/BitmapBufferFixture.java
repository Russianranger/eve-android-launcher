package io.github.russianranger.eve;

import android.graphics.Bitmap;
import java.nio.ByteBuffer;

/** Native copy/presentation fixtures use the test platform's actual byte layout. */
final class BitmapBufferFixture {
    private BitmapBufferFixture() { }
    static ByteBuffer pixels(int width, int height, int[] colors) {
        Bitmap reference = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888, false);
        try {
            reference.setPixels(colors, 0, width, 0, 0, width, height);
            // Robolectric's Linux native Skia uses BGRA, unlike Android's RGBA
            // buffer contract. These fixtures test bulk publication and drawing;
            // RFB host fixtures check exact wire RGBA, and startup qualification
            // rejects any platform that fails the real RGB/opaque-padding probe.
            ByteBuffer nativePixels = ByteBuffer.allocate(reference.getByteCount());
            reference.copyPixelsToBuffer(nativePixels); nativePixels.rewind();
            return nativePixels;
        } finally { reference.recycle(); }
    }
}
