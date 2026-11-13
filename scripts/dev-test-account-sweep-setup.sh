#!/usr/bin/env bash
# Installs a user systemd timer that hourly runs `dev_test_account.py sweep`:
# stale throwaway dev test accounts are deleted, test-chat backups older than
# 7 days are removed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/dev-test-account-sweep.service" <<UNIT
[Unit]
Description=OpenMates throwaway dev test account sweep

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=30min
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/dev_test_account.py sweep
UNIT

cat > "$SYSTEMD_DIR/dev-test-account-sweep.timer" <<UNIT
[Unit]
Description=Sweep throwaway dev test accounts hourly

[Timer]
OnBootSec=15min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now dev-test-account-sweep.timer
systemctl --user status dev-test-account-sweep.timer --no-pager
