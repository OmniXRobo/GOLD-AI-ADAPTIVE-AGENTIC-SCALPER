package com.omnixrobo.goldai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;

/**
 * Polls the server's read-only signal list and posts a notification for each new pending signal.
 * It never approves, rejects or executes anything.
 */
public class SignalWatchService extends Service {
    private static final String CH_STATUS = "watch";
    private static final String CH_SIGNALS = "signals";
    private static final int ONGOING_ID = 1;
    private static final long INTERVAL_MS = 20000;
    private static final long MAX_BACKOFF_MS = 120000;
    private static final int SEEN_LIMIT = 300;

    private HandlerThread thread;
    private Handler handler;
    private long delay = INTERVAL_MS;
    private int nextId = 100;

    static void start(Context c) {
        Intent i = new Intent(c, SignalWatchService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, SignalWatchService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        channels();
        startForeground(ONGOING_ID, ongoing("Watching for new signals"));
        thread = new HandlerThread("signal-watch");
        thread.start();
        handler = new Handler(thread.getLooper());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!Prefs.alerts(this) || Prefs.deviceToken(this) == null || Prefs.server(this) == null) {
            stopSelf();
            return START_NOT_STICKY;
        }
        handler.removeCallbacksAndMessages(null);
        handler.post(poll);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (handler != null) handler.removeCallbacksAndMessages(null);
        if (thread != null) thread.quitSafely();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private final Runnable poll = new Runnable() {
        @Override
        public void run() {
            String server = Prefs.server(SignalWatchService.this);
            String token = Prefs.deviceToken(SignalWatchService.this);
            if (server == null || token == null || !Prefs.alerts(SignalWatchService.this)) {
                stopSelf();
                return;
            }
            try {
                Http.Response r = Http.request("GET", server + "/api/device/signals", token, null);
                if (r.code == 401) {
                    Prefs.setDeviceToken(SignalWatchService.this, null);
                    notifySimple("Signal alerts paused", "Open Gold AI and sign in again to resume alerts.");
                    stopSelf();
                    return;
                }
                if (r.code != 200) throw new Exception("HTTP " + r.code);
                handle(new JSONArray(r.body));
                updateOngoing("Watching for new signals");
                delay = INTERVAL_MS;
            } catch (Exception e) {
                updateOngoing("Server unreachable, retrying");
                delay = Math.min(delay * 2, MAX_BACKOFF_MS);
            }
            handler.postDelayed(this, delay);
        }
    };

    private void handle(JSONArray list) throws Exception {
        List<String> seen = new ArrayList<String>(Arrays.asList(Prefs.seen(this).split(",")));
        boolean primed = Prefs.primed(this);
        for (int i = 0; i < list.length(); i++) {
            JSONObject s = list.getJSONObject(i);
            String id = s.optString("id");
            if (id.isEmpty() || seen.contains(id)) continue;
            seen.add(id);
            // On the first poll only remember what already exists, so old signals don't all ring at once.
            if (primed && "pending".equals(s.optString("status"))) notifySignal(s);
        }
        while (seen.size() > SEEN_LIMIT) seen.remove(0);
        StringBuilder sb = new StringBuilder();
        for (String id : seen) {
            if (id.isEmpty()) continue;
            if (sb.length() > 0) sb.append(',');
            sb.append(id);
        }
        Prefs.setSeen(this, sb.toString());
    }

    private void notifySignal(JSONObject s) {
        String side = s.optString("side", "").toUpperCase(Locale.US);
        int d = s.optInt("digits", 2);
        String title = side + " " + s.optString("symbol", "XAUUSD") + " @ " + num(s, "entry", d);
        String text = "SL " + num(s, "stop_loss", d) + " · TP " + num(s, "take_profit", d)
                + " · conf " + Math.round(s.optDouble("confidence", 0) * 100) + "% · " + s.optString("broker", "");
        String more = text + "\n" + s.optString("reason", "") + "\nSignal only. Review it in the app before acting.";
        Notification.Builder b = builder(CH_SIGNALS)
                .setSmallIcon(R.drawable.ic_stat_signal)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(more))
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_MESSAGE)
                .setContentIntent(open("/signals"));
        nm().notify(nextId++, b.build());
    }

    private void notifySimple(String title, String text) {
        nm().notify(2, builder(CH_SIGNALS).setSmallIcon(R.drawable.ic_stat_signal).setContentTitle(title)
                .setContentText(text).setAutoCancel(true).setContentIntent(open("/")).build());
    }

    /** Price with the instrument's decimals (2 for gold and BTC, 5 for forex, 3 for JPY pairs). */
    private static String num(JSONObject s, String key, int digits) {
        double v = s.optDouble(key, Double.NaN);
        int d = Math.max(0, Math.min(8, digits));
        return Double.isNaN(v) ? "n/a" : String.format(Locale.US, "%." + d + "f", v);
    }

    private Notification ongoing(String text) {
        return builder(CH_STATUS).setSmallIcon(R.drawable.ic_stat_signal).setContentTitle("Gold AI signal alerts")
                .setContentText(text).setOngoing(true).setContentIntent(open("/")).build();
    }

    private void updateOngoing(String text) {
        nm().notify(ONGOING_ID, ongoing(text));
    }

    private PendingIntent open(String path) {
        Intent i = new Intent(this, MainActivity.class).putExtra(MainActivity.EXTRA_PATH, path)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(this, path.hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    @SuppressWarnings("deprecation")
    private Notification.Builder builder(String channel) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, channel) : new Notification.Builder(this);
        b.setColor(getColor(R.color.gold));
        if (Build.VERSION.SDK_INT < 26 && CH_SIGNALS.equals(channel)) b.setPriority(Notification.PRIORITY_HIGH).setDefaults(Notification.DEFAULT_ALL);
        return b;
    }

    private NotificationManager nm() {
        return (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
    }

    private void channels() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationChannel watch = new NotificationChannel(CH_STATUS, "Alert service status", NotificationManager.IMPORTANCE_MIN);
        watch.setShowBadge(false);
        NotificationChannel sig = new NotificationChannel(CH_SIGNALS, "Trade signals", NotificationManager.IMPORTANCE_HIGH);
        sig.setDescription("New gold, Bitcoin and forex signals from your Gold AI server");
        nm().createNotificationChannel(watch);
        nm().createNotificationChannel(sig);
    }
}
