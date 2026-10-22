package com.omnixrobo.goldai;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONObject;

/** First-run screen and settings: server address and signal alerts. */
public class SetupActivity extends Activity {
    private EditText server;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(R.layout.activity_setup);
        server = (EditText) findViewById(R.id.server);
        status = (TextView) findViewById(R.id.status);
        Switch alerts = (Switch) findViewById(R.id.alerts);
        Button test = (Button) findViewById(R.id.test);
        Button save = (Button) findViewById(R.id.save);
        TextView version = (TextView) findViewById(R.id.version);

        String current = Prefs.server(this);
        if (current != null) server.setText(current);
        alerts.setChecked(Prefs.alerts(this));
        try {
            version.setText("App " + getPackageManager().getPackageInfo(getPackageName(), 0).versionName);
        } catch (PackageManager.NameNotFoundException ignored) {
        }

        alerts.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton b, boolean on) {
                Prefs.setAlerts(SetupActivity.this, on);
                if (on) {
                    if (Prefs.deviceToken(SetupActivity.this) != null) SignalWatchService.start(SetupActivity.this);
                    else status.setText("Alerts start after you sign in to the dashboard on this phone.");
                } else {
                    SignalWatchService.stop(SetupActivity.this);
                }
            }
        });
        test.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                check(Prefs.normalize(server.getText().toString()));
            }
        });
        save.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String url = Prefs.normalize(server.getText().toString());
                if (url == null || Uri.parse(url).getHost() == null) {
                    status.setText("Enter the server address, for example http://100.101.102.103:8001");
                    return;
                }
                if (!url.equals(Prefs.server(SetupActivity.this))) {
                    SignalWatchService.stop(SetupActivity.this);
                    Prefs.setServer(SetupActivity.this, url);
                }
                Intent i = new Intent(SetupActivity.this, MainActivity.class);
                i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
                startActivity(i);
                finish();
            }
        });
    }

    private void check(final String url) {
        if (url == null) {
            status.setText("Enter the server address first.");
            return;
        }
        status.setText("Checking " + url + " ...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                String msg;
                try {
                    Http.Response r = Http.request("GET", url + "/api/health", null, null);
                    boolean ok = r.code == 200 && "ok".equals(new JSONObject(r.body).optString("status"));
                    msg = ok ? "Connected. The Gold AI server answered." : "The server answered with HTTP " + r.code + ", not the Gold AI API.";
                } catch (Exception e) {
                    msg = "Could not connect: " + e.getMessage();
                }
                String warn = warning(url);
                final String text = warn == null ? msg : msg + "\n\n" + warn;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        status.setText(text);
                    }
                });
            }
        }).start();
    }

    /** Plain HTTP is fine inside Tailscale or a LAN; warn when it would cross the open internet. */
    static String warning(String url) {
        Uri u = Uri.parse(url);
        String host = u.getHost() == null ? "" : u.getHost();
        if (!"http".equals(u.getScheme())) return null;
        boolean privateHost = host.endsWith(".ts.net") || host.startsWith("100.") || host.startsWith("10.")
                || host.startsWith("192.168.") || host.matches("^172\\.(1[6-9]|2\\d|3[01])\\..*") || host.equals("localhost");
        return privateHost ? null
                : "Warning: this address uses plain HTTP over the internet. Your password and data would not be encrypted. Use Tailscale or HTTPS.";
    }
}
