#!/usr/bin/env bash
# =============================================================================
# OpenMates Agent Worktree Reconciliation Timer Installer
#
# Installs a user-level systemd oneshot and hourly timer on the dev machine.
# The job first enforces the unconditional 72-hour hard lifetime without a
# network dependency, then integrates current eligible checkpoints and safely
# reconciles younger worktrees. Legacy state is never merged.
# Run manually after deploying lifecycle changes to the root control plane.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/worktree-reconciliation.service" <<EOF
[Unit]
Description=OpenMates agent worktree reconciliation

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
RuntimeMaxSec=50min
Nice=10
ExecStart=/bin/bash -lc 'expire_status=0; /usr/bin/python3 $PROJECT_ROOT/scripts/sessions.py worktree expire --max-age-hours 72 || expire_status=\$?; fetch_status=0; git fetch origin dev || fetch_status=\$?; auto_status=0; if [ "\$fetch_status" -eq 0 ]; then /usr/bin/python3 $PROJECT_ROOT/scripts/sessions.py worktree auto-integrate || auto_status=\$?; fi; reconcile_status=0; if [ "\$fetch_status" -eq 0 ]; then /usr/bin/python3 $PROJECT_ROOT/scripts/sessions.py worktree reconcile --target origin/dev --idle-hours 48 --apply-safe || reconcile_status=\$?; fi; if [ "\$expire_status" -ne 0 ]; then exit "\$expire_status"; fi; if [ "\$reconcile_status" -ne 0 ]; then exit "\$reconcile_status"; fi; if [ "\$fetch_status" -ne 0 ]; then exit "\$fetch_status"; fi; exit "\$auto_status"'
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
