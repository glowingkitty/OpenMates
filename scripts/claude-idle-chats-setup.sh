#!/bin/bash
# Install the systemd user timer that closes Claude chat processes idle for
# more than 3 hours (scripts/claude_idle_chats.py reap), every 30 minutes.
# Closed chats keep their transcript; events go to
# <canonical checkout>/logs/claude-idle-chats/events.jsonl. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-claude-idle-chats.service" <<UNIT
[Unit]
Description=Claude chat lifecycle: stop idle chats, enforce the running-chat cap, write counts

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=15min
ExecStart=/usr/bin/python3 -I -S $PROJECT_ROOT/scripts/claude_idle_chats.py reap
UNIT

cat > "$SYSTEMD_DIR/openmates-claude-idle-chats.timer" <<UNIT
[Unit]
Description=Run the Claude chat lifecycle every minute (a finished turn frees its slot within minutes)

[Timer]
OnBootSec=5min
OnActiveSec=1min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-claude-idle-chats.timer
systemctl --user restart openmates-claude-idle-chats.timer
systemctl --user status openmates-claude-idle-chats.timer --no-pager | head -5
