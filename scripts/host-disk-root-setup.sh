#!/usr/bin/env bash
# One-time installer for the weekly root disk cleanup (TASK-7646). Run by the owner:
#   sudo bash scripts/host-disk-root-setup.sh            # install, then clean once now
#   sudo bash scripts/host-disk-root-setup.sh --uninstall
# Copies host_disk_root.py to a root-owned path outside the repo (the repo stays
# user-writable), caps the systemd journal at 1 GiB, sets Docker's default log
# rotation (without restarting Docker) and installs a weekly timer.
# Re-run after reviewing changes to scripts/host_disk_root.py.
set -euo pipefail

TOOL_DEST="/usr/local/sbin/openmates-host-disk-root"
UNIT_DIR="/etc/systemd/system"
JOURNALD_DROPIN="/etc/systemd/journald.conf.d/openmates-size.conf"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/host_disk_root.py"

if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root: sudo bash scripts/host-disk-root-setup.sh" >&2
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now openmates-host-disk-root.timer 2>/dev/null || true
    rm -f "$UNIT_DIR/openmates-host-disk-root.timer" "$UNIT_DIR/openmates-host-disk-root.service" \
        "$TOOL_DEST" "$JOURNALD_DROPIN"
    if [ -f /etc/docker/daemon.json.before-openmates-host-disk ]; then
        mv -f /etc/docker/daemon.json.before-openmates-host-disk /etc/docker/daemon.json
        echo "Restored /etc/docker/daemon.json (active after the next Docker restart)"
    fi
    systemctl daemon-reload
    systemctl restart systemd-journald
    echo "Removed the weekly root disk cleanup."
    exit 0
fi
if [ $# -gt 0 ]; then
    echo "Unknown argument: $1" >&2
    exit 2
fi
if [ ! -f "$SRC" ]; then
    echo "Tool source not found: $SRC" >&2
    exit 1
fi

TMP_TOOL="$(mktemp /usr/local/sbin/.openmates-host-disk-root.XXXXXX)"
trap 'rm -f "$TMP_TOOL"' EXIT
install -m 0755 -o root -g root "$SRC" "$TMP_TOOL"
mv -f "$TMP_TOOL" "$TOOL_DEST"
echo "Installed $TOOL_DEST (sha256 $(sha256sum "$TOOL_DEST" | cut -d' ' -f1))"

mkdir -p "$(dirname "$JOURNALD_DROPIN")"
printf '[Journal]\nSystemMaxUse=1G\n' > "$JOURNALD_DROPIN"
systemctl restart systemd-journald
echo "Capped the systemd journal at 1 GiB ($JOURNALD_DROPIN)"

# Default log rotation for containers created from now on: 3 x 10 MB each, so ~35
# containers stay near the 1 GB container-log budget. Merged into daemon.json and
# validated first; Docker is NOT restarted here (that would restart every
# container): it applies after the next Docker restart or host reboot, and to each
# container recreated after that. The weekly run truncates logs meanwhile.
DAEMON_JSON="/etc/docker/daemon.json"
TMP_DAEMON="$(mktemp /etc/docker/.daemon.json.XXXXXX)"
trap 'rm -f "$TMP_TOOL" "$TMP_DAEMON"' EXIT
/usr/bin/python3 -I -c '
import json, sys
path, out = sys.argv[1], sys.argv[2]
try:
    config = json.load(open(path))
except FileNotFoundError:
    config = {}
config.setdefault("log-driver", "json-file")
if config["log-driver"] == "json-file":
    config.setdefault("log-opts", {}).update({"max-size": "10m", "max-file": "3"})
json.dump(config, open(out, "w"), indent=2)
' "$DAEMON_JSON" "$TMP_DAEMON"
if dockerd --validate --config-file "$TMP_DAEMON" >/dev/null 2>&1; then
    [ -f "$DAEMON_JSON" ] && cp -p "$DAEMON_JSON" "$DAEMON_JSON.before-openmates-host-disk"
    install -m 0644 -o root -g root "$TMP_DAEMON" "$DAEMON_JSON"
    echo "Docker default log rotation set in $DAEMON_JSON (active after the next Docker restart)"
else
    echo "WARNING: merged $DAEMON_JSON did not validate; left unchanged:" >&2
    dockerd --validate --config-file "$TMP_DAEMON" >&2 || true
fi

cat > "$UNIT_DIR/openmates-host-disk-root.service" <<EOF
[Unit]
Description=OpenMates weekly root disk cleanup (orphaned Docker layers, container logs, journal)
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I $TOOL_DEST apply
Nice=10
IOSchedulingClass=idle
EOF
cat > "$UNIT_DIR/openmates-host-disk-root.timer" <<'EOF'
[Unit]
Description=Run the OpenMates root disk cleanup weekly

[Timer]
OnCalendar=Sun *-*-* 03:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now openmates-host-disk-root.timer
echo "Enabled openmates-host-disk-root.timer (Sundays 03:30 UTC)"

echo "Running the cleanup once now:"
df -h / | tail -1
/usr/bin/python3 -I "$TOOL_DEST" apply
df -h / | tail -1
