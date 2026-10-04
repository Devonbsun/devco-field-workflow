"""Cheap, read-only readiness check shared by the launcher and watchdog."""
import json
import sys
import urllib.request

def health():
    with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as response:
        data = json.load(response)
        if data.get("service") != "devco-field" or data.get("ready") is not True:
            raise RuntimeError("DEVCO host is not ready")
        return data

if __name__ == "__main__":
    try:
        data = health()
        if "--quiet" not in sys.argv:
            print(json.dumps(data))
    except Exception as error:
        if "--quiet" not in sys.argv:
            print(str(error), file=sys.stderr)
        sys.exit(1)
