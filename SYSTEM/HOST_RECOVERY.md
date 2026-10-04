# DEVCO host recovery

The original Android launch command used `pgrep -f SYSTEM/devco_app.py` inside a shell whose own arguments contained that text. It could see itself and skip starting Python. A detached Python process also had no crash or hang recovery.

## Installed design

- termux-services/runit supervises the devco and devco-watchdog services.
- devco-host ensure serializes startup, acquires Termux's wake lock, starts supervision and waits for an HTTP readiness response.
- /health is read-only and checks the server identity and photo-watcher thread.
- An exclusive file lock and binding the listening socket before starting the photo watcher prevent duplicate workers.
- The watchdog checks every 10 seconds after a 30-second startup grace. Four failed checks trigger a restart of only the runit-owned devco service.
- Logs rotate at 1 MiB with five old files per service.
- The Termux profile hook repairs the currently installed legacy app's login-shell startup path.
- ~/.termux/boot/20-devco-host starts the same service after a reboot, once Termux:Boot is installed and opened.
- Android app version 1.1-host-recovery requests RUN_COMMAND permission, invokes the service launcher directly, probes readiness in the background and reconnects when returning to the app. It preserves an already loaded page during host recovery rather than periodically reloading unsaved notes.

## Setup

Install termux-services, then run SYSTEM/install_host.sh. Before the first migration, stop only the verified old unsupervised DEVCO process. Never use a broad pkill pattern.

The original Android signing key remains on the phone. ANDROID_APP/build_recovery.sh uses the locally stored signing password under the ignored build directory. No signing key or password is committed.

SYSTEM/finish_host_setup.py opens the prepared update and matching official GitHub Termux:Boot APK for Android confirmation, opens Termux:Boot once and requests a Termux battery-optimization exemption. Open DEVCO Field afterward and grant its permission to run Termux commands. On Samsung, also keep Termux out of Sleeping/Deep sleeping apps if enabled.

The Termux:Boot APK is v0.8.1 from github.com/termux/termux-boot, signed with the same certificate as this phone's GitHub Termux installation.

## Verified on the phone, 2026-10-04

- A terminated supervised server restarted and became healthy in about 0.5 seconds.
- A duplicate Python launch exited before starting another photo watcher.
- Four concurrent ensure requests retained a single healthy server.
- A deliberately frozen server was replaced by the watchdog in about 51 seconds.
- The configured boot script cold-started a stopped host, preserved saved state, and was idempotent. The field page returned HTTP 200 afterward.
- Saved active-job/JU state stayed unchanged in the restart test.
- Java compiled, APK signature verified, and the update certificate matched the original APK.

Pending device acceptance: Android app update and Termux:Boot installation; battery exemption and RUN_COMMAND permission; real phone reboot and app UI checks. Script-level boot tests do not prove Android delivered a boot broadcast.

No process can run with the phone powered off. Android Force stop explicitly disables an app until it is opened again. This setup provides recovery, not an absolute uptime guarantee.

Status: devco-host status. Logs: $PREFIX/var/log/sv/devco/current and $PREFIX/var/log/sv/devco-watchdog/current.
