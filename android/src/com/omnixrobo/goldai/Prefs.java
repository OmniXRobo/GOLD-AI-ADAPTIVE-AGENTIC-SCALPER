package com.omnixrobo.goldai;

import android.content.Context;
import android.content.SharedPreferences;

/** App settings. Only the read-only device token is stored, never the dashboard password or session. */
final class Prefs {
    private static final String FILE = "gold_ai";

    private Prefs() {}

    private static SharedPreferences p(Context c) {
        return c.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static String server(Context c) {
        return p(c).getString("server", null);
    }

    static void setServer(Context c, String url) {
        p(c).edit().putString("server", url).remove("device_token").remove("seen").remove("primed").apply();
    }

    static boolean alerts(Context c) {
        return p(c).getBoolean("alerts", true);
    }

    static void setAlerts(Context c, boolean on) {
        p(c).edit().putBoolean("alerts", on).apply();
    }

    static String deviceToken(Context c) {
        return p(c).getString("device_token", null);
    }

    static void setDeviceToken(Context c, String token) {
        SharedPreferences.Editor e = p(c).edit();
        if (token == null) e.remove("device_token");
        else e.putString("device_token", token);
        e.apply();
    }

    static String seen(Context c) {
        return p(c).getString("seen", "");
    }

    static boolean primed(Context c) {
        return p(c).getBoolean("primed", false);
    }

    static void setSeen(Context c, String seen) {
        p(c).edit().putString("seen", seen).putBoolean("primed", true).apply();
    }

    /** Accepts "host:port" or a full URL; defaults to https and drops a trailing slash. */
    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return null;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "https://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
