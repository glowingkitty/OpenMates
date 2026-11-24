#!/usr/bin/env bash
# Installs the user systemd timer that runs the dev voice check after new dev deploys.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/voice-post-update-check.service" <<UNIT
[Unit]
Description=OpenMates real voice-call check after dev deploys

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=2h
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/voice_post_update_check.py dev-watch
UNIT

cat > "$SYSTEMD_DIR/voice-post-update-check.timer" <<UNIT
[Unit]
Description=Look for a new dev revision every 5 minutes and run the voice check

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now voice-post-update-check.timer
systemctl --user status voice-post-update-check.timer --no-pager
