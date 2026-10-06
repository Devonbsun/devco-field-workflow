#!/data/data/com.termux/files/usr/bin/bash
set -eu
repo_path="$HOME/DEVCO_FIELD"
termux_prefix="/data/data/com.termux/files/usr"
service_path="$termux_prefix/var/service/devco-files"
mkdir -p "$service_path/log" "$termux_prefix/var/log/sv/devco-files"
cat > "$service_path/run" <<EOF
#!$termux_prefix/bin/sh
cd "$repo_path"
exec 2>&1
exec "$termux_prefix/bin/python" -u "$repo_path/SYSTEM/project_directory.py" --watch
EOF
cat > "$service_path/log/run" <<EOF
#!$termux_prefix/bin/sh
exec "$termux_prefix/bin/svlogd" -tt "$termux_prefix/var/log/sv/devco-files"
EOF
printf 's1048576\nn3\n' > "$termux_prefix/var/log/sv/devco-files/config"
chmod 700 "$service_path/run" "$service_path/log/run"
chmod 700 "$repo_path/SYSTEM/devco-files"
ln -sfn "$repo_path/SYSTEM/devco-files" "$termux_prefix/bin/devco-files"
service-daemon start >/dev/null 2>&1 || true
SVDIR="$termux_prefix/var/service" sv-enable devco-files
