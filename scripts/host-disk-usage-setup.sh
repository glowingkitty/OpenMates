#!/usr/bin/env bash
# Installs the hourly disk size log (scripts/host_disk_usage.py record) as a
# systemd user timer. Run as the dev user: bash scripts/host-disk-usage-setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-host-disk-usage.service" <<UNIT
[Unit]
Description=OpenMates hourly disk size log per category

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=30min
Nice=19
IOSchedulingClass=idle
ExecStart=/usr/bin/python3 -I $PROJECT_ROOT/scripts/host_disk_usage.py record
UNIT

cat > "$SYSTEMD_DIR/openmates-host-disk-usage.timer" <<UNIT
[Unit]
Description=Measure OpenMates dev host disk use every hour

[Timer]
OnBootSec=5min
OnCalendar=hourly
RandomizedDelaySec=2min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-host-disk-usage.timer
systemctl --user status openmates-host-disk-usage.timer --no-pager | head -5
