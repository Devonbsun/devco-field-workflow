"""Restart only the supervised DEVCO host after sustained failed HTTP checks."""
import os
from pathlib import Path
import subprocess
import time
from host_health import health

service = Path(os.environ["PREFIX"]) / "var/service/devco"
failures = 0
# Give a cold phone and filesystem time to become ready.
time.sleep(30)
while True:
    if (service / "down").exists():
        failures = 0
    else:
        try:
            health()
            failures = 0
        except Exception as error:
            failures += 1
            print(f"DEVCO health failure {failures}/4: {error}", flush=True)
            if failures >= 4:
                # runit owns the PID; never use a broad pgrep/pkill pattern.
                subprocess.run(["sv", "-w", "15", "force-restart", str(service)],
                               timeout=25, check=False)
                failures = 0
                time.sleep(30)
    time.sleep(10)
