#!/usr/bin/env bash
# One-time installer for the weekly root disk cleanup (TASK-7646). Run by the owner:
#   sudo bash scripts/host-disk-root-setup.sh            # install, then clean once now
#   sudo bash scripts/host-disk-root-setup.sh --uninstall
# Copies host_disk_root.py to a root-owned path outside the repo (the repo stays
# user-writable), caps the systemd journal at 1 GiB and installs a weekly timer.
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
