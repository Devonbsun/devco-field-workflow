#!/data/data/com.termux/files/usr/bin/bash
set -eu
ROOT="$HOME/DEVCO_FIELD"
export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export SVDIR="$PREFIX/var/service"
command -v sv >/dev/null || { echo "Install termux-services first."; exit 1; }
for service in devco devco-watchdog; do
  mkdir -p "$SVDIR/$service/log" "$PREFIX/var/log/sv/$service"
  if [ ! -f "$SVDIR/$service/run" ]; then touch "$SVDIR/$service/down"; fi
  script=devco_app.py
  [ "$service" = devco ] || script=host_watchdog.py
  cat > "$SVDIR/$service/run" <<EOF
#!$PREFIX/bin/sh
export HOME="$HOME"
export PREFIX="$PREFIX"
export PATH="$PREFIX/bin:/system/bin"
cd "$ROOT"
exec 2>&1
exec "$PREFIX/bin/python" -u "$ROOT/SYSTEM/$script"
EOF
  cat > "$SVDIR/$service/log/run" <<EOF
#!$PREFIX/bin/sh
exec "$PREFIX/bin/svlogd" -tt "$PREFIX/var/log/sv/$service"
EOF
  printf 's1048576\nn5\n' > "$PREFIX/var/log/sv/$service/config"
  chmod 700 "$SVDIR/$service/run" "$SVDIR/$service/log/run"
done
chmod 700 "$ROOT/SYSTEM/devco-host" "$ROOT/SYSTEM/devco-app"
ln -sf "$ROOT/SYSTEM/devco-host" "$PREFIX/bin/devco-host"
ln -sf "$ROOT/SYSTEM/devco-app" "$PREFIX/bin/devco-app"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/20-devco-host" <<EOF
#!$PREFIX/bin/bash
exec "$ROOT/SYSTEM/devco-host" ensure
EOF
chmod 700 "$HOME/.termux/boot/20-devco-host"
# This also repairs the currently installed older app, whose -lc startup
# loads profile.d before its faulty pgrep check.
cat > "$PREFIX/etc/profile.d/devco-host.sh" <<'EOF'
if [ -x "$HOME/DEVCO_FIELD/SYSTEM/devco-host" ]; then
  "$HOME/DEVCO_FIELD/SYSTEM/devco-host" ensure >/dev/null 2>&1 &
fi
EOF
service-daemon start >/dev/null 2>&1 || true
sv-enable devco
sv-enable devco-watchdog
bash "$ROOT/SYSTEM/install_directory.sh"
"$ROOT/SYSTEM/devco-host" ensure
echo "DEVCO recovery enabled. Boot startup also requires Termux:Boot installed and opened once."
