#!/usr/bin/env bash
# Installs a user systemd timer that runs `status_server.py watch` every 5 minutes:
# the dev server alerts (Discord + email, same escalation as the status server)
# when status.openmates.org is unreachable or its data is stale. Until the
# status server is deployed, each run exits quietly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/status-server-watch.service" <<UNIT
[Unit]
Description=OpenMates dev-server cross-check of status.openmates.org

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=3min
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/status_server.py watch
UNIT

cat > "$SYSTEMD_DIR/status-server-watch.timer" <<UNIT
[Unit]
Description=Cross-check status.openmates.org every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now status-server-watch.timer
systemctl --user status status-server-watch.timer --no-pager
