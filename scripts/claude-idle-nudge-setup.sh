#!/bin/bash
# Install the systemd user timer that wakes Claude chats which stopped with work still owed
# (scripts/claude_idle_nudge.py nudge), every 10 minutes. Decisions go to
# <canonical checkout>/logs/claude-idle-chats/events.jsonl. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-claude-idle-nudge.service" <<UNIT
[Unit]
Description=Wake idle Claude chats that still owe work

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=15min
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/claude_idle_nudge.py nudge
UNIT

cat > "$SYSTEMD_DIR/openmates-claude-idle-nudge.timer" <<UNIT
[Unit]
Description=Wake idle Claude chats every 10 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=10min
AccuracySec=1min

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-claude-idle-nudge.timer
systemctl --user status openmates-claude-idle-nudge.timer --no-pager | head -5
