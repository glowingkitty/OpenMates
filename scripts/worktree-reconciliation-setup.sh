#!/usr/bin/env bash
# =============================================================================
# OpenMates Agent Worktree Reconciliation Timer Installer
#
# Installs a user-level systemd oneshot and hourly timer on the dev machine.
# The job first integrates current eligible checkpoints through normal deploy
# gates, then safely reconciles stale worktrees. Legacy state is never merged.
# Run manually after deploying lifecycle changes to the root control plane.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/worktree-reconciliation.service" <<EOF
[Unit]
Description=OpenMates agent worktree reconciliation

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
ExecStart=/bin/bash -lc 'git fetch origin dev || exit; auto_status=0; /usr/bin/python3 $PROJECT_ROOT/scripts/sessions.py worktree auto-integrate || auto_status=\$?; reconcile_status=0; /usr/bin/python3 $PROJECT_ROOT/scripts/sessions.py worktree reconcile --target origin/dev --idle-hours 48 --apply-safe || reconcile_status=\$?; if [ "\$reconcile_status" -ne 0 ]; then exit "\$reconcile_status"; fi; exit "\$auto_status"'
EOF

cat > "$SYSTEMD_DIR/worktree-reconciliation.timer" <<EOF
[Unit]
Description=Reconcile OpenMates agent worktrees hourly

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now worktree-reconciliation.timer
systemctl --user status worktree-reconciliation.timer --no-pager
