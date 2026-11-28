#!/bin/bash
# Install the systemd user timers of the worktree WIP safety (scripts/worktree_wip.py):
#   openmates-worktree-wip-sweep.timer    every 30 minutes: snapshot every dirty session
#                                         worktree to refs/openmates/wip/<session> and write
#                                         logs/worktree-wip/status.json (read by the chat lifecycle)
#   openmates-worktree-readiness.timer    nightly 02:30 UTC: sweep, run the dev->main release-readiness
#                                         gate (logs/worktree-wip/readiness.json, shown in the daily
#                                         meeting) and resume stopped owner chats of unfinished work.
# Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
USER_PATH="$HOME/.npm-global/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-worktree-wip-sweep.service" <<UNIT
[Unit]
Description=Worktree WIP safety: snapshot dirty session worktrees

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=10min
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/worktree_wip.py recover
UNIT

cat > "$SYSTEMD_DIR/openmates-worktree-wip-sweep.timer" <<UNIT
[Unit]
Description=Snapshot dirty worktrees and recover stopped owners every 30 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=30min
AccuracySec=2min

[Install]
WantedBy=timers.target
UNIT

cat > "$SYSTEMD_DIR/openmates-worktree-readiness.service" <<UNIT
[Unit]
Description=Nightly dev->main worktree readiness check and owner wake-ups

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
Environment=PATH=$USER_PATH
TimeoutStartSec=45min
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/worktree_wip.py nightly
UNIT

cat > "$SYSTEMD_DIR/openmates-worktree-readiness.timer" <<UNIT
[Unit]
Description=Run the worktree readiness check every night

[Timer]
OnCalendar=*-*-* 02:30:00 UTC
Persistent=true
AccuracySec=5min

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-worktree-wip-sweep.timer openmates-worktree-readiness.timer
systemctl --user list-timers --no-pager | grep -E "worktree-(wip|readiness)" || true
