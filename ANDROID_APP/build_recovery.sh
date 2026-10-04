#!/data/data/com.termux/files/usr/bin/bash
set -eu
export ANDROID_DATA="${ANDROID_DATA:-/data}"
export ANDROID_ROOT="${ANDROID_ROOT:-/system}"
APP="$HOME/DEVCO_FIELD/ANDROID_APP"
BUILD="$APP/build/recovery"
mkdir -p "$BUILD/classes" "$BUILD/dex"
javac -source 8 -target 8 -classpath "$APP/lib/android.jar" -d "$BUILD/classes" "$APP/src/com/devco/field/MainActivity.java"
d8 --lib "$APP/lib/android.jar" --min-api 21 --output "$BUILD/dex" "$BUILD"/classes/com/devco/field/*.class
aapt package -f -M "$APP/AndroidManifest.xml" -I "$APP/lib/android.jar" -F "$BUILD/unsigned.apk"
python - "$BUILD" <<'PY'
import sys, zipfile
from pathlib import Path
build = Path(sys.argv[1])
with zipfile.ZipFile(build / "unsigned.apk", "a") as apk:
    for dex in (build / "dex").glob("*.dex"):
        apk.write(dex, dex.name)
PY
zipalign -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
# The existing key and its password stay on the phone, outside git.
apksigner sign --ks "$APP/devco-field.keystore" --ks-pass "file:$APP/build/signing-password" --out "$BUILD/DEVCO_Field_Host_Recovery.apk" "$BUILD/aligned.apk"
apksigner verify "$BUILD/DEVCO_Field_Host_Recovery.apk"
echo "Built and verified $BUILD/DEVCO_Field_Host_Recovery.apk"
