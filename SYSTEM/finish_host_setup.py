#!/data/data/com.termux/files/usr/bin/python
"""Open Android's required confirmation screens for the prepared host update."""
import os
from pathlib import Path
import subprocess
import time

ROOT = Path.home() / "DEVCO_FIELD"
BUILD = ROOT / "ANDROID_APP/build"
os.environ.setdefault("ANDROID_DATA", "/data")
os.environ.setdefault("ANDROID_ROOT", "/system")

def installed(package, version=None):
    result = subprocess.run(["pm", "path", "--user", "0", package], capture_output=True, text=True, timeout=10)
    paths = [line[8:] for line in result.stdout.splitlines() if line.startswith("package:")]
    if not paths:
        return False
    if version is None:
        return True
    result = subprocess.run(["aapt", "dump", "badging", paths[0]], capture_output=True, text=True, timeout=10)
    return "versionName='" + version + "'" in result.stdout

def install(apk, package, version=None):
    if installed(package, version):
        return
    print("Android confirmation needed: " + apk.name, flush=True)
    subprocess.run(["termux-open", "--view", "--content-type", "application/vnd.android.package-archive", str(apk)], check=True, timeout=15)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if installed(package, version):
            print("Installed: " + package, flush=True)
            return
        time.sleep(3)
    raise SystemExit("Installation still pending. Run devco-setup to continue.")

install(BUILD / "recovery/DEVCO_Field_Host_Recovery.apk", "com.devco.field", "1.2-photos-ju-files")
install(BUILD / "Termux_Boot.apk", "com.termux.boot")
# Termux:Boot must be opened once so Android enables its boot receiver.
subprocess.run(["am", "start", "--user", "0", "-n", "com.termux.boot/.BootActivity"], timeout=15, check=False)
time.sleep(2)
print("Confirm that Termux may keep running in the background.", flush=True)
subprocess.run(["am", "start", "--user", "0", "-a", "android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
                "-d", "package:com.termux"], timeout=15, check=False)
print("After allowing background activity, reopen DEVCO Field and allow its Termux permission if asked.", flush=True)
