package com.omnixrobo.goldai;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/** Shows the dashboard served by the user's own server in a WebView. */
public class MainActivity extends Activity {
    static final String EXTRA_PATH = "path";

    private WebView web;
    private View errorView;
    private TextView errorText;
    private String base;
    private volatile String pageOrigin = "";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        base = Prefs.server(this);
        if (base == null) {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(getColor(R.color.bg));
        web = new WebView(this);
        web.setBackgroundColor(getColor(R.color.bg));
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        errorView = buildErrorView();
        errorView.setVisibility(View.GONE);
        root.addView(errorView, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setUserAgentString(ws.getUserAgentString() + " GoldAIApp/" + version());
        web.addJavascriptInterface(new Bridge(), "GoldAIApp");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new Client());

        // Always load the dashboard fresh from the server. Restoring saved WebView state replayed pages from an
        // older build whose scripts no longer exist, so those pages never opened. After an app update the HTTP
        // cache is cleared once for the same reason (the sign-in kept in localStorage is not touched).
        String v = version();
        if (!v.equals(Prefs.cacheVersion(this))) {
            web.clearCache(true);
            Prefs.setCacheVersion(this, v);
        }
        web.loadUrl(base + pathFrom(getIntent()));

        if (Prefs.alerts(this)) {
            askNotificationPermission();
            if (Prefs.deviceToken(this) != null) SignalWatchService.start(this);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String path = pathFrom(intent);
        if (web != null && !path.isEmpty()) web.loadUrl(base + path);
    }

    @Override
    protected void onResume() {
        super.onResume();
        String now = Prefs.server(this);
        if (web != null && now != null && !now.equals(base)) {
            base = now;
            web.clearCache(true);
            web.clearHistory();
            web.loadUrl(base + "/");
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    private static String pathFrom(Intent i) {
        String p = i == null ? null : i.getStringExtra(EXTRA_PATH);
        return p != null && p.startsWith("/") ? p : "";
    }

    private String version() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    private void askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {"android.permission.POST_NOTIFICATIONS"}, 1);
        }
    }

    private static String origin(Uri u) {
        if (u == null || u.getScheme() == null || u.getHost() == null) return "";
        return u.getScheme() + "://" + u.getHost() + (u.getPort() == -1 ? "" : ":" + u.getPort());
    }

    private boolean isOurs(Uri u) {
        return origin(u).equalsIgnoreCase(origin(Uri.parse(base)));
    }

    private void showError(String msg) {
        errorText.setText(msg + "\n\n" + base);
        errorView.setVisibility(View.VISIBLE);
    }

    private View buildErrorView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(getColor(R.color.bg));
        int pad = dp(28);
        box.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Can't reach your server");
        title.setTextColor(getColor(R.color.text));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        title.setGravity(Gravity.CENTER);
        box.addView(title);

        errorText = new TextView(this);
        errorText.setTextColor(getColor(R.color.text2));
        errorText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        errorText.setGravity(Gravity.CENTER);
        errorText.setPadding(0, dp(10), 0, dp(10));
        box.addView(errorText);

        TextView hint = new TextView(this);
        hint.setText("Check that the VPS service is running and that Tailscale (or your VPN) is connected on this phone.");
        hint.setTextColor(getColor(R.color.text2));
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        hint.setGravity(Gravity.CENTER);
        box.addView(hint);

        Button retry = new Button(this);
        retry.setText("Retry");
        retry.setAllCaps(false);
        retry.setTextColor(Color.parseColor("#17130A"));
        retry.setBackgroundResource(R.drawable.btn_gold);
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                errorView.setVisibility(View.GONE);
                web.reload();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        lp.topMargin = dp(24);
        box.addView(retry, lp);

        Button settings = new Button(this);
        settings.setText("Change server");
        settings.setAllCaps(false);
        settings.setTextColor(getColor(R.color.text));
        settings.setBackgroundResource(R.drawable.field_bg);
        settings.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(MainActivity.this, SetupActivity.class));
            }
        });
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        lp2.topMargin = dp(10);
        box.addView(settings, lp2);
        return box;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private final class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (isOurs(u)) return false;
            // Anything off the server opens in the phone's browser, outside the bridge.
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (Exception ignored) {
            }
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            pageOrigin = origin(Uri.parse(url));
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            pageOrigin = origin(Uri.parse(url));
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (req.isForMainFrame()) showError(String.valueOf(err.getDescription()));
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            handler.cancel();
            showError("The server's HTTPS certificate is not trusted.");
        }
    }

    /** Exposed to the dashboard as window.GoldAIApp; only answers pages from the configured server. */
    private final class Bridge {
        private boolean trusted() {
            return pageOrigin.equalsIgnoreCase(origin(Uri.parse(base)));
        }

        @JavascriptInterface
        public void onSession(final String sessionToken) {
            if (!trusted() || sessionToken == null || !Prefs.alerts(MainActivity.this)) return;
            final String server = base;
            new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        JSONObject body = new JSONObject().put("device", Build.MANUFACTURER + " " + Build.MODEL);
                        Http.Response r = Http.request("POST", server + "/api/auth/device-token", sessionToken, body.toString());
                        if (r.code == 200) {
                            Prefs.setDeviceToken(MainActivity.this, new JSONObject(r.body).getString("token"));
                            SignalWatchService.start(MainActivity.this);
                        }
                    } catch (Exception ignored) {
                        // Alerts stay off until the next sign-in; the dashboard itself still works.
                    }
                }
            }).start();
        }

        @JavascriptInterface
        public void openSettings() {
            if (!trusted()) return;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    startActivity(new Intent(MainActivity.this, SetupActivity.class));
                }
            });
        }

        @JavascriptInterface
        public String appVersion() {
            return version();
        }

        @JavascriptInterface
        public boolean alertsEnabled() {
            return Prefs.alerts(MainActivity.this) && Prefs.deviceToken(MainActivity.this) != null;
        }
    }
}
