package io.github.russianranger.eve;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;

/** Server-first control deck; operations live in the service across Activity recreation. */
public final class MainActivity extends Activity {
    private static final int CLIENT_ZIP = 1, SUPPORT_ZIP = 2;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private LinearLayout body;
    private TextView stateText, workText, logText;
    private String tab = "Server";
    private CheckBox useAdreno;
    private boolean updatingRenderer;
    private final List<Button> controls = new ArrayList<>();
    private boolean resumed;
    private long logGeneration;
    private final Runnable refresh = new Runnable() {
        @Override public void run() { if (!resumed) return; updateState(); handler.postDelayed(this, 1000); }
    };
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView label(String text, int size, int color) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color); view.setPadding(0, dp(5), 0, dp(5)); return view;
    }
    private GradientDrawable panel(int fill, int border) {
        GradientDrawable background = new GradientDrawable(); background.setColor(fill); background.setCornerRadius(dp(10)); background.setStroke(dp(1), border); return background;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (!RuntimeService.busy && RuntimeService.message.equals("Ready")) {
            RuntimeService.message = getSharedPreferences("last-operation", MODE_PRIVATE).getString("message", "Ready");
            RuntimeService.error = getSharedPreferences("last-operation", MODE_PRIVATE).getString("error", "");
        }
        if (state != null) tab = state.getString("tab", "Server");
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{0xff07111d, 0xff13273b, 0xff07111d}));
        root.setPadding(dp(18), dp(12), dp(18), dp(12));
        root.setOnApplyWindowInsetsListener((view, insets) -> { root.setPadding(dp(18) + insets.getSystemWindowInsetLeft(), dp(12) + insets.getSystemWindowInsetTop(), dp(18) + insets.getSystemWindowInsetRight(), dp(12) + insets.getSystemWindowInsetBottom()); return insets; });
        TextView title = label("EVE  /  LOCAL COMMAND", 23, 0xffeef8fa); title.setTypeface(Typeface.DEFAULT, Typeface.BOLD); root.addView(title);
        root.addView(label("ANDROID LAUNCHER   ·   " + BuildConfig.VERSION_NAME + " PREVIEW", 11, 0xff82b7cb));
        LinearLayout tabs = new LinearLayout(this);
        for (String name : new String[]{"Server", "Client", "Logs"}) {
            Button button = new Button(this); button.setText(name); button.setTextColor(0xffd9eff4); button.setAllCaps(false); button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff183247));
            button.setOnClickListener(v -> { tab = name; render(); }); tabs.addView(button, new LinearLayout.LayoutParams(0, dp(48), 1));
        }
        root.addView(tabs);
        workText = label("", 13, 0xff6ee4f0); root.addView(workText);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL); body.setPadding(0, dp(12), 0, dp(16)); scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1)); setContentView(root); render();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 3);
    }
    private LinearLayout card(String title, String description) {
        LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(16), dp(12), dp(16), dp(12));
        card.setBackground(panel(0xff102334, 0xff29475d));
        TextView heading = label(title, 19, 0xffeef8fa); heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD); card.addView(heading);
        if (!description.isEmpty()) card.addView(label(description, 14, 0xffb2c9d5));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.bottomMargin = dp(14); body.addView(card, params); return card;
    }
    private void action(LinearLayout parent, String title, String action) {
        Button button = new Button(this); button.setText(title); button.setAllCaps(false); button.setTextColor(0xffeef8fa); button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff24516b));
        button.setOnClickListener(v -> { if (action.equals("pick-client")) pickClient(); else if (action.equals("pick-export")) pickExport(); else if (action.equals("view-client")) startActivity(new Intent(this, ClientDisplayActivity.class)); else run(action, null); });
        parent.addView(button, new LinearLayout.LayoutParams(-1, -2)); controls.add(button);
        button.setTag(action);
    }
    private void render() {
        logGeneration++; controls.clear(); body.removeAllViews(); stateText = null; logText = null;
        if (tab.equals("Server")) {
            LinearLayout state = card("Your local universe", "EVE.js 0.12.9 · client build 3396210\nSetup downloads the prepared ARM64 server package. World data stays on this device.");
            stateText = label("", 15, 0xff6ee4f0); state.addView(stateText);
            LinearLayout setup = card("Set up the server", "Install once, then prepare the universe and Jita market. Repeating preparation preserves existing world data.");
            action(setup, "1  Install server runtime", "install-server"); action(setup, "2  Prepare local world", "prepare-server");
            LinearLayout session = card("Server session", "Readiness checks the game connection, gateway and market. The notification keeps the session accessible while you switch apps.");
            action(session, "Start server", "start-server"); action(session, "Save and stop server", "stop-server");
        } else if (tab.equals("Client")) {
            LinearLayout state = card("Client performance", "Start the local server first. GPU rendering and responsive text entry are the focus of this preview.");
            stateText = label("", 14, 0xff6ee4f0); state.addView(stateText);
            LinearLayout client = card("Supported EVE client", "Requires EVE 24.01 build 3396210. Import a ZIP containing tq, ResFiles and index_tranquility.txt. Preserve the complete shared cache.");
            action(client, "Install Wine / FEX runtime", "install-client"); action(client, "Import complete client ZIP", "pick-client");
            action(client, "Resume interrupted client import", "resume-client");
            action(client, "Validate and prepare client", "validate-client"); action(client, "Probe Wine / FEX", "probe-client");
            LinearLayout session = card("Client session", "Open the fullscreen display for touch, controller layers and gear controls. Use Adreno GPU rendering; software recovery is slower. Stop the client before changing this option.");
            useAdreno = new CheckBox(this); useAdreno.setText("Use Adreno GPU rendering"); useAdreno.setTextColor(0xffeef8fa);
            useAdreno.setChecked(new ClientRuntime(this).renderer().equals("turnip-dxvk"));
            useAdreno.setOnCheckedChangeListener((button, checked) -> {
                if (updatingRenderer) return;
                try { new ClientRuntime(this).useAdreno(checked); }
                catch (IllegalStateException error) {
                    updatingRenderer = true; useAdreno.setChecked(new ClientRuntime(this).renderer().equals("turnip-dxvk")); updatingRenderer = false;
                    Toast.makeText(this, error.getMessage(), Toast.LENGTH_SHORT).show();
                }
            });
            session.addView(useAdreno);
            action(session, "Start EVE client", "start-client"); action(session, "Open client display", "view-client"); action(session, "Stop EVE client", "stop-client");
        } else {
            LinearLayout tools = card("Diagnostics", "Export this support ZIP after the first server test, including failures. It contains bounded logs and status receipts.");
            action(tools, "Export support logs", "pick-export");
            Button refreshButton = new Button(this); refreshButton.setText("Refresh log view"); refreshButton.setAllCaps(false); refreshButton.setOnClickListener(v -> loadLogs()); tools.addView(refreshButton);
            LinearLayout output = card("Recent output", ""); logText = label("Loading…", 11, 0xffc1d6df); logText.setTypeface(Typeface.MONOSPACE); logText.setTextIsSelectable(true); output.addView(logText); loadLogs();
        }
        updateState();
    }
    private void updateState() {
        workText.setText(RuntimeService.message);
        for (Button button : controls) button.setEnabled(!RuntimeService.busy || button.getTag().equals("stop-server") || button.getTag().equals("stop-client") || button.getTag().equals("view-client"));
        try {
            RuntimeManager runtime = RuntimeManager.get(this);
            if (stateText != null && tab.equals("Server")) {
                JSONObject server = runtime.serverStatus();
                String text = "Runtime: " + (server.optBoolean("installed") ? "installed" : "not installed") + "\nWorld: " + (server.optBoolean("prepared") ? "prepared" : "not prepared") + "\n" + (server.optBoolean("ready") ? "SERVER READY" : server.optString("message", "Server stopped")) + "\nFree storage: " + runtime.home.getUsableSpace() / 1073741824L + " GiB";
                stateText.setText(text);
            } else if (stateText != null && tab.equals("Client")) {
                if (useAdreno != null) useAdreno.setEnabled(!RuntimeService.busy && !new ClientRuntime(this).alive());
                JSONObject state = new ClientRuntime(this).status(); stateText.setText(state.optString("message", state.toString(2)));
            }
        } catch (Exception e) { if (stateText != null) stateText.setText("Status unavailable: " + e.getMessage()); }
    }
    private void loadLogs() {
        final TextView target = logText; final long generation = logGeneration;
        new Thread(() -> {
            StringBuilder text = new StringBuilder();
            for (Map.Entry<String, File> file : SupportExport.files(this).entrySet()) {
                try { String tail = SupportExport.tail(file.getValue(), 16384); if (!tail.isEmpty()) text.append(file.getKey()).append('\n').append(tail).append("\n\n"); }
                catch (IOException e) { text.append(file.getKey()).append(": ").append(e.getMessage()).append('\n'); }
                if (text.length() > 150000) break;
            }
            String result = text.length() == 0 ? "No runtime output yet." : text.toString();
            handler.post(() -> { if (target != null && generation == logGeneration && tab.equals("Logs")) target.setText(result); });
        }, "eve-log-view").start();
    }
    private void run(String action, Uri uri) {
        try { RuntimeService.launch(this, action, uri); } catch (RuntimeException e) { new AlertDialog.Builder(this).setTitle("Could not start operation").setMessage(e.getMessage()).setPositiveButton("OK", null).show(); }
    }
    private void pickClient() { Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/zip").addCategory(Intent.CATEGORY_OPENABLE); startActivityForResult(intent, CLIENT_ZIP); }
    private void pickExport() {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/zip").addCategory(Intent.CATEGORY_OPENABLE);
        intent.putExtra(Intent.EXTRA_TITLE, "eve-support-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date()) + ".zip"); startActivityForResult(intent, SUPPORT_ZIP);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        if (request != CLIENT_ZIP && request != SUPPORT_ZIP) return;
        Uri uri = data.getData();
        try {
            if (request == CLIENT_ZIP) getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            else getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        } catch (SecurityException ignored) { /* Existing one-shot grant still covers this operation. */ }
        run(request == CLIENT_ZIP ? "import-client" : "export-logs", uri);
    }
    @Override public void onResume() { super.onResume(); resumed = true; if (!RuntimeService.active && !RuntimeService.busy && (RuntimeManager.get(this).serverAlive() || new ClientRuntime(this).alive())) run("recover-session", null); handler.post(refresh); }
    @Override public void onPause() { resumed = false; handler.removeCallbacks(refresh); super.onPause(); }
    @Override public void onSaveInstanceState(Bundle state) { state.putString("tab", tab); super.onSaveInstanceState(state); }
}
