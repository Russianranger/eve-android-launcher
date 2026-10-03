package io.github.russianranger.eve;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import java.io.*;

/** A single worker owns setup; the service remains foreground while the server runs. */
public final class RuntimeService extends Service {
    static volatile boolean busy;
    static volatile boolean active;
    static volatile String operation = "", message = "Ready", error = "";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private volatile Thread worker;
    private volatile boolean destroyed;
    private PowerManager.WakeLock wake;
    private long lastNotice;
    private final Runnable monitor = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            RuntimeManager runtime = RuntimeManager.get(RuntimeService.this);
            if (!busy && !runtime.serverAlive()) { finish(); return; }
            if (wake != null && !wake.isHeld()) wake.acquire(12 * 60 * 60 * 1000L);
            handler.postDelayed(this, 1000);
        }
    };
    static void launch(Context context, String action, Uri uri) {
        Intent intent = new Intent(context, RuntimeService.class).setAction(action);
        if (uri != null) intent.setData(uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        context.startForegroundService(intent);
    }
    private Notification notification(String text) {
        PendingIntent open = PendingIntent.getActivity(this, 1, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 2, new Intent(this, RuntimeService.class).setAction("stop-server"), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, "eve-runtime").setSmallIcon(R.drawable.ic_launcher).setContentTitle("EVE local runtime").setContentText(text).setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(null, "Stop", stop).build()).build();
    }
    private void update(String text) {
        message = text;
        if (!destroyed && System.currentTimeMillis() - lastNotice > 1500) {
            if (Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                getSystemService(NotificationManager.class).notify(1, notification(text));
            }
            lastNotice = System.currentTimeMillis();
        }
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("eve-runtime", "Local EVE runtime", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, notification(message));
        active = true;
        if (intent == null || intent.getAction() == null) { if (!RuntimeManager.get(this).serverAlive()) finish(); return START_NOT_STICKY; }
        String action = intent.getAction();
        if (worker != null) {
            if (action.equals("stop-server")) {
                try { RuntimeManager.get(this).requestServerStop(); } catch (Exception e) { append(this, "Stop request failed: " + e.getMessage()); }
                worker.interrupt(); update("Stopping the current operation…");
            }
            return START_NOT_STICKY;
        }
        busy = true; operation = action; error = "";
        if (wake == null) wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "eve:runtime");
        // Renew while a user-started server session exists; never acquire without a foreground notice.
        if (!wake.isHeld()) wake.acquire(12 * 60 * 60 * 1000L);
        Uri uri = intent.getData();
        worker = new Thread(() -> {
            RuntimeManager runtime = RuntimeManager.get(this); ClientRuntime client = new ClientRuntime(this);
            append(this, "Started " + action);
            try {
                switch (action) {
                    case "install-server": runtime.installServer(this::update); break;
                    case "prepare-server": runtime.prepareServer(this::update); break;
                    case "start-server": runtime.startServer(this::update); break;
                    case "stop-server": runtime.stopServer(this::update); break;
                    case "recover-server": update(runtime.serverStatus().optString("message", "Recovered local server session")); break;
                    case "install-client": client.install(this::update); break;
                    case "import-client":
                        if (uri == null) throw new IOException("Select a complete client ZIP");
                        try (InputStream input = getContentResolver().openInputStream(uri)) { if (input == null) throw new IOException("Client ZIP cannot be opened"); client.importZip(input, this::update); }
                        break;
                    case "validate-client": client.validate(this::update); break;
                    case "resume-client": client.resume(this::update); break;
                    case "probe-client": client.probe(this::update); break;
                    case "export-logs":
                        if (uri == null) throw new IOException("Choose where to save the support ZIP");
                        try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) { if (output == null) throw new IOException("Support ZIP cannot be saved"); SupportExport.write(this, output); }
                        update("Support logs exported."); break;
                    default: throw new IOException("Unknown runtime action");
                }
                append(this, "Completed " + action + ": " + message);
            } catch (Exception e) {
                error = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                update(Thread.currentThread().isInterrupted() ? "Operation cancelled. Open Logs for details." : "Failed: " + error);
                append(this, action + " failed: " + e.getClass().getSimpleName() + ": " + error);
            } finally {
                getSharedPreferences("last-operation", MODE_PRIVATE).edit().putString("message", message).putString("error", error).apply();
                busy = false; worker = null;
                if (!destroyed) handler.post(() -> { handler.removeCallbacks(monitor); handler.post(monitor); });
            }
        }, "eve-" + action);
        worker.start(); return START_NOT_STICKY;
    }
    static synchronized void append(Context context, String line) {
        try {
            File file = new File(context.getFilesDir(), "operations.log");
            if (file.length() > 1024 * 1024) RuntimeManager.text(file, "Previous operations rotated.\n");
            try (Writer writer = new FileWriter(file, true)) { writer.write(new java.util.Date() + " · " + line + "\n"); }
        } catch (IOException e) { android.util.Log.e("EVE", "Operation log", e); }
    }
    private void finish() { active = false; handler.removeCallbacks(monitor); if (wake != null && wake.isHeld()) wake.release(); stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); }
    @Override public void onDestroy() {
        destroyed = true;
        active = false;
        handler.removeCallbacks(monitor);
        if (worker != null) worker.interrupt();
        if (RuntimeManager.get(this).serverAlive()) {
            try { RuntimeManager.get(this).requestServerStop(); } catch (IOException e) { append(this, "Service shutdown: " + e.getMessage()); }
        }
        if (wake != null && wake.isHeld()) wake.release(); super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
