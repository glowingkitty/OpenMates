#!/usr/bin/env bash
# Install the dev-host watchdog alongside the existing chat lifecycle timer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
UNIT_NAME=openmates-chat-recovery-watchdog

mkdir -p "$SYSTEMD_DIR"
cat > "$SYSTEMD_DIR/$UNIT_NAME.service" <<UNIT
[Unit]
Description=Recover stalled Claude and Codex work chats

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=10min
ExecStart=/usr/bin/python3 -I -S $PROJECT_ROOT/scripts/chat_recovery_watchdog.py
UNIT

cat > "$SYSTEMD_DIR/$UNIT_NAME.timer" <<UNIT
[Unit]
Description=Check for stalled work chats every minute

[Timer]
OnCalendar=*:0/1
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME.timer"
systemctl --user list-timers --all "$UNIT_NAME.timer" --no-pager
