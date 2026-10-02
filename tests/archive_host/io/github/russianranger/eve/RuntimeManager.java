package io.github.russianranger.eve;

import java.io.InterruptedIOException;

/** The extractor's sole RuntimeManager dependency; no runtime logic is copied. */
final class RuntimeManager {
    static void cancelled() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) {
            throw new InterruptedIOException("Operation cancelled");
        }
    }
}
