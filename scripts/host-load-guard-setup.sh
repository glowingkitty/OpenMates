#!/bin/bash
# Install the systemd user timer that samples host load once a minute and logs
# overload events (with the top RSS process groups) to
# <canonical checkout>/logs/host-load-guard/events.jsonl. It never kills or
# pauses anything; hooks read the same hysteresis state. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-host-load-guard.service" <<UNIT
[Unit]
Description=OpenMates host load sample (log only)

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=30s
ExecStart=/usr/bin/python3 -I -S $PROJECT_ROOT/scripts/host_load_guard.py monitor
UNIT

cat > "$SYSTEMD_DIR/openmates-host-load-guard.timer" <<UNIT
[Unit]
Description=Sample OpenMates dev host load every minute

[Timer]
OnBootSec=1min
OnStartupSec=1min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-host-load-guard.timer
systemctl --user status openmates-host-load-guard.timer --no-pager | head -5
