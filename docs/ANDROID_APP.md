# Android app

`android/` is a small native Android app (Android 7.0 / API 24 and newer) that shows the dashboard served by
your own Gold AI server and can alert you when a new signal appears. It contains no trading logic and holds no
broker credentials: everything it shows comes from your server. Real-money trading stays disabled until the owner
grants it on the server; the app cannot grant it.

## What it does
- **Dashboard**: opens your server's dashboard full screen (same login, same pages). Links to other sites open in
  the phone's browser.
- **Signal alerts** (optional, on by default): after you sign in, the app asks the server for a *read-only device
  token* (`POST /api/auth/device-token`, valid 30 days). A small foreground service then reads
  `GET /api/device/signals` every 20 seconds (backing off to 2 minutes when the server is unreachable) and posts a
  notification for each new pending signal. Alerts are read-only: approving or rejecting a signal still happens in
  the dashboard, which needs your normal session. The device token is never accepted by any other endpoint.
- **Revoking**: Settings → *Revoke all phone alert tokens* (owner/admin) invalidates every phone's token at once.
  Turning alerts off on the phone stops polling.

## Reaching the VPS from your phone (do this first)
The service listens on `127.0.0.1:8001` on the VPS, which a phone cannot reach. Do **not** open port 8001 to the
internet. Recommended: **Tailscale** (free for personal use; private, encrypted, no open ports).

1. On the VPS: install Tailscale for Windows from tailscale.com and sign in.
2. On the phone: install Tailscale from the Play Store and sign in to the **same** account.
3. On the VPS, in an Administrator PowerShell, publish the local service to your private tailnet over HTTPS:
   `tailscale serve --bg 8001`
   It prints an address like `https://your-vps.your-tailnet.ts.net`. Only devices signed in to your tailnet can open it.
4. In the app, enter that address and tap **Test**, then **Save and open**.

`tailscale serve` keeps the service on 127.0.0.1, so nothing else on the VPS needs to change. Plain
`http://` addresses are accepted only for private networks; the app warns when a public address is used without HTTPS.

## Installing the APK
1. Copy `gold-ai-<version>.apk` (latest: 1.4.0 once built on the VPS, which labels alerts Scalp or Swing; 1.3.0 before that) to the phone (or download it from the project files).
2. Open it and allow "Install unknown apps" for the app you opened it with when Android asks.
3. Open **Gold AI**, enter the server address, sign in with your dashboard account.
4. Allow notifications when asked. For reliable alerts, set the app's battery usage to *Unrestricted*
   (Settings → Apps → Gold AI → Battery).

Android only installs an update that is signed with the same key as the installed app. Keep the signing keystore
private and backed up (it is not in this repository).

## Building
The build does not need Gradle or Android Studio:

```bash
# tools: JDK 17+, aapt (v1), d8 (or dx), zipalign, apksigner
#   Android SDK: build-tools/<ver>/ has them all; Ubuntu: apt install aapt dalvik-exchange zipalign apksigner
ANDROID_JAR=$ANDROID_HOME/platforms/android-34/android.jar \
KEYSTORE=~/.gold-ai/gold-ai-release.jks \
./android/build.sh          # -> android/build/gold-ai.apk
```

With the full Android SDK, use `platforms/android-33` or newer. Without it, a Robolectric `android-all` jar for
Android 13 (`org.robolectric:android-all:13-robolectric-9030017` on Maven Central) works as `ANDROID_JAR`; aapt v1
cannot read the resource table of the Android 14+ jars. The first build creates the keystore if it does not exist.

Bump `android:versionCode` and `android:versionName` in `android/AndroidManifest.xml` for each release.

## Limits
- Verified: the APK builds, is zip-aligned and its v2/v3 signature verifies (`apksigner verify`); the server side is
  covered by `tests/test_api.py`. It has **not** yet been run on a physical phone or emulator.
- Alerts depend on the phone keeping the foreground service alive; aggressive battery savers can delay them.
  Telegram alerts (server side) remain the more reliable channel once a bot token is configured.
- HTTPS servers must have a certificate the phone trusts (`tailscale serve` provides one). Self-signed certificates
  are refused.
