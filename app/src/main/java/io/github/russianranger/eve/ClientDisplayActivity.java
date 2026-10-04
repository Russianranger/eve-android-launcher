package io.github.russianranger.eve;

import android.app.*;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.content.res.ColorStateList;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import java.io.File;
import java.io.IOException;
import java.net.*;
import java.util.concurrent.*;

/** Fullscreen EVE display and layered controls. RuntimeService owns the client session. */
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
    private TextView status, layerBanner, layerStatus;
    private FrameLayout menuLayer;
    private LinearLayout menu;
    private ImageButton gear;
    private ControllerManager controller;
    private DisplayInput gameInput;
    private PointerMotion pointerMotion;
    private AlertDialog mappingDialog;
    private boolean menuOpen, mappingsOpen;
    private int pointerMask;
    private final Runnable hideLayer = () -> { if (layerBanner != null) layerBanner.setVisibility(View.GONE); };
    private volatile Socket socket;
    private volatile RfbClient connection;
    private volatile boolean visible;
    private volatile long generation;
    private volatile boolean receivedFrame;
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        fullscreen();
        FrameLayout root = new FrameLayout(this); root.setBackgroundColor(Color.BLACK);
        screen = new RfbView(this);
        root.addView(screen, new FrameLayout.LayoutParams(-1, -1));
        pointerMotion = new PointerMotion((x, y, mask) -> submit(client -> client.pointer(x, y, mask)),
            new PointerMotion.Scheduler() {
                public void post(Runnable task) { screen.postOnAnimation(task); }
                public void remove(Runnable task) { screen.removeCallbacks(task); }
            });
        gameInput = new DisplayInput(new DisplayInput.Sink() {
            public void key(int symbol, boolean down) { submit(client -> client.key(symbol, down)); }
            public void pointer(int x, int y, int mask) {
                if (mask != pointerMask) { pointerMask = mask; pointerMotion.edge(x, y, mask); }
                else pointerMotion.move(x, y, mask);
            }
        });
        screen.setPointer((x, y, mask) -> { if (gameInputActive()) gameInput.touch(x, y, mask); });
        status = new TextView(this); status.setTextColor(0xff6ee4f0); status.setTextSize(12);
        status.setPadding(dp(12), dp(6), dp(12), dp(6)); status.setBackground(panel(0xc0081728));
        status.setText("Connecting to local client display…");
        FrameLayout.LayoutParams statusPosition = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        statusPosition.topMargin = dp(12); root.addView(status, statusPosition);
        layerBanner = new TextView(this); layerBanner.setTextColor(0xffeafcff); layerBanner.setTextSize(15);
        layerBanner.setPadding(dp(18), dp(8), dp(18), dp(8)); layerBanner.setBackground(panel(0xb0092036));
        layerBanner.setVisibility(View.GONE);
        FrameLayout.LayoutParams bannerPosition = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        bannerPosition.topMargin = dp(12); root.addView(layerBanner, bannerPosition);
        menuLayer = new FrameLayout(this); menuLayer.setBackgroundColor(0x80030b17); menuLayer.setVisibility(View.GONE);
        menuLayer.setOnClickListener(view -> setMenuOpen(false)); root.addView(menuLayer, new FrameLayout.LayoutParams(-1, -1));
        menu = new LinearLayout(this); menu.setOrientation(LinearLayout.VERTICAL); menu.setPadding(dp(14), dp(10), dp(14), dp(14));
        menu.setBackground(panel(0xf009192d)); menu.setOnClickListener(view -> { });
        TextView title = new TextView(this); title.setText("EVE / FLIGHT CONTROLS"); title.setTextColor(0xff6ee4f0);
        title.setTextSize(16); title.setPadding(0, dp(6), 0, dp(8)); menu.addView(title);
        layerStatus = new TextView(this); layerStatus.setTextColor(0xffc6e9f4); layerStatus.setTextSize(13); menu.addView(layerStatus);
        button(menu, "Back to client", () -> setMenuOpen(false));
        button(menu, "Next controller layer", () -> controller.nextLayer());
        button(menu, "Controller mappings", this::controllerMappings);
        button(menu, "Text entry", this::textEntry);
        button(menu, "Tab", () -> menuKey(0xff09)); button(menu, "Enter", () -> menuKey(0xff0d));
        button(menu, "Esc", () -> menuKey(0xff1b));
        button(menu, "Right click", () -> { setMenuOpen(false); gameInput.mouse("menu-right", 4, true); gameInput.mouse("menu-right", 4, false); });
        button(menu, "Launcher", this::finish);
        ScrollView menuScroll = new ScrollView(this); menuScroll.setFillViewport(false); menuScroll.addView(menu);
        FrameLayout.LayoutParams menuPosition = new FrameLayout.LayoutParams(Math.min(dp(340), getResources().getDisplayMetrics().widthPixels - dp(32)), -1, Gravity.TOP | Gravity.RIGHT);
        menuPosition.setMargins(dp(12), dp(68), dp(12), dp(12)); menuLayer.addView(menuScroll, menuPosition);
        gear = new ImageButton(this); gear.setImageResource(R.drawable.ic_client_gear); gear.setPadding(dp(8), dp(8), dp(8), dp(8));
        gear.setContentDescription("Open flight controls"); gear.setTooltipText("Flight controls");
        gear.setBackground(new RippleDrawable(ColorStateList.valueOf(0x556ee4f0), panel(0xb009192d), null));
        gear.setOnClickListener(view -> setMenuOpen(!menuOpen));
        FrameLayout.LayoutParams gearPosition = new FrameLayout.LayoutParams(dp(48), dp(48), Gravity.TOP | Gravity.RIGHT);
        gearPosition.setMargins(dp(12), dp(12), dp(12), 0); root.addView(gear, gearPosition);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            int left = 0, top = 0, right = 0, bottom = 0;
            if (Build.VERSION.SDK_INT >= 28 && insets.getDisplayCutout() != null) {
                left = insets.getDisplayCutout().getSafeInsetLeft(); top = insets.getDisplayCutout().getSafeInsetTop();
                right = insets.getDisplayCutout().getSafeInsetRight(); bottom = insets.getDisplayCutout().getSafeInsetBottom();
            }
            gearPosition.setMargins(dp(12) + left, dp(12) + top, dp(12) + right, 0); gear.setLayoutParams(gearPosition);
            menuPosition.setMargins(dp(12) + left, dp(68) + top, dp(12) + right, dp(12) + bottom); menuScroll.setLayoutParams(menuPosition);
            return insets;
        });
        setContentView(root);
        controller = new ControllerManager(this, RuntimeManager.get(this).clientState, event -> {
            switch (event.optString("type")) {
                case "button":
                    if (event.optString("action").equals("ClientMenu")) { if (event.optBoolean("down")) setMenuOpen(true); }
                    else gameInput.action(event.optString("action"), event.optBoolean("down"));
                    break;
                case "pointer": gameInput.move((float) event.optDouble("x"), (float) event.optDouble("y")); break;
                case "wheel": gameInput.wheel(event.optInt("y")); break;
                case "layer": showLayer(); break;
                case "capture": if (!event.optBoolean("down")) gameInput.releaseAll(); break;
            }
        });
        layerStatus.setText("Layer " + controller.layerLabel());
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
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x446ee4f0), panel(0xff173951), null));
        button.setOnClickListener(view -> action.run());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(48)); params.topMargin = dp(5); tools.addView(button, params);
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
    private GradientDrawable panel(int color) {
        GradientDrawable background = new GradientDrawable(); background.setColor(color);
        background.setCornerRadius(dp(12)); background.setStroke(dp(1), 0xff315d78); return background;
    }
    private void fullscreen() {
        // PhoneWindow.getInsetsController() dereferences its decor on Android 13.
        // Install it before the first fullscreen request, which precedes setContentView.
        View decor = getWindow().getDecorView();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        if (Build.VERSION.SDK_INT >= 28) {
            WindowManager.LayoutParams attributes = getWindow().getAttributes();
            attributes.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(attributes);
        }
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController insets = decor.getWindowInsetsController();
            if (insets != null) { insets.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE); insets.hide(WindowInsets.Type.systemBars()); }
        } else decor.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }
    private boolean gameInputActive() { return visible && connection != null && hasWindowFocus() && !menuOpen && !mappingsOpen && activeTextDialog == null; }
    private void updateCapture() {
        if (controller == null) return;
        boolean enabled = gameInputActive();
        if (controller.active() != enabled) controller.capture(enabled);
        if (!enabled) { screen.releasePointer(); gameInput.releaseAll(); }
    }
    private void setMenuOpen(boolean open) {
        menuOpen = open; menuLayer.setVisibility(open ? View.VISIBLE : View.GONE);
        gear.setContentDescription(open ? "Close flight controls" : "Open flight controls");
        if (controller != null) layerStatus.setText("Layer " + controller.layerLabel());
        updateCapture(); if (open) menu.getChildAt(0).requestFocus(); else { screen.requestFocus(); fullscreen(); }
    }
    private void showLayer() {
        if (controller == null || layerBanner == null) return;
        String label = "Layer " + controller.layerLabel(); layerStatus.setText(label); layerBanner.setText(label);
        layerBanner.setVisibility(View.VISIBLE); handler.removeCallbacks(hideLayer); handler.postDelayed(hideLayer, 1500);
    }
    private void controllerMappings() {
        mappingsOpen = true; setMenuOpen(false); updateCapture();
        mappingDialog = new ControllerDialog(this, controller, () -> {
            mappingsOpen = false; mappingDialog = null; screen.requestFocus(); fullscreen(); updateCapture();
        }).show();
    }
    private void press(int key) { submit(client -> client.tap(key)); }
    private void menuKey(int key) { setMenuOpen(false); press(key); }
    private void textEntry() {
        if (activeTextDialog != null) return;
        setMenuOpen(false);
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
        activeTextDialog.setOnDismissListener(dialog -> { text.setText(""); activeTextDialog = null; screen.requestFocus(); fullscreen(); updateCapture(); });
        updateCapture(); activeTextDialog.show();
    }
    private void displayStatus(long token, String message) { handler.post(() -> {
        if (visible && generation == token) { status.setText(message); status.setVisibility(receivedFrame ? View.GONE : View.VISIBLE); updateCapture(); }
    }); }
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
        try { input.execute(() -> { try { if (client != null) client.releaseInputs(); } catch (IOException ignored) { } finally { close(previous); } }); }
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
            RfbClient sessionClient = null;
            DisplayPerformance measured = null;
            boolean connected = false;
            try {
                synchronized (socketLock) { if (!visible || generation != token) break; socket = attempt; }
                attempt.connect(new InetSocketAddress("127.0.0.1", 5907), 3000);
                attempt.setTcpNoDelay(true); attempt.setSoTimeout(15000);
                measured = new DisplayPerformance();
                RfbClient client = new RfbClient(attempt.getInputStream(), attempt.getOutputStream(), new RfbClient.Screen() {
                    @Override public void resize(int width, int height) { if (generation == token) {
                        screen.resize(width, height); handler.post(() -> { if (generation == token) gameInput.size(width, height); });
                    } }
                    @Override public void pixels(int x, int y, int width, int height, int[] pixels) { if (generation == token) screen.pixels(x, y, width, height, pixels); }
                    @Override public void updated() {
                        if (generation != token) return;
                        screen.updated();
                        if (!receivedFrame) { receivedFrame = true; displayStatus(token, "Local display connected · touch to click · use Text for login fields"); }
                    }
                }, measured);
                sessionClient = client;
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
                    receivedFrame = false;
                    if (connected) deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(2);
                    String detail = error.getMessage() == null ? "connection closed" : error.getMessage();
                    displayStatus(token, "Waiting for local client display · " + detail + " · Return to Launcher for logs");
                    if (!detail.equals(previousError)) { RuntimeService.append(this, "Client display connection: " + detail); previousError = detail; }
                }
            } finally {
                // A peer that stopped reading must not trap reconnect in a release write.
                handler.postDelayed(() -> close(attempt), 250);
                try { if (sessionClient != null) sessionClient.releaseInputs(); } catch (IOException ignored) { }
                try { attempt.close(); } catch (IOException ignored) { }
                synchronized (socketLock) {
                    if (generation == token) { connection = null; socket = null; performance = null; screen.setPerformance(null); receivedFrame = false;
                        handler.post(() -> { if (generation == token) updateCapture(); }); }
                }
                finishPerformance(measured);
            }
            if (!visible || generation != token) break;
            try { Thread.sleep(1500); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); break; }
        }
    }
    @Override public void onResume() {
        super.onResume(); fullscreen(); final long token;
        synchronized (socketLock) { visible = true; receivedFrame = false; token = ++generation; }
        new Thread(() -> connect(token), "eve-display-reader").start();
    }
    @Override public void onPause() {
        if (controller != null) controller.capture(false);
        screen.releasePointer(); gameInput.releaseAll();
        visible = false;
        if (activeTextDialog != null) activeTextDialog.dismiss();
        if (mappingDialog != null) mappingDialog.dismiss();
        disconnect();
        super.onPause();
    }
    @Override public void onDestroy() {
        if (controller != null) controller.close();
        gameInput.releaseAll(); pointerMotion.cancel(); handler.removeCallbacks(hideLayer);
        disconnect(); input.shutdown(); screen.dispose();
        getWindow().removeOnFrameMetricsAvailableListener(frameListener); frameThread.quitSafely(); diagnostics.shutdown();
        super.onDestroy();
    }
    private int keysym(KeyEvent event) {
        switch (event.getKeyCode()) {
            case KeyEvent.KEYCODE_SHIFT_LEFT: return 0xffe1;
            case KeyEvent.KEYCODE_SHIFT_RIGHT: return 0xffe2;
            case KeyEvent.KEYCODE_CTRL_LEFT: return 0xffe3;
            case KeyEvent.KEYCODE_CTRL_RIGHT: return 0xffe4;
            case KeyEvent.KEYCODE_ALT_LEFT: return 0xffe9;
            case KeyEvent.KEYCODE_ALT_RIGHT: return 0xffea;
            case KeyEvent.KEYCODE_MOVE_HOME: return 0xff50;
            case KeyEvent.KEYCODE_MOVE_END: return 0xff57;
            case KeyEvent.KEYCODE_PAGE_UP: return 0xff55;
            case KeyEvent.KEYCODE_PAGE_DOWN: return 0xff56;
            case KeyEvent.KEYCODE_INSERT: return 0xff63;
            case KeyEvent.KEYCODE_NUM_LOCK: return 0xff7f;
            case KeyEvent.KEYCODE_ENTER: return 0xff0d;
            case KeyEvent.KEYCODE_TAB: return 0xff09;
            case KeyEvent.KEYCODE_DEL: return 0xff08;
            case KeyEvent.KEYCODE_FORWARD_DEL: return 0xffff;
            case KeyEvent.KEYCODE_ESCAPE: return 0xff1b;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 0xff51;
            case KeyEvent.KEYCODE_DPAD_UP: return 0xff52;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 0xff53;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 0xff54;
            default:
                if (event.getKeyCode() >= KeyEvent.KEYCODE_F1 && event.getKeyCode() <= KeyEvent.KEYCODE_F12)
                    return 0xffbe + event.getKeyCode() - KeyEvent.KEYCODE_F1;
                int code = event.getUnicodeChar(event.getMetaState() & ~(KeyEvent.META_CTRL_MASK | KeyEvent.META_ALT_MASK | KeyEvent.META_META_MASK));
                return code == 0 ? 0 : code <= 255 ? code : 0x01000000 | code;
        }
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (!gameInputActive()) return super.dispatchKeyEvent(event);
        if (controller.key(event)) return true;
        if (ControllerManager.isGamepad(event)) return true;
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK) { if (event.getAction() == KeyEvent.ACTION_UP) setMenuOpen(true); return true; }
        if (!event.isFromSource(InputDevice.SOURCE_KEYBOARD)) return super.dispatchKeyEvent(event);
        int key = keysym(event);
        if (key != 0 && (event.getAction() == KeyEvent.ACTION_DOWN || event.getAction() == KeyEvent.ACTION_UP)) {
            gameInput.key("physical:" + event.getDeviceId() + ":" + event.getKeyCode(), key, event.getAction() == KeyEvent.ACTION_DOWN);
            return true;
        }
        return super.dispatchKeyEvent(event);
    }
    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        return gameInputActive() && controller.motion(event) || super.dispatchGenericMotionEvent(event);
    }
    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus); if (focus && activeTextDialog == null) fullscreen(); updateCapture();
    }
    @Override public void onBackPressed() { if (menuOpen) setMenuOpen(false); else setMenuOpen(true); }
}
