package io.github.russianranger.eve;

import android.app.*;
import android.graphics.Color;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import java.io.File;
import java.io.IOException;
import java.net.*;
import java.util.concurrent.*;

/** Initial EVE startup/login display. RuntimeService continues owning the client session. */
public final class ClientDisplayActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Object socketLock = new Object();
    private final ThreadPoolExecutor input = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(128), task -> new Thread(task, "eve-display-input"), new ThreadPoolExecutor.AbortPolicy());
    private final ScheduledThreadPoolExecutor diagnostics = new ScheduledThreadPoolExecutor(1,
        task -> new Thread(task, "eve-display-diagnostics"));
    private static final Object performanceFileLock = new Object();
    private static long savedPerformanceId;
    private static boolean savedPerformanceEnded;
    private File performanceFile;
    private HandlerThread frameThread;
    private Window.OnFrameMetricsAvailableListener frameListener;
    private AlertDialog activeTextDialog;
    private volatile DisplayPerformance performance;
    private RfbView screen;
    private TextView status;
    private volatile Socket socket;
    private volatile RfbClient connection;
    private volatile boolean visible;
    private volatile long generation;
    private volatile boolean receivedFrame;
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.BLACK);
        root.setOnApplyWindowInsetsListener((view, insets) -> { root.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom()); return insets; });
        LinearLayout tools = new LinearLayout(this); tools.setBackgroundColor(0xff102334);
        button(tools, "Launcher", this::finish); button(tools, "Text", this::textEntry);
        button(tools, "Tab", () -> press(0xff09)); button(tools, "Enter", () -> press(0xff0d));
        button(tools, "Esc", () -> press(0xff1b)); button(tools, "Right click", () -> screen.rightClick());
        HorizontalScrollView bar = new HorizontalScrollView(this); bar.addView(tools); root.addView(bar);
        status = new TextView(this); status.setTextColor(0xff6ee4f0); status.setTextSize(12); status.setPadding(dp(8), dp(3), dp(8), dp(3));
        status.setText("Connecting to local client display…"); root.addView(status);
        screen = new RfbView(this); screen.setPointer((x, y, mask) -> submit(client -> client.pointer(x, y, mask)));
        root.addView(screen, new LinearLayout.LayoutParams(-1, 0, 1)); setContentView(root);
        performanceFile = new File(RuntimeManager.get(this).clientState, "logs/display-performance.json");
        diagnostics.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        diagnostics.setContinueExistingPeriodicTasksAfterShutdownPolicy(false);
        diagnostics.scheduleAtFixedRate(() -> persistPerformance(performance), 10, 10, TimeUnit.SECONDS);
        frameThread = new HandlerThread("eve-display-frame-metrics"); frameThread.start();
        frameListener = (window, frame, dropped) -> {
            DisplayPerformance measured = performance;
            if (measured != null && measured.active.get()) measured.frame(frame.getMetric(FrameMetrics.TOTAL_DURATION),
                frame.getMetric(FrameMetrics.DRAW_DURATION), frame.getMetric(FrameMetrics.SYNC_DURATION),
                Build.VERSION.SDK_INT >= 31 ? frame.getMetric(FrameMetrics.GPU_DURATION) : -1, dropped);
        };
        getWindow().addOnFrameMetricsAvailableListener(frameListener, new Handler(frameThread.getLooper()));
    }
    private void persistPerformance(DisplayPerformance measured) {
        if (measured == null) return;
        synchronized (performanceFileLock) {
            boolean ended = !measured.active.get();
            if (measured.id < savedPerformanceId || (measured.id == savedPerformanceId && savedPerformanceEnded && !ended)) return;
            try {
                RuntimeManager.text(performanceFile, measured.json(!ended));
                savedPerformanceId = measured.id; savedPerformanceEnded = ended;
            } catch (IOException ignored) { } // Diagnostics must not interrupt display or input.
        }
    }
    private void finishPerformance(DisplayPerformance measured) {
        if (measured == null) return;
        measured.finish();
        try { diagnostics.execute(() -> persistPerformance(measured)); }
        catch (RejectedExecutionException stopped) { }
    }
    private void button(LinearLayout tools, String title, Runnable action) {
        Button button = new Button(this); button.setText(title); button.setAllCaps(false);
        button.setTextColor(0xffeef8fa); button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff24516b));
        button.setOnClickListener(view -> action.run()); tools.addView(button, new LinearLayout.LayoutParams(-2, dp(44)));
    }
    private interface Input { void send(RfbClient client) throws IOException; }
    private void submit(Input action) {
        RfbClient target = connection; long token = generation;
        if (target == null || !visible) return;
        DisplayPerformance measured = performance; long enqueued = System.nanoTime();
        if (measured != null) measured.inputQueued(input.getQueue().size() + 1);
        try {
            input.execute(() -> {
                if (!visible || generation != token || connection != target) return;
                long started = System.nanoTime();
                if (measured != null) measured.inputStarted(started - enqueued);
                try { action.send(target); }
                catch (IOException error) { failedInput(target, token); }
                finally { if (measured != null) measured.inputFinished(System.nanoTime() - started); }
            });
        } catch (RejectedExecutionException saturated) {
            if (measured != null) measured.rejectedInputs.incrementAndGet();
            // Never silently drop a button release. Reconnect resets the pointer state.
            failedInput(target, token);
            input.getQueue().clear();
        }
    }
    private void press(int key) { submit(client -> client.tap(key)); }
    private void textEntry() {
        if (activeTextDialog != null) return;
        EditText text = new EditText(this);
        // Do not offer prediction or retain passwords in diagnostics.
        text.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        text.setSingleLine(true); text.setSaveEnabled(false); text.setFreezesText(false);
        text.setImeOptions(EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        text.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        CheckBox replace = new CheckBox(this); replace.setText("Replace selected field"); replace.setChecked(true);
        LinearLayout fields = new LinearLayout(this); fields.setOrientation(LinearLayout.VERTICAL); fields.setPadding(dp(16), 0, dp(16), 0);
        fields.addView(text); fields.addView(replace);
        activeTextDialog = new AlertDialog.Builder(this).setTitle("Send text to selected EVE field").setView(fields)
            .setPositiveButton("Send", (dialog, which) -> {
                String value = text.getText().toString(); text.setText("");
                if (value.length() > 4096) { Toast.makeText(this, "Send up to 4096 characters at once", Toast.LENGTH_SHORT).show(); return; }
                boolean replacing = replace.isChecked(); submit(client -> client.text(value, replacing));
            }).setNegativeButton("Cancel", (dialog, which) -> text.setText("")).create();
        activeTextDialog.setOnDismissListener(dialog -> { text.setText(""); activeTextDialog = null; });
        activeTextDialog.show();
    }
    private void displayStatus(long token, String message) { handler.post(() -> { if (visible && generation == token) status.setText(message); }); }
    private void failedInput(RfbClient target, long token) {
        synchronized (socketLock) { if (generation == token && connection == target) close(socket); }
    }
    private static void close(Socket current) { if (current != null) try { current.close(); } catch (IOException ignored) { } }
    private void disconnect() {
        final Socket previous;
        final RfbClient client;
        synchronized (socketLock) {
            visible = false; generation++; previous = socket; client = connection; socket = null; connection = null;
        }
        DisplayPerformance measured = performance; performance = null; screen.setPerformance(null); finishPerformance(measured);
        input.getQueue().clear();
        try { input.execute(() -> { try { if (client != null) client.pointer(0, 0, 0); } catch (IOException ignored) { } finally { close(previous); } }); }
        catch (RejectedExecutionException stopped) { close(previous); }
        // A blocked sender cannot retain a background display connection.
        handler.postDelayed(() -> close(previous), 250);
    }
    private void connect(long token) {
        long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(2);
        String previousError = "";
        while (visible && generation == token) {
            if (System.nanoTime() >= deadline) {
                displayStatus(token, "Display unavailable after two minutes · Return to Launcher and export support logs");
                RuntimeService.append(this, "Client display connection timed out");
                break;
            }
            Socket attempt = new Socket();
            DisplayPerformance measured = null;
            boolean connected = false;
            try {
                synchronized (socketLock) { if (!visible || generation != token) break; socket = attempt; }
                attempt.connect(new InetSocketAddress("127.0.0.1", 5907), 3000);
                attempt.setTcpNoDelay(true); attempt.setSoTimeout(15000);
                measured = new DisplayPerformance();
                RfbClient client = new RfbClient(attempt.getInputStream(), attempt.getOutputStream(), new RfbClient.Screen() {
                    @Override public void resize(int width, int height) { if (generation == token) screen.resize(width, height); }
                    @Override public void pixels(int x, int y, int width, int height, int[] pixels) { if (generation == token) screen.pixels(x, y, width, height, pixels); }
                    @Override public void updated() {
                        if (generation != token) return;
                        screen.updated();
                        if (!receivedFrame) { receivedFrame = true; displayStatus(token, "Local display connected · touch to click · use Text for login fields"); }
                    }
                }, measured);
                client.handshake();
                if (!visible || generation != token) break;
                receivedFrame = false;
                client.pointer(0, 0, 0);
                synchronized (socketLock) {
                    if (!visible || generation != token) break;
                    connection = client; performance = measured; screen.setPerformance(measured);
                }
                attempt.setSoTimeout(0);
                connected = true;
                RuntimeService.append(this, "Client display connected on loopback port 5907");
                displayStatus(token, "Display connected; waiting for first frame…");
                while (visible && generation == token) client.readUpdate();
            } catch (IOException | RuntimeException error) {
                if (visible && generation == token) {
                    if (connected) deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(2);
                    String detail = error.getMessage() == null ? "connection closed" : error.getMessage();
                    displayStatus(token, "Waiting for local client display · " + detail + " · Return to Launcher for logs");
                    if (!detail.equals(previousError)) { RuntimeService.append(this, "Client display connection: " + detail); previousError = detail; }
                }
            } finally {
                try { attempt.close(); } catch (IOException ignored) { }
                synchronized (socketLock) {
                    if (generation == token) { connection = null; socket = null; performance = null; screen.setPerformance(null); }
                }
                finishPerformance(measured);
            }
            if (!visible || generation != token) break;
            try { Thread.sleep(1500); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); break; }
        }
    }
    @Override public void onResume() {
        super.onResume(); final long token;
        synchronized (socketLock) { visible = true; receivedFrame = false; token = ++generation; }
        new Thread(() -> connect(token), "eve-display-reader").start();
    }
    @Override public void onPause() {
        if (activeTextDialog != null) activeTextDialog.dismiss();
        screen.releasePointer(); disconnect();
        super.onPause();
    }
    @Override public void onDestroy() {
        disconnect(); input.shutdown(); screen.dispose();
        getWindow().removeOnFrameMetricsAvailableListener(frameListener); frameThread.quitSafely(); diagnostics.shutdown();
        super.onDestroy();
    }
    private int keysym(KeyEvent event) {
        switch (event.getKeyCode()) {
            case KeyEvent.KEYCODE_ENTER: return 0xff0d;
            case KeyEvent.KEYCODE_TAB: return 0xff09;
            case KeyEvent.KEYCODE_DEL: return 0xff08;
            case KeyEvent.KEYCODE_FORWARD_DEL: return 0xffff;
            case KeyEvent.KEYCODE_ESCAPE: return 0xff1b;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 0xff51;
            case KeyEvent.KEYCODE_DPAD_UP: return 0xff52;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 0xff53;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 0xff54;
            default: int code = event.getUnicodeChar(); return code == 0 ? 0 : code <= 255 ? code : 0x01000000 | code;
        }
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (activeTextDialog != null || !hasWindowFocus()) return super.dispatchKeyEvent(event);
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK) return super.dispatchKeyEvent(event);
        int key = keysym(event);
        if (key != 0 && (event.getAction() == KeyEvent.ACTION_DOWN || event.getAction() == KeyEvent.ACTION_UP)) {
            if (event.getAction() == KeyEvent.ACTION_DOWN) press(key);
            return true;
        }
        return super.dispatchKeyEvent(event);
    }
}
