#!/usr/bin/env bash
# Builds the Gold AI Android app without Gradle.
#
# Needs: JDK 17+, aapt (v1), d8 or dx, zipalign, apksigner, and an android.jar to compile against.
#   ANDROID_JAR   path to platforms/android-34/android.jar (or any API 33+ android.jar)
#   KEYSTORE      signing keystore (created on first run if missing; keep it private and backed up:
#                 Android only installs updates signed with the same key)
#   KS_PASS       keystore password (default: prompt via keytool/apksigner)
# Output: build/gold-ai.apk
set -euo pipefail
cd "$(dirname "$0")"

: "${ANDROID_JAR:?set ANDROID_JAR to an android.jar (API 33 or newer)}"
KEYSTORE="${KEYSTORE:-$HOME/.gold-ai/gold-ai-release.jks}"
ALIAS="${KEY_ALIAS:-gold-ai}"
MIN_SDK=24
TARGET_SDK=34

pick() { for t in "$@"; do command -v "$t" >/dev/null 2>&1 && { echo "$t"; return; }; done; }
AAPT="$(pick aapt)"
DEX="$(pick d8 dx dalvik-exchange)"
[ -n "$AAPT" ] && [ -n "$DEX" ] || { echo "need aapt and d8/dx on PATH" >&2; exit 1; }
command -v zipalign >/dev/null && command -v apksigner >/dev/null || { echo "need zipalign and apksigner" >&2; exit 1; }

rm -rf build && mkdir -p build/gen build/classes

echo "[1/5] resources"
"$AAPT" package -f -m -J build/gen -M AndroidManifest.xml -S res -I "$ANDROID_JAR" \
  --min-sdk-version $MIN_SDK --target-sdk-version $TARGET_SDK -F build/unsigned.apk

echo "[2/5] compile"
# A real SDK android.jar carries java.lang; a Robolectric android-all jar does not, so pair it with --release 8.
if unzip -l "$ANDROID_JAR" java/lang/Object.class >/dev/null 2>&1; then
  JFLAGS=(-source 8 -target 8 -bootclasspath "$ANDROID_JAR")
else
  JFLAGS=(--release 8 -classpath "$ANDROID_JAR")
fi
javac -nowarn -Xlint:-options -encoding UTF-8 "${JFLAGS[@]}" -d build/classes $(find build/gen src -name '*.java')

echo "[3/5] dex"
if [ "$(basename "$DEX")" = d8 ]; then
  "$DEX" --release --min-api $MIN_SDK --lib "$ANDROID_JAR" --output build $(find build/classes -name '*.class')
else
  "$DEX" --dex --min-sdk-version=$MIN_SDK --output=build/classes.dex build/classes
fi
(cd build && "$AAPT" add -f unsigned.apk classes.dex >/dev/null)

echo "[4/5] align"
zipalign -f -p 4 build/unsigned.apk build/aligned.apk

echo "[5/5] sign"
if [ ! -f "$KEYSTORE" ]; then
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -keystore "$KEYSTORE" -alias "$ALIAS" -keyalg RSA -keysize 3072 -validity 10000 \
    -dname "CN=Gold AI, O=OmniXRobo" ${KS_PASS:+-storepass "$KS_PASS" -keypass "$KS_PASS"}
fi
apksigner sign --ks "$KEYSTORE" --ks-key-alias "$ALIAS" ${KS_PASS:+--ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS"} \
  --min-sdk-version $MIN_SDK --out build/gold-ai.apk build/aligned.apk
apksigner verify build/gold-ai.apk
echo "built $(pwd)/build/gold-ai.apk"
